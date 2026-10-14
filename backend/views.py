from json import JSONDecodeError
from flask import abort, jsonify, request
import geojson as gj
from shapely.geometry import shape
from shapely.errors import GeometryTypeError
from backend.models import ChargingPoint, Location, Operator, Session, GridConnection
from backend.utils import stations_to_geojson
import datetime

import numpy as np

from sqlalchemy import select, func, extract

from backend.aggregators import (
    simulate_cost_optimal_operation,
    simulate_delayed_profiles_from_sessions,
    simulate_uncontrolled_profiles_from_sessions,
    simulate_avg_charging_profiles_from_sessions
)

from flask import current_app, Blueprint
from backend.session_sources import SessionSourceService, SOURCE_LABELS
from backend.cpft_runtime import CPFTUnavailable
from backend.scenario_profiles import grid, simulate_scenarios
from backend.scenario_sampling import point_power
from backend.cpft import day_window
from backend.spatial_profiles import DEFAULT_ATLAS
from pathlib import Path
from zoneinfo import ZoneInfo


station_data = Blueprint("station_data", "station_data")


@station_data.record
def record(state):
    db = state.app.config.get("station_data.db")

    if db is None:
        raise Exception(
            "This blueprint expects you to provide "
            "database access through station_data.db"
        )


@station_data.route("/within", methods=["POST"])
def get_stations_within():
    db = current_app.config["station_data.db"]
    try:
        data = gj.loads(request.data)
        polygon = str(shape(data))
    except (JSONDecodeError, KeyError, GeometryTypeError, TypeError):
        abort(400, "Could not handle request, expected GeoJSON")
    statement = (
        select(
            ChargingPoint.id,
            ChargingPoint.power,
            ChargingPoint.type,
            Operator.name,
            Location.latitude,
            Location.longitude,
            Location.street,
            Location.supplement,
        )
        .join(ChargingPoint.column)
        .join(Location)
        .join(Operator)
        .filter(func.ST_Within(Location.geom, func.ST_GeomFromEWKT(polygon)))
    )

    query_result = db.session.execute(statement)

    return jsonify(stations_to_geojson(query_result))


@station_data.route("/all", methods=["GET"])
def get_all_stations():
    db = current_app.config["station_data.db"]
    statement = (
        select(
            ChargingPoint.id,
            ChargingPoint.power,
            ChargingPoint.type,
            Operator.name,
            Location.latitude,
            Location.longitude,
            Location.street,
            Location.supplement,
        )
        .join(ChargingPoint.column)
        .join(Location)
        .join(Operator)
    )

    query_result = db.session.execute(statement)

    return jsonify(stations_to_geojson(query_result))


@station_data.route("/aggregate_load", methods=["GET", "POST"])
def get_aggregate_load():
    """
    This endpoint is called when the user selects one or more chargers on the map.
    It returns the aggregated load profile for the selected chargers.

    Input:
    - selected_markers: Comma-separated list of charger IDs

    Returns:
    - x: The time axis (15-minute intervals)
    - y: The aggregated load profile for the selected chargers
    """
    db = current_app.config["station_data.db"]
    cfg = current_app.config["aggregator_config"]
    arguments = request.get_json(silent=True) if request.method == "POST" else request.args
    if arguments is None or not hasattr(arguments, "get"):
        return jsonify(error="Expected a JSON object"), 400
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

    method = arguments.get(
        "strategy", ""
    )
    method = str(method).strip()
    source = str(arguments.get("session_source", "database")).strip()
    if source not in {"database", *SOURCE_LABELS}:
        return jsonify(error="Unknown session source"), 400
    if method not in {"afap", "alap", "avg", "ocost"}:
        return jsonify(error="Unknown charging strategy"), 400
    if source != "database" and arguments.get("demand_assumption", "base") not in {"low", "base", "high"}:
        return jsonify(error="Unknown demand assumption"), 400

    selected_markers = selected_markers.split(
        ",") if selected_markers != "" else []
    if len(selected_markers) > 0:
        selected_markers = tuple(selected_markers)
        statement = (
            select(
                ChargingPoint.id,
                ChargingPoint.power,
                ChargingPoint.type,
                Operator.name,
                Location.latitude,
                Location.longitude,
                Location.street,
            )
            .join(ChargingPoint.column)
            .join(Location)
            .join(Operator)
        ).filter(ChargingPoint.id.in_(selected_markers))
        query_result = db.session.execute(statement)
        # make diuctionary from query_result with id as key and power as value
        point_rows = list(query_result)
        chargers = {row[0]: row[1] for row in point_rows}

        if source != "database":
            try:
                target = datetime.date.fromisoformat(arguments.get("date", ""))
                seed = int(arguments.get("seed", "42"))
                timezone_name = current_app.config.get("SESSION_SCENARIO_TIMEZONE", "Europe/Amsterdam")
                charger_data = [dict(id=row[0], power=row[1], type=row[2], latitude=row[4], longitude=row[5]) for row in point_rows]
                if len(charger_data) != len(set(selected_markers)):
                    return jsonify(error="One or more selected charging points are unavailable"), 400
                service = current_app.extensions.get("session_source_service")
                if service is None:
                    service = SessionSourceService(
                        cache_path=current_app.config.get("SESSION_SCENARIO_CACHE", Path(current_app.instance_path)/"session_scenarios.sqlite"),
                        atlas_path=current_app.config.get("SESSION_SCENARIO_ATLAS", DEFAULT_ATLAS),
                        daily_arrivals=float(current_app.config.get("SESSION_DAILY_ARRIVALS", 2.)))
                    current_app.extensions["session_source_service"] = service
                sessions, metadata = service.get(charger_data, target, source=source,
                    assumption=arguments.get("demand_assumption", "base"), seed=seed, timezone_name=timezone_name)
                start, target_start = day_window(target-datetime.timedelta(days=1), timezone_name)
                _, end = day_window(target, timezone_name)
                timestamps, past_steps = grid(start, end, target_start)
                if method == "ocost":
                    if len(timestamps) != 288:
                        return jsonify(error="Cost optimisation currently supports two 24-hour days. Choose another strategy for a daylight-saving transition."), 422
                    zone = ZoneInfo(timezone_name)
                    rows = [(session.cp_id, session.start.astimezone(zone).replace(tzinfo=None),
                             session.end.astimezone(zone).replace(tzinfo=None), session.energy_kwh) for session in sessions]
                    load_profile, up_flex, down_flex = simulate_cost_optimal_operation(
                        {int(charger["id"]): point_power(charger) for charger in charger_data}, rows,
                        start_date=str(target-datetime.timedelta(days=1)))
                else:
                    load_profile, up_flex, down_flex = simulate_scenarios(charger_data, sessions, start, end, method)
                metadata["flexibility_note"] = "Indicative differences between charging schedules; not a firm flexibility commitment."
                return jsonify(x=list(range(len(timestamps))), timestamps=[timestamp.isoformat() for timestamp in timestamps],
                    past_steps=past_steps, y=list(load_profile), up_flex=list(up_flex), down_flex=list(down_flex), source=metadata)
            except (ValueError, KeyError, TypeError) as exc:
                return jsonify(error=str(exc)), 400
            except CPFTUnavailable as exc:
                return jsonify(error=str(exc)), 503
            except (OSError, RuntimeError) as exc:
                current_app.logger.exception("Session source failed")
                return jsonify(error=f"{SOURCE_LABELS[source]} is unavailable: {exc}"), 503

        date = arguments.get("date", "")
        year = int(date.split("-")[0])
        month = int(date.split("-")[1])
        day = int(date.split("-")[2])

        start_date = get_day_before(date)
        start_year = int(start_date.split("-")[0])
        start_month = int(start_date.split("-")[1])
        start_day = int(start_date.split("-")[2])

        statement = (
            select(
                Session.cp_id,
                Session.start,
                Session.end,
                Session.consumption
            )
        ).filter(
            (
                Session.cp_id.in_(selected_markers) &
                (extract('year', Session.start) == int(year)) &
                (extract('month', Session.start) == int(month)) &
                (extract('day', Session.start) == int(day))
            ) |
            (
                Session.cp_id.in_(selected_markers) &
                (extract('year', Session.end) == int(start_year)) &
                (extract('month', Session.end) == int(start_month)) &
                (extract('day', Session.end) == int(start_day))
            )
        )

        charging_sessions = db.session.execute(statement)
        charging_sessions = [s for s in charging_sessions]

        # print(f'charging_sessions: {charging_sessions}')
        # print(f'query_result: {charging_sessions}')
        print(f'Analyzing {len(charging_sessions)}  charging sessions' +
              f' for date {date} using the {method} method .')

        if method == "afap":
            load_profile, up_flex, down_flex = simulate_uncontrolled_profiles_from_sessions(
                chargers,
                charging_sessions,
                start_date=start_date)
        elif method == "alap":
            load_profile, up_flex, down_flex = simulate_delayed_profiles_from_sessions(
                chargers,
                charging_sessions,
                start_date=start_date)
        elif method == "avg":
            load_profile, up_flex, down_flex = simulate_avg_charging_profiles_from_sessions(
                chargers,
                charging_sessions,
                start_date=start_date)
        elif method == "ocost":
            load_profile, up_flex, down_flex = simulate_cost_optimal_operation(
                chargers,
                charging_sessions,
                start_date=start_date)
        else:
            print(f'Unknown method: {method}')

        return jsonify({"x": list(range(len(load_profile))),
                        "y": list(load_profile),
                        "up_flex": list(up_flex),
                        "down_flex": list(down_flex)})
    else:
        if source != "database":
            try:
                target = datetime.date.fromisoformat(arguments.get("date", ""))
                zone = current_app.config.get("SESSION_SCENARIO_TIMEZONE", "Europe/Amsterdam")
                start, target_start = day_window(target-datetime.timedelta(days=1), zone)
                _, end = day_window(target, zone)
                timestamps, split = grid(start, end, target_start)
                zeros = [0.]*len(timestamps)
                return jsonify(x=list(range(len(timestamps))), timestamps=[timestamp.isoformat() for timestamp in timestamps],
                    past_steps=split, y=zeros, up_flex=zeros, down_flex=zeros,
                    source=dict(source=source, label=SOURCE_LABELS[source], synthetic=True, assumption=arguments.get("demand_assumption", "base"),
                                point_count=0, spatial_matched_points=0, note="No charging points in this selection."))
            except ValueError as exc:
                return jsonify(error=str(exc)), 400
        return jsonify({"x": np.arange(144).tolist(),
                        "y": np.zeros(144).tolist(),
                       "up_flex": np.zeros(144).tolist(),
                        "down_flex": np.zeros(144).tolist()})


def get_day_before(date):
    year = int(date.split("-")[0])
    month = int(date.split("-")[1])
    day = int(date.split("-")[2])

    date = datetime.date(year, month, day)
    date = date - datetime.timedelta(days=1)
    return date.strftime("%Y-%m-%d")

# @station_data.route("/chargers-by-transformers/grouped", methods=["POST"])
# def get_chargers_by_transformers_grouped():
#     db = current_app.config["station_data.db"]
#     print("Received request for chargers by transformers (grouped)")
#     try:
#         payload = request.get_json(force=True, silent=False)
#         transformer_ids = payload["transformer_ids"]
#         print(f"Received transformer_ids: {transformer_ids}")
#         if (not isinstance(transformer_ids, list)
#             or not transformer_ids
#             or not all(isinstance(tid, int) for tid in transformer_ids)):
#             raise ValueError
#     except Exception:
#         abort(400, 'Expected JSON body: {"transformer_ids": [int, ...]}')

#     stmt = (
#         select(GridConnection.transformer_id, GridConnection.column_id)
#         .where(GridConnection.transformer_id.in_(transformer_ids))
#     )
#     rows = db.session.execute(stmt).all()
#     print(f"Query returned {len(rows)} rows")
#     grouped = {}
#     for tf_id, cp_id in rows:
#         grouped.setdefault(tf_id, set()).add(cp_id)

#     # convert sets to sorted lists for JSON
#     grouped = {k: sorted(v) for k, v in grouped.items()}
    
#     #make a list of all unique charger ids
#     unique_chargers = sorted({cp for s in grouped.values() for cp in s})
    
#     print (f"Grouped data: {unique_chargers}")
    
#     return jsonify({
#         "transformer_ids": transformer_ids,
#         "chargers_by_transformer": unique_chargers, 
#         "count_total_unique_chargers": len(unique_chargers)
#     })

# routes/station_data.py
# from flask import Blueprint, request, jsonify, abort, current_app
# from sqlalchemy import select
# from backend.models import GridConnection, Column, ChargingPoint

# station_data = Blueprint("station_data", __name__)

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

