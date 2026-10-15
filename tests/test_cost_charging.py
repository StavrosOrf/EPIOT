"""Minimum-cost and V2G charging through ReFlex, the plan store and the price store, without a network."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from backend.cost_charging import (
    STEP_HOURS, CostSettings, PlanStore, cheapest_first, complete, v2g_lp,
)
from backend.day_ahead_prices import PricesUnavailable, PriceStore, price_zone
from backend.session_frame import SessionFrame
from tests.reflex_fakes import FakeReflex, PriceFeed, optimiser, parse, price_at

UTC = timezone.utc
START = datetime(2026, 10, 13, 22, tzinfo=UTC)  # local midnight in Amsterdam, a two-day window
END = START+timedelta(days=2)
CHARGERS = [dict(id=1, power=11., country="Netherlands"), dict(id=2, power=22., country="Germany"),
            dict(id=3, power=3.7, country=None)]


def frame(*rows):
    """Sessions as (point, start hours after START, end hours after START, kWh)."""
    stamp = lambda hours: (START+timedelta(hours=hours)).timestamp()
    return SessionFrame(np.array([row[0] for row in rows]), np.array([stamp(row[1]) for row in rows]),
                        np.array([stamp(row[2]) for row in rows]), np.array([row[3] for row in rows], float))


SESSIONS = frame((1, 1.05, 9.92, 30.), (1, 17.13, 20., 12.), (2, 8.05, 11., 25.), (3, 30.5, 30.6, 3.),
                 (3, 40.02, 47.7, 20.))


def energy_of(load):
    return sum(load)*STEP_HOURS


def test_plans_deliver_the_requested_energy_within_plug_limits(tmp_path):
    cost = optimiser(tmp_path)
    [(load, up, down)], summary = cost.profiles(CHARGERS, [SESSIONS], START, END, "ocost")
    # Energy is capped by what the plug can deliver while connected (the 6-minute session)
    delivered = 30+12+25+3.7*0.1+20
    assert energy_of(load) == pytest.approx(delivered, abs=1e-6)
    assert min(load) >= -1e-9 and min(up) >= -1e-9
    assert np.allclose(np.asarray(down), -np.asarray(load))
    assert summary["connections"] == 5 and summary["optimised_now"] == 4 and summary["scheduled_locally"] == 1
    assert summary["reflex_plans_replaced"] == 0
    assert summary["price_zones"] == {"NL": 4, "DE-LU": 1} and summary["price_zone_stand_ins"] == 2


def test_cost_plans_are_cheaper_than_charging_on_arrival(tmp_path):
    cost = optimiser(tmp_path)
    problems, _ = cost.problems(CHARGERS, SESSIONS, "ocost")
    stored = cost.plans
    cost.profiles(CHARGERS, [SESSIONS], START, END, "ocost")
    plans = stored.get_many(problems.keys)
    for index, key in enumerate(problems.keys):
        plan = plans[key][1]*STEP_HOURS
        capacity = problems.capacity(index)
        assert (plan <= capacity+1e-9).all()
        arrival = cheapest_first(np.arange(len(capacity)), capacity, problems.energy[index])
        assert plan@problems.prices[index] <= arrival@problems.prices[index]+1e-9


def test_a_second_request_and_the_next_window_read_the_store(tmp_path):
    reflex = FakeReflex()
    cost = optimiser(tmp_path, reflex)
    first, _ = cost.profiles(CHARGERS, [SESSIONS], START, END, "ocost")
    calls = len(reflex.queries)
    again, summary = cost.profiles(CHARGERS, [SESSIONS], START, END, "ocost")
    assert again == first and len(reflex.queries) == calls
    assert summary["from_store"] == 5 and summary["optimised_now"] == 0
    # The following window shares the sessions of its first day: only the new one is optimised
    later = SessionFrame.concat([SESSIONS, frame((2, 50., 55., 10.))])
    _, summary = cost.profiles(CHARGERS, [later], START+timedelta(days=1), END+timedelta(days=1), "ocost")
    assert summary["optimised_now"] == 1
    assert sum(len(query["assets"]["evChargePoints"]) for query in reflex.queries[calls:]) == 1


def test_draws_are_optimised_together_and_strategies_kept_apart(tmp_path):
    reflex = FakeReflex()
    cost = optimiser(tmp_path, reflex)
    other = frame((1, 3., 12., 20.), (2, 30., 33.5, 15.))
    profiles, summary = cost.profiles(CHARGERS, [SESSIONS, other], START, END, "ocost")
    assert len(profiles) == 2 and len(reflex.queries) == 2  # one run per price zone
    assert energy_of(profiles[1][0]) == pytest.approx(35, abs=1e-6)
    _, summary = cost.profiles(CHARGERS, [other], START, END, "v2g")
    assert summary["from_store"] == 0


def test_requests_follow_reflex_quirks(tmp_path):
    reflex = FakeReflex()
    cost = optimiser(tmp_path, reflex)
    cost.profiles(CHARGERS, [frame((1, 1.05, 9.92, 30.), (1, 10., 12., 5.))], START, END, "ocost")
    cost.profiles(CHARGERS, [frame((1, 1.05, 9.92, 30.))], START, END, "v2g")
    one_way, v2x = reflex.queries
    first, second = one_way["assets"]["evChargePoints"]
    assert first["id"] != second["id"]  # every connection is a charge point of its own
    (session,) = first["chargeSessions"]
    # Whole intervals only: 01:10 to 09:50 (exclusive) is sent as 01:10 to 09:40 (inclusive)
    assert parse(session["startTime"]) == START+timedelta(hours=1, minutes=10)
    assert parse(session["endTime"]) == START+timedelta(hours=9, minutes=40)
    assert session["energyToCharge"] == round(30*3.6e6) and "minEnergyToCharge" not in session
    (point,) = v2x["assets"]["evChargePoints"]
    assert parse(point["chargeSessions"][0]["endTime"]) == START+timedelta(hours=9, minutes=50)
    assert point["maxDischargePower"] == 11000
    assert point["chargeSessions"][0]["minEnergyDuringCharging"] == -round(10*3.6e6)
    assert {element["targetType"] for query in reflex.queries for element in query["globalTarget"]["elements"]} == {"price"}


def test_short_connections_never_reach_reflex(tmp_path):
    reflex = FakeReflex()
    cost = optimiser(tmp_path, reflex)
    [(load, _, _)], summary = cost.profiles(CHARGERS, [frame((1, 2.02, 2.3, 2.))], START, END, "ocost")
    assert reflex.queries == [] and summary["scheduled_locally"] == 1
    assert energy_of(load) == pytest.approx(2, abs=1e-9)


def test_a_plan_that_breaks_a_limit_is_replaced_and_counted(tmp_path):
    def over_power(point, plan):
        plan = plan.copy()
        plan[np.argmax(plan)] *= 2
        return plan
    cost = optimiser(tmp_path, FakeReflex(distort=over_power))
    [(load, _, _)], summary = cost.profiles(CHARGERS, [SESSIONS], START, END, "ocost")
    assert summary["reflex_plans_replaced"] == 4 and summary["by_reflex"] == 0
    assert energy_of(load) == pytest.approx(30+12+25+0.37+20, abs=1e-6)


def test_over_delivery_is_trimmed_in_the_dearest_steps(tmp_path):
    def too_much(point, plan):
        plan = plan.copy()
        first = np.flatnonzero(plan == 0)[0]
        plan[first] = point["maxChargePower"]*600*0.1
        return plan
    cost = optimiser(tmp_path, FakeReflex(distort=too_much))
    [(load, _, _)], summary = cost.profiles(CHARGERS, [frame((1, 1., 9., 30.))], START, END, "ocost")
    assert summary["energy_adjusted"] == 1 and summary["reflex_plans_replaced"] == 0
    assert energy_of(load) == pytest.approx(30, abs=1e-9)


def test_v2g_returns_energy_and_keeps_the_battery_limits(tmp_path):
    cost = optimiser(tmp_path, v2g_depth_kwh=8.)
    sessions = frame((1, 12.03, 34.97, 20.), (2, 14., 40., 5.))
    [(load, up, down)], summary = cost.profiles(CHARGERS, [sessions], START, END, "v2g")
    assert summary["energy_adjusted"] == 2 and summary["v2g_depth_kwh"] == 8
    assert min(load) < 0 and energy_of(load) == pytest.approx(25, abs=1e-6)
    problems, _ = cost.problems(CHARGERS, sessions, "v2g")
    for (first, power, solver), index in zip(cost.plans.get_many(problems.keys).values(), range(2)):
        running = np.cumsum(power*STEP_HOURS)
        assert running.min() >= -8-1e-9 and running.max() <= problems.energy[index]+1e-9
        assert running[-1] == pytest.approx(problems.energy[index])
    assert all(low <= 1e-9 for low in down)
    # Cheaper than the one-way optimum on the same sessions
    one_way, _ = cost.profiles(CHARGERS, [sessions], START, END, "ocost")
    prices = np.array([price_at(START.timestamp()+600*step+300) for step in range(288)])
    assert np.dot(load, prices) < np.dot(one_way[0][0], prices)


def test_new_prices_make_a_new_plan(tmp_path):
    feed = PriceFeed(published=datetime(2026, 10, 14, tzinfo=UTC))
    reflex = FakeReflex()
    clock = [datetime(2026, 10, 14, 12, tzinfo=UTC).timestamp()]
    cost = optimiser(tmp_path, reflex, feed)
    cost.prices.clock = lambda: clock[0]
    sessions = frame((1, 30., 40., 20.))  # on the 15th: not published yet
    _, summary = cost.profiles(CHARGERS, [sessions], START, END, "ocost")
    assert summary["prices_use_reference"] is True
    feed.published, clock[0] = datetime(2026, 10, 15, tzinfo=UTC), clock[0]+86400
    _, summary = cost.profiles(CHARGERS, [sessions], START, END, "ocost")
    assert summary["prices_use_reference"] is False and summary["optimised_now"] == 1


def test_prices_are_exact_time_weighted_means_on_the_ten_minute_grid(tmp_path):
    feed = PriceFeed()
    store = PriceStore(tmp_path/"p.sqlite", fetch=feed, clock=lambda: datetime(2026, 10, 15, 12, tzinfo=UTC).timestamp())
    first = int(datetime(2026, 10, 14, tzinfo=UTC).timestamp())//600
    values, reference = store.prices("NL", first, 6)
    unix = first*600
    assert values[1] == pytest.approx((price_at(unix)+price_at(unix+900))/2)  # 00:10-00:20 spans two quarters
    assert not reference.any()
    calls = len(feed.calls)
    store.prices("NL", first, 6)
    assert len(feed.calls) == calls  # known days stay local


def test_unpublished_days_use_the_nearest_published_day_and_are_flagged(tmp_path):
    feed = PriceFeed(published=datetime(2026, 10, 15, tzinfo=UTC))
    store = PriceStore(tmp_path/"p.sqlite", fetch=feed, clock=lambda: datetime(2026, 10, 15, 12, tzinfo=UTC).timestamp())
    first = int(datetime(2026, 10, 15, 23, tzinfo=UTC).timestamp())//600
    values, reference = store.prices("NL", first, 12)
    assert reference[6:].all() and not reference[:6].any()
    assert values[6] == pytest.approx(store.prices("NL", first+6-144, 1)[0][0])
    # Days that cannot be published yet are not asked for again and again
    calls = len(feed.calls)
    store.prices("NL", first, 12)
    assert len(feed.calls) == calls


def test_no_prices_at_all_is_an_explicit_error(tmp_path):
    store = PriceStore(tmp_path/"p.sqlite", fetch=lambda zone, start, end: [])
    with pytest.raises(PricesUnavailable):
        store.prices("NL", 2_900_000, 10)


def test_countries_map_to_bidding_zones():
    assert price_zone("Germany") == ("DE-LU", False)
    assert price_zone("United Kingdom") == ("NL", True) and price_zone(None) == ("NL", True)


def test_local_solvers_are_optimal_and_feasible():
    prices = np.array([50., 10., 80., 5., 60.])
    plan = cheapest_first(prices, np.full(5, 2.), 3.)
    assert plan.tolist() == [0, 1, 0, 2, 0]
    kwh = v2g_lp(prices, np.full(5, 2.), 2., 3., 1.)
    running = np.cumsum(kwh)
    assert running[-1] == pytest.approx(3) and running.min() >= -1-1e-9 and running.max() <= 3+1e-9
    assert kwh@prices < plan@prices
    adjusted = complete(np.array([2., 0, 0, 0, 0]), prices, np.full(5, 2.), np.zeros(5), 3., 0.)
    assert adjusted.tolist() == [2, 0, 0, 1, 0]
    assert complete(np.zeros(2), prices[:2], np.full(2, 1.), np.zeros(2), 3., 0.) is None


def test_settings_are_validated():
    assert CostSettings.from_config({"REFLEX_V2G_DEPTH_KWH": "5"}).v2g_depth_kwh == 5
    with pytest.raises(ValueError):
        CostSettings.from_config({"REFLEX_PARALLEL_RUNS": 0})


def test_plan_store_round_trip(tmp_path):
    store = PlanStore(tmp_path/"plans.sqlite")
    store.put_many({"a": (7, np.array([1., 2.5]), "reflex")})
    first, power, solver = store.get_many(["a", "b"])["a"]
    assert (first, power.tolist(), solver) == (7, [1, 2.5], "reflex")


def test_dates_far_ahead_use_the_latest_published_day(tmp_path):
    feed = PriceFeed(published=datetime(2026, 10, 16, tzinfo=UTC))
    store = PriceStore(tmp_path/"p.sqlite", fetch=feed, clock=lambda: datetime(2026, 10, 15, 12, tzinfo=UTC).timestamp())
    first = int(datetime(2026, 12, 1, tzinfo=UTC).timestamp())//600
    values, reference = store.prices("NL", first, 6)
    assert reference.all()
    newest = int(datetime(2026, 10, 16, tzinfo=UTC).timestamp())
    assert values[0] == pytest.approx(price_at(newest))  # the first quarter-hour holds the whole step
