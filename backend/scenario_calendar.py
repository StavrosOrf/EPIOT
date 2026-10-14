"""Day-level calendar, weather and demand effects for synthetic charging scenarios.

Independent per-point randomness averages out over an area, so without common
day-level effects every weekday of a large selection looks the same. Real
charging demand varies from day to day through effects shared by all points:

- season (annual harmonics) and day of week, scaling the attempted-arrival rate;
- public holidays, which take Sunday's arrival pattern and level (adjusted by
  their own effect); bridge days and partial holidays mix the two regimes;
- a common demand shock: mean-one log-normal AR(1), so busy and quiet spells
  last a few days (negative-binomial day counts, as observed);
- daily mean temperature from a stochastic weather generator (climatological
  mean and spread plus AR(1) anomalies), raising energy per session on cold and
  hot days.

Parameters come from scripts/calibrate_calendar_effects.py (ElaadNL 2019 open
data, KNMI and ERA5 temperatures) and are stored in calendar_effects.json. Every
random quantity is hashed from (country, date, seed), so any date is
reproducible and independent of the requested window. Factors are normalized
so that the long-run averages of the bundled ElaadNL priors are preserved.
See docs/concepts/calendar-effects.md.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
import json
from pathlib import Path

import holidays as holiday_data
import numpy as np
from scipy.special import ndtri

from backend.random_streams import text_key, uniforms

ROOT = Path(__file__).resolve().parents[1]
PARAMETERS = ROOT/"backend/data/calendar_effects.json"
# Holidays that are official but not a general day off (NL: depends on the collective agreement)
PARTIAL_HOLIDAYS = {"NL": {"Goede vrijdag"}}
NORMALIZATION_YEARS = (2020, 2039)
SHOCK_TOLERANCE = 1e-6


def country_code(value, default="NL"):
    """ISO code for a stored country name or code; unknown values use the default."""
    from backend.charger_sources import COUNTRY_NAMES
    if not value:
        return default, False
    value = str(value).strip()
    if value.upper() in COUNTRY_NAMES:
        return value.upper(), True
    codes = {name.lower(): code for code, name in COUNTRY_NAMES.items()}
    return (codes[value.lower()], True) if value.lower() in codes else (default, False)


class holiday_calendar:
    """Day types of one country: workday, weekend, holiday or partial (bridge day / partial holiday)."""
    def __init__(self, country, partial_weight=.5):
        self.country, self.partial_weight = country, partial_weight
        self.partial_names = PARTIAL_HOLIDAYS.get(country, set())
        self.holidays = holiday_data.country_holidays(country)

    def name(self, day):
        return self.holidays.get(day) or ("Bridge day" if self.bridge(day) else "")

    def full(self, day):
        names = self.holidays.get(day)
        return bool(names) and not all(name.strip() in self.partial_names for name in names.split(";"))

    def bridge(self, day):
        """A Monday before or a Friday after a holiday on a weekday."""
        return ((day.weekday() == 0 and self.full(day+timedelta(days=1)))
                or (day.weekday() == 4 and self.full(day-timedelta(days=1))))

    def kind(self, day):
        if self.full(day):
            return "holiday"
        if day.weekday() >= 5:
            return "weekend"
        return "partial" if day in self.holidays or self.bridge(day) else "workday"


@dataclass(frozen=True)
class DayEffects:
    """Effects for consecutive local days; arrays are indexed by day."""
    days: list
    kind: list
    name: list
    weekend_share: np.ndarray  # share of arrivals following the weekend/holiday arrival curve
    volume: np.ndarray         # attempted-arrival multiplier, long-run mean one
    temperature: np.ndarray    # synthetic daily mean temperature, degC
    energy: np.ndarray         # energy-per-session multiplier, long-run mean one in NL

    def at(self, day):
        return (day-self.days[0]).days

    def summary(self, index):
        return dict(date=str(self.days[index]), day_type=self.kind[index], holiday=self.name[index] or None,
                    volume_factor=round(float(self.volume[index]), 3), temperature_c=round(float(self.temperature[index]), 1),
                    energy_factor=round(float(self.energy[index]), 3))


def neutral_effects(first, last):
    """No day-level effects: weekends by calendar only, all factors one."""
    days = [first+timedelta(days=offset) for offset in range((last-first).days+1)]
    weekend = np.array([day.weekday() >= 5 for day in days], float)
    ones = np.ones(len(days))
    return DayEffects(days, ["weekend" if value else "workday" for value in weekend], [""]*len(days),
                      weekend, ones, np.full(len(days), np.nan), ones)


def ar1(keys, ordinals, phi, label):
    """Unit-variance stationary AR(1) on day ordinals, as a truncated moving average.

    x_d = sqrt(1-phi^2) sum_k phi^k e_{d-k}, with e hashed per day, so any day's
    value is computed from its own past without simulating from a start date.
    """
    lags = max(1, int(np.ceil(np.log(SHOCK_TOLERANCE)/np.log(max(phi, 1e-9))))) if phi > 0 else 0
    weights = phi**np.arange(lags+1)
    weights *= np.sqrt((1-phi**2)/(1-phi**(2*(lags+1)))) if phi > 0 else 1.
    span = np.arange(ordinals[0]-lags, ordinals[-1]+1)
    noise = ndtri(uniforms(np.full(len(span), keys[label]), span, 0))
    return np.convolve(noise, weights, mode="valid")


def harmonic_terms(day_of_year, count):
    angle = 2*np.pi*np.asarray(day_of_year, float)/365.25
    return np.column_stack([f(k*angle) for k in range(1, count+1) for f in (np.cos, np.sin)])


class CalendarEffects:
    def __init__(self, path=PARAMETERS):
        self.path = Path(path)
        self.parameters = json.loads(self.path.read_text(encoding="utf-8"))
        self.version = self.parameters["version"]
        demand = self.parameters["demand"]
        self.seasonal = np.asarray(demand["seasonal_harmonics"], float)
        self.weekday = np.exp(np.asarray(demand["weekday_log"], float))
        self.holiday = self.weekday[6]*np.exp(demand["holiday_log"])
        self.sigma, self.phi = demand["shock_sigma"], demand["shock_phi"]
        self.partial_weight = self.parameters["holidays"]["partial_weight"]
        self.energy_parameters = self.parameters["energy"]
        self.climate = self.parameters["climate"]
        self.default = self.parameters["default_country"]
        self._calendars, self._normalizers = {}, {}

    def calendar(self, country):
        if country not in self._calendars:
            self._calendars[country] = holiday_calendar(country, self.partial_weight)
        return self._calendars[country]

    def season(self, days):
        doy = np.array([day.timetuple().tm_yday for day in days])
        return np.exp(harmonic_terms(doy, len(self.seasonal)//2) @ self.seasonal)

    def regimes(self, country, days):
        """Expected volume (before season and shock) and weekend share for each day type."""
        calendar = self.calendar(country)
        kinds = [calendar.kind(day) for day in days]
        volume, weekend = np.empty(len(days)), np.empty(len(days))
        for index, (day, kind) in enumerate(zip(days, kinds)):
            regular = self.weekday[day.weekday()]
            if kind == "holiday":
                volume[index], weekend[index] = self.holiday, 1.
            elif kind == "partial":
                # A share of the population behaves as on a holiday
                share = self.partial_weight
                volume[index] = (1-share)*regular+share*self.holiday
                weekend[index] = share*self.holiday/volume[index]
            else:
                volume[index], weekend[index] = regular, float(day.weekday() >= 5)
        return kinds, [calendar.name(day) for day in days], volume, weekend

    def normalizer(self, country):
        """Mean of season x day-type volume over twenty years, so the long-run mean volume is one."""
        if country not in self._normalizers:
            first, last = date(NORMALIZATION_YEARS[0], 1, 1), date(NORMALIZATION_YEARS[1], 12, 31)
            days = [first+timedelta(days=offset) for offset in range((last-first).days+1)]
            self._normalizers[country] = float(np.mean(self.season(days)*self.regimes(country, days)[2]))
        return self._normalizers[country]

    def temperature_climate(self, country, days):
        climate = self.climate.get(country) or self.climate[self.default]
        doy = np.array([day.timetuple().tm_yday for day in days])
        mean = np.column_stack([np.ones(len(days)), harmonic_terms(doy, (len(climate["mean_harmonics"])-1)//2)]) @ climate["mean_harmonics"]
        variance = np.column_stack([np.ones(len(days)), harmonic_terms(doy, (len(climate["variance_harmonics"])-1)//2)]) @ climate["variance_harmonics"]
        return mean, np.sqrt(np.maximum(variance, .25)), climate["ar1"]

    def energy_response(self, temperature):
        p = self.energy_parameters
        return np.exp(p["heating_log_per_c"]*np.maximum(0., p["heating_base_c"]-temperature)
                      + p["cooling_log_per_c"]*np.maximum(0., temperature-p["cooling_base_c"]))

    @property
    def energy_normalizer(self):
        """Session-weighted climatological mean of the energy response in the reference climate.

        The bundled energy prior is an annual Dutch distribution, so the response
        is scaled to average one there; colder or warmer countries then differ.
        """
        if not hasattr(self, "_energy_normalizer"):
            country = self.energy_parameters["reference_climate"]
            days = [date(2021, 1, 1)+timedelta(days=offset) for offset in range(365)]
            mean, spread, _ = self.temperature_climate(country, days)
            nodes, weights = np.polynomial.hermite_e.hermegauss(40)
            expected = (self.energy_response(mean[:, None]+spread[:, None]*nodes[None])*weights).sum(1)/weights.sum()
            sessions = self.season(days)*self.regimes(country, days)[2]
            self._energy_normalizer = float((expected*sessions).sum()/sessions.sum())
        return self._energy_normalizer

    def effects(self, country, first, last, seed):
        """Day effects for one country's local days first..last (inclusive)."""
        days = [first+timedelta(days=offset) for offset in range((last-first).days+1)]
        ordinals = np.array([day.toordinal() for day in days])
        keys = {label: text_key(f"{self.version}|{country}|{label}|{int(seed)}") for label in ("demand", "temperature")}
        kinds, names, regime, weekend = self.regimes(country, days)
        shock = np.exp(self.sigma*ar1(keys, ordinals, self.phi, "demand")-self.sigma**2/2)
        volume = self.season(days)*regime/self.normalizer(country)*shock
        mean, spread, phi = self.temperature_climate(country, days)
        temperature = mean+spread*ar1(keys, ordinals, phi, "temperature")
        energy = self.energy_response(temperature)/self.energy_normalizer
        return DayEffects(days, kinds, names, weekend, volume, temperature, energy)


@lru_cache(maxsize=2)
def _effects(path, modified):
    return CalendarEffects(path)


def get_calendar(path=PARAMETERS):
    path = Path(path)
    return _effects(str(path), path.stat().st_mtime_ns if path.exists() else 0)
