"""Compare the pre-optimization Git revision with current analysis code.

Uses disposable synthetic fixtures, real SQLite/SpatiaLite and local HTTP.
No application databases are opened and no external service is contacted.
"""

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
from threading import Thread
import time
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASELINE = "4ba8f16"
ZONE = "Europe/Amsterdam"
TARGET = date(2025, 10, 14)

import numpy as np
from flask import Flask
from geoalchemy2 import load_spatialite
from sqlalchemy import create_engine, event
from sqlalchemy.orm import scoped_session, sessionmaker
from werkzeug.serving import make_server, WSGIRequestHandler

from backend.cpft import day_window
from backend.grid_data import GridHour, GridStore
from backend.kpi.statistics import calculate_kpis
from backend.scenario_sampling import ScenarioSession, session_to_dict
from backend.session_sources import ScenarioCache, SessionSourceService
from backend.spatial_profiles import DEFAULT_ATLAS, get_atlas
from backend.spatialite import configure_spatialite


def git(*args):
    return subprocess.check_output(["git", "-c", f"safe.directory={ROOT.as_posix()}", *args],
                                   cwd=ROOT, text=True, encoding="utf-8")


def old_module(revision, path):
    source = git("show", f"{revision}:{path}")
    module = ModuleType("benchmark_before_"+path.replace("/", "_").replace(".", "_"))
    module.__file__ = str(ROOT/path)
    sys.modules[module.__name__] = module
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def summary(samples):
    return dict(median_ms=statistics.median(samples), min_ms=min(samples), max_ms=max(samples),
                samples_ms=samples)


def comparison(name, before, after, **details):
    old, new = summary(before), summary(after)
    return dict(name=name, before=old, after=new, speedup=old["median_ms"]/new["median_ms"],
                reduction_pct=100*(1-new["median_ms"]/old["median_ms"]), **details)


def paired(name, before, after, repeats, check, setup=None, **details):
    times = {"before": [], "after": []}
    # Exclude imports, first calls and code/database page warmup from the samples.
    for iteration in range(repeats+1):
        results = {}
        for label, operation in ([("before", before), ("after", after)] if iteration % 2 == 0
                                 else [("after", after), ("before", before)]):
            if setup:
                setup(label, iteration)
            start = time.perf_counter_ns()
            results[label] = operation()
            elapsed = (time.perf_counter_ns()-start)/1e6
            if iteration:
                times[label].append(elapsed)
        check(results["before"], results["after"])
    result = comparison(name, times["before"], times["after"], **details)
    print(f"{name}: {result['before']['median_ms']:.2f} -> {result['after']['median_ms']:.2f} ms "
          f"({result['speedup']:.2f}x)", flush=True)
    return result


def assert_equal(left, right):
    assert left == right


def assert_basic_equal(full, basic):
    for key, value in basic.items():
        if key == "summary":
            for metric, number in value.items():
                if isinstance(number, (int, float)):
                    assert np.isclose(number, full[key][metric], rtol=1e-10, atol=1e-8), metric
                else:
                    assert number == full[key][metric], metric
        else:
            assert value == full[key], key


def fixture(points, days):
    chargers = [dict(id=i+1, power=11., type="regular", latitude=52.37+.003*np.sin(i),
                     longitude=4.88+.04*(i+.5)/points) for i in range(points)]
    first = TARGET-timedelta(days=days-1)
    daily = []
    for offset in range(days):
        day = first+timedelta(days=offset)
        left, _ = day_window(day, ZONE)
        records = [ScenarioSession(charger["id"], left+timedelta(hours=start),
                                   left+timedelta(hours=end), energy)
                   for charger in chargers
                   for start, end, energy in [(3.25, 6., 7.), (9., 16., 18.), (21.5, 26.25, 10.)]]
        # Include the previous day's overnight connections in occupancy.
        previous = left-timedelta(days=1)
        records += [ScenarioSession(charger["id"], previous+timedelta(hours=21.5),
                                    previous+timedelta(hours=26.25), 10.) for charger in chargers]
        daily.append((day, records))
    left, _ = day_window(first-timedelta(days=1), ZONE)
    _, right = day_window(TARGET+timedelta(days=1), ZONE)
    hours = [GridHour(left+timedelta(hours=i), 100.+10*(i % 24), 40.+i % 40, False, False)
             for i in range(int((right-left).total_seconds()/3600))]
    return chargers, daily, hours


def make_app(path, chargers, hours, old_views, old_kpi, old_features, service):
    from backend.views import station_data
    from backend.features import features_data
    from backend.kpi.user import kpi_data
    configure_spatialite()
    engine = create_engine(f"sqlite:///{(path/'app.sqlite').as_posix()}")
    # Fixture preparation is untimed; avoid thousands of EPSG insert transactions.
    event.listen(engine, "connect", lambda connection, record:
                 load_spatialite(connection, record, transaction=True, init_mode="WGS84"))
    with engine.begin() as db:
        for statement in [
            "CREATE TABLE operators (id INTEGER PRIMARY KEY,name TEXT)",
            "CREATE TABLE locations (id INTEGER PRIMARY KEY,latitude REAL,longitude REAL,street TEXT,supplement TEXT,postal_name TEXT,country TEXT)",
            "SELECT AddGeometryColumn('locations','geom',4326,'POINT','XY')",
            "CREATE TABLE columns (id INTEGER PRIMARY KEY,operator_id INTEGER,location_id INTEGER,source TEXT)",
            "CREATE TABLE charging_points (id INTEGER PRIMARY KEY,column_id INTEGER,power REAL,type TEXT)",
            "CREATE TABLE transformers (id INTEGER PRIMARY KEY,location_id INTEGER,type TEXT)",
            "CREATE TABLE sessions (id INTEGER PRIMARY KEY,cp_id INTEGER,start DATETIME,end DATETIME,consumption REAL)",
            "CREATE TABLE power_mixes (id INTEGER PRIMARY KEY,country_zone TEXT,datetime DATETIME,renewable_percentage REAL,co2_intensity REAL)",
            "CREATE INDEX ix_locations_coordinates ON locations(latitude,longitude)",
            "INSERT INTO operators VALUES (1,'Benchmark')",
        ]:
            db.exec_driver_sql(statement)
        for charger in chargers:
            point = charger["id"]
            db.exec_driver_sql("INSERT INTO locations VALUES (?,?,?,'Synthetic street',NULL,'Amsterdam','NL',MakePoint(?,?,4326))",
                              (point, charger["latitude"], charger["longitude"], charger["longitude"], charger["latitude"]))
            db.exec_driver_sql("INSERT INTO columns VALUES (?,1,?,NULL)", (point, point))
            db.exec_driver_sql("INSERT INTO charging_points VALUES (?,?,11,'regular')", (point, point))
            if point % 10 == 1:
                db.exec_driver_sql("INSERT INTO transformers VALUES (?,?,'Middle')", (point, point))
    grid_path = path/"grid.sqlite"
    GridStore(grid_path).save(hours)
    sessions = scoped_session(sessionmaker(bind=engine))
    app = Flask(__name__)
    app.config.update(TESTING=True, GRID_DATA_CACHE=str(grid_path), aggregator_config={},
                      **{"station_data.db": SimpleNamespace(session=sessions, engine=engine)})
    # Both algorithms read the SAME pre-populated session cache; no generator stub.
    app.extensions["session_source_service"] = service
    app.register_blueprint(old_views.station_data, url_prefix="/before/stations", name="before_stations")
    app.register_blueprint(old_kpi.kpi_data, url_prefix="/before/kpi", name="before_kpi")
    app.register_blueprint(old_features.features_data, url_prefix="/before/features", name="before_features")
    app.register_blueprint(station_data, url_prefix="/after/stations", name="after_stations")
    app.register_blueprint(kpi_data, url_prefix="/after/kpi", name="after_kpi")

    @app.teardown_appcontext
    def close_session(_error):
        sessions.remove()

    return app, engine


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    lines = ["# Analysis speed comparison", "",
             f"Baseline: `{report['baseline_commit']}`; {report['repeats']} measured repeats after one discarded warmup.",
             "", "Synthetic fixtures on this machine; local single-worker HTTP, SQLite and real SpatiaLite.",
             "No added network delay. HTTP timings include requests and JSON parsing, but exclude plotting/DOM rendering.",
             "Cold means an empty scenario cache, with Python imports and the atlas already loaded.",
             "CPFT inference and external cost optimization are not benchmarked.", "",
             "| Comparison | Before median (ms) | After median (ms) | Speedup | Time reduction |",
             "|---|---:|---:|---:|---:|"]
    for row in report["results"]:
        speed = f"{row['speedup']:.2f}x" if row["speedup"] is not None else "Deferred work"
        reduction = f"{row['reduction_pct']:.1f}%" if row["reduction_pct"] is not None else "n/a"
        lines.append(f"| {row['name']} | {row['before']['median_ms']:.3f} | {row['after']['median_ms']:.3f} | "
                     f"{speed} | {reduction} |")
    lines += ["", "The environmental follow-up defers work: inspect the full-KPI-workflow row as well as time to basic KPIs.",
              "The microbenchmarks isolate individual changes and their speedups must not be multiplied together.",
              "Wall-clock speed is recorded, not asserted in CI. Correctness and request/connection counts are asserted.",
              "", "Raw samples, fixture settings, request counts, payload sizes and source hashes are in the adjacent JSON file.",
              "", "## HTTP work per action", "",
              "| Action | Before requests / bytes | After requests / bytes |", "|---|---:|---:|"]
    for row in report.get("http_actions", []):
        lines.append(f"| {row['name']} | {row['before_requests']} / {row['before_bytes']} | "
                     f"{row['after_requests']} / {row['after_bytes']} |")
    path.with_suffix(".md").write_text("\n".join(lines)+"\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default=BASELINE)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--points", type=int, default=100, help="HTTP workflow and scenario-service selection size")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--cache-points", type=int, default=1000)
    parser.add_argument("--kpi-points", type=int, default=500)
    parser.add_argument("--kpi-days", type=int, default=30)
    parser.add_argument("--output", type=Path, default=ROOT/"reports/analysis_speed_comparison.json")
    args = parser.parse_args()
    if min(args.repeats, args.points, args.days, args.cache_points, args.kpi_points, args.kpi_days) < 1:
        parser.error("All sizes and repeats must be positive")
    revision = git("rev-parse", args.baseline).strip()
    shared_dependencies = ["backend/scenario_sampling.py", "backend/scenario_profiles.py",
        "backend/carbon_charging.py", "backend/kpi/environment.py", "backend/grid_data.py",
        "backend/utils.py", "backend/aggregators.py", "backend/cpft.py"]
    for relative in shared_dependencies:
        if git("show", f"{revision}:{relative}") != (ROOT/relative).read_text(encoding="utf-8"):
            raise RuntimeError(f"{relative} differs from the baseline. Use an isolated checkout comparison "
                               "instead of mixing different numerical methods in this benchmark.")
    before_sources = old_module(revision, "backend/session_sources.py")
    before_spatial = old_module(revision, "backend/spatial_profiles.py")
    before_sources.get_atlas = before_spatial.get_atlas
    before_stats = old_module(revision, "backend/kpi/statistics.py")
    before_views = old_module(revision, "backend/views.py")
    before_kpi = old_module(revision, "backend/kpi/user.py")
    before_features = old_module(revision, "backend/features.py")
    before_kpi.calculate_kpis = before_stats.calculate_kpis
    paths = shared_dependencies + ["backend/session_sources.py", "backend/spatial_profiles.py", "backend/kpi/statistics.py",
             "backend/views.py", "backend/features.py", "backend/kpi/user.py", "static/scripts/script.js", "static/scripts/data_fetch.js",
             "scripts/benchmark_analysis.py", "scripts/benchmark_analysis_http.mjs"]
    source_hashes = {path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in paths}
    input_hashes = {str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in [DEFAULT_ATLAS, *sorted((ROOT/"data").glob("distribution-of-*.csv"))]}
    results = []
    with tempfile.TemporaryDirectory(prefix="epiot-speed-") as folder:
        work = Path(folder)
        chargers, daily, hours = fixture(args.points, args.days)
        # Cache-only benchmark with realistic nonempty serialized sessions.
        cache_path = work/"bulk.sqlite"
        new_cache, old_cache = ScenarioCache(cache_path), before_sources.ScenarioCache(cache_path)
        records = [session_to_dict(record) for record in daily[0][1][:3]]
        payload = json.dumps({"sessions": records, "spatial_profile": None})
        keys = [str(i) for i in range(args.cache_points)]
        new_cache.save([(key, "simple", str(TARGET), int(key), payload, "benchmark") for key in keys])
        results.append(paired(f"Warm cache reads: {len(keys)} points", lambda: {key: old_cache.get(key) for key in keys},
                              lambda: new_cache.get_many(keys), args.repeats, assert_equal,
                              before_connections=len(keys), after_connections=1))

        # Real sampler, identical seed and priors. Cold cache initialization is outside timing.
        for source in ("simple", "spatial"):
            if source == "spatial" and not DEFAULT_ATLAS.exists():
                raise RuntimeError("Spatial benchmark needs the bundled Amsterdam atlas")
            before_spatial.get_atlas(DEFAULT_ATLAS)
            get_atlas(DEFAULT_ATLAS)
            services = {}

            def setup(label, iteration):
                cls = before_sources.SessionSourceService if label == "before" else SessionSourceService
                services[label] = cls(work/f"{source}-{label}-{iteration}.sqlite")
                if label == "after":
                    get_atlas(DEFAULT_ATLAS)._resolve_coordinates.cache_clear()

            def same_sessions(left, right):
                assert left[0] == right[0]

            results.append(paired(f"Cold {source} scenario: {args.points} points, 1 day",
                lambda: services["before"].get(chargers, TARGET, source=source),
                lambda: services["after"].get(chargers, TARGET, source=source),
                args.repeats, same_sessions, setup=setup))
            results.append(paired(f"Warm {source} scenario: {args.points} points, 1 day",
                lambda: services["before"].get(chargers, TARGET, source=source),
                lambda: services["after"].get(chargers, TARGET, source=source), args.repeats, same_sessions))

        for count, days in dict.fromkeys([(args.points, args.days), (args.kpi_points, args.kpi_days)]):
            points, sessions, mix = fixture(count, days)
            values = (points, sessions, sessions[0][0], TARGET, ZONE, mix)
            results.append(paired(f"Basic KPI computation: {count} points x {days} days",
                lambda: before_stats.calculate_kpis(*values),
                lambda: calculate_kpis(*values, include_environment=False),
                args.repeats, assert_basic_equal))

        # HTTP comparisons use actual frontend functions from both revisions.
        shared_cache = work/"http-sessions.sqlite"
        service = SessionSourceService(shared_cache)
        old_service = before_sources.SessionSourceService(shared_cache)
        for day, _ in daily:
            service.get(chargers, day, source="simple")
        app, engine = make_app(work, chargers, hours, before_views, before_kpi, before_features, service)

        @app.before_request
        def select_service():
            from flask import request
            app.extensions["session_source_service"] = old_service if request.path.startswith("/before/") else service

        for filename in ("script.js", "data_fetch.js"):
            (work/("before-"+filename)).write_text(git("show", f"{revision}:static/scripts/{filename}"), encoding="utf-8")
        server = make_server("127.0.0.1", 0, app, request_handler=QuietHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        spec = dict(base_url=f"http://127.0.0.1:{server.server_port}", root=str(ROOT), work=str(work),
                    repeats=args.repeats, date=str(TARGET), start_date=str(daily[0][0]), points=args.points,
                    polygon={"geometry":{"type":"Polygon","coordinates":[[[4.879,52.36],[4.921,52.36],[4.921,52.38],[4.879,52.38],[4.879,52.36]]]}})
        spec_path = work/"http-spec.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        try:
            node = subprocess.run(["node", "--preserve-symlinks", "--preserve-symlinks-main",
                str(ROOT/"scripts/benchmark_analysis_http.mjs"), str(spec_path)],
                text=True, capture_output=True, encoding="utf-8", cwd=ROOT, timeout=600)
            if node.returncode:
                raise RuntimeError(node.stderr)
            http = json.loads(node.stdout)
        finally:
            server.shutdown()
            thread.join(timeout=5)
            engine.dispose()
        results.extend(http["results"])
    report = dict(baseline_commit=revision, current_head=git("rev-parse", "HEAD").strip(),
                  generated_at=datetime.now(timezone.utc).isoformat(), repeats=args.repeats,
                  settings={key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
                  machine=dict(platform=platform.platform(), python=sys.version, numpy=np.__version__),
                  source_sha256=source_hashes, input_sha256=input_hashes, seed=42,
                  shared_numerical_dependencies_verified=True, results=results, http_actions=http["actions"],
                  limitations=["Synthetic fixtures; not production latency", "No chart rendering",
                               "Single-worker loopback HTTP; no injected delay", "CPFT and external optimizer not measured"])
    write_report(args.output, report)
    print(f"Saved {args.output} and {args.output.with_suffix('.md')}", flush=True)


if __name__ == "__main__":
    main()
