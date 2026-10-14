"""ReFlex request, transport and result contracts for EPIOT's 48-hour grid."""

from datetime import datetime, timedelta, timezone
import math
import os
import time
from urllib.parse import quote

import numpy as np
import requests

DEFAULT_BASE_URL = "https://drive2x-reflex.hesi.energy/services"
PROFILE_STEPS = 288
STEP_SECONDS = 600


class ReflexError(RuntimeError):
    """The service failed or returned a result EPIOT cannot use."""


class ReflexTimeout(ReflexError):
    """A submitted run did not finish within the polling deadline."""


def _utc(value):
    # Existing EPIOT database rows are naive. Preserve the legacy UTC assumption;
    # timezone-aware inputs are converted rather than merely relabelled with Z.
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def create_ReFlex_Query(chargers, charging_sessions, prices, start_date):
    """Convert (cp_id, start, end, kWh) rows and kW ratings to ReFlex W/J.

    The horizon is 288 ten-minute intervals starting at UTC midnight. Availability
    is the plugged-in fraction of each interval. Sessions wholly outside the
    horizon are ignored; partially covered sessions are rejected because their
    in-window energy demand is unknown.
    """
    start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = start + timedelta(seconds=PROFILE_STEPS * STEP_SECONDS)
    prices = np.asarray(prices, dtype=float)
    if prices.shape != (PROFILE_STEPS,) or not np.isfinite(prices).all():
        raise ValueError("ReFlex requires 288 finite ten-minute prices")
    result = {
        "runType": "singleRunConfig",
        "congestionPoints": [],
        "globalTarget": {
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "timeStepDuration": "PT10M",
            "elements": [{"targetType": "price", "value": float(p)} for p in prices],
        },
        "assets": {"evChargePoints": [], "nonFlexibleAssets": []},
    }
    points, availability, windows = {}, {}, {}
    steps = np.arange(PROFILE_STEPS) * STEP_SECONDS
    for cp_id, arrival, departure, energy in charging_sessions:
        arrival, departure = _utc(arrival), _utc(departure)
        energy = float(energy)
        if departure <= arrival or not math.isfinite(energy) or energy < 0:
            raise ValueError("Sessions require increasing times and finite nonnegative kWh")
        if departure <= start or arrival >= end:
            continue
        if arrival < start or departure > end:
            raise ValueError("Session crosses the ReFlex horizon; in-window energy is unknown")
        power = chargers[cp_id]
        power = 11.0 if power is None or power <= 0 else float(power)
        if not math.isfinite(power):
            raise ValueError("Charger power must be finite")
        if cp_id not in points:
            points[cp_id] = {
                "id": str(cp_id), "minChargePower": 0,
                "maxChargePower": int(power * 1000), "chargeSessions": [],
            }
            availability[cp_id] = np.zeros(PROFILE_STEPS)
            windows[cp_id] = []
        if any(arrival < b and departure > a for a, b in windows[cp_id]):
            raise ValueError(f"Overlapping sessions for charge point {cp_id}")
        windows[cp_id].append((arrival, departure))
        points[cp_id]["chargeSessions"].append({
            "startTime": arrival.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endTime": departure.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "energyToCharge": round(energy * 3.6e6),
        })
        a = (arrival - start).total_seconds()
        b = (departure - start).total_seconds()
        availability[cp_id] += np.maximum(0, np.minimum(steps + STEP_SECONDS, b)
                                           - np.maximum(steps, a)) / STEP_SECONDS
    result["assets"]["evChargePoints"] = list(points.values())
    return result, availability


class ReflexClient:
    """Bounded, TLS-verified API calls. No automatic retries of run submission.

    REFLEX_BASE_URL overrides the historical EPIOT endpoint. Requests also
    supports REQUESTS_CA_BUNDLE for installations using a project-specific CA.
    """

    def __init__(self, base_url=None, *, request_timeout=10, run_timeout=120,
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

    def _request(self, method, path, *, timeout=None, **kwargs):
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
        try:
            data = response.json()
        except ValueError as exc:
            raise ReflexError(f"ReFlex {method} {path} returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ReflexError(f"ReFlex {method} {path} must return a JSON object")
        return data

    def run(self, query):
        submitted = self._request("POST", "/run/single", json=query)
        run_id = submitted.get("id")
        if not isinstance(run_id, str) or not run_id.strip():
            raise ReflexError("ReFlex submission did not return a run id")
        path_id = quote(run_id, safe="")
        deadline = self.clock() + self.run_timeout
        while True:
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise ReflexTimeout(f"ReFlex run {run_id} exceeded {self.run_timeout}s; "
                                    "the remote run may still be queued or running")
            status = self._request("GET", f"/run/info/{path_id}",
                                   timeout=min(self.request_timeout, remaining)).get("runStatus")
            if status == "completed":
                return self._request("GET", f"/run/results/{path_id}")
            if status in {"failed", "cancelled"}:
                raise ReflexError(f"ReFlex run {run_id} {status}")
            if status not in {"submitted", "running"}:
                raise ReflexError(f"ReFlex run {run_id} returned an unknown runStatus")
            self.sleep(min(self.poll_interval, max(0, deadline - self.clock())))


def aggregate_reflex_results(query, availability, results):
    """Validate energy plans and return EPIOT load/up/down arrays in average kW.

    Flexibility is instantaneous power headroom, not a guarantee that energy
    targets remain feasible after a schedule change.
    """
    points = {p["id"]: p for p in query["assets"]["evChargePoints"]}
    plans = results.get("devicePlans")
    if not isinstance(plans, dict) or set(plans) != set(points):
        raise ReflexError("ReFlex devicePlans must contain exactly the requested charge points")
    fractions = {str(key): value for key, value in availability.items()}
    load, up, down = (np.zeros(PROFILE_STEPS) for _ in range(3))
    for key, values in plans.items():
        try:
            energy = np.asarray(values, dtype=float)
        except (TypeError, ValueError) as exc:
            raise ReflexError(f"ReFlex plan {key} must contain numeric joules") from exc
        if (energy.shape != (PROFILE_STEPS,) or not np.isfinite(energy).all()
                or (energy < 0).any()):
            raise ReflexError(f"ReFlex plan {key} requires 288 finite nonnegative joule values")
        power = energy / (STEP_SECONDS * 1000)
        limit = points[key]["maxChargePower"] / 1000 * fractions[key]
        # Integer-Joule output can differ by one Joule due to rounding.
        if (power > limit + 1 / (STEP_SECONDS * 1000)).any():
            raise ReflexError(f"ReFlex plan {key} exceeds charger power or plugged-in availability")
        load += power
        up += np.maximum(0, limit - power)
        down -= power
    return load.tolist(), up.tolist(), down.tolist()
