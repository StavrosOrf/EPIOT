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
