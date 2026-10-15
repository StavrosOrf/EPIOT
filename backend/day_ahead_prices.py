"""Day-ahead prices on EPIOT's 10-minute grid, kept in a local store.

Prices are fetched from Energy-Charts once and kept in a small SQLite file, so a
request for a known day never leaves the server. A step without a published
price (a future day, or a gap in the feed) takes the price at the same time on
the nearest day within a week that has one, or, further ahead, on the latest
day with prices, and is flagged as such, as the grid data do with their
historical reference.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from threading import Lock
import time

import numpy as np

from backend.api_calls.prices import PriceFeedError, fetch_day_ahead_prices

STEP = 600
DAY = 86400
REFERENCE_DAYS = 7      # how far a missing step looks for the same time on another day
RETRY_SECONDS = 900     # a day without (or failing) data is asked for again after this
MAX_FETCH_DAYS = 62

# Energy-Charts bidding zones of the countries in the charger registers.
# Countries without a zone of their own (the United Kingdom left the coupled
# market) and points without a country use the Dutch zone; the response says so.
DEFAULT_ZONE = "NL"
COUNTRY_ZONES = {
    "Netherlands": "NL", "Germany": "DE-LU", "Luxembourg": "DE-LU", "France": "FR", "Belgium": "BE",
    "Switzerland": "CH", "Liechtenstein": "CH", "Austria": "AT", "Finland": "FI", "Portugal": "PT",
    "Spain": "ES", "Italy": "IT-North", "Poland": "PL", "Czechia": "CZ", "Czech Republic": "CZ",
    "Denmark": "DK1", "Norway": "NO2", "Sweden": "SE3", "Hungary": "HU", "Slovenia": "SI",
}


class PricesUnavailable(RuntimeError):
    """No published or reference day-ahead price exists for part of the window."""


def price_zone(country):
    """(bidding zone, whether it is the default stand-in) for a country name."""
    zone = COUNTRY_ZONES.get(country)
    return (zone, False) if zone else (DEFAULT_ZONE, True)


class PriceStore:
    """Quarter-hourly or hourly points per zone; `prices()` resolves any window."""

    def __init__(self, path, *, fetch=fetch_day_ahead_prices, clock=time.time):
        self.path = Path(path)
        self.fetch = fetch
        self.clock = clock
        self.lock = Lock()
        self.attempts = {}  # (zone, UTC day) -> time of the last fetch

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            with connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("CREATE TABLE IF NOT EXISTS prices (zone TEXT NOT NULL, unix INTEGER NOT NULL, "
                                   "seconds INTEGER NOT NULL, price REAL NOT NULL, PRIMARY KEY(zone, unix))")
                yield connection
        finally:
            connection.close()

    def points(self, zone, left, right):
        with self.connect() as connection:
            rows = connection.execute("SELECT unix, seconds, price FROM prices WHERE zone=? AND unix>=? AND unix<? "
                                      "ORDER BY unix", (zone, int(left)-3600, int(right))).fetchall()
        return np.array(rows, float).reshape(-1, 3)

    def newest_day(self, zone):
        """Start of the latest UTC day with prices for every step, or None."""
        with self.connect() as connection:
            (latest,) = connection.execute("SELECT max(unix) FROM prices WHERE zone=?", (zone,)).fetchone()
        if latest is None:
            return None
        for day in range(int(latest)//DAY*DAY, int(latest)//DAY*DAY-3*DAY, -DAY):
            if np.isfinite(self.lookup(self.points(zone, day, day+DAY), day+np.arange(0, DAY, STEP))).all():
                return day
        return None

    def save(self, zone, points):
        """Store fetched points; each lasts until the next one, at most an hour."""
        if not points:
            return
        unix = np.array([point[0] for point in points], np.int64)
        gaps = np.diff(unix)
        seconds = np.minimum(np.append(gaps, gaps[-1] if len(gaps) else 3600), 3600)
        with self.connect() as connection:
            connection.executemany(
                "INSERT INTO prices VALUES (?,?,?,?) ON CONFLICT(zone, unix) DO UPDATE SET "
                "seconds=excluded.seconds, price=excluded.price",
                [(zone, int(stamp), int(length), float(price))
                 for stamp, length, (_, price) in zip(unix, seconds, points) if length > 0])

    @staticmethod
    def lookup(points, steps):
        """Time-weighted mean price of each 10-minute step, NaN where any part is unknown.

        Price intervals start on 5-minute boundaries, so each 5-minute half of a
        step lies inside one interval and the mean of the halves is exact.
        """
        if not len(points):
            return np.full(len(steps), np.nan)
        unix, seconds, price = points.T
        halves = []
        for offset in (STEP/4, 3*STEP/4):
            moment = steps+offset
            index = np.searchsorted(unix, moment, "right")-1
            found = (index >= 0) & (moment < unix[np.maximum(index, 0)]+seconds[np.maximum(index, 0)])
            halves.append(np.where(found, price[np.maximum(index, 0)], np.nan))
        return (halves[0]+halves[1])/2

    def _fetch_missing(self, zone, steps, missing):
        """Ask Energy-Charts once for the days that are absent and could be published."""
        now = self.clock()
        latest = (int(now)//DAY+1)*DAY  # tomorrow's auction is the last one published
        days = sorted({int(step)//DAY*DAY for step in steps[missing]})
        # The days before also serve as references for the ones not published yet, and the
        # latest auctions for days further ahead than that
        wanted = {day-offset*DAY for day in days for offset in range(REFERENCE_DAYS+1)}
        if days[-1] > latest:
            wanted |= {latest-offset*DAY for offset in range(REFERENCE_DAYS+1)}
        wanted = sorted(wanted)
        wanted = [day for day in wanted if day <= latest
                  and now-self.attempts.get((zone, day), -np.inf) > RETRY_SECONDS]
        if not wanted:
            return
        stored = self.points(zone, wanted[0], wanted[-1]+DAY)
        wanted = [day for day in wanted
                  if not np.isfinite(self.lookup(stored, day+np.arange(0, DAY, STEP))).all()]
        if not wanted:
            return
        first, last = wanted[0], wanted[-1]
        first = max(first, last-(MAX_FETCH_DAYS-1)*DAY)
        start = datetime.fromtimestamp(first, timezone.utc)
        end = datetime.fromtimestamp(last+DAY-60, timezone.utc)
        self.save(zone, self.fetch(zone, start, end))
        # Only an answer counts as an attempt: after a failure the next request tries again
        for day in range(first, last+DAY, DAY):
            self.attempts[(zone, day)] = now

    def prices(self, zone, first_step, count):
        """(EUR/MWh per step, reference flag per step) for `count` steps from step index `first_step`.

        Step k covers [600k, 600k+600) UTC epoch seconds.
        """
        steps = (first_step+np.arange(count))*STEP
        left, right = steps[0]-REFERENCE_DAYS*DAY, steps[-1]+STEP+REFERENCE_DAYS*DAY
        with self.lock:
            points = self.points(zone, left, right)
            values = self.lookup(points, steps)
            missing = ~np.isfinite(values)
            failure = None
            if missing.any():
                try:
                    self._fetch_missing(zone, steps, missing)
                except PriceFeedError as exc:
                    failure = exc  # references below, or PricesUnavailable
                points = self.points(zone, left, right)
                values = self.lookup(points, steps)
        reference = ~np.isfinite(values)
        if reference.any():
            # The same time on the nearest earlier day, then the nearest later one
            for offset in [-day*DAY for day in range(1, REFERENCE_DAYS+1)]+[day*DAY for day in range(1, REFERENCE_DAYS+1)]:
                gap = ~np.isfinite(values)
                if not gap.any():
                    break
                values[gap] = self.lookup(points, steps[gap]+offset)
        gap = ~np.isfinite(values)
        if gap.any():
            # Further ahead than that: the same time on the latest day with a full set of prices
            newest = self.newest_day(zone)
            if newest is not None:
                day = self.points(zone, newest, newest+DAY)
                values[gap] = self.lookup(day, newest+steps[gap] % DAY)
        if not np.isfinite(values).all():
            raise PricesUnavailable(f"No day-ahead prices for the {zone} bidding zone near this window "
                                    f"or stored at all ({failure or 'none published'}).")
        return values, reference
