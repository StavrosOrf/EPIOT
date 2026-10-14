"""Session records, priors and arrival curves shared by the synthetic scenarios."""

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
PRIORS = ROOT / "seed_data"
ASSUMPTION_MULTIPLIERS = {"low": .5, "base": 1., "high": 1.5}


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


@lru_cache(maxsize=4)
def load_priors(directory=str(PRIORS)):
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
    """One point's sessions connected during [start, end), from its synthetic world.

    A convenience view of backend.scenario_world.sample_world, which samples
    many points at once. Volume is an assumed attempted-arrival rate, not a
    guaranteed session count. Geographic coefficients, duration scales and
    copula correlation are priors.
    """
    from backend.scenario_world import sample_world
    return sample_world([charger], start, end, profiles=[spatial_profile], source=source, seed=seed, assumption=assumption,
                        timezone_name=timezone_name, daily_arrivals=daily_arrivals, priors=priors).records()
