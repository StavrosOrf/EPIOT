"""Inclusive local-day KPIs from stored sessions or on-the-fly scenarios."""

from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from backend.cpft import day_window
from backend.scenario_profiles import STEP, point_powers, point_table
from backend.session_frame import as_frame, bin_integrals
from backend.kpi.environment import EnvironmentalComparison

# P(all chargers busy) needs a per-charger occupancy grid; with more points than
# this it is vanishingly small and the grid would only cost memory
BLOCKING_MAX_POINTS = 2000
# Per-charger detail is only drawn for a handful of points
CHARGER_DETAIL_MAX_POINTS = 200
# Load-duration curve sampled at exceedance 0, 5, ..., 100 %
LOAD_DURATION_POINTS = 21


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


def overflow(values, upper):
    """How many values the last bin of `histogram` absorbed beyond its upper edge."""
    return int((np.asarray(values, float) >= upper).sum())


def quantile(values, percent):
    return float(np.percentile(values, percent)) if len(values) else None


def local_hours(timestamps, zone, half_hours=False):
    local = pd.to_datetime(np.asarray(timestamps, float), unit="s", utc=True).tz_convert(zone)
    hours = local.hour.to_numpy()
    return hours*2+local.minute.to_numpy()//30 if half_hours else hours


def clock_hours(timestamps, zone):
    """Local time of day as fractional hours."""
    local = pd.to_datetime(np.asarray(timestamps, float), unit="s", utc=True).tz_convert(zone)
    return local.hour.to_numpy()+local.minute.to_numpy()/60+local.second.to_numpy()/3600


def mean_clock_hour(hours):
    """Circular mean, so 23:30 and 00:30 average to midnight rather than noon."""
    if not len(hours):
        return None
    angle = np.asarray(hours, float)*(2*np.pi/24)
    sine, cosine = np.sin(angle).mean(), np.cos(angle).mean()
    if np.hypot(sine, cosine) < 1e-9:
        return None
    return float(np.arctan2(sine, cosine) % (2*np.pi)*24/(2*np.pi))


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


def idle_gaps(points, start, end):
    """Hours from a charger's connection ending to its next one starting.

    Back-to-back connections give 0; overlapping ones are not gaps. Gaps are
    only seen inside the range, so very long idle spells are truncated.
    """
    if len(points) < 2:
        return np.zeros(0)
    order = np.lexsort((start, points))
    points, start, end = points[order], start[order], end[order]
    origin = start.min()
    start, end = start-origin, end-origin
    offset = points*(end.max()+1.)
    reach = np.maximum.accumulate(end+offset)-offset
    gap = start[1:]-reach[:-1]
    return gap[(points[1:] == points[:-1]) & (gap >= 0)]/3600


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
    fields = ("arrival", "departure", "duration", "consumption", "daily", "slack")
    distributions = {kind: {field: [] for field in fields} for kind in ("wd", "we")}
    arrival_energy = {kind: np.zeros(24) for kind in distributions}
    arrival_count = {kind: np.zeros(24) for kind in distributions}
    sessions_by_weekday = defaultdict(list)
    available = {kind: np.zeros(48) for kind in distributions}
    exposure = {kind: np.zeros(48) for kind in distributions}
    blocked = {kind: np.zeros(48) for kind in distributions}
    load_sum = {kind: np.zeros(48) for kind in distributions}
    load_steps = {kind: np.zeros(48) for kind in distributions}
    idle_days = dict.fromkeys(distributions, 0)
    occupied_by_point = np.zeros(points)
    energy_by_point = np.zeros(points)
    sessions_by_point = np.zeros(points)
    profiles_energy = dict(afap=0., alap=0., avg=0.)
    environmental = EnvironmentalComparison(power_mix, timezone_name) if include_environment else None
    basic_energy = 0.
    session_count, duration_total, session_energy_total = 0, 0., 0.
    range_seconds = 0.
    daily_totals, daily_loads, arrival_clock = [], [], []
    gap_points, gap_starts, gap_ends = [], [], []
    peak_kw, peak_at = 0., None
    track_blocking = 0 < points <= BLOCKING_MAX_POINTS
    zone = ZoneInfo(timezone_name)
    for day, records in daily_sessions:
        left_time, right_time = day_window(day, timezone_name)
        left, right = left_time.timestamp(), right_time.timestamp()
        kind = "we" if day.weekday() >= 5 else "wd"
        count = int((right-left)/STEP)
        span = count*STEP
        frame = as_frame(records)
        power = point_powers(chargers, frame.cp_id)
        listed = ~np.isnan(power)
        # A connection ending exactly at this day's start departs today, but has
        # no overlap with it, so the overlap filter below must not decide departures
        departures = frame.end[listed & (frame.end >= left) & (frame.end < right)]
        keep = listed & (frame.start < right) & (frame.end > left)
        frame, power = frame.select(keep), power[keep]
        point = np.searchsorted(ids, frame.cp_id)
        relative_start, relative_end = frame.start-left, frame.end-left
        seconds = frame.end-frame.start
        energy = np.minimum(frame.energy_kwh, power*seconds/3600)
        # Hours at rated power; what remains of the stay is idle, schedulable time
        charge_seconds = np.divide(energy*3600, power, out=np.zeros(len(power)), where=power > 0)
        inside = np.maximum(0., np.minimum(relative_end, span)-np.maximum(relative_start, 0.))
        daily_energy = np.bincount(point, energy*inside/seconds, points)
        arrived = (frame.start >= left) & (frame.start < right)
        hours = local_hours(frame.start[arrived], timezone_name)
        distributions[kind]["arrival"].extend(hours.tolist())
        distributions[kind]["duration"].extend((seconds[arrived]/3600).tolist())
        distributions[kind]["slack"].extend((np.maximum(0., seconds-charge_seconds)[arrived]/3600).tolist())
        distributions[kind]["consumption"].extend(energy[arrived].tolist())
        arrival_clock.append(clock_hours(frame.start[arrived], timezone_name))
        arrival_energy[kind] += np.bincount(hours, energy[arrived], 24)
        arrival_count[kind] += np.bincount(hours, minlength=24)
        day_counts = np.bincount(point[arrived], minlength=points)
        session_count += int(arrived.sum())
        duration_total += float(seconds[arrived].sum()/3600)
        session_energy_total += float(energy[arrived].sum())
        gap_points.append(point[arrived])
        gap_starts.append(frame.start[arrived])
        gap_ends.append(frame.end[arrived])
        # Same arrival-cohort average-energy total, without scheduling strategies.
        basic_energy += float((energy*np.maximum(0., np.minimum(relative_end, span)-relative_start)/seconds)[arrived].sum())
        distributions[kind]["departure"].extend(local_hours(departures, timezone_name).tolist())
        # Local half-hour bins average actual elapsed time, including repeated
        # or absent DST hours, and include selected points with no sessions.
        merged_point, merged_start, merged_end = union_intervals(
            point, np.clip(relative_start, 0, span), np.clip(relative_end, 0, span), span)
        slots = local_hours(left+np.arange(count)*STEP, timezone_name, half_hours=True)
        if track_blocking:
            # Busy share of each point in each step, so "every point busy" is known too
            busy_share = bin_integrals(merged_start, merged_end, 1., count, STEP,
                                       rows=merged_point, row_count=points).reshape(points, count).sum(axis=0)
            busy = busy_share*STEP
            blocked[kind] += np.bincount(slots, np.maximum(0., busy_share-(points-1))*STEP, 48)
        else:
            busy = bin_integrals(merged_start, merged_end, float(STEP), count, STEP)
        occupied_by_point += np.bincount(merged_point, merged_end-merged_start, points)
        available[kind] += np.bincount(slots, points*STEP-busy, 48)
        exposure[kind] += np.bincount(slots, np.full(count, float(points*STEP)), 48)
        # Uncontrolled (as fast as possible) load of every connection, from true arrival
        load = bin_integrals(relative_start, relative_start+charge_seconds, power, count, STEP)
        load_sum[kind] += np.bincount(slots, load, 48)
        load_steps[kind] += np.bincount(slots, minlength=48)
        daily_loads.append(load)
        if count and load.max() > peak_kw:
            peak_kw = float(load.max())
            peak_at = datetime.fromtimestamp(left+int(load.argmax())*STEP, zone)
        distributions[kind]["daily"].extend(daily_energy.tolist())
        idle_days[kind] += int((daily_energy <= 0).sum())
        energy_by_point += daily_energy
        sessions_by_point += day_counts
        sessions_by_weekday[day.weekday()].extend(day_counts.tolist())
        daily_totals.append(dict(date=str(day), session_count=int(day_counts.sum()), energy_kwh=float(daily_energy.sum())))
        range_seconds += right-left
        # Each day's arrivals up to midnight, so a range equals the sum of its days
        if environmental is not None:
            day_scheduled_energy = environmental.add_day(chargers, frame, left_time, right_time)
            for strategy in profiles_energy:
                profiles_energy[strategy] += day_scheduled_energy[strategy]
    output = {}
    limits = {}
    for kind, values in distributions.items():
        for field, bins, upper, name in [("arrival", 24, 24, "arrival"), ("departure", 24, 24, "departure"),
                                       ("duration", 24, 24, "duration"), ("slack", 24, 24, "slack"),
                                       ("consumption", 10, 100, "consumption"),
                                       ("daily", 10, 200, "daily_consumption")]:
            output[f"{name}_dist_{kind}"] = histogram(values[field], bins, upper)
            if name in ("duration", "slack", "consumption", "daily_consumption"):
                limits.setdefault(name, {})[kind] = overflow(values[field], upper)
        output[f"hour_of_arrival_consumption_{kind}"] = [
            float(total/n) if n else None for total, n in zip(arrival_energy[kind], arrival_count[kind])]
        output[f"idle_charger_days_{kind}"] = idle_days[kind]
        output["weekday_availability" if kind == "wd" else "weekend_availability"] = [
            float(free/observed) if observed else None for free, observed in zip(available[kind], exposure[kind])]
        output["weekday_blocking" if kind == "wd" else "weekend_blocking"] = [
            float(full/(observed/points)) if observed and track_blocking else None
            for full, observed in zip(blocked[kind], exposure[kind])]
        output["load_profile_"+kind] = [float(total/n) if n else None
                                        for total, n in zip(load_sum[kind], load_steps[kind])]
    output["overflow"] = limits
    for weekday in range(7):
        output[f"sessions_per_day_{weekday}"] = histogram(sessions_by_weekday[weekday], 6, 6, True)
    per_day = [np.asarray(sessions_by_weekday[weekday], float) for weekday in range(7)]
    output["sessions_per_day_mean"] = [float(counts.mean()) if len(counts) else None for counts in per_day]
    output["sessions_per_day_p90"] = [quantile(counts, 90) for counts in per_day]
    output["sessions_per_day_observations"] = [len(counts) for counts in per_day]
    ratios = (occupied_by_point/range_seconds if range_seconds else np.zeros(points)).tolist()
    output["occupation_ratio_dist"] = histogram(ratios, 20, 1, True)
    hours_available = chargers.powers*range_seconds/3600
    utilisation = np.divide(energy_by_point, hours_available, out=np.zeros(points), where=hours_available > 0)
    if points <= CHARGER_DETAIL_MAX_POINTS:
        output["charger_usage"] = dict(id=ids.tolist(), occupancy=ratios, utilisation=utilisation.tolist(),
                                       sessions=sessions_by_point.astype(int).tolist(), energy_kwh=energy_by_point.tolist())
    loads = np.concatenate(daily_loads) if daily_loads else np.zeros(0)
    output["load_duration_kw"] = (np.percentile(loads, np.linspace(100, 0, LOAD_DURATION_POINTS)).tolist()
                                  if len(loads) else None)
    if environmental is not None:
        output.update(environment_fields(environmental.result()))
    output["range"] = dict(start_date=str(start_date), end_date=str(end_date), inclusive=True,
                          day_count=(end_date-start_date).days+1, timezone=timezone_name, elapsed_hours=range_seconds/3600)
    durations = np.concatenate([np.asarray(values["duration"], float) for values in distributions.values()])
    slack = np.concatenate([np.asarray(values["slack"], float) for values in distributions.values()])
    gap_hours = idle_gaps(np.concatenate(gap_points) if gap_points else np.zeros(0, np.int64),
                          np.concatenate(gap_starts) if gap_starts else np.zeros(0),
                          np.concatenate(gap_ends) if gap_ends else np.zeros(0))
    charger_days = points*output["range"]["day_count"]
    used_days = charger_days-sum(idle_days.values())
    rated_power = float(chargers.powers.sum()) if points else 0.
    mean_load = float(loads.mean()) if len(loads) else 0.
    all_blocking = [value for key in ("weekday_blocking", "weekend_blocking") for value in output[key] if value is not None]
    output["summary"] = dict(point_count=points, session_count=session_count,
        session_energy_kwh=session_energy_total, energy_kwh=profiles_energy["avg"] if include_environment else basic_energy,
        mean_duration_hours=duration_total/session_count if session_count else 0.,
        mean_occupancy_ratio=float(np.mean(ratios)) if ratios else 0., daily=daily_totals,
        median_duration_hours=quantile(durations, 50), p90_duration_hours=quantile(durations, 90),
        mean_arrival_hour=mean_clock_hour(np.concatenate(arrival_clock) if arrival_clock else []),
        mean_slack_hours=float(slack.mean()) if len(slack) else None,
        # Share of connected time not needed to deliver the energy at rated power
        slack_share=float(slack.sum()/durations.sum()) if durations.sum() > 0 else None,
        peak_kw=peak_kw, peak_time=peak_at.isoformat() if peak_at is not None and peak_kw > 0 else None,
        mean_load_kw=mean_load, rated_power_kw=rated_power,
        load_factor=mean_load/peak_kw if peak_kw > 0 else None,
        coincidence_factor=peak_kw/rated_power if rated_power > 0 and peak_kw > 0 else None,
        idle_charger_day_share=sum(idle_days.values())/charger_days if charger_days else None,
        sessions_per_used_charger_day=session_count/used_days if used_days > 0 else None,
        median_idle_gap_hours=quantile(gap_hours, 50), idle_gap_count=len(gap_hours),
        mean_utilisation=float(utilisation.mean()) if points else None,
        max_blocking_probability=max(all_blocking) if all_blocking else None)
    if include_environment:
        output["summary"]["scheduled_energy_kwh"] = profiles_energy
    return output
