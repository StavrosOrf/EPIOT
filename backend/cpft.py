"""Adapt a CPFT predictor's hourly output into validated session forecasts.

The predictor is injected: importing this module never trains a model or loads
TensorFlow. A predictor must return records from CPFT's forecast_whole_period
schema, covering the requested UTC interval. Its history and fitted artifacts
are owned by the caller. This adapter does not claim to implement CPFT inference.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from math import isfinite
from typing import Any, Iterable, Mapping, Protocol
from zoneinfo import ZoneInfo

UTC = timezone.utc
HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class HourPrediction:
    timestamp: datetime
    occupancy_probability: float
    occupied: bool
    energy_kwh: float


@dataclass(frozen=True)
class SessionPrediction:
    start: datetime
    end: datetime
    energy_kwh: float
    start_censored: bool = False
    end_censored: bool = False


@dataclass(frozen=True)
class PointForecast:
    cp_id: int
    hours: tuple[HourPrediction, ...]
    sessions: tuple[SessionPrediction, ...]


@dataclass(frozen=True)
class ForecastBatch:
    run_id: str
    target_date: date
    timezone: str
    issued_at: datetime
    model_version: str
    points: tuple[PointForecast, ...]


class CPFTPredictor(Protocol):
    def forecast(
        self, *, cp_id: int, history: Any, start: datetime, end: datetime
    ) -> Iterable[Mapping[str, Any]]:
        """Return CPFT hourly records; start/end are aware UTC boundaries."""
        ...


def as_utc(value: datetime | str) -> datetime:
    """Reject ambiguous naive timestamps rather than guessing their timezone."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("Forecast timestamps must include a timezone")
    return value.astimezone(UTC)


def day_window(target_date: date, timezone_name: str) -> tuple[datetime, datetime]:
    zone = ZoneInfo(timezone_name)
    start = datetime.combine(target_date, time.min, zone).astimezone(UTC)
    end = datetime.combine(target_date + timedelta(days=1), time.min, zone).astimezone(UTC)
    return start, end


def sessions_from_hours(hours: tuple[HourPrediction, ...]) -> tuple[SessionPrediction, ...]:
    """Group occupied bins; boundary flags mean arrival/departure is unknown."""
    sessions = []
    start = None
    energy = 0.0
    for i, hour in enumerate(hours):
        if hour.occupied:
            if start is None:
                start = hour.timestamp
            energy += hour.energy_kwh
        if start is not None and (not hour.occupied or i == len(hours) - 1):
            end = hour.timestamp + HOUR if hour.occupied else hour.timestamp
            sessions.append(SessionPrediction(
                start, end, energy,
                start_censored=start == hours[0].timestamp,
                end_censored=hour.occupied and i == len(hours) - 1,
            ))
            start, energy = None, 0.0
    return tuple(sessions)


def adapt_cpft_output(
    cp_id: int, rows: Iterable[Mapping[str, Any]], *, target_date: date,
    timezone_name: str = "Europe/Amsterdam",
) -> PointForecast:
    """Validate a complete local day of CPFT output and retain its hourly data.

    Input timestamps must be timezone-aware. For timezone-free Excel exports,
    explicitly restore UTC before calling this function, as specified by CPFT.
    Availability 1 means occupied. An unoccupied bin must have zero energy.
    """
    if isinstance(cp_id, bool) or not isinstance(cp_id, int) or cp_id <= 0:
        raise ValueError("cp_id must be a positive integer")
    hours = []
    for row in rows:
        try:
            timestamp = as_utc(row["hour"])
            probability = float(row["availability_forecast_prob"])
            occupied = float(row["availability_forecast_bin"])
            energy = float(row["kWh_forecast_next_whole_period"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid CPFT record for charging point {cp_id}: {exc}") from exc
        if not isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError("Occupancy probability must be finite and between 0 and 1")
        if occupied not in (0, 1):
            raise ValueError("Occupancy must be binary (0 or 1)")
        if not isfinite(energy) or energy < 0:
            raise ValueError("Energy must be finite and nonnegative")
        if not occupied and energy != 0:
            raise ValueError("An unoccupied hour cannot have positive energy")
        hours.append(HourPrediction(timestamp, probability, bool(occupied), energy))
    hours.sort(key=lambda h: h.timestamp)
    start, end = day_window(target_date, timezone_name)
    expected = tuple(start + i * HOUR for i in range(int((end - start) / HOUR)))
    if tuple(h.timestamp for h in hours) != expected:
        raise ValueError("CPFT output must cover the complete target day exactly once per hour")
    result = tuple(hours)
    return PointForecast(cp_id, result, sessions_from_hours(result))


def predict_session_forecasts(
    predictor: CPFTPredictor, histories: Mapping[int, Any], *, run_id: str,
    target_date: date, issued_at: datetime, model_version: str,
    timezone_name: str = "Europe/Amsterdam",
) -> ForecastBatch:
    """Call the configured predictor once per point, without database writes.

    Failure at any point propagates to the caller; no partial batch is returned.
    Passing the same run_id to persistence makes a retry replace that run.
    """
    if not run_id.strip() or not model_version.strip():
        raise ValueError("run_id and model_version are required")
    issued_at = as_utc(issued_at)
    start, end = day_window(target_date, timezone_name)
    points = []
    for cp_id, history in sorted(histories.items()):
        rows = predictor.forecast(cp_id=cp_id, history=history, start=start, end=end)
        points.append(adapt_cpft_output(
            cp_id, rows, target_date=target_date, timezone_name=timezone_name,
        ))
    return ForecastBatch(run_id, target_date, timezone_name, issued_at, model_version, tuple(points))
