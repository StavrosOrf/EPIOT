"""Transport for the DRIVE2X ReFlex Insights service (OpenAPI 0.3.0).

The request and result contracts live in backend/cost_charging.py; this module
only submits runs, waits for them and fetches their device plans.
"""

import math
import os
import time
from urllib.parse import quote

import requests

DEFAULT_BASE_URL = "https://drive2x-reflex.hesi.energy/services"


class ReflexError(RuntimeError):
    """The service failed or returned a result EPIOT cannot use."""


class ReflexTimeout(ReflexError):
    """A submitted run did not finish within the polling deadline."""


class ReflexClient:
    """Bounded, TLS-verified API calls. No automatic retries of run submission.

    REFLEX_BASE_URL overrides the default endpoint. Requests also supports
    REQUESTS_CA_BUNDLE for installations using a project-specific CA.
    """

    def __init__(self, base_url=None, *, request_timeout=30, run_timeout=120,
                 poll_interval=1, transport=None, clock=None, sleep=None):
        self.base_url = (base_url or os.environ.get("REFLEX_BASE_URL")
                         or DEFAULT_BASE_URL).rstrip("/")
        for name, value in (("request_timeout", request_timeout),
                            ("run_timeout", run_timeout), ("poll_interval", poll_interval)):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        self.request_timeout = request_timeout
        self.run_timeout = run_timeout
        self.poll_interval = poll_interval
        self.transport = requests if transport is None else transport
        self.clock = time.monotonic if clock is None else clock
        self.sleep = time.sleep if sleep is None else sleep

    def _request(self, method, path, *, timeout=None, parse=True, **kwargs):
        try:
            response = self.transport.request(
                method, self.base_url + path,
                timeout=self.request_timeout if timeout is None else timeout,
                headers={"Accept": "application/json"}, **kwargs,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            detail = f"HTTP {status}" if status is not None else type(exc).__name__
            raise ReflexError(f"ReFlex {method} {path} failed: {detail}") from exc
        if not parse:
            return None
        try:
            data = response.json()
        except ValueError as exc:
            raise ReflexError(f"ReFlex {method} {path} returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ReflexError(f"ReFlex {method} {path} must return a JSON object")
        return data

    def submit(self, query):
        run_id = self._request("POST", "/run/single", json=query).get("id")
        if not isinstance(run_id, str) or not run_id.strip():
            raise ReflexError("ReFlex submission did not return a run id")
        return run_id

    def status(self, run_id, timeout=None):
        return self._request("GET", f"/run/info/{quote(run_id, safe='')}", timeout=timeout).get("runStatus")

    def results(self, run_id):
        return self._request("GET", f"/run/results/{quote(run_id, safe='')}")

    def delete(self, run_id):
        """Remove a finished run, or cancel a waiting one; the instance is shared."""
        try:
            self._request("DELETE", f"/run/{quote(run_id, safe='')}", parse=False)
        except ReflexError:
            pass

    def run(self, query):
        """Submit one run and return its results."""
        results = {}
        self.run_many([query], lambda index, result: results.setdefault(index, result))
        return results[0]

    def run_many(self, queries, on_result, *, parallel=8):
        """Run every query, at most `parallel` at a time, polling them together.

        `on_result(index, results)` is called as each run completes, so the work
        already done is kept when a later run fails or the deadline passes. The
        deadline covers all runs. Runs still waiting at the end are cancelled.
        """
        waiting = list(range(len(queries)))
        pending = {}
        try:
            deadline = self.clock()+self.run_timeout
            while waiting or pending:
                while waiting and len(pending) < parallel:
                    index = waiting.pop(0)
                    pending[index] = self.submit(queries[index])
                for index, run_id in list(pending.items()):
                    remaining = deadline-self.clock()
                    if remaining <= 0:
                        raise ReflexTimeout(
                            f"ReFlex did not finish {len(pending)+len(waiting)} of {len(queries)} runs within "
                            f"{self.run_timeout:g} s. The service is shared and may be busy; the finished part "
                            "is kept, so a retry continues from there.")
                    status = self.status(run_id, timeout=min(self.request_timeout, remaining))
                    if status == "completed":
                        result = self.results(run_id)
                        del pending[index]
                        self.delete(run_id)
                        on_result(index, result)
                    elif status in {"failed", "cancelled"}:
                        del pending[index]
                        self.delete(run_id)
                        raise ReflexError(f"ReFlex run {run_id} {status}")
                    elif status not in {"submitted", "running"}:
                        raise ReflexError(f"ReFlex run {run_id} returned an unknown runStatus")
                if pending and not (waiting and len(pending) < parallel):
                    self.sleep(min(self.poll_interval, max(0, deadline-self.clock())))
        finally:
            for run_id in pending.values():
                self.delete(run_id)
