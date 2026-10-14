"""Overview counts, nearest real locations, reuse and data invalidation."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from flask import Flask
import numpy as np
import pytest
from sqlalchemy import create_engine, event

from backend.charger_import import aggregate_density, cell_degrees
from backend.map_density import DensityCache
from backend.views import station_data


def reference(rows, zoom):
    """Independent per-cell calculation, including weighted representative."""
    import math
    groups = {}
    for row in rows:
        key = tuple(np.floor((row[:2] + [90, 180]) / cell_degrees(zoom)).astype(int))
        groups.setdefault(key, []).append(row)
    output = []
    for _, values in sorted(groups.items()):
        values = np.asarray(values)
        lat, lon, points, fast, sites = values.T
        y, x = np.average(lat, weights=points), np.average(lon, weights=points)
        i = np.argmin((lat-y)**2 + ((lon-x)*math.cos(math.radians(y)))**2)
        output.append([round(float(lat[i]), 5), round(float(lon[i]), 5), int(sum(points)), int(sum(fast)), int(sum(sites))])
    return output


@pytest.mark.parametrize("zoom", range(3, 12))
def test_vectorized_density_matches_reference(zoom):
    rng = np.random.default_rng(42)
    rows = np.column_stack((rng.uniform(-70, 70, 8000), rng.uniform(-175, 175, 8000),
                            rng.integers(1, 12, 8000), rng.integers(0, 2, 8000), np.ones(8000)))
    # Exact duplicates, tied nearest representatives, negative coordinates,
    # cell boundaries and fast points must retain the old counts and positions.
    rows = np.concatenate((rows, [[52.1, 4.5, 2, 1, 1], [52.11, 4.51, 2, 0, 1],
                                 [52.1, 4.5, 1, 0, 1], [0, 0, 1, 0, 1]]))
    assert aggregate_density(rows, zoom) == reference(rows, zoom)
    assert aggregate_density(np.empty((0, 5)), zoom) == []


@pytest.fixture
def map_app(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path/'map.sqlite').as_posix()}")
    with engine.begin() as db:
        for statement in [
            "CREATE TABLE locations(id INTEGER PRIMARY KEY,latitude REAL,longitude REAL)",
            "CREATE TABLE columns(id INTEGER PRIMARY KEY,location_id INTEGER)",
            "CREATE TABLE charging_points(id INTEGER PRIMARY KEY,column_id INTEGER,power REAL)",
            "INSERT INTO locations VALUES(1,52.37,4.9),(2,52.38,4.91),(3,NULL,0)",
            "INSERT INTO columns VALUES(1,1),(2,2),(3,3)",
            "INSERT INTO charging_points VALUES(1,1,11),(2,1,50),(3,2,NULL),(4,3,11)",
        ]:
            db.exec_driver_sql(statement)
    app = Flask(__name__)
    app.config.update(TESTING=True, **{"station_data.db": SimpleNamespace(engine=engine)})
    app.register_blueprint(station_data, url_prefix="/stations")
    scans = []

    @event.listens_for(engine, "before_cursor_execute")
    def count_scan(_connection, _cursor, statement, *args):
        if "GROUP BY l.id" in statement:
            scans.append(statement)

    yield app, engine, scans
    engine.dispose()


def test_snapshot_shared_between_zooms_and_concurrent_requests(map_app):
    _, engine, scans = map_app
    cache = DensityCache()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda zoom: cache.get(engine, "v1", zoom), [11, 10, 9, 11]))
    assert len(scans) == 1
    assert all(sum(row[2] for row in cells) == 3 for cells in results)
    cache.get(engine, "v2", 11)
    assert len(scans) == 2


def test_density_endpoint_reuses_snapshot_and_invalidates_database_edits(map_app):
    app, engine, scans = map_app
    client = app.test_client()
    first = client.get("/stations/density?zoom=11")
    assert sum(row[2] for row in first.json["cells"]) == 3
    assert sum(row[3] for row in first.json["cells"]) == 1
    client.get("/stations/density?zoom=8")
    assert len(scans) == 1
    assert client.get("/stations/density?zoom=11", headers={"If-None-Match": first.headers["ETag"]}).status_code == 304
    with engine.begin() as db:
        db.exec_driver_sql("INSERT INTO charging_points VALUES(5,1,150)")
    changed = client.get("/stations/density?zoom=11")
    assert sum(row[2] for row in changed.json["cells"]) == 4
    assert changed.headers["ETag"] != first.headers["ETag"]
    assert len(scans) == 2
    # A separate application must never reuse this application's cells.
    other = Flask("second-map")
    other.config["station_data.db"] = SimpleNamespace(engine=engine)
    other.register_blueprint(station_data, url_prefix="/stations")
    other.test_client().get("/stations/density?zoom=11")
    assert len(scans) == 3


@pytest.mark.parametrize("query", ["zoom=12", "zoom=no", "zoom=4&bbox=nan,0,1,2",
                                      "zoom=4&bbox=0,0,inf,2", "zoom=4&bbox=2,0,1,2", "zoom=4&bbox=0,2,1,1"])
def test_density_rejects_invalid_bounds(map_app, query):
    app, _, scans = map_app
    assert app.test_client().get("/stations/density?"+query).status_code == 400
    assert scans == []


def test_wal_writes_invalidate_overview(map_app):
    app, engine, scans = map_app
    with engine.connect() as db:
        db.exec_driver_sql("PRAGMA journal_mode=WAL")
        client = app.test_client()
        first = client.get("/stations/density?zoom=11")
        db.exec_driver_sql("UPDATE charging_points SET power=150 WHERE id=1")
        db.commit()
        second = client.get("/stations/density?zoom=11")
        assert sum(row[3] for row in first.json["cells"]) == 1
        assert sum(row[3] for row in second.json["cells"]) == 2
        assert len(scans) == 2


def test_comparison_runner_against_original_code(map_app, tmp_path):
    """Small executable before/after comparison; assert equivalence, not speed."""
    import json
    from pathlib import Path
    import subprocess
    import sys
    _, engine, _ = map_app
    root = Path(__file__).resolve().parents[1]
    output = tmp_path/"comparison.json"
    completed = subprocess.run([sys.executable, str(root/"scripts/benchmark_map.py"),
        "--database", engine.url.database, "--repeats", "2", "--output", str(output)],
        cwd=root, capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stdout+completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["points"] == 4
    assert len(report["results"]) == 5
    for row in report["results"]:
        for variant in ("before", "after"):
            assert len(row[variant]["samples_ms"]) == 2
            assert row[variant]["min_ms"] > 0
