"""Compare CPFT library samples with exact CPFT runs for the same points and dates.

The library's only approximation is its cells (mixture cluster, volume bins,
representative power and date). This runs the checkpoints exactly for random
points, each with its own spatial profile, volume and power, on random dates,
and compares occupancy and energy with library samples for the same points.

    uv run --extra cpft python scripts/validate_cpft_library.py
"""

import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scipy.stats import chi2

from backend.cpft_library import choose_entries, get_library, issue_time, sample_cpft
from backend.cpft_runtime import CPFTModelRuntime
from backend.scenario_sampling import ASSUMPTION_MULTIPLIERS, point_power
from backend.scenario_world import sample_world
from backend.spatial_profiles import DEFAULT_ATLAS, get_atlas


def points(count, rng):
    inside = rng.random(count) < .6
    return [dict(id=int(cp_id), power=float(rng.choice([3.7, 11., 22., 50.])), type="fast" if rng.random() < .2 else "regular",
                 latitude=float(52.33+rng.random()*.07 if inside[i] else 50+rng.random()),
                 longitude=float(4.83+rng.random()*.12 if inside[i] else 8+rng.random()))
            for i, cp_id in enumerate(rng.choice(10**7, count, replace=False))]


def hourly(frame, ids, issue, horizon):
    """Occupied flags and kWh per forecast hour from the sessions still running after issue.

    A connection that continues one the history shows at issue starts before it; only its
    part after issue is a forecast. The library's energy comes from the priors, not from the
    checkpoint, so the kWh columns of the report differ by design; occupancy is what is compared.
    """
    occupied, energy = np.zeros((len(ids), horizon)), np.zeros((len(ids), horizon))
    index = {cp_id: row for row, cp_id in enumerate(ids)}
    for cp_id, start, end, kwh in zip(frame.cp_id, frame.start, frame.end, frame.energy_kwh):
        if end > issue:
            first, last = max(int((start-issue)//3600), 0), int(round((end-issue)/3600))
            if last > first:
                occupied[index[int(cp_id)], first:last] = 1
                energy[index[int(cp_id)], first:last] += kwh/(last-first)
    return occupied, energy


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--points", type=int, default=300)
    parser.add_argument("--dates", type=int, default=6)
    parser.add_argument("--repeats", type=int, default=5, help="Library draws per point (different seeds)")
    parser.add_argument("--assumption", default="base", choices=list(ASSUMPTION_MULTIPLIERS))
    parser.add_argument("--timezone", default="Europe/Amsterdam")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--output", type=Path, default=ROOT/"reports/cpft_library_validation.json")
    args = parser.parse_args()
    started = time.perf_counter()
    rng = np.random.default_rng(31)
    runtime, library, atlas = CPFTModelRuntime(threads=args.threads), get_library(), get_atlas(DEFAULT_ATLAS)
    library.check(args.timezone)
    targets = sorted({date(2025, 1, 1)+timedelta(days=int(day)) for day in rng.choice(3*365, args.dates, replace=False)})
    rows = []
    for target in targets:
        chargers = points(args.points, rng)
        profiles = [atlas.resolve(charger) for charger in chargers]
        issue = issue_time(target, args.timezone)
        horizon = int((datetime.combine(target+timedelta(days=1), datetime.min.time(), issue.tzinfo)-issue).total_seconds()//3600)
        ids = [charger["id"] for charger in chargers]
        # Exact: each point's own world history up to issue, then the checkpoints
        history = sample_world(chargers, issue-timedelta(days=14), issue, profiles=profiles, source="cpft-history",
                               assumption=args.assumption, timezone_name=args.timezone)
        probability, occupied, energy = runtime.forecast(history, ids, [point_power(c) for c in chargers], int(issue.timestamp()), horizon)
        # Library: several independent draws for the same points
        sampled_occupied, sampled_energy, used = [], [], []
        for seed in range(args.repeats):
            frame, _ = sample_cpft(chargers, target, profiles=profiles, seed=seed, assumption=args.assumption,
                                   timezone_name=args.timezone, library=library)
            o, e = hourly(frame, ids, issue.timestamp(), horizon)
            sampled_occupied.append(o)
            sampled_energy.append(e)
            used.append(choose_entries(library, chargers, target, profiles=profiles, seed=seed, assumption=args.assumption,
                                       daily_arrivals=2., timezone_name=args.timezone, calendar=None, countries=None, info={})["cells"])
        # Error of the library mean: each cell's finite trajectories are shared by the
        # points that use it (sum over cells of (share)^2 var/K), plus the draws within cells
        used = np.concatenate(used)
        cells, uses = np.unique(used, return_counts=True)
        hours = library.occupied[:, :horizon].sum(1).astype(float)
        variance = 0.
        for cell, count in zip(cells, uses):
            values = hours[library.cell_offsets[cell]:library.cell_offsets[cell+1]]
            share = count/len(used)
            variance += share**2*values.var(ddof=1)/len(values)+count*values.var(ddof=1)/len(used)**2
        exact_hours = occupied.sum(1)
        combined_error = float(np.sqrt(variance+exact_hours.var(ddof=1)/len(ids)))
        library_occupied, library_energy = np.mean(sampled_occupied, axis=0), np.mean(sampled_energy, axis=0)
        exact_curve, library_curve = occupied.mean(0), library_occupied.mean(0)
        # Exact runs are one draw per point, so compare with their own sampling error
        standard_error = np.sqrt(exact_curve*(1-exact_curve)/len(ids)+library_curve*(1-library_curve)/(len(ids)*args.repeats))
        library_hours = float(np.mean([o.sum(1).mean() for o in sampled_occupied]))
        rows.append(dict(target=str(target), weekday=target.strftime("%a"), horizon=horizon, points=len(ids),
            standard_error_hours=combined_error, z=(library_hours-float(exact_hours.mean()))/combined_error,
            cells_used=int(len(cells)),
            exact_occupied_hours=float(occupied.sum(1).mean()), library_occupied_hours=float(np.mean([o.sum(1).mean() for o in sampled_occupied])),
            exact_kwh=float(energy.sum(1).mean()), library_kwh=float(np.mean([e.sum(1).mean() for e in sampled_energy])),
            mean_abs_hourly_occupancy_difference=float(np.abs(exact_curve-library_curve).mean()),
            mean_hourly_standard_error=float(standard_error.mean()),
            hours_outside_two_standard_errors=int((np.abs(exact_curve-library_curve) > 2*standard_error).sum())))
        print(json.dumps(rows[-1]), flush=True)
    summary = dict(executed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), library_built_at=library.meta["built_at"],
                   library_inputs=library.meta["inputs_sha256"][:16], assumption=args.assumption, repeats=args.repeats,
                   seconds=round(time.perf_counter()-started, 1), dates=rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    exact = sum(row["exact_occupied_hours"] for row in rows)/len(rows)
    sampled = sum(row["library_occupied_hours"] for row in rows)/len(rows)
    statistic = sum(row["z"]**2 for row in rows)
    summary["chi2"], summary["chi2_p"] = statistic, float(chi2.sf(statistic, len(rows)))
    args.output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = ["# CPFT library validation", "",
             f"Library built {library.meta['built_at']} (inputs `{library.meta['inputs_sha256'][:16]}`). "
             f"{args.points} random points per date, 60% inside the Amsterdam atlas, mixed power and 20% fast; "
             f"{args.assumption} demand. Exact = the checkpoints run on each point's own 14-day history and power. "
             f"Library = {args.repeats} independent draws per point, averaged.", "",
             "| Date | Day | Hours | Occupied h/point, exact | Library | s.e. | z | kWh/point, exact | Library | Mean abs. hourly occupancy diff. |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in rows:
        lines.append(f"| {row['target']} | {row['weekday']} | {row['horizon']} | {row['exact_occupied_hours']:.2f} | {row['library_occupied_hours']:.2f} | "
                     f"{row['standard_error_hours']:.2f} | {row['z']:+.2f} | {row['exact_kwh']:.2f} | {row['library_kwh']:.2f} | "
                     f"{row['mean_abs_hourly_occupancy_difference']:.3f} |")
    lines += ["", f"Across dates: {exact:.2f} occupied hours per point exactly, {sampled:.2f} from the library; "
              f"chi-square {statistic:.1f} on {len(rows)} degrees of freedom (p = {summary['chi2_p']:.3f}).", "",
              "Occupancy is the checkpoint's. The library's kWh columns are the sessions' energy from the priors given each",
              "connection's length, not the checkpoint's hourly kWh, which is far lower, so they are not comparable with the",
              "exact runs' kWh.", "",
              "The standard error combines the exact runs' sampling error with the library's: each cell's finite",
              "trajectories are shared by every point that uses it on that day, so a cell's mean error is common to",
              "those points. A small p-value would indicate an approximation beyond this sampling error.", ""]
    args.output.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
