"""KPI endpoint with inclusive local dates and selectable session sources."""

from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import select

from backend.cpft import day_window
from backend.cpft_runtime import CPFTUnavailable
from backend.kpi.statistics import calculate_kpis, calculate_environment_kpis, days_between
from backend.models import ChargingPoint, Location
from backend.stored_sessions import STORED_LABEL, STORED_NOTE, stored_records
from backend.request_args import (RequestTooLarge, check_point_days, demand_assumption, request_arguments,
                                  scenario_seed, session_source)
from backend.session_sources import SOURCE_LABELS, session_service
from backend.grid_data import app_grid_hours

kpi_data = Blueprint("kpi", "kpi")
MAX_RANGE_DAYS = 366


def calendar_date(value, zone):
    """Accept calendar dates and convert legacy aware timestamps to local dates."""
    if not isinstance(value, str) or not value:
        raise ValueError("Both a start date and an end date are required")
    try:
        return date.fromisoformat(value)
    except ValueError:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(zone).date() if parsed.tzinfo else parsed.date()


@kpi_data.route("/user", methods=["GET", "POST"])
def get_user_kpi():
    try:
        arguments = request_arguments(request)
        section = arguments.get("section", "all")
        if section not in {"all", "basic", "environment"}:
            raise ValueError("Unknown KPI section")
        timezone_name = current_app.config.get("SESSION_SCENARIO_TIMEZONE", "Europe/Amsterdam")
        zone = ZoneInfo(timezone_name)
        start_date = calendar_date(arguments.get("start_date"), zone)
        end_date = calendar_date(arguments.get("end_date"), zone)
        if end_date < start_date:
            raise ValueError("The end date must be on or after the start date")
        # Synthetic scenarios have no "today": any date is only a calendar context
        if (end_date-start_date).days >= MAX_RANGE_DAYS:
            raise ValueError(f"KPI ranges are limited to {MAX_RANGE_DAYS} days")
        source = session_source(arguments)
        assumption = demand_assumption(arguments)
        seed = scenario_seed(arguments)
        markers = arguments.get("selected_markers", [])
        if isinstance(markers, str):
            markers = markers.strip().split(",") if markers.strip() else []
        if not isinstance(markers, list):
            raise ValueError("Selected markers must be IDs or a comma-separated string")
        ids = sorted({int(value) for value in markers})
        check_point_days(current_app.config, len(ids), (end_date-start_date).days+1)
        db = current_app.config["station_data.db"]
        rows = list(db.session.execute(select(ChargingPoint.id, ChargingPoint.power, ChargingPoint.type,
            Location.latitude, Location.longitude, Location.country).join(ChargingPoint.column).join(Location)
            .where(ChargingPoint.id.in_(ids))))
        if len(rows) != len(ids):
            raise ValueError("One or more selected charging points are unavailable")
        chargers = [dict(id=row[0], power=row[1], type=row[2], latitude=row[3], longitude=row[4], country=row[5]) for row in rows]
        left, _ = day_window(start_date, timezone_name)
        _, right = day_window(end_date, timezone_name)
        mix = app_grid_hours(left, right, db.session,
            cache_path=current_app.config.get("GRID_DATA_CACHE", Path(current_app.instance_path)/"grid_data.sqlite"),
            allow_stale=current_app.config.get("GRID_ALLOW_STALE", True), timezone_name=timezone_name) if section != "basic" else ()
        metadata = dict(source=source, label=SOURCE_LABELS.get(source, STORED_LABEL),
            synthetic=source != "database", assumption=assumption if source != "database" else None,
            seed=seed, point_count=len(chargers),
            note="Synthetic scenarios with assumed demand, not verified local charging forecasts."
                 if source != "database" else STORED_NOTE)
        if source == "database":
            # Existing Session timestamps are local, timezone-free datetimes.
            local_left = datetime.combine(start_date, time.min)
            local_right = datetime.combine(end_date+timedelta(days=1), time.min)
            records = stored_records(db.session, ids, local_left, local_right, zone)
            daily = ((day, records) for day in days_between(start_date, end_date))
        elif not chargers:
            daily = ((day, []) for day in days_between(start_date, end_date))
        else:
            # Generated on request for the whole range: one view of the same scenario
            daily, generated = session_service(current_app).days(chargers, start_date, end_date, source=source,
                assumption=assumption, seed=seed, timezone_name=timezone_name)
            metadata.update(generated)
        if section == "environment":
            output = calculate_environment_kpis(chargers, daily, timezone_name, mix)
        else:
            output = calculate_kpis(chargers, daily, start_date, end_date, timezone_name, mix,
                                    include_environment=section != "basic")
        metadata["point_days"] = len(chargers)*((end_date-start_date).days+1)
        output["source"] = metadata
        output["section"] = section
        return jsonify(output)
    except RequestTooLarge as exc:
        return jsonify(error=str(exc)), 422
    except (ValueError, TypeError, KeyError) as exc:
        return jsonify(error=str(exc)), 400
    except CPFTUnavailable as exc:
        return jsonify(error=str(exc)), 503
    except (OSError, RuntimeError) as exc:
        current_app.logger.exception("KPI session source failed")
        return jsonify(error=f"KPI session source is unavailable: {exc}"), 503
