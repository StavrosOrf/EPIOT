"""Inclusive local-day KPIs from stored sessions or on-the-fly scenarios."""

from collections import defaultdict
from datetime import timedelta

import numpy as np
import pandas as pd

from backend.cpft import day_window
from backend.scenario_profiles import STEP, point_powers, point_table
from backend.session_frame import as_frame, bin_integrals
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


def local_hours(timestamps, zone, half_hours=False):
    local = pd.to_datetime(np.asarray(timestamps, float), unit="s", utc=True).tz_convert(zone)
    hours = local.hour.to_numpy()
    return hours*2+local.minute.to_numpy()//30 if half_hours else hours


def union_intervals(points, start, end, span):
    """Merge each point's overlapping records in [0, span], so occupancy counts them once."""
    if not len(points):
        return points, start, end
    order = np.lexsort((start, points))
    points, start, end = points[order], start[order], end[order]
    # Offsetting each point beyond the window keeps the running maximum per point
    offset = points*(span+1.)
    reach = np.maximum.accumulate(end+offset)-offset
    opens = np.ones(len(points), bool)
    opens[1:] = (points[1:] != points[:-1]) | (start[1:] > reach[:-1])
    first = np.flatnonzero(opens)
    return points[first], start[first], np.maximum.reduceat(end, first)


def environment_fields(environment):
    output = {"environment": environment}
    for strategy, label in [("afap", "uncontrolled"), ("alap", "delayed"), ("avg", "avg"), ("mincarbon", "mincarbon")]:
        metrics = environment["strategies"][strategy]
        output[f"co2_intensities_{label}"] = metrics["intensity_by_hour"]
        output[f"renewable_energy_shared_{label}"] = metrics["renewable_share_pct"]
    return output


def calculate_environment_kpis(chargers, daily_sessions, timezone_name, power_mix):
    """Environmental-only request: do not repeat behavioural/occupancy aggregation."""
    chargers = point_table(chargers)
    comparison = EnvironmentalComparison(power_mix, timezone_name)
    for day, records in daily_sessions:
        left, right = day_window(day, timezone_name)
        comparison.add_day(chargers, records, left, right)
    return environment_fields(comparison.result())


def calculate_kpis(chargers, daily_sessions, start_date, end_date, timezone_name, power_mix=(), *, include_environment=True):
    """Each daily input holds that local day's sessions; extra sessions are ignored.

    Daily windows are disjoint: a scenario's previous-day history is never
    counted again. Full connection durations are retained; occupancy and
    scheduled energy are restricted to the inclusive selected date range.
    """
    chargers = point_table(chargers)
    ids = chargers.ids
    points = len(ids)
    distributions = {kind: {field: [] for field in ("arrival", "departure", "duration", "consumption", "daily")}
                     for kind in ("wd", "we")}
    arrival_energy = {kind: np.zeros(24) for kind in distributions}
    arrival_count = {kind: np.zeros(24) for kind in distributions}
    sessions_by_weekday = defaultdict(list)
    available = {kind: np.zeros(48) for kind in distributions}
    exposure = {kind: np.zeros(48) for kind in distributions}
    occupied_by_point = np.zeros(points)
    profiles_energy = dict(afap=0., alap=0., avg=0.)
    environmental = EnvironmentalComparison(power_mix, timezone_name) if include_environment else None
    basic_energy = 0.
    session_count, duration_total, session_energy_total = 0, 0., 0.
    range_seconds = 0.
    daily_totals = []
    for day, records in daily_sessions:
        left_time, right_time = day_window(day, timezone_name)
        left, right = left_time.timestamp(), right_time.timestamp()
        kind = "we" if day.weekday() >= 5 else "wd"
        count = int((right-left)/STEP)
        span = count*STEP
        frame = as_frame(records)
        power = point_powers(chargers, frame.cp_id)
        keep = ~np.isnan(power) & (frame.start < right) & (frame.end > left)
        frame, power = frame.select(keep), power[keep]
        point = np.searchsorted(ids, frame.cp_id)
        relative_start, relative_end = frame.start-left, frame.end-left
        seconds = frame.end-frame.start
        energy = np.minimum(frame.energy_kwh, power*seconds/3600)
        inside = np.maximum(0., np.minimum(relative_end, span)-np.maximum(relative_start, 0.))
        daily_energy = np.bincount(point, energy*inside/seconds, points)
        arrived = (frame.start >= left) & (frame.start < right)
        hours = local_hours(frame.start[arrived], timezone_name)
        distributions[kind]["arrival"].extend(hours.tolist())
        distributions[kind]["duration"].extend((seconds[arrived]/3600).tolist())
        distributions[kind]["consumption"].extend(energy[arrived].tolist())
        arrival_energy[kind] += np.bincount(hours, energy[arrived], 24)
        arrival_count[kind] += np.bincount(hours, minlength=24)
        day_counts = np.bincount(point[arrived], minlength=points)
        session_count += int(arrived.sum())
        duration_total += float(seconds[arrived].sum()/3600)
        session_energy_total += float(energy[arrived].sum())
        # Same arrival-cohort average-energy total, without scheduling strategies.
        basic_energy += float((energy*np.maximum(0., np.minimum(relative_end, span)-relative_start)/seconds)[arrived].sum())
        departed = (frame.end >= left) & (frame.end < right)
        distributions[kind]["departure"].extend(local_hours(frame.end[departed], timezone_name).tolist())
        # Local half-hour bins average actual elapsed time, including repeated
        # or absent DST hours, and include selected points with no sessions.
        merged_point, merged_start, merged_end = union_intervals(
            point, np.clip(relative_start, 0, span), np.clip(relative_end, 0, span), span)
        busy = bin_integrals(merged_start, merged_end, float(STEP), count, STEP)
        occupied_by_point += np.bincount(merged_point, merged_end-merged_start, points)
        slots = local_hours(left+np.arange(count)*STEP, timezone_name, half_hours=True)
        available[kind] += np.bincount(slots, points*STEP-busy, 48)
        exposure[kind] += np.bincount(slots, np.full(count, float(points*STEP)), 48)
        distributions[kind]["daily"].extend(daily_energy.tolist())
        sessions_by_weekday[day.weekday()].extend(day_counts.tolist())
        daily_totals.append(dict(date=str(day), session_count=int(day_counts.sum()), energy_kwh=float(daily_energy.sum())))
        range_seconds += right-left
        # Each day's arrivals up to midnight, so a range equals the sum of its days
        if environmental is not None:
            day_scheduled_energy = environmental.add_day(chargers, frame, left_time, right_time)
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
    ratios = (occupied_by_point/range_seconds if range_seconds else np.zeros(points)).tolist()
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
