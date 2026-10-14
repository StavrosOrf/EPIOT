"""Spatial behaviour priors for synthetic charging scenarios, not fitted effects."""

from functools import lru_cache
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ATLAS = ROOT / "data/wijkenbuurten_2022_v2_amsterdam.gpkg"
ARCHETYPES = ("residential", "workplace", "retail", "mixed")


def nonnegative(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def profile_from_attributes(attributes=None):
    """Transparent, uncalibrated weights; no private/home access inference."""
    if not attributes:
        return {"weights": dict(residential=0., workplace=0., retail=0., mixed=1.),
                "arrival_multiplier": 1., "features": {}, "matched": False}
    area = nonnegative(attributes.get("oppervlakte_land_in_ha"))
    homes = nonnegative(attributes.get("woningvoorraad"))
    businesses = nonnegative(attributes.get("aantal_bedrijfsvestigingen"))
    retail = nonnegative(attributes.get("aantal_bedrijven_handel_en_horeca"))
    population_density = nonnegative(attributes.get("bevolkingsdichtheid_inwoners_per_km2"))
    if not area or (homes is None and businesses is None and population_density is None):
        return profile_from_attributes()
    area_km2 = area/100
    home_density = (homes or 0)/area_km2
    business_density = (businesses or 0)/area_km2
    retail_density = (retail or 0)/area_km2
    # Coefficients and reference densities are explicit scenario assumptions.
    scores = np.array([.2+home_density/2500, .2+max(0., business_density-retail_density)/400,
                       .2+retail_density/300, .5])
    weights = dict(zip(ARCHETYPES, (scores/scores.sum()).tolist()))
    multiplier = float(np.clip(.6+.4*np.log1p((population_density or 0)/3000+business_density/500), .6, 2.2))
    return {"weights": weights, "arrival_multiplier": multiplier, "matched": True,
            "neighbourhood_code": str(attributes.get("buurtcode", "")),
            "neighbourhood_name": str(attributes.get("buurtnaam", "")),
            "features": dict(population_density=population_density, homes_per_km2=home_density,
                             businesses_per_km2=business_density, retail_per_km2=retail_density)}


class SpatialAtlas:
    def __init__(self, path=DEFAULT_ATLAS):
        self.path = Path(path)
        self.frame = None
        if self.path.exists():
            import geopandas as gpd
            columns = ["buurtcode", "buurtnaam", "water", "oppervlakte_land_in_ha", "woningvoorraad",
                       "aantal_bedrijfsvestigingen", "aantal_bedrijven_handel_en_horeca",
                       "bevolkingsdichtheid_inwoners_per_km2"]
            self.frame = gpd.read_file(self.path, columns=columns).to_crs(4326)
            self.frame = self.frame[self.frame.geometry.notna() & ~self.frame.geometry.is_empty].reset_index(drop=True)

    def resolve(self, charger):
        lat, lon = charger.get("latitude"), charger.get("longitude")
        try:
            lat, lon = float(lat), float(lon)
        except (ValueError, TypeError):
            return {**profile_from_attributes(), "fallback_reason": "missing_coordinates"}
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            return {**profile_from_attributes(), "fallback_reason": "invalid_coordinates"}
        return self._resolve_coordinates(lat, lon)

    @lru_cache(maxsize=32768)
    def _resolve_coordinates(self, lat, lon):
        # A new atlas instance (file revision) or changed coordinates misses the cache.
        from shapely.geometry import Point
        if self.frame is None:
            return {**profile_from_attributes(), "fallback_reason": "atlas_unavailable"}
        matches = self.frame.sindex.query(Point(lon, lat), predicate="intersects")
        if len(matches) == 0:
            return {**profile_from_attributes(), "fallback_reason": "outside_atlas"}
        # Reproducible boundary assignment when a point intersects two polygons.
        selected = self.frame.iloc[matches].sort_values("buurtcode").iloc[0].to_dict()
        result = profile_from_attributes(selected)
        if not result["matched"]:
            result["fallback_reason"] = "neighbourhood_attributes_unavailable"
        return result


@lru_cache(maxsize=4)
def _atlas(path, modified_ns):
    return SpatialAtlas(path)


def get_atlas(path=DEFAULT_ATLAS):
    path = Path(path).resolve()
    return _atlas(str(path), path.stat().st_mtime_ns if path.exists() else 0)
