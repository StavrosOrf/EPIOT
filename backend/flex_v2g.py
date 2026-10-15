"""Exact aggregate flexibility of bidirectional (vehicle-to-grid) charging.

A connection may charge c_t and discharge d_t kWh per step while plugged in.
Its running energy since arrival, S_t, stays in [-depth, E] and ends at E,
the energy it leaves with: the limits the V2G strategy gives ReFlex. Such a
lossless device is a generalised polymatroid (Mukhi, Loho & Abate,
arXiv:2503.23458, Lemma 1), so every bound of the fleet is the sum of the
connections' bounds.

Only interval bounds are needed. The constraints are differences between
neighbouring S_t, so one forward and one backward pass give the exact range
[L_t, H_t] of each S_t, and the most energy over steps j+1..k is
min(sum c, H_k - L_j), the least max(-sum d, L_k - H_j). A connection is
modelled over its whole stay and the window takes S_k - S_(window start), so
crossing the window edge needs no correction. Cost: O(connections x steps).
"""

import numpy as np

from backend.scenario_profiles import point_powers
from backend.session_frame import as_frame, epoch

STEP = 600.
STEP_HOURS = STEP/3600


def connection_ranges(chargers, sessions, start, end, depth, discharge_share=1.):
    """Per connection over its own steps: charge and discharge limits and the range of S.

    Rows are connections touching [start, end); column r is the r-th step from
    the step of arrival (padded with zero limits). Returns (first absolute step,
    c, d, L, H), with L and H one column longer (S before each step and at the end).
    """
    frame = as_frame(sessions)
    power = point_powers(chargers, frame.cp_id)
    left, right = epoch(start), epoch(end)
    keep = ~np.isnan(power) & (frame.end > left) & (frame.start < right)
    frame, power = frame.select(keep), power[keep]
    first = np.floor(frame.start/STEP).astype(np.int64)
    steps = np.ceil(frame.end/STEP).astype(np.int64)-first
    width = int(steps.max(initial=0))
    edges = (first[:, None]+np.arange(width+1)[None, :])*STEP
    plugged = np.clip(np.minimum(edges[:, 1:], frame.end[:, None])-np.maximum(edges[:, :-1], frame.start[:, None]), 0, STEP)
    charge = power[:, None]*plugged/3600
    discharge = discharge_share*charge
    energy = np.minimum(frame.energy_kwh, charge.sum(1))
    count = len(frame)
    high, low = np.empty((count, width+1)), np.empty((count, width+1))
    high[:, 0] = low[:, 0] = 0.
    for r in range(1, width+1):
        high[:, r] = np.minimum(energy, high[:, r-1]+charge[:, r-1])
        low[:, r] = np.maximum(-depth, low[:, r-1]-discharge[:, r-1])
    # The vehicle leaves with exactly E (padding steps after departure have no limits)
    high[:, width] = low[:, width] = energy
    for r in range(width, 0, -1):
        high[:, r-1] = np.minimum(high[:, r-1], high[:, r]+discharge[:, r-1])
        low[:, r-1] = np.maximum(low[:, r-1], low[:, r]-charge[:, r-1])
    return first, charge, discharge, low, high


class V2GFlexibility:
    """The fleet's interval bounds on the window [start, end), in kWh."""

    def __init__(self, chargers, sessions, start, end, depth, discharge_share=1.):
        self.count = int((end-start).total_seconds()/STEP)
        self.base = int(epoch(start)//STEP)
        self.first, self.charge, self.discharge, self.low, self.high = connection_ranges(
            chargers, sessions, start, end, depth, discharge_share)
        width = self.charge.shape[1]
        self.charged = np.concatenate([np.zeros((len(self.first), 1)), np.cumsum(self.charge, 1)], 1)
        self.discharged = np.concatenate([np.zeros((len(self.first), 1)), np.cumsum(self.discharge, 1)], 1)
        self.width = width

    def _index(self, boundaries):
        """Column of S at window boundaries (0 = window start) for every connection."""
        return np.clip(self.base+np.asarray(boundaries)[None, :]-self.first[:, None], 0, self.width)

    def interval(self, j, k):
        """(most, least) energy the fleet can take between window boundaries j and k, per pair."""
        rows = np.arange(len(self.first))[:, None]
        j, k = self._index(np.atleast_1d(j)), self._index(np.atleast_1d(k))
        most = np.minimum(self.charged[rows, k]-self.charged[rows, j], self.high[rows, k]-self.low[rows, j])
        least = np.maximum(self.discharged[rows, j]-self.discharged[rows, k], self.low[rows, k]-self.high[rows, j])
        return most.sum(0), least.sum(0)

    def envelopes(self):
        """The same fields as the one-way envelope (backend/flex_polytope.envelopes)."""
        boundaries = np.arange(self.count+1)
        step_max, step_min = self.interval(boundaries[:-1], boundaries[1:])
        cumulative_max, cumulative_min = self.interval(np.zeros(self.count, int), boundaries[1:])
        total_max, total_min = self.interval([0], [self.count])
        return {"cumulative_max_kwh": cumulative_max.tolist(), "cumulative_min_kwh": cumulative_min.tolist(),
                "power_max_kw": (step_max/STEP_HOURS).tolist(), "power_min_kw": (step_min/STEP_HOURS).tolist(),
                "total_min_kwh": float(total_min[0]), "total_max_kwh": float(total_max[0])}

    def contains(self, load_kw, tol=1e-6):
        """Necessary check that an aggregate profile is feasible: every step, prefix and suffix."""
        energy = np.asarray(load_kw, float)*STEP_HOURS
        boundaries = np.arange(self.count+1)
        running = np.concatenate([[0.], np.cumsum(energy)])
        checks = [(boundaries[:-1], boundaries[1:]), (np.zeros(self.count, int), boundaries[1:]),
                  (boundaries[:-1], np.full(self.count, self.count))]
        for j, k in checks:
            most, least = self.interval(j, k)
            taken = running[k]-running[j]
            if (taken > most+tol).any() or (taken < least-tol).any():
                return False
        return True
