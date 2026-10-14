"""Lazy, bounded inference using the existing CPFT checkpoints and verified scalers."""

from datetime import timedelta
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
from threading import Lock

import numpy as np
import pandas as pd

from backend.scenario_sampling import ROOT, ScenarioSession, point_power

MANIFEST = ROOT / "backend/data/cpft_preprocessing.json"
MODEL_DIR = ROOT / "others/CPFT-main/CPFT-tool/CPFT_VS_Code_Python/outputs"
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


class CPFTModelRuntime:
    def __init__(self, manifest=MANIFEST, threads=2):
        # Share the exact feature construction exercised by the checkpoint audit.
        from scripts.evaluate_cpft_models import AVAIL_COLS, ENERGY_COLS, source_definitions
        self.bundle = json.loads(Path(manifest).read_text(encoding="utf-8"))
        if self.bundle["availability_features"] != AVAIL_COLS or self.bundle["energy_features"] != ENERGY_COLS:
            raise CPFTUnavailable("CPFT feature order differs from its saved preprocessing")
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
        except ImportError as exc:
            raise CPFTUnavailable("CPFT inference is unavailable. Install the project cpft extra or precompute its scenarios.") from exc
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

    def forecast(self, chargers, histories, issue, end):
        from scripts.evaluate_cpft_models import (
            observations_at_issue, causal_input_rows, feature_row, scale_availability, scale_energy,
        )
        initial, raw_history = [], []
        for charger in chargers:
            records = histories[int(charger["id"])]
            frame = pd.DataFrame([dict(connectionTime=session.start, disconnectTime=session.end,
                                       chargeEndTime=session.end, kWhDelivered=session.energy_kwh) for session in records],
                                 columns=["connectionTime", "disconnectTime", "chargeEndTime", "kWhDelivered"])
            for column in ["connectionTime", "disconnectTime", "chargeEndTime"]:
                frame[column] = pd.to_datetime(frame[column], utc=True)
            observed = observations_at_issue(frame, issue, self.seq_len+168)
            rows, history = causal_input_rows(observed, self.bounds, self.seq_len)
            initial.append(rows)
            raw_history.append(history)
        av_sequence = np.stack([scale_availability(rows, self.scaler_av) for rows in initial])
        energy_sequence = np.stack([scale_energy(rows, self.scaler_energy) for rows in initial])
        av_history = np.stack([rows.availability.to_numpy() for rows in raw_history])
        energy_history = np.stack([rows.kWhDelivered.to_numpy() for rows in raw_history])
        points = {int(charger["id"]): [] for charger in chargers}
        horizon = int((end-issue).total_seconds()/3600)
        with self.lock:
            for lead in range(horizon):
                timestamp = issue+timedelta(hours=lead)
                probability = self.predict_av(av_sequence).numpy().reshape(-1)
                occupied = probability >= self.threshold
                energy = np.maximum(0, np.expm1(self.predict_energy(energy_sequence).numpy().reshape(-1)))
                energy = np.where(occupied, energy, 0)
                # A whole occupied hour cannot deliver more than rated kWh.
                energy = np.minimum(energy, [point_power(charger) for charger in chargers])
                rows = []
                for i, charger in enumerate(chargers):
                    points[int(charger["id"])].append(dict(hour=timestamp, availability_forecast_prob=float(probability[i]),
                        availability_forecast_bin=int(occupied[i]), kWh_forecast_next_whole_period=float(energy[i])))
                    feedback = np.clip(energy[i], *self.bounds["kWhDelivered"])
                    rows.append(feature_row(timestamp, av_history[i], energy_history[i], occupied[i], feedback,
                        float(occupied[i])*self.proxies["occupancy_count"],
                        float(occupied[i])*self.proxies["connected_minutes"]))
                rows = pd.DataFrame(rows)
                av_sequence = np.concatenate([av_sequence[:, 1:], scale_availability(rows, self.scaler_av)[:, None]], axis=1)
                energy_sequence = np.concatenate([energy_sequence[:, 1:], scale_energy(rows, self.scaler_energy)[:, None]], axis=1)
                av_history = np.column_stack([av_history, occupied.astype(float)])
                energy_history = np.column_stack([energy_history, rows.kWhDelivered.to_numpy()])
        return points


def sessions_from_forecast(cp_id, rows):
    from backend.cpft import HourPrediction, sessions_from_hours
    hours = tuple(HourPrediction(row["hour"], row["availability_forecast_prob"], bool(row["availability_forecast_bin"]),
                                row["kWh_forecast_next_whole_period"]) for row in rows)
    return [ScenarioSession(cp_id, session.start, session.end, session.energy_kwh) for session in sessions_from_hours(hours)]


@lru_cache(maxsize=1)
def _cached_runtime():
    return CPFTModelRuntime()


def get_runtime():
    with _runtime_lock:
        return _cached_runtime()
