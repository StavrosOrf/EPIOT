"""On-the-fly scenarios: window independence, vectorized equivalence and CPFT sampling."""

from datetime import date, timedelta

import numpy as np
import pytest

from backend.carbon_charging import balanced_sessions, minimum_carbon_profile
from backend.cpft import day_window
from backend.cpft_library import CPFTLibrary, issue_time, sample_cpft
from backend.scenario_profiles import simulate_scenarios
from backend.scenario_sampling import point_power
from backend.scenario_world import sample_world
from backend.session_frame import bin_integrals
from backend.session_sources import SessionSourceService
from backend.spatial_profiles import profile_from_attributes
from scripts.build_cpft_library import VOLUME_BINS
from tests.cpft_helpers import write_test_library

ZONE = "Europe/Amsterdam"
RNG = np.random.default_rng(11)
CHARGERS = [dict(id=int(cp_id), power=float(RNG.choice([3.7, 11, 22, 50])), type="fast" if RNG.random() < .2 else "regular")
            for cp_id in RNG.choice(10**6, 300, replace=False)]
PROFILES = [profile_from_attributes(dict(oppervlakte_land_in_ha=100, woningvoorraad=int(RNG.integers(0, 8000)),
    aantal_bedrijfsvestigingen=int(RNG.integers(0, 3000)), aantal_bedrijven_handel_en_horeca=int(RNG.integers(0, 500)),
    bevolkingsdichtheid_inwoners_per_km2=int(RNG.integers(0, 20000)))) if RNG.random() < .5 else None for _ in CHARGERS]


def window(first, last):
    return day_window(first, ZONE)[0], day_window(last, ZONE)[1]


@pytest.mark.parametrize("source,profiles", [("simple", None), ("spatial", PROFILES)])
def test_a_day_is_identical_alone_and_inside_any_longer_window(source, profiles):
    """Window independence across DST, so nothing needs to be prepared or stored."""
    long = sample_world(CHARGERS, *window(date(2026, 10, 1), date(2026, 11, 5)), profiles=profiles, source=source)
    for day in [date(2026, 10, 3), date(2026, 10, 25), date(2026, 11, 2)]:
        left, right = window(day, day)
        alone = sample_world(CHARGERS, left, right, profiles=profiles, source=source)
        assert len(alone)
        assert alone.equals(long.overlapping(left.timestamp(), right.timestamp()))
        week = sample_world(CHARGERS, *window(day-timedelta(days=3), day+timedelta(days=3)), profiles=profiles, source=source)
        assert alone.equals(week.overlapping(left.timestamp(), right.timestamp()))


def test_sessions_never_overlap_and_respect_power_and_duration_limits():
    frame = sample_world(CHARGERS, *window(date(2026, 3, 1), date(2026, 4, 30)), profiles=PROFILES, source="spatial", assumption="high")
    same_point = frame.cp_id[1:] == frame.cp_id[:-1]
    assert (frame.start[1:][same_point] >= frame.end[:-1][same_point]).all()
    power = np.array([point_power(next(c for c in CHARGERS if c["id"] == cp_id)) for cp_id in frame.cp_id])
    hours = (frame.end-frame.start)/3600
    assert (frame.energy_kwh <= power*hours+1e-9).all()
    assert ((hours >= .25) & (hours <= 72)).all()
    assert (frame.start % 900 == 0).all()  # arrivals on UTC quarter-hours


def test_seed_source_and_demand_assumption_change_the_scenario_as_expected():
    left, right = window(date(2026, 6, 1), date(2026, 6, 14))
    base = sample_world(CHARGERS, left, right)
    assert sample_world(CHARGERS, left, right).equals(base)
    assert not sample_world(CHARGERS, left, right, seed=7).equals(base)
    assert not sample_world(CHARGERS, left, right, source="spatial").equals(base)
    counts = [len(sample_world(CHARGERS, left, right, assumption=level)) for level in ("low", "base", "high")]
    assert counts[0] < counts[1] < counts[2]
    assert len(sample_world(CHARGERS, left, right, daily_arrivals=0.)) == 0


def test_bin_integrals_match_brute_force_overlap():
    left = RNG.uniform(-2000, 9000, 400)
    right = left+RNG.uniform(1, 5000, 400)
    weight = RNG.uniform(0, 10, 400)
    rows = RNG.integers(0, 3, 400)
    actual = bin_integrals(left, right, weight, 12, 600, rows, 3)
    edges = np.arange(12)*600.
    expected = np.zeros((3, 12))
    for a, b, w, r in zip(left, right, weight, rows):
        expected[r] += w*np.maximum(0, np.minimum(edges+600, b)-np.maximum(edges, a))/600
    np.testing.assert_allclose(actual, expected, rtol=1e-10, atol=1e-9)


def reference_profiles(chargers, sessions, start, end):
    """The per-session implementation the vectorized profiles replaced."""
    count = int((end-start).total_seconds()/600)
    starts = np.arange(count)*600.
    power_by_id = {int(charger["id"]): point_power(charger) for charger in chargers}
    early, late, average = np.zeros(count), np.zeros(count), np.zeros(count)
    for session in sessions:
        if session.cp_id not in power_by_id or session.end <= start or session.start >= end:
            continue
        power = power_by_id[session.cp_id]
        duration = (session.end-session.start).total_seconds()
        energy = min(session.energy_kwh, power*duration/3600)
        charge_seconds = energy/power*3600
        relative_start, relative_end = (session.start-start).total_seconds(), (session.end-start).total_seconds()
        for output, low, high, rate in [(early, relative_start, relative_start+charge_seconds, power),
                                        (late, relative_end-charge_seconds, relative_end, power),
                                        (average, relative_start, relative_end, energy*3600/duration)]:
            output += rate*np.maximum(0, np.minimum(starts+600, high)-np.maximum(starts, low))/600
    return dict(afap=early, alap=late, avg=average)


def reference_minimum_carbon(chargers, sessions, start, end, costs):
    """The per-session greedy fill the vectorized schedule replaced."""
    count = int((end-start).total_seconds()/600)
    powers = {int(charger["id"]): point_power(charger) for charger in chargers}
    offsets, profile = np.arange(count)*600., np.zeros(count)
    for record in sessions:
        if record.energy_kwh <= 1e-12:
            continue
        low, high = (record.start-start).total_seconds(), (record.end-start).total_seconds()
        capacity = powers[record.cp_id]*np.maximum(0., np.minimum(offsets+600, high)-np.maximum(offsets, low))/3600
        candidates = np.flatnonzero(capacity > 1e-12)
        remaining = record.energy_kwh
        for index in candidates[np.lexsort((candidates, costs[candidates]))]:
            energy = min(remaining, capacity[index])
            profile[index] += energy*6
            remaining -= energy
            if remaining <= 1e-10:
                break
    return profile


def test_vectorized_profiles_and_carbon_schedule_match_the_per_session_versions():
    start, end = window(date(2026, 10, 24), date(2026, 10, 25))  # includes the 25-hour day
    sessions = sample_world(CHARGERS, start, end, profiles=PROFILES, source="spatial").records()
    expected = reference_profiles(CHARGERS, sessions, start, end)
    costs = RNG.uniform(50, 400, int((end-start).total_seconds()/600)).round()  # ties are broken by time
    for strategy in ("afap", "alap", "avg"):
        profile, up, down = simulate_scenarios(CHARGERS, sessions, start, end, strategy)
        np.testing.assert_allclose(profile, expected[strategy], rtol=1e-9, atol=1e-8)
        np.testing.assert_allclose(up, np.maximum(expected["afap"]-expected[strategy], 0), atol=1e-8)
    balanced = balanced_sessions(CHARGERS, sessions, start, end)
    np.testing.assert_allclose(minimum_carbon_profile(CHARGERS, balanced, start, end, costs),
                               reference_minimum_carbon(CHARGERS, balanced.records(), start, end, costs), rtol=1e-9, atol=1e-7)


@pytest.fixture(scope="module")
def library(tmp_path_factory):
    return CPFTLibrary(write_test_library(tmp_path_factory.mktemp("cpft")/"library.npz"))


@pytest.mark.parametrize("target,horizon", [(date(2026, 10, 15), 30), (date(2026, 3, 29), 29), (date(2026, 10, 25), 31)])
def test_cpft_history_stops_at_issue_and_forecast_covers_the_target_day(library, target, horizon):
    frame, info = sample_cpft(CHARGERS, target, profiles=PROFILES, library=library)
    issue = issue_time(target, ZONE).timestamp()
    assert info["horizon_hours"] == horizon
    history, forecast = frame.select(frame.start < issue), frame.select(frame.start >= issue)
    assert (history.end <= issue).all()
    # CPFT forecasts elapsed UTC hours: 16 hours after issue is 10:00 local, or
    # 09:00/11:00 on the days the clocks change
    assert len(forecast) == len(CHARGERS)
    assert set(forecast.start) == {issue+16*3600} and set(forecast.end) == {issue+17*3600}
    _, end = day_window(target, ZONE)
    assert issue+horizon*3600 == end.timestamp()
    power = np.array([point_power(next(c for c in CHARGERS if c["id"] == cp_id)) for cp_id in forecast.cp_id])
    np.testing.assert_allclose(forecast.energy_kwh, np.minimum(2., power))


def test_cpft_days_are_the_same_alone_or_in_a_range(tmp_path):
    service = SessionSourceService(atlas_path=tmp_path/"missing.gpkg", library_path=write_test_library(tmp_path/"library.npz"))
    daily, metadata = service.days(CHARGERS, date(2026, 10, 13), date(2026, 10, 16), source="cpft", seed=3)
    for day, frame in daily:
        assert frame.equals(service.get(CHARGERS, day, source="cpft", seed=3)[0])
    assert metadata["generated"] == "on request" and metadata["issue_hour_local"] == 18


def test_cpft_volume_between_bins_mixes_the_neighbouring_bins(tmp_path):
    library = CPFTLibrary(write_test_library(tmp_path/"marked.npz", mark_volume=True))
    chargers = [dict(id=cp_id, power=11.) for cp_id in range(1, 4001)]
    # 2.5 arrivals/day lies between the 2 and 3 bins; marked energy is 1 + the bin index
    lower, upper = 1.+VOLUME_BINS.index(2.), 1.+VOLUME_BINS.index(3.)
    profiles = [{"weights": {"mixed": 1.}, "arrival_multiplier": 1.25}]*len(chargers)
    frame, info = sample_cpft(chargers, date(2026, 5, 5), profiles=profiles, library=library)
    forecast = frame.select(frame.start >= issue_time(date(2026, 5, 5), ZONE).timestamp())
    assert set(np.round(forecast.energy_kwh)) == {lower, upper}
    expected = np.log(2.5/2)/np.log(3/2)
    assert np.mean(forecast.energy_kwh > lower+.5) == pytest.approx(expected, abs=.03)
    assert info["outside_volume_range"] == 0
    exact, _ = sample_cpft(chargers[:500], date(2026, 5, 5), library=library)  # generic 2/day: exactly the 2/day bin
    assert set(np.round(exact.select(exact.start >= issue_time(date(2026, 5, 5), ZONE).timestamp()).energy_kwh)) == {lower}
    zero, info = sample_cpft(chargers[:5], date(2026, 5, 5), profiles=[{"weights": {"mixed": 1.}, "arrival_multiplier": 0.}]*5,
                             library=library)
    assert len(zero) == 0 and info["zero_volume_points"] == 5
