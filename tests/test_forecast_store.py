"""Prediction -> actual SQLite save -> fresh connection fetch, without app data."""

from dataclasses import replace
from datetime import timedelta

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event, inspect
from sqlalchemy.exc import IntegrityError

from backend.cpft import adapt_cpft_output, day_window
from backend.forecast_store import fetch_forecast_batch, save_forecast_batch
from backend.models import ForecastHour, ForecastRun, ForecastSession
from .cpft_helpers import cpft_rows


def row_counts(engine):
    with engine.connect() as connection:
        return tuple(connection.exec_driver_sql(f"SELECT COUNT(*) FROM {name}").scalar_one()
                     for name in ("forecast_runs", "forecast_hourly", "forecast_sessions", "sessions"))


def test_predict_save_fetch_round_trip_preserves_all_fields_and_observations(forecast_engine, batch):
    save_forecast_batch(forecast_engine, batch)
    forecast_engine.dispose()  # force the fetch to use a fresh connection
    restored = fetch_forecast_batch(forecast_engine, batch.run_id)
    assert restored == batch
    assert row_counts(forecast_engine) == (1, 48, 1, 1)
    with forecast_engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT cp_id, consumption FROM sessions").all() == [(101, 8.0)]
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


def test_retry_is_idempotent_and_replaces_old_sessions(forecast_engine, batch):
    save_forecast_batch(forecast_engine, batch)
    save_forecast_batch(forecast_engine, batch)
    assert row_counts(forecast_engine) == (1, 48, 1, 1)
    empty_point = adapt_cpft_output(
        101, cpft_rows(*day_window(batch.target_date, batch.timezone)), target_date=batch.target_date,
    )
    updated = replace(batch, points=(empty_point, batch.points[1]))
    save_forecast_batch(forecast_engine, updated)
    assert fetch_forecast_batch(forecast_engine, batch.run_id) == updated
    assert row_counts(forecast_engine) == (1, 48, 0, 1)


@pytest.mark.parametrize("cp_ids,expected", [(None, [101, 202]), ([101], [101]), ([202], [202]), ([], []), ([999], [])])
def test_fetch_filters_charging_points_and_preserves_zero_session_results(forecast_engine, batch, cp_ids, expected):
    save_forecast_batch(forecast_engine, batch)
    result = fetch_forecast_batch(forecast_engine, batch.run_id, cp_ids=cp_ids)
    assert [p.cp_id for p in result.points] == expected
    if expected == [202]:
        assert result.points[0].sessions == ()
        assert len(result.points[0].hours) == 24


def test_unknown_run_is_distinct_from_zero_demand(forecast_engine, batch):
    assert fetch_forecast_batch(forecast_engine, "missing") is None
    save_forecast_batch(forecast_engine, batch)
    assert fetch_forecast_batch(forecast_engine, batch.run_id, cp_ids=[202]) is not None


def test_runs_are_fetched_explicitly_without_mixing_revisions(forecast_engine, batch):
    newer = replace(batch, run_id="revised", model_version="v2", issued_at=batch.issued_at + timedelta(hours=1))
    save_forecast_batch(forecast_engine, batch)
    save_forecast_batch(forecast_engine, newer)
    assert fetch_forecast_batch(forecast_engine, batch.run_id) == batch
    assert fetch_forecast_batch(forecast_engine, newer.run_id) == newer


@pytest.mark.parametrize("changes", [
    {"model_version": "different"}, {"issued_at": None}, {"points": ()},
])
def test_existing_run_id_cannot_change_identity(forecast_engine, batch, changes):
    save_forecast_batch(forecast_engine, batch)
    if changes.get("issued_at", "absent") is None:
        changes = {"issued_at": batch.issued_at + timedelta(hours=1)}
    with pytest.raises(ValueError, match="different forecast batch"):
        save_forecast_batch(forecast_engine, replace(batch, **changes))
    assert fetch_forecast_batch(forecast_engine, batch.run_id) == batch


def test_unknown_point_rejects_the_entire_batch(forecast_engine, batch):
    invalid = replace(batch, points=(batch.points[0], replace(batch.points[1], cp_id=999)))
    with pytest.raises(ValueError, match="Unknown charging point IDs"):
        save_forecast_batch(forecast_engine, invalid)
    assert row_counts(forecast_engine) == (0, 0, 0, 1)


def test_duplicate_points_are_rejected(forecast_engine, batch):
    with pytest.raises(ValueError, match="only once"):
        save_forecast_batch(forecast_engine, replace(batch, points=(batch.points[0],) * 2))
    assert row_counts(forecast_engine) == (0, 0, 0, 1)


def test_inconsistent_derived_sessions_cannot_be_written(forecast_engine, batch):
    invalid_point = replace(batch.points[0], sessions=())
    with pytest.raises(ValueError, match="sessions must match"):
        save_forecast_batch(forecast_engine, replace(batch, points=(invalid_point, batch.points[1])))
    assert row_counts(forecast_engine) == (0, 0, 0, 1)


def test_database_failure_rolls_back_deletes_and_partial_inserts(forecast_engine, batch):
    save_forecast_batch(forecast_engine, batch)
    with forecast_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER fail_forecast BEFORE INSERT ON forecast_hourly "
            "WHEN NEW.energy_kwh = 9 BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        )
    point = adapt_cpft_output(101, cpft_rows(*day_window(batch.target_date, batch.timezone), {8: 9.0}),
                              target_date=batch.target_date)
    with pytest.raises(IntegrityError, match="injected failure"):
        save_forecast_batch(forecast_engine, replace(batch, points=(point, batch.points[1])))
    assert fetch_forecast_batch(forecast_engine, batch.run_id) == batch
    assert row_counts(forecast_engine) == (1, 48, 1, 1)


def test_failed_first_write_leaves_no_run_or_partial_results(forecast_engine, batch):
    with forecast_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER fail_forecast BEFORE INSERT ON forecast_hourly "
            "WHEN NEW.cp_id = 202 BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        )
    with pytest.raises(IntegrityError, match="injected failure"):
        save_forecast_batch(forecast_engine, batch)
    assert fetch_forecast_batch(forecast_engine, batch.run_id) is None
    assert row_counts(forecast_engine) == (0, 0, 0, 1)


def test_fetch_keeps_a_consistent_snapshot_during_concurrent_publication(forecast_engine, batch):
    with forecast_engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode=WAL").scalar_one() == "wal"
    save_forecast_batch(forecast_engine, batch)
    point = adapt_cpft_output(101, cpft_rows(*day_window(batch.target_date, batch.timezone), {8: 7.0}),
                              target_date=batch.target_date)
    updated = replace(batch, points=(point, batch.points[1]))
    published = False

    def publish_after_run_read(connection, cursor, statement, parameters, context, executemany):
        nonlocal published
        if not published and statement.lstrip().startswith("SELECT") and "FROM forecast_runs" in statement:
            published = True
            # A second real connection writes between the reader's SELECTs.
            save_forecast_batch(forecast_engine, updated)

    event.listen(forecast_engine, "after_cursor_execute", publish_after_run_read)
    try:
        snapshot = fetch_forecast_batch(forecast_engine, batch.run_id)
    finally:
        event.remove(forecast_engine, "after_cursor_execute", publish_after_run_read)
    assert published
    assert snapshot == batch
    assert fetch_forecast_batch(forecast_engine, batch.run_id) == updated


def test_migration_matches_models_and_downgrade_keeps_observations(forecast_engine, forecast_migration):
    inspector = inspect(forecast_engine)
    for model in (ForecastRun, ForecastHour, ForecastSession):
        columns = inspector.get_columns(model.__tablename__)
        assert {c["name"] for c in columns} == set(model.__table__.columns.keys())
    with forecast_engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            forecast_migration.downgrade()
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM sessions").scalar_one() == 1
    assert "forecast_runs" not in inspect(forecast_engine).get_table_names()
