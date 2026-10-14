"""Lossless country snapshots for offline installation; geometry is rebuilt."""

from contextlib import closing
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile

from backend.charger_sources import COUNTRY_NAMES, ROOT, SOURCES, plausible
from backend.models import Model

FORMAT_VERSION = 2
SEED_DIR = ROOT / "seed_data"
COUNTRY_TABLES = ("operators", "locations", "columns", "charging_points", "transformers",
                  "grid_connections", "power_mixes", "sessions", "forecast_hourly", "forecast_sessions")
SHARED_TABLES = ("operators", "gamma_distributions", "forecast_runs")
# Small runtime inputs kept as plain files in seed_data/ and read from there directly.
PRIORS = ("distribution-of-arrival.csv", "distribution-of-arrival-weekend.csv",
          "distribution-of-connection-time.csv", "distribution-of-energy-demand.csv")
ATLAS_NAME = "wijkenbuurten_2022_v2_amsterdam.gpkg"


def fields(table):
    return [column.name for column in Model.metadata.tables[table].columns if column.name != "geom"]


def read_only(path):
    return sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro", uri=True)


def snapshot_table(connection, table, condition="1", params=()):
    columns = fields(table)
    selected = ",".join(f'"{name}"' for name in columns)
    primary = ",".join(f'"{column.name}"' for column in Model.metadata.tables[table].primary_key)
    return dict(columns=columns, rows=connection.execute(
        f'SELECT {selected} FROM "{table}" WHERE {condition} ORDER BY {primary}', params).fetchall())


def write_snapshot(directory, name, payload):
    path = directory / name
    # Unchanged snapshots are byte-for-byte stable: no gzip timestamp/name.
    with path.open("wb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed:
        compressed.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))
    return dict(file=name, bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                tables={table: len(data["rows"]) for table, data in payload["tables"].items()})


def export_snapshots(database, output=SEED_DIR, data_dir=ROOT/"instance", grid_cache=None):
    output, data_dir, database = Path(output), Path(data_dir), Path(database)
    output.mkdir(parents=True, exist_ok=True)
    with closing(read_only(database)) as connection:
        connection.execute("BEGIN")  # one consistent database snapshot
        inverse = {name: code for code, name in COUNTRY_NAMES.items()}
        assignments = []
        for id_, country, lat, lon in connection.execute("SELECT id,country,latitude,longitude FROM locations ORDER BY id"):
            code = inverse.get(country)
            if code is None and plausible("NL", lat, lon):
                # Untagged Liander locations and a mislabelled legacy Amsterdam
                # row are packaged in NL, keeping their original fields/IDs.
                code = "NL"
            if code is None:
                raise ValueError(f"Location {id_} has an unsupported country: {country}")
            assignments.append((id_, code))
        connection.execute("CREATE TEMP TABLE location_country (id INTEGER PRIMARY KEY, country TEXT NOT NULL)")
        connection.executemany("INSERT INTO location_country VALUES (?,?)", assignments)
        countries = sorted({code for _, code in assignments})
        manifest = dict(format_version=FORMAT_VERSION, created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        countries={}, sources={key: vars(value) for key, value in SOURCES.items()},
                        omissions=["raw supplier downloads", "live occupancy snapshots", "rebuildable scenario and hourly caches"],
                        total_rows={table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                                    for table in (*COUNTRY_TABLES, *SHARED_TABLES)})
        manifest_path = data_dir/"chargers/manifest.json"
        provenance = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        shared = dict(format_version=FORMAT_VERSION, country=None,
                      tables={table: snapshot_table(connection, table,
                          "id NOT IN (SELECT operator_id FROM columns)" if table == "operators" else "1")
                          for table in SHARED_TABLES},
                      charger_manifest=provenance)
        manifest["shared"] = write_snapshot(output, "shared.json.gz", shared)
        locs = "SELECT id FROM location_country WHERE country=?"
        cols = f"SELECT id FROM columns WHERE location_id IN ({locs})"
        points = f"SELECT id FROM charging_points WHERE column_id IN ({cols})"
        filters = dict(locations=f"id IN ({locs})", columns=f"location_id IN ({locs})",
            operators=f"id IN (SELECT operator_id FROM columns WHERE id IN ({cols}))",
            charging_points=f"column_id IN ({cols})", transformers=f"location_id IN ({locs})",
            grid_connections=f"column_id IN ({cols})", sessions=f"cp_id IN ({points})",
            power_mixes="country_zone=?", forecast_hourly=f"cp_id IN ({points})", forecast_sessions=f"cp_id IN ({points})")
        grid_cache = Path(grid_cache) if grid_cache else database.parent/"grid_data.sqlite"
        for country in countries:
            payload = dict(format_version=FORMAT_VERSION, country=country,
                tables={table: snapshot_table(connection, table, filters[table], (country,)) for table in COUNTRY_TABLES})
            if grid_cache.exists():
                from backend.grid_data import GridStore
                payload["grid_observations"] = [hour.to_dict() for hour in GridStore(grid_cache).read(zone=country, observations=True)]
            manifest["countries"][country] = write_snapshot(output, f"{country}.json.gz", payload)
        for table in (*COUNTRY_TABLES, *SHARED_TABLES):
            if table == "operators":  # referenced in multiple countries
                continue
            exported = manifest["shared"]["tables"].get(table, 0)+sum(item["tables"].get(table, 0) for item in manifest["countries"].values())
            if exported != manifest["total_rows"][table]:
                raise ValueError(f"Incomplete export of {table}: {exported} / {manifest['total_rows'][table]}")
    (output/"manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return manifest


def read_snapshot(directory, metadata, *, country):
    expected = "shared.json.gz" if country is None else f"{country}.json.gz"
    if metadata["file"] != expected:
        raise ValueError("Unexpected snapshot filename")
    raw = (Path(directory)/expected).read_bytes()
    if len(raw) != metadata["bytes"] or hashlib.sha256(raw).hexdigest() != metadata["sha256"]:
        raise ValueError(f"Snapshot checksum mismatch: {expected}")
    payload = json.loads(gzip.decompress(raw))
    if payload.get("format_version") != FORMAT_VERSION or payload.get("country") != country:
        raise ValueError(f"Unsupported snapshot format/country: {expected}")
    required = SHARED_TABLES if country is None else COUNTRY_TABLES
    if set(payload["tables"]) != set(required):
        raise ValueError(f"Invalid table set: {expected}")
    for table, data in payload["tables"].items():
        if data["columns"] != fields(table) or len(data["rows"]) != metadata["tables"][table]:
            raise ValueError(f"Invalid schema/count for {table} in {expected}")
        if any(len(row) != len(data["columns"]) for row in data["rows"]):
            raise ValueError(f"Invalid row length for {table}")
    return payload


def migrate_database(path):
    """Run the app's Flask-Alembic migrations with SpatiaLite."""
    from flask import Flask
    from flask_alembic import Alembic
    from flask_sqlalchemy_lite import SQLAlchemy
    from geoalchemy2 import load_spatialite
    from sqlalchemy import event
    from backend.spatialite import configure_spatialite
    configure_spatialite()
    application = Flask(__name__)
    application.config["SQLALCHEMY_ENGINES"] = {"default": f"sqlite:///{Path(path).resolve().as_posix()}"}
    application.config["ALEMBIC"] = {"script_location": str(ROOT/"migrations")}
    db = SQLAlchemy(application)
    alembic = Alembic(application, metadatas=Model.metadata)
    with application.app_context():
        event.listen(db.engine, "connect", lambda connection, _: load_spatialite(connection, transaction=True, init_mode="WGS84"))
        try:
            alembic.upgrade()
        finally:
            db.engine.dispose()


def insert_tables(connection, tables):
    # Restore parents before children regardless of JSON object key order.
    for table in dict.fromkeys((*SHARED_TABLES, *COUNTRY_TABLES)):
        if table not in tables:
            continue
        data = tables[table]
        if not data["rows"]:
            continue
        columns = ",".join(f'"{name}"' for name in data["columns"])
        placeholders = ",".join("?" for _ in data["columns"])
        if table == "operators":
            for id_, name in data["rows"]:
                existing = connection.exec_driver_sql("SELECT name FROM operators WHERE id=?", (id_,)).first()
                if existing and existing[0] != name:
                    raise ValueError(f"Conflicting operator {id_}")
            suffix = " ON CONFLICT(id) DO NOTHING"
        else:
            suffix = ""
        connection.exec_driver_sql(f'INSERT INTO "{table}" ({columns}) VALUES ({placeholders})'+suffix,
                                   [tuple(row) for row in data["rows"]])


def bootstrap(database, *, seed_dir=SEED_DIR, data_dir=ROOT/"instance", countries=None):
    """Build a new database offline; refuse to overwrite an existing database."""
    database, seed_dir, data_dir = Path(database).resolve(), Path(seed_dir), Path(data_dir)
    if database.exists():
        raise FileExistsError(f"Database already exists: {database}. Use --database with a new filename.")
    manifest = json.loads((seed_dir/"manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format_version") != FORMAT_VERSION:
        raise ValueError("Unsupported bootstrap manifest version")
    selected = sorted(set(countries or manifest["countries"]))
    if not selected or any(code not in manifest["countries"] for code in selected):
        raise ValueError("Select country codes listed in seed_data/manifest.json")
    # Check hashes/schema before creating a database or runtime inputs.
    shared = read_snapshot(seed_dir, manifest["shared"], country=None)
    for code in selected:
        read_snapshot(seed_dir, manifest["countries"][code], country=code)
    missing = [name for name in (*PRIORS, ATLAS_NAME) if not (seed_dir/name).is_file()]
    if missing:
        raise ValueError(f"Bootstrap bundle is missing runtime inputs: {', '.join(missing)}")
    database.parent.mkdir(parents=True, exist_ok=True)
    from scripts.update_charger_data import engine_for
    from backend.charger_import import region_counts
    from backend.grid_data import GridHour, GridStore
    with tempfile.TemporaryDirectory(prefix="epiot-bootstrap-", dir=database.parent) as staging:
        staging = Path(staging)
        staged_db = staging/"default.sqlite"
        migrate_database(staged_db)
        engine = engine_for(staged_db)
        observations = []
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                insert_tables(connection, shared["tables"])
                for code in selected:
                    payload = read_snapshot(seed_dir, manifest["countries"][code], country=code)
                    insert_tables(connection, payload["tables"])
                    observations.append((code, payload.get("grid_observations", [])))
                connection.exec_driver_sql("UPDATE locations SET geom=MakePoint(longitude,latitude,4326) "
                                           "WHERE longitude IS NOT NULL AND latitude IS NOT NULL")
                if connection.exec_driver_sql("PRAGMA foreign_key_check").all():
                    raise ValueError("Bootstrap contains broken foreign keys")
                for table, column, parent in [("transformers", "location_id", "locations"),
                        ("grid_connections", "column_id", "columns"), ("grid_connections", "transformer_id", "transformers")]:
                    count = connection.exec_driver_sql(f'SELECT COUNT(*) FROM "{table}" t LEFT JOIN "{parent}" p '
                        f'ON p.id=t."{column}" WHERE p.id IS NULL').scalar_one()
                    if count:
                        raise ValueError(f"Bootstrap contains {count} broken {table}.{column} references")
                counts = region_counts(connection)
                imports = {source: dict(sites=connection.exec_driver_sql("SELECT COUNT(*) FROM columns WHERE source=?", (source,)).scalar_one(),
                    points=connection.exec_driver_sql("SELECT COUNT(*) FROM charging_points WHERE source=?", (source,)).scalar_one(),
                    imported_at=manifest["created_at"]) for source in SOURCES}
        finally:
            engine.dispose()
        runtime = staging/"runtime"
        runtime.mkdir()
        for code, rows in observations:
            if rows:
                hours = [GridHour.from_dict(row) for row in rows]
                store = GridStore(staging/"grid_data.sqlite")
                store.save(hours, zone=code, observations=True)
                store.save(hours, zone=code)
        charger_manifest = dict(shared.get("charger_manifest", {}))
        charger_manifest.update(regions=counts, imports=imports, bootstrap=dict(countries=selected,
                                format_version=FORMAT_VERSION, snapshot_date=manifest["created_at"]))
        (runtime/"chargers").mkdir()
        (runtime/"chargers/manifest.json").write_text(json.dumps(charger_manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        # Publish runtime files only after all migration/import checks succeed.
        for path in runtime.rglob("*"):
            if path.is_file():
                target = data_dir/path.relative_to(runtime)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
        if (staging/"grid_data.sqlite").exists() and not (database.parent/"grid_data.sqlite").exists():
            shutil.copyfile(staging/"grid_data.sqlite", database.parent/"grid_data.sqlite")
        # Reserve the name exclusively, then publish the completed database
        # with a rename. This avoids a second large copy and partial DB files.
        with database.open("xb"):
            pass
        try:
            staged_db.replace(database)
        except OSError:
            database.unlink(missing_ok=True)  # remove only our empty reservation
            raise
    return dict(database=str(database), countries=selected, regions=counts)
