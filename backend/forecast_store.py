"""Atomic save and fetch operations for CPFT forecast batches.

Callers pass their configured SQLAlchemy engine. These functions never import
the Flask application or open instance/default.sqlite implicitly. Apply the
forecast migration before using them with an application database.
"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.cpft import (
    UTC, ForecastBatch, HourPrediction, PointForecast, SessionPrediction,
    adapt_cpft_output, as_utc,
)
from backend.models import ChargingPoint, ForecastHour, ForecastRun, ForecastSession


def _metadata(batch):
    return dict(
        target_date=batch.target_date, timezone=batch.timezone,
        issued_at=as_utc(batch.issued_at).replace(tzinfo=None),
        model_version=batch.model_version,
    )


def save_forecast_batch(engine, batch: ForecastBatch) -> None:
    """Save all points atomically; retrying an identical run ID adds no duplicates.

    A run ID cannot be reused for different issue metadata or point membership.
    A new revision should use a new run ID. Observed Session rows are untouched.
    """
    if not batch.run_id.strip() or not batch.model_version.strip():
        raise ValueError("run_id and model_version are required")
    ids = [point.cp_id for point in batch.points]
    if len(ids) != len(set(ids)):
        raise ValueError("A charging point may appear only once per batch")
    # Revalidate at the write boundary, including objects constructed directly.
    for point in batch.points:
        validated = adapt_cpft_output(point.cp_id, [dict(
            hour=h.timestamp, availability_forecast_prob=h.occupancy_probability,
            availability_forecast_bin=h.occupied, kWh_forecast_next_whole_period=h.energy_kwh,
        ) for h in point.hours], target_date=batch.target_date, timezone_name=batch.timezone)
        if validated != point:
            raise ValueError("Forecast sessions must match their validated hourly predictions")
    metadata = _metadata(batch)
    with Session(engine) as db, db.begin():
        known = set(db.scalars(select(ChargingPoint.id).where(ChargingPoint.id.in_(ids))))
        if known != set(ids):
            raise ValueError(f"Unknown charging point IDs: {sorted(set(ids) - known)}")
        existing = db.get(ForecastRun, batch.run_id)
        if existing is not None:
            old_ids = set(db.scalars(select(ForecastHour.cp_id).where(
                ForecastHour.run_id == batch.run_id).distinct()))
            if any(getattr(existing, key) != value for key, value in metadata.items()) or old_ids != set(ids):
                raise ValueError("run_id already belongs to a different forecast batch")
            db.execute(delete(ForecastSession).where(ForecastSession.run_id == batch.run_id))
            db.execute(delete(ForecastHour).where(ForecastHour.run_id == batch.run_id))
        else:
            db.add(ForecastRun(id=batch.run_id, **metadata))
            db.flush()
        for point in batch.points:
            db.add_all(ForecastHour(
                run_id=batch.run_id, cp_id=point.cp_id,
                timestamp=h.timestamp.astimezone(UTC).replace(tzinfo=None),
                occupancy_probability=h.occupancy_probability,
                occupied=h.occupied, energy_kwh=h.energy_kwh,
            ) for h in point.hours)
            db.add_all(ForecastSession(
                run_id=batch.run_id, cp_id=point.cp_id, session_index=i,
                start=s.start.astimezone(UTC).replace(tzinfo=None),
                end=s.end.astimezone(UTC).replace(tzinfo=None), energy_kwh=s.energy_kwh,
                start_censored=s.start_censored, end_censored=s.end_censored,
            ) for i, s in enumerate(point.sessions))


def fetch_forecast_batch(engine, run_id: str, *, cp_ids=None) -> ForecastBatch | None:
    """Read one committed run in a single database snapshot, optionally by point.

    Unknown run returns None. A known run with no matching points has points=().
    Zero-occupancy forecasts still contain their hourly predictions.
    """
    # Explicit BEGIN gives SQLite a snapshot spanning all three SELECTs, even
    # with sqlite3's legacy transaction control on supported Python versions.
    with engine.connect() as connection:
        if engine.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN")
        else:
            connection = connection.execution_options(isolation_level="REPEATABLE READ")
            connection.begin()
        with Session(bind=connection) as db:
            run = db.get(ForecastRun, run_id)
            if run is None:
                return None
            hours_query = select(ForecastHour).where(ForecastHour.run_id == run_id)
            sessions_query = select(ForecastSession).where(ForecastSession.run_id == run_id)
            if cp_ids is not None:
                ids = tuple(cp_ids)
                hours_query = hours_query.where(ForecastHour.cp_id.in_(ids))
                sessions_query = sessions_query.where(ForecastSession.cp_id.in_(ids))
            hours_by_point = {}
            sessions_by_point = {}
            for h in db.scalars(hours_query.order_by(ForecastHour.cp_id, ForecastHour.timestamp)):
                hours_by_point.setdefault(h.cp_id, []).append(HourPrediction(
                    h.timestamp.replace(tzinfo=UTC), h.occupancy_probability, h.occupied, h.energy_kwh,
                ))
            for s in db.scalars(sessions_query.order_by(ForecastSession.cp_id, ForecastSession.session_index)):
                sessions_by_point.setdefault(s.cp_id, []).append(SessionPrediction(
                    s.start.replace(tzinfo=UTC), s.end.replace(tzinfo=UTC), s.energy_kwh,
                    s.start_censored, s.end_censored,
                ))
            return ForecastBatch(
                run.id, run.target_date, run.timezone, run.issued_at.replace(tzinfo=UTC), run.model_version,
                tuple(PointForecast(cp_id, tuple(hours), tuple(sessions_by_point.get(cp_id, ())))
                      for cp_id, hours in hours_by_point.items()),
            )
