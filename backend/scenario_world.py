"""On-the-fly synthetic charging worlds: every window is a view of one scenario.

No live charging data arrive, so a scenario is a pure function of the point,
its spatial profile, the bundled priors, the demand assumption and the seed.
Nothing is prepared ahead of time or stored: a request samples only the
sessions overlapping its window, vectorized over all selected points.

Day-level effects. With a calendar (backend/scenario_calendar.py), each local
day and country also gets a season, day-of-week, holiday, common demand-shock
and temperature effect: arrivals are scaled, holidays follow the weekend
arrival curve and energy per session follows the day's temperature. These are
hashed from (country, date, seed) too, so window independence is unchanged.

Window independence. Random numbers are keyed by (point, absolute UTC
quarter-hour) instead of being drawn in sequence, and occupancy blocking runs
in fixed UTC days. Each day's run starts empty three days early (the longest
connection), which almost always reproduces the earlier days exactly, and keeps
only that day's arrivals. An arrival that would still overlap a connection
from one of the three previous days is dropped. Because the days are fixed, a day sampled
alone is identical to the same day inside a month-long KPI range, and changing
the window never changes a session.
"""

from functools import lru_cache

import numpy as np
import pandas as pd
from scipy.special import ndtr, ndtri

from backend.random_streams import mix, stream, text_key, to_unit, uniforms
from backend.scenario_sampling import ASSUMPTION_MULTIPLIERS, arrival_curve, load_priors, point_power
from backend.session_frame import SessionFrame, epoch
from backend.spatial_profiles import ARCHETYPES

WORLD_VERSION = "world-v1"
SLOT = 900
SLOTS_PER_DAY = 96
BLOCK_SLOTS = SLOTS_PER_DAY
WARMUP_SLOTS = 3*SLOTS_PER_DAY
ROW_SLOTS = BLOCK_SLOTS+WARMUP_SLOTS
WARMUP_ROWS = -(-WARMUP_SLOTS//BLOCK_SLOTS)
MAX_HOURS = 72.
# Earlier days whose connections can still be running when a day starts
LOOKBACK_ROWS = -(-int(MAX_HOURS*3600)//(BLOCK_SLOTS*SLOT))
DURATION_SCALE = {"residential": 1.4, "workplace": 1., "retail": .4, "mixed": 1.}
# Gaussian-copula correlation between a session's duration and its energy (assumed)
DURATION_ENERGY_CORRELATION = .4
# Stays at fast (DC) points are this share of the public prior's
FAST_DURATION_SCALE = .6
FALLBACK_PROFILE = {"weights": {"mixed": 1.}, "arrival_multiplier": 1.}
CHUNK_CELLS = 4_000_000

def point_keys(ids, source, seed, version=WORLD_VERSION):
    return np.array([text_key(f"{version}|{int(cp_id)}|{source}|{int(seed)}") for cp_id in ids], np.uint64)


def profile_arrays(profiles, count):
    profiles = profiles if profiles is not None else [None]*count
    weights = np.array([[(profile or FALLBACK_PROFILE)["weights"].get(name, 0.) for name in ARCHETYPES]
                        for profile in profiles], float).reshape(count, len(ARCHETYPES))
    if not (np.isfinite(weights).all() and (weights >= 0).all() and (weights.sum(1) > 0).all()):
        raise ValueError("Invalid spatial mixture weights")
    multipliers = np.array([(profile or FALLBACK_PROFILE).get("arrival_multiplier", 1.) for profile in profiles], float)
    return weights/weights.sum(1, keepdims=True), multipliers


@lru_cache(maxsize=4096)
def local_day_slots(midnight, timezone_name):
    """Local quarter-hour indices that exist on one calendar day (92, 96 or 100)."""
    midnight = pd.Timestamp(midnight, unit="s", tz="UTC").tz_convert(timezone_name)
    stamps = pd.date_range(midnight, periods=26*4, freq="15min")
    stamps = stamps[stamps.normalize() == midnight]
    return (stamps.hour*4+stamps.minute//15).to_numpy(), midnight.weekday() >= 5


def local_components(first_slot, count, timezone_name, priors, countries=("NL",), calendar=None, seed=42):
    """Per-country arrival mass per archetype and UTC quarter-hour, with day-level factors.

    Normalizing over the whole calendar day (23, 24 or 25 hours) keeps the
    daily attempted-arrival volume independent of where a window starts. Each
    day mixes the weekday and weekend curves by its weekend share (1 on
    weekends and holidays, partial on bridge days). Returns the components
    (countries, archetypes, slots) and the volume and energy factors
    (countries, slots); without a calendar the factors are one.
    """
    from backend.scenario_calendar import neutral_effects
    stamps = pd.to_datetime((first_slot+np.arange(count))*SLOT, unit="s", utc=True).tz_convert(timezone_name)
    local_slots = (stamps.hour*4+stamps.minute//15).to_numpy()
    unique_days, day_index = np.unique(stamps.normalize().as_unit("s").asi8, return_inverse=True)
    day_index = day_index.reshape(-1)
    dates = [pd.Timestamp(int(value), unit="s", tz="UTC").tz_convert(timezone_name).date() for value in unique_days]
    curves = {(kind, weekend): arrival_curve(priors, kind, weekend) for kind in ARCHETYPES for weekend in (False, True)}
    day_mass = []
    for value in unique_days:
        full_slots, _ = local_day_slots(int(value), timezone_name)
        day_mass.append({key: curve[full_slots].sum() for key, curve in curves.items()})
    component = np.empty((len(countries), len(ARCHETYPES), count))
    volume, energy = np.ones((len(countries), count)), np.ones((len(countries), count))
    for c, country in enumerate(countries):
        effects = calendar.effects(country, dates[0], dates[-1], seed) if calendar else neutral_effects(dates[0], dates[-1])
        share = np.asarray(effects.weekend_share)[[effects.at(day) for day in dates]][day_index]
        for k, kind in enumerate(ARCHETYPES):
            weekday = curves[(kind, False)][local_slots]/np.array([mass[(kind, False)] for mass in day_mass])[day_index]
            weekend = curves[(kind, True)][local_slots]/np.array([mass[(kind, True)] for mass in day_mass])[day_index]
            component[c, k] = (1-share)*weekday+share*weekend
        if calendar:
            positions = np.array([effects.at(day) for day in dates])[day_index]
            volume[c], energy[c] = effects.volume[positions], effects.energy[positions]
    return component, volume, energy


def session_attributes(keys, slots, weights, component, power, fast, priors, energy_factor=1.):
    """Archetype, duration and energy of a candidate arrival, from its own uniforms.

    `energy_factor` scales the drawn energy for the arrival day's weather before
    the power and duration limit applies.
    """
    posterior = weights*component.T
    cumulative = np.cumsum(posterior, axis=1)
    pick = uniforms(keys, slots, 1)*cumulative[:, -1]
    kind = np.minimum((pick[:, None] >= cumulative).sum(1), len(ARCHETYPES)-1)
    u_duration, u_other = uniforms(keys, slots, 2), uniforms(keys, slots, 3)
    workplace = kind == ARCHETYPES.index("workplace")
    # Positive duration/energy dependence is assumed (Gaussian copula, 0.4)
    u_energy = ndtr(DURATION_ENERGY_CORRELATION*ndtri(u_duration)
                    +np.sqrt(1-DURATION_ENERGY_CORRELATION**2)*ndtri(u_other))
    duration, energy = [np.where(workplace, quantiles(priors[name], "workplace", u), quantiles(priors[name], "public", u))
                        for name, u in (("duration", u_duration), ("energy", u_energy))]
    duration *= np.array([DURATION_SCALE[name] for name in ARCHETYPES])[kind]
    # Whole seconds keep departures and the next free quarter-hour exact
    seconds = np.round(np.clip(np.where(fast, duration*FAST_DURATION_SCALE, duration), .25, MAX_HOURS)*3600).astype(np.int64)
    energy = np.where(kind == ARCHETYPES.index("retail"), energy*.75, energy)*energy_factor
    return seconds, np.clip(energy, 0., power*seconds/3600)


def quantiles(table, column, probability):
    percentages = table["Percentage of charging events"].to_numpy(float)
    return np.interp((1-probability)*100, percentages, table[column].to_numpy(float))


def energy_given_duration(hours, uniform, power, fast, priors, energy_factor=1.):
    """Energy of connections whose length is already known.

    Used where something else decides when a vehicle is plugged in (the CPFT
    occupancy forecast) and the energy still has to be consistent with the
    other sources. The length's place in the public duration prior fixes a
    duration quantile; energy follows through the same copula as a freshly
    sampled session, from `uniform` (one per connection), and is capped by
    what the plug can deliver in that time.
    """
    hours = np.asarray(hours, float)
    table = priors["duration"]
    exceeded = table["Percentage of charging events"].to_numpy(float)
    lengths = table["public"].to_numpy(float)
    order = np.argsort(lengths, kind="stable")
    # Share of sessions lasting longer than the prior-equivalent length
    longer = np.interp(hours/np.where(fast, FAST_DURATION_SCALE, 1.), lengths[order], exceeded[order])
    u_duration = np.clip(1-longer/100, 1e-6, 1-1e-6)
    u_energy = ndtr(DURATION_ENERGY_CORRELATION*ndtri(u_duration)
                    +np.sqrt(1-DURATION_ENERGY_CORRELATION**2)*ndtri(uniform))
    energy = quantiles(priors["energy"], "public", u_energy)*energy_factor
    return np.clip(energy, 0., np.asarray(power, float)*hours)


def blocked_walk(row, slot, seconds):
    """Accept candidates in time order per row, skipping those while occupied.

    Rounds advance every row by one accepted connection, so the work is
    vectorized over rows and the loop length is the most connections in a row.
    """
    order = np.lexsort((slot, row))
    row, slot, seconds = row[order], slot[order], seconds[order]
    span = int(slot.max())+ROW_SLOTS+1 if len(slot) else 1
    composite = row*span+slot
    ends = np.searchsorted(row, np.unique(row), "right")
    starts = np.searchsorted(row, np.unique(row), "left")
    row_end = np.zeros(int(row.max())+1 if len(row) else 0, np.int64)
    row_end[row[starts]] = ends
    accepted = np.zeros(len(slot), bool)
    current = starts
    while len(current):
        accepted[current] = True
        free = slot[current]+(seconds[current]+SLOT-1)//SLOT
        following = np.searchsorted(composite, row[current]*span+free, "left")
        current = following[following < row_end[row[current]]]
    return order[accepted]


def sample_world(chargers, start, end, *, profiles=None, source="simple", seed=42, assumption="base",
                 timezone_name="Europe/Amsterdam", daily_arrivals=2., priors=None, calendar=None, countries=None):
    """Sessions connected during [start, end), for every point, as a SessionFrame.

    `calendar` (a CalendarEffects) adds day-level effects; `countries` gives each
    point's ISO country code for its holidays and climate (default: the
    calendar's default country).
    """
    if assumption not in ASSUMPTION_MULTIPLIERS:
        raise ValueError("Unknown demand assumption")
    left, right = epoch(start), epoch(end)
    if right <= left:
        raise ValueError("Scenario window must be increasing")
    if not chargers:
        return SessionFrame.empty()
    priors = priors if priors is not None else load_priors()
    ids = np.array([int(charger["id"]) for charger in chargers], np.int64)
    if len(np.unique(ids)) != len(ids):
        raise ValueError("Duplicate charging-point IDs")
    weights, multipliers = profile_arrays(profiles, len(chargers))
    volume = daily_arrivals*multipliers*ASSUMPTION_MULTIPLIERS[assumption]
    if not (np.isfinite(volume).all() and (volume >= 0).all()):
        raise ValueError("Invalid assumed arrival volume")
    power = np.array([point_power(charger) for charger in chargers])
    fast = np.array([str(charger.get("type", "")).lower() == "fast" for charger in chargers])
    keys = point_keys(ids, source, seed)

    # Days whose arrivals can reach the window, plus earlier ones for the overlap rule
    first_block = int((left-MAX_HOURS*3600)//(BLOCK_SLOTS*SLOT))-LOOKBACK_ROWS
    last_block = int(np.ceil(right/(BLOCK_SLOTS*SLOT)))-1
    blocks = last_block-first_block+1
    first_slot = first_block*BLOCK_SLOTS-WARMUP_SLOTS
    union = blocks*BLOCK_SLOTS+WARMUP_SLOTS
    absolute = first_slot+np.arange(union)
    default = calendar.default if calendar else "NL"
    countries = list(countries) if countries is not None else [default]*len(chargers)
    present, country = np.unique(np.asarray(countries, dtype=object).astype(str), return_inverse=True)
    country = country.reshape(-1)
    component, day_volume, day_energy = local_components(first_slot, union, timezone_name, priors, list(present), calendar, seed)
    groups, group_of = np.unique(np.column_stack([weights, volume, country]), axis=0, return_inverse=True)
    group_of = group_of.reshape(-1)
    group_country = groups[:, -1].astype(np.int64)
    # One matrix product per country keeps the arithmetic of the calendar-free sampler
    mixture = np.empty((len(groups), union))
    for c in np.unique(group_country):
        rows = group_country == c
        mixture[rows] = groups[rows, :len(ARCHETYPES)] @ component[c]
    probability = -np.expm1(-groups[:, len(ARCHETYPES):len(ARCHETYPES)+1]*day_volume[group_country]*mixture)
    # Compare the top 53 random bits with an integer threshold, as to_unit would
    threshold = np.floor(probability*2.**53+.5).astype(np.uint64)
    slot_stream = stream(absolute, 0)

    points, slots = [], []
    size = max(1, CHUNK_CELLS//union)
    for offset in range(0, len(chargers), size):
        chunk = slice(offset, offset+size)
        draws = mix(np.bitwise_xor(keys[chunk, None], slot_stream[None, :]))
        np.right_shift(draws, np.uint64(11), out=draws)
        point, slot = np.nonzero(draws < threshold[group_of[chunk]])
        points.append(point+offset)
        slots.append(slot)
    point, slot = np.concatenate(points), np.concatenate(slots)
    seconds, energy = session_attributes(keys[point], absolute[slot], weights[point], component[country[point], :, slot].T,
                                          power[point], fast[point], priors, day_energy[country[point], slot])

    # Row b simulates union slots [b*BLOCK, b*BLOCK+ROW) and keeps its last BLOCK.
    # A candidate is kept by one row and is warm-up for up to WARMUP_ROWS later rows.
    owner = (slot-WARMUP_SLOTS)//BLOCK_SLOTS
    indices, rows, kept = [], [], []
    for later in range(WARMUP_ROWS+1):
        block = owner+later
        valid = (block >= 0) & (block < blocks) & (block*BLOCK_SLOTS <= slot)
        indices.append(np.flatnonzero(valid))
        rows.append(point[valid]*blocks+block[valid])
        kept.append(np.full(valid.sum(), later == 0))
    candidate, row, kept = np.concatenate(indices), np.concatenate(rows), np.concatenate(kept)
    accepted = blocked_walk(row, slot[candidate], seconds[candidate])
    accepted = accepted[kept[accepted]]
    row, candidate = row[accepted], candidate[accepted]

    starts = (absolute[slot[candidate]]*SLOT).astype(float)
    ends = starts+seconds[candidate]
    # The overlap rule uses the previous days' own last departures, so it never
    # depends on which days a request happens to include
    last_end = np.full((len(chargers), LOOKBACK_ROWS+blocks), -np.inf)
    np.maximum.at(last_end, (row//blocks, LOOKBACK_ROWS+row % blocks), ends)
    previous = np.full(len(row), -np.inf)
    for back in range(1, LOOKBACK_ROWS+1):
        previous = np.maximum(previous, last_end[row//blocks, LOOKBACK_ROWS+row % blocks-back])
    keep = (starts >= previous) & (starts < right) & (ends > left)
    frame = SessionFrame(ids[point[candidate[keep]]], starts[keep], ends[keep], energy[candidate[keep]])
    return frame.sorted()
