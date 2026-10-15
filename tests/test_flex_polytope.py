import itertools
from datetime import datetime, timedelta, timezone

import numpy as np
from scipy.optimize import linprog

from backend.flex_polytope import (
    build_polytope, contains, envelopes, lower_energy, max_sustained_reduction,
    upper_energy, window_flexibility,
)
from backend.scenario_sampling import ScenarioSession

START = datetime(2025, 1, 15, tzinfo=timezone.utc)
T = 6
END = START+timedelta(minutes=10*T)
CHARGERS = [{"id": 1, "power": 6.}, {"id": 2, "power": 12.}, {"id": 3, "power": 6.}]


def step(n):
    return START+timedelta(minutes=10*n)


SESSIONS = [
    ScenarioSession(1, step(0), step(4), 2.5),
    ScenarioSession(2, step(1), step(6), 5.),
    ScenarioSession(3, step(-2), step(3), 3.),   # crosses the window start
]


def brute(poly, mask, sense):
    n, t = poly.capacity.shape
    m = n*t
    a_eq = np.zeros((n, m))
    for i in range(n):
        a_eq[i, i*t:(i+1)*t] = 1
    cost = np.tile(mask.astype(float), n)*sense
    # energy range as two inequalities
    res = linprog(cost, A_ub=np.vstack([a_eq, -a_eq]),
                  b_ub=np.concatenate([poly.e_max, -poly.e_min]),
                  bounds=[(0, c) for c in poly.capacity.ravel()], method="highs")
    return res.fun*sense


def test_set_bounds_match_lp_for_every_subset():
    poly = build_polytope(CHARGERS, SESSIONS, START, END)
    for bits in itertools.product([0, 1], repeat=T):
        mask = np.array(bits, float)
        assert np.isclose(upper_energy(poly, mask), brute(poly, mask, -1))
        assert np.isclose(lower_energy(poly, mask), brute(poly, mask, 1))


def test_edge_session_must_deliver_only_what_does_not_fit_outside():
    poly = build_polytope(CHARGERS, SESSIONS, START, END)
    # 6 kW for 50 min = 5 kWh capacity; 2 steps (2 kWh) outside, 3 kWh needed
    assert np.isclose(poly.e_min[2], 1.)
    assert np.isclose(poly.e_max[2], 3.)


def test_envelopes_contain_afap_and_reject_overload():
    poly = build_polytope(CHARGERS, SESSIONS, START, END)
    env = envelopes(poly)
    assert env["cumulative_max_kwh"][-1] >= env["cumulative_min_kwh"][-1]
    load = np.array(env["power_min_kw"])
    assert contains(poly, load) == (load.sum()*(1/6) >= env["total_min_kwh"]-1e-6)
    assert not contains(poly, np.full(T, 1000.))


def test_window_and_sustained_reduction():
    poly = build_polytope(CHARGERS, SESSIONS, START, END)
    mask = np.array([0, 1, 1, 1, 0, 0], bool)
    baseline = np.array(envelopes(poly)["power_max_kw"])
    baseline = np.minimum(baseline, 6.)
    window = window_flexibility(poly, baseline, mask)
    assert window["sheddable_kwh"] >= 0 and window["absorbable_kwh"] >= 0
    reduction = max_sustained_reduction(poly, baseline, mask)
    assert 0 <= reduction <= baseline[mask].min()+1e-9
