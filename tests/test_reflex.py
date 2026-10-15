"""The ReFlex transport: submission, parallel polling, deadlines and clean-up; no network."""

import pytest
import requests

from backend.api_calls.reflex import ReflexClient, ReflexError, ReflexTimeout


class Response:
    def __init__(self, data=None, status=200):
        self.data, self.status_code = data, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return self.data


class Service:
    """Runs finish after `polls` status requests; records every call."""

    def __init__(self, polls=1, status="completed"):
        self.polls, self.final = polls, status
        self.calls, self.seen, self.runs = [], {}, 0

    def request(self, method, url, timeout=None, headers=None, json=None):
        path = url.split("/services", 1)[1]
        self.calls.append((method, path))
        if method == "POST":
            self.runs += 1
            return Response({"id": f"run-{self.runs}"})
        run = path.rsplit("/", 1)[1]
        if method == "DELETE":
            return Response(status=202)
        if path.startswith("/run/info/"):
            self.seen[run] = self.seen.get(run, 0)+1
            return Response({"runStatus": self.final if self.seen[run] >= self.polls else "running"})
        return Response({"devicePlans": {run: [1, 2]}})


class Clock:
    def __init__(self):
        self.now = 0.

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def client(service, clock=None, timeout=120):
    clock = clock or Clock()
    return ReflexClient("https://reflex.test/services", transport=service, run_timeout=timeout,
                        clock=clock, sleep=clock.sleep)


def test_one_run_returns_its_results_and_is_deleted():
    service = Service(polls=2)
    assert client(service).run({"q": 1}) == {"devicePlans": {"run-1": [1, 2]}}
    assert service.calls == [("POST", "/run/single"), ("GET", "/run/info/run-1"), ("GET", "/run/info/run-1"),
                             ("GET", "/run/results/run-1"), ("DELETE", "/run/run-1")]


def test_many_runs_keep_a_bounded_number_in_flight():
    service = Service(polls=3)
    finished = []
    in_flight = []

    def track(method, url, **kwargs):
        response = Service.request(service, method, url, **kwargs)
        posts = sum(call[0] == "POST" for call in service.calls)
        deletes = sum(call[0] == "DELETE" for call in service.calls)
        in_flight.append(posts-deletes)
        return response

    service.request = track
    client(service).run_many([{}]*7, lambda index, result: finished.append(index), parallel=3)
    assert sorted(finished) == list(range(7))
    assert max(in_flight) == 3


def test_a_deadline_keeps_finished_runs_and_cancels_the_rest():
    service = Service(polls=10**6)
    clock = Clock()
    finished = []
    with pytest.raises(ReflexTimeout, match="finished part is kept"):
        client(service, clock, timeout=5).run_many([{}]*2, lambda index, result: finished.append(index))
    assert finished == []
    assert sorted(path for method, path in service.calls if method == "DELETE") == ["/run/run-1", "/run/run-2"]


def test_a_failed_run_is_an_error():
    with pytest.raises(ReflexError, match="failed"):
        client(Service(status="failed")).run({})


def test_http_errors_name_the_call_not_the_body():
    class Down(Service):
        def request(self, method, url, **kwargs):
            return Response(status=503)
    with pytest.raises(ReflexError, match=r"POST /run/single failed: HTTP 503"):
        client(Down()).run({})


def test_settings_must_be_positive():
    with pytest.raises(ValueError):
        ReflexClient(run_timeout=0)
