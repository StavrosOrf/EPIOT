"""Equal-energy charging schedules with exact connection and power limits."""

import numpy as np

from backend.scenario_sampling import ScenarioSession, point_power


class CarbonScheduleUnavailable(ValueError):
    pass


def balanced_sessions(chargers, sessions, start, end):
    """Clip connections to the window with their uniform-charging energy share.

    Only for schedules that pick *where* to put energy (minimum carbon), never
    for AFAP/ALAP: a clipped start would look like an arrival at the window
    edge and pile charging up at midnight. It is a scenario assumption.
    """
    powers = {int(charger["id"]): point_power(charger) for charger in chargers}
    result = []
    for record in sessions:
        left, right = max(record.start, start), min(record.end, end)
        if left >= right or record.cp_id not in powers:
            continue
        duration = (record.end-record.start).total_seconds()
        energy = min(record.energy_kwh, powers[record.cp_id]*duration/3600)
        result.append(ScenarioSession(record.cp_id, left, right, energy*(right-left).total_seconds()/duration))
    return sorted(result, key=lambda record: (record.cp_id, record.start, record.end))


def arrival_cohort(chargers, sessions, start, end, horizon=None):
    """Connections arriving in [start, end), for equal-energy comparisons.

    Every strategy charges the same energy from the true arrival time, and a
    connection is followed past `end` up to `horizon` (default `end`). One still
    running at `horizon` keeps its uniform-charging share up to it. Connections
    that arrived earlier belong to the previous window, so nothing appears to
    arrive at the window start (e.g. midnight).
    """
    horizon = max(end, horizon or end)
    powers = {int(charger["id"]): point_power(charger) for charger in chargers}
    result = []
    for record in sessions:
        if not start <= record.start < end or record.cp_id not in powers:
            continue
        right = min(record.end, horizon)
        duration = (record.end-record.start).total_seconds()
        energy = min(record.energy_kwh, powers[record.cp_id]*duration/3600)
        result.append(ScenarioSession(record.cp_id, record.start, right,
                                      energy*(right-record.start).total_seconds()/duration))
    return sorted(result, key=lambda record: (record.cp_id, record.start, record.end))


def minimum_carbon_profile(chargers, sessions, start, end, carbon_intensity):
    """Independent non-overlapping plugs: fill cheapest feasible interval first.

    The linear objective is sum(kWh * gCO2e/kWh). Continuous charging is allowed
    to pause, each interval respects plug power, and each session gets its fixed
    energy. No network-capacity model or actual avoided-emissions claim is made.
    Every candidate charging interval needs a known carbon value.
    """
    count = int((end-start).total_seconds()/600)
    costs = np.asarray(carbon_intensity, dtype=float)
    if costs.shape != (count,):
        raise CarbonScheduleUnavailable("Carbon data do not match the charging time grid")
    powers = {int(charger["id"]): point_power(charger) for charger in chargers}
    offsets, profile = np.arange(count)*600., np.zeros(count)
    last_end = {}
    for record in sorted(sessions, key=lambda record: (record.cp_id, record.start)):
        if record.start < last_end.get(record.cp_id, record.start):
            raise CarbonScheduleUnavailable("Overlapping connections prevent a feasible single-plug carbon comparison")
        last_end[record.cp_id] = record.end
        if record.energy_kwh <= 1e-12:
            continue
        relative_start = (record.start-start).total_seconds()
        relative_end = (record.end-start).total_seconds()
        capacity = powers[record.cp_id]*np.maximum(0., np.minimum(offsets+600, relative_end)-np.maximum(offsets, relative_start))/3600
        candidates = np.flatnonzero(capacity > 1e-12)
        if not np.isfinite(costs[candidates]).all() or (costs[candidates] < 0).any():
            raise CarbonScheduleUnavailable("Minimum-carbon charging needs carbon data for every feasible connection interval")
        if capacity.sum()+1e-8 < record.energy_kwh:
            raise CarbonScheduleUnavailable("The connection window cannot deliver the required charging energy")
        order = candidates[np.lexsort((candidates, costs[candidates]))]
        remaining = record.energy_kwh
        for index in order:
            energy = min(remaining, capacity[index])
            profile[index] += energy*6
            remaining -= energy
            if remaining <= 1e-10:
                break
    return profile


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
