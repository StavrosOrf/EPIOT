"""Deterministic model stand-ins; no training or external services."""

from datetime import date, datetime, timedelta

import pytest

from backend.cpft import UTC

def require_tensorflow(reason="Install the cpft extra for checkpoint inference"):
    """Skip unless TensorFlow imports.

    An installed but unusable build (for example one compiled against NumPy 1,
    which raises AttributeError, not ImportError) cannot run the checkpoints
    any more than a missing one.
    """
    try:
        import tensorflow  # noqa: F401
    except Exception as error:
        pytest.skip(f"{reason} (TensorFlow unavailable: {type(error).__name__}: {error})")


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


def write_test_library(path, timezone_name="Europe/Amsterdam", lead=None, kwh=2.0, entries=2, mark_volume=False, mark_weekday=False,
                       run=1, ongoing_until=None):
    """A tiny CPFT library in the real format, without TensorFlow.

    Every entry is occupied for `run` hours from `lead` hours after the 18:00 issue
    (16, which is 10:00 local on the target day, unless given), after a 3 kWh history
    connection 10 or 12 hours before issue. `mark_volume` moves the run later by the
    volume-bin index and `mark_weekday` by the context's weekday, so a sample shows
    which cell it came from. With `ongoing_until` the history connection (3 kWh, from
    3 hours before issue) is still running at issue, due to end that many hours after
    it, and the run starts at issue unless `lead` says otherwise. The hourly kWh is
    stored as `kwh` but is not what the sampler delivers.
    """
    import json
    import numpy as np
    from backend.cpft_library import HORIZON, current_inputs
    from scripts.build_cpft_library import FALLBACK, VOLUME_BINS, calendar_contexts
    contexts = calendar_contexts(timezone_name)
    cells = len(contexts)*len(VOLUME_BINS)*2
    total = cells*entries
    volume = (np.arange(total)//entries//2) % len(VOLUME_BINS)
    weekday = np.array([key[0] for key, _ in contexts])[np.arange(total)//(entries*2*len(VOLUME_BINS))]
    lead = (16 if ongoing_until is None else 0) if lead is None else lead
    first = lead+(volume if mark_volume else weekday if mark_weekday else np.zeros(total, int))
    hours = np.arange(HORIZON)[None, :]
    occupied = ((hours >= first[:, None]) & (hours < (first+run)[:, None])).astype(np.uint8)
    energy = (occupied*kwh*1000).astype(np.uint16)
    starts = np.repeat(np.array([-10*3600, -12*3600], np.int32)[None], total, 0)[np.arange(total), np.arange(total) % 2]
    ends = starts+2*3600
    if ongoing_until is not None:
        starts, ends = np.full(total, -3*3600, np.int32), np.full(total, int(ongoing_until*3600), np.int32)
    meta = dict(timezone=timezone_name, contexts=[list(key) for key, _ in contexts], mixtures=[list(FALLBACK)],
                volume_bins=list(VOLUME_BINS), inputs_sha256=current_inputs(), built_at="test")
    np.savez_compressed(path, meta=np.frombuffer(json.dumps(meta).encode(), np.uint8),
        cell_offsets=np.arange(cells+1, dtype=np.int64)*entries, probability_255=occupied*250, occupied=occupied,
        kwh_milli=energy, history_offsets=np.arange(total+1, dtype=np.int64), history_start=starts,
        history_end=ends, history_energy=np.full(total, 3., np.float32))
    return path
