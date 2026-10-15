"""Polytope (generalized-polymatroid) view of aggregate EV charging flexibility.

Each connection i may charge x_i with 0 <= x_it <= U_it (kWh per step the plug
can deliver while connected) and e_min_i <= sum_t x_it <= e_max_i. These sets
are g-polymatroids (Mukhi & Abate, arXiv:2306.16824; Mukhi, Loho & Abate,
arXiv:2503.23458), so the Minkowski sum over connections is described by the
sum of the per-connection bounds: for a set of steps A the aggregate can deliver
at most b(A) = sum_i min(e_max_i, U_i(A)) and at least
p(A) = sum_i max(0, e_min_i - U_i(not A)). Every query is O(N) numpy.
"""

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix

from backend.scenario_profiles import point_powers
from backend.session_frame import as_frame, epoch

STEP_SECONDS = 600.
STEP_HOURS = STEP_SECONDS/3600


@dataclass(frozen=True)
class FlexPolytope:
    capacity: np.ndarray  # (N, T) kWh each connection can take per step
    e_min: np.ndarray     # (N,) kWh that must be delivered inside the window
    e_max: np.ndarray     # (N,) kWh that can be delivered inside the window

    @property
    def steps(self):
        return self.capacity.shape[1]


def build_polytope(chargers, sessions, start, end):
    """Capacity matrix and energy range per connection on the 10-minute grid.

    `sessions` is a SessionFrame or any iterable of ScenarioSession. Energy
    outside [start, end) is charged at full power, so a connection crossing the
    window edge only has to deliver what does not fit outside.
    """
    steps = int((end-start).total_seconds()/STEP_SECONDS)
    frame = as_frame(sessions)
    power = point_powers(chargers, frame.cp_id)
    low, high = epoch(start), epoch(end)
    keep = ~np.isnan(power) & (frame.end > low) & (frame.start < high)
    frame, power = frame.select(keep), power[keep]
    duration = frame.end-frame.start
    energy = np.minimum(frame.energy_kwh, power*duration/3600)
    left, right = (frame.start-low)[:, None], (frame.end-low)[:, None]
    edges = np.arange(steps)*STEP_SECONDS
    overlap = np.maximum(0., np.minimum(edges+STEP_SECONDS, right)-np.maximum(edges, left))
    capacity = power[:, None]*overlap/3600
    inside = capacity.sum(1)
    outside = power*duration/3600-inside
    return FlexPolytope(capacity.reshape(len(frame), steps), np.maximum(0., energy-outside),
                        np.minimum(energy, inside))


def upper_energy(poly, mask):
    """b(A): most energy the fleet can deliver within the steps in `mask`."""
    return float(np.minimum(poly.e_max, poly.capacity@mask).sum())


def lower_energy(poly, mask):
    """p(A): least energy the fleet must deliver within the steps in `mask`."""
    outside = poly.capacity.sum(1)-poly.capacity@mask
    return float(np.maximum(0., poly.e_min-outside).sum())


def envelopes(poly):
    """Cumulative energy band and per-step power bounds (kWh / kW)."""
    capacity, e_min, e_max = poly.capacity, poly.e_min[:, None], poly.e_max[:, None]
    cumulative = np.cumsum(capacity, axis=1)
    remaining = capacity.sum(1)[:, None]-cumulative
    outside_step = capacity.sum(1)[:, None]-capacity
    return {
        "cumulative_max_kwh": np.minimum(e_max, cumulative).sum(0).tolist(),
        "cumulative_min_kwh": np.maximum(0., e_min-remaining).sum(0).tolist(),
        "power_max_kw": (np.minimum(e_max, capacity).sum(0)/STEP_HOURS).tolist(),
        "power_min_kw": (np.maximum(0., e_min-outside_step).sum(0)/STEP_HOURS).tolist(),
        "total_min_kwh": float(poly.e_min.sum()),
        "total_max_kwh": float(poly.e_max.sum()),
    }


def contains(poly, load_kw, tol=1e-6):
    """Necessary check that an aggregate profile lies in the polytope.

    Verifies all prefix and suffix energy bounds and per-step power bounds.
    """
    energy = np.asarray(load_kw, float)*STEP_HOURS
    env = envelopes(poly)
    cum = np.cumsum(energy)
    total = energy.sum()
    ok = (cum <= np.array(env["cumulative_max_kwh"])+tol).all()
    ok &= (cum >= np.array(env["cumulative_min_kwh"])-tol).all()
    ok &= (energy <= np.array(env["power_max_kw"])*STEP_HOURS+tol).all()
    ok &= (energy >= np.array(env["power_min_kw"])*STEP_HOURS-tol).all()
    ok &= env["total_min_kwh"]-tol <= total <= env["total_max_kwh"]+tol
    return bool(ok)


def window_flexibility(poly, baseline_kw, mask):
    """Energy (kWh) the window can absorb above / shed below the baseline."""
    mask = np.asarray(mask, float)
    scheduled = float((np.asarray(baseline_kw, float)*STEP_HOURS)@mask)
    return {"absorbable_kwh": max(0., upper_energy(poly, mask)-scheduled),
            "sheddable_kwh": max(0., scheduled-lower_energy(poly, mask))}


def max_sustained_reduction(poly, baseline_kw, mask):
    """Largest R (kW) such that load <= baseline - R on every step in `mask`.

    Exact disaggregated LP over the polytope; every connection keeps its energy
    range and per-step limit. Returns 0 if no reduction is feasible.
    """
    mask = np.asarray(mask, bool)
    n, t = poly.capacity.shape
    idx_i, idx_t = np.nonzero(poly.capacity > 1e-12)
    m = len(idx_i)
    if n == 0 or m == 0 or not mask.any():
        return 0.
    window = np.flatnonzero(mask)
    position = np.full(t, -1)
    position[window] = np.arange(len(window))
    # rows: window steps (sum x + R <= baseline), then energy max and min per session
    in_window = position[idx_t] >= 0
    rows = np.concatenate([position[idx_t[in_window]], len(window)+idx_i, len(window)+n+idx_i])
    cols = np.concatenate([np.flatnonzero(in_window), np.arange(m), np.arange(m)])
    vals = np.concatenate([np.ones(in_window.sum()), np.ones(m), -np.ones(m)])
    rows = np.concatenate([rows, np.arange(len(window))])
    cols = np.concatenate([cols, np.full(len(window), m)])
    vals = np.concatenate([vals, np.ones(len(window))])
    a = coo_matrix((vals, (rows, cols)), shape=(len(window)+2*n, m+1)).tocsr()
    b = np.concatenate([np.asarray(baseline_kw, float)[window]*STEP_HOURS, poly.e_max, -poly.e_min])
    cost = np.zeros(m+1)
    cost[m] = -1
    bounds = [(0, c) for c in poly.capacity[idx_i, idx_t]]+[(0, None)]
    result = linprog(cost, A_ub=a, b_ub=b, bounds=bounds, method="highs")
    return float(result.x[m]/STEP_HOURS) if result.status == 0 else 0.
