"""Spatial scenarios, source selection, cache isolation, and model-backed inference."""

from datetime import date, datetime, timedelta, timezone
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from flask import Flask
import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.cpft import day_window
from backend.cpft_runtime import CPFTUnavailable, FrozenScaler, get_runtime
from backend.scenario_profiles import grid, simulate_scenarios
from backend.scenario_sampling import ScenarioSession, generate_sessions
from backend.session_sources import SessionSourceService
from backend.spatial_profiles import profile_from_attributes, SpatialAtlas

UTC = timezone.utc
TARGET = date(2026, 10, 15)
CHARGERS = [dict(id=1, power=11., type="regular", latitude=52.36, longitude=4.90),
            dict(id=2, power=3.7, type="regular", latitude=52.37, longitude=4.91)]


def attributes(homes=5000, businesses=50, retail=5):
    return dict(buurtcode="BU-test", buurtnaam="Test", oppervlakte_land_in_ha=100,
                woningvoorraad=homes, aantal_bedrijfsvestigingen=businesses,
                aantal_bedrijven_handel_en_horeca=retail, bevolkingsdichtheid_inwoners_per_km2=8000)


def test_spatial_context_changes_behaviour_weights_and_handles_missing_values():
    residential = profile_from_attributes(attributes())
    retail = profile_from_attributes(attributes(homes=30, businesses=3000, retail=2800))
    assert residential["weights"]["residential"] > residential["weights"]["retail"]
    assert retail["weights"]["retail"] > retail["weights"]["residential"]
    assert sum(retail["weights"].values()) == pytest.approx(1)
    unknown = profile_from_attributes(dict(oppervlakte_land_in_ha=-99999999, woningvoorraad=-99999999))
    assert unknown["matched"] is False
    assert unknown["weights"]["mixed"] == 1


def test_geographic_join_is_by_coordinate_and_does_not_reclassify_access_type(tmp_path):
    import geopandas as gpd
    from shapely.geometry import box
    atlas = SpatialAtlas(tmp_path/"missing.gpkg")
    atlas.frame = gpd.GeoDataFrame([attributes(), attributes(homes=30, businesses=3000, retail=2800)],
        geometry=[box(4.8, 52.3, 4.9, 52.4), box(4.9, 52.3, 5.0, 52.4)], crs=4326)
    atlas.frame.loc[1, "buurtcode"] = "BU-retail"
    left = dict(id=1, latitude=52.35, longitude=4.85, type="regular")
    right = dict(id=2, latitude=52.35, longitude=4.95, type="regular")
    assert atlas.resolve(left)["neighbourhood_code"] == "BU-test"
    assert atlas.resolve(right)["neighbourhood_code"] == "BU-retail"
    assert left["type"] == right["type"] == "regular"
    assert atlas.resolve(dict(latitude=None, longitude=None))["matched"] is False
    assert atlas.resolve(dict(latitude=0, longitude=0))["fallback_reason"] == "outside_atlas"


@pytest.mark.parametrize("source", ["simple", "spatial"])
def test_sampler_is_reproducible_nonoverlapping_and_energy_feasible(source):
    start, _ = day_window(TARGET, "Europe/Amsterdam")
    _, end = day_window(TARGET+timedelta(days=14), "Europe/Amsterdam")
    profile = profile_from_attributes(attributes()) if source == "spatial" else None
    sessions = generate_sessions(CHARGERS[0], start, end, spatial_profile=profile, source=source, seed=9)
    assert sessions == generate_sessions(CHARGERS[0], start, end, spatial_profile=profile, source=source, seed=9)
    assert sessions
    for session in sessions:
        assert 0 <= session.energy_kwh <= 11*(session.end-session.start).total_seconds()/3600+1e-9
    assert all(left.end <= right.start for left, right in zip(sessions, sessions[1:]))


def test_ending_synthetic_history_at_issue_does_not_change_earlier_generated_sessions():
    start, _ = day_window(TARGET-timedelta(days=14), "Europe/Amsterdam")
    issue = datetime(2026, 10, 14, 16, tzinfo=UTC)
    end = issue+timedelta(hours=12)
    short = generate_sessions(CHARGERS[0], start, issue, seed=7)
    long = generate_sessions(CHARGERS[0], start, end, seed=7)
    assert short == [session for session in long if session.start < issue]


@pytest.mark.parametrize("strategy", ["afap", "alap", "avg"])
def test_profile_preserves_fractional_energy_and_overnight_connections(strategy):
    start = datetime(2026, 10, 14, tzinfo=UTC)
    end = start+timedelta(days=2)
    records = [ScenarioSession(1, start+timedelta(hours=23, minutes=55), start+timedelta(hours=26), 5.3)]
    profile, up, down = simulate_scenarios(CHARGERS[:1], records, start, end, strategy)
    assert len(profile) == 288
    assert sum(profile)/6 == pytest.approx(5.3)
    assert max(profile) <= 11
    assert min(up) >= 0 and max(down) <= 0


@pytest.mark.parametrize("target,expected", [(date(2026, 3, 29), 138), (date(2026, 10, 25), 150)])
def test_profiles_cover_complete_dst_target_days(target, expected):
    start, target_start = day_window(target-timedelta(days=1), "Europe/Amsterdam")
    _, end = day_window(target, "Europe/Amsterdam")
    timestamps, split = grid(start, end, target_start)
    assert len(timestamps)-split == expected
    sessions = generate_sessions(CHARGERS[0], start, end, seed=4)
    assert all(session.start.utcoffset() is not None for session in sessions)
    assert len(simulate_scenarios(CHARGERS[:1], sessions, start, end, "avg")[0]) == len(timestamps)


class FakeRuntime:
    def forecast(self, chargers, histories, issue, end):
        assert all(session.start < issue for values in histories.values() for session in values)
        result = {}
        for charger in chargers:
            rows, hour = [], issue
            while hour < end:
                occupied = int(hour.hour == 10)
                rows.append(dict(hour=hour, availability_forecast_prob=.9 if occupied else .1,
                    availability_forecast_bin=occupied, kWh_forecast_next_whole_period=2.*occupied))
                hour += timedelta(hours=1)
            result[charger["id"]] = rows
        return result


def test_all_sources_persist_separately_and_point_selection_does_not_change_scenario(tmp_path):
    calls = []
    def factory():
        calls.append(1)
        return FakeRuntime()
    service = SessionSourceService(tmp_path/"cache.sqlite", atlas_path=tmp_path/"missing.gpkg", runtime_factory=factory)
    by_source = {}
    for source in ["simple", "spatial", "cpft"]:
        records, meta = service.get(CHARGERS, TARGET, source=source)
        assert meta["synthetic"] and not meta["verified_observations"]
        subset, again = service.get(CHARGERS[:1], TARGET, source=source)
        assert subset == [session for session in records if session.cp_id == 1]
        assert again["cache_hits"] == 1
        by_source[source] = records
    assert len(calls) == 1
    assert by_source["cpft"] != by_source["spatial"]
    with service.cache.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM scenario_cache").fetchone()[0] == 6


def test_cpft_failure_does_not_fall_back_to_random_or_publish_partial_cache(tmp_path):
    def unavailable():
        raise CPFTUnavailable("model missing")
    service = SessionSourceService(tmp_path/"cache.sqlite", atlas_path=tmp_path/"missing.gpkg", runtime_factory=unavailable)
    with pytest.raises(CPFTUnavailable):
        service.get(CHARGERS, TARGET, source="cpft")
    with service.cache.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM scenario_cache").fetchone()[0] == 0


def test_frozen_scalers_keep_original_in_place_float32_arithmetic():
    source = np.array([[1.1234567, 17.123456]], np.float32)
    mean, scale = np.array([.123456789, 8.123456789]), np.array([.9123456789, 1.123456789])
    expected = source.copy()
    expected -= mean
    expected /= scale
    np.testing.assert_array_equal(FrozenScaler(mean, scale).transform(source), expected)
    assert FrozenScaler(mean, scale).transform(source).dtype == np.float32


@pytest.fixture
def scenario_client(tmp_path):
    from backend.views import station_data
    engine = create_engine(f"sqlite:///{(tmp_path/'app.sqlite').as_posix()}")
    with engine.begin() as connection:
        for sql in [
            "CREATE TABLE operators (id INTEGER PRIMARY KEY, name TEXT)",
            "CREATE TABLE locations (id INTEGER PRIMARY KEY, latitude REAL, longitude REAL, street TEXT)",
            "CREATE TABLE columns (id INTEGER PRIMARY KEY, operator_id INTEGER, location_id INTEGER)",
            "CREATE TABLE charging_points (id INTEGER PRIMARY KEY, column_id INTEGER, power REAL, type TEXT)",
            "CREATE TABLE sessions (id INTEGER PRIMARY KEY, cp_id INTEGER, start DATETIME, end DATETIME, consumption REAL)",
            "INSERT INTO operators VALUES (1,'test')", "INSERT INTO locations VALUES (1,52.36,4.90,'test')",
            "INSERT INTO columns VALUES (1,1,1)", "INSERT INTO charging_points VALUES (1,1,11,'regular')",
            "INSERT INTO sessions VALUES (1,1,'2026-10-14 08:00','2026-10-14 10:00',7)"]:
            connection.exec_driver_sql(sql)
    with Session(engine) as session:
        app = Flask(__name__)
        app.config.update(TESTING=True, aggregator_config={}, **{"station_data.db": SimpleNamespace(session=session)})
        app.extensions["session_source_service"] = SessionSourceService(tmp_path/"cache.sqlite", atlas_path=tmp_path/"missing.gpkg", runtime_factory=FakeRuntime)
        app.register_blueprint(station_data, url_prefix="/stations")
        yield app.test_client(), engine
    engine.dispose()


@pytest.mark.parametrize("source", ["simple", "spatial", "cpft"])
def test_api_selects_source_and_does_not_modify_stored_sessions(scenario_client, source):
    client, engine = scenario_client
    response = client.get(f"/stations/aggregate_load?selected_markers=1&strategy=avg&date=2026-10-15&session_source={source}")
    assert response.status_code == 200
    data = response.get_json()
    assert len(data["y"]) == len(data["timestamps"]) == 288
    assert data["source"]["source"] == source
    assert data["past_steps"] == 144
    again = client.get(f"/stations/aggregate_load?selected_markers=1&strategy=avg&date=2026-10-15&session_source={source}").get_json()
    assert data["y"] == again["y"]
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*),SUM(consumption) FROM sessions").one() == (1, 7)


@pytest.mark.parametrize("query", ["session_source=unknown", "session_source=simple&demand_assumption=unknown", "session_source=simple&seed=-1"])
def test_invalid_source_options_are_rejected(scenario_client, query):
    client, _ = scenario_client
    assert client.get(f"/stations/aggregate_load?selected_markers=1&strategy=avg&date=2026-10-15&{query}").status_code == 400


def test_post_selection_and_empty_cpft_selection(scenario_client):
    client, _ = scenario_client
    query = dict(selected_markers=[1], strategy="avg", date="2026-10-15", session_source="spatial")
    response = client.post("/stations/aggregate_load", json=query)
    assert response.status_code == 200
    assert response.get_json()["source"]["source"] == "spatial"
    query.update(selected_markers=[], session_source="cpft")
    empty = client.post("/stations/aggregate_load", json=query)
    assert empty.status_code == 200
    assert empty.get_json()["y"] == [0.]*288
    assert empty.get_json()["source"]["point_count"] == 0


@pytest.mark.parametrize("target,expected", [("2026-03-29", 138), ("2026-10-25", 150)])
def test_api_dst_day_lengths_and_optimizer_limit(scenario_client, target, expected):
    client, _ = scenario_client
    query = dict(selected_markers=[1], strategy="avg", date=target, session_source="simple")
    data = client.post("/stations/aggregate_load", json=query).get_json()
    assert len(data["y"])-data["past_steps"] == expected
    query["strategy"] = "ocost"
    assert client.post("/stations/aggregate_load", json=query).status_code == 422


def test_api_model_failure_is_explicit(scenario_client):
    client, _ = scenario_client
    def unavailable():
        raise CPFTUnavailable("CPFT model unavailable")
    client.application.extensions["session_source_service"].runtime_factory = unavailable
    response = client.post("/stations/aggregate_load", json=dict(selected_markers=[1], strategy="avg", date="2026-10-15", session_source="cpft"))
    assert response.status_code == 503
    assert "CPFT" in response.get_json()["error"]


def test_real_saved_checkpoints_reproduce_export_with_runtime_scalers():
    if importlib.util.find_spec("tensorflow") is None:
        pytest.skip("Install the cpft extra for checkpoint validation")
    runtime = get_runtime()
    from scripts.evaluate_cpft_models import scale_availability, scale_energy, SOURCE
    sheets = pd.read_excel(SOURCE/"outputs/EV_forecasting_upgraded_results.xlsx", sheet_name=["hourly_input", "test_availability", "test_kwh"])
    frame = sheets["hourly_input"]
    frame.index = pd.to_datetime(frame.hour, utc=True)
    for sheet, predictor, scaler, scale_fn, output in [
        ("test_availability", runtime.predict_av, runtime.scaler_av, scale_availability, "availability_pred_prob_for_auc"),
        ("test_kwh", runtime.predict_energy, runtime.scaler_energy, scale_energy, "kWh_pred")]:
        first = sheets[sheet].iloc[0]
        position = frame.index.get_loc(pd.Timestamp(first.hour, tz="UTC"))
        values = scale_fn(frame.iloc[position-72:position], scaler)[None]
        predicted = float(predictor(values).numpy()[0, 0])
        if sheet == "test_kwh":
            predicted = max(0, np.expm1(predicted))
        assert predicted == pytest.approx(float(first[output]), abs=1e-5)
