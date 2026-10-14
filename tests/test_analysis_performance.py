"""Regression checks for avoided work and unchanged analysis results."""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from flask import Flask
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from tests.test_kpi_sources import client, request
from tests.test_session_sources import CHARGERS
from backend.spatial_profiles import SpatialAtlas


def test_spatial_resolution_reused_until_coordinates_or_atlas_change(tmp_path):
    atlas = SpatialAtlas(tmp_path/"missing.gpkg")
    atlas._resolve_coordinates.cache_clear()
    atlas.resolve(CHARGERS[0])
    atlas.resolve(dict(CHARGERS[0], id=999))
    assert atlas._resolve_coordinates.cache_info().hits == 1
    atlas.resolve(dict(CHARGERS[0], latitude=52.0))
    SpatialAtlas(tmp_path/"replacement.gpkg").resolve(CHARGERS[0])
    assert atlas._resolve_coordinates.cache_info().misses == 3


@pytest.mark.parametrize("source", ["database", "simple", "spatial", "cpft"])
def test_basic_kpis_skip_grid_and_scheduling_with_identical_statistics(client, monkeypatch, source):
    browser, _ = client
    full = request(browser, session_source=source).get_json()

    def forbidden(*args, **kwargs):
        raise AssertionError("Basic KPIs must not load grid data or schedule charging")

    monkeypatch.setattr("backend.kpi.user.app_grid_hours", forbidden)
    monkeypatch.setattr("backend.kpi.statistics.EnvironmentalComparison", forbidden)
    response = request(browser, session_source=source, section="basic")
    assert response.status_code == 200
    basic = response.get_json()
    assert "environment" not in basic
    assert not any(key.startswith("co2_") for key in basic)
    for key, value in basic.items():
        if key not in {"source", "summary", "section"}:
            assert value == full[key]
    expected = {key: value for key, value in full["summary"].items() if key != "scheduled_energy_kwh"}
    assert basic["summary"].keys() == expected.keys()
    for key, value in expected.items():
        assert basic["summary"][key] == (pytest.approx(value) if isinstance(value, (int, float)) else value)


def test_environment_only_matches_full_and_skips_behavioural_calculation(client, monkeypatch):
    browser, _ = client
    full = request(browser).get_json()

    def forbidden(*args, **kwargs):
        raise AssertionError("Environment-only requests must skip behavioural calculation")

    monkeypatch.setattr("backend.kpi.user.calculate_kpis", forbidden)
    response = request(browser, section="environment")
    assert response.status_code == 200
    environment = response.get_json()
    assert environment["environment"] == full["environment"]
    assert "arrival_dist_wd" not in environment
    for key in environment:
        if key.startswith(("co2_", "renewable_")):
            assert environment[key] == full[key]
    assert request(browser, section="unknown").status_code == 400


@pytest.mark.parametrize("day", [date(2025, 3, 30), date(2025, 10, 26)])
def test_basic_summary_matches_full_across_dst(day):
    from backend.cpft import day_window
    from backend.kpi.statistics import calculate_kpis
    from backend.scenario_sampling import ScenarioSession
    left, right = day_window(day, "Europe/Amsterdam")
    records = [ScenarioSession(1, left-timedelta(hours=1), left+timedelta(hours=1), 2),
               ScenarioSession(1, left+timedelta(hours=2), right+timedelta(hours=3), 20)]
    args = (CHARGERS, [(day, records)], day, day, "Europe/Amsterdam")
    full, basic = calculate_kpis(*args), calculate_kpis(*args, include_environment=False)
    assert basic["summary"]["energy_kwh"] == pytest.approx(full["summary"]["energy_kwh"])
    assert basic["range"] == full["range"]


def test_compact_area_endpoints_and_revision_invalidation(tmp_path):
    from backend.views import station_data
    from backend.features import features_data
    from shapely import wkt
    engine = create_engine(f"sqlite:///{(tmp_path/'app.sqlite').as_posix()}")

    @event.listens_for(engine, "connect")
    def spatial_functions(connection, _):
        connection.create_function("GeomFromEWKT", 1, lambda value: value)
        connection.create_function("ST_Within", 2, lambda point, polygon: wkt.loads(point).within(wkt.loads(polygon)))

    with engine.begin() as db:
        for sql in [
            "CREATE TABLE operators (id INTEGER PRIMARY KEY)",
            "CREATE TABLE locations (id INTEGER PRIMARY KEY,latitude REAL,longitude REAL,geom TEXT)",
            "CREATE TABLE columns (id INTEGER PRIMARY KEY,operator_id INTEGER,location_id INTEGER)",
            "CREATE TABLE charging_points (id INTEGER PRIMARY KEY,column_id INTEGER)",
            "CREATE TABLE transformers (id INTEGER PRIMARY KEY,location_id INTEGER,type TEXT)",
            "INSERT INTO operators VALUES (1)",
            "INSERT INTO locations VALUES (1,52.35,4.85,'POINT(4.85 52.35)'),(2,53,6,'POINT(6 53)')",
            "INSERT INTO columns VALUES (1,1,1),(2,1,2)",
            "INSERT INTO charging_points VALUES (17,1),(19,2)",
            "INSERT INTO transformers VALUES (25,1,'Middle'),(26,1,'Low'),(27,2,'Middle')",
        ]:
            db.exec_driver_sql(sql)
    with Session(engine) as session:
        app = Flask(__name__)
        app.config.update(TESTING=True, GRID_DATA_CACHE=str(tmp_path/"grid.sqlite"),
                          **{"station_data.db": SimpleNamespace(session=session)})
        app.register_blueprint(station_data, url_prefix="/stations")
        app.register_blueprint(features_data, url_prefix="/features")
        browser = app.test_client()
        polygon = dict(type="Polygon", coordinates=[[[4.8,52.3],[4.9,52.3],[4.9,52.4],[4.8,52.4],[4.8,52.3]]])
        assert browser.post("/stations/within?ids_only=1", json=polygon).get_json() == {"ids": [17]}
        assert browser.post("/features/transformers/within?ids_only=1",
                            json=dict(polygon, tr_type="Middle")).get_json() == {"ids": [25]}
        first = browser.get("/stations/analysis-version")
        assert first.headers["Cache-Control"] == "no-store"
        assert browser.get("/stations/analysis-version").get_json() == first.get_json()
        (tmp_path/"grid.sqlite").write_bytes(b"updated")
        grid_change = browser.get("/stations/analysis-version").get_json()
        assert grid_change["infrastructure"] == first.get_json()["infrastructure"]
        assert grid_change["analysis"] != first.get_json()["analysis"]
        session.rollback()
        with engine.begin() as db:
            db.exec_driver_sql("INSERT INTO charging_points VALUES (18,1)")
        changed = browser.get("/stations/analysis-version").get_json()
        assert changed["infrastructure"] != first.get_json()["infrastructure"]
        assert browser.post("/stations/within?ids_only=1", json=polygon).get_json() == {"ids": [17,18]}
    engine.dispose()
