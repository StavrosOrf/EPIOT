"""Equal-energy charging schedules with exact connection and power limits."""

import numpy as np

from backend.scenario_sampling import point_power
from backend.session_frame import SessionFrame, as_frame, epoch

STEP = 600


class CarbonScheduleUnavailable(ValueError):
    pass


def frame_powers(chargers, frame):
    from backend.scenario_profiles import point_powers
    return point_powers(chargers, frame.cp_id)


def balanced_sessions(chargers, sessions, start, end):
    """Clip connections to the window with their uniform-charging energy share.

    Only for schedules that pick *where* to put energy (minimum carbon), never
    for AFAP/ALAP: a clipped start would look like an arrival at the window
    edge and pile charging up at midnight. It is a scenario assumption.
    """
    frame = as_frame(sessions)
    left, right = epoch(start), epoch(end)
    power = frame_powers(chargers, frame)
    low, high = np.maximum(frame.start, left), np.minimum(frame.end, right)
    keep = (high > low) & ~np.isnan(power)
    duration = frame.end-frame.start
    energy = np.minimum(frame.energy_kwh, power*duration/3600)*(high-low)/duration
    return SessionFrame(frame.cp_id[keep], low[keep], high[keep], energy[keep]).sorted()


def arrival_cohort(chargers, sessions, start, end, horizon=None):
    """Connections arriving in [start, end), for equal-energy comparisons.

    Every strategy charges the same energy from the true arrival time, and a
    connection is followed past `end` up to `horizon` (default `end`). One still
    running at `horizon` keeps its uniform-charging share up to it. Connections
    that arrived earlier belong to the previous window, so nothing appears to
    arrive at the window start (e.g. midnight).
    """
    frame = as_frame(sessions)
    left, right = epoch(start), epoch(end)
    limit = max(right, epoch(horizon) if horizon is not None else right)
    power = frame_powers(chargers, frame)
    keep = (frame.start >= left) & (frame.start < right) & ~np.isnan(power)
    high = np.minimum(frame.end, limit)
    duration = frame.end-frame.start
    energy = np.minimum(frame.energy_kwh, power*duration/3600)*(high-frame.start)/duration
    return SessionFrame(frame.cp_id[keep], frame.start[keep], high[keep], energy[keep]).sorted()


def minimum_carbon_profile(chargers, sessions, start, end, carbon_intensity):
    """Independent non-overlapping plugs: fill cheapest feasible interval first.

    The linear objective is sum(kWh * gCO2e/kWh). Continuous charging is allowed
    to pause, each interval respects plug power, and each session gets its fixed
    energy. No network-capacity model or actual avoided-emissions claim is made.
    Every candidate charging interval needs a known carbon value.

    All sessions are filled at once: candidate (session, interval) pairs are
    ordered by session, cost and time, and each takes what its session still
    needs after the cheaper intervals before it.
    """
    count = int((end-start).total_seconds()/STEP)
    costs = np.asarray(carbon_intensity, dtype=float)
    if costs.shape != (count,):
        raise CarbonScheduleUnavailable("Carbon data do not match the charging time grid")
    frame = as_frame(sessions).sorted()
    same_point = frame.cp_id[1:] == frame.cp_id[:-1]
    if (frame.start[1:][same_point] < frame.end[:-1][same_point]).any():
        raise CarbonScheduleUnavailable("Overlapping connections prevent a feasible single-plug carbon comparison")
    frame = frame.select(frame.energy_kwh > 1e-12)
    power = frame_powers(chargers, frame)
    left = epoch(start)
    relative_start = np.clip(frame.start-left, 0., count*STEP)
    relative_end = np.clip(frame.end-left, 0., count*STEP)
    first = np.minimum((relative_start//STEP).astype(np.int64), count-1)
    last = np.minimum(np.ceil(relative_end/STEP).astype(np.int64)-1, count-1)
    lengths = np.maximum(last-first+1, 0)
    session = np.repeat(np.arange(len(frame)), lengths)
    interval = np.arange(lengths.sum())+np.repeat(first-(np.cumsum(lengths)-lengths), lengths)
    overlap = np.minimum((interval+1)*STEP, relative_end[session])-np.maximum(interval*STEP, relative_start[session])
    capacity = power[session]*np.maximum(overlap, 0.)/3600
    candidate = capacity > 1e-12
    session, interval, capacity = session[candidate], interval[candidate], capacity[candidate]
    cost = costs[interval]
    if not np.isfinite(cost).all() or (cost < 0).any():
        raise CarbonScheduleUnavailable("Minimum-carbon charging needs carbon data for every feasible connection interval")
    if (np.bincount(session, capacity, len(frame))+1e-8 < frame.energy_kwh).any():
        raise CarbonScheduleUnavailable("The connection window cannot deliver the required charging energy")
    order = np.lexsort((interval, cost, session))
    session, interval, capacity = session[order], interval[order], capacity[order]
    filled = np.cumsum(capacity)
    before = filled-capacity-np.concatenate([[0.], filled])[np.searchsorted(session, session, "left")]
    energy = np.clip(frame.energy_kwh[session]-before, 0., capacity)
    return np.bincount(interval, energy*3600/STEP, count)


def daily_profiles(chargers, sessions, start, end, strategy, timezone_name, grid_hours=()):
    """Load-profile window in one pass, so no connection restarts at midnight.

    Splitting the window per day clipped overnight connections at 00:00, and
    AFAP then charged them again from midnight. `timezone_name` is kept for
    callers; the window is already expressed in local-day bounds.
    """
    from backend.scenario_profiles import grid, simulate_scenarios
    hours = {hour.timestamp: hour.co2_intensity for hour in grid_hours}
    timeline, _ = grid(start, end, start)
    costs = [hours.get(timestamp.replace(minute=0, second=0, microsecond=0)) for timestamp in timeline]
    return simulate_scenarios(chargers, sessions, start, end, strategy, carbon_intensity=costs)
