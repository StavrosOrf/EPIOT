"""API error shape, request validation, the stored-session day query and its index."""

import datetime
import importlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from flask import Flask, abort
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.api_errors import register_json_errors
from backend.models import Session as StoredSession
from backend.request_args import (RequestTooLarge, check_point_days, demand_assumption, request_arguments,
                                  scenario_seed, session_source)
from backend.views import station_data

ROOT = Path(__file__).resolve().parents[1]


def stations_client(tmp_path, sessions=()):
    """The station blueprint over a minimal schema; the legacy stored-session path needs no SpatiaLite."""
    engine = create_engine(f"sqlite:///{(tmp_path/'app.sqlite').as_posix()}")
    with engine.begin() as connection:
        for sql in [
            "CREATE TABLE operators (id INTEGER PRIMARY KEY, name TEXT)",
            "CREATE TABLE locations (id INTEGER PRIMARY KEY, street TEXT, latitude REAL, longitude REAL, country TEXT)",
            "CREATE TABLE columns (id INTEGER PRIMARY KEY, operator_id INTEGER, location_id INTEGER)",
            "CREATE TABLE charging_points (id INTEGER PRIMARY KEY, column_id INTEGER, power REAL, type TEXT)",
            "CREATE TABLE sessions (id INTEGER PRIMARY KEY, cp_id INTEGER, start DATETIME, end DATETIME, consumption REAL)",
            "INSERT INTO operators VALUES (1,'Operator')", "INSERT INTO locations VALUES (1,'Street',52.36,4.90,'NL')",
            "INSERT INTO columns VALUES (1,1,1)", "INSERT INTO charging_points VALUES (1,1,6,'regular')",
        ]:
            connection.exec_driver_sql(sql)
        for number, (start, end, energy) in enumerate(sessions, 1):
            connection.exec_driver_sql("INSERT INTO sessions VALUES (?,?,?,?,?)", (number, 1, start, end, energy))
    session = Session(engine)
    app = Flask(__name__)
    app.config.update(TESTING=True, aggregator_config={}, **{"station_data.db": SimpleNamespace(session=session, engine=engine)})
    app.register_blueprint(station_data, url_prefix="/stations")
    register_json_errors(app, {"station_data"})
    return app.test_client(), session, engine


def test_aborts_in_api_blueprints_are_json_and_pages_keep_html(tmp_path):
    client, session, engine = stations_client(tmp_path)
    try:
        response = client.post("/stations/within", data="not geojson")
        assert response.status_code == 400
        assert response.is_json
        assert response.get_json() == {"error": "Could not handle request, expected GeoJSON"}
        # Outside the API blueprints the default HTML error remains
        assert client.get("/nowhere").mimetype == "text/html"
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize("date", ["", "yesterday", "2025-13-01", "2025-1-5x"])
def test_stored_session_endpoint_rejects_a_bad_date_with_400(tmp_path, date):
    client, session, engine = stations_client(tmp_path)
    try:
        response = client.post("/stations/aggregate_load", json=dict(selected_markers=[1], strategy="afap", date=date))
        assert response.status_code == 400
        assert "date" in response.get_json()["error"]
    finally:
        session.close()
        engine.dispose()


def post_load(client, **overrides):
    query = dict(selected_markers=[1], strategy="afap", date="2025-01-15")
    query.update(overrides)
    return client.post("/stations/aggregate_load", json=query)


def test_stored_sessions_go_through_the_scenario_engine_for_the_window(tmp_path):
    # Chosen day 2025-01-15, so the window is 2025-01-14 and 2025-01-15 (local), 288 ten-minute steps
    sessions = [
        ("2025-01-15 10:00:00.000000", "2025-01-15 11:00:00.000000", 3.0),   # on the day
        ("2025-01-14 08:00:00.000000", "2025-01-14 09:00:00.000000", 2.0),   # the day before
        ("2025-01-13 08:00:00.000000", "2025-01-13 09:00:00.000000", 5.0),   # two days before: outside
        ("2025-01-16 08:00:00.000000", "2025-01-16 09:00:00.000000", 5.0),   # the day after: outside
        ("2025-01-15 00:00:00.000000", "2025-01-15 00:30:00.000000", 1.0),   # starts exactly at midnight
        ("2025-01-14 22:00:00.000000", "2025-01-15 02:00:00.000000", 24.0),  # overnight: 22:00-02:00
    ]
    client, session, engine = stations_client(tmp_path, sessions)
    try:
        response = post_load(client)
        assert response.status_code == 200
        data = response.get_json()
        load = data["y"]
        assert len(load) == 288 and len(data["timestamps"]) == 288 and data["past_steps"] == 144
        # 6 kW charger: 1 kWh per step
        assert load[48:50] == [6, 6]                # the day before, 08:00
        assert load[204:207] == [6, 6, 6]           # the day, 10:00
        assert load[144] == 6 + 6                   # midnight session and the overnight connection together
        # The overnight connection charges 22:00-02:00 as one block: 24 steps from step 132
        assert load[132:144] == [6]*12 and load[145:156] == [6]*11 and load[156] == 0
        assert sum(load)/6 == 2 + 3 + 1 + 24
        source = data["source"]
        assert source["source"] == "database" and source["synthetic"] is False
        assert source["session_count"] == 4 and source["point_count"] == 1
        assert "flex_polytope" in data
    finally:
        session.close()
        engine.dispose()


def test_stored_sessions_follow_the_chosen_strategy(tmp_path):
    client, session, engine = stations_client(tmp_path, [("2025-01-15 10:00:00.000000", "2025-01-15 14:00:00.000000", 5.0)])
    try:
        early = 144+10*6
        late = 144+14*6
        afap = post_load(client, strategy="afap").get_json()["y"]
        alap = post_load(client, strategy="alap").get_json()["y"]
        avg = post_load(client, strategy="avg").get_json()["y"]
        assert afap[early:early+5] == [6]*5 and sum(afap)/6 == pytest.approx(5)
        assert alap[late-5:late] == [6]*5 and sum(alap)/6 == pytest.approx(5)
        assert avg[early:late] == pytest.approx([1.25]*24) and sum(avg)/6 == pytest.approx(5)
        # minimum-carbon scheduling needs a generated session source
        assert post_load(client, strategy="mincarbon").status_code == 400
    finally:
        session.close()
        engine.dispose()


def test_unknown_points_and_bad_ids_are_rejected_for_stored_sessions_too(tmp_path):
    client, session, engine = stations_client(tmp_path)
    try:
        assert post_load(client, selected_markers=[1, 999]).status_code == 400
        assert post_load(client, selected_markers="1,abc").status_code == 400
        assert post_load(client, strategy="nonsense").status_code == 400
    finally:
        session.close()
        engine.dispose()


def test_requests_beyond_the_point_day_limit_are_refused_with_a_clear_message(tmp_path):
    client, session, engine = stations_client(tmp_path)
    try:
        client.application.config["MAX_POINT_DAYS"] = 3   # the load profile spans two days per point
        assert post_load(client, selected_markers=[1]).status_code == 200
        response = post_load(client, selected_markers=[1, 2])
        assert response.status_code == 422
        assert "4 point-days" in response.get_json()["error"] and "limit is 3" in response.get_json()["error"]
    finally:
        session.close()
        engine.dispose()


def test_point_day_limit_defaults_and_can_be_switched_off():
    check_point_days({}, 3000, 333)                       # inside the default limit
    with pytest.raises(RequestTooLarge, match="the limit is 1,000,000"):
        check_point_days({}, 3000, 367)
    check_point_days({"MAX_POINT_DAYS": 0}, 10**6, 366)   # 0 disables the limit
    check_point_days({"MAX_POINT_DAYS": "50"}, 5, 10)     # environment values arrive as text
    with pytest.raises(RequestTooLarge):
        check_point_days({"MAX_POINT_DAYS": "50"}, 6, 10)


def test_an_empty_selection_is_a_zero_day_on_the_same_grid(tmp_path):
    client, session, engine = stations_client(tmp_path)
    try:
        data = post_load(client, selected_markers=[]).get_json()
        assert len(data["y"]) == 288 and set(data["y"]) == {0.0}
        assert data["source"]["point_count"] == 0
    finally:
        session.close()
        engine.dispose()


def test_session_indexes_serve_the_day_query_and_roll_back(tmp_path):
    path = ROOT / "migrations/1792108800_session_indexes.py"
    spec = importlib.util.spec_from_file_location("session_indexes", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "1792022400"
    engine = create_engine(f"sqlite:///{(tmp_path/'indexes.sqlite').as_posix()}")
    plan = ("EXPLAIN QUERY PLAN SELECT cp_id FROM sessions "
            "WHERE cp_id IN (1, 2) AND start >= '2025-01-15' AND start < '2025-01-16'")
    with engine.begin() as connection:
        StoredSession.__table__.drop(connection, checkfirst=True)
        # The model carries the indexes; a database that predates them needs the migration
        connection.exec_driver_sql("CREATE TABLE sessions (id INTEGER PRIMARY KEY, cp_id INTEGER, start DATETIME, end DATETIME, consumption REAL)")
        assert "SCAN" in connection.exec_driver_sql(plan).fetchall()[0][-1]
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()  # safe to run again
        assert "ix_sessions_cp_id_start" in connection.exec_driver_sql(plan).fetchall()[0][-1]
        names = {row[1] for row in connection.exec_driver_sql("PRAGMA index_list(sessions)")}
        assert {"ix_sessions_cp_id_start", "ix_sessions_cp_id_end"} <= names
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert not {row[1] for row in connection.exec_driver_sql("PRAGMA index_list(sessions)")}
    engine.dispose()
    assert {index.name for index in StoredSession.__table__.indexes} == {"ix_sessions_cp_id_start", "ix_sessions_cp_id_end"}


class Arguments(dict):
    """A plain mapping stands in for request.args / a JSON body."""


def test_shared_argument_validation():
    assert session_source(Arguments()) == "database"
    assert session_source(Arguments(session_source=" simple ")) == "simple"
    with pytest.raises(ValueError, match="Unknown session source"):
        session_source(Arguments(session_source="nonsense"))
    assert demand_assumption(Arguments()) == "base"
    with pytest.raises(ValueError, match="Unknown demand assumption"):
        demand_assumption(Arguments(demand_assumption="extreme"))
    assert scenario_seed(Arguments()) == 42
    assert scenario_seed(Arguments(seed="7")) == 7
    for bad in (-1, 2**32):
        with pytest.raises(ValueError, match="Seed must be"):
            scenario_seed(Arguments(seed=bad))
    with pytest.raises(ValueError):
        scenario_seed(Arguments(seed="abc"))


def test_request_arguments_reads_the_body_for_post_and_the_query_for_get():
    app = Flask(__name__)
    with app.test_request_context("/x", method="POST", json=dict(a=1)):
        from flask import request
        assert request_arguments(request)["a"] == 1
    with app.test_request_context("/x?a=2"):
        from flask import request
        assert request_arguments(request)["a"] == "2"
    with app.test_request_context("/x", method="POST", json=[1, 2]):
        from flask import request
        with pytest.raises(ValueError, match="Expected a JSON object"):
            request_arguments(request)


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    """app.py imported against a throw-away database, with SpatiaLite faked."""
    monkeypatch.chdir(ROOT)  # the app resolves instance and static folders from the working tree
    monkeypatch.setenv("FLASK_SQLALCHEMY_ENGINES", '{"default": "sqlite:///%s"}' % (tmp_path / "app.sqlite").as_posix())
    monkeypatch.delenv("EPIOT_DEBUG", raising=False)
    sys.modules.pop("app", None)
    module = importlib.import_module("app")
    yield module
    with module.app.app_context():
        module.db.engine.dispose()
    sys.modules.pop("app", None)


def test_importing_app_is_production_unless_debug_is_requested(app_module, monkeypatch):
    # A WSGI server imports the module, so it never gets the debugger by accident
    assert app_module.DEBUG is False
    monkeypatch.setenv("EPIOT_DEBUG", "1")
    assert app_module.env_flag("EPIOT_DEBUG", default=False) is True
    monkeypatch.setenv("EPIOT_DEBUG", "off")
    assert app_module.env_flag("EPIOT_DEBUG", default=True) is False
    monkeypatch.delenv("EPIOT_DEBUG")
    assert app_module.env_flag("EPIOT_DEBUG", default=True) is True


def test_healthz_reports_the_database_and_spatialite(app_module, monkeypatch):
    client = app_module.app.test_client()
    # No SpatiaLite function in the fake: the check fails without leaking details
    monkeypatch.setattr(app_module, "load_spatialite", lambda connection: None)
    response = client.get("/healthz")
    assert response.status_code == 503
    assert response.get_json() == {"status": "error"}
    with app_module.app.app_context():
        app_module.db.engine.dispose()  # a new connection runs the (fake) SpatiaLite loader
    monkeypatch.setattr(app_module, "load_spatialite",
                        lambda connection: connection.create_function("spatialite_version", 0, lambda: "5.1-test"))
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "spatialite": "5.1-test"}
    assert response.headers["Cache-Control"] == "no-store"


def test_scripts_are_javascript_and_other_static_files_keep_their_own_type(app_module):
    client = app_module.app.test_client()
    script = client.get("/static/scripts/script.js")
    assert script.status_code == 200
    assert script.mimetype == "application/javascript"
    stylesheet = client.get("/static/css/styles.css")
    assert stylesheet.status_code == 200
    assert stylesheet.mimetype == "text/css"
    logo = client.get("/static/images/charger_icon.png")
    assert logo.mimetype == "image/png"
