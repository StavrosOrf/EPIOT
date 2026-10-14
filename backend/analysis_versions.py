"""Cheap file/configuration revisions for the browser's bounded analysis caches."""

import hashlib
import json
from pathlib import Path

from backend.scenario_sampling import ROOT
from backend.spatial_profiles import DEFAULT_ATLAS
from backend.charger_sources import MANIFEST


def file_stamp(path):
    path = Path(path)
    try:
        info = path.stat()
        return str(path), info.st_mtime_ns, info.st_size
    except FileNotFoundError:
        return str(path), None, None


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:24]


def analysis_versions(app):
    database = app.config["station_data.db"].session.get_bind().url.database
    infrastructure = [file_stamp(MANIFEST), app.config.get("ANALYSIS_DATA_REVISION", "")]
    if database and database != ":memory:":
        infrastructure += [file_stamp(database), file_stamp(str(database)+"-wal")]
    grid_path = app.config.get("GRID_DATA_CACHE", Path(app.instance_path)/"grid_data.sqlite")
    paths = list((ROOT/"backend").glob("*.py")) + list((ROOT/"backend/kpi").glob("*.py"))
    paths += list((ROOT/"seed_data").glob("distribution-of-*.csv"))
    paths += [ROOT/"backend/data/cpft_preprocessing.json", ROOT/"backend/data/cpft_library.npz", ROOT/"backend/data/calendar_effects.json",
              app.config.get("SESSION_SCENARIO_ATLAS", DEFAULT_ATLAS), grid_path, str(grid_path)+"-wal"]
    model_dir = ROOT/"others/CPFT-main/CPFT-tool/CPFT_VS_Code_Python/outputs"
    paths += [model_dir/name for name in ("best_availability.keras", "best_kwh.keras")]
    configuration = {key: app.config.get(key) for key in (
        "SESSION_SCENARIO_TIMEZONE", "SESSION_DAILY_ARRIVALS", "SESSION_CALENDAR_EFFECTS", "GRID_ALLOW_STALE", "aggregator_config")}
    return dict(infrastructure=digest(infrastructure),
                analysis=digest([infrastructure, configuration, [file_stamp(path) for path in paths]]))
