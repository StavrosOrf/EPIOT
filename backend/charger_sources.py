"""Open charger-location sources: registry, downloads and parsing.

Each source is parsed into the same `Site`/`Point` records, which
`backend.charger_import` writes into the existing locations/columns/
charging_points tables. Nothing here touches the database.

Raw files live under data/chargers/raw/<source>/ and are described in
data/chargers/manifest.json; see docs/charger_sources.md.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import csv
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import re
import time

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data/chargers"
RAW_DIR = DATA_DIR / "raw"
MANIFEST = DATA_DIR / "manifest.json"
USER_AGENT = "EPIOT-Drive2X/1.0 (charger-location research)"


@dataclass(frozen=True)
class Source:
    id: str
    label: str
    publisher: str
    licence: str
    url: str
    countries: tuple


SOURCES = {
    "ndw": Source("ndw", "NDW DOT-NL", "Nationaal Dataportaal Wegverkeer (NDW)",
                  "Open data, free of charge (NDW terms)", "https://docs.ndw.nu/en/faq/DOT-NL/", ("NL",)),
    "bnetza": Source("bnetza", "Ladesäulenregister", "Bundesnetzagentur",
                     "Open data (Bundesnetzagentur terms)",
                     "https://www.bundesnetzagentur.de/DE/Fachthemen/ElektrizitaetundGas/E-Mobilitaet/start.html", ("DE",)),
    "osm": Source("osm", "OpenStreetMap", "OpenStreetMap contributors", "ODbL 1.0",
                  "https://www.openstreetmap.org/copyright", ("PT", "IT", "GB")),
    "bfe": Source("bfe", "ich-tanke-strom.ch", "Swiss Federal Office of Energy (BFE)",
                  "Open use, source must be credited (opendata.swiss)",
                  "https://opendata.swiss/en/dataset/ladestationen", ("CH", "LI")),
    "irve": Source("irve", "Base nationale des IRVE", "data.gouv.fr (Etalab) consolidation of operator data",
                   "Licence Ouverte / Open Licence 2.0",
                   "https://www.data.gouv.fr/datasets/base-nationale-des-irve-data-gouv-infrastructures-de-recharge-pour-vehicules-electriques-donnees-statiques",
                   ("FR",)),
    "digitraffic": Source("digitraffic", "Digitraffic AFIR", "Fintraffic (Finnish national access point)", "CC BY 4.0",
                          "https://www.digitraffic.fi/en/road-traffic/afir/", ("FI",)),
}
# Chargers loaded by backend.loaders.load_ams_data before sources were tagged.
LEGACY_SOURCE = "pilot"


@dataclass(frozen=True)
class Region:
    """A place offered in location search; `osm` regions are also downloaded."""
    id: str
    name: str
    country: str
    lat: float
    lon: float
    bbox: tuple  # south, west, north, east
    osm: bool = False
    zoom: int = 13


def _box(lat, lon, dlat=0.09, dlon=0.14):
    return (round(lat-dlat, 3), round(lon-dlon, 3), round(lat+dlat, 3), round(lon+dlon, 3))


REGIONS = (
    Region("amsterdam", "Amsterdam", "NL", 52.3731, 4.8926, (52.28, 4.72, 52.43, 5.08)),
    Region("rotterdam", "Rotterdam", "NL", 51.9225, 4.4792, _box(51.9225, 4.4792)),
    Region("the-hague", "The Hague", "NL", 52.0705, 4.3007, _box(52.0705, 4.3007)),
    Region("utrecht", "Utrecht", "NL", 52.0907, 5.1214, _box(52.0907, 5.1214)),
    Region("eindhoven", "Eindhoven", "NL", 51.4416, 5.4697, _box(51.4416, 5.4697)),
    Region("delft", "Delft", "NL", 52.0116, 4.3571, _box(52.0116, 4.3571, .03, .05), zoom=14),
    Region("berlin", "Berlin", "DE", 52.5200, 13.4050, (52.34, 13.09, 52.68, 13.76), zoom=12),
    Region("munich", "Munich", "DE", 48.1372, 11.5756, _box(48.1372, 11.5756)),
    Region("hamburg", "Hamburg", "DE", 53.5511, 9.9937, _box(53.5511, 9.9937, .12, .2), zoom=12),
    Region("frankfurt", "Frankfurt am Main", "DE", 50.1109, 8.6821, _box(50.1109, 8.6821)),
    Region("cologne", "Cologne", "DE", 50.9375, 6.9603, _box(50.9375, 6.9603)),
    Region("lisbon", "Lisbon", "PT", 38.7223, -9.1393, (38.69, -9.23, 38.80, -9.09), osm=True),
    Region("porto", "Porto", "PT", 41.1579, -8.6291, (41.13, -8.69, 41.19, -8.55), osm=True),
    Region("milan", "Milan", "IT", 45.4642, 9.1900, (45.39, 9.04, 45.54, 9.28), osm=True),
    Region("rome", "Rome", "IT", 41.9028, 12.4964, (41.79, 12.37, 41.99, 12.62), osm=True, zoom=12),
    Region("turin", "Turin", "IT", 45.0703, 7.6869, (45.00, 7.58, 45.14, 7.77), osm=True),
    Region("london", "London", "GB", 51.5072, -0.1276, (51.28, -0.51, 51.70, 0.33), osm=True, zoom=12),
    Region("manchester", "Manchester", "GB", 53.4808, -2.2426, (53.40, -2.35, 53.55, -2.13), osm=True),
    Region("zurich", "Zurich", "CH", 47.3769, 8.5417, _box(47.3769, 8.5417, .06, .1)),
    Region("geneva", "Geneva", "CH", 46.2044, 6.1432, _box(46.2044, 6.1432, .05, .08)),
    Region("basel", "Basel", "CH", 47.5596, 7.5886, _box(47.5596, 7.5886, .04, .07), zoom=14),
    Region("bern", "Bern", "CH", 46.9480, 7.4474, _box(46.9480, 7.4474, .04, .07), zoom=14),
    Region("lausanne", "Lausanne", "CH", 46.5197, 6.6323, _box(46.5197, 6.6323, .04, .07), zoom=14),
    Region("paris", "Paris", "FR", 48.8566, 2.3522, (48.80, 2.22, 48.92, 2.47), zoom=12),
    Region("lyon", "Lyon", "FR", 45.7640, 4.8357, _box(45.7640, 4.8357, .06, .1)),
    Region("marseille", "Marseille", "FR", 43.2965, 5.3698, _box(43.2965, 5.3698, .08, .12)),
    Region("toulouse", "Toulouse", "FR", 43.6047, 1.4442, _box(43.6047, 1.4442, .07, .1)),
    Region("nice", "Nice", "FR", 43.7102, 7.2620, _box(43.7102, 7.2620, .04, .08), zoom=14),
    Region("helsinki", "Helsinki", "FI", 60.1699, 24.9384, (60.12, 24.78, 60.30, 25.15), zoom=12),
    Region("tampere", "Tampere", "FI", 61.4978, 23.7610, _box(61.4978, 23.7610, .05, .12)),
)
COUNTRY_NAMES = {"NL": "Netherlands", "DE": "Germany", "PT": "Portugal", "IT": "Italy", "GB": "United Kingdom",
                 "CH": "Switzerland", "FR": "France", "FI": "Finland", "ES": "Spain", "BE": "Belgium",
                 "DK": "Denmark", "LU": "Luxembourg", "AT": "Austria", "LI": "Liechtenstein", "SE": "Sweden",
                 "NO": "Norway", "EE": "Estonia", "PL": "Poland", "CZ": "Czechia"}


@dataclass
class Point:
    key: str
    power_kw: float | None
    kind: str  # "fast" (DC) or "regular" (AC), matching the pilot data


@dataclass
class Site:
    source: str
    key: str
    lat: float
    lon: float
    country: str
    operator: str | None = None
    name: str | None = None
    street: str | None = None
    city: str | None = None
    postcode: str | None = None
    group: str | None = None  # sites sharing a group share one location row
    points: list = field(default_factory=list)
    position_suspect: bool = False  # publisher explicitly marks coordinates incorrect


# Where a site of each country can plausibly be (south, west, north, east).
# Feeds contain placeholders (50, -15) and swapped or foreign coordinates.
EUROPE = (34.0, -11.0, 72.0, 32.0)
COUNTRY_BOUNDS = {
    "NL": [(50.7, 3.2, 53.7, 7.3)],
    "DE": [(47.2, 5.8, 55.1, 15.1)],
    "CH": [(45.8, 5.9, 47.9, 10.5)],
    "FI": [(59.6, 19.0, 70.2, 31.6)],
    # Metropolitan France and Corsica, then the overseas departments and territories
    "FR": [(41.3, -5.3, 51.2, 9.7), (14.3, -61.9, 16.6, -60.7), (17.8, -63.2, 18.2, -62.7), (2.0, -54.7, 5.9, -51.5),
           (-21.5, 55.1, -20.8, 55.9), (-13.1, 44.9, -12.6, 45.4), (46.7, -56.5, 47.2, -56.1),
           (-28.0, -155.0, -7.0, -134.0), (-23.0, 163.0, -19.0, 169.0)],
}


ISO3 = {"NLD": "NL", "DEU": "DE", "CHE": "CH", "FRA": "FR", "FIN": "FI", "AUT": "AT", "ITA": "IT", "BEL": "BE",
        "LUX": "LU", "LIE": "LI", "ESP": "ES", "DNK": "DK", "PRT": "PT", "GBR": "GB", "SWE": "SE", "NOR": "NO",
        "EST": "EE", "POL": "PL", "CZE": "CZ"}


def country_code(value, default=None):
    """'DEU', 'de' or 'DE' -> 'DE'. Feeds list stations abroad, so a site's
    country comes from its address where the feed gives one."""
    value = str(value or "").strip().upper()
    return ISO3.get(value) or (value if len(value) == 2 and value.isalpha() else default)


def plausible(country, lat, lon):
    return any(in_bbox(lat, lon, box) for box in COUNTRY_BOUNDS.get(country, [EUROPE]))


def valid_coordinates(lat, lon):
    return (lat is not None and lon is not None and math.isfinite(lat) and math.isfinite(lon)
            and -90 <= lat <= 90 and -180 <= lon <= 180 and (lat, lon) != (0, 0))


def number(value, decimal_comma=False):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        text = str(value).strip()
        if decimal_comma:
            text = text.replace(".", "").replace(",", ".") if "," in text else text
        try:
            result = float(text)
        except ValueError:
            return None
    return result if math.isfinite(result) else None


def clean(value):
    value = (value or "").strip() if isinstance(value, str) else value
    return value or None


# --------------------------------------------------------------------------
# NDW DOT-NL (OCPI 2.2.1 locations, whole country)
# --------------------------------------------------------------------------

NDW_FILES = {
    "charging_point_locations_ocpi.json.gz": "https://opendata.ndw.nu/charging_point_locations_ocpi.json.gz",
    "charging_point_tariffs_ocpi.json.gz": "https://opendata.ndw.nu/charging_point_tariffs_ocpi.json.gz",
    "charging_point_locations.geojson.gz": "https://opendata.ndw.nu/charging_point_locations.geojson.gz",
}


def connector_kw(connector):
    watts = number(connector.get("max_electric_power"))
    if not watts:
        volts, amps = number(connector.get("max_voltage")), number(connector.get("max_amperage"))
        if volts and amps:
            watts = volts*amps*(3 if connector.get("power_type") == "AC_3_PHASE" else 1)
    return round(watts/1000, 2) if watts else None


def parse_ndw(locations):
    for location in locations:
        coordinates = location.get("coordinates") or {}
        lat, lon = number(coordinates.get("latitude")), number(coordinates.get("longitude"))
        if location.get("publish") is False or not valid_coordinates(lat, lon):
            continue
        points = []
        for evse in location.get("evses") or []:
            if evse.get("status") == "REMOVED":
                continue
            connectors = evse.get("connectors") or []
            powers = [p for p in map(connector_kw, connectors) if p]
            dc = any(c.get("power_type") == "DC" for c in connectors)
            points.append(Point(evse.get("evse_id") or evse.get("uid"), max(powers) if powers else None,
                                "fast" if dc else "regular"))
        if not points:
            continue
        operator = location.get("operator") or location.get("suboperator") or location.get("owner") or {}
        country = country_code(location.get("country"), country_code(location.get("country_code"), "NL"))
        # OCPI location IDs are only unique per party (charge point operator)
        key = f"{country}*{location.get('party_id') or ''}*{location['id']}"
        yield Site("ndw", key, lat, lon, country, clean(operator.get("name")), clean(location.get("name")),
                   clean(location.get("address")), clean(location.get("city")), clean(location.get("postal_code")),
                   points=points)


def read_ndw(directory=RAW_DIR / "ndw"):
    with gzip.open(Path(directory) / "charging_point_locations_ocpi.json.gz", "rt", encoding="utf-8") as handle:
        data = json.load(handle)
    return parse_ndw(data["data"] if isinstance(data, dict) else data)


# --------------------------------------------------------------------------
# Bundesnetzagentur Ladesäulenregister (CSV, whole country)
# --------------------------------------------------------------------------

BNETZA_PAGE = SOURCES["bnetza"].url
BNETZA_FALLBACK = ("https://data.bundesnetzagentur.de/Bundesnetzagentur/DE/Fachthemen/ElektrizitaetundGas/"
                   "E-Mobilitaet/Ladesaeulenregister_BNetzA_2026-09-01.csv")


def bnetza_csv_url(session):
    """The file name carries its publication date, so find the current link."""
    try:
        page = session.get(BNETZA_PAGE, timeout=60).text
        links = re.findall(r'https://data\.bundesnetzagentur\.de/[^"\']+Ladesaeulenregister[^"\']*\.csv', page)
        if links:
            return sorted(set(links))[-1]
    except Exception:  # the fallback below is still a valid download
        pass
    return BNETZA_FALLBACK


def _column(header, *prefixes):
    for name in header:
        if any(name.startswith(prefix) for prefix in prefixes):
            return name
    raise KeyError(f"BNetzA CSV has no column starting with {prefixes}")


def parse_bnetza(text):
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines[:50]) if line.startswith("Ladeeinrichtungs-ID"))
    reader = csv.DictReader(lines[start:], delimiter=";")
    header = reader.fieldnames
    lat_key, lon_key = _column(header, "Breitengrad"), _column(header, "Längengrad", "Laengengrad")
    street_key = _column(header, "Stra")
    for row in reader:
        lat, lon = number(row.get(lat_key), True), number(row.get(lon_key), True)
        if not row.get("Ladeeinrichtungs-ID") or not valid_coordinates(lat, lon):
            continue
        device = row["Ladeeinrichtungs-ID"].strip()
        count = int(number(row.get("Anzahl Ladepunkte")) or 1)
        total = number(row.get("Nennleistung Ladeeinrichtung [kW]"), True)
        points = []
        for i in range(1, max(count, 1)+1):
            plug = row.get(f"Steckertypen{i}") or ""
            power = number(row.get(f"Nennleistung Stecker{i}"), True) or (total/count if total else None)
            points.append(Point(clean(row.get(f"EVSE-ID{i}")) or f"{device}#{i}", power,
                                "fast" if "DC" in plug else "regular"))
        street = " ".join(filter(None, [clean(row.get(street_key)), clean(row.get("Hausnummer"))])) or None
        yield Site("bnetza", device, lat, lon, "DE", clean(row.get("Betreiber")), clean(row.get("Anzeigename (Karte)")),
                   street, clean(row.get("Ort")), clean(row.get("Postleitzahl")),
                   group=f"{lat:.5f},{lon:.5f}", points=points)


def read_bnetza(directory=RAW_DIR / "bnetza"):
    path = Path(directory) / "ladesaeulenregister.csv"
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    return parse_bnetza(text)


# --------------------------------------------------------------------------
# OpenStreetMap via Overpass (city bounding boxes)
# --------------------------------------------------------------------------

OVERPASS_ENDPOINTS = ("https://overpass-api.de/api/interpreter",
                      "https://overpass.kumi.systems/api/interpreter",
                      "https://maps.mail.ru/osm/tools/overpass/api/interpreter")
DC_SOCKETS = ("type2_combo", "chademo", "tesla_supercharger", "tesla_supercharger_ccs", "type1_combo", "gb_dc")


def overpass_query(bbox):
    south, west, north, east = bbox
    return (f'[out:json][timeout:180];nwr["amenity"="charging_station"]'
            f"({south},{west},{north},{east});out center tags;")


def output_kw(value):
    """'22 kW', '7.4kW', '50' or '22 kW;11 kW' -> the largest value in kW."""
    best = None
    for part in re.split(r"[;,/]", str(value or "")):
        match = re.search(r"(\d+(?:\.\d+)?)\s*(kw|kva|w)?", part.strip().lower())
        if match:
            amount = float(match.group(1))/(1000 if match.group(2) == "w" else 1)
            best = amount if best is None else max(best, amount)
    return best


def parse_osm(elements, region):
    for element in elements:
        tags = element.get("tags") or {}
        if tags.get("access") in {"private", "no"}:
            continue
        lat, lon = element.get("lat"), element.get("lon")
        if lat is None and element.get("center"):
            lat, lon = element["center"].get("lat"), element["center"].get("lon")
        if not valid_coordinates(number(lat), number(lon)):
            continue
        sockets = {key.split(":")[1] for key in tags if key.startswith("socket:") and key.count(":") == 1}
        outputs = [output_kw(value) for key, value in tags.items()
                   if key.endswith(":output") or key in ("charging_station:output", "maxpower")]
        outputs = [value for value in outputs if value and value < 1000]
        socket_count = sum(int(number(tags[f"socket:{name}"]) or 0) for name in sockets)
        capacity = number(tags.get("capacity") or tags.get("capacity:motorcar") or tags.get("capacity:charging"))
        count = int(min(max(capacity or socket_count or 1, 1), 50))
        kind = "fast" if sockets & set(DC_SOCKETS) else "regular"
        power = max(outputs) if outputs else None
        key = f"{element['type']}/{element['id']}"
        street = " ".join(filter(None, [tags.get("addr:street"), tags.get("addr:housenumber")])) or None
        yield Site("osm", key, float(lat), float(lon), region.country, clean(tags.get("operator") or tags.get("network")),
                   clean(tags.get("name")), street, clean(tags.get("addr:city")) or region.name,
                   clean(tags.get("addr:postcode")), points=[Point(f"{key}#{i}", power, kind) for i in range(1, count+1)])


def read_osm(directory=RAW_DIR / "osm"):
    for region in REGIONS:
        path = Path(directory) / f"{region.id}.json"
        if region.osm and path.exists():
            yield from parse_osm(json.loads(path.read_text(encoding="utf-8")).get("elements", []), region)


# --------------------------------------------------------------------------
# Switzerland: BFE ich-tanke-strom.ch (OICP JSON, whole country)
# --------------------------------------------------------------------------

BFE_FILES = {
    "evse_data.json": "https://data.geo.admin.ch/ch.bfe.ladestellen-elektromobilitaet/data/oicp/ch.bfe.ladestellen-elektromobilitaet.json",
    "evse_status.json": "https://data.geo.admin.ch/ch.bfe.ladestellen-elektromobilitaet/status/oicp/ch.bfe.ladestellen-elektromobilitaet.json",
}


def parse_bfe(data):
    """One OICP record per EVSE; half reuse the EVSE ID as station ID, so a
    site is one operator's EVSEs at one position."""
    sites = {}
    for block in data.get("EVSEData", []):
        operator = clean(block.get("OperatorName")) or clean(block.get("OperatorID"))
        for record in block.get("EVSEDataRecord") or []:
            try:
                lat, lon = map(float, (record.get("GeoCoordinates") or {}).get("Google", "").split())
            except ValueError:
                continue
            if not valid_coordinates(lat, lon) or not record.get("EvseID"):
                continue
            key = f"{block.get('OperatorID')}@{lat:.5f},{lon:.5f}"
            if key not in sites:
                names = record.get("ChargingStationNames") or []
                names = [names] if isinstance(names, dict) else names  # a single name is not always wrapped
                name = next((n.get("value") for n in names if n.get("lang") == "en"), names[0].get("value") if names else None)
                address = record.get("Address") or {}
                street = " ".join(filter(None, [clean(address.get("Street")), clean(address.get("HouseNum"))])) or None
                sites[key] = Site("bfe", key, lat, lon, country_code(address.get("Country"), "CH"), operator, clean(name), street, clean(address.get("City")),
                                  clean(address.get("PostalCode")), group=f"{lat:.5f},{lon:.5f}")
            facilities = record.get("ChargingFacilities") or []
            powers = [p for p in (number(f.get("power")) for f in facilities) if p]
            dc = any(f.get("powertype") == "DC" for f in facilities)
            sites[key].points.append(Point(record["EvseID"], max(powers) if powers else None, "fast" if dc else "regular"))
    return iter(sites.values())


def read_bfe(directory=RAW_DIR / "bfe"):
    return parse_bfe(json.loads((Path(directory) / "evse_data.json").read_text(encoding="utf-8")))


# --------------------------------------------------------------------------
# France: Base nationale des IRVE (consolidated CSV, whole country)
# --------------------------------------------------------------------------

IRVE_DATASET_API = "https://www.data.gouv.fr/api/1/datasets/5448d3e0c751df01f85d0572/"
TRUE_TEXT = {"true", "1", "oui", "yes"}


def irve_kw(value):
    power = number(value)
    # A few operators report watts instead of kilowatts
    return power/1000 if power and power > 1000 else power


def irve_position(row):
    """Prefer data.gouv.fr's checked coordinates; the raw field is often malformed."""
    lat, lon = number(row.get("consolidated_latitude")), number(row.get("consolidated_longitude"))
    if valid_coordinates(lat, lon):
        return lat, lon
    match = re.match(r"\s*\[\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\]", row.get("coordonneesXY") or "")
    if match:
        lon, lat = float(match.group(1)), float(match.group(2))
        if valid_coordinates(lat, lon):
            return lat, lon
    return None


def parse_irve(rows):
    """One row per charging point (pdc), grouped by roaming station ID.

    A pdc listed more than once keeps its most recently updated row."""
    stations = {}
    for row in rows:
        station, point = clean(row.get("id_station_itinerance")), clean(row.get("id_pdc_itinerance"))
        if not station or not point or irve_position(row) is None:
            continue
        points = stations.setdefault(station, {})
        if point not in points or (row.get("date_maj") or "") > (points[point].get("date_maj") or ""):
            points[point] = row
    for station, points in stations.items():
        first = next(iter(points.values()))
        lat, lon = irve_position(first)
        # The register also lists stations abroad; their ID prefix names the
        # operator's country, not the station's, so charger_positions relabels them
        site = Site("irve", station, lat, lon, "FR", clean(first.get("nom_operateur")) or clean(first.get("nom_enseigne")),
                    clean(first.get("nom_station")), clean(first.get("adresse_station")),
                    clean(first.get("consolidated_commune")), clean(first.get("consolidated_code_postal")))
        site.position_suspect = any(str(row.get("consolidated_is_lon_lat_correct", "")).lower() == "false"
                                    for row in points.values())
        for key, row in points.items():
            dc = any((row.get(column) or "").strip().lower() in TRUE_TEXT
                     for column in ("prise_type_combo_ccs", "prise_type_chademo"))
            site.points.append(Point(key, irve_kw(row.get("puissance_nominale")), "fast" if dc else "regular"))
        yield site


def read_irve(directory=RAW_DIR / "irve"):
    with open(Path(directory) / "irve_statique.csv", encoding="utf-8", newline="") as handle:
        yield from parse_irve(csv.DictReader(handle))


# --------------------------------------------------------------------------
# Finland: Fintraffic Digitraffic AFIR (GeoJSON, whole country)
# --------------------------------------------------------------------------

DIGITRAFFIC_FILES = {
    "locations.json": "https://afir.digitraffic.fi/api/charging-network/v1/locations?limit=ALL",
    "statuses.json": "https://afir.digitraffic.fi/api/charging-network/v1/locations/statuses?limit=ALL",
}


def parse_digitraffic(collection):
    for feature in collection.get("features") or []:
        properties = feature.get("properties") or {}
        coordinates = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coordinates) < 2 or not valid_coordinates(number(coordinates[1]), number(coordinates[0])):
            continue
        points = []
        for evse in properties.get("evses") or []:
            if not evse.get("id"):
                continue
            connectors = evse.get("connectors") or []
            watts = [w for w in (number(c.get("maxElectricPower")) for c in connectors) if w]
            points.append(Point(evse["id"], round(max(watts)/1000, 2) if watts else None,
                                "fast" if any(c.get("powerType") == "DC" for c in connectors) else "regular"))
        if not points:
            continue
        operator = properties.get("operator") or {}
        address = properties.get("address") or {}
        yield Site("digitraffic", str(properties["id"]), float(coordinates[1]), float(coordinates[0]),
                   country_code(address.get("countryCode"), "FI"),
                   clean((operator.get("details") or {}).get("name")) or clean(operator.get("id")),
                   clean(properties.get("name")), clean(address.get("street")), clean(address.get("city")),
                   clean(address.get("postalCode")), points=points)


def read_digitraffic(directory=RAW_DIR / "digitraffic"):
    return parse_digitraffic(json.loads((Path(directory) / "locations.json").read_text(encoding="utf-8")))


READERS = {"ndw": read_ndw, "bnetza": read_bnetza, "osm": read_osm, "bfe": read_bfe, "irve": read_irve,
           "digitraffic": read_digitraffic}


# --------------------------------------------------------------------------
# Downloads
# --------------------------------------------------------------------------

def _session():
    import requests
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


def _record(path, url):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(path=path.relative_to(DATA_DIR).as_posix(), url=url, bytes=path.stat().st_size, sha256=digest,
                fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))


def _download(session, url, path, log):
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    with session.get(url, stream=True, timeout=300) as response:
        response.raise_for_status()
        with open(partial, "wb") as handle:
            for chunk in response.iter_content(1 << 20):
                handle.write(chunk)
    partial.replace(path)
    log(f"  {path.relative_to(DATA_DIR).as_posix()}  {path.stat().st_size/1e6:.1f} MB")
    return _record(path, url)


def fetch_ndw(session, log=print):
    return [_download(session, url, RAW_DIR / "ndw" / name, log) for name, url in NDW_FILES.items()]


def fetch_bnetza(session, log=print):
    url = bnetza_csv_url(session)
    return [_download(session, url, RAW_DIR / "bnetza" / "ladesaeulenregister.csv", log)]


def fetch_osm(session, log=print, attempts=3):
    records = []
    for region in (r for r in REGIONS if r.osm):
        path = RAW_DIR / "osm" / f"{region.id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(attempts*len(OVERPASS_ENDPOINTS)):
            endpoint = OVERPASS_ENDPOINTS[attempt % len(OVERPASS_ENDPOINTS)]
            try:
                response = session.post(endpoint, data={"data": overpass_query(region.bbox)}, timeout=240)
                response.raise_for_status()
                payload = response.json()
                if "elements" not in payload:
                    raise ValueError(payload.get("remark", "no elements in response"))
            except Exception as exc:  # Overpass is often busy; rotate mirrors and back off
                log(f"  {region.id}: {endpoint} failed ({exc}); retrying")
                time.sleep(min(5*(attempt+1), 30))
                continue
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            log(f"  osm/{region.id}.json  {len(payload['elements'])} stations")
            records.append(_record(path, endpoint))
            break
        else:
            log(f"  {region.id}: giving up; keeping any earlier download")
    return records


def fetch_bfe(session, log=print):
    return [_download(session, url, RAW_DIR / "bfe" / name, log) for name, url in BFE_FILES.items()]


def fetch_irve(session, log=print):
    """The consolidated CSV gets a new dated URL every day; ask data.gouv.fr for it."""
    resources = session.get(IRVE_DATASET_API, timeout=60).json().get("resources", [])
    csvs = [r for r in resources if (r.get("format") or "").lower() == "csv" and "consolidation" in (r.get("url") or "")]
    if not csvs:
        raise RuntimeError("data.gouv.fr lists no consolidated IRVE CSV")
    return [_download(session, csvs[0]["url"], RAW_DIR / "irve" / "irve_statique.csv", log)]


def fetch_digitraffic(session, log=print):
    # Digitraffic asks clients to identify themselves
    session.headers["Digitraffic-User"] = "EPIOT-Drive2X"
    return [_download(session, url, RAW_DIR / "digitraffic" / name, log) for name, url in DIGITRAFFIC_FILES.items()]


FETCHERS = {"ndw": fetch_ndw, "bnetza": fetch_bnetza, "osm": fetch_osm, "bfe": fetch_bfe, "irve": fetch_irve,
            "digitraffic": fetch_digitraffic}


def load_manifest():
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_manifest(manifest):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


# Natural Earth 1:10m land and countries (public domain): find sites far out
# at sea, and sites in a country other than their feed's (Antwerp in NDW)
LAND_FILE = DATA_DIR / "ne_10m_land.zip"
LAND_URL = "https://naciscdn.org/naturalearth/10m/physical/ne_10m_land.zip"
COUNTRIES_FILE = DATA_DIR / "ne_10m_admin_0_countries.zip"
COUNTRIES_URL = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip"


def fetch(sources=tuple(SOURCES), log=print):
    session, manifest = _session(), load_manifest()
    for key, path, url in [("land", LAND_FILE, LAND_URL), ("countries", COUNTRIES_FILE, COUNTRIES_URL)]:
        if not path.exists():
            log(f"Fetching Natural Earth {key} polygons")
            manifest[key] = _download(session, url, path, log)
    for source in sources:
        log(f"Fetching {SOURCES[source].label}")
        files = FETCHERS[source](session, log)
        if files:
            manifest.setdefault("downloads", {})[source] = files
            save_manifest(manifest)
    return manifest


def in_bbox(lat, lon, bbox):
    south, west, north, east = bbox
    return south <= lat <= north and west <= lon <= east
