"""Prepare tomorrow's selectable scenarios outside the Flask/Gunicorn process."""

import argparse
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.session_sources import SessionSourceService, SOURCE_LABELS
from backend.spatial_profiles import DEFAULT_ATLAS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    timezone_name = os.environ.get("FLASK_SESSION_SCENARIO_TIMEZONE", "Europe/Amsterdam")
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--timezone", default=timezone_name)
    parser.add_argument("--daily-arrivals", type=float, default=float(os.environ.get("FLASK_SESSION_DAILY_ARRIVALS", "2")))
    parser.add_argument("--atlas", type=Path, default=Path(os.environ.get("FLASK_SESSION_SCENARIO_ATLAS", str(DEFAULT_ATLAS))))
    parser.add_argument("--source", choices=["all", *SOURCE_LABELS], default="all")
    parser.add_argument("--assumption", choices=["low", "base", "high"], default="base")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--database", type=Path, default=ROOT / "instance/default.sqlite")
    parser.add_argument("--cache", type=Path, default=Path(os.environ.get("FLASK_SESSION_SCENARIO_CACHE", str(ROOT / "instance/session_scenarios.sqlite"))))
    parser.add_argument("--point-ids", help="Optional comma-separated IDs; otherwise every point in the database")
    args = parser.parse_args()
    if args.date is None:
        args.date = datetime.now(ZoneInfo(args.timezone)).date()+timedelta(days=1)
    with sqlite3.connect(args.database.resolve().as_uri()+"?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        rows = connection.execute("SELECT p.id,p.power,p.type,l.latitude,l.longitude FROM charging_points p JOIN columns c ON p.column_id=c.id JOIN locations l ON c.location_id=l.id ORDER BY p.id").fetchall()
    if args.point_ids:
        requested = {int(value) for value in args.point_ids.split(",")}
        rows = [row for row in rows if row[0] in requested]
        if len(rows) != len(requested):
            parser.error("One or more point IDs do not exist")
    chargers = [dict(zip(["id", "power", "type", "latitude", "longitude"], row)) for row in rows]
    if not chargers:
        parser.error("No charging points to prepare")
    service = SessionSourceService(cache_path=args.cache, atlas_path=args.atlas, daily_arrivals=args.daily_arrivals)
    sources = list(SOURCE_LABELS) if args.source == "all" else [args.source]
    for source in sources:
        started = time.perf_counter()
        for offset in range(0, len(chargers), 64):
            _, metadata = service.get(chargers[offset:offset+64], args.date, source=source, assumption=args.assumption, seed=args.seed, timezone_name=args.timezone)
            print(json.dumps(dict(source=source, date=str(args.date), prepared=min(offset+64, len(chargers)), total=len(chargers),
                                  cache_hits=metadata["cache_hits"], seconds=round(time.perf_counter()-started, 2))), flush=True)


if __name__ == "__main__":
    main()
