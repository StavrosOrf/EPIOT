"""Protect inference feature ordering, scaling, forecast timing, and information cutoff."""

import numpy as np
import pandas as pd
import pytest

from scripts.evaluate_cpft_models import (
    AVAIL_COLS, ENERGY_COLS, causal_baseline, causal_input_rows, feature_row,
    next_day_windows, observations_at_issue, scale_availability, scale_energy, day_ahead_forecasts,
)


def row():
    return feature_row(pd.Timestamp("2021-02-01 20:00", tz="UTC"), np.arange(168) % 2,
                       np.arange(168), 1, 999, 1, 60)


def test_lags_are_exact_offsets_and_rolling_statistics_exclude_current_hour():
    features = row()
    assert features["kWhDelivered_lag1"] == 167
    assert features["kWhDelivered_lag6"] == 162
    assert features["kWhDelivered_lag24"] == 144
    assert features["kWhDelivered_lag168"] == 0
    assert features["kWhDelivered_roll_mean6"] == np.mean(np.arange(162, 168))
    assert features["kWhDelivered_roll_std6"] == pytest.approx(np.std(np.arange(162, 168), ddof=1))
    assert features["availability_roll_mean168"] == .5
    assert features["hour_of_day"] == 20
    assert features["day_type"] == 0


def test_checkpoint_feature_dimensions_and_order_are_preserved():
    assert len(AVAIL_COLS) == 35
    assert len(ENERGY_COLS) == 42
    assert AVAIL_COLS[11] == "availability_lag1"
    assert ENERGY_COLS[0] == "kWhDelivered"
    assert len(set(AVAIL_COLS)) == 35
    assert len(set(ENERGY_COLS)) == 42


class ScaleByTen:
    def transform(self, values):
        self.values = np.asarray(values)
        return self.values/10


def test_availability_scaling_matches_original_float32_conversion():
    scaler = ScaleByTen()
    features = pd.DataFrame([row()])
    scaled = scale_availability(features, scaler)
    assert scaler.values.dtype == np.float32
    np.testing.assert_allclose(scaled, features[AVAIL_COLS].to_numpy(np.float32)/10)
    assert scaled.dtype == np.float32


def test_energy_scaling_keeps_main_kwh_raw_and_scales_every_other_feature():
    scaler = ScaleByTen()
    features = pd.DataFrame([row()])
    scaled = scale_energy(features, scaler)
    assert scaled[0, 0] == 999
    np.testing.assert_allclose(scaled[:, 1:], features[ENERGY_COLS[1:]].to_numpy()/10, rtol=1e-6)
    assert scaled.dtype == np.float32


def sessions():
    frame = pd.DataFrame([
        dict(connectionTime="2021-02-01 14:00", disconnectTime="2021-02-01 16:00", chargeEndTime="2021-02-01 16:00", kWhDelivered=4.),
        dict(connectionTime="2021-02-01 17:00", disconnectTime="2021-02-01 20:00", chargeEndTime="2021-02-01 19:00", kWhDelivered=500.),
        dict(connectionTime="2021-02-01 19:00", disconnectTime="2021-02-01 21:00", chargeEndTime="2021-02-01 20:00", kWhDelivered=1000.),
    ])
    for name in ["connectionTime", "disconnectTime", "chargeEndTime"]:
        frame[name] = pd.to_datetime(frame[name], utc=True)
    return frame


def test_ongoing_session_final_energy_and_future_sessions_are_unavailable():
    history = observations_at_issue(sessions(), pd.Timestamp("2021-02-01 18:00", tz="UTC"), hours=6)
    assert history.kWhDelivered.sum() == 4
    assert history.iloc[-1].availability == 1
    assert history.iloc[-1].connected_minutes == 60
    assert history.iloc[-1].kWhDelivered == 0
    assert history.index[-1] == pd.Timestamp("2021-02-01 17:00", tz="UTC")


def test_perturbing_information_after_issue_cannot_change_historical_inputs():
    source = sessions()
    issue = pd.Timestamp("2021-02-01 18:00", tz="UTC")
    expected = observations_at_issue(source, issue, hours=240)
    changed = source.copy()
    changed.loc[1:, "kWhDelivered"] = 999999
    changed.loc[1:, "disconnectTime"] += pd.Timedelta(days=10)
    changed.loc[1:, "chargeEndTime"] += pd.Timedelta(days=10)
    pd.testing.assert_frame_equal(expected, observations_at_issue(changed, issue, hours=240))
    bounds = {"kWhDelivered": (0, 100), "connected_minutes": (0, 60)}
    expected_rows, _ = causal_input_rows(expected, bounds, 72)
    actual_rows, _ = causal_input_rows(observations_at_issue(changed, issue, hours=240), bounds, 72)
    pd.testing.assert_frame_equal(expected_rows, actual_rows)


@pytest.mark.parametrize("start,end,target,expected_hours", [
    ("2021-03-13", "2021-03-17", "2021-03-14", 23),
    ("2021-11-06", "2021-11-10", "2021-11-07", 25),
])
def test_next_day_covers_local_dst_day_and_issue_stays_at_18(start, end, target, expected_hours):
    zone = "America/Los_Angeles"
    index = pd.date_range(start, end, inclusive="left", freq="h", tz=zone).tz_convert("UTC")
    windows = next_day_windows(index, zone)
    selected = next(window for window in windows if window["target_date"] == target)
    assert len(selected["timestamps"]) == expected_hours
    assert selected["horizon"] == 6+expected_hours
    assert all(window["issue"].tz_convert(zone).hour == 18 for window in windows)
    assert selected["timestamps"][0].tz_convert(zone).hour == 0


def test_previous_day_baseline_does_not_read_values_after_issue():
    index = pd.date_range("2021-02-01", periods=96, freq="h", tz="UTC")
    hourly = pd.DataFrame({"energy": np.arange(96, dtype=float)}, index=index)
    issue = index[48]
    target = index[54:78]
    prediction = causal_baseline(hourly, issue, target, "energy", 24)
    modified = hourly.copy()
    modified.loc[issue:, "energy"] = 999999
    np.testing.assert_array_equal(prediction, causal_baseline(modified, issue, target, "energy", 24))
    np.testing.assert_array_equal(prediction[:18], np.arange(30, 48))
    np.testing.assert_array_equal(prediction[18:], np.arange(24, 30))


def test_insufficient_history_is_rejected():
    with pytest.raises(ValueError, match="168"):
        feature_row(pd.Timestamp("2021-02-01", tz="UTC"), [0]*72, [0]*72, 0, 0, 0, 0)


def test_batched_origins_return_chronological_rows_for_baseline_alignment():
    class IdentityScaler:
        def transform(self, values):
            return np.asarray(values)

    class Output:
        def __init__(self, value):
            self.value = value

        def numpy(self):
            return self.value

    def zero_predictor(values):
        return Output(np.zeros((len(values), 1), dtype=np.float32))

    index = pd.date_range("2021-01-01", "2021-02-04", freq="h", tz="UTC")
    frame = pd.DataFrame({"availability": np.arange(len(index)) % 2, "kWhDelivered": np.arange(len(index)) % 3}, index=index)
    test_index = index[index >= pd.Timestamp("2021-02-01", tz="UTC")]
    windows = next_day_windows(test_index, "UTC")[:2]
    predictions = day_ahead_forecasts(sessions(), frame, windows,
        {"connected_minutes": (0, 60), "kWhDelivered": (0, 100)},
        {"occupancy_count": 1, "connected_minutes": 50}, IdentityScaler(), IdentityScaler(),
        72, .5, zero_predictor, zero_predictor)
    assert predictions.hour.is_monotonic_increasing
    assert predictions.target_date.iloc[:24].nunique() == 1
    assert predictions.target_date.iloc[24:].nunique() == 1
    np.testing.assert_array_equal(predictions.actual_kwh, frame.kWhDelivered.reindex(predictions.hour))
