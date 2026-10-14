"""Inclusive local-day KPIs from stored sessions or cached daily scenarios."""

from collections import defaultdict
from datetime import timedelta
from zoneinfo import ZoneInfo

import numpy as np

from backend.cpft import day_window
from backend.scenario_profiles import grid
from backend.scenario_sampling import point_power
from backend.kpi.environment import EnvironmentalComparison


def days_between(start, end):
    for offset in range((end-start).days+1):
        yield start+timedelta(days=offset)


def histogram(values, bins, upper, probability=False):
    # Include overflow in the last displayed bin rather than silently dropping it.
    values = np.clip(values, 0, np.nextafter(float(upper), 0))
    counts = np.histogram(values, bins=bins, range=(0, upper))[0].astype(float)
    if probability and counts.sum():
        counts /= counts.sum()
    return counts.tolist()


def union_seconds(intervals, left, right):
    """Count overlapping stored records once when measuring point occupancy."""
    total, last = 0., left
    for start, end in sorted(intervals):
        start, end = max(left, start, last), min(right, end)
        if end > start:
            total += end-start
            last = end
    return total


def environment_fields(environment):
    output = {"environment": environment}
    for strategy, label in [("afap", "uncontrolled"), ("alap", "delayed"), ("avg", "avg"), ("mincarbon", "mincarbon")]:
        metrics = environment["strategies"][strategy]
        output[f"co2_intensities_{label}"] = metrics["intensity_by_hour"]
        output[f"renewable_energy_shared_{label}"] = metrics["renewable_share_pct"]
    return output


def calculate_environment_kpis(chargers, daily_sessions, timezone_name, power_mix):
    """Environmental-only request: do not repeat behavioural/occupancy aggregation."""
    comparison = EnvironmentalComparison(power_mix, timezone_name)
    for day, records in daily_sessions:
        left, right = day_window(day, timezone_name)
        comparison.add_day(chargers, records, left, right)
    return environment_fields(comparison.result())


def calculate_kpis(chargers, daily_sessions, start_date, end_date, timezone_name, power_mix=(), *, include_environment=True):
    """Each daily input is the same target-day scenario used by load profiles.

    Daily windows are disjoint: never count a scenario's previous-day history as
    another forecast. Full connection durations are retained; occupancy and
    scheduled energy are restricted to the inclusive selected date range.
    """
    zone = ZoneInfo(timezone_name)
    ids = [int(charger["id"]) for charger in chargers]
    points = len(ids)
    power = {int(charger["id"]): point_power(charger) for charger in chargers}
    distributions = {kind: {field: [] for field in ("arrival", "departure", "duration", "consumption", "daily")}
                     for kind in ("wd", "we")}
    arrival_energy = {kind: np.zeros(24) for kind in distributions}
    arrival_count = {kind: np.zeros(24) for kind in distributions}
    sessions_by_weekday = defaultdict(list)
    available = {kind: np.zeros(48) for kind in distributions}
    exposure = {kind: np.zeros(48) for kind in distributions}
    occupied_by_point = defaultdict(float)
    profiles_energy = dict(afap=0., alap=0., avg=0.)
    environmental = EnvironmentalComparison(power_mix, timezone_name) if include_environment else None
    basic_energy = 0.
    session_count, duration_total, session_energy_total = 0, 0., 0.
    range_seconds = 0.
    daily_totals = []
    for day, records in daily_sessions:
        left, right = day_window(day, timezone_name)
        kind = "we" if day.weekday() >= 5 else "wd"
        timeline, _ = grid(left, right, left)
        offsets = np.arange(len(timeline))*600.
        local_slots = np.array([timestamp.astimezone(zone).hour*2+timestamp.astimezone(zone).minute//30 for timestamp in timeline])
        intervals = defaultdict(list)
        day_counts = dict.fromkeys(ids, 0)
        daily_energy = dict.fromkeys(ids, 0.)
        for record in records:
            if record.cp_id not in power or record.start >= right or record.end <= left:
                continue
            relative_start = (record.start-left).total_seconds()
            relative_end = (record.end-left).total_seconds()
            intervals[record.cp_id].append((relative_start, relative_end))
            seconds = (record.end-record.start).total_seconds()
            energy = min(record.energy_kwh, power[record.cp_id]*seconds/3600)
            daily_energy[record.cp_id] += energy*max(0., min(relative_end, len(timeline)*600)-max(relative_start, 0.))/seconds
            if left <= record.start < right:
                arrival = record.start.astimezone(zone).hour
                distributions[kind]["arrival"].append(arrival)
                distributions[kind]["duration"].append(seconds/3600)
                distributions[kind]["consumption"].append(energy)
                arrival_energy[kind][arrival] += energy
                arrival_count[kind][arrival] += 1
                day_counts[record.cp_id] += 1
                session_count += 1
                duration_total += seconds/3600
                session_energy_total += energy
                # Same arrival-cohort average-energy total, without scheduling strategies.
                basic_energy += energy*max(0., min(relative_end, len(timeline)*600)-relative_start)/seconds
            if left <= record.end < right:
                distributions[kind]["departure"].append(record.end.astimezone(zone).hour)
        # Local half-hour bins average actual elapsed time, including repeated
        # or absent DST hours, and include selected points with no sessions.
        busy = np.zeros(len(timeline))
        for cp_id, spans in intervals.items():
            occupied = np.array([union_seconds(spans, offset, offset+600) for offset in offsets])
            busy += occupied
            occupied_by_point[cp_id] += occupied.sum()
        for slot, occupied in zip(local_slots, busy):
            available[kind][slot] += points*600-occupied
            exposure[kind][slot] += points*600
        distributions[kind]["daily"].extend(daily_energy.values())
        sessions_by_weekday[day.weekday()].extend(day_counts.values())
        daily_totals.append(dict(date=str(day), session_count=sum(day_counts.values()), energy_kwh=sum(daily_energy.values())))
        range_seconds += (right-left).total_seconds()
        # Each day's arrivals up to midnight, so a range equals the sum of its days
        if environmental is not None:
            day_scheduled_energy = environmental.add_day(chargers, records, left, right)
            for strategy in profiles_energy:
                profiles_energy[strategy] += day_scheduled_energy[strategy]
    output = {}
    for kind, fields in distributions.items():
        for field, bins, upper, name in [("arrival", 24, 24, "arrival"), ("departure", 24, 24, "departure"),
                                       ("duration", 24, 24, "duration"), ("consumption", 10, 100, "consumption"),
                                       ("daily", 10, 200, "daily_consumption")]:
            output[f"{name}_dist_{kind}"] = histogram(fields[field], bins, upper)
        output[f"hour_of_arrival_consumption_{kind}"] = np.divide(arrival_energy[kind], arrival_count[kind],
            out=np.zeros(24), where=arrival_count[kind]>0).tolist()
        output["weekday_availability" if kind == "wd" else "weekend_availability"] = [
            float(free/observed) if observed else None for free, observed in zip(available[kind], exposure[kind])]
    for weekday in range(7):
        output[f"sessions_per_day_{weekday}"] = histogram(sessions_by_weekday[weekday], 6, 6, True)
    ratios = [occupied_by_point[cp_id]/range_seconds if range_seconds else 0 for cp_id in ids]
    output["occupation_ratio_dist"] = histogram(ratios, 20, 1, True)
    if environmental is not None:
        output.update(environment_fields(environmental.result()))
    output["range"] = dict(start_date=str(start_date), end_date=str(end_date), inclusive=True,
                          day_count=(end_date-start_date).days+1, timezone=timezone_name, elapsed_hours=range_seconds/3600)
    output["summary"] = dict(point_count=points, session_count=session_count,
        session_energy_kwh=session_energy_total, energy_kwh=profiles_energy["avg"] if include_environment else basic_energy,
        mean_duration_hours=duration_total/session_count if session_count else 0.,
        mean_occupancy_ratio=float(np.mean(ratios)) if ratios else 0., daily=daily_totals)
    if include_environment:
        output["summary"]["scheduled_energy_kwh"] = profiles_energy
    return output
