"""Selectable session sources and a separate SQLite cache of synthetic scenarios."""

from datetime import datetime, timedelta
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from backend.scenario_sampling import (
    ROOT, UTC, ASSUMPTION_MULTIPLIERS, generate_sessions, session_to_dict, session_from_dict, ScenarioSession,
)
from backend.spatial_profiles import DEFAULT_ATLAS, get_atlas

SOURCE_LABELS = {"simple": "Simple session sampler", "spatial": "Spatial session sampler", "cpft": "CPFT on synthetic histories"}


class ScenarioCache:
    """No observed Session rows are read or written by this cache."""
    def __init__(self, path):
        self.path = Path(path) if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.connect() as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("CREATE TABLE IF NOT EXISTS scenario_cache (cache_key TEXT PRIMARY KEY, source TEXT NOT NULL, target_date TEXT NOT NULL, cp_id INTEGER NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL)")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(str(self.path), timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def get(self, key):
        return self.get_many([key]).get(key)

    def get_many(self, keys):
        """Read a day's selection with one connection, below SQLite's bind limit."""
        keys = list(dict.fromkeys(keys))
        if not self.path or not keys:
            return {}
        values = {}
        with self.connect() as connection:
            for offset in range(0, len(keys), 900):
                batch = keys[offset:offset+900]
                rows = connection.execute(
                    f"SELECT cache_key,payload FROM scenario_cache WHERE cache_key IN ({','.join('?' for _ in batch)})", batch)
                values.update((key, json.loads(payload)) for key, payload in rows)
        return values

    def save(self, entries):
        if self.path and entries:
            with self.connect() as connection:
                connection.executemany("INSERT INTO scenario_cache VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(cache_key) DO NOTHING", entries)


class SessionSourceService:
    def __init__(self, cache_path=None, atlas_path=DEFAULT_ATLAS, runtime_factory=None, daily_arrivals=2.):
        self.cache = ScenarioCache(cache_path)
        self.atlas_path = Path(atlas_path)
        self.runtime_factory = runtime_factory
        self.daily_arrivals = daily_arrivals
        files = [ROOT / "backend" / name for name in ["scenario_sampling.py", "spatial_profiles.py", "cpft_runtime.py", "session_sources.py"]]
        files += [ROOT / "backend/data/cpft_preprocessing.json"]
        files += sorted((ROOT / "data").glob("distribution-of-*.csv"))
        self.version = hashlib.sha256(b"".join(path.read_bytes() for path in files)).hexdigest()[:16]

    def get(self, chargers, target_date, *, source="simple", assumption="base", seed=42, timezone_name="Europe/Amsterdam"):
        if source not in SOURCE_LABELS or assumption not in ASSUMPTION_MULTIPLIERS:
            raise ValueError("Unknown session source or demand assumption")
        if not isinstance(seed, int) or not 0 <= seed <= 2**32-1:
            raise ValueError("Seed must be an integer between 0 and 4294967295")
        zone = ZoneInfo(timezone_name)
        start = datetime.combine(target_date-timedelta(days=1), datetime.min.time(), zone).astimezone(UTC)
        end = datetime.combine(target_date+timedelta(days=1), datetime.min.time(), zone).astimezone(UTC)
        issue = datetime.combine(target_date-timedelta(days=1), datetime.min.time().replace(hour=18), zone).astimezone(UTC)
        chargers = sorted(chargers, key=lambda charger: int(charger["id"]))
        if len({int(charger["id"]) for charger in chargers}) != len(chargers):
            raise ValueError("Duplicate charging-point IDs")
        point_values, missing, profiles, keys = {}, [], {}, {}
        atlas = get_atlas(self.atlas_path) if source != "simple" and chargers else None
        model_files = None
        if source == "cpft" and chargers:
            from backend.cpft_runtime import MODEL_DIR
            model_files = {}
            for name in ["best_availability.keras", "best_kwh.keras"]:
                info = (MODEL_DIR/name).stat()
                model_files[name] = (info.st_mtime_ns, info.st_size)
        for charger in chargers:
            cp_id = int(charger["id"])
            profile = atlas.resolve(charger) if atlas else None
            profiles[cp_id] = profile
            identity = dict(source=source, date=str(target_date), charger=charger, profile=profile, assumption=assumption,
                            seed=seed, timezone=timezone_name, version=self.version, daily_arrivals=self.daily_arrivals)
            # Model replacement invalidates even a previously populated cache.
            if source == "cpft":
                identity["model_files"] = model_files
            key = hashlib.sha256(json.dumps(identity, sort_keys=True, allow_nan=False).encode()).hexdigest()
            keys[cp_id] = key
        cached = self.cache.get_many(keys.values())
        for charger in chargers:
            cp_id = int(charger["id"])
            if keys[cp_id] in cached:
                point_values[cp_id] = cached[keys[cp_id]]
            else:
                missing.append(charger)
        if source == "cpft" and missing:
            from backend.cpft_runtime import get_runtime, sessions_from_forecast
            histories = {int(charger["id"]): generate_sessions(charger, issue-timedelta(days=14), issue,
                spatial_profile=profiles[int(charger["id"])], seed=seed, assumption=assumption,
                timezone_name=timezone_name, daily_arrivals=self.daily_arrivals, source="cpft-history") for charger in missing}
            runtime = self.runtime_factory() if self.runtime_factory else get_runtime()
            # Bound memory and model batches even when a region contains many points.
            forecasts = {}
            for offset in range(0, len(missing), 64):
                forecasts.update(runtime.forecast(missing[offset:offset+64], histories, issue, end))
            for charger in missing:
                cp_id = int(charger["id"])
                past = [ScenarioSession(cp_id, session.start, min(session.end, issue),
                        session.energy_kwh if session.end <= issue else 0.)
                        for session in histories[cp_id] if session.start < issue and session.end > start]
                records = past+sessions_from_forecast(cp_id, forecasts[cp_id])
                point_values[cp_id] = {"sessions": [session_to_dict(record) for record in records],
                    "spatial_profile": profiles[cp_id], "forecast_hours": [dict(row, hour=row["hour"].isoformat()) for row in forecasts[cp_id]]}
        elif missing:
            for charger in missing:
                cp_id = int(charger["id"])
                records = generate_sessions(charger, start, end, spatial_profile=profiles[cp_id], seed=seed,
                    assumption=assumption, timezone_name=timezone_name, daily_arrivals=self.daily_arrivals, source=source)
                point_values[cp_id] = {"sessions": [session_to_dict(record) for record in records], "spatial_profile": profiles[cp_id]}
        now = datetime.now(UTC).isoformat()
        self.cache.save([(keys[int(charger["id"])], source, str(target_date), int(charger["id"]),
                          json.dumps(point_values[int(charger["id"])], allow_nan=False), now) for charger in missing])
        records = [session_from_dict(value) for cp_id in sorted(point_values) for value in point_values[cp_id]["sessions"]]
        records.sort(key=lambda record: (record.cp_id, record.start))
        matched = sum(bool(profile and profile.get("matched")) for profile in profiles.values())
        metadata = dict(source=source, label=SOURCE_LABELS[source], synthetic=True, verified_observations=False,
                        assumption=assumption, seed=seed, scenario_version=self.version, timezone=timezone_name,
                        target_date=str(target_date), issue_time=issue.isoformat() if source == "cpft" else None,
                        point_count=len(chargers), spatial_matched_points=matched,
                        spatial_fallback_points=len(chargers)-matched if source != "simple" else 0,
                        history_source="spatial synthetic sessions" if source == "cpft" else None,
                        session_count=len(records), cache_hits=len(chargers)-len(missing),
                        note="Synthetic scenarios; spatial effects and demand levels are assumed, not calibrated to local charging observations.")
        if source == "cpft":
            metadata["note"] = "Existing CPFT checkpoints on spatial synthetic histories; occupied hours become approximate sessions. This is not a verified local forecast."
        return records, metadata
