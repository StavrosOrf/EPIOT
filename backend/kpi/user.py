"""KPI endpoint with inclusive local dates and selectable session sources."""

from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import select

from backend.cpft import day_window
from backend.cpft_runtime import CPFTUnavailable
from backend.kpi.statistics import calculate_kpis, days_between
from backend.models import ChargingPoint, Location, Session
from backend.scenario_sampling import ScenarioSession, UTC
from backend.session_sources import SessionSourceService, SOURCE_LABELS
from backend.spatial_profiles import DEFAULT_ATLAS
from backend.grid_data import app_grid_hours

kpi_data = Blueprint("kpi", "kpi")


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
    arguments = request.get_json(silent=True) if request.method == "POST" else request.args
    if arguments is None or not hasattr(arguments, "get"):
        return jsonify(error="Expected a JSON object"), 400
    try:
        timezone_name = current_app.config.get("SESSION_SCENARIO_TIMEZONE", "Europe/Amsterdam")
        zone = ZoneInfo(timezone_name)
        start_date = calendar_date(arguments.get("start_date"), zone)
        end_date = calendar_date(arguments.get("end_date"), zone)
        if end_date < start_date:
            raise ValueError("The end date must be on or after the start date")
        if end_date > datetime.now(zone).date():
            raise ValueError("KPI dates cannot be after today")
        source = str(arguments.get("session_source", "database")).strip()
        if source not in {"database", *SOURCE_LABELS}:
            raise ValueError("Unknown session source")
        assumption = arguments.get("demand_assumption", "base")
        if assumption not in {"low", "base", "high"}:
            raise ValueError("Unknown demand assumption")
        seed = int(arguments.get("seed", 42))
        if not 0 <= seed <= 2**32-1:
            raise ValueError("Seed must be an integer between 0 and 4294967295")
        markers = arguments.get("selected_markers", [])
        if isinstance(markers, str):
            markers = markers.strip().split(",") if markers.strip() else []
        if not isinstance(markers, list):
            raise ValueError("Selected markers must be IDs or a comma-separated string")
        ids = sorted({int(value) for value in markers})
        db = current_app.config["station_data.db"]
        rows = list(db.session.execute(select(ChargingPoint.id, ChargingPoint.power, ChargingPoint.type,
            Location.latitude, Location.longitude).join(ChargingPoint.column).join(Location)
            .where(ChargingPoint.id.in_(ids))))
        if len(rows) != len(ids):
            raise ValueError("One or more selected charging points are unavailable")
        chargers = [dict(id=row[0], power=row[1], type=row[2], latitude=row[3], longitude=row[4]) for row in rows]
        left, _ = day_window(start_date, timezone_name)
        _, right = day_window(end_date, timezone_name)
        mix = app_grid_hours(left, right, db.session,
            cache_path=current_app.config.get("GRID_DATA_CACHE", Path(current_app.instance_path)/"grid_data.sqlite"),
            allow_stale=current_app.config.get("GRID_ALLOW_STALE", True), timezone_name=timezone_name)
        metadata = dict(source=source, label=SOURCE_LABELS.get(source, "Stored sessions"),
            synthetic=source != "database", assumption=assumption if source != "database" else None,
            seed=seed, point_count=len(chargers), cache_hits=0,
            note="Synthetic scenarios with assumed demand, not verified local charging forecasts."
                 if source != "database" else "Stored session dataset; local charging observations are not verified.")
        if source == "database":
            # Existing Session timestamps are local, timezone-free datetimes.
            local_left = datetime.combine(start_date, time.min)
            local_right = datetime.combine(end_date+timedelta(days=1), time.min)
            stored = db.session.execute(select(Session.cp_id, Session.start, Session.end, Session.consumption)
                .where(Session.cp_id.in_(ids), Session.start < local_right, Session.end > local_left)).all()
            records = [ScenarioSession(cp_id, start.replace(tzinfo=zone).astimezone(UTC),
                       end.replace(tzinfo=zone).astimezone(UTC), float(energy or 0))
                       for cp_id, start, end, energy in stored if start and end and end > start and (energy or 0) >= 0]
            daily = ((day, records) for day in days_between(start_date, end_date))
        elif not chargers:
            daily = ((day, []) for day in days_between(start_date, end_date))
        else:
            service = current_app.extensions.get("session_source_service")
            if service is None:
                service = SessionSourceService(
                    cache_path=current_app.config.get("SESSION_SCENARIO_CACHE", Path(current_app.instance_path)/"session_scenarios.sqlite"),
                    atlas_path=current_app.config.get("SESSION_SCENARIO_ATLAS", DEFAULT_ATLAS),
                    daily_arrivals=float(current_app.config.get("SESSION_DAILY_ARRIVALS", 2.)))
                current_app.extensions["session_source_service"] = service
            def scenarios():
                for day in days_between(start_date, end_date):
                    records, daily_metadata = service.get(chargers, day, source=source, assumption=assumption,
                        seed=seed, timezone_name=timezone_name)
                    metadata["cache_hits"] += daily_metadata["cache_hits"]
                    metadata["label"], metadata["note"] = daily_metadata["label"], daily_metadata["note"]
                    yield day, records
            daily = scenarios()
        output = calculate_kpis(chargers, daily, start_date, end_date, timezone_name, mix)
        metadata["point_days"] = len(chargers)*output["range"]["day_count"]
        output["source"] = metadata
        return jsonify(output)
    except (ValueError, TypeError, KeyError) as exc:
        return jsonify(error=str(exc)), 400
    except CPFTUnavailable as exc:
        return jsonify(error=str(exc)), 503
    except (OSError, RuntimeError) as exc:
        current_app.logger.exception("KPI session source failed")
        return jsonify(error=f"KPI session source is unavailable: {exc}"), 503
