"""Reproducible simple/spatial session scenarios using the existing CSV priors."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.special import ndtr

from backend.spatial_profiles import ARCHETYPES

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
ASSUMPTION_MULTIPLIERS = {"low": .5, "base": 1., "high": 1.5}
SAMPLER_VERSION = "spatial-priors-v1"


@dataclass(frozen=True)
class ScenarioSession:
    cp_id: int
    start: datetime
    end: datetime
    energy_kwh: float

    def __post_init__(self):
        if self.start.utcoffset() is None or self.end.utcoffset() is None or self.end <= self.start:
            raise ValueError("Scenario sessions require increasing timezone-aware timestamps")
        if not np.isfinite(self.energy_kwh) or self.energy_kwh < 0:
            raise ValueError("Scenario energy must be finite and nonnegative")


def point_power(charger):
    try:
        power = float(charger.get("power"))
    except (TypeError, ValueError):
        power = 11.
    return power if np.isfinite(power) and power > 0 else 11.


def point_rng(cp_id, source, start_date, seed):
    encoded = f"{SAMPLER_VERSION}|{int(cp_id)}|{source}|{start_date}|{int(seed)}".encode()
    return np.random.default_rng(int.from_bytes(hashlib.sha256(encoded).digest()[:8], "little"))


@lru_cache(maxsize=4)
def load_priors(directory=str(ROOT / "data")):
    directory = Path(directory)
    tables = {name: pd.read_csv(directory / filename) for name, filename in [
        ("weekday", "distribution-of-arrival.csv"), ("weekend", "distribution-of-arrival-weekend.csv"),
        ("duration", "distribution-of-connection-time.csv"), ("energy", "distribution-of-energy-demand.csv")]}
    for name in ["weekday", "weekend"]:
        if len(tables[name]) != 96:
            raise ValueError("Arrival priors must contain 96 quarter-hour rows")
    return tables


def quantile(table, column, probability):
    percentages = table["Percentage of charging events"].to_numpy(float)
    values = table[column].to_numpy(float)
    return float(np.interp((1-probability)*100, percentages, values))


def arrival_curve(priors, archetype, weekend):
    base_column = "workplace" if archetype == "workplace" else "public"
    table = priors["weekend" if weekend else "weekday"]
    # The bundled weekend table has no workplace column; retain the existing
    # sampler's public-profile fallback and document this borrowed prior.
    if base_column not in table:
        base_column = "public"
    mass = table[base_column].to_numpy(float).clip(min=0)
    mass = mass/mass.sum()
    hours = np.arange(96)/4
    if archetype in ("residential", "retail"):
        centre, width = (19., 3.) if archetype == "residential" else (13., 3.5)
        distances = np.minimum(abs(hours-centre), 24-abs(hours-centre))
        bump = np.exp(-.5*(distances/width)**2)
        mass = .35*mass+.65*bump/bump.sum()
    return mass/mass.sum()


def generate_sessions(charger, start, end, *, spatial_profile=None, seed=42, assumption="base",
                      timezone_name="Europe/Amsterdam", daily_arrivals=2., priors=None, source="simple"):
    """Attempt arrivals on UTC quarter-hours; occupancy blocks overlapping arrivals.

    Volume is an assumed attempted-arrival rate, not a guaranteed session count.
    Geographic coefficients, duration scales and copula correlation are priors.
    Three warm-up days carry overnight connections consistently into the window.
    """
    if assumption not in ASSUMPTION_MULTIPLIERS:
        raise ValueError("Unknown demand assumption")
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    if end <= start:
        raise ValueError("Scenario window must be increasing")
    priors = priors if priors is not None else load_priors()
    profile = spatial_profile or {"weights": {"mixed": 1.}, "arrival_multiplier": 1.}
    weights = np.array([profile["weights"].get(name, 0.) for name in ARCHETYPES], float)
    if not (np.isfinite(weights).all() and (weights >= 0).all() and weights.sum() > 0):
        raise ValueError("Invalid spatial mixture weights")
    weights /= weights.sum()
    rng = point_rng(charger["id"], source, start.isoformat(), seed)
    power = point_power(charger)
    volume = daily_arrivals*profile.get("arrival_multiplier", 1.)*ASSUMPTION_MULTIPLIERS[assumption]
    if not np.isfinite(volume) or volume < 0:
        raise ValueError("Invalid assumed arrival volume")
    timeline = pd.date_range(start-timedelta(days=3), end, inclusive="left", freq="15min", tz="UTC")
    local = timeline.tz_convert(timezone_name)
    sessions, free_at = [], start-timedelta(days=3)
    curves = {(kind, weekend): arrival_curve(priors, kind, weekend) for kind in ARCHETYPES for weekend in (False, True)}
    for day in sorted(set(local.date)):
        positions = np.flatnonzero(local.date == day)
        slots = local[positions].hour*4+local[positions].minute//15
        component = np.stack([curves[(kind, day.weekday() >= 5)][slots] for kind in ARCHETYPES])
        # Normalize against the full known calendar day, even when generation
        # ends at an 18:00 issue time. Ending earlier must not boost past demand.
        midnight = datetime.combine(day, datetime.min.time(), ZoneInfo(timezone_name)).astimezone(UTC)
        tomorrow = datetime.combine(day+timedelta(days=1), datetime.min.time(), ZoneInfo(timezone_name)).astimezone(UTC)
        full_day = pd.date_range(midnight, tomorrow, inclusive="left", freq="15min").tz_convert(timezone_name)
        full_slots = full_day.hour*4+full_day.minute//15
        normalizers = np.array([curves[(kind, day.weekday() >= 5)][full_slots].sum() for kind in ARCHETYPES])
        component /= normalizers[:, None]
        mixture = weights @ component
        for offset, pos in enumerate(positions):
            timestamp = timeline[pos].to_pydatetime()
            if timestamp < free_at or rng.random() >= -np.expm1(-volume*mixture[offset]):
                continue
            posterior = weights*component[:, offset]
            kind = ARCHETYPES[int(rng.choice(len(ARCHETYPES), p=posterior/posterior.sum()))]
            base_column = "workplace" if kind == "workplace" else "public"
            z1, z2 = rng.standard_normal(2)
            # Positive duration/energy dependence is assumed, not estimated.
            duration = quantile(priors["duration"], base_column, float(ndtr(z1)))
            energy = quantile(priors["energy"], base_column, float(ndtr(.4*z1+np.sqrt(1-.4**2)*z2)))
            duration *= {"residential": 1.4, "workplace": 1., "retail": .4, "mixed": 1.}[kind]
            if str(charger.get("type", "")).lower() == "fast":
                duration *= .6
            duration = float(np.clip(duration, .25, 72.))
            energy *= .75 if kind == "retail" else 1.
            energy = float(np.clip(energy, 0., power*duration))
            departure = timestamp+timedelta(hours=duration)
            free_at = departure
            if departure > start:
                sessions.append(ScenarioSession(int(charger["id"]), timestamp, departure, energy))
    return sessions


def session_to_dict(session):
    return dict(cp_id=session.cp_id, start=session.start.isoformat(), end=session.end.isoformat(), energy_kwh=session.energy_kwh)


def session_from_dict(value):
    return ScenarioSession(int(value["cp_id"]), datetime.fromisoformat(value["start"]), datetime.fromisoformat(value["end"]), float(value["energy_kwh"]))
