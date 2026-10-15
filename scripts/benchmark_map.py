"""Compare overview generation and real Leaflet rendering against Git baseline.

The supplied charger database is opened read-only. Baseline modules are loaded
without changing the checkout. Chrome and pinned map assets are only needed
with --browser; downloads happen before timing and are cached under .tmp.
"""

import argparse
from datetime import datetime, timezone
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
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify, send_file
from sqlalchemy import create_engine
from werkzeug.serving import make_server, WSGIRequestHandler
from backend.views import station_data


def git(*args):
    return subprocess.check_output(["git", "-c", f"safe.directory={ROOT.as_posix()}", *args],
                                   cwd=ROOT, encoding="utf-8")


# Profile simulators the baseline views import and this benchmark never calls;
# they were replaced by the vectorised engine in backend/scenario_profiles.py and,
# for cost optimisation, by backend/cost_charging.py.
REMOVED_SIMULATORS = ("simulate_uncontrolled_profiles_from_sessions", "simulate_delayed_profiles_from_sessions",
                      "simulate_avg_charging_profiles_from_sessions", "simulate_cost_optimal_operation")


def old_module(revision, path):
    # The module itself is gone too (cost optimisation moved to backend/cost_charging.py)
    try:
        import backend.aggregators as aggregators
    except ImportError:
        aggregators = sys.modules.setdefault("backend.aggregators", ModuleType("backend.aggregators"))

    def removed(*args, **kwargs):
        raise RuntimeError("Removed from the application; not used by the map benchmark")

    added = [name for name in REMOVED_SIMULATORS if not hasattr(aggregators, name)]
    for name in added:
        setattr(aggregators, name, removed)
    module = ModuleType("map_before_"+path.replace("/", "_").replace(".", "_"))
    module.__file__ = str(ROOT/path)
    sys.modules[module.__name__] = module
    try:
        exec(compile(git("show", f"{revision}:{path}"), module.__file__, "exec"), module.__dict__)
    finally:
        for name in added:
            delattr(aggregators, name)
    return module


def summary(samples):
    return dict(median_ms=statistics.median(samples), min_ms=min(samples), max_ms=max(samples), samples_ms=samples)


def result(name, before, after, **extra):
    old, new = summary(before), summary(after)
    return dict(name=name, before=old, after=new, speedup=old["median_ms"]/new["median_ms"], **extra)


CASES = [
    ("First city overview (empty server cache)", 11, "4.3,52,5.5,52.7"),
    ("First visit to next zoom", 10, "3.7,51.6,6.1,53.1"),
    ("First country overview", 7, "-1,49,11,55"),
    ("First Europe overview", 4, "-15,32,35,68"),
    ("Return to city overview", 11, "4.3,52,5.5,52.7"),
]


def make_app(engine, baseline):
    before = old_module(baseline, "backend/views.py")
    before.density_cells = old_module(baseline, "backend/charger_import.py").density_cells
    app = Flask(__name__)
    app.config.update(TESTING=True, **{"station_data.db": SimpleNamespace(engine=engine)})
    app.register_blueprint(before.station_data, url_prefix="/before/stations", name="before_map")
    app.register_blueprint(station_data, url_prefix="/after/stations", name="after_map")

    def reset(variant):
        if variant == "before":
            before._density_cache.clear()
        else:
            app.extensions.pop("map_density", None)

    @app.post("/benchmark/reset/<variant>")
    def reset_route(variant):
        reset(variant)
        return jsonify(ok=True)

    @app.get("/<variant>/scripts/<name>")
    def source(variant, name):
        if name not in {"script.js", "loaders.js", "charger_sites.js", "map_density.js"}:
            return "Unknown module", 404
        content = git("show", f"{baseline}:static/scripts/{name}") if variant == "before" else (ROOT/"static/scripts"/name).read_text(encoding="utf-8")
        return content, 200, {"Content-Type": "application/javascript"}

    @app.get("/marker_icon")
    def icons():
        return jsonify(charge_icon="/images/charger_icon.png", transformer_icon="/images/transformer_icon.png")

    @app.get("/benchmark")
    def page():
        return '''<!doctype html><html><head><meta charset="utf-8">
        <link rel="stylesheet" href="/benchmark/vendor/leaflet.css">
        <link rel="stylesheet" href="/benchmark/vendor/MarkerCluster.css">
        <link rel="stylesheet" href="/benchmark/styles.css">
        <style>#map {position:absolute;left:0;top:0;width:1280px;height:800px;} body {margin:0;}</style>
        <script src="/benchmark/vendor/leaflet.js"></script>
        <script src="/benchmark/vendor/leaflet.markercluster.js"></script></head>
        <body><div id="map"></div><script src="/benchmark/browser.js"></script></body></html>'''

    @app.get("/benchmark/browser.js")
    def browser_script():
        return send_file(ROOT/"scripts/benchmark_map_browser.js", mimetype="application/javascript")

    @app.get("/benchmark/styles.css")
    def styles():
        return send_file(ROOT/"static/css/styles.css", mimetype="text/css")

    @app.get("/benchmark/vendor/<name>")
    def vendor(name):
        return send_file(ROOT/".tmp/map-benchmark/vendor"/Path(name).name)

    return app, reset


def server_benchmark(app, reset, repeats):
    timings = {name: {"before": [], "after": []} for name, _, _ in CASES}
    client = app.test_client()
    for iteration in range(repeats+1):
        values = {}
        for variant in (["before", "after"] if iteration % 2 == 0 else ["after", "before"]):
            reset(variant)
            values[variant] = []
            for name, zoom, bbox in CASES:
                start = time.perf_counter_ns()
                response = client.get(f"/{variant}/stations/density?zoom={zoom}&bbox={bbox}")
                elapsed = (time.perf_counter_ns()-start)/1e6
                assert response.status_code == 200
                values[variant].append(response.json)
                if iteration:
                    timings[name][variant].append(elapsed)
        assert values["before"] == values["after"], "Density counts or representative charger positions changed"
    return [result("Server: "+name, **times) for name, times in timings.items()]


VENDOR = {
    "leaflet.js": "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
    "leaflet.css": "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
    "leaflet.markercluster.js": "https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js",
    "MarkerCluster.css": "https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css",
}


def browser_benchmark(app, repeats, chrome, work):
    assets = ROOT/".tmp/map-benchmark/vendor"
    assets.mkdir(parents=True, exist_ok=True)
    for name, url in VENDOR.items():
        path = assets/name
        if not path.exists():
            with urlopen(url, timeout=30) as response:
                path.write_bytes(response.read())

    class QuietHandler(WSGIRequestHandler):
        def log_request(self, *args, **kwargs):
            pass

    server = make_server("127.0.0.1", 0, app, request_handler=QuietHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    spec = work/"spec.json"
    spec.write_text(json.dumps(dict(base=f"http://127.0.0.1:{server.server_port}", work=str(work), chrome=str(chrome), repeats=repeats)), encoding="utf-8")
    try:
        completed = subprocess.run(["node", "--experimental-websocket", "--preserve-symlinks", "--preserve-symlinks-main",
            str(ROOT/"scripts/benchmark_map_chrome.mjs"), str(spec)], cwd=ROOT, capture_output=True, encoding="utf-8", timeout=600)
        if completed.returncode:
            raise RuntimeError(completed.stderr)
        raw = json.loads(completed.stdout)
    finally:
        server.shutdown()
        thread.join(timeout=5)
    rows = []
    for index, record in enumerate(raw["runs"][0]["before"]):
        samples = {variant: [pair[variant][index]["ms"] for pair in raw["runs"]] for variant in ("before", "after")}
        rows.append(result("Browser: "+record["name"], **samples,
            work={variant: {key: raw["runs"][-1][variant][index][key] for key in
                 ("requests", "bytes", "created", "markers", "dom_markers")} for variant in ("before", "after")},
            longest_tasks_ms={variant: [pair[variant][index]["longest_task_ms"] for pair in raw["runs"]] for variant in ("before", "after")}))
    # Keep timings and verification hashes rather than thousands of coordinates.
    for pair in raw["runs"]:
        for records in pair.values():
            for row in records:
                row["cells_sha256"] = hashlib.sha256(json.dumps(row.pop("cells")).encode()).hexdigest()
    return rows, raw


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    lines = ["# Charger map speed comparison", "",
        f"Baseline `{report['baseline']}`; {report['points']:,} charging points; {report['repeats']} measured repeats after one discarded warmup.",
        "", "Database opened read-only. Server caches reset before each zoom sequence; imports and OS disk cache are warm.",
        "When enabled, browser cases use real headless Chrome, Leaflet 1.9.4 and MarkerCluster 1.5.3 at 1280 x 800.",
        "They include local HTTP, JSON parsing, clustering, DOM updates and two paint frames. Basemap tiles and zoom animation are excluded.",
        "All returned cells and displayed charger counts/locations are checked against the original implementation.", "",
        "| Comparison | Before median (ms) | After median (ms) | Speedup |", "|---|---:|---:|---:|"]
    for row in report["results"]:
        lines.append(f"| {row['name']} | {row['before']['median_ms']:.2f} | {row['after']['median_ms']:.2f} | {row['speedup']:.2f}x |")
    lines += ["", "## Browser work per action", "", "| Action | Requests before / after | New markers before / after |", "|---|---:|---:|"]
    for row in report["results"]:
        if "work" in row:
            a, b = row["work"]["before"], row["work"]["after"]
            lines.append(f"| {row['name']} | {a['requests']} / {b['requests']} | {a['created']} / {b['created']} |")
    lines += ["", "These timings describe this dataset and machine, not remote production latency. Speedups are not multiplied together or enforced in tests.",
              "Browser viewport cache lifetime is 30 seconds and capacity is 16 views. Server snapshots invalidate on database/WAL/manifest changes.",
              "Raw samples, browser version, data stamps and source hashes are in the adjacent JSON file."]
    path.with_suffix(".md").write_text("\n".join(lines)+"\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT/"instance/default.sqlite")
    parser.add_argument("--baseline", default="4ba8f16")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--chrome", type=Path, default=Path("C:/Program Files/Google/Chrome/Application/chrome.exe"))
    parser.add_argument("--output", type=Path, default=ROOT/"reports/map_speed_comparison.json")
    args = parser.parse_args()
    if args.repeats < 1 or not args.database.is_file():
        parser.error("Use a positive repeat count and an existing charger database")
    database = args.database.resolve()
    revision = git("rev-parse", args.baseline).strip()
    # SQLite URI mode=ro guarantees the original application data is untouched.
    engine = create_engine(f"sqlite:///file:{database.as_posix()}?mode=ro&uri=true")
    stamp = lambda: [(path.name, path.stat().st_size, path.stat().st_mtime_ns) for path in
                     (database, Path(str(database)+"-wal")) if path.exists()]
    initial_stamp = stamp()
    sources = ["backend/charger_import.py", "backend/map_density.py", "backend/views.py", "static/scripts/map_density.js",
               "static/scripts/loaders.js", "static/scripts/script.js", "scripts/benchmark_map.py",
               "scripts/benchmark_map_browser.js", "scripts/benchmark_map_chrome.mjs"]
    hashes = {path: hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in sources}
    try:
        with engine.connect() as db:
            points = db.exec_driver_sql("SELECT COUNT(*) FROM charging_points").scalar_one()
        app, reset = make_app(engine, revision)
        results = server_benchmark(app, reset, args.repeats)
        browser = None
        for row in results:
            print(f"{row['name']}: {row['before']['median_ms']:.1f} -> {row['after']['median_ms']:.1f} ms", flush=True)
        if args.browser:
            if not args.chrome.is_file():
                parser.error("Chrome not found; supply --chrome with its executable path")
            with tempfile.TemporaryDirectory(prefix="epiot-map-", ignore_cleanup_errors=True) as folder:
                browser_rows, browser = browser_benchmark(app, args.repeats, args.chrome, Path(folder))
            results.extend(browser_rows)
        assert stamp() == initial_stamp, "Database changed during timing; rerun on a stable dataset"
        report = dict(baseline=revision, points=points, repeats=args.repeats, results=results, browser=browser,
                      database=database.name, database_stamps=initial_stamp, source_sha256=hashes,
                      generated_at=datetime.now(timezone.utc).isoformat(), platform=platform.platform())
        write_report(args.output, report)
        print(f"Saved {args.output} and {args.output.with_suffix('.md')}", flush=True)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
