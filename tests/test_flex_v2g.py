"""Bidirectional flexibility: the closed-form bounds against linear programming and the one-way model."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from scipy.linalg import block_diag
from scipy.optimize import linprog

from backend.flex_polytope import build_polytope, envelopes
from backend.flex_v2g import V2GFlexibility, connection_ranges
from backend.session_frame import SessionFrame
from tests.reflex_fakes import optimiser

UTC = timezone.utc
START = datetime(2026, 10, 14, 22, tzinfo=UTC)
END = START+timedelta(hours=8)  # a short window keeps the linear programmes small
CHARGERS = [dict(id=1, power=11.), dict(id=2, power=7.4), dict(id=3, power=22.)]


def frame(*rows):
    """(point, start hours after START, end hours after START, kWh); some cross the window edges."""
    stamp = lambda hours: (START+timedelta(hours=hours)).timestamp()
    return SessionFrame(np.array([row[0] for row in rows]), np.array([stamp(row[1]) for row in rows]),
                        np.array([stamp(row[2]) for row in rows]), np.array([row[3] for row in rows], float))


SESSIONS = frame((1, -2.37, 3.15, 18.), (2, 0.5, 2.05, 4.), (3, 4.12, 9.4, 30.), (1, 4.5, 7.93, 12.), (2, 6.2, 6.3, 1.))


def linear_programme_bounds(depth, weights):
    """Most and least fleet energy for per-window-step `weights`, solved jointly over every connection's stay."""
    first, charge, discharge, _, _ = connection_ranges(CHARGERS, SESSIONS, START, END, depth)
    width = charge.shape[1]
    energy = np.minimum(SESSIONS.energy_kwh, charge.sum(1))
    running = np.tril(np.ones((width, width)))
    blocks = [np.vstack([running, -running])]*len(first)
    a_ub = block_diag(*blocks)
    b_ub = np.concatenate([np.concatenate([np.full(width, e), np.full(width, depth)]) for e in energy])
    a_eq = block_diag(*[np.ones((1, width))]*len(first))
    bounds = [bound for c, d in zip(charge, discharge) for bound in zip(-d, c)]
    base = int(START.timestamp()//600)
    objective = np.concatenate([np.array([weights[first[i]+r-base] if 0 <= first[i]+r-base < len(weights) else 0.
                                          for r in range(width)])
                                for i in range(len(first))])
    solve = lambda sign: linprog(sign*objective, A_ub=a_ub, b_ub=b_ub, A_eq=a_eq, b_eq=energy,
                                 bounds=bounds, method="highs")
    most, least = solve(-1), solve(1)
    assert most.status == least.status == 0
    return -most.fun, least.fun


@pytest.mark.parametrize("depth", [0., 6.])
def test_bounds_match_linear_programming(depth):
    flexibility = V2GFlexibility(CHARGERS, SESSIONS, START, END, depth)
    envelope = flexibility.envelopes()
    steps = flexibility.count
    for step in (0, 3, 17, 25, 33, steps-1):
        weights = np.zeros(steps)
        weights[step] = 1
        most, least = linear_programme_bounds(depth, weights)
        assert envelope["power_max_kw"][step]/6 == pytest.approx(most, abs=1e-7)
        assert envelope["power_min_kw"][step]/6 == pytest.approx(least, abs=1e-7)
    for step in (5, 20, steps-1):
        weights = (np.arange(steps) <= step).astype(float)
        most, least = linear_programme_bounds(depth, weights)
        assert envelope["cumulative_max_kwh"][step] == pytest.approx(most, abs=1e-7)
        assert envelope["cumulative_min_kwh"][step] == pytest.approx(least, abs=1e-7)
    for j, k in ((3, 17), (12, 38), (25, steps)):
        weights = ((np.arange(steps) >= j) & (np.arange(steps) < k)).astype(float)
        most, least = linear_programme_bounds(depth, weights)
        actual_max, actual_min = flexibility.interval([j], [k])
        assert actual_max[0] == pytest.approx(most, abs=1e-7)
        assert actual_min[0] == pytest.approx(least, abs=1e-7)
    assert envelope["total_max_kwh"] == pytest.approx(envelope["cumulative_max_kwh"][-1])


def test_discharge_widens_the_band_below_zero():
    one_way = V2GFlexibility(CHARGERS, SESSIONS, START, END, 0., discharge_share=0.).envelopes()
    both = V2GFlexibility(CHARGERS, SESSIONS, START, END, 6.).envelopes()
    assert min(one_way["power_min_kw"]) >= 0 and min(both["power_min_kw"]) < 0
    assert all(b <= a+1e-9 for a, b in zip(one_way["cumulative_min_kwh"], both["cumulative_min_kwh"]))


def test_without_discharge_it_is_the_one_way_envelope():
    one_way = envelopes(build_polytope(CHARGERS, SESSIONS, START, END))
    same = V2GFlexibility(CHARGERS, SESSIONS, START, END, 0., discharge_share=0.).envelopes()
    for key in one_way:
        assert np.allclose(same[key], one_way[key], atol=1e-9), key


def test_v2g_schedules_lie_inside_and_others_do_not(tmp_path):
    cost = optimiser(tmp_path, v2g_depth_kwh=6.)
    [(load, _, _)], _ = cost.profiles(CHARGERS, [SESSIONS], START, END, "v2g", background=True)
    flexibility = V2GFlexibility(CHARGERS, SESSIONS, START, END, 6.)
    assert min(load) < 0 and flexibility.contains(load)
    too_much = list(load)
    too_much[10] += 60
    assert not flexibility.contains(too_much)
    deeper = list(load)
    deeper[12] -= 100  # more discharge than the plugs and batteries allow
    assert not flexibility.contains(deeper)


def test_an_empty_selection_has_no_flexibility():
    envelope = V2GFlexibility(CHARGERS, SessionFrame.empty(), START, END, 6.).envelopes()
    assert envelope["total_max_kwh"] == envelope["total_min_kwh"] == 0
    assert not any(envelope["power_max_kw"]) and not any(envelope["power_min_kw"])
