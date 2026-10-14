"""App-local overview snapshots, shared across zooms and concurrent requests."""

from pathlib import Path
from threading import Lock

from backend.analysis_versions import digest, file_stamp
from backend.charger_import import aggregate_density, density_locations
from backend.charger_sources import MANIFEST


class DensityCache:
    def __init__(self):
        self.lock = Lock()
        self.version = None
        self.locations = None
        self.zooms = {}

    def get(self, engine, version, zoom):
        # A single builder prevents simultaneous map requests from repeating
        # the full database scan. Publish only fully built snapshots.
        with self.lock:
            if self.version != version:
                with engine.connect() as connection:
                    locations = density_locations(connection)
                self.locations, self.zooms, self.version = locations, {}, version
            if zoom not in self.zooms:
                self.zooms[zoom] = aggregate_density(self.locations, zoom)
            return self.zooms[zoom]


def density_version(app, engine):
    # Include database identity and WAL writes, not only the import manifest:
    # edits and separate Flask apps must never inherit another dataset's cells.
    stamps = [str(engine.url), file_stamp(MANIFEST), app.config.get("ANALYSIS_DATA_REVISION", "")]
    database = engine.url.database
    if database and database != ":memory:":
        path = Path(database.removeprefix("file:"))
        stamps.extend((file_stamp(path), file_stamp(str(path) + "-wal")))
    return digest(stamps)
