"""Prepare hourly Dutch grid data from free/local files and stale references."""

import argparse
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.cpft import day_window
from backend.grid_data import GridStore, legacy_hour, read_csv, resolve_hours


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT/"instance/default.sqlite")
    parser.add_argument("--cache", type=Path, default=Path(os.environ.get("FLASK_GRID_DATA_CACHE", str(ROOT/"instance/grid_data.sqlite"))))
    parser.add_argument("--csv", type=Path, default=os.environ.get("EPIOT_GRID_CSV"))
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--no-stale", action="store_true")
    parser.add_argument("--timezone", default="Europe/Amsterdam")
    args = parser.parse_args(argv)
    today = datetime.now(ZoneInfo(args.timezone)).date()
    with sqlite3.connect(args.database.resolve().as_uri()+"?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        rows = connection.execute("SELECT datetime,renewable_percentage,co2_intensity FROM power_mixes WHERE country_zone='NL' ORDER BY datetime").fetchall()
        first = connection.execute("SELECT date(MIN(start)) FROM sessions").fetchone()[0]
    originals = {hour.timestamp: hour for hour in map(lambda row: legacy_hour(*row), rows)}
    store = GridStore(args.cache)
    for hour in store.read(observations=True):
        originals[hour.timestamp] = hour
    if args.csv:
        for hour in read_csv(args.csv):
            originals[hour.timestamp] = hour
    store.save(originals.values(), observations=True)
    start_date = args.start or (date.fromisoformat(first) if args.backfill and first else today-timedelta(days=7))
    end_date = args.end or today+timedelta(days=1)
    if start_date > end_date:
        parser.error("Start date must be on or before end date")
    start, _ = day_window(start_date, args.timezone)
    _, end = day_window(end_date, args.timezone)
    hours = resolve_hours(originals.values(), start, end, allow_stale=not args.no_stale, timezone_name=args.timezone)
    store.save(hours)
    report = dict(start=str(start_date), end=str(end_date), hours=len(hours), original_hours=len(originals),
        carbon_reference_hours=sum(hour.carbon_is_stale for hour in hours),
        renewable_reference_hours=sum(hour.renewable_is_stale for hour in hours),
        missing_carbon_hours=sum(hour.co2_intensity is None for hour in hours),
        missing_renewable_hours=sum(hour.renewable_percentage is None for hour in hours),
        source="free/local data only; no paid API", cache=str(args.cache))
    print(json.dumps(report), flush=True)
    return report


if __name__ == "__main__":
    main()
