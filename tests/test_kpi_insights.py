"""Behavioural, grid, mobility and city KPIs beyond the plain histograms."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from backend.kpi.statistics import calculate_kpis, days_between, idle_gaps, mean_clock_hour
from backend.scenario_sampling import UTC, ScenarioSession

TZ = "Europe/Amsterdam"
ZONE = ZoneInfo(TZ)
MONDAY = date(2025, 10, 13)


def session(cp_id, day, start_hour, end_hour, kwh):
    midnight = datetime(day.year, day.month, day.day, tzinfo=ZONE)
    return ScenarioSession(cp_id, (midnight+timedelta(hours=start_hour)).astimezone(UTC),
                           (midnight+timedelta(hours=end_hour)).astimezone(UTC), kwh)


def chargers(*powers):
    return [dict(id=index+1, power=power) for index, power in enumerate(powers)]


def kpis(points, records, first=MONDAY, last=None):
    """Like the database source: every day sees every record, windows do the filtering."""
    last = last or first
    return calculate_kpis(points, [(day, records) for day in days_between(first, last)],
                          first, last, TZ, include_environment=False)


def test_departure_exactly_at_local_midnight_is_counted_once():
    result = kpis(chargers(11), [session(1, MONDAY, 18, 24, 6)], MONDAY, MONDAY+timedelta(days=1))
    assert sum(result['departure_dist_wd']) == 1
    assert result['departure_dist_wd'][0] == 1


def test_idle_time_is_the_stay_minus_charging_at_rated_power():
    result = kpis(chargers(11), [session(1, MONDAY, 9, 17, 22)])
    assert result['slack_dist_wd'][6] == 1  # 8 h connected, 2 h of charging
    assert result['summary']['mean_slack_hours'] == pytest.approx(6)
    assert result['summary']['slack_share'] == pytest.approx(0.75)
    assert result['summary']['median_duration_hours'] == pytest.approx(8)


def test_energy_the_rated_power_cannot_deliver_is_capped_before_idle_time_is_computed():
    result = kpis(chargers(11), [session(1, MONDAY, 9, 11, 500)])
    assert result['summary']['session_energy_kwh'] == pytest.approx(22)
    assert result['summary']['slack_share'] == pytest.approx(0)


def test_values_beyond_the_last_bin_are_reported_not_hidden():
    records = [session(1, MONDAY, 8, 8+40, 20), session(2, MONDAY, 6, 12, 400)]
    result = kpis(chargers(11, 150), records)
    assert result['duration_dist_wd'][23] == 1
    assert result['consumption_dist_wd'][9] == 1
    assert result['overflow']['duration']['wd'] == 1
    assert result['overflow']['consumption']['wd'] == 1
    assert result['overflow']['duration']['we'] == 0


def test_hours_without_arrivals_have_no_mean_energy():
    result = kpis(chargers(11), [session(1, MONDAY, 9, 10, 4), session(1, MONDAY, 10.5, 12, 6)])
    mean = result['hour_of_arrival_consumption_wd']
    assert mean[9] == pytest.approx(4)
    assert mean[10] == pytest.approx(6)
    assert mean[8] is None and mean[23] is None
    assert result['hour_of_arrival_consumption_we'] == [None]*24


def test_idle_charger_days_are_counted_apart_from_charging_days():
    result = kpis(chargers(11, 11), [session(1, MONDAY, 9, 12, 10)])
    assert result['idle_charger_days_wd'] == 1
    assert result['idle_charger_days_we'] == 0
    assert result['summary']['idle_charger_day_share'] == pytest.approx(0.5)
    # The distribution keeps every charger-day; idle ones sit in the first bin with the charging one
    assert result['daily_consumption_dist_wd'][0] == 2


def test_uncontrolled_load_peak_and_factors():
    records = [session(1, MONDAY, 10, 14, 11), session(2, MONDAY, 10, 14, 22)]
    result = kpis(chargers(11, 22), records)
    summary = result['summary']
    assert summary['peak_kw'] == pytest.approx(33)
    assert summary['peak_time'].startswith('2025-10-13T10:00:00+02:00')
    assert summary['mean_load_kw'] == pytest.approx(33/24)
    assert summary['load_factor'] == pytest.approx(1/24)
    assert summary['coincidence_factor'] == pytest.approx(1)
    profile = result['load_profile_wd']
    assert profile[20] == pytest.approx(33) and profile[21] == pytest.approx(33) and profile[22] == pytest.approx(0)
    assert result['load_profile_we'] == [None]*48
    curve = result['load_duration_kw']
    assert curve[0] == pytest.approx(33) and curve[-1] == pytest.approx(0) and curve == sorted(curve, reverse=True)


def test_blocking_is_the_time_every_charger_is_occupied():
    records = [session(1, MONDAY, 8, 12, 5), session(2, MONDAY, 10, 14, 5)]
    result = kpis(chargers(11, 11), records)
    blocking, free = result['weekday_blocking'], result['weekday_availability']
    assert blocking[20:24] == pytest.approx([1.]*4)  # 10:00-12:00
    assert sum(blocking) == pytest.approx(4)
    assert free[16:20] == pytest.approx([.5]*4) and free[20:24] == pytest.approx([0.]*4)
    assert result['weekend_blocking'] == [None]*48
    assert result['summary']['max_blocking_probability'] == pytest.approx(1)


def test_blocking_is_unavailable_without_chargers():
    result = kpis([], [])
    assert result['weekday_blocking'] == [None]*48
    assert result['charger_usage']['id'] == []
    assert result['summary']['coincidence_factor'] is None


def test_idle_gaps_between_sessions_on_the_same_charger():
    records = [session(1, MONDAY, 8, 10, 5), session(1, MONDAY, 14, 15, 5), session(1, MONDAY, 15, 16, 5),
               session(2, MONDAY, 12, 13, 5)]
    result = kpis(chargers(11, 11), records)
    assert result['summary']['idle_gap_count'] == 2
    assert result['summary']['median_idle_gap_hours'] == pytest.approx(2)  # gaps of 4 h and 0 h
    assert result['summary']['sessions_per_used_charger_day'] == pytest.approx(2)


def test_overlapping_connections_are_not_gaps():
    points = np.array([0, 0, 0])
    start = np.array([0., 3600., 20000.])
    end = np.array([10000., 5000., 30000.])
    assert idle_gaps(points, start, end) == pytest.approx([10000/3600])


def test_sessions_per_charger_and_day_summarise_every_weekday_seen():
    tuesday = MONDAY+timedelta(days=1)
    records = [session(1, MONDAY, 8, 9, 2), session(1, MONDAY, 10, 11, 2),
               session(1, tuesday, 8, 9, 2), session(2, tuesday, 8, 9, 2)]
    result = kpis(chargers(11, 11), records, MONDAY, tuesday)
    assert result['sessions_per_day_observations'] == [2, 2, 0, 0, 0, 0, 0]
    assert result['sessions_per_day_mean'][:2] == pytest.approx([1., 1.])
    assert result['sessions_per_day_p90'][0] == pytest.approx(np.percentile([2, 0], 90))
    assert result['sessions_per_day_mean'][2] is None


def test_charger_usage_separates_connected_time_from_energy_delivered():
    result = kpis(chargers(11, 22), [session(1, MONDAY, 8, 16, 22)])
    usage = result['charger_usage']
    assert usage['id'] == [1, 2]
    assert usage['occupancy'] == pytest.approx([8/24, 0])
    assert usage['utilisation'] == pytest.approx([22/(11*24), 0])
    assert usage['sessions'] == [1, 0]
    assert result['summary']['mean_utilisation'] == pytest.approx(22/(11*24)/2)


def test_clock_times_average_around_midnight():
    mean = mean_clock_hour([23.5, 0.5])
    assert min(mean, 24-mean) == pytest.approx(0, abs=1e-6)
    assert mean_clock_hour([8, 10]) == pytest.approx(9)
    assert mean_clock_hour([]) is None
