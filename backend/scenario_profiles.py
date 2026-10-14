"""Energy-conserving scenario profiles on actual UTC intervals, including DST."""

from datetime import timedelta

import numpy as np

from backend.scenario_sampling import point_power


def grid(start, end, target_start):
    steps = int((end-start).total_seconds()/600)
    timestamps = [start+timedelta(minutes=10*i) for i in range(steps)]
    return timestamps, int((target_start-start).total_seconds()/600)


def simulate_scenarios(chargers, sessions, start, end, strategy):
    """Integrate fractional interval overlap rather than rounding session energy."""
    if strategy not in ("afap", "alap", "avg"):
        raise ValueError("Unsupported local charging strategy")
    timestamps, _ = grid(start, end, start)
    count = len(timestamps)
    starts = np.arange(count)*600.
    power_by_id = {int(charger["id"]): point_power(charger) for charger in chargers}
    early, late, average = np.zeros(count), np.zeros(count), np.zeros(count)
    for session in sessions:
        power = power_by_id[session.cp_id]
        duration = (session.end-session.start).total_seconds()
        energy = min(session.energy_kwh, power*duration/3600)
        charge_seconds = energy/power*3600
        relative_start = (session.start-start).total_seconds()
        relative_end = (session.end-start).total_seconds()
        for output, left, right, rate in [
            (early, relative_start, relative_start+charge_seconds, power),
            (late, relative_end-charge_seconds, relative_end, power),
            (average, relative_start, relative_end, energy*3600/duration)]:
            overlap = np.maximum(0, np.minimum(starts+600, right)-np.maximum(starts, left))
            output += rate*overlap/600
    selected = {"afap": early, "alap": late, "avg": average}[strategy]
    # Dispatch envelopes relative to the chosen schedule, not firm flexibility.
    return selected.tolist(), np.maximum(early-selected, 0).tolist(), np.minimum(late-selected, 0).tolist()
