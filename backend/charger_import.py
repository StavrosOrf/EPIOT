"""Write parsed charger sources into the locations/columns/charging_points tables.

Imported rows carry `source` and `external_id`, so a re-import replaces one
source without touching the others or the untagged Amsterdam pilot chargers
(which own the observed sessions, forecasts and grid connections).

IDs are stable across re-imports: an external ID keeps the integer ID it got
the first time, and new ones are numbered from a per-source base far above the
pilot IDs and below JavaScript's 2**53 limit.
"""

from collections import defaultdict
from datetime import datetime, timezone
import math

from backend.charger_sources import COUNTRY_NAMES, REGIONS, LEGACY_SOURCE, plausible

ID_BASE = {"ndw": 1_000_000_000_000, "bnetza": 2_000_000_000_000, "osm": 3_000_000_000_000,
           "bfe": 4_000_000_000_000, "irve": 5_000_000_000_000, "digitraffic": 6_000_000_000_000}
TABLES = ("locations", "columns", "charging_points")


def tagged_schema(connection):
    columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(charging_points)")}
    return {"source", "external_id"} <= columns


class IdMap:
    def __init__(self, connection, table, source):
        self.known = dict(connection.exec_driver_sql(
            f"SELECT external_id, id FROM {table} WHERE source = ?", (source,)).all())
        self.next = max([ID_BASE[source], *self.known.values()]) + 1

    def __call__(self, key):
        if key not in self.known:
            self.known[key] = self.next
            self.next += 1
        return self.known[key]


class NearbyIndex:
    """Grid lookup of points within `metres` of a set of coordinates."""

    def __init__(self, coordinates, metres):
        self.cell = metres/111_320
        self.metres = metres
        self.cells = defaultdict(list)
        for lat, lon in coordinates:
            self.cells[self._key(lat, lon)].append((lat, lon))

    def _key(self, lat, lon):
        return int(lat//self.cell), int(lon//self.cell)

    def near(self, lat, lon):
        row, col = self._key(lat, lon)
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                for other_lat, other_lon in self.cells.get((row+dr, col+dc), ()):
                    dy = (lat-other_lat)*111_320
                    dx = (lon-other_lon)*111_320*math.cos(math.radians(lat))
                    if dx*dx+dy*dy <= self.metres**2:
                        return True
        return False


def pilot_index(connection, metres):
    rows = connection.exec_driver_sql(
        "SELECT l.latitude, l.longitude FROM columns c JOIN locations l ON l.id = c.location_id "
        "WHERE (c.source IS NULL OR c.source = ?) AND l.latitude IS NOT NULL", (LEGACY_SOURCE,)).all()
    return NearbyIndex(rows, metres)


def operator_ids(connection):
    rows = connection.exec_driver_sql("SELECT id, name FROM operators").all()
    by_name = {name.strip().lower(): id_ for id_, name in rows if name}
    state = {"next": max([0, *(id_ for id_, _ in rows)]) + 1, "new": []}

    def lookup(name):
        name = (name or "(Unknown Operator)").strip()
        key = name.lower()
        if key not in by_name:
            by_name[key] = state["next"]
            state["new"].append((state["next"], name))
            state["next"] += 1
        return by_name[key]

    return lookup, state


def delete_source(connection, source):
    connection.exec_driver_sql(
        "DELETE FROM grid_connections WHERE column_id IN (SELECT id FROM columns WHERE source = ?)", (source,))
    for table in reversed(TABLES):
        connection.exec_driver_sql(f"DELETE FROM {table} WHERE source = ?", (source,))


def pilot_area(path):
    """Membership test for the pilot's neighbourhood atlas (Amsterdam), or None."""
    from pathlib import Path
    if not Path(path).exists():
        return None
    import geopandas as gpd
    from shapely import contains_xy
    area = gpd.read_file(path, columns=["buurtcode"]).to_crs(4326).union_all()
    return lambda lat, lon: bool(contains_xy(area, lon, lat))


def import_source(connection, source, sites, *, dedupe_metres=30., exclude=None, countries=None, with_geometry=True):
    """Replace one source's rows with `sites`; returns counts for the manifest.

    `exclude(lat, lon)` skips sites in an area another dataset already covers,
    such as the Amsterdam pilot, whose positions are too coarse to match one by one.
    """
    if not tagged_schema(connection):
        raise RuntimeError("The database lacks source columns. Run: uv run flask --app app db upgrade")
    ids = {table: IdMap(connection, table, source) for table in TABLES}
    pilot = pilot_index(connection, dedupe_metres) if dedupe_metres else None
    operator, operators = operator_ids(connection)

    locations, columns, points = {}, [], []
    skipped = repeated = excluded = misplaced = uncovered = 0
    site_keys, point_keys = set(), set()
    for site in sites:
        if not plausible(site.country, site.lat, site.lon):  # placeholder or foreign coordinates
            misplaced += 1
            continue
        if countries and site.country not in countries:
            # A station abroad that the feed happens to list (e.g. Madrid in the
            # French register): the country is not covered, so leave it out
            uncovered += 1
            continue
        if exclude and exclude(site.lat, site.lon):
            excluded += 1
            continue
        if pilot and pilot.near(site.lat, site.lon):
            skipped += 1
            continue
        if site.key in site_keys:  # feeds occasionally list a site twice
            repeated += 1
            continue
        site_keys.add(site.key)
        group = site.group or site.key
        if group not in locations:
            locations[group] = (ids["locations"](group), site.street or site.name, None, site.city, site.postcode,
                                COUNTRY_NAMES.get(site.country, site.country), site.lat, site.lon, source, group)
        column_id = ids["columns"](site.key)
        columns.append((column_id, operator(site.operator), locations[group][0], source, site.key))
        for number, point in enumerate(site.points, 1):
            # Feeds repeat EVSE IDs (or omit them); qualify until the key is unique
            key = point.key or f"{site.key}#{number}"
            if key in point_keys:
                key = f"{site.key}/{key}"
            suffix = 2
            while key in point_keys:
                key, suffix = f"{site.key}/{point.key}~{suffix}", suffix + 1
            point_keys.add(key)
            points.append((ids["charging_points"](key), column_id, point.kind,
                           round(point.power_kw, 2) if point.power_kw else None, source, key))

    delete_source(connection, source)
    if operators["new"]:
        connection.exec_driver_sql("INSERT INTO operators (id, name) VALUES (?, ?)", operators["new"])
    for statement, rows in [
            ("INSERT INTO locations (id, street, supplement, postal_name, zip_code, country, latitude, longitude, "
             "source, external_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", list(locations.values())),
            ("INSERT INTO columns (id, operator_id, location_id, source, external_id) VALUES (?, ?, ?, ?, ?)", columns),
            ("INSERT INTO charging_points (id, column_id, type, power, source, external_id) "
             "VALUES (?, ?, ?, ?, ?, ?)", points)]:
        if rows:
            connection.exec_driver_sql(statement, rows)
    if with_geometry:
        connection.exec_driver_sql(
            "UPDATE locations SET geom = MakePoint(longitude, latitude, 4326) WHERE source = ?", (source,))
    return dict(locations=len(locations), sites=len(columns), points=len(points), skipped_pilot_area=excluded, skipped_pilot_duplicates=skipped,
                skipped_repeated_sites=repeated, skipped_bad_position=misplaced, skipped_outside_coverage=uncovered, operators_added=len(operators["new"]),
                imported_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))


def region_counts(connection):
    """Charging sites and points per search region, across all sources."""
    counts = {}
    for region in REGIONS:
        south, west, north, east = region.bbox
        sites, points = connection.exec_driver_sql(
            "SELECT COUNT(DISTINCT c.id), COUNT(cp.id) FROM locations l JOIN columns c ON c.location_id = l.id "
            "JOIN charging_points cp ON cp.column_id = c.id "
            "WHERE l.latitude BETWEEN ? AND ? AND l.longitude BETWEEN ? AND ?", (south, north, west, east)).one()
        counts[region.id] = dict(sites=sites, points=points)
    return counts



def cell_degrees(zoom):
    """Grid cell for overview bubbles: about 64 screen pixels at this zoom."""
    return 90/2**zoom


def density_cells(connection, zoom):
    """Charging points per grid cell, all sources: [lat, lon, points, fast, sites].

    The bubble sits on the charging location nearest the cell's mean position.
    The mean itself can fall in the sea or a river between coastal towns or
    river banks.
    """
    import numpy as np
    size = cell_degrees(zoom)
    rows = connection.exec_driver_sql(
        # Unknown power is not fast; a bare SUM would be NULL where no power is known
        "SELECT l.latitude, l.longitude, COUNT(cp.id), SUM(COALESCE(cp.power, 0) >= 50), COUNT(DISTINCT c.id) "
        "FROM charging_points cp JOIN columns c ON c.id = cp.column_id JOIN locations l ON l.id = c.location_id "
        "WHERE l.latitude IS NOT NULL AND l.longitude IS NOT NULL GROUP BY l.id").all()
    if not rows:
        return []
    lat, lon, points, fast, sites = (np.array(column, dtype=float) for column in zip(*rows))
    cell = (np.floor((lat+90)/size).astype(np.int64) << 32) + np.floor((lon+180)/size).astype(np.int64)
    order = np.argsort(cell, kind="stable")
    cells, starts = np.unique(cell[order], return_index=True)
    output = []
    for begin, end in zip(starts, list(starts[1:])+[len(order)]):
        members = order[begin:end]
        weights = points[members]
        mean_lat, mean_lon = np.average(lat[members], weights=weights), np.average(lon[members], weights=weights)
        scale = math.cos(math.radians(mean_lat))
        nearest = members[np.argmin((lat[members]-mean_lat)**2+((lon[members]-mean_lon)*scale)**2)]
        output.append([round(float(lat[nearest]), 5), round(float(lon[nearest]), 5), int(weights.sum()),
                       int(fast[members].sum()), int(sites[members].sum())])
    return output
