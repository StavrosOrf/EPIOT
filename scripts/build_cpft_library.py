"""Build the CPFT scenario library once per checkpoint or prior version.

Runs the bundled CPFT checkpoints over synthetic histories for every calendar
context and profile cell, and saves the trajectories that requests sample from
(backend/data/cpft_library.npz). This replaces a daily forecast job: nothing
here depends on today's date, and the web application never loads TensorFlow.

    uv run --extra cpft python scripts/build_cpft_library.py
"""

import argparse
from datetime import date, datetime, timedelta, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.cpft_library import HISTORY_HOURS, HORIZON, ISSUE_HOUR, LIBRARY, context_key, inputs_digest, issue_time
from backend.cpft_runtime import CPFTModelRuntime
from backend.scenario_world import WORLD_VERSION, sample_world
from backend.spatial_profiles import ARCHETYPES, DEFAULT_ATLAS, SpatialAtlas, profile_from_attributes

# Attempted arrivals per day; calendar effects move points across bins, so the
# range covers low demand on quiet days up to high demand on busy days
VOLUME_BINS = (.35, .5, .75, 1., 1.5, 2., 3., 4.5, 6.75, 10.)
POWERS = (11., 50.)  # representative regular and fast points; requests cap energy by actual power
FALLBACK = (0., 0., 0., 1.)


def calendar_contexts(timezone_name, first=date(2025, 1, 1), last=date(2027, 12, 31)):
    """Each (weekday, month, issue UTC offset) with its date nearest mid-month."""
    best = {}
    day = first
    while day <= last:
        key = context_key(day, timezone_name)
        rank = (abs(day.day-15), day)
        if key not in best or rank < best[key][0]:
            best[key] = (rank, day)
        day += timedelta(days=1)
    return sorted((key, value[1]) for key, value in best.items())


def mixture_codebook(atlas_path, clusters, iterations=100):
    """The generic fallback profile plus k-means centres of the atlas neighbourhood mixtures."""
    atlas = SpatialAtlas(atlas_path)
    if atlas.frame is None or clusters == 0:
        return np.array([FALLBACK])
    profiles = [profile_from_attributes(row) for row in atlas.frame.drop(columns="geometry").to_dict("records")]
    points = np.array([[profile["weights"][name] for name in ARCHETYPES] for profile in profiles if profile["matched"]])
    centres = [np.array(FALLBACK)]
    for _ in range(clusters):  # farthest-point initialisation, deterministic
        distance = np.min([np.abs(points-centre).sum(1) for centre in centres], axis=0)
        centres.append(points[distance.argmax()])
    centres = np.array(centres[1:])
    for _ in range(iterations):
        label = np.abs(points[:, None]-centres[None]).sum(-1).argmin(1)
        centres = np.array([points[label == k].mean(0) if (label == k).any() else centres[k] for k in range(clusters)])
    return np.vstack([FALLBACK, centres])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--timezone", default=os.environ.get("FLASK_SESSION_SCENARIO_TIMEZONE", "Europe/Amsterdam"))
    parser.add_argument("--output", type=Path, default=LIBRARY)
    parser.add_argument("--atlas", type=Path, default=DEFAULT_ATLAS)
    parser.add_argument("--mixtures", type=int, default=3, help="Atlas mixture clusters besides the generic profile")
    parser.add_argument("--entries", type=int, default=12, help="Trajectories per cell of an atlas mixture")
    parser.add_argument("--generic-entries", type=int, default=48,
                        help="Trajectories per cell of the generic profile, which most points use")
    parser.add_argument("--core-entries", type=int, default=160,
                        help="Trajectories per generic-profile cell at the core volumes, where most points fall")
    parser.add_argument("--core-volumes", default="1,1.5,2,3,4.5",
                        help="Attempted arrivals per day that get --core-entries (comma-separated bin values)")
    parser.add_argument("--seed", type=int, default=20261014)
    parser.add_argument("--threads", type=int, default=os.cpu_count() or 2)
    parser.add_argument("--batch", type=int, default=1024)
    parser.add_argument("--contexts", type=int, help="Only the first N calendar contexts (for a quick trial)")
    args = parser.parse_args(argv)

    started = time.perf_counter()
    runtime = CPFTModelRuntime(threads=args.threads)
    contexts = calendar_contexts(args.timezone)[:args.contexts]
    mixtures = mixture_codebook(args.atlas, args.mixtures)
    cells = [(m, v, t) for m in range(len(mixtures)) for v in range(len(VOLUME_BINS)) for t in range(len(POWERS))]
    core = {round(float(value), 9) for value in args.core_volumes.split(",")}
    counts = [(args.core_entries if round(VOLUME_BINS[v], 9) in core else args.generic_entries) if m == 0 else args.entries
              for m, v, t in cells]

    offsets, probability, occupied, energy = [0], [], [], []
    history_offsets, history_start, history_end, history_energy = [0], [], [], []
    next_id = 1
    for number, ((weekday, month, offset), target) in enumerate(contexts):
        issue = issue_time(target, args.timezone)
        chargers, profiles = [], []
        for (m, v, t), count in zip(cells, counts):
            for _ in range(count):
                chargers.append(dict(id=next_id, power=POWERS[t], type="fast" if t else "regular"))
                profiles.append({"weights": dict(zip(ARCHETYPES, mixtures[m])), "arrival_multiplier": VOLUME_BINS[v]})
                next_id += 1
            offsets.append(offsets[-1]+count)
        history = sample_world(chargers, issue-timedelta(days=14), issue, profiles=profiles, source="cpft-history",
                               seed=args.seed, daily_arrivals=1., timezone_name=args.timezone)
        ids = np.array([charger["id"] for charger in chargers])
        powers = np.array([charger["power"] for charger in chargers])
        for first in range(0, len(ids), args.batch):
            batch = slice(first, first+args.batch)
            p, o, e = runtime.forecast(history, ids[batch], powers[batch], int(issue.timestamp()), HORIZON)
            probability.append(np.round(p*250).astype(np.uint8))
            occupied.append(o.astype(np.uint8))
            energy.append(np.round(np.minimum(e, 65.535)*1000).astype(np.uint16))
        # Keep the history the window shows before issue, relative to issue
        visible = history.select(history.end > issue.timestamp()-HISTORY_HOURS*3600)
        order = np.searchsorted(ids, visible.cp_id)
        history_offsets.extend(history_offsets[-1]+np.cumsum(np.bincount(order, minlength=len(ids))))
        history_start.append((visible.start-issue.timestamp()).astype(np.int32))
        history_end.append(np.ceil(visible.end-issue.timestamp()).astype(np.int32))
        history_energy.append(visible.energy_kwh.astype(np.float32))
        print(json.dumps(dict(context=number+1, of=len(contexts), weekday=weekday, month=month, utc_offset_minutes=offset,
                              date=str(target), entries=len(ids), seconds=round(time.perf_counter()-started, 1))), flush=True)

    meta = dict(timezone=args.timezone, contexts=[list(key) for key, _ in contexts],
                representative_dates=[str(day) for _, day in contexts], mixtures=mixtures.tolist(),
                mixture_order=list(ARCHETYPES), volume_bins=list(VOLUME_BINS), representative_power_kw=dict(regular=POWERS[0], fast=POWERS[1]),
                entries_per_cell=dict(atlas_mixtures=args.entries, generic=args.generic_entries,
                                      generic_core=args.core_entries, core_volumes=sorted(core)),
                issue_hour=ISSUE_HOUR, horizon_hours=HORIZON, history_hours=HISTORY_HOURS, history_days=14,
                occupancy_threshold=runtime.threshold, seed=args.seed, world_version=WORLD_VERSION,
                inputs_sha256=inputs_digest(), built_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                build_seconds=round(time.perf_counter()-started, 1),
                library_versions={name: importlib.metadata.version(name) for name in ("tensorflow", "keras", "numpy")})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".tmp.npz")
    np.savez_compressed(temporary, meta=np.frombuffer(json.dumps(meta).encode(), np.uint8),
        cell_offsets=np.array(offsets, np.int64), probability_255=np.concatenate(probability),
        occupied=np.concatenate(occupied), kwh_milli=np.concatenate(energy),
        history_offsets=np.array(history_offsets, np.int64), history_start=np.concatenate(history_start),
        history_end=np.concatenate(history_end), history_energy=np.concatenate(history_energy))
    temporary.replace(args.output)
    print(json.dumps(dict(output=str(args.output), entries=offsets[-1], bytes=args.output.stat().st_size,
                          seconds=meta["build_seconds"])), flush=True)


if __name__ == "__main__":
    main()
