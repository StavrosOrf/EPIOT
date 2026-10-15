"""Exercise offline reconstruction, data preservation and damaged-bundle handling."""
from contextlib import closing
import gzip
import json
import re
import sqlite3
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import box

from backend.bootstrap_data import (ATLAS_NAME, COUNTRY_TABLES, SHARED_TABLES, PRIORS,
                                    bootstrap, export_snapshots, fields, read_only)
from backend.spatialite import configure_spatialite
from scripts.update_charger_data import engine_for


def migration_head():
    """The revision no other migration builds on, so a new migration needs no edit here."""
    revisions = {}
    for path in (Path(__file__).resolve().parents[1]/"migrations").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        revision = re.search(r'^revision = "(\w+)"', text, re.M)
        parent = re.search(r'^down_revision = (?:"(\w+)"|None)', text, re.M)
        if revision:
            revisions[revision.group(1)] = parent.group(1) if parent else None
    heads = set(revisions) - set(revisions.values())
    assert len(heads) == 1, heads
    return heads.pop()


@pytest.fixture
def snapshots(tmp_path):
    database = tmp_path/"source.sqlite"
    with sqlite3.connect(database) as connection:
        for table in dict.fromkeys((*COUNTRY_TABLES, *SHARED_TABLES)):
            connection.execute(f'CREATE TABLE "{table}" ('+",".join(f'"{name}"' for name in fields(table))+")")
        connection.execute("INSERT INTO operators VALUES (7, 'Shared operator')")
        connection.execute("INSERT INTO operators VALUES (8, 'Legacy unused operator')")
        for id_, country, lat, lon in [(1, "Netherlands", 52.37, 4.89), (2, "Germany", 52.52, 13.405)]:
            connection.execute("INSERT INTO locations(id,country,latitude,longitude,source,external_id) VALUES (?,?,?,?,?,?)",
                               (id_, country, lat, lon, None if id_ == 1 else "bnetza", None if id_ == 1 else "DE1"))
            connection.execute("INSERT INTO columns(id,operator_id,location_id) VALUES (?,?,?)", (id_, 7, id_))
            connection.execute("INSERT INTO charging_points(id,column_id,type,power) VALUES (?,?,'regular',22)", (id_, id_))
        connection.execute("INSERT INTO sessions VALUES (9,1,'2026-10-10 09:00:00','2026-10-10 10:00:00',7.5)")
        connection.execute("INSERT INTO transformers VALUES (5,1,'Middle')")
        connection.execute("INSERT INTO grid_connections VALUES (4,5,1)")
        connection.execute("INSERT INTO power_mixes(id,country_zone,datetime,renewable_percentage,co2_intensity) "
                           "VALUES (3,'NL','2026-10-10 09:00:00',45,200)")
    data = tmp_path/"source-data"
    data.mkdir()
    directory = tmp_path/"seed"
    manifest = export_snapshots(database, directory, data)
    # Small runtime inputs are plain files in seed_data/, not part of the snapshots.
    for name in PRIORS:
        (directory/name).write_text("retained,prior\n1,2\n", encoding="utf-8")
    gpd.GeoDataFrame([dict(buurtcode="test", buurtnaam="Neighbourhood", water="NEE", oppervlakte_land_in_ha=20,
        woningvoorraad=100, aantal_bedrijfsvestigingen=10, aantal_bedrijven_handel_en_horeca=2,
        bevolkingsdichtheid_inwoners_per_km2=4000, geometry=box(4.8, 52.3, 5., 52.4))], crs=4326).to_file(directory/ATLAS_NAME)
    return directory, manifest, database, data


@pytest.fixture
def spatialite_available():
    from geoalchemy2 import load_spatialite
    configure_spatialite()
    with sqlite3.connect(":memory:") as connection:
        try:
            load_spatialite(connection, transaction=True, init_mode="WGS84")
        except sqlite3.OperationalError as exc:
            pytest.skip(f"SpatiaLite is required for the offline bootstrap integration test: {exc}")


def test_country_export_contains_only_its_chargers_and_referenced_data(snapshots):
    directory, manifest, _, _ = snapshots
    assert set(manifest["countries"]) == {"DE", "NL"}
    assert manifest["countries"]["DE"]["tables"]["sessions"] == 0
    assert manifest["countries"]["NL"]["tables"]["sessions"] == 1
    payload = json.loads(gzip.decompress((directory/"NL.json.gz").read_bytes()))
    assert "geom" not in payload["tables"]["locations"]["columns"]
    assert "atlas" not in payload
    assert "priors" not in json.loads(gzip.decompress((directory/"shared.json.gz").read_bytes()))
    assert len(payload["tables"]["grid_connections"]["rows"]) == 1


def test_unchanged_snapshot_files_are_reproducible(snapshots, tmp_path):
    directory, _, database, data = snapshots
    second = tmp_path/"second"
    export_snapshots(database, second, data)
    for path in directory.glob("*.gz"):
        assert path.read_bytes() == (second/path.name).read_bytes()


def test_offline_bootstrap_preserves_ids_sessions_grid_and_geometry(snapshots, tmp_path, spatialite_available):
    directory, _, original, data = snapshots
    target = tmp_path/"fresh/instance/default.sqlite"
    runtime = tmp_path/"fresh/data"
    bootstrap(target, seed_dir=directory, data_dir=runtime)
    with closing(read_only(original)) as before, closing(read_only(target)) as after:
        for table in (*COUNTRY_TABLES, *SHARED_TABLES):
            selected = ",".join(f'"{name}"' for name in fields(table))
            assert before.execute(f'SELECT {selected} FROM "{table}" ORDER BY 1').fetchall() == after.execute(
                f'SELECT {selected} FROM "{table}" ORDER BY 1').fetchall()
        assert after.execute("PRAGMA foreign_key_check").fetchall() == []
        assert after.execute("SELECT version_num FROM alembic_version").fetchone()[0] == migration_head()
    engine = engine_for(target)
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT ST_X(geom), ST_Y(geom) FROM locations WHERE id=1").one() == (4.89, 52.37)
    finally:
        engine.dispose()
    assert not any((runtime/name).exists() for name in (*PRIORS, ATLAS_NAME))
    assert (runtime/"chargers/manifest.json").exists()


def test_one_country_can_be_installed_without_the_others(snapshots, tmp_path, spatialite_available):
    directory, _, _, _ = snapshots
    target = tmp_path/"de.sqlite"
    bootstrap(target, seed_dir=directory, data_dir=tmp_path/"runtime", countries=["DE"])
    with closing(read_only(target)) as connection:
        assert connection.execute("SELECT id FROM charging_points").fetchall() == [(2,)]
        assert connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_corrupt_snapshot_is_rejected_before_writing_runtime_files(snapshots, tmp_path):
    directory, _, _, _ = snapshots
    path = directory/"NL.json.gz"
    path.write_bytes(path.read_bytes()+b"corrupted")
    target, runtime = tmp_path/"new.sqlite", tmp_path/"runtime"
    with pytest.raises(ValueError, match="checksum mismatch"):
        bootstrap(target, seed_dir=directory, data_dir=runtime)
    assert not target.exists() and not runtime.exists()


def test_missing_seed_input_is_rejected_before_writing_runtime_files(snapshots, tmp_path):
    directory, _, _, _ = snapshots
    (directory/ATLAS_NAME).unlink()
    target, runtime = tmp_path/"new.sqlite", tmp_path/"runtime"
    with pytest.raises(ValueError, match=ATLAS_NAME):
        bootstrap(target, seed_dir=directory, data_dir=runtime)
    assert not target.exists() and not runtime.exists()


def test_bootstrap_refuses_to_overwrite_an_existing_database(snapshots, tmp_path):
    target = tmp_path/"existing.sqlite"
    target.write_bytes(b"existing server data")
    with pytest.raises(FileExistsError):
        bootstrap(target, seed_dir=snapshots[0], data_dir=tmp_path/"runtime")
    assert target.read_bytes() == b"existing server data"
