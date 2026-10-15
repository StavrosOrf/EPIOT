"""Spatial scenarios, source selection, on-request generation and the CPFT library."""

from datetime import date, datetime, timedelta, timezone
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
from tests import reflex_fakes
from tests.cpft_helpers import require_tensorflow, write_test_library

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


def test_bundled_atlas_is_read_without_gdal():
    """GDAL in the same process as mod_spatialite crashes, so the GeoPackage is read with sqlite3."""
    from backend.spatial_profiles import DEFAULT_ATLAS, SpatialAtlas
    atlas = SpatialAtlas(DEFAULT_ATLAS)
    assert len(atlas.frame) == 481 and atlas.frame.crs.to_epsg() == 4326 and atlas.frame.geometry.is_valid.all()
    centre = atlas.resolve(dict(latitude=52.3731, longitude=4.8926))  # Dam square
    assert centre["matched"] and centre["neighbourhood_code"].startswith("BU0363")


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


@pytest.fixture
def library(tmp_path):
    return write_test_library(tmp_path/"library.npz")


def test_all_sources_are_generated_on_request_and_point_selection_does_not_change_scenario(tmp_path, library):
    service = SessionSourceService(atlas_path=tmp_path/"missing.gpkg", library_path=library)
    by_source = {}
    for source in ["simple", "spatial", "cpft"]:
        records, meta = service.get(CHARGERS, TARGET, source=source)
        assert meta["synthetic"] and not meta["verified_observations"]
        assert meta["generated"] == "on request"
        subset, _ = service.get(CHARGERS[:1], TARGET, source=source)
        assert subset.equals(records.select(records.cp_id == 1))
        assert service.get(list(reversed(CHARGERS)), TARGET, source=source)[0].equals(records)
        by_source[source] = records
    assert not by_source["cpft"].equals(by_source["spatial"])
    # Nothing is written anywhere: there is no scenario cache to prepare or invalidate
    assert sorted(path.name for path in tmp_path.iterdir()) == ["library.npz"]


def test_missing_cpft_library_is_explicit_and_never_falls_back_to_random(tmp_path):
    service = SessionSourceService(atlas_path=tmp_path/"missing.gpkg", library_path=tmp_path/"missing.npz")
    with pytest.raises(CPFTUnavailable, match="library is missing"):
        service.get(CHARGERS, TARGET, source="cpft")


def test_cpft_library_built_from_other_inputs_is_rejected(tmp_path, monkeypatch):
    path = write_test_library(tmp_path/"stale.npz")
    monkeypatch.setattr("backend.cpft_library.current_inputs", lambda line_ending=b"\n": "changed checkpoints")
    service = SessionSourceService(atlas_path=tmp_path/"missing.gpkg", library_path=path)
    with pytest.raises(CPFTUnavailable, match="Rebuild"):
        service.get(CHARGERS, TARGET, source="cpft")


def test_cpft_library_built_from_crlf_inputs_is_accepted(tmp_path, monkeypatch):
    """A library built on Windows hashed the same priors with CRLF line endings."""
    from backend.cpft_library import current_inputs
    crlf = current_inputs(b"\r\n")
    assert crlf != current_inputs()
    monkeypatch.setattr("backend.cpft_library.current_inputs", lambda line_ending=b"\n": crlf)
    path = write_test_library(tmp_path/"windows.npz")  # stamped with the CRLF digest
    monkeypatch.setattr("backend.cpft_library.current_inputs",
                        lambda line_ending=b"\n": crlf if line_ending == b"\r\n" else "linux checkout")
    service = SessionSourceService(atlas_path=tmp_path/"missing.gpkg", library_path=path)
    assert len(service.get(CHARGERS, TARGET, source="cpft")[0]) >= 0


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
            "CREATE TABLE locations (id INTEGER PRIMARY KEY, latitude REAL, longitude REAL, street TEXT, country TEXT)",
            "CREATE TABLE columns (id INTEGER PRIMARY KEY, operator_id INTEGER, location_id INTEGER)",
            "CREATE TABLE charging_points (id INTEGER PRIMARY KEY, column_id INTEGER, power REAL, type TEXT)",
            "CREATE TABLE sessions (id INTEGER PRIMARY KEY, cp_id INTEGER, start DATETIME, end DATETIME, consumption REAL)",
            "CREATE TABLE power_mixes (id INTEGER PRIMARY KEY, country_zone TEXT, datetime DATETIME, renewable_percentage REAL, co2_intensity REAL)",
            "INSERT INTO operators VALUES (1,'test')", "INSERT INTO locations VALUES (1,52.36,4.90,'test','Netherlands')",
            "INSERT INTO columns VALUES (1,1,1)", "INSERT INTO charging_points VALUES (1,1,11,'regular')",
            "INSERT INTO sessions VALUES (1,1,'2026-10-14 08:00','2026-10-14 10:00',7)"]:
            connection.exec_driver_sql(sql)
    with Session(engine) as session:
        app = Flask(__name__)
        app.config.update(TESTING=True, aggregator_config={}, GRID_DATA_CACHE=str(tmp_path/'grid.sqlite'), **{"station_data.db": SimpleNamespace(session=session)})
        app.extensions["session_source_service"] = SessionSourceService(atlas_path=tmp_path/"missing.gpkg",
            library_path=write_test_library(tmp_path/"library.npz"))
        # Cost strategies use stand-ins for ReFlex and Energy-Charts: no network in tests
        app.extensions["cost_optimiser"] = reflex_fakes.optimiser(tmp_path)
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
@pytest.mark.parametrize("strategy", ["avg", "ocost", "v2g"])
def test_api_dst_day_lengths_for_every_strategy(scenario_client, target, expected, strategy):
    client, _ = scenario_client
    query = dict(selected_markers=[1], strategy=strategy, date=target, session_source="simple")
    response = client.post("/stations/aggregate_load", json=query)
    assert response.status_code == 200
    data = response.get_json()
    assert len(data["y"])-data["past_steps"] == expected


def test_cost_strategies_answer_at_once_and_reflex_replaces_the_plans_later(scenario_client):
    client, _ = scenario_client
    optimiser = client.application.extensions["cost_optimiser"]
    query = dict(selected_markers=[1], date="2026-10-15", session_source="simple")
    first = {strategy: client.post("/stations/aggregate_load", json={**query, "strategy": strategy}).get_json()
             for strategy in ("ocost", "v2g")}
    for strategy, profile in first.items():
        source = profile["source"]
        assert source["optimisation"]["engine"] == "DRIVE2X ReFlex" and "scheduling_note" in source
        # Nothing waited for ReFlex: the exact local optimum stands in for its plans
        assert source["optimisation"]["reflex_pending"] > 0
    # V2G has its own bidirectional envelope, which its schedule lies in and which reaches below zero
    v2g_envelope = first["v2g"]["flex_polytope"]
    assert v2g_envelope["model"] == "bidirectional" and v2g_envelope["schedule_feasible"] is True
    assert min(v2g_envelope["power_min_kw"]) < 0 and first["ocost"]["flex_polytope"]["model"] == "one-way"
    assert all(up >= 0 >= down for up, down in zip(first["v2g"]["up_flex"], first["v2g"]["down_flex"]))
    assert optimiser.wait_idle(timeout=30)
    for strategy, profile in first.items():
        again = client.post("/stations/aggregate_load", json={**query, "strategy": strategy}).get_json()
        optimisation = again["source"]["optimisation"]
        assert optimisation["reflex_pending"] == 0 and optimisation["by_reflex"] > 0
        assert optimisation["from_store"] == optimisation["connections"]
        # ReFlex's plans differ from the optimum only in timing, not in energy
        assert sum(again["y"]) == pytest.approx(sum(profile["y"]), rel=.1)
    band = client.post("/stations/aggregate_load", json={**query, "strategy": "ocost", "ensemble": 3}).get_json()
    assert band["source"]["ensemble"]["members"] == 3


def test_a_reflex_failure_never_fails_a_request(scenario_client):
    from backend.api_calls.reflex import ReflexError
    client, _ = scenario_client
    optimiser = client.application.extensions["cost_optimiser"]

    class Down:
        def run_many(self, *args, **kwargs):
            raise ReflexError("ReFlex POST /run/single failed: HTTP 503")
    optimiser.client_factory = Down
    query = dict(selected_markers=[1], strategy="v2g", date="2026-10-15", session_source="simple")
    response = client.post("/stations/aggregate_load", json=query)
    assert response.status_code == 200
    pending = response.get_json()["source"]["optimisation"]["reflex_pending"]
    assert pending > 0 and optimiser.wait_idle(timeout=30)
    # The provisional plans stay, and the failed connections are not sent again at once
    again = client.post("/stations/aggregate_load", json=query).get_json()["source"]["optimisation"]
    assert again["reflex_pending"] == pending and not optimiser.waiting


def test_api_model_failure_is_explicit(scenario_client, tmp_path):
    client, _ = scenario_client
    client.application.extensions["session_source_service"].library_path = tmp_path/"absent.npz"
    response = client.post("/stations/aggregate_load", json=dict(selected_markers=[1], strategy="avg", date="2026-10-15", session_source="cpft"))
    assert response.status_code == 503
    assert "CPFT" in response.get_json()["error"]


def test_minimum_carbon_api_matches_average_energy_and_fails_on_missing_grid(scenario_client):
    from backend.grid_data import GridHour, GridStore
    client, _ = scenario_client
    start, _ = day_window(TARGET-timedelta(days=1),'Europe/Amsterdam')
    _, end = day_window(TARGET,'Europe/Amsterdam')
    query = dict(selected_markers=[1],date=str(TARGET),strategy='mincarbon',session_source='simple')
    assert client.post('/stations/aggregate_load',json=query).status_code == 422
    store = GridStore(client.application.config['GRID_DATA_CACHE'])
    store.save([GridHour(start+timedelta(hours=i),100+10*(i%24),50,False,False) for i in range(int((end-start).total_seconds()/3600))],
               observations=True)
    energies = []
    for strategy in ['afap','alap','avg','mincarbon']:
        response = client.post('/stations/aggregate_load',json=dict(query,strategy=strategy))
        assert response.status_code == 200
        data = response.get_json()
        energies.append(sum(data['y'])/6)
        assert max(data['y']) <= 11+1e-8
    # AFAP/ALAP follow connections from their real arrival, so energy inside the
    # window differs for connections crossing its edges; average power and
    # minimum carbon both give such connections their uniform in-window share
    assert energies[3] == pytest.approx(energies[2])


def test_real_saved_checkpoints_reproduce_export_with_runtime_scalers():
    require_tensorflow("Install the cpft extra for checkpoint validation")
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


def test_ensemble_returns_a_percentile_band_around_the_requested_draw(scenario_client):
    client, _ = scenario_client
    base = dict(selected_markers=[1], strategy="afap", date="2026-10-15", session_source="simple", seed=7)
    single = client.post("/stations/aggregate_load", json=base).get_json()
    assert "ensemble" not in single["source"]
    many = client.post("/stations/aggregate_load", json={**base, "ensemble": 8}).get_json()
    band = many["source"]["ensemble"]
    # The line is still the requested seed's own draw, so a band never changes the single-draw result
    assert many["y"] == single["y"]
    assert band["members"] == 8 and band["seeds"] == list(range(7, 15)) and band["quantiles"] == [10, 50, 90]
    steps = len(single["y"])
    assert len(band["p10"]) == len(band["p50"]) == len(band["p90"]) == steps
    assert all(low <= middle <= high for low, middle, high in zip(band["p10"], band["p50"], band["p90"]))
    assert max(band["p90"]) > 0
    # a repeated request is identical: nothing about the band is random
    again = client.post("/stations/aggregate_load", json={**base, "ensemble": 8}).get_json()
    assert again["source"]["ensemble"] == band


def test_ensemble_band_widens_with_different_seeds_and_collapses_for_one_draw(scenario_client):
    client, _ = scenario_client
    base = dict(selected_markers=[1], strategy="alap", date="2026-10-15", session_source="spatial")
    one = client.post("/stations/aggregate_load", json={**base, "ensemble": 1}).get_json()
    assert "ensemble" not in one["source"]
    band = client.post("/stations/aggregate_load", json={**base, "ensemble": 12}).get_json()["source"]["ensemble"]
    assert any(high > low for low, high in zip(band["p10"], band["p90"]))


@pytest.mark.parametrize("extra,message", [
    (dict(ensemble=0), "between 1 and"), (dict(ensemble=500), "between 1 and"), (dict(ensemble="many"), "whole number"),
    (dict(ensemble=3, session_source="database"), "generated session source"),
])
def test_invalid_ensembles_are_rejected(scenario_client, extra, message):
    client, _ = scenario_client
    query = dict(selected_markers=[1], strategy="avg", date="2026-10-15", session_source="simple")
    query.update(extra)
    response = client.post("/stations/aggregate_load", json=query)
    assert response.status_code == 400
    assert message in response.get_json()["error"]


def test_ensemble_counts_towards_the_point_day_limit(scenario_client):
    client, _ = scenario_client
    client.application.config["MAX_POINT_DAYS"] = 10
    query = dict(selected_markers=[1], strategy="avg", date="2026-10-15", session_source="simple")
    assert client.post("/stations/aggregate_load", json={**query, "ensemble": 5}).status_code == 200
    refused = client.post("/stations/aggregate_load", json={**query, "ensemble": 6})
    assert refused.status_code == 422
    assert "12 point-days" in refused.get_json()["error"]

