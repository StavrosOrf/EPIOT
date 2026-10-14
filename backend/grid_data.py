"""Free/local grid data with explicit missing values and historical references.

No network calls or paid API credentials are used, and nothing is refreshed on
a schedule. The separate SQLite store holds imported original observations;
any requested window is resolved from them on the fly, filling dates without
observations from a labelled historical reference. References never become
observations in the application database.
"""

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from functools import lru_cache
import csv
import json
import math
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from backend.scenario_sampling import UTC


def utc(value, *, legacy_naive=False):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        if not legacy_naive:
            raise ValueError("Grid timestamps must include a timezone")
        value = value.replace(tzinfo=UTC)
    value = value.astimezone(UTC)
    if value.minute or value.second or value.microsecond:
        raise ValueError("Grid timestamps must be hourly interval starts")
    return value


def number(value, upper=None):
    if value is None or value == "":
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 and (upper is None or value <= upper) else None


def flag(value):
    if value is None or value == "":
        return None
    if value in (True, 1, "true", "True", "1"):
        return True
    if value in (False, 0, "false", "False", "0"):
        return False
    raise ValueError("Estimated-data flags must be true, false or empty")


@dataclass(frozen=True)
class GridHour:
    timestamp: datetime
    co2_intensity: float | None
    renewable_percentage: float | None
    carbon_is_estimated: bool | None = None
    renewable_is_estimated: bool | None = None
    carbon_is_stale: bool = False
    renewable_is_stale: bool = False
    carbon_source_timestamp: datetime | None = None
    renewable_source_timestamp: datetime | None = None
    source: str = "local dataset"
    method: str = "historical hourly data"
    basis: str = "unknown"
    carbon_source: str | None = None
    renewable_source: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "timestamp", utc(self.timestamp))
        object.__setattr__(self, "co2_intensity", number(self.co2_intensity))
        object.__setattr__(self, "renewable_percentage", number(self.renewable_percentage, 100))
        if self.co2_intensity is not None and self.carbon_source is None:
            object.__setattr__(self, "carbon_source", self.source)
        if self.renewable_percentage is not None and self.renewable_source is None:
            object.__setattr__(self, "renewable_source", self.source)
        for field in ("carbon_source_timestamp", "renewable_source_timestamp"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, utc(value))

    def to_dict(self):
        value = asdict(self)
        for key in ("timestamp", "carbon_source_timestamp", "renewable_source_timestamp"):
            if value[key] is not None:
                value[key] = value[key].isoformat()
        return value

    @classmethod
    def from_dict(cls, value):
        value = dict(value)
        for key in ("timestamp", "carbon_source_timestamp", "renewable_source_timestamp"):
            if value.get(key) is not None:
                value[key] = utc(value[key])
        return cls(**value)


def legacy_hour(timestamp, renewable, carbon):
    timestamp = utc(timestamp, legacy_naive=True)
    return GridHour(timestamp, carbon, renewable, carbon_source_timestamp=timestamp,
        renewable_source_timestamp=timestamp, source="Existing Dutch PowerMix data",
        method="legacy hourly data; provider estimation flags were not retained", basis="consumption")


def complete_reference(hours, timezone_name="Europe/Amsterdam"):
    """Latest complete 24-hour profile, indexed by local clock hour.

    A DST-crossing window with a repeated/missing local hour is not a complete
    diurnal profile. All borrowed values retain their original timestamps.
    """
    zone = ZoneInfo(timezone_name)
    valid = sorted({hour.timestamp: hour for hour in hours if hour.co2_intensity is not None
        and hour.renewable_percentage is not None and not hour.carbon_is_stale and not hour.renewable_is_stale}.values(),
        key=lambda hour: hour.timestamp)
    for end in range(len(valid), 23, -1):
        window = valid[end-24:end]
        if all(right.timestamp-left.timestamp == timedelta(hours=1) for left, right in zip(window, window[1:])):
            profile = {hour.timestamp.astimezone(zone).hour: hour for hour in window}
            if len(profile) == 24:
                return profile
    return {}


def resolve_hours(hours, start, end, *, allow_stale=True, timezone_name="Europe/Amsterdam"):
    """Keep exact-date values; fill missing signals only with labelled references."""
    originals = {hour.timestamp: hour for hour in hours}
    reference = complete_reference(originals.values(), timezone_name) if allow_stale else {}
    zone = ZoneInfo(timezone_name)
    result, timestamp = [], utc(start)
    while timestamp < end:
        exact = originals.get(timestamp, GridHour(timestamp, None, None, method="missing"))
        borrowed = reference.get(timestamp.astimezone(zone).hour)
        changes = {}
        if borrowed is not None:
            for metric, estimated, stale, origin, provider in [
                ("co2_intensity", "carbon_is_estimated", "carbon_is_stale", "carbon_source_timestamp", "carbon_source"),
                ("renewable_percentage", "renewable_is_estimated", "renewable_is_stale", "renewable_source_timestamp", "renewable_source")]:
                if getattr(exact, metric) is None:
                    changes.update({metric: getattr(borrowed, metric), estimated: True, stale: True,
                        origin: borrowed.timestamp, provider: getattr(borrowed, provider)})
            if changes:
                changes.update(source=borrowed.source, method="historical diurnal reference; matched by local hour",
                               basis=borrowed.basis)
        result.append(replace(exact, **changes))
        timestamp += timedelta(hours=1)
    return result


class GridStore:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self, *, write=False):
        if write:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path) if write else self.path.resolve().as_uri()+"?mode=ro",
                                    uri=not write, timeout=30)
        try:
            with connection:
                if write:
                    connection.execute("PRAGMA journal_mode=WAL")
                    for table in ("grid_observations", "grid_hourly"):
                        connection.execute(f"CREATE TABLE IF NOT EXISTS {table} (zone TEXT NOT NULL, timestamp TEXT NOT NULL, payload TEXT NOT NULL, prepared_at TEXT NOT NULL, PRIMARY KEY(zone,timestamp))")
                yield connection
        finally:
            connection.close()

    def save(self, hours, *, zone="NL", observations=False):
        table = "grid_observations" if observations else "grid_hourly"
        now = datetime.now(UTC).isoformat()
        with self.connect(write=True) as connection:
            connection.executemany(f"INSERT INTO {table} VALUES (?,?,?,?) ON CONFLICT(zone,timestamp) DO UPDATE SET payload=excluded.payload,prepared_at=excluded.prepared_at",
                [(zone, hour.timestamp.isoformat(), json.dumps(hour.to_dict(), allow_nan=False), now) for hour in hours])

    def read(self, start=None, end=None, *, zone="NL", observations=False):
        if not self.path.exists():
            return []
        table = "grid_observations" if observations else "grid_hourly"
        query, params = f"SELECT payload FROM {table} WHERE zone=?", [zone]
        if start is not None:
            query += " AND timestamp>=?"
            params.append(utc(start).isoformat())
        if end is not None:
            query += " AND timestamp<?"
            params.append(utc(end).isoformat())
        with self.connect() as connection:
            return [GridHour.from_dict(json.loads(row[0])) for row in connection.execute(query+" ORDER BY timestamp", params)]


def read_csv(path):
    """Import an already available free/local hourly dataset, without API access."""
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not {"timestamp", "co2_intensity", "renewable_percentage"}.issubset(reader.fieldnames or []):
            raise ValueError("CSV requires timestamp, co2_intensity and renewable_percentage columns")
        rows = []
        for row in reader:
            if row.get("zone", "NL").upper() != "NL":
                raise ValueError("This grid pipeline requires a Dutch (NL) dataset")
            timestamp = utc(row["timestamp"])
            rows.append(GridHour(timestamp, number(row.get("co2_intensity")), number(row.get("renewable_percentage"), 100),
                flag(row.get("carbon_is_estimated", row.get("is_estimated"))),
                flag(row.get("renewable_is_estimated", row.get("is_estimated"))),
                carbon_source_timestamp=timestamp, renewable_source_timestamp=timestamp,
                source=row.get("source") or Path(path).name, basis=row.get("basis") or "unknown"))
        if len({row.timestamp for row in rows}) != len(rows):
            raise ValueError("CSV has duplicate hourly timestamps")
        return rows


@lru_cache(maxsize=4)
def _stored_observations(path, stamps):
    return tuple(GridStore(path).read(observations=True))


def stored_observations(path):
    """Imported observations, read again only when the store files change."""
    stamps = []
    for suffix in ("", "-wal"):
        try:
            info = Path(str(path)+suffix).stat()
        except FileNotFoundError:
            continue
        stamps.append((suffix, info.st_mtime_ns, info.st_size))
    return _stored_observations(str(path), tuple(stamps)) if stamps else ()


def app_grid_hours(start, end, db_session, *, cache_path, allow_stale=True, timezone_name="Europe/Amsterdam"):
    """Hourly grid values for any window, resolved on request from all observations."""
    from sqlalchemy import select
    from backend.models import PowerMix
    originals = {hour.timestamp: hour for hour in stored_observations(cache_path)}
    if db_session is not None:
        legacy = db_session.execute(select(PowerMix.datetime, PowerMix.renewable_percentage, PowerMix.co2_intensity)
            .where(PowerMix.country_zone == "NL").order_by(PowerMix.datetime)).all()
        for row in legacy:
            hour = legacy_hour(*row)
            originals.setdefault(hour.timestamp, hour)
    return resolve_hours(originals.values(), start, end, allow_stale=allow_stale, timezone_name=timezone_name)
