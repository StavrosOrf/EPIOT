from json import JSONDecodeError
from flask import abort, jsonify, request
import geojson as gj
from shapely.geometry import box, shape
from shapely.errors import GeometryTypeError
from backend.models import ChargingPoint, Column, Location, Operator, GridConnection
from backend.charger_sources import COUNTRY_NAMES, LEGACY_SOURCE, MANIFEST, REGIONS, SOURCES, load_manifest
from backend.charger_import import cell_degrees
from backend.station_cache import StationCache
from backend.map_density import DensityCache, density_version
import math
from backend.utils import stations_to_geojson
import datetime

import numpy as np

from sqlalchemy import select, func

from flask import current_app, Blueprint
from backend.session_sources import SOURCE_LABELS, session_service
from backend.request_args import (RequestTooLarge, check_point_days, demand_assumption, ensemble_size,
                                  request_arguments, scenario_seed, session_source)
from backend.cpft_runtime import CPFTUnavailable
from backend.day_profile import UnsupportedWindow, day_profile, empty_profile, ensemble_summary
from backend.session_frame import SessionFrame
from backend.stored_sessions import STORED_LABEL, STORED_NOTE, stored_records
from pathlib import Path
from zoneinfo import ZoneInfo
from backend.grid_data import app_grid_hours
from backend.carbon_charging import CarbonScheduleUnavailable
from backend.analysis_versions import analysis_versions


station_data = Blueprint("station_data", "station_data")


@station_data.record
def record(state):
    db = state.app.config.get("station_data.db")

    if db is None:
        raise Exception(
            "This blueprint expects you to provide "
            "database access through station_data.db"
        )


def station_columns():
    return (
        select(
            ChargingPoint.id,
            ChargingPoint.power,
            ChargingPoint.type,
            Operator.name,
            Location.latitude,
            Location.longitude,
            Location.street,
            Location.supplement,
            Column.source,
            Location.postal_name,
            Location.country,
        )
        .join(ChargingPoint.column)
        .join(Location)
        .join(Operator)
    )


@station_data.route("/within", methods=["POST"])
def get_stations_within():
    db = current_app.config["station_data.db"]
    try:
        data = gj.loads(request.data)
        geometry = shape(data)
        polygon = str(geometry)
    except (JSONDecodeError, KeyError, GeometryTypeError, TypeError, AttributeError):
        abort(400, "Could not handle request, expected GeoJSON")
    west, south, east, north = geometry.bounds
    # The indexed bounding-box test narrows the rows before the exact polygon test
    statement = station_columns().filter(
        Location.latitude.between(south, north),
        Location.longitude.between(west, east),
    )
    # The bounding-box test is exact for a rectangle (the map viewport)
    if geometry.geom_type != "Polygon" or not geometry.equals(box(west, south, east, north)):
        statement = statement.filter(func.ST_Within(Location.geom, func.ST_GeomFromEWKT(polygon)))

    if request.args.get("ids_only") == "1":
        ids = db.session.execute(statement.with_only_columns(ChargingPoint.id).order_by(ChargingPoint.id)).scalars().all()
        return jsonify(ids=ids)

    if geometry.geom_type in ("Polygon", "MultiPolygon"):
        cache = current_app.extensions.setdefault("station_cache", StationCache())
        version = density_version(current_app, db.engine)
        found = cache.features(db.session, station_columns(), Location, version, geometry)
        if found is not None:
            body = '{"type":"FeatureCollection","features":[' + ",".join(found) + "]}"
            return current_app.response_class(body, mimetype="application/json")

    query_result = db.session.execute(statement)

    return jsonify(stations_to_geojson(query_result))


@station_data.route("/analysis-version", methods=["GET"])
def get_analysis_version():
    response = jsonify(analysis_versions(current_app))
    response.headers["Cache-Control"] = "no-store"
    return response


@station_data.route("/all", methods=["GET"])
def get_all_stations():
    """Every charging point, or one source's with ?source=pilot|ndw|bnetza|osm."""
    db = current_app.config["station_data.db"]
    statement = station_columns()
    source = request.args.get("source")
    if source == LEGACY_SOURCE:
        statement = statement.filter(Column.source.is_(None))
    elif source:
        statement = statement.filter(Column.source == source)
    query_result = db.session.execute(statement)

    return jsonify(stations_to_geojson(query_result))


@station_data.route("/coverage", methods=["GET"])
def get_coverage():
    """Searchable cities with charger counts, and the open-data sources behind them."""
    manifest = load_manifest()
    counts = manifest.get("regions", {})
    imported = manifest.get("imports", {})
    regions = [dict(id=region.id, name=region.name, country=region.country,
                    country_name=COUNTRY_NAMES[region.country], lat=region.lat, lon=region.lon,
                    zoom=region.zoom, bbox=region.bbox, **counts.get(region.id, dict(sites=None, points=None)))
               for region in REGIONS]
    sources = [dict(id=source.id, label=source.label, publisher=source.publisher, licence=source.licence,
                    url=source.url, countries=source.countries, imported_at=imported.get(source.id, {}).get("imported_at"))
               for source in SOURCES.values()]
    return jsonify(regions=regions, sources=sources)


# Overview zooms (below city level) get aggregated bubbles, never single points
DENSITY_ZOOMS = range(3, 12)


@station_data.route("/density", methods=["GET"])
def get_density():
    """Charging points aggregated on a zoom-dependent grid, inside an optional bbox=west,south,east,north."""
    try:
        zoom = int(request.args.get("zoom", ""))
        bbox = [float(value) for value in request.args.get("bbox", "-180,-90,180,90").split(",")]
        if (zoom not in DENSITY_ZOOMS or len(bbox) != 4 or not all(math.isfinite(v) for v in bbox)
                or bbox[0] > bbox[2] or bbox[1] > bbox[3]):
            raise ValueError
    except ValueError:
        return jsonify(error=f"zoom must be {DENSITY_ZOOMS.start}-{DENSITY_ZOOMS.stop-1}, "
                             "bbox west,south,east,north"), 400
    engine = current_app.config["station_data.db"].engine
    version = density_version(current_app, engine)
    cache = current_app.extensions.setdefault("map_density", DensityCache())
    west, south, east, north = bbox
    pad = cell_degrees(zoom)
    cells = [cell for cell in cache.get(engine, version, zoom)
             if south-pad <= cell[0] <= north+pad and west-pad <= cell[1] <= east+pad]
    response = jsonify(zoom=zoom, cell_degrees=pad, cells=cells)
    response.set_etag(f"{version}-{zoom}-{'-'.join(map(str, bbox))}")
    response.headers["Cache-Control"] = "private, max-age=30"
    return response.make_conditional(request)


@station_data.route("/aggregate_load", methods=["GET", "POST"])
def get_aggregate_load():
    """The load profile of the selected charging points for one local day.

    Input (JSON body for POST, query string for GET):
    - selected_markers: charging-point IDs, a list or a comma-separated string
    - strategy: afap, alap, avg, ocost or mincarbon
    - date: the target day, YYYY-MM-DD
    - session_source: database (stored sessions), simple, spatial or cpft
    - demand_assumption, seed: scenario sources only
    - ensemble: number of seeded session draws (default 1). With more than one,
      source.ensemble holds the 10th/50th/90th percentile load over seeds
      seed, seed+1, ...; y stays the requested seed's own draw.

    Returns the 10-minute profile of the previous and the target day: x,
    timestamps, past_steps, y (load, kW), up_flex, down_flex, flex_polytope and
    the provenance of the sessions in source. Stored and generated sessions are
    scheduled by the same engine.
    """
    db = current_app.config["station_data.db"]
    try:
        arguments = request_arguments(request)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    selected_markers = arguments.get("selected_markers", "")
    if isinstance(selected_markers, list):
        selected_markers = ",".join(str(value) for value in selected_markers)
    if not isinstance(selected_markers, str):
        return jsonify(error="Selected markers must be IDs or a comma-separated string"), 400
    if selected_markers == "undefined":
        return jsonify({"x": np.arange(144).tolist(),
                        "y": np.zeros(144).tolist(),
                        "up_flex": np.zeros(144).tolist(),
                        "down_flex": np.zeros(144).tolist()})

    method = str(arguments.get("strategy", "")).strip()
    try:
        source = session_source(arguments)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    if method not in {"afap", "alap", "avg", "ocost", "mincarbon"}:
        return jsonify(error="Unknown charging strategy"), 400
    if method == "mincarbon" and source == "database":
        return jsonify(error="Select a simple, spatial or CPFT session source for minimum-carbon charging."), 400
    assumption = "base"
    draws = 1
    if source != "database":
        try:
            assumption = demand_assumption(arguments)
            draws = ensemble_size(arguments, current_app.config)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
    elif arguments.get("ensemble") not in (None, "", 1, "1"):
        return jsonify(error="Several draws need a generated session source; stored sessions have no sampling to vary."), 400
    if draws > 1 and method == "ocost":
        return jsonify(error="Several draws are not available for cost optimisation; choose another strategy."), 400

    target_day = None
    # An empty selection of stored sessions without a date has no day to look up
    if source != "database" or selected_markers != "" or arguments.get("date"):
        try:
            target_day = datetime.date.fromisoformat(str(arguments.get("date", "")))
        except ValueError:
            return jsonify(error="date must be a calendar date, YYYY-MM-DD"), 400
    timezone_name = current_app.config.get("SESSION_SCENARIO_TIMEZONE", "Europe/Amsterdam")

    try:
        ids = sorted({int(value) for value in selected_markers.split(",") if value.strip()})
    except ValueError:
        return jsonify(error="Selected markers must be integer charging-point IDs"), 400
    try:
        check_point_days(current_app.config, len(ids), 2*draws)  # the previous and the target day, per draw
    except RequestTooLarge as exc:
        return jsonify(error=str(exc)), 422
    stored = source == "database"
    if not ids:
        if target_day is None:
            return jsonify({"x": np.arange(144).tolist(),
                            "y": np.zeros(144).tolist(),
                            "up_flex": np.zeros(144).tolist(),
                            "down_flex": np.zeros(144).tolist()})
        metadata = dict(source=source, label=STORED_LABEL if stored else SOURCE_LABELS[source], synthetic=not stored,
                        point_count=0, spatial_matched_points=0, note="No charging points in this selection.")
        if not stored:
            metadata["assumption"] = assumption
        return jsonify(empty_profile(target_day, timezone_name, metadata))

    rows = db.session.execute(
        select(ChargingPoint.id, ChargingPoint.power, ChargingPoint.type, Location.latitude, Location.longitude,
               Location.country)
        .join(ChargingPoint.column).join(Location).filter(ChargingPoint.id.in_(ids))).all()
    charger_data = [dict(id=row[0], power=row[1], type=row[2], latitude=row[3], longitude=row[4], country=row[5])
                    for row in rows]
    if len(charger_data) != len(ids):
        return jsonify(error="One or more selected charging points are unavailable"), 400

    def grid_hours(start, end):
        return app_grid_hours(start, end, db.session,
                              cache_path=current_app.config.get("GRID_DATA_CACHE", Path(current_app.instance_path)/"grid_data.sqlite"),
                              allow_stale=current_app.config.get("GRID_ALLOW_STALE", True), timezone_name=timezone_name)

    try:
        if stored:
            zone = ZoneInfo(timezone_name)
            left = datetime.datetime.combine(target_day-datetime.timedelta(days=1), datetime.time.min)
            right = datetime.datetime.combine(target_day+datetime.timedelta(days=1), datetime.time.min)
            sessions = SessionFrame.from_records(stored_records(db.session, ids, left, right, zone))
            metadata = dict(source="database", label=STORED_LABEL, synthetic=False, verified_observations=False,
                            point_count=len(charger_data), session_count=len(sessions), timezone=timezone_name,
                            target_date=str(target_day), note=STORED_NOTE)
            current_app.logger.info("Analysing %d stored sessions for %s with the %s method",
                                    len(sessions), target_day, method)
        else:
            # Computed on request for any date: no live data, so nothing is prepared or cached
            seed = scenario_seed(arguments)
            service = session_service(current_app)
            sessions, metadata = service.get(charger_data, target_day, source=source, assumption=assumption,
                                             seed=seed, timezone_name=timezone_name)
        profile = day_profile(charger_data, sessions, metadata, target_day, method, timezone_name, grid_hours)
        if draws > 1:
            seeds = [(seed+offset) % 2**32 for offset in range(draws)]
            more = (service.get(charger_data, target_day, source=source, assumption=assumption, seed=other,
                                timezone_name=timezone_name)[0] for other in seeds[1:])
            profile["source"]["ensemble"] = ensemble_summary(
                charger_data, [sessions, *more], seeds, target_day, method, timezone_name, grid_hours)
        return jsonify(profile)
    except UnsupportedWindow as exc:
        return jsonify(error=str(exc)), 422
    except CarbonScheduleUnavailable as exc:
        return jsonify(error=str(exc)), 422
    except (ValueError, KeyError, TypeError) as exc:
        return jsonify(error=str(exc)), 400
    except CPFTUnavailable as exc:
        return jsonify(error=str(exc)), 503
    except (OSError, RuntimeError) as exc:
        current_app.logger.exception("Session source failed")
        label = STORED_LABEL if stored else SOURCE_LABELS[source]
        return jsonify(error=f"{label} are unavailable: {exc}" if stored else f"{label} is unavailable: {exc}"), 503


@station_data.route("/charging-points-by-transformers", methods=["POST"])
def charging_points_by_transformers():
    """
    Body: {"transformer_ids": [int, ...]}
    Returns: {"transformer_ids":[...], "charging_point_ids":[...], "count": N}
    """
    db = current_app.config["station_data.db"]
    try:
        payload = request.get_json(force=True)
        tf_ids = payload["transformer_ids"]
        if not isinstance(tf_ids, list) or not all(isinstance(t, int) for t in tf_ids):
            raise ValueError
    except Exception:
        abort(400, 'Expected JSON: {"transformer_ids":[int,...]}')

    # Column IDs linked to those transformers
    col_ids = db.session.execute(
        select(GridConnection.column_id).where(GridConnection.transformer_id.in_(tf_ids))
    ).scalars().all()

    if not col_ids:
        return jsonify({"transformer_ids": tf_ids, "charging_point_ids": [], "count": 0})

    # Expand to ChargingPoint IDs
    cp_ids = db.session.execute(
        select(ChargingPoint.id).where(ChargingPoint.column_id.in_(col_ids))
    ).scalars().all()

    # Deduplicate & sort for stability
    cp_ids = sorted(set(int(x) for x in cp_ids))

    return jsonify({"transformer_ids": tf_ids, "charging_point_ids": cp_ids, "count": len(cp_ids)})

