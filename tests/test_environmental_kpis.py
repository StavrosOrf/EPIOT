"""Grid provenance, partial accounting, energy conservation and carbon optima."""

from datetime import date, datetime, timedelta
import sqlite3

import numpy as np
import pytest
from scipy.optimize import linprog

from backend.carbon_charging import CarbonScheduleUnavailable, arrival_cohort, daily_profiles, minimum_carbon_profile
from backend.cpft import day_window
from backend.grid_data import GridHour, GridStore, read_csv, resolve_hours, complete_reference
from backend.kpi.environment import EnvironmentalComparison
from backend.scenario_profiles import simulate_scenarios
from backend.scenario_sampling import ScenarioSession, UTC
from scripts.prepare_grid_data import main as prepare_grid

DAY = date(2026, 10, 14)
LEFT, RIGHT = day_window(DAY, 'Europe/Amsterdam')
CHARGERS = [dict(id=1, power=1)]


def original_profile():
    start = datetime(2025, 10, 22, tzinfo=UTC)
    return [GridHour(start+timedelta(hours=i), 100+i*10, 20+i, False, False,
        carbon_source_timestamp=start+timedelta(hours=i), renewable_source_timestamp=start+timedelta(hours=i),
        source='test local hourly file', basis='consumption') for i in range(24)]


def compare(records, hours, chargers=CHARGERS):
    result = EnvironmentalComparison(hours, 'Europe/Amsterdam')
    result.add_day(chargers, records, LEFT, RIGHT)
    return result.result()


def test_new_observations_are_used_on_the_next_request_without_preparation(tmp_path):
    from backend.grid_data import app_grid_hours
    store = GridStore(tmp_path/'grid.sqlite')
    store.save(original_profile(), observations=True)
    assert all(hour.carbon_is_stale for hour in app_grid_hours(LEFT, RIGHT, None, cache_path=store.path))
    store.save([GridHour(LEFT, 42, 60, False, False)], observations=True)
    hours = app_grid_hours(LEFT, RIGHT, None, cache_path=store.path)
    assert hours[0].co2_intensity == 42 and hours[0].carbon_is_stale is False
    assert hours[1].carbon_is_stale is True


def test_reference_preserves_origins_and_never_turns_missing_values_into_zero():
    profile = original_profile()
    exact = GridHour(LEFT, 0, None, False)
    resolved = resolve_hours(profile+[exact], LEFT, RIGHT)
    assert resolved[0].co2_intensity == 0
    assert resolved[0].carbon_is_stale is False
    assert resolved[0].renewable_is_stale is True
    assert resolved[1].carbon_is_estimated is True
    assert resolved[1].carbon_source_timestamp.year == 2025
    assert resolved[1].timestamp.year == 2026
    strict = resolve_hours(profile, LEFT, RIGHT, allow_stale=False)
    assert all(hour.co2_intensity is None and hour.renewable_percentage is None for hour in strict)
    assert not complete_reference(profile[:-1])


@pytest.mark.parametrize('target,count', [(date(2026,3,29),23),(date(2026,10,25),25)])
def test_reference_uses_local_hours_on_dst_days(target, count):
    left, right = day_window(target, 'Europe/Amsterdam')
    resolved = resolve_hours(original_profile(), left, right)
    assert len(resolved) == count
    assert all(hour.carbon_is_stale for hour in resolved)
    if count == 25:
        assert resolved[2].co2_intensity == resolved[3].co2_intensity
        assert resolved[2].carbon_source_timestamp == resolved[3].carbon_source_timestamp


def test_store_keeps_original_observations_separate_from_reference_cache(tmp_path):
    store = GridStore(tmp_path/'grid.sqlite')
    originals = original_profile()
    store.save(originals, observations=True)
    resolved = resolve_hours(originals, LEFT, RIGHT)
    store.save(resolved)
    assert store.read(observations=True) == originals
    assert store.read(LEFT, RIGHT) == resolved
    with store.connect() as connection:
        assert connection.execute("SELECT json_extract(payload,'$.carbon_is_stale') FROM grid_hourly LIMIT 1").fetchone()[0] == 1
    store.save(resolve_hours([], LEFT, RIGHT))
    assert all(hour.co2_intensity is None for hour in store.read(LEFT, RIGHT))
    assert store.read(observations=True) == originals


def test_csv_validates_timezones_quality_flags_and_explicit_missing_values(tmp_path):
    path = tmp_path/'grid.csv'
    path.write_text('timestamp,co2_intensity,renewable_percentage,is_estimated,basis\n2025-10-22T00:00:00Z,0,50,false,consumption\n2025-10-22T01:00:00Z,,110,true,consumption\n', encoding='utf-8')
    rows = read_csv(path)
    assert rows[0].co2_intensity == 0 and rows[0].carbon_is_estimated is False
    assert rows[1].co2_intensity is None and rows[1].renewable_percentage is None
    assert rows[1].carbon_is_estimated is True
    path.write_text('timestamp,co2_intensity,renewable_percentage\n2025-10-22 00:00,100,50\n', encoding='utf-8')
    with pytest.raises(ValueError, match='timezone'):
        read_csv(path)


def test_grid_import_is_offline_and_does_not_change_the_application_db(tmp_path, monkeypatch):
    import requests
    def prohibit_network(*args, **kwargs):
        pytest.fail('Grid preparation must not call an API')
    monkeypatch.setattr(requests.sessions.Session, 'request', prohibit_network)
    application = tmp_path/'main.sqlite'
    with sqlite3.connect(application) as connection:
        connection.execute('CREATE TABLE sessions (start TEXT)')
        connection.execute("INSERT INTO sessions VALUES ('2025-08-30 00:00')")
        connection.execute('CREATE TABLE power_mixes (datetime TEXT,renewable_percentage REAL,co2_intensity REAL,country_zone TEXT)')
        connection.executemany('INSERT INTO power_mixes VALUES (?,?,?,?)',
            [(hour.timestamp.isoformat(),hour.renewable_percentage,hour.co2_intensity,'NL') for hour in original_profile()])
    report = prepare_grid(['--database',str(application),'--cache',str(tmp_path/'cache.sqlite'),
                           '--start','2026-10-13','--end','2026-10-14'])
    assert report['hours'] == report['carbon_reference_hours'] == 48
    assert report['original_hours'] == 24
    with sqlite3.connect(application) as connection:
        assert connection.execute('SELECT COUNT(*) FROM power_mixes').fetchone()[0] == 24
        assert connection.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 1


@pytest.mark.parametrize('seed', range(5))
def test_fractional_carbon_schedule_matches_linear_program_optimum(seed):
    rng = np.random.default_rng(seed)
    record = ScenarioSession(1, LEFT+timedelta(minutes=5), LEFT+timedelta(minutes=55), .45)
    costs = rng.uniform(50,500,144)
    profile = minimum_carbon_profile(CHARGERS,[record],LEFT,RIGHT,costs)
    offsets = np.arange(144)*600
    capacity = np.maximum(0,np.minimum(offsets+600,3300)-np.maximum(offsets,300))/3600
    optimum = linprog(costs,A_eq=np.ones((1,144)),b_eq=[.45],bounds=list(zip(np.zeros(144),capacity)),method='highs')
    assert optimum.success
    assert sum(profile)/6 == pytest.approx(.45)
    assert np.max(profile) <= 1+1e-10
    assert profile@costs/6 == pytest.approx(optimum.fun)
    assert np.all(profile[6:] == 0)


def test_missing_candidate_carbon_data_and_overlapping_plugs_are_rejected():
    record = ScenarioSession(1,LEFT,LEFT+timedelta(hours=2),1)
    costs = np.full(144,100.)
    costs[10] = np.nan
    with pytest.raises(CarbonScheduleUnavailable,match='every feasible'):
        minimum_carbon_profile(CHARGERS,[record],LEFT,RIGHT,costs)
    costs[:] = 100
    with pytest.raises(CarbonScheduleUnavailable,match='Overlapping'):
        minimum_carbon_profile(CHARGERS,[record,record],LEFT,RIGHT,costs)
    costs[100] = np.nan  # outside the connected interval is harmless
    assert sum(minimum_carbon_profile(CHARGERS,[record],LEFT,RIGHT,costs))/6 == pytest.approx(1)


def test_arrival_cohort_gives_all_strategies_identical_energy_from_the_true_arrival():
    earlier = ScenarioSession(1,LEFT-timedelta(hours=1),LEFT+timedelta(hours=3),2)
    late = ScenarioSession(1,RIGHT-timedelta(hours=1),RIGHT+timedelta(hours=3),2)
    # The connection that arrived before the window belongs to the previous one
    [cohort] = arrival_cohort(CHARGERS,[earlier,late],LEFT,RIGHT).records()
    assert (cohort.start, cohort.end, cohort.energy_kwh) == (late.start, RIGHT, pytest.approx(.5))
    costs = np.full(144,500.)
    costs[-3:] = 100
    values = {strategy:np.asarray(simulate_scenarios(CHARGERS,[cohort],LEFT,RIGHT,strategy,carbon_intensity=costs)[0])
              for strategy in ['afap','alap','avg','mincarbon']}
    for profile in values.values():
        assert sum(profile)/6 == pytest.approx(.5)
        assert np.max(profile) <= 1+1e-10
        assert np.all(profile[:-6] == 0)  # nothing before the 23:00 arrival
    assert values['mincarbon']@costs <= values['afap']@costs+1e-10
    # Followed past midnight when the horizon allows, so it keeps its full energy
    [followed] = arrival_cohort(CHARGERS,[late],LEFT,RIGHT,RIGHT+timedelta(days=1)).records()
    assert (followed.end, followed.energy_kwh) == (late.end, 2)


def test_overnight_connections_do_not_restart_charging_at_midnight():
    # Arrived 21:00 the evening before with 5 kWh on an 11 kW point: AFAP is
    # done by 21:28, so the window that starts at midnight sees no AFAP load
    chargers = [dict(id=1, power=11)]
    overnight = ScenarioSession(1,LEFT-timedelta(hours=3),LEFT+timedelta(hours=7),5)
    afap, alap, avg = (np.asarray(simulate_scenarios(chargers,[overnight],LEFT,RIGHT,s)[0]) for s in ['afap','alap','avg'])
    assert afap.sum() == 0
    assert alap.sum()/6 == pytest.approx(5) and np.flatnonzero(alap).max() == 41  # ends at 07:00
    assert avg.sum()/6 == pytest.approx(5*7/10) and avg[0] == pytest.approx(.5)
    # A two-day load-profile window is simulated in one pass: no restart at the inner midnight
    previous, _ = day_window(DAY-timedelta(days=1),'Europe/Amsterdam')
    evening = ScenarioSession(1,LEFT-timedelta(hours=3),LEFT+timedelta(hours=7),20)
    profile = np.asarray(daily_profiles(chargers,[evening],previous,RIGHT,'afap','Europe/Amsterdam')[0])
    starts = np.flatnonzero(np.diff((np.r_[0,profile] > 0).astype(int)) == 1)
    assert len(starts) == 1 and starts[0] == 144-18  # one charging block, from 21:00


def test_emissions_summary_and_afap_difference_are_energy_weighted():
    record = ScenarioSession(1,LEFT,LEFT+timedelta(hours=2),1)
    hours = [GridHour(LEFT+timedelta(hours=i),500 if i==0 else 100,50,False,False) for i in range(24)]
    result = compare([record],hours)
    baseline, minimum = result['strategies']['afap'], result['strategies']['mincarbon']
    assert baseline['emissions_kg'] == pytest.approx(.5)
    assert minimum['emissions_kg'] == pytest.approx(.1)
    assert minimum['average_intensity_g_per_kwh'] == pytest.approx(100)
    assert minimum['footprint_difference_vs_afap_pct'] == pytest.approx(-80)
    assert all(row['same_energy'] and row['carbon_energy_coverage_pct']==pytest.approx(100) for row in result['strategies'].values())


def test_hourly_emissions_show_where_each_strategy_charges_while_the_intensity_curve_does_not():
    record = ScenarioSession(1,LEFT,LEFT+timedelta(hours=2),1)
    hours = [GridHour(LEFT+timedelta(hours=i),500 if i==0 else 100,50,False,False) for i in range(24)]
    strategies = compare([record],hours)['strategies']
    baseline, minimum, delayed = strategies['afap'], strategies['mincarbon'], strategies['alap']
    # As fast as possible charges in the dirty first hour, minimum carbon in the clean second hour
    assert baseline['emissions_by_hour_kg'][0] == pytest.approx(.5) and baseline['emissions_by_hour_kg'][1] == 0
    assert minimum['emissions_by_hour_kg'][0] == 0 and minimum['emissions_by_hour_kg'][1] == pytest.approx(.1)
    assert baseline['energy_by_hour_kwh'][:2] == pytest.approx([1, 0])
    assert delayed['energy_by_hour_kwh'][:2] == pytest.approx([0, 1])
    for row in strategies.values():
        assert len(row['emissions_by_hour_kg']) == len(row['energy_by_hour_kwh']) == 24
        assert sum(row['emissions_by_hour_kg']) == pytest.approx(row['emissions_kg'])
        assert sum(row['energy_by_hour_kwh']) == pytest.approx(row['energy_kwh'])
    # The intensity is the grid's own value at the hour a strategy charges, so it cannot tell strategies apart
    assert baseline['intensity_by_hour'][0] == pytest.approx(500) and minimum['intensity_by_hour'][1] == pytest.approx(100)
    assert baseline['intensity_by_hour'][1] is None and minimum['intensity_by_hour'][0] is None


def test_unavailable_strategy_has_no_hourly_series():
    record = ScenarioSession(1,LEFT,LEFT+timedelta(hours=2),1)
    result = compare([record],[GridHour(LEFT,100,None),GridHour(LEFT+timedelta(hours=1),None,80)])
    assert result['strategies']['mincarbon']['emissions_by_hour_kg'] is None
    assert result['strategies']['mincarbon']['energy_by_hour_kwh'] is None


def test_independent_carbon_and_renewable_coverage_and_no_partial_savings_claim():
    record = ScenarioSession(1,LEFT,LEFT+timedelta(hours=2),1)
    hours = [GridHour(LEFT,100,None),GridHour(LEFT+timedelta(hours=1),None,80)]
    result = compare([record],hours)
    average = result['strategies']['avg']
    assert average['emissions_kg'] == pytest.approx(.05)
    assert average['average_intensity_g_per_kwh'] == pytest.approx(100)
    assert average['renewable_share_pct'] == pytest.approx(80)
    assert average['carbon_energy_coverage_pct'] == pytest.approx(50)
    assert average['renewable_energy_coverage_pct'] == pytest.approx(50)
    assert average['status'] == 'partial'
    assert average['footprint_difference_vs_afap_kg'] is None
    assert result['strategies']['mincarbon']['available'] is False
    assert result['strategies']['mincarbon']['emissions_kg'] is None


def test_stale_reference_coverage_is_distinct_from_matching_date_coverage():
    record = ScenarioSession(1,LEFT,LEFT+timedelta(hours=2),1)
    result = compare([record],resolve_hours(original_profile(),LEFT,RIGHT))
    assert result['uses_historical_reference'] is True
    assert result['reference_source_start'].startswith('2025-')
    assert all(row['status']=='historical_reference' and row['matching_date_carbon_coverage_pct']==0
               and row['estimated_carbon_energy_pct']==pytest.approx(100) for row in result['strategies'].values())


def test_strict_mode_suppresses_reference_values_and_does_not_claim_reference_coverage(tmp_path):
    from backend.grid_data import app_grid_hours
    store = GridStore(tmp_path/'grid.sqlite')
    store.save(original_profile(), observations=True)
    assert all(hour.carbon_is_stale for hour in app_grid_hours(LEFT,RIGHT,None,cache_path=store.path))
    hours = app_grid_hours(LEFT,RIGHT,None,cache_path=store.path,allow_stale=False)
    assert all(hour.co2_intensity is None and hour.renewable_percentage is None for hour in hours)
    result = compare([ScenarioSession(1,LEFT,LEFT+timedelta(hours=1),1)],hours)
    assert result['covered_steps'] == 0
    assert result['uses_historical_reference'] is False
    assert result['strategies']['afap']['emissions_kg'] is None


def test_zero_energy_and_zero_carbon_are_valid_without_division_by_zero():
    zero = compare([],[])
    assert zero['strategies']['afap']['status'] == 'no_charging'
    assert zero['strategies']['afap']['emissions_kg'] == 0
    record = ScenarioSession(1,LEFT,LEFT+timedelta(hours=1),1)
    result = compare([record],[GridHour(LEFT+timedelta(hours=i),0,100,False,False) for i in range(24)])
    assert result['strategies']['mincarbon']['average_intensity_g_per_kwh'] == 0
    assert result['strategies']['mincarbon']['footprint_difference_vs_afap_kg'] == 0
    assert result['strategies']['mincarbon']['footprint_difference_vs_afap_pct'] is None
