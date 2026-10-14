"""Repair charger positions the open feeds get wrong, before import.

Three faults occur in the feeds (see docs/charger_sources.md):

* out of country: swapped latitude/longitude, typos (latitude 55 for 51) and
  placeholders such as (50, -15) in the Atlantic;
* pile-ups: unrelated sites sharing one point, e.g. 188 German devices from
  across the country on one spot in the North Sea, or a whole town's chargers
  on its centroid;
* wrong country label: feeds list stations abroad (the Swiss feed has German,
  Austrian and Italian ones); the parsers take the country from the address.

A swap is tried next, then the address
is geocoded with the country's official geocoder where one exists (PDOK, Swiss
geo.admin.ch, French Géoplateforme) and Nominatim otherwise. Results are cached
in data/chargers/geocode_cache.json so re-imports make no repeat requests.
What cannot be resolved is left for the importer's plausibility check to drop.
"""

from collections import Counter, defaultdict
from functools import lru_cache
import json
import math
from pathlib import Path
import re
import time

from backend.charger_sources import COUNTRIES_FILE, DATA_DIR, LAND_FILE, USER_AGENT, plausible

CACHE = DATA_DIR / "geocode_cache.json"
OVERRIDES = Path(__file__).resolve().parent / "data/charger_position_overrides.json"
PILE_UP_ADDRESSES = 3  # distinct addresses on one point before it counts as a pile-up
CONFIRM_METRES = 1000  # a geocoded address this close confirms the feed's position
# Natural Earth's 1:10m coast is off by a few hundred metres and misses
# reclaimed land (Maasvlakte) and small islands. Sites more than about 2 km out
# are checked against their address; without an address match, only those more
# than about 8 km out are dropped.
OFFSHORE_DEGREES = .02
FAR_OFFSHORE_DEGREES = .1
EUROPE_CLIP = (-32., 27., 45., 72.)  # west, south, east, north; overseas sites are not checked


@lru_cache(maxsize=1)
def land_masks(path=str(LAND_FILE)):
    """Europe's land grown by OFFSHORE_DEGREES and by FAR_OFFSHORE_DEGREES, or
    None without the land file."""
    if not Path(path).exists():
        return None
    import geopandas as gpd
    from shapely import prepare
    from shapely.geometry import box
    land = gpd.read_file(f"zip://{Path(path).as_posix()}").clip(box(*EUROPE_CLIP)).union_all()
    masks = land.buffer(OFFSHORE_DEGREES), land.buffer(FAR_OFFSHORE_DEGREES)
    for mask in masks:
        prepare(mask)
    return masks


def land_mask():
    masks = land_masks()
    return masks[0] if masks else None


# Natural Earth borders are accurate to a few hundred metres: a site this close
# to its labelled country keeps the label
BORDER_DEGREES = .01
# Natural Earth lists these as separate countries; the feeds count them as part
# of Finland (Aland) and France (overseas collectivities)
COUNTRY_PARTS = {"AX": "FI", "PF": "FR", "NC": "FR", "MF": "FR", "BL": "FR", "PM": "FR", "WF": "FR"}


class CountryShapes:
    """Which country a point lies in, from Natural Earth's 1:10m borders."""

    def __init__(self, frame):
        from shapely import STRtree
        self.codes = list(frame["ISO_A2_EH"])
        self.geometries = list(frame.geometry)
        self.tree = STRtree(self.geometries)
        self.near = {}

    def contains_near(self, country, lats, lons):
        """Mask of points within BORDER_DEGREES of `country` (all True if unknown)."""
        import numpy as np
        from shapely import contains_xy, prepare
        if country not in self.codes:
            return np.ones(len(lats), dtype=bool)
        if country not in self.near:
            shape = self.geometries[self.codes.index(country)].buffer(BORDER_DEGREES)
            prepare(shape)
            self.near[country] = shape
        return contains_xy(self.near[country], lons, lats)

    def country_at(self, lat, lon):
        from shapely.geometry import Point
        hits = self.tree.query(Point(lon, lat), predicate="intersects")
        return COUNTRY_PARTS.get(self.codes[hits[0]], self.codes[hits[0]]) if len(hits) else None


@lru_cache(maxsize=1)
def country_shapes(path=str(COUNTRIES_FILE)):
    if not Path(path).exists():
        return None
    import geopandas as gpd
    frame = gpd.read_file(f"zip://{Path(path).as_posix()}", columns=["ISO_A2_EH"])
    return CountryShapes(frame[frame["ISO_A2_EH"].str.len() == 2].reset_index(drop=True))


def relabel_by_border(sites, shapes):
    """A site clearly inside another country takes that country's label; the
    importer then leaves out countries its source does not cover."""
    import numpy as np
    moved = 0
    by_country = defaultdict(list)
    for site in sites:
        if not math.isnan(site.lat):
            by_country[site.country].append(site)
    for country, group in by_country.items():
        inside = shapes.contains_near(country, np.array([s.lat for s in group]), np.array([s.lon for s in group]))
        for site, ok in zip(group, inside):
            if ok:
                continue
            found = shapes.country_at(site.lat, site.lon)
            if found and found != site.country:  # at sea it keeps its label
                site.country = found
                moved += 1
    return moved


def offshore(lat, lon, mask=None):
    mask = mask if mask is not None else land_mask()
    if mask is None or not (EUROPE_CLIP[1] <= lat <= EUROPE_CLIP[3] and EUROPE_CLIP[0] <= lon <= EUROPE_CLIP[2]):
        return False
    from shapely import contains_xy
    return not contains_xy(mask, lon, lat)


def normalise(text):
    return re.sub(r"[\W_]+", " ", str(text or "").lower()).strip()  # some feeds give postcodes as numbers


def address_key(site):
    return "|".join([site.country, normalise(site.street), normalise(site.postcode), normalise(site.city)])


def metres(a, b):
    dy = (a[0]-b[0])*111_320
    dx = (a[1]-b[1])*111_320*math.cos(math.radians((a[0]+b[0])/2))
    return math.hypot(dx, dy)


def pile_ups(sites):
    """Positions shared by sites with several different addresses."""
    by_position = defaultdict(list)
    for site in sites:
        if math.isnan(site.lat):  # already dropped
            continue
        by_position[(round(site.lat, 5), round(site.lon, 5))].append(site)
    return {position: group for position, group in by_position.items()
            if len({address_key(site) for site in group if site.street}) >= PILE_UP_ADDRESSES}


class Geocoder:
    """Address -> (lat, lon), cached on disk, including misses."""

    def __init__(self, cache_path=CACHE, session=None, log=print):
        self.path = Path(cache_path)
        try:
            self.cache = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.cache = {}
        self.session = session
        self.log = log
        self.requests = 0
        self.last_nominatim = 0.

    def _get(self, url, params):
        if self.session is None:
            import requests
            self.session = requests.Session()
            self.session.headers["User-Agent"] = USER_AGENT
        self.requests += 1
        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def _pdok(self, site):
        query = " ".join(filter(None, [site.street, site.postcode, site.city]))
        docs = self._get("https://api.pdok.nl/bzk/locatieserver/search/v3_1/free",
                         {"q": query, "fq": "type:adres", "rows": 1, "fl": "centroide_ll"})["response"]["docs"]
        if docs:
            lon, lat = map(float, re.findall(r"[-\d.]+", docs[0]["centroide_ll"]))
            return lat, lon
        return None

    def _swiss(self, site):
        query = " ".join(filter(None, [site.street, site.postcode, site.city]))
        results = self._get("https://api3.geo.admin.ch/rest/services/api/SearchServer",
                            {"searchText": query, "type": "locations", "limit": 1, "sr": 4326}).get("results", [])
        if results:
            return float(results[0]["attrs"]["lat"]), float(results[0]["attrs"]["lon"])
        return None

    def _france(self, site):
        query = " ".join(filter(None, [site.street, site.postcode, site.city]))
        features = self._get("https://data.geopf.fr/geocodage/search", {"q": query, "limit": 1}).get("features", [])
        if features and features[0]["properties"].get("score", 0) >= .5:
            lon, lat = features[0]["geometry"]["coordinates"]
            return lat, lon
        return None

    def _nominatim(self, site):
        # Nominatim's usage policy allows at most one request per second
        time.sleep(max(0., 1.1-(time.monotonic()-self.last_nominatim)))
        self.last_nominatim = time.monotonic()
        params = {"street": site.street, "postalcode": site.postcode, "city": site.city,
                  "countrycodes": site.country.lower(), "format": "jsonv2", "limit": 1}
        results = self._get("https://nominatim.openstreetmap.org/search",
                            {key: value for key, value in params.items() if value})
        return (float(results[0]["lat"]), float(results[0]["lon"])) if results else None

    def locate_anywhere(self, site):
        """For a site outside its labelled country: (lat, lon, country) from its
        address, searched across all countries."""
        query = ", ".join(filter(None, [site.street, " ".join(filter(None, [str(site.postcode or ""), site.city]))]))
        if not query.strip():
            return None
        key = "*|" + normalise(query)
        if key not in self.cache:
            time.sleep(max(0., 1.1-(time.monotonic()-self.last_nominatim)))
            self.last_nominatim = time.monotonic()
            try:
                results = self._get("https://nominatim.openstreetmap.org/search",
                                    {"q": query, "format": "jsonv2", "limit": 1, "addressdetails": 1})
            except Exception as exc:
                self.log(f"    geocoding failed for {site.city or site.postcode}: {exc}")
                return None
            found = results[0] if results else None
            self.cache[key] = ([float(found["lat"]), float(found["lon"]), found["address"]["country_code"].upper()]
                               if found and found.get("address", {}).get("country_code") else None)
        value = self.cache[key]
        return tuple(value) if value else None

    def locate(self, site):
        if not site.street and not site.postcode:
            return None
        key = address_key(site)
        if key not in self.cache:
            provider = {"NL": self._pdok, "CH": self._swiss, "LI": self._swiss, "FR": self._france}.get(
                site.country, self._nominatim)
            try:
                found = provider(site)
            except Exception as exc:  # network or service trouble: try again next import
                self.log(f"    geocoding failed for {site.city or site.postcode}: {exc}")
                return None
            self.cache[key] = list(found) if found else None
            if self.requests % 25 == 0:
                self.save()
        value = self.cache[key]
        return tuple(value) if value else None

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=0), encoding="utf-8")


def move(site, lat, lon):
    """Keep coordinate-based location groups in step with the new position."""
    if site.group and re.fullmatch(r"-?[\d.]+,-?[\d.]+", site.group):
        site.group = f"{lat:.5f},{lon:.5f}"
    site.lat, site.lon = lat, lon


def position_overrides():
    return json.loads(OVERRIDES.read_text(encoding="utf-8"))


def apply_position_override(site, overrides):
    correction = overrides.get(f"{site.source}:{site.key}")
    if correction and metres((site.lat, site.lon), correction["position"]) <= CONFIRM_METRES:
        site.position_suspect = False
        return False
    # Do not overwrite a future corrected feed position elsewhere.
    if correction and metres((site.lat, site.lon), correction["bad_position"]) <= CONFIRM_METRES:
        move(site, *correction["position"])
        site.country = correction["country"]
        site.position_suspect = False
        return True
    return False


def repair_positions(sites, geocoder=None, mask=None, shapes=None):
    """Fix what can be fixed in place; returns the sites and counts of each repair.

    `mask` is the 2 km land mask and `shapes` the country borders (defaults: the
    Natural Earth ones); pass False to skip either check.
    """
    sites = list(sites)
    stats = Counter()
    overrides = position_overrides()
    for site in sites:
        stats["verified_overrides"] += apply_position_override(site, overrides)
    if mask is None:
        mask, far_mask = land_masks() or (None, None)
    elif mask is False:
        mask = far_mask = None
    else:
        far_mask = mask.buffer(FAR_OFFSHORE_DEGREES-OFFSHORE_DEGREES)
    at_sea = lambda lat, lon: offshore(lat, lon, mask) if mask is not None else False
    far_at_sea = lambda lat, lon: offshore(lat, lon, far_mask) if far_mask is not None else False
    outside = []
    for site in sites:
        if not site.position_suspect and plausible(site.country, site.lat, site.lon) and not at_sea(site.lat, site.lon):
            continue
        if at_sea(site.lat, site.lon):
            stats["at_sea"] += 1
        if plausible(site.country, site.lon, site.lat) and not at_sea(site.lon, site.lat):
            move(site, site.lon, site.lat)
            stats["swapped"] += 1
        else:
            outside.append(site)
    # Outside the labelled country: a station abroad, or a bad position.
    # The address decides, searched in every country.
    for site in outside:
        sea_only = plausible(site.country, site.lat, site.lon)  # right country, only failed the sea check
        found = geocoder.locate_anywhere(site) if geocoder else None
        if not found and geocoder:
            # The country's own geocoder knows addresses the all-country search misses
            local = geocoder.locate(site)
            found = (*local, site.country) if local else None
        if found and plausible(found[2], found[0], found[1]) and not far_at_sea(found[0], found[1]):
            lat, lon, country = found
            if metres((lat, lon), (site.lat, site.lon)) <= CONFIRM_METRES:
                # The address agrees: a quay, an island or a station abroad
                stats["confirmed_by_address" if sea_only and country == site.country else "relabelled_abroad"] += 1
            else:
                move(site, lat, lon)
                stats["geocoded"] += 1
            site.country = country
        elif sea_only and not site.position_suspect and not far_at_sea(site.lat, site.lon):
            stats["kept_near_coast"] += 1  # the coarse coastline cannot tell a quay from water
        else:
            # Nothing better known: drop it rather than show it at sea or abroad
            site.lat = site.lon = float("nan")
            stats["unresolved"] += 1
    suspects = []
    piles = pile_ups(sites)
    for group in piles.values():
        suspects.extend(group)
    stats["pile_up_points"], stats["pile_up_sites"] = len(piles), sum(len(group) for group in piles.values())
    placeholders = {position for position, group in piles.items() if len({normalise(s.city) for s in group}) >= 3}
    for site in suspects:
        found = geocoder.locate(site) if geocoder else None
        if found and plausible(site.country, *found):
            if metres(found, (site.lat, site.lon)) > CONFIRM_METRES:
                move(site, *found)
                stats["geocoded"] += 1
            else:
                stats["confirmed"] += 1
        elif (round(site.lat, 5), round(site.lon, 5)) in placeholders:
            # Sites from several towns on one point: the point means nothing
            site.lat = site.lon = float("nan")
            stats["unresolved_placeholder"] += 1
        else:
            stats["unresolved"] += 1
    shapes = country_shapes() if shapes is None else (shapes or None)
    if shapes is not None:
        stats["relabelled_by_border"] = relabel_by_border(sites, shapes)
    if geocoder:
        geocoder.save()
        stats["geocoder_requests"] = geocoder.requests
    return sites, dict(stats)
