"""KPI source selection, inclusive ranges, timezone boundaries and cache reuse."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from flask import Flask
import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.cpft import day_window
from backend.cpft_runtime import CPFTUnavailable
from backend.kpi.statistics import calculate_kpis
from backend.kpi.user import kpi_data
from backend.scenario_sampling import ScenarioSession, UTC
from backend.session_sources import SessionSourceService


class DailyRuntime:
    def forecast(self, chargers, histories, issue, end):
        output = {}
        for charger in chargers:
            rows, timestamp = [], issue
            while timestamp < end:
                occupied = timestamp.hour == 10
                rows.append(dict(hour=timestamp, availability_forecast_prob=.9 if occupied else .1,
                    availability_forecast_bin=int(occupied), kWh_forecast_next_whole_period=2*int(occupied)))
                timestamp += timedelta(hours=1)
            output[charger["id"]] = rows
        return output


@pytest.fixture
def client(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path/'app.sqlite').as_posix()}")
    with engine.begin() as connection:
        for sql in [
            "CREATE TABLE locations (id INTEGER PRIMARY KEY, latitude REAL, longitude REAL)",
            "CREATE TABLE columns (id INTEGER PRIMARY KEY, operator_id INTEGER, location_id INTEGER)",
            "CREATE TABLE charging_points (id INTEGER PRIMARY KEY, column_id INTEGER, power REAL, type TEXT)",
            "CREATE TABLE sessions (id INTEGER PRIMARY KEY, cp_id INTEGER, start DATETIME, end DATETIME, consumption REAL)",
            "CREATE TABLE power_mixes (id INTEGER PRIMARY KEY, country_zone TEXT, datetime DATETIME, renewable_percentage REAL, co2_intensity REAL)",
            "INSERT INTO locations VALUES (1,52.36,4.90)", "INSERT INTO columns VALUES (1,1,1)",
            "INSERT INTO charging_points VALUES (1,1,11,'regular'),(2,1,11,'regular'),(3,1,11,'regular')",
            "INSERT INTO sessions VALUES (1,1,'2025-10-12 23:30','2025-10-13 00:30',4)",
            "INSERT INTO sessions VALUES (2,1,'2025-10-13 00:30','2025-10-13 01:30',4.5)",
            "INSERT INTO sessions VALUES (3,1,'2025-10-14 23:30','2025-10-15 00:30',3)",
            "INSERT INTO sessions VALUES (4,2,'2025-10-14 05:00','2025-10-16 08:00',26)",
            "INSERT INTO sessions VALUES (5,1,'2025-10-15 00:00','2025-10-15 02:00',99)",
        ]:
            connection.exec_driver_sql(sql)
    with Session(engine) as session:
        app = Flask(__name__)
        app.config.update(TESTING=True, GRID_DATA_CACHE=str(tmp_path/'grid.sqlite'), **{"station_data.db": SimpleNamespace(session=session)})
        app.extensions["session_source_service"] = SessionSourceService(tmp_path/'cache.sqlite',
            atlas_path=tmp_path/'missing.gpkg', runtime_factory=DailyRuntime)
        app.register_blueprint(kpi_data, url_prefix='/kpi')
        yield app.test_client(), engine
    engine.dispose()


def request(client, **overrides):
    query = dict(selected_markers=[1, 2, 3], start_date="2025-10-13", end_date="2025-10-14", session_source="database")
    query.update(overrides)
    return client.post('/kpi/user', json=query)


def test_full_inclusive_range_and_overlapping_overnight_sessions(client):
    browser, engine = client
    response = request(browser)
    assert response.status_code == 200
    data = response.get_json()
    assert data['range']['day_count'] == 2
    assert data['summary']['session_count'] == 3
    assert sum(data['arrival_dist_wd']) == 3
    assert data['summary']['mean_duration_hours'] == pytest.approx((1+1+51)/3)
    # Energy follows the same sessions as session_count: arrivals in the range,
    # charged from their true arrival and cut at the end of the range. Session 1
    # arrived the evening before, so its 2 kWh share belongs to that day.
    assert data['summary']['energy_kwh'] == pytest.approx(4.5+1.5+26*19/51)
    assert data['summary']['point_count'] == 3  # includes unused point 3
    assert data['occupation_ratio_dist'][0] > 0
    assert len(data['weekday_availability']) == 48
    assert data['weekend_availability'] == [None]*48  # no weekend in this range
    assert sum(data['sessions_per_day_0']) == pytest.approx(1)
    assert data['environment']['covered_steps'] == 0
    assert data['renewable_energy_shared_avg'] is None
    assert all(value is None for value in data['co2_intensities_avg'])
    with engine.connect() as db:
        assert db.exec_driver_sql('SELECT COUNT(*) FROM sessions').scalar() == 5


def test_same_day_range_includes_last_evening_and_zero_use_days(client):
    browser, _ = client
    data = request(browser, start_date="2025-10-14").get_json()
    assert data['range']['day_count'] == 1
    assert data['summary']['session_count'] == 2
    assert data['arrival_dist_wd'][23] == 1
    empty = request(browser, start_date="2025-10-20", end_date="2025-10-20").get_json()
    assert empty['summary']['energy_kwh'] == 0
    assert empty['summary']['session_count'] == 0
    assert empty['weekday_availability'] == [1.]*48
    assert empty['sessions_per_day_0'][0] == 1


def test_legacy_utc_picker_midnight_is_converted_to_local_calendar_date(client):
    browser, _ = client
    response = browser.get('/kpi/user?selected_markers=1,2,3&start_date=2025-10-12T22:00:00.000Z&end_date=2025-10-13T22:00:00.000Z')
    data = response.get_json()
    assert data['range']['start_date'] == '2025-10-13'
    assert data['range']['end_date'] == '2025-10-14'
    assert data['summary']['session_count'] == 3


@pytest.mark.parametrize('source', ['simple', 'spatial', 'cpft'])
def test_selected_source_range_equals_sum_of_cached_target_days(client, source):
    browser, engine = client
    data = request(browser, session_source=source).get_json()
    repeat = request(browser, session_source=source).get_json()
    assert data['source']['source'] == source
    assert data['source']['synthetic'] is True
    assert repeat['source']['cache_hits'] == 6
    assert data['summary'] == repeat['summary']
    singles = [request(browser, session_source=source, start_date=day, end_date=day).get_json()
               for day in ['2025-10-13', '2025-10-14']]
    assert data['summary']['session_count'] == sum(item['summary']['session_count'] for item in singles)
    assert data['summary']['energy_kwh'] == pytest.approx(sum(item['summary']['energy_kwh'] for item in singles))
    if source == 'cpft':
        assert data['summary']['session_count'] == 6  # no synthetic-history arrivals counted
        assert data['summary']['energy_kwh'] == pytest.approx(12)
    with engine.connect() as db:
        assert db.exec_driver_sql('SELECT COUNT(*) FROM sessions').scalar() == 5


@pytest.mark.parametrize('updates', [dict(start_date=''), dict(end_date='2025-10-12'),
    dict(session_source='unknown'), dict(demand_assumption='unknown'), dict(seed=-1),
    dict(selected_markers=[999]), dict(selected_markers={}),
    dict(end_date=str(datetime.now(ZoneInfo('Europe/Amsterdam')).date()+timedelta(days=1)))])
def test_invalid_ranges_and_source_options_are_rejected(client, updates):
    browser, _ = client
    assert request(browser, **updates).status_code == 400


def test_empty_cpft_selection_does_not_load_models_and_returns_finite_data(client):
    browser, _ = client
    def unavailable():
        raise CPFTUnavailable('missing checkpoint')
    browser.application.extensions['session_source_service'].runtime_factory = unavailable
    response = request(browser, selected_markers=[], session_source='cpft')
    assert response.status_code == 200
    assert response.get_json()['summary']['point_count'] == 0
    assert request(browser, session_source='cpft').status_code == 503


@pytest.mark.parametrize('day,hours', [(date(2025, 3, 30), 23), (date(2025, 10, 26), 25)])
def test_dst_full_day_occupancy_and_energy_use_actual_elapsed_time(day, hours):
    left, right = day_window(day, 'Europe/Amsterdam')
    chargers = [dict(id=1, power=11)]
    records = [ScenarioSession(1, left, right, hours)]
    result = calculate_kpis(chargers, [(day, records)], day, day, 'Europe/Amsterdam')
    assert result['range']['elapsed_hours'] == hours
    assert result['summary']['energy_kwh'] == pytest.approx(hours)
    assert result['summary']['mean_duration_hours'] == hours
    assert result['summary']['mean_occupancy_ratio'] == 1
    assert np.isfinite(result['occupation_ratio_dist']).all()
    if hours == 23:
        assert result['weekend_availability'][4:6] == [None, None]  # absent local 02:00 hour


def test_environmental_values_use_matching_hours_and_energy_weighted_intensity():
    day = date(2025, 10, 13)
    left, _ = day_window(day, 'Europe/Amsterdam')
    record = ScenarioSession(1, left, left+timedelta(hours=2), 2)
    mix = [(left.replace(tzinfo=None), 50., 100.), ((left+timedelta(hours=1)).replace(tzinfo=None), 100., 200.)]
    result = calculate_kpis([dict(id=1, power=1)], [(day, [record])], day, day, 'Europe/Amsterdam', mix)
    assert result['environment']['coverage_fraction'] == pytest.approx(2/24)
    assert result['renewable_energy_shared_avg'] == pytest.approx(75)
    assert result['co2_intensities_avg'][:2] == pytest.approx([100, 200])
    assert result['co2_intensities_avg'][2:] == [None]*22


@pytest.mark.parametrize('source', ['simple','spatial','cpft'])
def test_api_environment_reference_is_labelled_and_all_schedules_have_same_energy(client, source):
    from backend.grid_data import GridHour, GridStore, resolve_hours
    browser, _ = client
    origin = datetime(2024,10,22,tzinfo=UTC)
    observations = [GridHour(origin+timedelta(hours=i),100+10*i,50,False,False) for i in range(24)]
    left, _ = day_window(date(2025,10,13),'Europe/Amsterdam')
    _, right = day_window(date(2025,10,14),'Europe/Amsterdam')
    store = GridStore(browser.application.config['GRID_DATA_CACHE'])
    store.save(resolve_hours(observations,left,right))
    response = request(browser,session_source=source)
    assert response.status_code == 200
    environment = response.get_json()['environment']
    assert environment['uses_historical_reference'] is True
    strategies = environment['strategies']
    assert all(row['same_energy'] and row['status']=='historical_reference' for row in strategies.values())
    assert strategies['mincarbon']['emissions_kg'] <= strategies['afap']['emissions_kg']+1e-8
    assert all(row['matching_date_carbon_coverage_pct']==0 for row in strategies.values())
