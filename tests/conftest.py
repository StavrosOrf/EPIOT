"""Forecast tests use disposable SQLite files and the real forecast migration.

Only the charging-point ID directory is needed from the spatial schema. Creating
that minimal parent table keeps these tests independent of SpatiaLite and avoids
importing app.py, whose default configuration opens the application database.
"""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event

from backend.models import Session as ObservedSession
from backend.cpft import predict_session_forecasts
from .cpft_helpers import ISSUED, TARGET, StubPredictor


@pytest.fixture
def batch():
    return predict_session_forecasts(
        StubPredictor(), {101: "history-101", 202: "history-202"},
        run_id="day-ahead-2026-10-14", target_date=TARGET, issued_at=ISSUED,
        model_version="cpft-test-v1",
    )


@pytest.fixture
def forecast_migration():
    path = Path(__file__).resolve().parents[1] / "migrations/1791849600_cpft_forecasts.py"
    spec = importlib.util.spec_from_file_location("forecast_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def forecast_engine(tmp_path, forecast_migration):
    engine = create_engine(f"sqlite:///{(tmp_path / 'forecasts.sqlite').as_posix()}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE charging_points (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO charging_points VALUES (101), (202)")
        ObservedSession.__table__.create(connection)
        connection.exec_driver_sql(
            "INSERT INTO sessions (id, cp_id, start, end, consumption) "
            "VALUES (1, 101, '2026-10-12 09:00:00', '2026-10-12 11:00:00', 8.0)"
        )
        with Operations.context(MigrationContext.configure(connection)):
            forecast_migration.upgrade()
    try:
        yield engine
    finally:
        engine.dispose()
