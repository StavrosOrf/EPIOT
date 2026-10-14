"""Compare on-request scenarios with the cached, daily-prepared design they replaced.

The baseline is a Git revision of the previous design (scenario cache filled by
a daily job, CPFT inference per request on a cache miss). Each variant runs in
its own process on identical synthetic points, priors and atlas. For the
baseline, "cold" is a request whose day was not prepared and "warm" one served
from the prepared cache; the new design has no cache, so every request is cold.

    uv run --extra cpft python scripts/benchmark_on_the_fly.py --baseline 9ef972c

Timings exclude imports, model/library/atlas loading and HTTP. No database or
network is used. Session counts are reported to show comparable volumes; the
two designs draw different (equally distributed) random scenarios.
"""

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
ZONE = "Europe/Amsterdam"
TARGET = date(2026, 10, 15)


def chargers(count):
    import numpy as np
    rng = np.random.default_rng(2026)
    inside = rng.random(count) < .5  # half inside the Amsterdam atlas
    return [dict(id=int(cp_id), power=float(rng.choice([3.7, 11., 22., 50.])),
                 type="fast" if rng.random() < .2 else "regular",
                 latitude=float(52.33+rng.random()*.07 if inside[i] else 50+rng.random()),
                 longitude=float(4.83+rng.random()*.12 if inside[i] else 8+rng.random()))
            for i, cp_id in enumerate(rng.choice(10**7, count, replace=False))]


def grid_mix(start, end):
    from backend.grid_data import GridHour, resolve_hours
    origin = datetime(2025, 10, 22, tzinfo=timezone.utc)
    profile = [GridHour(origin+timedelta(hours=i), 150+12*i, 40+i, False, False) for i in range(24)]
    return resolve_hours(profile, start, end)


def worker(variant, spec):
    """Runs inside the variant's code tree; prints timings as JSON."""
    from backend.cpft import day_window
    from backend.carbon_charging import daily_profiles
    from backend.kpi.statistics import calculate_environment_kpis, calculate_kpis
    from backend.session_sources import SessionSourceService
    from backend.spatial_profiles import DEFAULT_ATLAS, get_atlas
    get_atlas(DEFAULT_ATLAS)
    folder = Path(spec["folder"])/variant
    folder.mkdir(parents=True, exist_ok=True)
    counter = iter(range(10**6))

    def service():
        if variant == "after":
            return SessionSourceService(atlas_path=DEFAULT_ATLAS)
        return SessionSourceService(cache_path=folder/f"cache-{next(counter)}.sqlite", atlas_path=DEFAULT_ATLAS)

    def day_sessions(svc, points, first, last, source):
        if variant == "after":
            return svc.days(points, first, last, source=source, timezone_name=ZONE)[0]
        return [(day, svc.get(points, day, source=source, timezone_name=ZONE)[0])
                for day in (first+timedelta(days=offset) for offset in range((last-first).days+1))]

    def profile_case(points, source):
        def run(svc):
            sessions, _ = svc.get(points, TARGET, source=source, timezone_name=ZONE)
            start, _ = day_window(TARGET-timedelta(days=1), ZONE)
            _, end = day_window(TARGET, ZONE)
            daily_profiles(points, sessions, start, end, "avg", ZONE)
            return len(sessions)
        return run

    def kpi_case(points, source, days, environment=False):
        first, last = TARGET-timedelta(days=days-1), TARGET
        mix = grid_mix(day_window(first, ZONE)[0], day_window(last, ZONE)[1]) if environment else ()
        def run(svc):
            daily = day_sessions(svc, points, first, last, source)
            if environment:
                calculate_environment_kpis(points, daily, ZONE, mix)
            else:
                output = calculate_kpis(points, daily, first, last, ZONE, include_environment=False)
                return output["summary"]["session_count"]
        return run

    if any(case["source"] == "cpft" for case in spec["cases"]):
        if variant == "after":
            from backend.cpft_library import get_library
            get_library()
        else:
            from backend.cpft_runtime import get_runtime
            get_runtime()
    results = []
    for case in spec["cases"]:
        points = chargers(case["points"])
        run = (profile_case(points, case["source"]) if case["kind"] == "profile"
               else kpi_case(points, case["source"], case["days"], case["kind"] == "environment"))
        repeats = case.get("repeats", spec["repeats"])
        run(service())  # discarded warm-up: imports, interpreter and numpy paths
        cold, warm, sessions = [], [], None
        for _ in range(repeats):
            svc = service()
            started = time.perf_counter()
            sessions = run(svc)
            cold.append((time.perf_counter()-started)*1000)
            if variant == "before":
                started = time.perf_counter()
                run(svc)
                warm.append((time.perf_counter()-started)*1000)
        results.append(dict(case, cold_ms=cold, warm_ms=warm, sessions=sessions))
        print(json.dumps(dict(variant=variant, name=case["name"], cold_median_ms=round(statistics.median(cold), 1))),
              file=sys.stderr, flush=True)
    print(json.dumps(results))


def baseline_tree(revision, folder):
    archive = folder/"baseline.tar"
    subprocess.run(["git", "archive", "--format=tar", "-o", str(archive), revision, "backend", "scripts"], cwd=ROOT, check=True)
    tree = folder/"baseline"
    with tarfile.open(archive) as handle:
        handle.extractall(tree, filter="data")
    # The checkpoints and CPFT source are unchanged; the working copies match the
    # recorded hashes, whereas an archive may convert line endings
    shutil.copytree(ROOT/"others/CPFT-main/CPFT-tool/CPFT_VS_Code_Python", tree/"others/CPFT-main/CPFT-tool/CPFT_VS_Code_Python")
    # Untracked inputs, at the paths of either layout
    for name in ["distribution-of-arrival.csv", "distribution-of-arrival-weekend.csv", "distribution-of-connection-time.csv",
                 "distribution-of-energy-demand.csv", "wijkenbuurten_2022_v2_amsterdam.gpkg"]:
        for target in ("data", "seed_data"):
            (tree/target).mkdir(exist_ok=True)
            shutil.copy2(ROOT/"seed_data"/name, tree/target/name)
    return tree


def report(results, args, revision):
    lines = ["# On-request scenario speed", "",
             f"Baseline: `{revision}` (scenario cache filled by a daily job; CPFT inference on a cache miss). "
             f"After: the working tree. Median of {args.repeats} repeats after one discarded warm-up, on {platform.processor() or platform.machine()}.", "",
             "Timings cover scenario generation plus the load profile or KPI calculation, in process.",
             "They exclude imports, loading the CPFT model/library and the atlas, HTTP and the database.",
             "**Before, cold** is a day the daily job had not prepared (a new date, seed or demand level);",
             "**before, warm** reads the prepared cache. **After** has no cache: every request is generated.", "",
             "| Case | Before, cold (ms) | Before, warm (ms) | After (ms) | vs cold | vs warm |",
             "|---|---:|---:|---:|---:|---:|"]
    for before, after in zip(results["before"], results["after"]):
        cold, warm, now = (statistics.median(values) if values else None
                           for values in (before["cold_ms"], before["warm_ms"], after["cold_ms"]))
        lines.append(f"| {before['name']} | {cold:,.0f} | {warm:,.0f} | {now:,.0f} | {cold/now:,.0f}x | {warm/now:.1f}x |")
    lines += ["", "Session counts (before / after), as a check of comparable scenario volumes:", ""]
    for before, after in zip(results["before"], results["after"]):
        if before["sessions"] is not None:
            lines.append(f"- {before['name']}: {before['sessions']:,} / {after['sessions']:,}")
    lines += ["", "Raw samples are in the adjacent JSON file."]
    return "\n".join(lines)+"\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", default="9ef972c")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--points", type=int, default=1000)
    parser.add_argument("--kpi-points", type=int, default=500)
    parser.add_argument("--kpi-days", type=int, default=7)
    parser.add_argument("--cpft-points", type=int, default=64)
    parser.add_argument("--cpft-days", type=int, default=3)
    parser.add_argument("--output", type=Path, default=ROOT/"reports/on_the_fly_speed.json")
    parser.add_argument("--worker", choices=["before", "after"], help=argparse.SUPPRESS)
    parser.add_argument("--spec", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, json.loads(args.spec.read_text(encoding="utf-8")))
        return
    cases = [dict(name=f"Load profile, simple, {args.points} points", kind="profile", source="simple", points=args.points),
             dict(name=f"Load profile, spatial, {args.points} points", kind="profile", source="spatial", points=args.points),
             dict(name=f"Load profile, CPFT, {args.cpft_points} points", kind="profile", source="cpft", points=args.cpft_points),
             dict(name=f"Basic KPIs, spatial, {args.kpi_points} points x {args.kpi_days} days", kind="kpi", source="spatial",
                  points=args.kpi_points, days=args.kpi_days),
             dict(name=f"Environment KPIs, simple, {args.kpi_points} points x {args.kpi_days} days", kind="environment",
                  source="simple", points=args.kpi_points, days=args.kpi_days),
             dict(name=f"Basic KPIs, CPFT, {args.cpft_points} points x {args.cpft_days} days", kind="kpi", source="cpft",
                  points=args.cpft_points, days=args.cpft_days, repeats=1)]
    revision = subprocess.run(["git", "rev-parse", "--short", args.baseline], cwd=ROOT, check=True,
                              capture_output=True, text=True).stdout.strip()
    results = {}
    with tempfile.TemporaryDirectory(prefix="epiot-on-the-fly-") as folder:
        folder = Path(folder)
        spec = folder/"spec.json"
        spec.write_text(json.dumps(dict(cases=cases, repeats=args.repeats, folder=str(folder))), encoding="utf-8")
        for variant, tree in (("before", baseline_tree(args.baseline, folder)), ("after", ROOT)):
            environment = dict(os.environ, PYTHONPATH=str(tree), TF_CPP_MIN_LOG_LEVEL="3")
            completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", variant, "--spec", str(spec)],
                                       cwd=tree, env=environment, capture_output=True, text=True)
            if completed.returncode:
                raise SystemExit(completed.stderr)
            results[variant] = json.loads(completed.stdout.strip().splitlines()[-1])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dict(baseline=revision, executed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        machine=platform.platform(), python=platform.python_version(), results=results), indent=2), encoding="utf-8")
    args.output.with_suffix(".md").write_text(report(results, args, revision), encoding="utf-8")
    print(args.output.with_suffix(".md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
