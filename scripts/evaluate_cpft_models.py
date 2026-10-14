"""Execute the bundled CPFT checkpoints with verified preprocessing and causal backtests.

No training or application database writes. The bundled session archive is the
only supported training provenance; reconstructed features must match its export.
See reports/cpft_model_evaluation/report.md for assumptions and reproduction.
"""

import argparse
import ast
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.analyze_cpft_predictions import classification_metrics, regression_metrics

SOURCE = ROOT / "others/CPFT-main/CPFT-tool/CPFT_VS_Code_Python"
LAGS = (1, 2, 3, 6, 12, 24, 48, 72, 168)
WINDOWS = (6, 24, 168)
CALENDAR = ["day_type", "month", "hod_sin", "hod_cos", "dow_sin", "dow_cos", "mon_sin", "mon_cos"]


def lag_names(target):
    return [f"{target}_lag{lag}" for lag in LAGS]


def rolling_names(target):
    return [f"{target}_roll_{stat}{width}" for width in WINDOWS for stat in ["mean", "std"]]


AVAIL_COLS = ["hour_of_day", *CALENDAR, "occupancy_count", "connected_minutes"] + lag_names("availability") + rolling_names("availability") + lag_names("kWhDelivered")
ENERGY_COLS = ["kWhDelivered", "availability", *CALENDAR, "occupancy_count", "connected_minutes"] + lag_names("kWhDelivered") + rolling_names("kWhDelivered") + lag_names("availability") + rolling_names("availability")


def progress(message):
    print(message, flush=True)


def source_definitions(names, namespace):
    """Load only named definitions, never the source's top-level training code."""
    path = SOURCE / "CPFT_pipeline_VS_Code_Python.py"
    parsed = ast.parse(path.read_text(encoding="utf-8"))
    selected = [node for node in parsed.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    if {node.name for node in selected} != set(names):
        raise ValueError("Expected CPFT definitions missing")
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return {name: namespace[name] for name in names}


def read_sessions(path):
    frame = pd.read_csv(path, usecols=["connectionTime", "disconnectTime", "doneChargingTime", "kWhDelivered", "stationID", "timezone"])
    for name in ["connectionTime", "disconnectTime", "doneChargingTime"]:
        frame[name] = pd.to_datetime(frame[name], errors="coerce", utc=True)
    frame["kWhDelivered"] = pd.to_numeric(frame.kWhDelivered, errors="coerce")
    frame = frame.dropna(subset=["connectionTime", "disconnectTime", "kWhDelivered"])
    frame = frame[frame.disconnectTime > frame.connectionTime].copy()
    frame["chargeEndTime"] = frame.doneChargingTime.fillna(frame.disconnectTime)
    frame["kWhDelivered"] = frame.kWhDelivered.clip(lower=0)
    if frame.stationID.nunique() != 1 or frame.timezone.nunique() != 1:
        raise ValueError("The checkpoints support only their original single-station archive")
    return frame


def prepare(sessions, sheets):
    from sklearn.preprocessing import StandardScaler
    functions = source_definitions(["build_hourly_frame", "zscore_filter_train_only", "add_lag_roll"], {"np": np, "pd": pd})
    raw = functions["build_hourly_frame"](sessions)
    clipped, clipping_stats = functions["zscore_filter_train_only"](raw, ["kWhDelivered", "connected_minutes"])
    frame = functions["add_lag_roll"](functions["add_lag_roll"](clipped, "availability"), "kWhDelivered").dropna().reset_index(drop=True)
    exported = sheets["hourly_input"]
    if list(frame.columns) != list(exported.columns):
        raise AssertionError("Reconstructed feature order differs from the training export")
    if not np.array_equal(frame.hour.to_numpy(), pd.to_datetime(exported.hour, utc=True).to_numpy()):
        raise AssertionError("Reconstructed timeline differs from the training export")
    numeric = frame.drop(columns="hour").to_numpy(float)
    numeric_export = exported.drop(columns="hour").to_numpy(float)
    # Rolling variances around zero differ slightly across pandas builds and
    # Excel round trips. A micro-unit tolerance is far below hourly resolution.
    if not np.allclose(numeric, numeric_export, rtol=1e-7, atol=1e-6):
        raise AssertionError(f"Reconstructed inputs differ from export: {np.max(np.abs(numeric-numeric_export))}")
    n_train, n_val = int(len(frame)*.60), int(len(frame)*.20)
    scaler_av = StandardScaler().fit(frame[AVAIL_COLS].iloc[:n_train].to_numpy(np.float32))
    scaler_kwh = StandardScaler().fit(frame[ENERGY_COLS[1:]].iloc[:n_train])
    bounds = {name: (float(mean-3*std), float(mean+3*std)) for name, (mean, std) in clipping_stats.items()}
    occupied_train = frame.iloc[:n_train].loc[frame.availability.iloc[:n_train].eq(1)]
    proxies = {name: float(occupied_train[name].mean()) for name in ["occupancy_count", "connected_minutes"]}
    return frame.set_index("hour"), scaler_av, scaler_kwh, bounds, proxies, {
        "export_features_match": True, "maximum_feature_difference": float(np.max(np.abs(numeric-numeric_export))),
        "training_rows_for_scalers": n_train, "validation_rows_before_windows": n_val,
        "training_end_inclusive": str(frame.hour.iloc[n_train-1]), "clipping_bounds": bounds,
        "future_connection_feature_proxies": proxies,
    }


def scale_availability(rows, scaler):
    # Original training converted the raw inputs to float32 before scaling.
    return scaler.transform(rows[AVAIL_COLS].to_numpy(np.float32)).astype(np.float32)


def scale_energy(rows, scaler):
    values = rows[ENERGY_COLS].to_numpy(float)
    values[:, 1:] = scaler.transform(rows[ENERGY_COLS[1:]])
    return values.astype(np.float32)


def calendar_row(timestamp):
    timestamp = pd.Timestamp(timestamp).tz_convert("UTC")
    hour, dow, month = timestamp.hour, timestamp.dayofweek, timestamp.month
    return {"hour_of_day": hour, "day_type": int(dow >= 5), "month": month,
            "hod_sin": np.sin(2*np.pi*hour/24), "hod_cos": np.cos(2*np.pi*hour/24),
            "dow_sin": np.sin(2*np.pi*dow/7), "dow_cos": np.cos(2*np.pi*dow/7),
            "mon_sin": np.sin(2*np.pi*(month-1)/12), "mon_cos": np.cos(2*np.pi*(month-1)/12)}


def feature_row(timestamp, preceding_availability, preceding_energy, occupied, energy, count, minutes):
    """Build a raw row; every lag/rolling value uses strictly earlier hours."""
    row = calendar_row(timestamp)
    row.update(availability=float(occupied), kWhDelivered=float(energy), occupancy_count=float(count), connected_minutes=float(minutes))
    for target, history in [("availability", preceding_availability), ("kWhDelivered", preceding_energy)]:
        history = np.asarray(history, float)
        if len(history) < max(LAGS) or not np.isfinite(history).all():
            raise ValueError("At least 168 finite preceding hours are required")
        for lag in LAGS:
            row[f"{target}_lag{lag}"] = history[-lag]
        for width in WINDOWS:
            row[f"{target}_roll_mean{width}"] = history[-width:].mean()
            row[f"{target}_roll_std{width}"] = history[-width:].std(ddof=1)
    return row


def observations_at_issue(sessions, issue, hours=240):
    """Past occupancy from observed connections; energy from completed records.

    Final kWh and charging-end information for sessions still connected at issue
    are unavailable. Their historical energy is conservatively zero; metered
    live energy could replace this policy if it were supplied.
    """
    issue = pd.Timestamp(issue).tz_convert("UTC")
    if issue != issue.floor("h"):
        raise ValueError("Issue time must be an exact hour")
    index = pd.date_range(end=issue-pd.Timedelta(hours=1), periods=hours, freq="h", tz="UTC")
    starts = index.as_unit("ns").asi8
    step = 3_600_000_000_000
    counts, minutes, energy = np.zeros(hours), np.zeros(hours), np.zeros(hours)
    relevant = sessions[(sessions.connectionTime < issue) & (sessions.disconnectTime > index[0])]
    for session in relevant.itertuples():
        conn = session.connectionTime.value
        # The only information used about a later disconnection is that it has
        # not happened at issue time; its future timestamp is not used.
        disc = min(session.disconnectTime, issue).value
        overlap = np.maximum(0, np.minimum(starts+step, disc)-np.maximum(starts, conn))
        counts += overlap > 0
        minutes += overlap / 60_000_000_000
        if session.disconnectTime <= issue and session.chargeEndTime <= issue and session.chargeEndTime.value > conn:
            end = session.chargeEndTime.value
            energy_overlap = np.maximum(0, np.minimum(starts+step, end)-np.maximum(starts, conn))
            energy += session.kWhDelivered * energy_overlap / (end-conn)
    return pd.DataFrame({"availability": (counts > 0).astype(float), "occupancy_count": counts,
                         "connected_minutes": minutes, "kWhDelivered": energy}, index=index)


def causal_input_rows(observations, bounds, sequence_length):
    observations = observations.copy()
    for name, (lower, upper) in bounds.items():
        observations[name] = observations[name].clip(lower=lower, upper=upper)
    rows = []
    for pos in range(len(observations)-sequence_length, len(observations)):
        current = observations.iloc[pos]
        rows.append(feature_row(observations.index[pos], observations.availability.iloc[:pos], observations.kWhDelivered.iloc[:pos],
                                current.availability, current.kWhDelivered, current.occupancy_count, current.connected_minutes))
    return pd.DataFrame(rows), observations


def next_day_windows(test_index, station_timezone, issue_hour=18):
    """Issue at 18:00 local the previous day; score the entire next local day."""
    windows = []
    for target in pd.date_range(test_index[0].tz_convert(station_timezone).normalize(),
                                test_index[-1].tz_convert(station_timezone).normalize(), freq="D"):
        next_midnight = pd.Timestamp(target.date()+timedelta(days=1)).tz_localize(station_timezone)
        issue = pd.Timestamp(f"{target.date()-timedelta(days=1)} {issue_hour:02d}:00").tz_localize(station_timezone)
        start, end, issue = target.tz_convert("UTC"), next_midnight.tz_convert("UTC"), issue.tz_convert("UTC")
        timestamps = pd.date_range(start, end, inclusive="left", freq="h")
        if issue >= test_index[0] and timestamps.isin(test_index).all():
            windows.append(dict(target_date=str(target.date()), issue=issue, start=start, end=end, timestamps=timestamps,
                                target_offset=int((start-issue)/pd.Timedelta(hours=1)),
                                horizon=int((end-issue)/pd.Timedelta(hours=1))))
    return windows


def causal_baseline(hourly, issue, timestamps, target, lag):
    """Fixed at issue time; recursively repeat lags when prior-day values are future."""
    values = {}
    through = pd.date_range(issue, timestamps[-1], freq="h")
    for timestamp in through:
        source = timestamp-pd.Timedelta(hours=lag)
        values[timestamp] = float(hourly.loc[source, target]) if source < issue else values[source]
    return np.array([values[t] for t in timestamps])


def load_checkpoints(frame, scaler_av, threads):
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
    import tensorflow as tf
    from tensorflow import keras
    tf.config.threading.set_intra_op_parallelism_threads(threads)
    tf.config.threading.set_inter_op_parallelism_threads(1)
    definitions = source_definitions(["BinaryAvailabilityModel"], {"tf": tf, "keras": keras, "layers": keras.layers})
    availability = keras.models.load_model(SOURCE / "outputs/best_availability.keras", custom_objects=definitions, compile=False, safe_mode=True)
    energy = keras.models.load_model(SOURCE / "outputs/best_kwh.keras", compile=False, safe_mode=True)
    if availability.n_features != len(AVAIL_COLS) or energy.input_shape[2] != len(ENERGY_COLS):
        raise AssertionError("Checkpoint feature dimensions mismatch")
    seq_len = availability.seq_len
    if energy.input_shape[1] != seq_len:
        raise AssertionError("Checkpoint sequence lengths differ")
    lag_index = AVAIL_COLS.index("availability_lag1")
    if not (np.isclose(scaler_av.mean_[lag_index], availability.lag1_mu_value, atol=1e-8, rtol=1e-8)
            and np.isclose(scaler_av.scale_[lag_index], availability.lag1_std_value, atol=1e-8, rtol=1e-8)):
        raise AssertionError("Reconstructed scaler does not match metadata embedded in checkpoint")

    @tf.function(input_signature=[tf.TensorSpec([None, seq_len, len(AVAIL_COLS)], tf.float32)])
    def predict_av(value):
        return availability(value, training=False)

    @tf.function(input_signature=[tf.TensorSpec([None, seq_len, len(ENERGY_COLS)], tf.float32)])
    def predict_energy(value):
        return energy(value, training=False)

    def predict_batches(predictor, scaled, positions, batch_size=256):
        output = []
        for start in range(0, len(positions), batch_size):
            selected = positions[start:start+batch_size]
            inputs = np.stack([scaled[pos-seq_len:pos] for pos in selected])
            output.append(predictor(inputs).numpy().reshape(-1))
        return np.concatenate(output)

    return seq_len, predict_av, predict_energy, predict_batches, dict(
        scaler_matches_embedded_checkpoint_metadata=True, availability_input=[seq_len, len(AVAIL_COLS)],
        energy_input=[seq_len, len(ENERGY_COLS)], parameters=dict(availability=availability.count_params(), energy=energy.count_params()),
        preserved_occupancy_blend=True, blend_weight=float(tf.sigmoid(availability.blend_logit).numpy()),
    )


def evaluate_one_step(frame, sheets, scaler_av, scaler_kwh, seq_len, predict_av, predict_energy, predict_batches):
    total_sequences = len(frame)-seq_len
    val_positions = np.arange(seq_len+int(total_sequences*.6), seq_len+int(total_sequences*.8))
    scaled_av = scale_availability(frame, scaler_av)
    scaled_kwh = scale_energy(frame, scaler_kwh)
    progress("Executing saved occupancy checkpoint on chronological validation windows...")
    val_prob = predict_batches(predict_av, scaled_av, val_positions)
    val_labels = frame.availability.iloc[val_positions].to_numpy(int)
    thresholds = np.linspace(.05, .95, 181)
    f1 = [classification_metrics(val_labels, val_prob >= threshold)["f1"] for threshold in thresholds]
    threshold = float(thresholds[np.argmax(f1)])
    av_test = sheets["test_availability"].copy()
    energy_test = sheets["test_kwh"].copy()
    av_test["hour"] = pd.to_datetime(av_test.hour, utc=True)
    energy_test["hour"] = pd.to_datetime(energy_test.hour, utc=True)
    av_positions = frame.index.get_indexer(av_test.hour)
    energy_positions = frame.index.get_indexer(energy_test.hour)
    if (av_positions < seq_len).any() or (energy_positions < seq_len).any():
        raise AssertionError("Export test timestamps cannot be aligned to checkpoint input windows")
    progress("Executing both saved checkpoints on the held-out one-hour test windows...")
    av_prob = predict_batches(predict_av, scaled_av, av_positions)
    kwh = np.maximum(0, np.expm1(predict_batches(predict_energy, scaled_kwh, energy_positions)))
    energy_occ = pd.Series(av_prob >= threshold, index=av_test.hour).reindex(energy_test.hour).to_numpy()
    actual_occ = frame.availability.iloc[av_positions].to_numpy(int)
    actual_kwh = frame.kWhDelivered.iloc[energy_positions].to_numpy()
    metrics = dict(occupancy=classification_metrics(actual_occ, av_prob >= threshold, av_prob),
                   energy_ungated=regression_metrics(actual_kwh, kwh),
                   energy_predicted_occupancy_gated=regression_metrics(actual_kwh, np.where(energy_occ, kwh, 0)),
                   baselines={})
    for lag, name in [(1, "Last hour"), (24, "Previous day"), (168, "Previous week")]:
        metrics["baselines"][name] = dict(
            occupancy=classification_metrics(actual_occ, frame.availability.reindex(av_test.hour-pd.Timedelta(hours=lag))),
            energy=regression_metrics(actual_kwh, frame.kWhDelivered.reindex(energy_test.hour-pd.Timedelta(hours=lag))))
    reconciliation = dict(
        maximum_occupancy_probability_difference=float(np.max(np.abs(av_prob-av_test.availability_pred_prob_for_auc))),
        maximum_energy_difference_kwh=float(np.max(np.abs(kwh-energy_test.kWh_pred))),
        predictions_reproduce_saved_export=bool(np.allclose(av_prob, av_test.availability_pred_prob_for_auc, atol=1e-5, rtol=1e-5)
                                                and np.allclose(kwh, energy_test.kWh_pred, atol=1e-5, rtol=1e-5)),
        threshold_reselected_on_validation=threshold, exported_threshold=float(sheets["metrics_summary"].threshold_TH.iloc[0]),
        validation_start=str(frame.index[val_positions[0]]), validation_end=str(frame.index[val_positions[-1]]),
        validation_occupancy_f1=float(max(f1)),
    )
    av_test = av_test.set_index("hour")
    av_test["checkpoint_probability"] = av_prob
    av_test["checkpoint_occupied"] = (av_prob >= threshold).astype(int)
    energy_test = energy_test.set_index("hour")
    energy_test["checkpoint_kwh_ungated"] = kwh
    energy_test["checkpoint_kwh_predicted_occupancy_gated"] = np.where(energy_occ, kwh, 0)
    return threshold, metrics, reconciliation, av_test.join(energy_test, how="outer")


def day_ahead_forecasts(sessions, frame, windows, bounds, proxies, scaler_av, scaler_kwh, seq_len, threshold,
                        predict_av, predict_energy, policy="training_conditional_means"):
    observations, initial_rows = [], []
    for window in windows:
        rows, history = causal_input_rows(observations_at_issue(sessions, window["issue"], seq_len+max(LAGS)), bounds, seq_len)
        observations.append(history)
        initial_rows.append(rows)
    av_sequences = np.stack([scale_availability(rows, scaler_av) for rows in initial_rows])
    energy_sequences = np.stack([scale_energy(rows, scaler_kwh) for rows in initial_rows])
    # Keep complete raw histories, so lag168 never becomes an adjacent lag.
    av_history = np.stack([history.availability.to_numpy() for history in observations])
    energy_history = np.stack([history.kWhDelivered.to_numpy() for history in observations])
    horizon = max(window["horizon"] for window in windows)
    predictions = []
    for lead in range(horizon):
        probability = predict_av(av_sequences).numpy().reshape(-1)
        occupied = probability >= threshold
        raw_kwh = np.maximum(0, np.expm1(predict_energy(energy_sequences).numpy().reshape(-1)))
        gated_kwh = np.where(occupied, raw_kwh, 0)
        rows = []
        for i, window in enumerate(windows):
            timestamp = window["issue"]+pd.Timedelta(hours=lead)
            if window["start"] <= timestamp < window["end"]:
                predictions.append(dict(target_date=window["target_date"], issue_time=window["issue"], hour=timestamp,
                                        lead_hours=lead+1, occupancy_probability=float(probability[i]), occupied=int(occupied[i]),
                                        energy_kwh=float(gated_kwh[i]), energy_kwh_ungated=float(raw_kwh[i]), policy=policy))
            if policy == "training_conditional_means":
                count = float(occupied[i])*proxies["occupancy_count"]
                minutes = float(occupied[i])*proxies["connected_minutes"]
            elif policy == "full_hour":
                count, minutes = float(occupied[i]), 60.*float(occupied[i])
            elif policy == "carry_last_activity":
                # Sensitivity to unknown activity features, not the default.
                count, minutes = observations[i].iloc[-1][["occupancy_count", "connected_minutes"]]
            else:
                raise ValueError(f"Unknown connection proxy policy: {policy}")
            minutes = np.clip(minutes, *bounds["connected_minutes"])
            feedback_kwh = np.clip(gated_kwh[i], *bounds["kWhDelivered"])
            rows.append(feature_row(timestamp, av_history[i], energy_history[i], occupied[i], feedback_kwh, count, minutes))
        rows = pd.DataFrame(rows)
        av_sequences = np.concatenate([av_sequences[:, 1:], scale_availability(rows, scaler_av)[:, None, :]], axis=1)
        energy_sequences = np.concatenate([energy_sequences[:, 1:], scale_energy(rows, scaler_kwh)[:, None, :]], axis=1)
        av_history = np.column_stack([av_history, occupied.astype(float)])
        energy_history = np.column_stack([energy_history, rows.kWhDelivered.to_numpy()])
        if (lead+1) % 6 == 0 or lead+1 == horizon:
            progress(f"  {policy}: completed recursive lead {lead+1}/{horizon} for {len(windows)} forecast origins")
    # Inference batches are lead-major; metrics and baseline arrays must share
    # chronological day-major order, including when multiple origins are batched.
    result = pd.DataFrame(predictions).sort_values(["target_date", "hour"]).reset_index(drop=True)
    if not (np.isfinite(result.energy_kwh).all() and result.energy_kwh.ge(0).all()
            and result.loc[result.occupied.eq(0), "energy_kwh"].eq(0).all()):
        raise AssertionError("Invalid predicted energy/occupancy combination")
    result["actual_occupied"] = frame.availability.reindex(result.hour).to_numpy(int)
    result["actual_kwh"] = frame.kWhDelivered.reindex(result.hour).to_numpy()
    return result


def summarize_day_ahead(predictions, sessions, windows, bounds):
    methods = {"CPFT": (predictions.occupied.to_numpy(), predictions.energy_kwh.to_numpy())}
    # Baselines use the same completed-record history available to CPFT at issue.
    histories = {window["target_date"]: observations_at_issue(sessions, window["issue"], 24*8+48)
                 for window in windows}
    for history in histories.values():
        for name, (lower, upper) in bounds.items():
            history[name] = history[name].clip(lower=lower, upper=upper)
    for lag, name in [(1, "Last hour"), (24, "Previous day (recursive)"), (168, "Previous week")]:
        occ, kwh = [], []
        for window in windows:
            history = histories[window["target_date"]]
            if lag == 1:
                occ.extend(np.repeat(history.availability.iloc[-1], len(window["timestamps"])))
                kwh.extend(np.repeat(history.kWhDelivered.iloc[-1], len(window["timestamps"])))
            else:
                occ.extend(causal_baseline(history, window["issue"], window["timestamps"], "availability", lag))
                kwh.extend(causal_baseline(history, window["issue"], window["timestamps"], "kWhDelivered", lag))
        methods[name] = (np.asarray(occ), np.asarray(kwh))
    methods["Always zero"] = (np.zeros(len(predictions)), np.zeros(len(predictions)))
    output = {}
    for name, (occupied, kwh) in methods.items():
        probability = predictions.occupancy_probability if name == "CPFT" else None
        output[name] = dict(occupancy=classification_metrics(predictions.actual_occupied, occupied, probability),
                            energy=regression_metrics(predictions.actual_kwh, kwh))
        predictions[name+"_kwh"] = kwh
        predictions[name+"_occupied"] = occupied
    daily = predictions.groupby("target_date", sort=True).agg(actual_kwh=("actual_kwh", "sum"), predicted_kwh=("energy_kwh", "sum"),
                                                              actual_occupied_hours=("actual_occupied", "sum"), predicted_occupied_hours=("occupied", "sum"))
    return output, daily


def write_preprocessing(output, original_hashes, seq_len, threshold, scaler_av, scaler_kwh, preprocessing):
    bundle = dict(source_sha256=original_hashes, sequence_length=seq_len, occupancy_threshold=threshold,
                  availability_features=AVAIL_COLS, energy_features=ENERGY_COLS, calendar_timezone="UTC",
                  availability_mean=scaler_av.mean_.tolist(), availability_scale=scaler_av.scale_.tolist(),
                  energy_scaled_features=ENERGY_COLS[1:], energy_mean=scaler_kwh.mean_.tolist(), energy_scale=scaler_kwh.scale_.tolist(),
                  preprocessing=preprocessing, note="Reconstructed only for the bundled original-station checkpoints; export predictions verified.")
    (output / "reconstructed_preprocessing.json").write_text(json.dumps(bundle, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def write_report(stats, predictions, daily, output):
    """Render measured results; can run independently of TensorFlow inference."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    one, day, test = stats["one_hour_ahead"], stats["day_ahead"], stats["next_day_test"]
    cpft = day["CPFT"]
    ungated = regression_metrics(predictions.actual_kwh, predictions.energy_kwh_ungated)
    stats["day_ahead_ungated_energy"] = ungated
    stats["day_ahead_lead_metrics"] = {
        str(lead): dict(occupancy=classification_metrics(group.actual_occupied, group.occupied, group.occupancy_probability),
                       energy=regression_metrics(group.actual_kwh, group.energy_kwh))
        for lead, group in predictions.groupby("lead_hours")}
    stats["evaluation_label_issues"] = dict(
        energy_positive_while_unoccupied_hours=int(((predictions.actual_kwh > 1e-8) & predictions.actual_occupied.eq(0)).sum()),
        energy_positive_while_unoccupied_kwh=float(predictions.loc[predictions.actual_occupied.eq(0), "actual_kwh"].sum()))
    sessions = read_sessions(SOURCE.parent / "Station_2_39_139_28.csv")
    issues = pd.to_datetime(predictions.issue_time.unique(), utc=True)
    ongoing = [int(((sessions.connectionTime < issue) & (sessions.disconnectTime > issue)).sum()) for issue in issues]
    stats["information_cutoff"] = dict(origins_with_ongoing_sessions=int(np.count_nonzero(ongoing)),
                                        maximum_ongoing_sessions=max(ongoing),
                                        energy_policy="Only records disconnected and finished charging by issue contribute historical energy. Ongoing-session historical energy is zero because live meter readings are absent.",
                                        publication_assumption="Completed session records and connection/disconnection events are assumed available immediately; ingestion delays are not recorded.")
    if (output / "test_results.xml").exists():
        totals = {key: 0 for key in ["tests", "failures", "errors", "skipped"]}
        for suite in ET.parse(output / "test_results.xml").getroot().iter("testsuite"):
            for key in totals:
                totals[key] += int(suite.get(key, "0"))
        stats["focused_test_results"] = totals
    (output / "statistics.json").write_text(json.dumps(stats, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.titleweight": "bold", "figure.facecolor": "white"})
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), layout="constrained")
    names = ["CPFT", "Previous day (recursive)", "Previous week", "Always zero"]
    labels = ["CPFT", "Previous day", "Previous week", "Zero"]
    x = np.arange(len(names))
    for delta, metric, label, color in [(-.18, "accuracy", "Accuracy", "#1677a6"), (.18, "f1", "F1", "#df8638")]:
        bars = axes[0, 0].bar(x+delta, [day[name]["occupancy"][metric] for name in names], .34, label=label, color=color)
        axes[0, 0].bar_label(bars, fmt="%.3f", fontsize=9, padding=2)
    axes[0, 0].set(title="Next-day occupancy", ylim=(0, 1.18), ylabel="Score (higher is better)", xticks=x, xticklabels=labels)
    axes[0, 0].legend(loc="upper left", ncols=2, frameon=False)
    for delta, metric, label, color in [(-.18, "mae", "MAE", "#1677a6"), (.18, "rmse", "RMSE", "#df8638")]:
        bars = axes[0, 1].bar(x+delta, [day[name]["energy"][metric] for name in names], .34, label=label, color=color)
        axes[0, 1].bar_label(bars, fmt="%.3f", fontsize=9, padding=2)
    axes[0, 1].set(title="Next-day hourly energy errors", ylim=(0, 1.42), ylabel="Error (kWh per hourly bin)", xticks=x, xticklabels=labels)
    axes[0, 1].legend(loc="upper left", ncols=2, frameon=False)
    dates = pd.to_datetime(daily.index)
    axes[1, 0].plot(dates, daily.actual_kwh, color="#354454", lw=1.3, label="Session-derived actual")
    axes[1, 0].plot(dates, daily.predicted_kwh, color="#1677a6", lw=1.3, label="CPFT")
    axes[1, 0].set(title="Total next-day energy", ylabel="Energy (kWh per local day)")
    axes[1, 0].xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    axes[1, 0].xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    axes[1, 0].legend(frameon=False)
    local_hours = pd.to_datetime(predictions.hour, utc=True).dt.tz_convert(stats["station_timezone"]).dt.hour
    profile = predictions.groupby(local_hours)[["actual_kwh", "energy_kwh"]].mean()
    axes[1, 1].bar(profile.index-.18, profile.actual_kwh, .34, color="#354454", label="Session-derived actual")
    axes[1, 1].bar(profile.index+.18, profile.energy_kwh, .34, color="#1677a6", label="CPFT")
    axes[1, 1].set(title="Average next-day hourly profile", xlabel=f"Hour in {stats['station_timezone']}", ylabel="Mean energy (kWh per hour)", xticks=np.arange(0, 24, 3))
    axes[1, 1].legend(frameon=False)
    for axis in axes.flat:
        axis.set_axisbelow(True)
        axis.grid(axis="y", alpha=.15)
    fig.suptitle(f"Executed CPFT checkpoints: {test['days']} complete next-day forecasts", fontsize=15, weight="bold")
    fig.supxlabel("Original example station only. Forecasts issued at 18:00 local; future observations excluded from inputs.", fontsize=10)
    fig.savefig(output / "prediction_diagnostics.png", dpi=180)
    fig.savefig(output / "prediction_diagnostics.svg")
    plt.close(fig)

    lines = ["# Executed CPFT model evaluation", "",
             "The existing checkpoints reproduce the exported one-hour predictions, but their complete next-day forecasts underpredict energy severely and do not beat seasonal occupancy baselines. These checkpoints are not suitable for the proposed station-wide daily service without further model development and validation.", "",
             "## Models actually executed", "",
             "Loaded `best_availability.keras` and `best_kwh.keras` with Keras 3.13.2 / TensorFlow 2.20.0 on CPU. The original custom `BinaryAvailabilityModel` definition and its learned blend are preserved. Only named definitions are loaded from the research script; its top-level training code is never run. Loading uses `compile=False`, `safe_mode=True` and the custom class, following the [Keras loading API](https://keras.io/api/models/model_saving_apis/model_saving_and_loading/). All model calls use `training=False`. No model was retrained or modified.", "",
             f"Input shapes are {stats['checkpoint_checks']['availability_input']} and {stats['checkpoint_checks']['energy_input']}; the trained 72-hour context is preserved for every horizon. The original UTC calendar convention is retained even though forecast issue/target boundaries use {stats['station_timezone']}.", "",
             "## Input verification", "",
             f"Rebuilt the original hourly labels, clipping and features from the original CSV. The maximum feature difference against the exported training frame is {stats['preprocessing']['maximum_feature_difference']:.3g}. StandardScaler parameters are reconstructed using only the original training slice; the embedded occupancy lag scaler metadata matches. No scaler is fitted to test or forecast data.", "",
             f"Checkpoint predictions reproduce the export: **{stats['checkpoint_export_reconciliation']['predictions_reproduce_saved_export']}**. Maximum differences: occupancy probability {stats['checkpoint_export_reconciliation']['maximum_occupancy_probability_difference']:.3g}, energy {stats['checkpoint_export_reconciliation']['maximum_energy_difference_kwh']:.3g} kWh. The occupancy threshold was reselected on the chronological validation windows only: {stats['checkpoint_export_reconciliation']['threshold_reselected_on_validation']:.3f}, matching the export. This threshold was originally tuned for one-step F1; it was not retuned on the day-ahead test.", "",
             "The reconstructed feature order, scalers, clipping limits and threshold are saved in `reconstructed_preprocessing.json`. They belong to this original station and training snapshot; they are not independently trained artifacts for Amsterdam.", "",
             "## One-hour results with observed historical windows", "",
             "| Method | Occupancy accuracy | Occupancy F1 | Energy MAE | Energy RMSE |",
             "| --- | ---: | ---: | ---: | ---: |",
             f"| CPFT, ungated energy | {one['occupancy']['accuracy']:.2%} | {one['occupancy']['f1']:.3f} | {one['energy_ungated']['mae']:.3f} | {one['energy_ungated']['rmse']:.3f} |"]
    for name, metrics in one["baselines"].items():
        lines.append(f"| {name} | {metrics['occupancy']['accuracy']:.2%} | {metrics['occupancy']['f1']:.3f} | {metrics['energy']['mae']:.3f} | {metrics['energy']['rmse']:.3f} |")
    lines += ["", "Energy errors are in kWh per hourly bin. These windows use retrospectively reconstructed historical energy, including finalized session information. They reproduce the published example evaluation and are not an operational information-cutoff backtest.", "",
              f"Gating one-hour energy using **predicted** occupancy gives MAE {one['energy_predicted_occupancy_gated']['mae']:.3f}, RMSE {one['energy_predicted_occupancy_gated']['rmse']:.3f}, and total energy bias {one['energy_predicted_occupancy_gated']['total_bias_percent']:.2f}%. Actual occupancy is never used to gate a prediction.", "",
              "## Complete next-day test", "",
              f"Tested {test['days']} complete local days ({test['hours']:,} hours), {test['first_target']} through {test['last_target']}. Forecasts are issued at 18:00 local the preceding day, use observations strictly before issue, and forecast the six-hour gap plus the whole target day. Scored leads are {min(test['leads'])}-{max(test['leads'])} hours. Day lengths: {test['day_lengths']}; the 23-hour spring DST day is included.", "",
              "| Method | Occupancy accuracy | Occupancy F1 | Energy MAE | Energy RMSE | Energy total bias |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name, metrics in day.items():
        lines.append(f"| {name} | {metrics['occupancy']['accuracy']:.2%} | {metrics['occupancy']['f1']:.3f} | {metrics['energy']['mae']:.3f} | {metrics['energy']['rmse']:.3f} | {metrics['energy']['total_bias_percent']:.2f}% |")
    lines += ["", f"CPFT predicts {cpft['energy']['predicted_total_kwh']:.2f} kWh against {cpft['energy']['actual_total_kwh']:.2f} kWh in the reconstructed observations. It predicts {cpft['occupancy']['predicted_occupied_hours']:,} occupied hours against {cpft['occupancy']['observed_occupied_hours']:,}, with precision {cpft['occupancy']['precision']:.2%} and recall {cpft['occupancy']['recall']:.2%}. Daily energy MAE is {stats['daily_energy']['mae']:.3f} kWh/day. Low overall errors can hide the predominance of zero-energy hours; the always-zero MAE is lower than CPFT's here.", "",
              f"Without the occupancy output gate, the already-executed energy predictions give MAE {ungated['mae']:.3f}, RMSE {ungated['rmse']:.3f}, and total bias {ungated['total_bias_percent']:.2f}%. This diagnostic changes only output gating, not the gated energy fed back during the rollout.", "",
              "## Correct recursive use and unavailable features", "",
              "At each predicted hour, all nonconsecutive lags and rolling means/sample standard deviations are recomputed from the actual preceding raw history plus predictions. Calendar fields advance in UTC, then each feature is scaled using its own original training scaler. The energy main input stays raw as in training; energy outputs use expm1 and nonnegative clipping. Previous-day baselines recurse when their source hour would be after issue, so no baseline peeks at observations unavailable to CPFT.", "",
              f"Historical occupancy/count/connected minutes use connection events up to issue. Historical energy uses only completed records whose disconnect and charging-end timestamps are at or before issue. Ongoing-session final energy totals are excluded; missing live-meter energy is conservatively zero. {stats['information_cutoff']['origins_with_ongoing_sessions']} of {test['days']} origins have ongoing sessions. Publication of completed records/events at their event times is an explicit assumption because ingestion timestamps are unavailable.", "",
              f"Future occupancy count and connected minutes are not predicted by these two checkpoints, but are required input features. The default policy uses predicted binary occupancy times training-only conditional means: count {stats['preprocessing']['future_connection_feature_proxies']['occupancy_count']:.3f}, connected minutes {stats['preprocessing']['future_connection_feature_proxies']['connected_minutes']:.3f}. This is an explicit approximation, not observed future information. Sensitivity checks keep the same weights, scaling, lag and calendar rules:", "",
              "| Future activity policy | Occupancy F1 | Energy MAE | Energy RMSE | Energy bias |",
              "| --- | ---: | ---: | ---: | ---: |",
              f"| Training conditional means (default) | {cpft['occupancy']['f1']:.3f} | {cpft['energy']['mae']:.3f} | {cpft['energy']['rmse']:.3f} | {cpft['energy']['total_bias_percent']:.2f}% |"]
    for name, metrics in stats["connection_proxy_sensitivity"].items():
        lines.append(f"| {name} | {metrics['occupancy']['f1']:.3f} | {metrics['energy']['mae']:.3f} | {metrics['energy']['rmse']:.3f} | {metrics['energy']['total_bias_percent']:.2f}% |")
    lines += ["", "`full_hour` assigns count 1 and 60 connected minutes when occupied. `carry_last_activity` freezes these activity features at the last observed value and is a diagnostic of the original carry-forward assumption, rather than the default. All evaluated policies show substantial energy underprediction.", "",
              "## Limits and next work", "",
              f"This is station {stats['source_station']} from the original example archive, not a model validation across EPIOT stations. Hourly energy truth is uniform allocation of session energy over charging duration and clipped using training-derived limits, rather than independent hourly meter readings. The archive contains {stats['charging_end_after_disconnect']} sessions with charging-end timestamps later than disconnect. In the scored target hours, {stats['evaluation_label_issues']['energy_positive_while_unoccupied_hours']} hours have positive reconstructed energy while occupancy is zero ({stats['evaluation_label_issues']['energy_positive_while_unoccupied_kwh']:.3f} kWh). These data inconsistencies limit physical interpretation; labels were preserved to match the trained preprocessing.", "",
              "The primary one-step metric advantage does not transfer to reliable next-day demand. Train/validate the model for the intended multi-hour task, include a defined method for unavailable connection features and ongoing-session energy, persist the full preprocessing bundle, and calibrate on day-ahead validation periods before evaluating an untouched test period. Use representative station histories and actual metered hourly energy where available. Exact session arrivals/departures are not established by hourly occupancy scores.", "",
              "![Executed model diagnostics](prediction_diagnostics.png)", "",
              "## Reproduction", "",
              "Create a separate Python 3.12 environment and install `scripts/cpft_evaluation_requirements.txt`. Run `python scripts/evaluate_cpft_models.py` from the repository root. Use `--threads 4` to bound TensorFlow CPU parallelism. `--limit-days 2 --skip-sensitivity --output reports/cpft_model_evaluation_smoke` is only a smoke test. `--render-only` regenerates the report/charts from completed outputs without executing the checkpoints again.", "",
              f"Measured runtime: {stats['runtime_seconds']:.1f} seconds on this machine, including reconstruction, one-step validation/test and three next-day policies. This is not a benchmark across 1,399 points. The JSON records source/checkpoint SHA-256 hashes and library versions; source files and checkpoint weights were unchanged. The web application database was not opened.", "",
              "Focused validation: `pytest tests/test_cpft_model_inputs.py tests/test_cpft.py tests/test_forecast_store.py -q`. Tests cover feature ordering, exact lag offsets, scaling, future-data perturbation invariance, causal baselines, batched timestamp ordering and both DST transitions. Actual checkpoint reproduction is checked during this evaluation.", "",
              f"Executed focused test results: {stats.get('focused_test_results', 'not supplied')}", ""]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/cpft_model_evaluation")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--limit-days", type=int, help="Smoke test only; omit for the full held-out period")
    parser.add_argument("--skip-sensitivity", action="store_true")
    parser.add_argument("--render-only", action="store_true", help="Regenerate report/charts from completed output files")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.render_only:
        stats = json.loads((args.output / "statistics.json").read_text(encoding="utf-8"))
        for relative_path, expected_hash in stats["source_sha256"].items():
            if hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest() != expected_hash:
                raise AssertionError("Cannot render this evaluation: original sources changed")
        if not (args.output / "reconstructed_preprocessing.json").exists():
            sessions = read_sessions(SOURCE.parent / "Station_2_39_139_28.csv")
            sheets = pd.read_excel(SOURCE / "outputs/EV_forecasting_upgraded_results.xlsx", sheet_name=["hourly_input"])
            _, scaler_av, scaler_kwh, _, _, preprocessing = prepare(sessions, sheets)
            write_preprocessing(args.output, stats["source_sha256"], stats["checkpoint_checks"]["availability_input"][0],
                                stats["checkpoint_export_reconciliation"]["threshold_reselected_on_validation"], scaler_av, scaler_kwh, preprocessing)
        predictions = pd.read_csv(args.output / "day_ahead_predictions.csv")
        daily = pd.read_csv(args.output / "daily_totals.csv", index_col="target_date")
        write_report(stats, predictions, daily, args.output)
        progress(f"Report: {args.output / 'report.md'}")
        return
    start = time.perf_counter()
    sessions_path = SOURCE.parent / "Station_2_39_139_28.csv"
    workbook_path = SOURCE / "outputs/EV_forecasting_upgraded_results.xlsx"
    source_files = [sessions_path, workbook_path, SOURCE / "outputs/best_availability.keras", SOURCE / "outputs/best_kwh.keras", SOURCE / "CPFT_pipeline_VS_Code_Python.py"]
    original_hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files}
    progress("Reconstructing original training features and fitted preprocessing...")
    sessions = read_sessions(sessions_path)
    sheets = pd.read_excel(workbook_path, sheet_name=["hourly_input", "metrics_summary", "test_availability", "test_kwh"])
    frame, scaler_av, scaler_kwh, bounds, proxies, preprocessing = prepare(sessions, sheets)
    progress("Loading existing Keras weights with the original custom occupancy model...")
    seq_len, predict_av, predict_energy, predict_batches, checkpoint_checks = load_checkpoints(frame, scaler_av, args.threads)
    threshold, one_step, reconciliation, one_step_rows = evaluate_one_step(frame, sheets, scaler_av, scaler_kwh, seq_len, predict_av, predict_energy, predict_batches)
    progress(f"One-hour test complete. Checkpoint/export match: {reconciliation['predictions_reproduce_saved_export']}; validation threshold: {threshold}")
    test_index = pd.DatetimeIndex(pd.to_datetime(sheets["test_kwh"].hour, utc=True))
    station_timezone = sessions.timezone.iloc[0]
    windows = next_day_windows(test_index, station_timezone)
    if args.limit_days:
        windows = windows[:args.limit_days]
    if not windows:
        raise ValueError("No complete held-out next-day windows")
    progress(f"Evaluating complete next-day forecasts issued at 18:00 {station_timezone}: {len(windows)} days...")
    predictions = day_ahead_forecasts(sessions, frame, windows, bounds, proxies, scaler_av, scaler_kwh, seq_len, threshold, predict_av, predict_energy)
    day_ahead, daily = summarize_day_ahead(predictions, sessions, windows, bounds)
    sensitivity = {}
    if not args.skip_sensitivity:
        for policy in ["full_hour", "carry_last_activity"]:
            alternative = day_ahead_forecasts(sessions, frame, windows, bounds, proxies, scaler_av, scaler_kwh, seq_len, threshold, predict_av, predict_energy, policy)
            sensitivity[policy] = dict(occupancy=classification_metrics(alternative.actual_occupied, alternative.occupied, alternative.occupancy_probability),
                                       energy=regression_metrics(alternative.actual_kwh, alternative.energy_kwh))
    for path in source_files:
        if hashlib.sha256(path.read_bytes()).hexdigest() != original_hashes[str(path.relative_to(ROOT))]:
            raise AssertionError("Source data/checkpoints changed during evaluation")
    stats = dict(executed_at_utc=datetime.now(timezone.utc).isoformat(), runtime_seconds=time.perf_counter()-start,
                 versions={name: importlib.metadata.version(name) for name in ["tensorflow", "keras", "numpy", "pandas", "scikit-learn", "openpyxl"]},
                 source_sha256=original_hashes, source_station=sessions.stationID.iloc[0], station_timezone=station_timezone,
                 sessions=len(sessions), charging_end_after_disconnect=int((sessions.chargeEndTime>sessions.disconnectTime).sum()),
                 preprocessing=preprocessing, checkpoint_checks=checkpoint_checks, checkpoint_export_reconciliation=reconciliation,
                 one_hour_ahead=one_step, day_ahead=day_ahead, connection_proxy_sensitivity=sensitivity,
                 next_day_test=dict(days=len(windows), hours=len(predictions), issue_hour_local=18,
                                    first_target=windows[0]["target_date"], last_target=windows[-1]["target_date"],
                                    leads=sorted(predictions.lead_hours.unique().tolist()),
                                    day_lengths=daily.index.to_series().map(predictions.groupby("target_date").size()).value_counts().to_dict()),
                 daily_energy=regression_metrics(daily.actual_kwh, daily.predicted_kwh),
                 smoke_test=bool(args.limit_days), no_training=True, original_sources_unchanged=True)
    (args.output / "statistics.json").write_text(json.dumps(stats, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    write_preprocessing(args.output, original_hashes, seq_len, threshold, scaler_av, scaler_kwh, preprocessing)
    one_step_rows.to_csv(args.output / "one_hour_predictions.csv", index_label="hour_utc")
    predictions.to_csv(args.output / "day_ahead_predictions.csv", index=False)
    daily.to_csv(args.output / "daily_totals.csv")
    write_report(stats, predictions, daily, args.output)
    progress(json.dumps({"one_hour_occupancy_f1": one_step["occupancy"]["f1"],
                         "one_hour_energy_mae": one_step["energy_ungated"]["mae"],
                         "next_day": {name: {"occupancy_f1": metrics["occupancy"]["f1"], "energy_mae": metrics["energy"]["mae"],
                                             "energy_bias_percent": metrics["energy"]["total_bias_percent"]} for name, metrics in day_ahead.items()},
                         "sensitivity": sensitivity}, indent=2))
    progress(f"Evaluation written to {args.output}")


if __name__ == "__main__":
    main()
