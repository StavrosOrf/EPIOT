"""Batched inference using the existing CPFT checkpoints and verified scalers.

Only the offline CPFT library build (scripts/build_cpft_library.py) and model
validation run this. Requests sample the prebuilt library and never load
TensorFlow. Features are built for a whole batch of points at once with numpy
and reproduce the row-by-row construction in scripts/evaluate_cpft_models.py
(tests compare both), including its float32/float64 scaling arithmetic.
"""

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from threading import Lock

import numpy as np

from backend.scenario_sampling import ROOT
from backend.session_frame import bin_integrals

MANIFEST = ROOT / "backend/data/cpft_preprocessing.json"
MODEL_DIR = ROOT / "others/CPFT-main/CPFT-tool/CPFT_VS_Code_Python/outputs"
LAGS = (1, 2, 3, 6, 12, 24, 48, 72, 168)
WINDOWS = (6, 24, 168)
HOUR = 3600
_runtime_lock = Lock()


class CPFTUnavailable(RuntimeError):
    pass


class FrozenScaler:
    """StandardScaler.transform arithmetic, without fitting or importing sklearn."""
    def __init__(self, mean, scale):
        self.mean = np.asarray(mean, float)
        self.scale = np.asarray(scale, float)
        if not (np.isfinite(self.mean).all() and np.isfinite(self.scale).all() and (self.scale > 0).all()):
            raise ValueError("Invalid frozen scaler")

    def transform(self, values):
        values = np.asarray(values).copy()
        values -= self.mean
        values /= self.scale
        return values


def calendar_columns(timestamps):
    """CPFT's UTC calendar fields for epoch-second timestamps."""
    timestamps = np.asarray(timestamps, np.int64)
    hour = (timestamps//HOUR) % 24
    dow = (timestamps//86400+3) % 7  # 1970-01-01 was a Thursday; Monday is 0
    month = np.array(np.asarray(timestamps, "datetime64[s]").astype("datetime64[M]").astype(int) % 12+1)
    return {"hour_of_day": hour.astype(float), "day_type": (dow >= 5).astype(float), "month": month.astype(float),
            "hod_sin": np.sin(2*np.pi*hour/24), "hod_cos": np.cos(2*np.pi*hour/24),
            "dow_sin": np.sin(2*np.pi*dow/7), "dow_cos": np.cos(2*np.pi*dow/7),
            "mon_sin": np.sin(2*np.pi*(month-1)/12), "mon_cos": np.cos(2*np.pi*(month-1)/12)}


def hourly_observations(sessions, rows, count, issue, hours):
    """observations_at_issue for many points: hourly bins ending at the issue hour.

    Occupancy uses connections observed before issue; energy only connections
    already completed at issue, spread uniformly over their connection time.
    """
    if issue % HOUR:
        raise ValueError("Issue time must be an exact hour")
    first = issue-hours*HOUR
    relevant = (sessions.start < issue) & (sessions.end > first)
    rows, start, end, energy = rows[relevant], sessions.start[relevant], sessions.end[relevant], sessions.energy_kwh[relevant]
    connected = np.minimum(end, issue)
    minutes = bin_integrals(start-first, connected-first, 60., hours, HOUR, rows, count)
    done = end <= issue
    energy = bin_integrals(start[done]-first, end[done]-first, energy[done]*HOUR/(end[done]-start[done]),
                           hours, HOUR, rows[done], count)
    # Connections touching each hour, counted once per connection
    low = np.maximum(((start-first)//HOUR).astype(np.int64), 0)
    high = np.minimum(np.ceil((connected-first)/HOUR).astype(np.int64)-1, hours-1)
    delta = np.zeros(count*hours+1)
    np.add.at(delta, rows*hours+low, 1.)
    np.add.at(delta, rows*hours+high+1, -1.)
    counts = np.cumsum(delta)[:-1].reshape(count, hours)
    reshape = (lambda value: value.reshape(count, hours)) if count == 1 else (lambda value: value)
    return {"availability": (counts > 0).astype(float), "occupancy_count": counts,
            "connected_minutes": reshape(minutes), "kWhDelivered": reshape(energy)}


def feature_columns(timestamps, availability_history, energy_history, availability, energy, count, minutes):
    """feature_row for a batch: lags and rolling statistics use strictly earlier hours."""
    columns = calendar_columns(timestamps)
    columns.update(availability=availability, kWhDelivered=energy, occupancy_count=count, connected_minutes=minutes)
    for target, history in (("availability", availability_history), ("kWhDelivered", energy_history)):
        if history.shape[-1] < max(LAGS) or not np.isfinite(history).all():
            raise ValueError("At least 168 finite preceding hours are required")
        for lag in LAGS:
            columns[f"{target}_lag{lag}"] = history[..., -lag]
        for width in WINDOWS:
            window = history[..., -width:]
            columns[f"{target}_roll_mean{width}"] = window.mean(-1)
            columns[f"{target}_roll_std{width}"] = window.std(-1, ddof=1)
    return columns


def input_windows(observations, bounds, sequence_length, issue):
    """causal_input_rows for a batch: the last `sequence_length` hourly feature rows."""
    observations = dict(observations)
    for name, (lower, upper) in bounds.items():
        observations[name] = np.clip(observations[name], lower, upper)
    hours = observations["availability"].shape[1]
    positions = np.arange(hours-sequence_length, hours)
    timestamps = issue-(hours-positions)*HOUR
    windows = {}
    for target in ("availability", "kWhDelivered"):
        history = observations[target]
        # Hours preceding each position, newest last: shape (points, positions, 168)
        span = np.lib.stride_tricks.sliding_window_view(history, max(LAGS), axis=1)
        windows[target] = span[:, positions-max(LAGS)]
    columns = feature_columns(timestamps[None, :], windows["availability"], windows["kWhDelivered"],
        *(observations[name][:, positions] for name in ("availability", "kWhDelivered", "occupancy_count", "connected_minutes")))
    return columns, observations


class CPFTModelRuntime:
    def __init__(self, manifest=MANIFEST, threads=2):
        self.bundle = json.loads(Path(manifest).read_text(encoding="utf-8"))
        self.availability_columns = self.bundle["availability_features"]
        self.energy_columns = self.bundle["energy_features"]
        for relative_path, expected in self.bundle["source_sha256"].items():
            path = ROOT / relative_path.replace("\\", "/")
            if path.suffix == ".keras" or path.name == "CPFT_pipeline_VS_Code_Python.py":
                if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    raise CPFTUnavailable(f"CPFT artifact does not match preprocessing: {path.name}")
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
        os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
        try:
            import tensorflow as tf
            from tensorflow import keras
            from scripts.evaluate_cpft_models import AVAIL_COLS, ENERGY_COLS, source_definitions
        except ImportError as exc:
            raise CPFTUnavailable("CPFT inference needs the project cpft extra (TensorFlow).") from exc
        if self.availability_columns != AVAIL_COLS or self.energy_columns != ENERGY_COLS:
            raise CPFTUnavailable("CPFT feature order differs from its saved preprocessing")
        try:
            tf.config.threading.set_intra_op_parallelism_threads(threads)
            tf.config.threading.set_inter_op_parallelism_threads(1)
        except RuntimeError:
            pass  # Another TensorFlow user has already initialized this process.
        custom = source_definitions(["BinaryAvailabilityModel"], {"tf": tf, "keras": keras, "layers": keras.layers})
        self.availability = keras.models.load_model(MODEL_DIR / "best_availability.keras", custom_objects=custom, compile=False, safe_mode=True)
        self.energy = keras.models.load_model(MODEL_DIR / "best_kwh.keras", compile=False, safe_mode=True)
        self.seq_len = self.bundle["sequence_length"]
        if self.availability.seq_len != self.seq_len or self.energy.input_shape[1:] != (self.seq_len, len(ENERGY_COLS)):
            raise CPFTUnavailable("CPFT checkpoint dimensions do not match preprocessing")
        self.scaler_av = FrozenScaler(self.bundle["availability_mean"], self.bundle["availability_scale"])
        self.scaler_energy = FrozenScaler(self.bundle["energy_mean"], self.bundle["energy_scale"])
        self.bounds = self.bundle["preprocessing"]["clipping_bounds"]
        self.proxies = self.bundle["preprocessing"]["future_connection_feature_proxies"]
        self.threshold = self.bundle["occupancy_threshold"]
        self.lock = Lock()

        @tf.function(input_signature=[tf.TensorSpec([None, self.seq_len, len(AVAIL_COLS)], tf.float32)])
        def predict_av(value):
            return self.availability(value, training=False)

        @tf.function(input_signature=[tf.TensorSpec([None, self.seq_len, len(ENERGY_COLS)], tf.float32)])
        def predict_energy(value):
            return self.energy(value, training=False)

        self.predict_av, self.predict_energy = predict_av, predict_energy

    def scale(self, columns):
        """scale_availability and scale_energy of evaluate_cpft_models, on stacked columns."""
        availability = np.stack([np.broadcast_to(columns[name], columns["availability"].shape)
                                 for name in self.availability_columns], -1).astype(np.float32)
        availability = self.scaler_av.transform(availability).astype(np.float32)
        energy = np.stack([np.broadcast_to(columns[name], columns["availability"].shape)
                           for name in self.energy_columns], -1).astype(float)
        energy[..., 1:] = self.scaler_energy.transform(energy[..., 1:])
        return availability, energy.astype(np.float32)

    def forecast(self, sessions, ids, powers, issue, horizon):
        """Recursive hourly forecasts from `issue` (epoch seconds) for `horizon` hours.

        Returns occupancy probability, occupied flags and capped hourly kWh,
        each shaped (points, horizon), in the order of `ids`.
        """
        ids = np.asarray(ids, np.int64)
        lookup = {int(cp_id): index for index, cp_id in enumerate(ids)}
        known = np.isin(sessions.cp_id, ids)
        sessions = sessions.select(known)
        rows = np.array([lookup[int(cp_id)] for cp_id in sessions.cp_id], np.int64)
        observed = hourly_observations(sessions, rows, len(ids), issue, self.seq_len+max(LAGS))
        columns, observed = input_windows(observed, self.bounds, self.seq_len, issue)
        av_sequence, energy_sequence = self.scale(columns)
        av_history, energy_history = observed["availability"], observed["kWhDelivered"]
        powers = np.asarray(powers, float)
        output = np.zeros((3, len(ids), horizon))
        with self.lock:
            for lead in range(horizon):
                probability = self.predict_av(av_sequence).numpy().reshape(-1)
                occupied = probability >= self.threshold
                energy = np.maximum(0, np.expm1(self.predict_energy(energy_sequence).numpy().reshape(-1)))
                # A whole occupied hour cannot deliver more than rated kWh.
                energy = np.minimum(np.where(occupied, energy, 0), powers)
                output[:, :, lead] = probability, occupied, energy
                feedback = np.clip(energy, *self.bounds["kWhDelivered"])
                row = feature_columns(np.array([issue+lead*HOUR]), av_history, energy_history, occupied.astype(float),
                    feedback, occupied*self.proxies["occupancy_count"], occupied*self.proxies["connected_minutes"])
                av_row, energy_row = self.scale(row)
                av_sequence = np.concatenate([av_sequence[:, 1:], av_row[:, None]], axis=1)
                energy_sequence = np.concatenate([energy_sequence[:, 1:], energy_row[:, None]], axis=1)
                av_history = np.column_stack([av_history, occupied.astype(float)])
                energy_history = np.column_stack([energy_history, feedback])
        return output[0], output[1].astype(bool), output[2]


@lru_cache(maxsize=1)
def _cached_runtime(threads):
    return CPFTModelRuntime(threads=threads)


def get_runtime(threads=2):
    with _runtime_lock:
        return _cached_runtime(threads)
