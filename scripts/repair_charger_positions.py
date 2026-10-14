"""Apply verified station corrections without reimporting or changing charger IDs."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.charger_positions import CONFIRM_METRES, metres, position_overrides
from backend.charger_sources import COUNTRY_NAMES, load_manifest, save_manifest
from scripts.update_charger_data import engine_for


def repair(database):
    database = Path(database).resolve()
    with sqlite3.connect(database.as_uri()+"?mode=ro", uri=True) as connection:
        changes = []
        for identity, correction in position_overrides().items():
            source, key = identity.split(":", 1)
            for id_, lat, lon in connection.execute(
                    "SELECT id, latitude, longitude FROM locations WHERE source=? AND external_id=?", (source, key)):
                if metres((lat, lon), correction["bad_position"]) <= CONFIRM_METRES:
                    changes.append((id_, correction))
        if not changes:
            return 0
        backup = database.with_name(database.name+".before-position-repair-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")+".bak")
        with sqlite3.connect(backup) as target:
            connection.backup(target)
    engine = engine_for(database)
    try:
        with engine.begin() as connection:
            for id_, correction in changes:
                lat, lon = correction["position"]
                connection.exec_driver_sql(
                    "UPDATE locations SET latitude=?, longitude=?, country=?, geom=MakePoint(?, ?, 4326) WHERE id=?",
                    (lat, lon, COUNTRY_NAMES[correction["country"]], lon, lat, id_))
    finally:
        engine.dispose()
    manifest = load_manifest()
    manifest["position_corrections"] = position_overrides()
    save_manifest(manifest)  # invalidate the server's overview cache
    print(f"Corrected {len(changes)} station(s); backup: {backup}")
    return len(changes)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT/"instance/default.sqlite")
    repair(parser.parse_args().database)
