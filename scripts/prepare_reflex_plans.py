"""Optimise the cost strategies ahead of time, so the interface reads them from the plan store.

Minimum charging cost and V2G are optimised by the shared DRIVE2X ReFlex service.
Requests never wait for it: a connection ReFlex has not optimised yet shows
EPIOT's exact optimum until the application's background queue has replaced it
(V2G takes ReFlex about 3 s per connection). This script waits for ReFlex
instead, for chargers and dates chosen in advance, with the same sessions and
settings the application uses, so those requests show ReFlex's plans at once.

    uv run python scripts/prepare_reflex_plans.py --bbox 4.85,52.35,4.92,52.39 --from 2026-10-14 --to 2026-10-20

Plans are keyed by their inputs, so running it again only optimises what is
missing or still provisional, such as days whose day-ahead prices have been
published since. The
application database is opened read-only.
"""

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
from backend.cost_charging import MODES, CostOptimiser, CostSettings, PlanStore
from backend.day_ahead_prices import PriceStore
from backend.day_profile import local_window
from backend.session_sources import SessionSourceService
from backend.spatial_profiles import DEFAULT_ATLAS


def flask_setting(name, default=None):
    """A FLASK_-prefixed setting, parsed as JSON where possible, as the application reads it."""
    value = os.environ.get("FLASK_"+name)
    if value is None:
        return default
    try:
        return json.loads(value)
    except ValueError:
        return value


def points(database, ids=None, bbox=None):
    query = ("SELECT charging_points.id, charging_points.power, charging_points.type, locations.latitude, "
             "locations.longitude, locations.country FROM charging_points "
             "JOIN columns ON charging_points.column_id = columns.id JOIN locations ON columns.location_id = locations.id")
    if ids:
        query, parameters = query+f" WHERE charging_points.id IN ({','.join('?'*len(ids))})", ids
    else:
        west, south, east, north = bbox
        query += " WHERE locations.longitude BETWEEN ? AND ? AND locations.latitude BETWEEN ? AND ?"
        parameters = [west, east, south, north]
    with sqlite3.connect(Path(database).resolve().as_uri()+"?mode=ro", uri=True) as connection:
        rows = connection.execute(query, parameters).fetchall()
    return [dict(id=row[0], power=row[1], type=row[2], latitude=row[3], longitude=row[4], country=row[5])
            for row in rows]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--points", help="Comma-separated charging-point IDs")
    selection.add_argument("--bbox", help="west,south,east,north in degrees")
    parser.add_argument("--from", dest="first", type=date.fromisoformat, help="First target date (default: today)")
    parser.add_argument("--to", dest="last", type=date.fromisoformat, help="Last target date (default: tomorrow)")
    parser.add_argument("--strategy", nargs="+", choices=MODES, default=list(MODES))
    parser.add_argument("--source", nargs="+", choices=["simple", "spatial", "cpft"], default=["spatial"])
    parser.add_argument("--demand", nargs="+", choices=["low", "base", "high"], default=["base"])
    parser.add_argument("--seed", type=int, default=42, help="The interface uses 42")
    parser.add_argument("--draws", type=int, default=1, help="Seeds seed, seed+1, ... as in an ensemble request")
    parser.add_argument("--timeout", type=float, default=3600, help="Seconds to wait for ReFlex per strategy and source")
    parser.add_argument("--database", type=Path, default=ROOT/"instance/default.sqlite")
    parser.add_argument("--plan-store", type=Path,
                        default=Path(flask_setting("REFLEX_PLAN_STORE", ROOT/"instance/reflex_plans.sqlite")))
    parser.add_argument("--price-store", type=Path,
                        default=Path(flask_setting("DAY_AHEAD_PRICE_STORE", ROOT/"instance/day_ahead_prices.sqlite")))
    args = parser.parse_args(argv)

    timezone_name = flask_setting("SESSION_SCENARIO_TIMEZONE", "Europe/Amsterdam")
    today = datetime.now(ZoneInfo(timezone_name)).date()
    first, last = args.first or today, args.last or (args.first or today)+timedelta(days=1)
    if last < first:
        parser.error("--to is before --from")
    chargers = points(args.database, ids=[int(value) for value in args.points.split(",")] if args.points else None,
                      bbox=[float(value) for value in args.bbox.split(",")] if args.bbox else None)
    if not chargers:
        parser.error("No charging points match the selection")
    settings = CostSettings.from_config({key: value for key in (
        "REFLEX_V2G_DEPTH_KWH", "REFLEX_BATCH_SESSIONS", "REFLEX_V2G_BATCH_SESSIONS", "REFLEX_PARALLEL_RUNS")
        if (value := flask_setting(key)) is not None} | {"REFLEX_RUN_TIMEOUT": args.timeout})
    optimiser = CostOptimiser(PlanStore(args.plan_store), PriceStore(args.price_store), settings)
    service = SessionSourceService(atlas_path=flask_setting("SESSION_SCENARIO_ATLAS", DEFAULT_ATLAS),
                                   daily_arrivals=float(flask_setting("SESSION_DAILY_ARRIVALS", 2.)),
                                   calendar_effects=str(flask_setting("SESSION_CALENDAR_EFFECTS", True)).lower()
                                   not in ("0", "false", "no"))
    days = [first+timedelta(days=offset) for offset in range((last-first).days+1)]
    start, _, _, _ = local_window(first, timezone_name)
    _, end, _, _ = local_window(last, timezone_name)
    print(f"{len(chargers)} charging points, {len(days)} target dates from {first} to {last}", flush=True)
    for source in args.source:
        for demand in args.demand:
            # Each target date's two-day window is a draw; plans shared by neighbouring windows are made once
            frames = [service.get(chargers, day, source=source, assumption=demand, seed=(args.seed+offset) % 2**32,
                                  timezone_name=timezone_name)[0]
                      for day in days for offset in range(args.draws)]
            for strategy in args.strategy:
                began = time.monotonic()
                _, summary = optimiser.profiles(chargers, frames, start, end, strategy)
                print(f"{source}/{demand}/{strategy}: {summary['connections']} connections, "
                      f"{summary['from_store']} already stored, {summary['optimised_now']} optimised by ReFlex, "
                      f"{summary['reflex_plans_replaced']} replaced locally, {summary['energy_adjusted']} adjusted "
                      f"({time.monotonic()-began:.0f} s)", flush=True)


if __name__ == "__main__":
    main()
