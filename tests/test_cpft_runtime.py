"""Batched CPFT features and inference reproduce the row-by-row reference."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from backend.cpft_runtime import hourly_observations, input_windows
from backend.scenario_sampling import ScenarioSession
from backend.session_frame import SessionFrame
from scripts.evaluate_cpft_models import AVAIL_COLS, ENERGY_COLS, causal_input_rows, feature_row, observations_at_issue
from .cpft_helpers import require_tensorflow

UTC = timezone.utc
ISSUE = datetime(2026, 10, 14, 16, tzinfo=UTC)
BOUNDS = {"kWhDelivered": [-3.98, 5.53], "connected_minutes": [-58.98, 109.53]}


def random_sessions(points, seed=3):
    rng = np.random.default_rng(seed)
    rows = []
    for cp_id in points:
        moment = ISSUE-timedelta(days=12)
        while moment < ISSUE+timedelta(hours=6):
            moment += timedelta(minutes=int(rng.integers(15, 2000)))
            # Microsecond ends, as produced by timedelta(hours=float) sessions
            end = moment+timedelta(hours=float(rng.uniform(.25, 30)))
            rows.append((cp_id, moment, end, float(rng.uniform(0, 40))))
            moment = end
    return rows


def reference_frame(rows):
    frame = pd.DataFrame([dict(connectionTime=start, disconnectTime=end, chargeEndTime=end, kWhDelivered=energy)
                          for _, start, end, energy in rows], columns=["connectionTime", "disconnectTime", "chargeEndTime", "kWhDelivered"])
    for column in ["connectionTime", "disconnectTime", "chargeEndTime"]:
        frame[column] = pd.to_datetime(frame[column], utc=True)
    return frame


def test_batched_observations_and_input_rows_match_reference():
    points = [7, 8, 9]
    rows = random_sessions(points)
    frame = SessionFrame.from_records([ScenarioSession(*row) for row in rows])
    index = np.searchsorted(points, frame.cp_id)
    batched = hourly_observations(frame, index, len(points), ISSUE.timestamp(), 240)
    columns, _ = input_windows(batched, BOUNDS, 72, ISSUE.timestamp())
    for position, cp_id in enumerate(points):
        reference = observations_at_issue(reference_frame([row for row in rows if row[0] == cp_id]), ISSUE, 240)
        # Float epoch seconds resolve ~0.2 microseconds; the reference uses integer nanoseconds
        for name in reference:
            np.testing.assert_allclose(batched[name][position], reference[name].to_numpy(), rtol=1e-8, atol=1e-7)
        expected, _ = causal_input_rows(reference, BOUNDS, 72)
        for name in set(AVAIL_COLS) | set(ENERGY_COLS):
            actual = np.broadcast_to(columns[name], columns["availability"].shape)[position]
            np.testing.assert_allclose(actual, expected[name].to_numpy(float), rtol=1e-8, atol=1e-7, err_msg=name)


def test_batched_recursive_forecast_matches_reference_loop():
    require_tensorflow()
    from backend.cpft_runtime import get_runtime
    from scripts.evaluate_cpft_models import scale_availability, scale_energy
    runtime = get_runtime()
    points, powers, horizon = [11, 12, 13, 14], np.array([11., 3.7, 22., 50.]), 30
    rows = [row for row in random_sessions(points, seed=5) if row[1] < ISSUE]
    frame = SessionFrame.from_records([ScenarioSession(*row) for row in rows])
    probability, occupied, energy = runtime.forecast(frame, points, powers, int(ISSUE.timestamp()), horizon)
    # The pre-batching implementation, point by point
    for position, cp_id in enumerate(points):
        observed = observations_at_issue(reference_frame([row for row in rows if row[0] == cp_id]), ISSUE, 240)
        inputs, history = causal_input_rows(observed, runtime.bounds, 72)
        av, en = scale_availability(inputs, runtime.scaler_av)[None], scale_energy(inputs, runtime.scaler_energy)[None]
        av_history, energy_history = history.availability.to_numpy(), history.kWhDelivered.to_numpy()
        for lead in range(horizon):
            p = float(runtime.predict_av(av).numpy().reshape(-1)[0])
            o = p >= runtime.threshold
            e = min(max(0., float(np.expm1(runtime.predict_energy(en).numpy().reshape(-1)[0]))) if o else 0., powers[position])
            assert probability[position, lead] == pytest.approx(p, abs=1e-6)
            assert occupied[position, lead] == o
            assert energy[position, lead] == pytest.approx(e, rel=1e-5, abs=1e-6)
            feedback = float(np.clip(e, *runtime.bounds["kWhDelivered"]))
            row = pd.DataFrame([feature_row(ISSUE+timedelta(hours=lead), av_history, energy_history, o, feedback,
                float(o)*runtime.proxies["occupancy_count"], float(o)*runtime.proxies["connected_minutes"])])
            av = np.concatenate([av[:, 1:], scale_availability(row, runtime.scaler_av)[:, None]], axis=1)
            en = np.concatenate([en[:, 1:], scale_energy(row, runtime.scaler_energy)[:, None]], axis=1)
            av_history = np.append(av_history, float(o))
            energy_history = np.append(energy_history, feedback)
