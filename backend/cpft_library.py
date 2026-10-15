"""CPFT day-ahead scenarios sampled on the fly from a prebuilt trajectory library.

Without live charging data, CPFT's input history is itself synthetic, so its
forecast depends only on the calendar and on the history's generating profile.
`scripts/build_cpft_library.py` runs the real checkpoints once per model or
prior version (never daily) over many synthetic histories, and stores the
resulting hourly trajectories by cell:

    (target weekday, month, UTC offset at issue) x land-use mixture
    x attempted-arrival volume x regular/fast point

Each entry keeps its own synthetic history around the issue time and its
31-hour recursive forecast. A request picks one entry per point and day with a
counter-based random number, so no TensorFlow, model call or stored scenario is
needed at request time. Occupancy entries are real CPFT outputs; the cells are
the only approximation of them (volume uses the two neighbouring bins with
log-linear odds, mixtures the nearest codebook entry).

CPFT decides when a point is occupied; the connections inside an occupied run
come from the same priors as the other sources. Two properties of the
checkpoints make that necessary. Their hourly kWh is an expected value far
below what a session delivers, and the recursive forecast often holds a point
occupied for the whole horizon, longer than any one stay in the duration prior.
Hourly occupancy cannot tell one long stay from several in a row, so each
occupied run is covered by back-to-back connections whose lengths follow the
duration prior and whose energy follows the energy prior given their length
(`energy_given_duration`), capped by the plug. That keeps CPFT's occupied hours
and gives the day arrivals and energy comparable to the other sources.

A run that starts at issue continues the connection the history shows at issue
(with that connection's own energy) instead of starting a new one at 18:00 for
every plugged-in point, and other runs start somewhere inside their first hour.

Day-level calendar effects (backend/scenario_calendar.py) enter through the
same cells: the day's demand factor scales the volume before the bin is
chosen, a holiday uses the Sunday calendar context (CPFT's own calendar
features know no holidays), and energy follows each day's temperature.
"""

from datetime import date, datetime, time, timedelta
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from backend.cpft_runtime import CPFTUnavailable, MANIFEST, MODEL_DIR
from backend.scenario_sampling import ASSUMPTION_MULTIPLIERS, PRIORS, ROOT, load_priors, point_power
from backend.scenario_world import (FAST_DURATION_SCALE, WORLD_VERSION, energy_given_duration, point_keys,
                                    profile_arrays, quantiles, uniforms)
from backend.session_frame import SessionFrame

LIBRARY = ROOT / "backend/data/cpft_library.npz"
# Counter space of the per-run random numbers, apart from the day ordinals used for choosing entries;
# each occupied run owns SLOTS_PER_RUN counters: one per connection, and the last for where it starts
RUN_SLOTS = 1 << 40
SLOTS_PER_RUN = 128
MAX_CONNECTIONS = SLOTS_PER_RUN-8
MIN_HOURS = .25  # the shortest connection, as in the world sampler
RESOLUTION_HOURS = 1.  # CPFT's occupancy is hourly: what it leaves under an hour after a connection is not another one
ISSUE_HOUR = 18
HORIZON = 31  # 18:00 to midnight plus the longest (25-hour) target day
HISTORY_HOURS = 20  # covers the window start before issue, including DST days
CHECKPOINTS = ("best_availability.keras", "best_kwh.keras")


def input_files():
    return [MODEL_DIR/name for name in CHECKPOINTS]+[MANIFEST]+sorted(PRIORS.glob("distribution-of-*.csv"))


def inputs_digest():
    """Checkpoints, preprocessing, sampling priors and world version behind a library."""
    digest = hashlib.sha256(WORLD_VERSION.encode())
    for path in input_files():
        digest.update(path.name.encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def issue_time(target, timezone_name):
    """18:00 local on the day before the target, as CPFT was evaluated."""
    return datetime.combine(target-timedelta(days=1), time(ISSUE_HOUR), ZoneInfo(timezone_name))


def context_key(target, timezone_name):
    issue = issue_time(target, timezone_name)
    return target.weekday(), target.month, int(issue.utcoffset().total_seconds()//60)


class CPFTLibrary:
    def __init__(self, path=LIBRARY):
        path = Path(path)
        if not path.exists():
            raise CPFTUnavailable("The CPFT scenario library is missing. Build it once with "
                                  "`uv run --extra cpft python scripts/build_cpft_library.py`.")
        with np.load(path) as data:
            arrays = {name: data[name] for name in data.files}
        self.meta = json.loads(bytes(arrays.pop("meta")).decode())
        for name, value in arrays.items():
            setattr(self, name, value)
        self.mixtures = np.asarray(self.meta["mixtures"], float)
        self.volumes = np.asarray(self.meta["volume_bins"], float)
        self.contexts = {tuple(key): index for index, key in enumerate(self.meta["contexts"])}
        self.shape = (len(self.contexts), len(self.mixtures), len(self.volumes), 2)

    def check(self, timezone_name):
        if self.meta["timezone"] != timezone_name:
            raise CPFTUnavailable(f"The CPFT library was built for {self.meta['timezone']}; rebuild it for {timezone_name}.")
        if self.meta["inputs_sha256"] != current_inputs():
            raise CPFTUnavailable("CPFT checkpoints or sampling priors changed since the library was built. "
                                  "Rebuild it with `uv run --extra cpft python scripts/build_cpft_library.py`.")

    def cells(self, context, mixture, volume, fast):
        return np.ravel_multi_index((np.broadcast_to(context, np.shape(mixture)), mixture, volume, fast.astype(np.int64)), self.shape)

    def context(self, weekday, month, offset):
        """The calendar context, or the same weekday and month at the other UTC offset."""
        if (weekday, month, offset) in self.contexts:
            return self.contexts[(weekday, month, offset)]
        options = [index for (day, mon, _), index in self.contexts.items() if day == weekday and mon == month]
        if not options:
            raise CPFTUnavailable(f"The CPFT library has no calendar context for weekday {weekday} in month {month}")
        return options[0]


@lru_cache(maxsize=1)
def _inputs(stamps):
    return inputs_digest()


def current_inputs():
    """Hash the inputs again only when one of their files changes."""
    return _inputs(tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in input_files()))


@lru_cache(maxsize=2)
def _library(path, modified):
    return CPFTLibrary(path)


def get_library(path=LIBRARY):
    path = Path(path)
    return _library(str(path), path.stat().st_mtime_ns if path.exists() else 0)


def runs(occupied):
    """Start and end hour of each occupied run, per row, in row-major order."""
    padded = np.zeros((occupied.shape[0], occupied.shape[1]+2), np.int8)
    padded[:, 1:-1] = occupied
    change = np.diff(padded, axis=1)
    starts, ends = np.nonzero(change == 1), np.nonzero(change == -1)
    return starts[0], starts[1], ends[1]


def choose_entries(library, chargers, target, *, profiles, seed, assumption, daily_arrivals, timezone_name, calendar, countries, info):
    """The library entry (and its cell) for each point with demand, plus day energy factors."""
    weekday, month, offset = context_key(target, timezone_name)
    context = library.context(weekday, month, offset)
    ids = np.array([int(charger["id"]) for charger in chargers], np.int64)
    power = np.array([point_power(charger) for charger in chargers])
    fast = np.array([str(charger.get("type", "")).lower() == "fast" for charger in chargers])
    weights, multipliers = profile_arrays(profiles, len(chargers))
    volume = daily_arrivals*multipliers*ASSUMPTION_MULTIPLIERS[assumption]
    keys = point_keys(ids, "cpft", seed)
    day = np.full(len(ids), target.toordinal())
    contexts = np.full(len(ids), context)
    energy_today, energy_before = np.ones(len(ids)), np.ones(len(ids))
    if calendar:
        countries = np.asarray(countries if countries is not None else [calendar.default]*len(ids), dtype=object).astype(str)
        info["calendar"] = {}
        for country in np.unique(countries):
            rows = countries == country
            effects = calendar.effects(country, target-timedelta(days=1), target, seed)
            volume[rows] *= effects.volume[1]
            energy_today[rows], energy_before[rows] = effects.energy[1], effects.energy[0]
            # CPFT's calendar features know no holidays: a holiday is forecast as a Sunday
            if effects.kind[1] in ("holiday", "partial"):
                holiday = uniforms(keys[rows], day[rows], 3) < effects.weekend_share[1]
                contexts[np.flatnonzero(rows)[holiday]] = library.context(6, month, offset)
            info["calendar"][country] = [effects.summary(0), effects.summary(1)]
    mixture = np.abs(weights[:, None, :]-library.mixtures[None]).sum(-1).argmin(1)
    # Log-linear odds between the two neighbouring volume bins
    logs = np.log(library.volumes)
    position = np.interp(np.log(np.maximum(volume, 1e-12)), logs, np.arange(len(logs)))
    lower = np.floor(position).astype(np.int64)
    choice = np.minimum(lower+(uniforms(keys, day, 1) < position-lower), len(logs)-1)
    info["outside_volume_range"] = int(((volume > 0) & ((volume < library.volumes[0]) | (volume > library.volumes[-1]))).sum())
    info["zero_volume_points"] = int((volume <= 0).sum())
    cells = library.cells(contexts, mixture, choice, fast)
    first, last = library.cell_offsets[cells], library.cell_offsets[cells+1]
    entry = first+np.minimum((uniforms(keys, day, 2)*(last-first)).astype(np.int64), last-first-1)
    active = np.flatnonzero(volume > 0)
    return dict(ids=ids[active], power=power[active], fast=fast[active], keys=keys[active], entry=entry[active],
                cells=cells[active], energy_today=energy_today[active], energy_before=energy_before[active])


def connections(first, last, keys, slots, fast, priors):
    """Back-to-back connections that cover each run from `first` to `last`.

    Lengths follow the public duration prior (shorter at fast points), at least
    15 minutes, and what would be left after a connection when that is less than
    an hour (the resolution of the occupancy) joins it. Returns, per connection,
    its run, start, end and turn.
    """
    scale = np.where(fast, FAST_DURATION_SCALE, 1.)
    cursor = np.asarray(first, float).copy()
    active = np.flatnonzero(last-cursor > 1e-6)
    runs_, starts, ends, turns = [], [], [], []
    for turn in range(MAX_CONNECTIONS):
        if not len(active):
            break
        drawn = quantiles(priors["duration"], "public", uniforms(keys[active], slots[active]+turn, 0))*scale[active]
        left = (last[active]-cursor[active])/3600
        hours = np.maximum(drawn, MIN_HOURS)
        hours = np.where((left-hours < RESOLUTION_HOURS) | (turn == MAX_CONNECTIONS-1), left, hours)
        finish = cursor[active]+hours*3600
        runs_.append(active)
        starts.append(cursor[active].copy())
        ends.append(finish)
        turns.append(np.full(len(active), turn, np.int64))
        cursor[active] = finish
        active = active[last[active]-cursor[active] > 1e-6]
    if not runs_:
        empty = np.zeros(0)
        return np.zeros(0, np.int64), empty, empty, np.zeros(0, np.int64)
    return np.concatenate(runs_), np.concatenate(starts), np.concatenate(ends), np.concatenate(turns)


def sample_cpft(chargers, target, *, profiles=None, seed=42, assumption="base", daily_arrivals=2.,
                timezone_name="Europe/Amsterdam", library=None, calendar=None, countries=None):
    """Synthetic history up to 18:00 the day before and CPFT occupancy from then to the end of `target`.

    Occupied runs become sessions whose energy follows the priors, given their length; a run that
    starts at issue continues the history's connection at issue. With a `calendar`, `countries`
    gives each point's ISO code for its day effects.
    """
    if assumption not in ASSUMPTION_MULTIPLIERS:
        raise ValueError("Unknown demand assumption")
    zone = ZoneInfo(timezone_name)
    issue = issue_time(target, timezone_name).timestamp()
    window_start = datetime.combine(target-timedelta(days=1), time.min, zone).timestamp()
    day_start = datetime.combine(target, time.min, zone).timestamp()
    end = datetime.combine(target+timedelta(days=1), time.min, zone).timestamp()
    horizon = round((end-issue)/3600)
    info = dict(issue_time=datetime.fromtimestamp(issue, ZoneInfo("UTC")).isoformat(), horizon_hours=horizon,
                outside_volume_range=0, zero_volume_points=0)
    if not chargers:
        return SessionFrame.empty(), info
    library = library or get_library()
    library.check(timezone_name)
    info.update(library_version=library.meta["inputs_sha256"][:16], built_at=library.meta["built_at"])
    chosen = choose_entries(library, chargers, target, profiles=profiles, seed=seed, assumption=assumption,
                            daily_arrivals=daily_arrivals, timezone_name=timezone_name, calendar=calendar,
                            countries=countries, info=info)
    ids, power, fast, keys, entry = chosen["ids"], chosen["power"], chosen["fast"], chosen["keys"], chosen["entry"]
    energy_today, energy_before = chosen["energy_today"], chosen["energy_before"]

    # History: the entry's own synthetic connections, cut at issue as CPFT saw them
    starts, lengths = library.history_offsets[entry], library.history_offsets[entry+1]-library.history_offsets[entry]
    owner = np.repeat(np.arange(len(entry)), lengths)
    index = np.arange(lengths.sum())+np.repeat(starts-(np.cumsum(lengths)-lengths), lengths)
    begin = issue+library.history_start[index].astype(float)
    finish = issue+library.history_end[index].astype(float)
    keep = finish > window_start
    owner, begin, finish, index = owner[keep], begin[keep], finish[keep], index[keep]

    # Forecast: CPFT says when each point is occupied
    priors = load_priors()
    occupied = library.occupied[entry, :horizon].astype(bool)
    row, low, high = runs(occupied)
    departure = issue+high*3600.
    # A run that starts at issue is the connection the history shows at issue, continued. It keeps its own
    # arrival and energy and leaves when it was due to, or when CPFT's run ends if that is sooner. What is
    # left of the run after that is covered by further connections.
    ongoing = finish > issue
    running = np.full(len(entry), -1, np.int64)
    running[owner[ongoing]] = np.flatnonzero(ongoing)
    continued = np.where(low == 0, running[row], -1)
    joined = continued >= 0
    stop = np.minimum(finish[continued[joined]], departure[joined])
    stop = np.where(departure[joined]-stop < RESOLUTION_HOURS*3600, departure[joined], stop)
    end = np.minimum(finish, issue)
    end[continued[joined]] = stop
    share = np.where(finish > end, (end-begin)/np.maximum(finish-begin, 1.), 1.)
    delivered = library.history_energy[index].astype(float)*energy_before[owner]*share
    delivered = np.minimum(delivered, power[owner]*np.maximum(end-begin, 0.)/3600)
    history = SessionFrame(ids[owner], begin, end, delivered)

    # Occupancy is hourly: a run starts somewhere inside its first hour (not on the hour for every point), and
    # whatever it covers is back-to-back connections drawn from the priors
    base = RUN_SLOTS+(target.toordinal()*64+low)*SLOTS_PER_RUN
    first = np.empty(len(low))
    first[joined] = stop
    first[~joined] = issue+(low[~joined]+.75*uniforms(keys[row[~joined]], base[~joined]+SLOTS_PER_RUN-1, 0))*3600.
    run, begins, ends, turn = connections(first, departure, keys[row], base, fast[row], priors)
    point = row[run]
    # Energy follows the priors given each connection's length, and the weather of its arrival day
    day_energy = np.where(begins < day_start, energy_before[point], energy_today[point])
    energy = energy_given_duration((ends-begins)/3600, uniforms(keys[point], base[run]+turn, 1), power[point], fast[point],
                                   priors, day_energy)
    forecast = SessionFrame(ids[point], begins, ends, energy)
    return SessionFrame.concat([history, forecast]).sorted(), info
