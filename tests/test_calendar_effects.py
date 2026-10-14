"""Calendar, weather and demand effects: calibration fidelity, day types and use in scenarios."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from backend.cpft import day_window
from backend.cpft_library import CPFTLibrary, issue_time, sample_cpft
from backend.scenario_calendar import get_calendar, holiday_calendar
from backend.scenario_world import sample_world
from backend.session_sources import SessionSourceService
from tests.cpft_helpers import write_test_library

ZONE = "Europe/Amsterdam"
CHARGERS = [dict(id=cp_id, power=11., type="regular") for cp_id in range(1, 1501)]


@pytest.fixture(scope="module")
def calendar():
    return get_calendar()


@pytest.fixture(scope="module")
def decades(calendar):
    return calendar.effects("NL", date(2000, 1, 1), date(2039, 12, 31), seed=42)


def test_effects_preserve_long_run_means_of_the_elaadnl_priors(calendar, decades):
    """Volume and session-weighted energy factors average one, so annual totals are unchanged."""
    assert decades.volume.mean() == pytest.approx(1, abs=.01)
    assert (decades.energy*decades.volume).sum()/decades.volume.sum() == pytest.approx(1, abs=.01)


def test_synthetic_weather_reproduces_the_calibrated_climatology(calendar, decades):
    temperature = pd.Series(decades.temperature, index=pd.to_datetime([str(day) for day in decades.days]))
    days = list(decades.days)
    mean, spread, phi = calendar.temperature_climate("NL", days)
    anomaly = (temperature.to_numpy()-mean)/spread
    assert anomaly.mean() == pytest.approx(0, abs=.05)
    assert anomaly.std() == pytest.approx(1, abs=.05)
    assert np.corrcoef(anomaly[1:], anomaly[:-1])[0, 1] == pytest.approx(phi, abs=.03)
    # KNMI De Bilt 1991-2020 normals for January and July
    monthly = temperature.groupby(temperature.index.month).mean()
    assert monthly[1] == pytest.approx(3.6, abs=1.)
    assert monthly[7] == pytest.approx(18.2, abs=1.)


def test_demand_shock_has_the_calibrated_size_and_persistence(calendar, decades):
    expected = calendar.season(decades.days)*calendar.regimes("NL", decades.days)[2]/calendar.normalizer("NL")
    shock = np.log(decades.volume/expected)
    assert shock.std() == pytest.approx(calendar.sigma, rel=.05)
    assert np.corrcoef(shock[1:], shock[:-1])[0, 1] == pytest.approx(calendar.phi, abs=.03)
    assert np.exp(shock).mean() == pytest.approx(1, abs=.01)


def test_effects_of_a_day_do_not_depend_on_the_window_or_country_of_other_points(calendar):
    long = calendar.effects("NL", date(2026, 1, 1), date(2026, 12, 31), seed=7)
    short = calendar.effects("NL", date(2026, 7, 14), date(2026, 7, 16), seed=7)
    for name in ("volume", "temperature", "energy", "weekend_share"):
        np.testing.assert_allclose(getattr(short, name), getattr(long, name)[long.at(date(2026, 7, 14)):][:3], rtol=1e-12)
    assert not np.allclose(calendar.effects("NL", date(2026, 7, 14), date(2026, 7, 16), seed=8).volume, short.volume)
    assert not np.allclose(calendar.effects("DE", date(2026, 7, 14), date(2026, 7, 16), seed=7).temperature, short.temperature)


@pytest.mark.parametrize("day,kind,name", [
    (date(2026, 4, 27), "holiday", "Koningsdag"), (date(2026, 12, 25), "holiday", "Eerste kerstdag"),
    (date(2026, 4, 3), "partial", "Goede vrijdag"), (date(2026, 5, 14), "holiday", "Hemelvaartsdag"),
    (date(2026, 5, 15), "partial", "Bridge day"), (date(2026, 5, 13), "workday", ""), (date(2026, 5, 16), "weekend", "")])
def test_dutch_day_types(day, kind, name):
    calendar = holiday_calendar("NL")
    assert calendar.kind(day) == kind
    assert calendar.name(day) == name


def test_holidays_follow_the_weekend_pattern_and_partial_days_mix_it(calendar):
    effects = calendar.effects("NL", date(2026, 5, 13), date(2026, 5, 16), seed=1)
    assert list(effects.weekend_share[[0, 1, 3]]) == [0., 1., 1.]
    assert 0 < effects.weekend_share[2] < 1
    # Each country uses its own holidays: German Unity Day, and the Friday after Ascension as a bridge day
    assert calendar.effects("DE", date(2026, 10, 3), date(2026, 10, 3), seed=1).kind == ["holiday"]
    assert calendar.effects("DE", date(2026, 5, 15), date(2026, 5, 15), seed=1).kind == ["partial"]
    assert calendar.effects("NL", date(2026, 10, 3), date(2026, 10, 3), seed=1).kind == ["weekend"]


def test_colder_countries_and_days_charge_more_energy_per_session(calendar):
    january = [calendar.effects(country, date(2026, 1, 1), date(2026, 1, 31), seed=3).energy.mean() for country in ("FI", "NL", "PT")]
    assert january[0] > january[1] > january[2]
    effects = calendar.effects("NL", date(2026, 1, 1), date(2026, 12, 31), seed=3)
    assert np.corrcoef(np.minimum(effects.temperature, 11), effects.energy)[0, 1] < -.9


def daily_counts(frame, first, days):
    counts = []
    for offset in range(days):
        left, right = day_window(first+timedelta(days=offset), ZONE)
        counts.append(((frame.start >= left.timestamp()) & (frame.start < right.timestamp())).sum())
    return np.array(counts, float)


def test_days_now_differ_in_aggregate_and_the_world_stays_window_independent(calendar):
    first, days = date(2026, 6, 1), 56
    start, end = day_window(first, ZONE)[0], day_window(first+timedelta(days=days-1), ZONE)[1]
    plain = daily_counts(sample_world(CHARGERS, start, end), first, days)
    effects = sample_world(CHARGERS, start, end, calendar=calendar)
    varied = daily_counts(effects, first, days)
    weekdays = np.array([(first+timedelta(days=offset)).weekday() < 5 for offset in range(days)])
    cv = lambda values: values.std()/values.mean()
    # Independent points average out (about 3% at this size); common day effects do not
    assert cv(varied[weekdays]) > 2*cv(plain[weekdays])
    left, right = day_window(date(2026, 6, 20), ZONE)
    alone = sample_world(CHARGERS, left, right, calendar=calendar)
    assert alone.equals(effects.overlapping(left.timestamp(), right.timestamp()))


def test_holiday_arrivals_follow_the_weekend_curve(calendar):
    def morning_share(day):
        left, right = day_window(day, ZONE)
        frame = sample_world(CHARGERS, left, right, calendar=calendar)
        frame = frame.select(frame.start >= left.timestamp())
        hours = pd.to_datetime(frame.start, unit="s", utc=True).tz_convert(ZONE).hour
        return np.mean((hours >= 6) & (hours < 10))
    workday, holiday, sunday = morning_share(date(2026, 4, 28)), morning_share(date(2026, 4, 27)), morning_share(date(2026, 4, 26))
    assert abs(holiday-sunday) < abs(holiday-workday)


def test_disabled_effects_reproduce_the_calendar_free_world(tmp_path):
    service = SessionSourceService(atlas_path=tmp_path/"missing.gpkg", calendar_effects=False)
    frame, metadata = service.get(CHARGERS[:200], date(2026, 12, 25), source="simple")
    assert metadata["calendar"]["applied"] is False
    start, end = day_window(date(2026, 12, 24), ZONE)[0], day_window(date(2026, 12, 25), ZONE)[1]
    assert frame.equals(sample_world(CHARGERS[:200], start, end))


def test_cpft_forecasts_a_holiday_as_a_sunday_and_scales_energy_with_temperature(tmp_path, calendar):
    library = CPFTLibrary(write_test_library(tmp_path/"weekday.npz", mark_weekday=True))
    chargers = CHARGERS[:300]
    def forecast(day):
        frame, info = sample_cpft(chargers, day, library=library, calendar=calendar, countries=["NL"]*len(chargers))
        return frame.select(frame.start >= issue_time(day, ZONE).timestamp()), info
    kings_day, info = forecast(date(2026, 4, 27))  # a Monday
    factor = info["calendar"]["NL"][1]["energy_factor"]
    assert info["calendar"]["NL"][1]["holiday"] == "Koningsdag"
    np.testing.assert_allclose(kings_day.energy_kwh, (1+6)*factor, rtol=1e-3)  # Sunday context
    tuesday, info = forecast(date(2026, 4, 28))
    np.testing.assert_allclose(tuesday.energy_kwh, (1+1)*info["calendar"]["NL"][1]["energy_factor"], rtol=1e-3)
