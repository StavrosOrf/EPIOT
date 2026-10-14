"""Energy-conserving scenario profiles on actual UTC intervals, including DST."""

from datetime import timedelta

import numpy as np

from backend.scenario_sampling import point_power
from backend.carbon_charging import balanced_sessions, minimum_carbon_profile
from backend.session_frame import as_frame, bin_integrals, epoch

STEP = 600


def grid(start, end, target_start):
    steps = int((end-start).total_seconds()/STEP)
    timestamps = [start+timedelta(seconds=STEP*i) for i in range(steps)]
    return timestamps, int((target_start-start).total_seconds()/STEP)


class PointTable(list):
    """The selected points, with their sorted IDs and rated powers computed once.

    Still a list of point dictionaries, so it can be passed wherever one is
    expected; per-day and per-strategy calls then reuse the arrays.
    """
    def __init__(self, chargers):
        super().__init__(chargers)
        ids = np.array([int(charger["id"]) for charger in self], np.int64)
        powers = np.array([point_power(charger) for charger in self], float)
        order = np.argsort(ids)
        self.ids, self.powers = ids[order], powers[order]


def point_table(chargers):
    return chargers if isinstance(chargers, PointTable) else PointTable(chargers)


def point_powers(chargers, cp_ids):
    """Rated power for each session's point; NaN marks points outside the selection."""
    table = point_table(chargers)
    ids, powers = table.ids, table.powers
    position = np.minimum(np.searchsorted(ids, cp_ids), max(len(ids)-1, 0))
    found = (ids[position] == cp_ids) if len(ids) else np.zeros(len(cp_ids), bool)
    return np.where(found, powers[position] if len(ids) else np.nan, np.nan)


def simulate_scenarios(chargers, sessions, start, end, strategy, *, carbon_intensity=None):
    """Integrate fractional interval overlap rather than rounding session energy.

    AFAP, ALAP and average power follow each connection from its true arrival
    to its true departure, and the window only crops the result: a car that
    arrived at 21:00 is charged from 21:00, not again from the window's midnight.
    """
    if strategy not in ("afap", "alap", "avg", "mincarbon"):
        raise ValueError("Unsupported local charging strategy")
    count = int((end-start).total_seconds()/STEP)
    left, right = epoch(start), epoch(end)
    frame = as_frame(sessions)
    chargers = point_table(chargers)
    power = point_powers(chargers, frame.cp_id)
    valid = ~np.isnan(power) & (frame.end > left) & (frame.start < right)
    frame, power = frame.select(valid), power[valid]
    duration = frame.end-frame.start
    energy = np.minimum(frame.energy_kwh, power*duration/3600)
    charge_seconds = energy/power*3600
    relative_start, relative_end = frame.start-left, frame.end-left
    early = bin_integrals(relative_start, relative_start+charge_seconds, power, count, STEP)
    late = bin_integrals(relative_end-charge_seconds, relative_end, power, count, STEP)
    average = bin_integrals(relative_start, relative_end, energy*3600/duration, count, STEP)
    if strategy == "mincarbon":
        # Cost-ordered, so a clipped connection is only available from the
        # window start, not forced to charge there
        selected = minimum_carbon_profile(chargers, balanced_sessions(chargers, frame, start, end),
                                          start, end, carbon_intensity)
    else:
        selected = {"afap": early, "alap": late, "avg": average}[strategy]
    # Dispatch envelopes relative to the chosen schedule, not firm flexibility.
    return selected.tolist(), np.maximum(early-selected, 0).tolist(), np.minimum(late-selected, 0).tolist()
