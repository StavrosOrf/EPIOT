"""Hand-built sessions through the vectorised profile engine every session source uses.

A 6 kW charger delivers exactly 1 kWh per 10-minute step, so expectations are exact.
"""

from datetime import datetime, timedelta, timezone

import pytest

from backend.scenario_profiles import simulate_scenarios
from backend.scenario_sampling import ScenarioSession

UTC = timezone.utc
START = datetime(2025, 1, 14, tzinfo=UTC)   # a two-day window: the 14th and the 15th
END = START + timedelta(days=2)
STEPS = 288


def at(day, hour, minute=0):
    return datetime(2025, 1, day, hour, minute, tzinfo=UTC)


def profile(strategy, sessions, power=6.0):
    chargers = [dict(id=1, power=power)]
    return simulate_scenarios(chargers, [ScenarioSession(1, *row) for row in sessions], START, END, strategy)


def test_uncontrolled_profile_charges_at_full_power_from_arrival():
    load, up_flex, down_flex = profile("afap", [(at(15, 10), at(15, 14), 5.0)])
    first = 144+10*6
    assert len(load) == STEPS
    assert load[first:first+5] == pytest.approx([6.0]*5)
    assert load[first-1] == 0 and load[first+5] == 0
    # Energy is conserved: each step is a sixth of an hour
    assert sum(load)/6 == pytest.approx(5.0)
    # Charging could instead be delayed to the end of the stay: the early block is the load that can be shed
    assert down_flex[first:first+5] == pytest.approx([-6.0]*5)
    assert up_flex == [0]*STEPS


def test_delayed_profile_finishes_at_departure():
    load, up_flex, _ = profile("alap", [(at(15, 10), at(15, 14), 5.0)])
    last = 144+14*6
    assert load[last-5:last] == pytest.approx([6.0]*5)
    assert load[last] == 0 and load[last-6] == 0
    assert sum(load)/6 == pytest.approx(5.0)
    # The early block is available as extra load before the delayed one
    first = 144+10*6
    assert up_flex[first:first+5] == pytest.approx([6.0]*5)


def test_average_power_spreads_the_energy_over_the_stay_and_conserves_it():
    load, _, _ = profile("avg", [(at(15, 10), at(15, 14), 5.0)])
    window = load[144+10*6:144+14*6]
    assert window == pytest.approx([1.25]*24)
    assert sum(load)/6 == pytest.approx(5.0)


def test_sessions_outside_the_window_are_ignored():
    load, up_flex, down_flex = profile("afap", [(at(20, 10), at(20, 14), 5.0), (at(10, 10), at(10, 14), 5.0)])
    assert load == [0]*STEPS and up_flex == [0]*STEPS and down_flex == [0]*STEPS


def test_unknown_rated_power_falls_back_to_11_kw():
    chargers = [dict(id=1, power=None)]
    load, _, _ = simulate_scenarios(chargers, [ScenarioSession(1, at(15, 0), at(15, 6), 11.0)], START, END, "afap")
    assert max(load) == pytest.approx(11.0)


def test_overnight_connection_is_charged_from_its_true_arrival_not_from_the_window_edge():
    # Arrives 22:00 the day before the window, leaves 04:00 inside it. 20 kWh at 6 kW
    # takes 3 h 20 min from arrival, so 1 h 20 min (8 steps) fall inside the window.
    load, _, _ = profile("afap", [(at(13, 22), at(14, 4), 20.0)])
    assert load[:8] == pytest.approx([6.0]*8)
    assert load[8] == 0
    assert sum(load)/6 == pytest.approx(8.0)  # only the share inside the window is reported


def test_connection_crossing_midnight_inside_the_window_is_not_restarted():
    load, _, _ = profile("afap", [(at(14, 23), at(15, 3), 10.0)])
    start = 23*6
    # 10 kWh / 6 kW = 100 minutes: 23:00 to 00:40, and nothing starts again at midnight
    assert load[start:start+10] == pytest.approx([6.0]*10)
    assert load[start+10] == 0
    assert sum(load)/6 == pytest.approx(10.0)
