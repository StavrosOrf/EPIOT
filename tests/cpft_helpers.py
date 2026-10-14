"""Deterministic model stand-ins; no training or external services."""

from datetime import date, datetime, timedelta

from backend.cpft import UTC

TARGET = date(2026, 10, 14)
ISSUED = datetime(2026, 10, 13, 16, tzinfo=UTC)


def cpft_rows(start, end, energies=None):
    """CPFT forecast_whole_period records, with occupied bins given by index."""
    energies = energies or {}
    return [dict(
        hour=start + timedelta(hours=i),
        availability_forecast_prob=0.8 if i in energies else 0.1,
        availability_forecast_bin=int(i in energies),
        kWh_forecast_next_whole_period=energies.get(i, 0.0),
    ) for i in range(int((end - start).total_seconds() / 3600))]


class StubPredictor:
    def __init__(self, energies=None):
        self.energies = energies if energies is not None else {101: {8: 2.0, 9: 3.0}}
        self.calls = []

    def forecast(self, **kwargs):
        self.calls.append(kwargs)
        return cpft_rows(kwargs["start"], kwargs["end"], self.energies.get(kwargs["cp_id"]))


def write_test_library(path, timezone_name="Europe/Amsterdam", lead=16, kwh=2.0, entries=2, mark_volume=False, mark_weekday=False):
    """A tiny CPFT library in the real format, without TensorFlow.

    Every entry occupies one hour `lead` hours after the 18:00 issue (10:00 local
    on the target day) with `kwh` delivered (or 1 + the volume-bin index with
    `mark_volume`, or 1 + the context's weekday with `mark_weekday`), after a 3 kWh
    history connection 10 or 12 hours before issue.
    """
    import json
    import numpy as np
    from backend.cpft_library import HORIZON, current_inputs
    from scripts.build_cpft_library import FALLBACK, VOLUME_BINS, calendar_contexts
    contexts = calendar_contexts(timezone_name)
    cells = len(contexts)*len(VOLUME_BINS)*2
    total = cells*entries
    occupied = np.zeros((total, HORIZON), np.uint8)
    occupied[:, lead] = 1
    volume = (np.arange(total)//entries//2) % len(VOLUME_BINS)
    weekday = np.array([key[0] for key, _ in contexts])[np.arange(total)//(entries*2*len(VOLUME_BINS))]
    marked = 1.+volume if mark_volume else 1.+weekday if mark_weekday else np.full(total, kwh)
    energy = (occupied*marked[:, None]*1000).astype(np.uint16)
    starts = np.repeat(np.array([-10*3600, -12*3600], np.int32)[None], total, 0)[np.arange(total), np.arange(total) % 2]
    meta = dict(timezone=timezone_name, contexts=[list(key) for key, _ in contexts], mixtures=[list(FALLBACK)],
                volume_bins=list(VOLUME_BINS), inputs_sha256=current_inputs(), built_at="test")
    np.savez_compressed(path, meta=np.frombuffer(json.dumps(meta).encode(), np.uint8),
        cell_offsets=np.arange(cells+1, dtype=np.int64)*entries, probability_255=occupied*250, occupied=occupied,
        kwh_milli=energy, history_offsets=np.arange(total+1, dtype=np.int64), history_start=starts,
        history_end=starts+2*3600, history_energy=np.full(total, 3., np.float32))
    return path
