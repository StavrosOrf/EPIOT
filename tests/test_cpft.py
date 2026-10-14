"""CPFT integration contracts, not tests of a trained model's accuracy."""

from datetime import date, datetime, timedelta

import pytest

from backend.cpft import (
    UTC, adapt_cpft_output, day_window, predict_session_forecasts,
)
from .cpft_helpers import ISSUED, TARGET, StubPredictor, cpft_rows


def test_prediction_calls_every_point_with_its_history_and_the_next_local_day():
    predictor = StubPredictor()
    histories = {202: ["second history"], 101: ["first history"]}
    result = predict_session_forecasts(
        predictor, histories, run_id="run", target_date=TARGET,
        issued_at=ISSUED, model_version="v1",
    )
    assert [call["cp_id"] for call in predictor.calls] == [101, 202]
    assert [call["history"] for call in predictor.calls] == [histories[101], histories[202]]
    for call in predictor.calls:
        assert call["start"] == datetime(2026, 10, 13, 22, tzinfo=UTC)
        assert call["end"] == datetime(2026, 10, 14, 22, tzinfo=UTC)
    assert [p.cp_id for p in result.points] == [101, 202]
    assert result.points[0].sessions[0].energy_kwh == 5.0
    assert result.points[1].sessions == ()
    assert len(result.points[1].hours) == 24  # zero demand is still a forecast


@pytest.mark.parametrize("target,hours", [(date(2026, 3, 29), 23), (date(2026, 10, 25), 25)])
def test_dst_days_are_not_forced_to_24_hours(target, hours):
    start, end = day_window(target, "Europe/Amsterdam")
    rows = cpft_rows(start, end, {i: 1.0 for i in range(hours)})
    forecast = adapt_cpft_output(101, rows, target_date=target)
    assert len(forecast.hours) == hours
    assert len({h.timestamp for h in forecast.hours}) == hours
    assert forecast.sessions[0].end - forecast.sessions[0].start == timedelta(hours=hours)
    assert forecast.sessions[0].energy_kwh == hours


def test_groups_occupied_bins_conserves_energy_and_marks_unknown_boundaries():
    start, end = day_window(TARGET, "Europe/Amsterdam")
    rows = cpft_rows(start, end, {0: 1.0, 1: 2.0, 2: 3.0, 7: 0.0, 22: 4.0, 23: 5.0})
    result = adapt_cpft_output(101, reversed(rows), target_date=TARGET)
    assert [(s.start, s.end, s.energy_kwh) for s in result.sessions] == [
        (start, start + timedelta(hours=3), 6.0),
        (start + timedelta(hours=7), start + timedelta(hours=8), 0.0),
        (start + timedelta(hours=22), end, 9.0),
    ]
    assert [(s.start_censored, s.end_censored) for s in result.sessions] == [
        (True, False), (False, False), (False, True),
    ]
    assert sum(s.energy_kwh for s in result.sessions) == sum(h.energy_kwh for h in result.hours)
    # The first session spans midnight UTC and remains one connected interval.
    assert result.sessions[0].start.day != result.sessions[0].end.day


def test_accepts_explicit_offset_timestamps_and_normalizes_to_utc():
    start, end = day_window(TARGET, "Europe/Amsterdam")
    rows = cpft_rows(start, end)
    rows[0]["hour"] = "2026-10-14T00:00:00+02:00"
    assert adapt_cpft_output(101, rows, target_date=TARGET).hours[0].timestamp == start


@pytest.mark.parametrize("field,value", [
    ("availability_forecast_prob", -0.1),
    ("availability_forecast_prob", 1.1),
    ("availability_forecast_prob", float("nan")),
    ("availability_forecast_bin", 2),
    ("availability_forecast_bin", float("nan")),
    ("kWh_forecast_next_whole_period", -1),
    ("kWh_forecast_next_whole_period", float("inf")),
    ("kWh_forecast_next_whole_period", 4),  # energy in an unoccupied hour
    ("hour", "2026-10-13T22:00:00"),  # timezone-free export is ambiguous
])
def test_rejects_invalid_prediction_values(field, value):
    rows = cpft_rows(*day_window(TARGET, "Europe/Amsterdam"))
    rows[0][field] = value
    with pytest.raises(ValueError):
        adapt_cpft_output(101, rows, target_date=TARGET)


@pytest.mark.parametrize("change", ["missing", "duplicate", "shifted", "extra", "empty"])
def test_rejects_incomplete_or_wrong_forecast_horizons(change):
    rows = cpft_rows(*day_window(TARGET, "Europe/Amsterdam"))
    if change == "missing":
        rows.pop(8)
    elif change == "duplicate":
        rows[8] = rows[7].copy()
    elif change == "shifted":
        for row in rows:
            row["hour"] += timedelta(hours=1)
    elif change == "extra":
        rows.append({**rows[-1], "hour": rows[-1]["hour"] + timedelta(hours=1)})
    else:
        rows = []
    with pytest.raises(ValueError, match="complete target day"):
        adapt_cpft_output(101, rows, target_date=TARGET)


def test_rejects_missing_cpft_columns():
    rows = cpft_rows(*day_window(TARGET, "Europe/Amsterdam"))
    del rows[0]["availability_forecast_prob"]
    with pytest.raises(ValueError, match="Invalid CPFT record"):
        adapt_cpft_output(101, rows, target_date=TARGET)


def test_predictor_failure_does_not_return_a_partial_batch():
    class FailingPredictor(StubPredictor):
        def forecast(self, **kwargs):
            if kwargs["cp_id"] == 202:
                raise RuntimeError("Model unavailable for point 202")
            return super().forecast(**kwargs)

    with pytest.raises(RuntimeError, match="point 202"):
        predict_session_forecasts(
            FailingPredictor(), {101: [], 202: []}, run_id="failed",
            target_date=TARGET, issued_at=ISSUED, model_version="v1",
        )
