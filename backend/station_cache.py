"""Tiled, pre-serialised charger features for the map's viewport requests.

A viewport query joins four tables and builds tens of thousands of dicts. Tiles
are read once per data version and kept as JSON fragments, so a pan over known
ground is a few array filters and one string join.
"""

from collections import OrderedDict
import math
from threading import Lock

import numpy as np
from shapely import contains_xy
from shapely.geometry import box
from sqlalchemy import select

TILE_DEGREES = 0.05
MAX_TILES = 900          # about 150 MB at the densest city tiles
MAX_REQUEST_TILES = 400  # larger requests (country views) use the database


class Tile:
    __slots__ = ("lat", "lon", "features")

    def __init__(self, rows):
        self.lat = np.array([row[4] for row in rows], dtype=float)
        self.lon = np.array([row[5] for row in rows], dtype=float)
        import json
        self.features = [json.dumps(feature, separators=(",", ":"), allow_nan=False)
                         for feature in feature_dicts(rows)]


def feature_dicts(rows):
    for r in rows:
        yield {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r[5], r[4]]},
            "properties": {
                "area_code": r[7], "id": r[0], "name": r[6], "power": r[1], "type": r[2], "operator": r[3],
                # Untagged rows are the Amsterdam pilot chargers
                "source": r[8] or "pilot", "city": r[9], "country": r[10],
            },
        }


class StationCache:
    def __init__(self):
        self.lock = Lock()
        self.version = None
        self.tiles = OrderedDict()

    def tile(self, session, statement, Location, version, row, col):
        key = (row, col)
        with self.lock:
            if self.version != version:
                self.version, self.tiles = version, OrderedDict()
            tile = self.tiles.get(key)
            if tile is not None:
                self.tiles.move_to_end(key)
                return tile
        south, west = row * TILE_DEGREES, col * TILE_DEGREES
        rows = session.execute(statement.filter(
            Location.latitude >= south, Location.latitude < south + TILE_DEGREES,
            Location.longitude >= west, Location.longitude < west + TILE_DEGREES)).all()
        tile = Tile(rows)
        with self.lock:
            if self.version == version:
                self.tiles[key] = tile
                while len(self.tiles) > MAX_TILES:
                    self.tiles.popitem(last=False)
        return tile

    def features(self, session, statement, Location, version, geometry):
        """Serialised features inside `geometry`, or None when it spans too many tiles."""
        west, south, east, north = geometry.bounds
        rows = range(math.floor(south / TILE_DEGREES), math.floor(north / TILE_DEGREES) + 1)
        cols = range(math.floor(west / TILE_DEGREES), math.floor(east / TILE_DEGREES) + 1)
        if len(rows) * len(cols) > MAX_REQUEST_TILES:
            return None
        rectangle = geometry.geom_type == "Polygon" and geometry.equals(box(west, south, east, north))
        selected = []
        for row in rows:
            for col in cols:
                tile = self.tile(session, statement, Location, version, row, col)
                if not len(tile.lat):
                    continue
                mask = (tile.lat >= south) & (tile.lat <= north) & (tile.lon >= west) & (tile.lon <= east)
                if not rectangle:
                    mask &= contains_xy(geometry, tile.lon, tile.lat)
                selected.extend(tile.features[i] for i in np.flatnonzero(mask))
        return selected

    def warm(self, session, statement, Location, version, bounds):
        west, south, east, north = bounds
        for row in range(math.floor(south / TILE_DEGREES), math.floor(north / TILE_DEGREES) + 1):
            for col in range(math.floor(west / TILE_DEGREES), math.floor(east / TILE_DEGREES) + 1):
                self.tile(session, statement, Location, version, row, col)
