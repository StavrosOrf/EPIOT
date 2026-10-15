"""One local day's load profile: sessions from any source, scheduled by one engine.

The window is the previous local day plus the target day, as a two-day plot
needs the evening before to show overnight connections. Stored and generated
sessions take exactly the same path from here on, so a strategy means the same
thing for every source.
"""

import datetime
from zoneinfo import ZoneInfo

import numpy as np

from backend.aggregators import simulate_cost_optimal_operation
from backend.carbon_charging import daily_profiles
from backend.cpft import day_window
from backend.flex_polytope import build_polytope, contains, envelopes
from backend.scenario_profiles import grid
from backend.scenario_sampling import point_power

TWO_DAY_STEPS = 288
ENERGY_BUDGET_NOTE = (
    "Each connection charges from its real arrival to its real departure; the window only crops the profile. "
    "Connections crossing the window edge can therefore put different energy inside the window under different strategies.")
FLEXIBILITY_NOTE = "Indicative differences between charging schedules; not a firm flexibility commitment."
CARBON_NOTE = "Minimum-carbon scenario using historical/reference grid information; not demonstrated avoided emissions."


ENSEMBLE_QUANTILES = (10, 50, 90)
ENSEMBLE_NOTE = (
    "The band spans the 10th to 90th percentile of the aggregate load over seeded draws of the same scenario "
    "(sessions, day effects and weather vary with the seed). The line is the draw for the requested seed. "
    "It shows how sensitive the result is to the synthetic sampling, not a calibrated forecast interval.")


class UnsupportedWindow(ValueError):
    """The strategy cannot run on this window (cost optimisation across a clock change)."""


def local_window(target, timezone_name):
    """Start and end instants of the previous and target local days, their 10-minute grid and the target's index."""
    start, target_start = day_window(target-datetime.timedelta(days=1), timezone_name)
    _, end = day_window(target, timezone_name)
    timestamps, past_steps = grid(start, end, target_start)
    return start, end, timestamps, past_steps


def empty_profile(target, timezone_name, source_metadata):
    """An all-zero day, for a selection without charging points."""
    _, _, timestamps, past_steps = local_window(target, timezone_name)
    zeros = [0.]*len(timestamps)
    return dict(x=list(range(len(timestamps))), timestamps=[timestamp.isoformat() for timestamp in timestamps],
                past_steps=past_steps, y=zeros, up_flex=zeros, down_flex=zeros, source=source_metadata)


def ensemble_summary(chargers, draws, seeds, target, method, timezone_name, grid_hours):
    """Percentile band of the load over several session draws under one strategy.

    `draws` yields each draw's sessions (the requested seed's first). Only the
    aggregate load is combined; flexibility envelopes stay those of the first draw.
    """
    start, end, _, _ = local_window(target, timezone_name)
    hours = grid_hours(start, end) if method == "mincarbon" else []
    loads = [daily_profiles(chargers, sessions, start, end, method, timezone_name, hours)[0] for sessions in draws]
    low, middle, high = np.percentile(np.asarray(loads, float), ENSEMBLE_QUANTILES, axis=0)
    return dict(members=len(loads), seeds=list(seeds), quantiles=list(ENSEMBLE_QUANTILES),
                p10=low.tolist(), p50=middle.tolist(), p90=high.tolist(), note=ENSEMBLE_NOTE)


def day_profile(chargers, sessions, metadata, target, method, timezone_name, grid_hours):
    """Load, flexibility and polytope envelopes of `sessions` under one strategy.

    `chargers` are point dictionaries (id, power, ...), `sessions` a SessionFrame
    or ScenarioSession records, and `grid_hours(start, end)` supplies carbon
    data when the strategy is minimum carbon. `metadata` is extended in place.
    """
    start, end, timestamps, past_steps = local_window(target, timezone_name)
    if method == "ocost":
        if len(timestamps) != TWO_DAY_STEPS:
            raise UnsupportedWindow(
                "Cost optimisation currently supports two 24-hour days. Choose another strategy for a daylight-saving transition.")
        zone = ZoneInfo(timezone_name)
        rows = [(session.cp_id, session.start.astimezone(zone).replace(tzinfo=None),
                 session.end.astimezone(zone).replace(tzinfo=None), session.energy_kwh)
                for session in (sessions.records() if hasattr(sessions, "records") else sessions)]
        load_profile, up_flex, down_flex = simulate_cost_optimal_operation(
            {int(charger["id"]): point_power(charger) for charger in chargers}, rows,
            start_date=str(target-datetime.timedelta(days=1)))
    else:
        hours = grid_hours(start, end) if method == "mincarbon" else []
        load_profile, up_flex, down_flex = daily_profiles(chargers, sessions, start, end, method, timezone_name, hours)
        metadata["energy_budget_note"] = ENERGY_BUDGET_NOTE
        if method == "mincarbon":
            metadata["grid_uses_historical_reference"] = any(hour.carbon_is_stale for hour in hours)
            metadata["scheduling_note"] = CARBON_NOTE
    metadata["flexibility_note"] = FLEXIBILITY_NOTE
    polytope = build_polytope(chargers, sessions, start, end)
    flex_polytope = envelopes(polytope)
    flex_polytope["schedule_feasible"] = contains(polytope, load_profile)
    return dict(x=list(range(len(timestamps))), timestamps=[timestamp.isoformat() for timestamp in timestamps],
                past_steps=past_steps, y=list(load_profile), up_flex=list(up_flex), down_flex=list(down_flex),
                flex_polytope=flex_polytope, source=metadata)
