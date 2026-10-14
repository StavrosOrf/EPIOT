"""Selectable synthetic session sources, computed on the fly for any date.

There is no live charging feed, so nothing is forecast or generated on a
schedule and nothing is cached. Simple and spatial scenarios are views of one
fixed synthetic world (backend/scenario_world.py). CPFT scenarios sample real
checkpoint trajectories from the prebuilt library (backend/cpft_library.py).
A request's sessions depend only on its inputs, so repeating a request, or
asking for a day inside a longer range, returns identical sessions.

Day-level calendar effects (season, day of week, holidays, a common demand
shock and temperature; backend/scenario_calendar.py) apply to all three
sources and are reported per day in the response metadata.
"""

from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from backend.cpft_library import LIBRARY, get_library, sample_cpft
from backend.scenario_calendar import PARAMETERS, country_code, get_calendar
from backend.scenario_sampling import ASSUMPTION_MULTIPLIERS
from backend.scenario_world import MAX_HOURS, WORLD_VERSION, sample_world
from backend.session_frame import SessionFrame
from backend.spatial_profiles import DEFAULT_ATLAS, get_atlas

SOURCE_LABELS = {"simple": "Simple session sampler", "spatial": "Spatial session sampler", "cpft": "CPFT on synthetic histories"}
NOTES = {
    "simple": "Synthetic scenario from public arrival, duration and energy priors; demand levels are assumed, not calibrated to local charging observations.",
    "spatial": "Synthetic scenario; spatial effects and demand levels are assumed, not calibrated to local charging observations.",
    "cpft": "Existing CPFT checkpoints on spatial synthetic histories, sampled from a prebuilt trajectory library; occupied hours become approximate sessions. This is not a verified local forecast.",
}


def local_midnight(day, zone):
    return datetime.combine(day, time.min, zone)


class SessionSourceService:
    def __init__(self, atlas_path=DEFAULT_ATLAS, daily_arrivals=2., library_path=LIBRARY,
                 calendar_effects=True, calendar_path=PARAMETERS):
        self.atlas_path = Path(atlas_path)
        self.daily_arrivals = daily_arrivals
        self.library_path = Path(library_path)
        self.calendar_effects, self.calendar_path = calendar_effects, Path(calendar_path)

    def calendar(self):
        return get_calendar(self.calendar_path) if self.calendar_effects else None

    def countries(self, chargers, calendar):
        """ISO code per point; points without a known country use the calendar's default."""
        default = calendar.default if calendar else "NL"
        resolved = [country_code(charger.get("country"), default) for charger in chargers]
        return [code for code, _ in resolved], sum(not known for _, known in resolved)

    def calendar_metadata(self, calendar, countries, unknown, first, last, seed):
        if not calendar:
            return dict(calendar=dict(applied=False, note="Calendar, weather and demand effects are disabled."))
        days = {country: [summary for effects in [calendar.effects(country, first, last, seed)]
                          for summary in map(effects.summary, range(len(effects.days)))]
                for country in sorted(set(countries))}
        return dict(calendar=dict(applied=True, version=calendar.version, days=days, points_with_default_country=unknown,
                                  note="Synthetic day effects (season, day of week, holidays, common demand shock and weather) "
                                       "calibrated on ElaadNL 2019 open data and KNMI/ERA5 temperatures; not forecasts of real days."))

    def validate(self, source, assumption, seed):
        if source not in SOURCE_LABELS or assumption not in ASSUMPTION_MULTIPLIERS:
            raise ValueError("Unknown session source or demand assumption")
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**32-1:
            raise ValueError("Seed must be an integer between 0 and 4294967295")

    def profiles(self, chargers, source):
        if source == "simple" or not chargers:
            return None
        atlas = get_atlas(self.atlas_path)
        return [atlas.resolve(charger) for charger in chargers]

    def metadata(self, chargers, profiles, source, assumption, seed, timezone_name, frame, **extra):
        matched = sum(bool(profile and profile.get("matched")) for profile in profiles or ())
        values = dict(source=source, label=SOURCE_LABELS[source], synthetic=True, verified_observations=False,
                      generated="on request", assumption=assumption, seed=seed, scenario_version=WORLD_VERSION,
                      timezone=timezone_name, point_count=len(chargers), spatial_matched_points=matched,
                      spatial_fallback_points=len(chargers)-matched if source != "simple" else 0,
                      history_source="spatial synthetic sessions" if source == "cpft" else None,
                      session_count=len(frame), note=NOTES[source])
        values.update(extra)
        return values

    def prepare(self, chargers, source, assumption, seed):
        self.validate(source, assumption, seed)
        chargers = sorted(chargers, key=lambda charger: int(charger["id"]))
        if len({int(charger["id"]) for charger in chargers}) != len(chargers):
            raise ValueError("Duplicate charging-point IDs")
        calendar = self.calendar()
        countries, unknown = self.countries(chargers, calendar)
        return chargers, self.profiles(chargers, source), calendar, countries, unknown

    def cpft_day(self, chargers, profiles, day, assumption, seed, timezone_name, calendar, countries):
        library = get_library(self.library_path) if chargers else None
        return sample_cpft(chargers, day, profiles=profiles, seed=seed, assumption=assumption, daily_arrivals=self.daily_arrivals,
                           timezone_name=timezone_name, library=library, calendar=calendar, countries=countries)

    def get(self, chargers, target_date, *, source="simple", assumption="base", seed=42, timezone_name="Europe/Amsterdam"):
        """Sessions for the previous day and the target day, the load-profile window."""
        chargers, profiles, calendar, countries, unknown = self.prepare(chargers, source, assumption, seed)
        zone = ZoneInfo(timezone_name)
        start, end = local_midnight(target_date-timedelta(days=1), zone), local_midnight(target_date+timedelta(days=1), zone)
        extra = dict(target_date=str(target_date))
        if source == "cpft":
            frame, info = self.cpft_day(chargers, profiles, target_date, assumption, seed, timezone_name, calendar, countries)
            info.pop("calendar", None)
            extra.update(info)
        else:
            frame = sample_world(chargers, start, end, profiles=profiles, source=source, seed=seed, assumption=assumption,
                                 timezone_name=timezone_name, daily_arrivals=self.daily_arrivals, calendar=calendar, countries=countries)
        if chargers:
            extra.update(self.calendar_metadata(calendar, countries, unknown, target_date-timedelta(days=1), target_date, seed))
        return frame, self.metadata(chargers, profiles, source, assumption, seed, timezone_name, frame, **extra)

    def days(self, chargers, start_date, end_date, *, source="simple", assumption="base", seed=42, timezone_name="Europe/Amsterdam"):
        """(day, sessions) for each local day of an inclusive range, and the range's provenance.

        Simple and spatial ranges are one continuous window of the same world
        the single-day view shows. CPFT forecasts every day from its own
        18:00 issue the evening before, as the day-ahead model does.
        """
        chargers, profiles, calendar, countries, unknown = self.prepare(chargers, source, assumption, seed)
        zone = ZoneInfo(timezone_name)
        days = [start_date+timedelta(days=offset) for offset in range((end_date-start_date).days+1)]
        extra = dict(start_date=str(start_date), end_date=str(end_date))
        if chargers:
            extra.update(self.calendar_metadata(calendar, countries, unknown, start_date, end_date, seed))
        if source == "cpft":
            daily = []
            for day in days:
                frame, info = self.cpft_day(chargers, profiles, day, assumption, seed, timezone_name, calendar, countries)
                daily.append((day, frame))
            extra.update({key: info[key] for key in ("library_version", "built_at") if key in info})
            extra["issue_hour_local"] = 18
            frame = SessionFrame.concat([frame for _, frame in daily])
        else:
            frame = sample_world(chargers, local_midnight(start_date, zone), local_midnight(end_date+timedelta(days=1), zone),
                                 profiles=profiles, source=source, seed=seed, assumption=assumption, timezone_name=timezone_name,
                                 daily_arrivals=self.daily_arrivals, calendar=calendar, countries=countries)
            # Each day gets only the sessions that can touch it (none lasts over 72 hours)
            ordered = frame.select(np.argsort(frame.start, kind="stable"))
            daily = []
            for day in days:
                left, right = local_midnight(day, zone).timestamp(), local_midnight(day+timedelta(days=1), zone).timestamp()
                low, high = np.searchsorted(ordered.start, [left-MAX_HOURS*3600, right])
                daily.append((day, ordered.select(slice(low, high)).overlapping(left, right)))
        return daily, self.metadata(chargers, profiles, source, assumption, seed, timezone_name, frame, **extra)


def session_service(app):
    """The application's service, configured from Flask settings on first use."""
    service = app.extensions.get("session_source_service")
    if service is None:
        service = SessionSourceService(atlas_path=app.config.get("SESSION_SCENARIO_ATLAS", DEFAULT_ATLAS),
                                       daily_arrivals=float(app.config.get("SESSION_DAILY_ARRIVALS", 2.)),
                                       calendar_effects=str(app.config.get("SESSION_CALENDAR_EFFECTS", True)).lower() not in ("0", "false", "no"))
        app.extensions["session_source_service"] = service
    return service
