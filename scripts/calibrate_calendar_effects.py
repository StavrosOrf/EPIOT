"""Calibrate the calendar, weather and demand effects of the synthetic scenarios.

Estimates, from public data, the day-level effects that make synthetic days
differ (see docs/session-sources.md):

- ElaadNL open data (10,000 random public charging transactions, 2019):
  seasonal and day-of-week demand, public-holiday demand, the persistent
  common daily demand shock, and the temperature response of session energy.
- KNMI De Bilt daily mean temperature: the 2019 temperatures for the energy
  regression and the Dutch 1991-2020 climatology.
- ERA5 reanalysis (via Open-Meteo) at reference points of the other countries:
  their 1991-2020 temperature climatologies.

Writes backend/data/calendar_effects.json, which the application reads, and
reports/calendar_effects_calibration.{md,json}. Inputs are downloaded once into
--data-dir and checked against their recorded SHA-256 where fixed.

    uv run python scripts/calibrate_calendar_effects.py
    uv run --with matplotlib python scripts/calibrate_calendar_effects.py --figures reports/figures
"""

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd
from scipy.optimize import least_squares, minimize
from scipy.special import gammaln
from scipy.stats import chi2_contingency

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.scenario_calendar import PARAMETERS, holiday_calendar

ELAAD_URL = ("https://raw.githubusercontent.com/umar-hashmi/Public-Load-profile-Datasets/main/"
             "Elaad_Dataset_manipulation/elaadnl_open_ev_datasets.xlsx")
ELAAD_SHA256 = "084aca2d35d8f05fe4570a94d75108ecfb097734e7f2dfc36788889b1fe7d276"
KNMI_URL = "https://www.daggegevens.knmi.nl/klimatologie/daggegevens"
OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"
# Climate reference points: KNMI De Bilt for the Netherlands, capitals elsewhere
REFERENCE_POINTS = {
    "NL": ("De Bilt (KNMI 260)", 52.10, 5.18), "DE": ("Berlin", 52.52, 13.40), "PT": ("Lisbon", 38.72, -9.14),
    "IT": ("Rome", 41.90, 12.50), "GB": ("London", 51.51, -0.13), "CH": ("Bern", 46.95, 7.45),
    "FR": ("Paris", 48.86, 2.35), "FI": ("Helsinki", 60.17, 24.94), "ES": ("Madrid", 40.42, -3.70),
    "BE": ("Brussels", 50.85, 4.35), "DK": ("Copenhagen", 55.68, 12.57), "LU": ("Luxembourg", 49.61, 6.13),
    "AT": ("Vienna", 48.21, 16.37), "LI": ("Vaduz", 47.14, 9.52), "SE": ("Stockholm", 59.33, 18.07),
    "NO": ("Oslo", 59.91, 10.75), "EE": ("Tallinn", 59.44, 24.75), "PL": ("Warsaw", 52.23, 21.01),
    "CZ": ("Prague", 50.08, 14.44)}
NORMALS = ("1991-01-01", "2020-12-31")
SEASONAL_HARMONICS = range(1, 7)
# 2019 growth of the Dutch plug-in fleet, which drives the number of public sessions.
# ElaadNL Jaaroverzicht 2019 - Outlook 2020 (RVO data): BEV +139%, PHEV -2% over 2019;
# RVO Jaaroverzicht 2020: 107,335 BEV and 96,521 PHEV at the end of 2019.
FLEET_END_2019 = 107_335+96_521
FLEET_END_2018 = 107_335/2.39+96_521/.98
FLEET_GROWTH = float(np.log(FLEET_END_2019/FLEET_END_2018))
PUBLIC_POINT_GROWTH = float(np.log(1.37))  # public charge points +37% in 2019, same source
SENSITIVITY_GROWTH = (0., .2, PUBLIC_POINT_GROWTH, FLEET_GROWTH, .5)
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def download(url, path, data=None, attempts=8):
    """Download once into the cache; wait and retry when a free API rate-limits."""
    for attempt in range(attempts):
        if path.exists():
            break
        request = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode() if data else None,
                                         headers={"User-Agent": "EPIOT calendar calibration"})
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                path.write_bytes(response.read())
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == attempts-1:
                raise
            time.sleep(60*(attempt+1))
    return path


def harmonics(day_of_year, count):
    angle = 2*np.pi*np.asarray(day_of_year, float)/365.25
    return np.column_stack([f(k*angle) for k in range(1, count+1) for f in (np.cos, np.sin)]) if count else np.zeros((len(angle), 0))


# --- Daily demand ----------------------------------------------------------

def growth(days, rate):
    """Log exposure of a fleet growing at `rate` (log units per year), centred mid-year."""
    return rate*(days.dayofyear.to_numpy()-183)/365.25


def count_design(days, kinds, count, trend=False):
    """Seasonal harmonics and day type (optionally a free trend); holidays take Sunday's day type plus their own effect."""
    weekday = np.where(kinds == "holiday", 6, days.dayofweek)
    columns = [np.ones(len(days))]+([(days.dayofyear-183)/365.25] if trend else [])+[harmonics(days.dayofyear, count)]
    columns += [(weekday == w).astype(float) for w in range(6)] + [(kinds == "holiday").astype(float)]
    return np.column_stack(columns)


def negative_binomial(X, y, offset=0.):
    """Maximum likelihood NB2 regression (log link, optional log offset): Var = mu + alpha mu^2."""
    def loss(p):
        mu, r = np.exp(offset+X@p[:-1]), np.exp(-p[-1])
        return -(gammaln(y+r)-gammaln(r)-gammaln(y+1)+r*np.log(r/(r+mu))+y*np.log(mu/(r+mu))).sum()
    start = np.zeros(X.shape[1]+1)
    start[0], start[-1] = np.log(y.mean()), np.log(.05)
    fit = minimize(loss, start, method="BFGS", options=dict(maxiter=5000))
    return fit.x, fit.fun


def latent_shock(y, mu, lags=7, blocks=None):
    """Moments of a mean-one log-normal AR(1) demand shock under Poisson sampling.

    Var(y) = mu + mu^2 (e^{s^2}-1) and Cov(y_d, y_{d+L}) = mu_d mu_{d+L} (e^{rho_L s^2}-1).
    With `blocks`, lagged pairs are taken only within a block (for the block bootstrap).
    """
    blocks = np.zeros(len(y), int) if blocks is None else blocks
    e = y-mu
    excess = (e**2-mu).sum()/(mu**2).sum()
    if excess <= 0:
        return 0., 0., np.zeros(lags)
    s2 = np.log(1+excess)
    rho = []
    for L in range(1, lags+1):
        same = blocks[L:] == blocks[:-L]
        ratio = (e[L:]*e[:-L])[same].sum()/(mu[L:]*mu[:-L])[same].sum()
        rho.append(np.log(max(1+ratio, 1e-9))/s2)
    rho = np.array(rho)
    phi = least_squares(lambda p: p[0]**np.arange(1, lags+1)-rho, [.5], bounds=([0.], [.99])).x[0]
    return float(np.sqrt(s2)), float(phi), rho


def seasonal_by_month(coefficients, count):
    days = pd.date_range("2021-01-01", "2021-12-31")
    log = harmonics(days.dayofyear, count) @ np.asarray(coefficients)
    factor = pd.Series(np.exp(log-np.log(np.exp(log).mean())), index=days)
    return factor.groupby(factor.index.month).mean().round(3).tolist()


def demand_model(transactions, holidays_nl, bootstrap, rng, rate=FLEET_GROWTH):
    """Negative binomial regression of sessions per day with a fleet-growth exposure offset.

    A trend and an annual cycle are poorly separable within one year, so the
    trend is fixed from independent fleet statistics rather than estimated.
    """
    days = pd.date_range("2019-01-01", "2019-12-31")
    counts = transactions.groupby("date").size().reindex(days, fill_value=0).to_numpy(float)
    kinds = np.array([holidays_nl.kind(day.date()) for day in days])
    fitted = kinds != "partial"  # partial days are kept out and used as a check of the mixing rule
    observed, offset = counts[fitted], growth(days[fitted], rate)
    selection = []
    for count in SEASONAL_HARMONICS:
        params, loss = negative_binomial(count_design(days[fitted], kinds[fitted], count), observed, offset)
        selection.append(dict(harmonics=count, parameters=len(params), aic=2*loss+2*len(params),
                              bic=2*loss+np.log(fitted.sum())*len(params)))
    count = min(selection, key=lambda row: row["bic"])["harmonics"]
    X = count_design(days[fitted], kinds[fitted], count)
    params, _ = negative_binomial(X, observed, offset)
    mu = np.exp(offset+X@params[:-1])
    sigma, phi, rho = latent_shock(observed, mu)
    # Moving-block bootstrap (two-week blocks) of the daily series for uncertainty
    draws = []
    for _ in range(bootstrap):
        blocks = rng.integers(0, len(observed)-14, len(observed)//14+1)
        index = np.concatenate([np.arange(b, b+14) for b in blocks])[:len(observed)]
        label = np.repeat(np.arange(len(blocks)), 14)[:len(observed)]
        p, _ = negative_binomial(X[index], observed[index], offset[index])
        s, f, _ = latent_shock(observed[index], np.exp(offset[index]+X[index]@p[:-1]), blocks=label)
        draws.append(np.concatenate([p[:-1], [s, f]]))
    draws = np.array(draws)
    low, high = np.percentile(draws, [2.5, 97.5], axis=0)
    names = ["intercept"]+[f"{f}{k}" for k in range(1, count+1) for f in ("cos", "sin")]+WEEKDAYS[:6]+["holiday"]
    estimates = {name: dict(value=float(v), ci95=[float(a), float(b)]) for name, v, a, b in zip(names, params[:-1], low, high)}
    seasonal = [estimates[f"{f}{k}"]["value"] for k in range(1, count+1) for f in ("cos", "sin")]
    monthly_draws = np.array([seasonal_by_month(row, count) for row in draws[:, 1:1+2*count]])
    # Sensitivity of the seasonal profile to the assumed growth, and the free-trend fit
    sensitivity = []
    for value in SENSITIVITY_GROWTH:
        p, loss = negative_binomial(X, observed, growth(days[fitted], value))
        sensitivity.append(dict(growth=round(value, 3), log_likelihood=-float(loss),
                                monthly=seasonal_by_month(p[1:1+2*count], count)))
    free, _ = negative_binomial(count_design(days[fitted], kinds[fitted], count, trend=True), observed)
    # Partial days: observed against the weekday and holiday regimes of the fitted model
    checks = []
    for position in np.flatnonzero(~fitted):
        day = days[position]
        regimes = {}
        for regime in ("weekday", "holiday"):
            row = count_design(days[[position]], np.array([regime]), count)
            regimes[regime] = float(np.exp(growth(days[[position]], rate)+row@params[:-1])[0])
        weight = (counts[position]-regimes["weekday"])/(regimes["holiday"]-regimes["weekday"])
        checks.append(dict(date=str(day.date()), name=holidays_nl.name(day.date()), observed=int(counts[position]),
                           expected_as_workday=round(regimes["weekday"], 1), expected_as_holiday=round(regimes["holiday"], 1),
                           implied_holiday_weight=round(float(weight), 2)))
    monthly = (pd.Series(observed).groupby(days[fitted].month).sum()/pd.Series(mu).groupby(days[fitted].month).sum()).round(3)
    return dict(harmonics=count, selection=selection, estimates=estimates, growth=rate, free_trend=float(free[1]),
                seasonal=seasonal, seasonal_monthly=seasonal_by_month(seasonal, count),
                seasonal_monthly_ci95=[np.percentile(monthly_draws, 2.5, axis=0).round(3).tolist(),
                                       np.percentile(monthly_draws, 97.5, axis=0).round(3).tolist()],
                growth_sensitivity=sensitivity,
                weekday_log=[estimates[name]["value"] for name in WEEKDAYS[:6]]+[0.],
                holiday_log=estimates["holiday"]["value"], nb_alpha=float(np.exp(params[-1])),
                shock=dict(sigma=sigma, phi=phi, sigma_ci95=[float(np.percentile(draws[:, -2], 2.5)), float(np.percentile(draws[:, -2], 97.5))],
                           phi_ci95=[float(np.percentile(draws[:, -1], 2.5)), float(np.percentile(draws[:, -1], 97.5))],
                           latent_autocorrelation=[round(float(value), 3) for value in rho]),
                partial_days=checks, monthly_observed_over_fitted=monthly.tolist(), days=int(fitted.sum()),
                sessions=int(observed.sum())), (days, counts, kinds, mu, fitted)


def count_temperature(transactions, holidays_nl, temperature, count, bootstrap, rng, rate=FLEET_GROWTH):
    """Does weather change the number of sessions? Adds the temperature anomaly to the count model.

    The anomaly is the day's temperature minus its centred 31-day mean, so it
    measures weather rather than season.
    """
    days = pd.date_range("2019-01-01", "2019-12-31")
    counts = transactions.groupby("date").size().reindex(days, fill_value=0).to_numpy(float)
    kinds = np.array([holidays_nl.kind(day.date()) for day in days])
    series = temperature.reindex(pd.date_range("2018-12-01", "2020-01-31"))
    anomaly = (series-series.rolling(31, center=True).mean()).reindex(days).to_numpy()
    fitted = kinds != "partial"
    X = np.column_stack([count_design(days[fitted], kinds[fitted], count), anomaly[fitted]])
    observed, offset = counts[fitted], growth(days[fitted], rate)
    estimate = negative_binomial(X, observed, offset)[0][-2]
    draws = []
    for _ in range(bootstrap):
        blocks = rng.integers(0, len(observed)-14, len(observed)//14+1)
        index = np.concatenate([np.arange(b, b+14) for b in blocks])[:len(observed)]
        draws.append(negative_binomial(X[index], observed[index], offset[index])[0][-2])
    return dict(log_per_c=float(estimate), ci95=np.percentile(draws, [2.5, 97.5]).tolist())


# --- Session energy and temperature ---------------------------------------

def energy_model(transactions, temperature, bootstrap, rng):
    """log(energy) on month, weekday and arrival-hour fixed effects plus temperature hinges.

    Month fixed effects absorb the 2019 fleet change (larger batteries over the
    year), so the temperature response is identified from day-to-day weather
    within each month.
    """
    t = transactions[(transactions.TotalEnergy > .5) & (transactions.ConnectedTime > .1)].copy()
    t["T"] = temperature.reindex(t.date).to_numpy()
    fixed = pd.concat([pd.get_dummies(t.start.dt.month, prefix="m"), pd.get_dummies(t.start.dt.dayofweek, prefix="d", drop_first=True),
                       pd.get_dummies(t.start.dt.hour, prefix="h", drop_first=True)], axis=1).astype(float).to_numpy()
    y, T = np.log(t.TotalEnergy.to_numpy()), t["T"].to_numpy()

    def fit(heat, cool, target=y, rows=slice(None)):
        X = np.column_stack([fixed[rows], np.maximum(0, heat-T[rows]), np.maximum(0, T[rows]-cool)])
        beta, *_ = np.linalg.lstsq(X, target[rows], rcond=None)
        return beta[-2:], ((target[rows]-X@beta)**2).sum()

    grid = [(heat, cool) for heat in np.arange(6, 18.5, .5) for cool in np.arange(16, 24.5, .5) if cool >= heat]
    heat, cool = min(grid, key=lambda pair: fit(*pair)[1])
    (heating, cooling), _ = fit(heat, cool)
    days = t.date.to_numpy()
    groups = {day: np.flatnonzero(days == day) for day in np.unique(days)}
    keys = list(groups)
    draws, connection_draws = [], []
    log_connection = np.log(t.ConnectedTime.to_numpy())
    for _ in range(bootstrap):
        rows = np.concatenate([groups[keys[i]] for i in rng.integers(0, len(keys), len(keys))])
        draws.append(fit(heat, cool, rows=rows)[0])
        connection_draws.append(fit(heat, cool, target=log_connection, rows=rows)[0])
    draws, connection_draws = np.array(draws), np.array(connection_draws)
    connection = fit(heat, cool, target=log_connection)[0]
    # Within-month residuals by temperature bin, for the report and figure
    base, *_ = np.linalg.lstsq(fixed, y, rcond=None)
    residual = y-fixed@base
    bins = pd.cut(T, [-15, 0, 3, 6, 9, 12, 15, 18, 21, 35])
    binned = pd.DataFrame(dict(residual=residual, T=T, bin=bins)).groupby("bin", observed=True).agg(
        temperature=("T", "mean"), log_energy_effect=("residual", "mean"), sessions=("residual", "size"))
    return dict(heating_base_c=float(heat), cooling_base_c=float(cool),
                heating_log_per_c=float(heating), heating_ci95=np.percentile(draws[:, 0], [2.5, 97.5]).tolist(),
                cooling_log_per_c=float(cooling), cooling_ci95=np.percentile(draws[:, 1], [2.5, 97.5]).tolist(),
                connection_heating_log_per_c=float(connection[0]), connection_heating_ci95=np.percentile(connection_draws[:, 0], [2.5, 97.5]).tolist(),
                connection_cooling_log_per_c=float(connection[1]), connection_cooling_ci95=np.percentile(connection_draws[:, 1], [2.5, 97.5]).tolist(),
                sessions=int(len(t)), warm_days=int((temperature["2019"] > cool).sum()),
                binned=[dict(temperature_c=round(float(r.temperature), 1), log_energy_effect=round(float(r.log_energy_effect), 3),
                             sessions=int(r.sessions)) for r in binned.itertuples()]), (T, residual)


def arrival_shapes(transactions, holidays_nl):
    """Hourly arrival distribution on holidays against Sundays and working days."""
    t = transactions.copy()
    t["kind"] = [holidays_nl.kind(day.date()) for day in t.date]
    t["group"] = np.where(t.kind == "holiday", "holiday", np.where(t.start.dt.dayofweek == 6, "sunday",
                          np.where(t.start.dt.dayofweek == 5, "saturday", np.where(t.kind == "partial", "partial", "workday"))))
    table = pd.crosstab(t.group, t.start.dt.hour).reindex(columns=range(24), fill_value=0)
    share = table.div(table.sum(1), axis=0)
    output = {}
    for other in ("sunday", "saturday", "workday"):
        pair = table.loc[["holiday", other]]
        pair = pair.loc[:, pair.sum() > 0]
        output[other] = dict(total_variation=round(float(.5*np.abs(share.loc["holiday"]-share.loc[other]).sum()), 3),
                             chi2_p=float(chi2_contingency(pair.to_numpy())[1]))
    return dict(sessions={group: int(value) for group, value in table.sum(1).items()}, holiday_vs=output)


# --- Temperature climatologies ---------------------------------------------

def climatology(series):
    """Day-of-year mean and standard deviation (harmonic fits) and AR(1) of standardized anomalies."""
    doy = series.index.dayofyear.to_numpy()
    H = np.column_stack([np.ones(len(series)), harmonics(doy, 3)])
    mean, *_ = np.linalg.lstsq(H, series.to_numpy(), rcond=None)
    anomaly = series.to_numpy()-H@mean
    S = np.column_stack([np.ones(len(series)), harmonics(doy, 2)])
    variance, *_ = np.linalg.lstsq(S, anomaly**2, rcond=None)
    z = anomaly/np.sqrt(np.maximum(S@variance, .25))
    phi = float(np.corrcoef(z[1:], z[:-1])[0, 1])
    rho2 = float(np.corrcoef(z[2:], z[:-2])[0, 1])
    return dict(mean_harmonics=mean.tolist(), variance_harmonics=variance.tolist(), ar1=phi, lag2_autocorrelation=rho2,
                mean_c=float(series.mean()), anomaly_sd_c=float(anomaly.std()),
                monthly_mean_c=[round(float(v), 1) for v in series.groupby(series.index.month).mean()])


def knmi_series(path):
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    return pd.Series([row["TG"]/10 for row in rows], index=pd.to_datetime([row["date"][:10] for row in rows])).sort_index()


def era5_series(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))["daily"]
    return pd.Series(data["temperature_2m_mean"], index=pd.to_datetime(data["time"]), dtype=float).dropna()


# --- Report ----------------------------------------------------------------

def figures(folder, demand_data, energy_data, demand, energy):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    folder.mkdir(parents=True, exist_ok=True)
    days, counts, kinds, mu, fitted = demand_data
    fig, ax = plt.subplots(figsize=(9, 3.2))
    ax.plot(days, counts, ".", ms=3, color="#888", label="ElaadNL sample, sessions per day")
    ax.plot(days[fitted], mu, color="#1f6feb", lw=1.2, label="Fitted mean (trend, season, weekday, holidays)")
    ax.plot(days[kinds == "holiday"], counts[kinds == "holiday"], "o", ms=4, color="#d1242f", label="Public holiday")
    ax.set_ylabel("Sessions in sample"); ax.legend(frameon=False, fontsize=8, loc="upper left"); ax.margins(x=0)
    fig.tight_layout(); fig.savefig(folder/"calendar-daily-demand.svg"); plt.close(fig)
    grid = np.linspace(-8, 30, 200)
    curve = energy["heating_log_per_c"]*np.maximum(0, energy["heating_base_c"]-grid)+energy["cooling_log_per_c"]*np.maximum(0, grid-energy["cooling_base_c"])
    binned = pd.DataFrame(energy["binned"])
    # Both relative to the comfort band between the two bases
    band = binned[(binned.temperature_c >= energy["heating_base_c"]) & (binned.temperature_c <= energy["cooling_base_c"])]
    shift = band.log_energy_effect.mean() if len(band) else 0.
    fig, ax = plt.subplots(figsize=(6, 3.2))
    ax.plot(binned.temperature_c, 100*(np.exp(binned.log_energy_effect-shift)-1), "o", color="#888", label="Within-month mean by temperature bin")
    ax.plot(grid, 100*(np.exp(curve)-1), color="#1f6feb", label="Fitted hinge model")
    ax.axhline(0, color="#ccc", lw=.8)
    ax.set_xlabel("Daily mean temperature, De Bilt (°C)"); ax.set_ylabel("Energy per session (%)"); ax.legend(frameon=False, fontsize=8)
    fig.tight_layout(); fig.savefig(folder/"calendar-energy-temperature.svg"); plt.close(fig)


def report_markdown(result):
    d, e, a = result["demand"], result["energy"], result["arrival_shapes"]
    pct = lambda value: f"{100*(np.exp(value)-1):+.1f}%"
    ci = lambda pair: f"[{pct(pair[0])}, {pct(pair[1])}]"
    lines = ["# Calendar, weather and demand effects: calibration", "",
             f"Generated {result['generated_at']} by `scripts/calibrate_calendar_effects.py`. "
             "Method and use: `docs/session-sources.md`.", "",
             "## Data", "",
             f"- ElaadNL open data: {d['sessions']:,} public charging transactions on {d['days']} days of 2019 "
             f"(SHA-256 `{result['sources']['elaadnl']['sha256'][:16]}`).",
             "- KNMI De Bilt (station 260) daily mean temperature, 1991-2020 and 2019.",
             "- ERA5 daily mean 2 m temperature (Open-Meteo archive) at the other countries' reference points, 1991-2020.", "",
             "## Daily demand (negative binomial regression of sessions per day)", "",
             f"Seasonality uses {d['harmonics']} annual harmonics, selected by BIC from {SEASONAL_HARMONICS.start}-{SEASONAL_HARMONICS.stop-1}. "
             f"The 2019 fleet growth enters as a fixed exposure offset of {d['growth']:.3f} log units per year "
             "(plug-in fleet, RVO figures via the ElaadNL 2019 annual overview), because a trend and an annual cycle are poorly "
             f"separable within one year (a free trend gives {d['free_trend']:.2f}). 95% intervals: two-week moving-block bootstrap.", "",
             "| Effect (vs Sunday) | Value | 95% interval |", "|---|---:|---:|"]
    for name in WEEKDAYS[:6]+["holiday"]:
        estimate = d["estimates"][name]
        lines.append(f"| {name.capitalize() if name != 'holiday' else 'Public holiday (vs a Sunday)'} | {pct(estimate['value'])} | {ci(estimate['ci95'])} |")
    lines += ["", "Seasonal demand factor by month (mean one), with 95% interval:", "",
              "| | " + " | ".join(MONTHS) + " |", "|---"*13 + "|",
              "| Factor | " + " | ".join(f"{v:.2f}" for v in d["seasonal_monthly"]) + " |",
              "| 95% low | " + " | ".join(f"{v:.2f}" for v in d["seasonal_monthly_ci95"][0]) + " |",
              "| 95% high | " + " | ".join(f"{v:.2f}" for v in d["seasonal_monthly_ci95"][1]) + " |", "",
              "Sensitivity of the seasonal factor to the assumed 2019 growth (log units per year):", "",
              "| Growth | Log-likelihood | " + " | ".join(MONTHS) + " |", "|---"*14 + "|"]
    lines += [f"| {row['growth']} | {row['log_likelihood']:.1f} | " + " | ".join(f"{v:.2f}" for v in row["monthly"]) + " |"
              for row in d["growth_sensitivity"]]
    s = d["shock"]
    lines += ["", f"Common daily demand shock (log-normal AR(1), mean one): sigma = {s['sigma']:.3f} "
              f"(95% {s['sigma_ci95'][0]:.3f}-{s['sigma_ci95'][1]:.3f}), phi = {s['phi']:.2f} "
              f"(95% {s['phi_ci95'][0]:.2f}-{s['phi_ci95'][1]:.2f}); latent autocorrelation at lags 1-7: {s['latent_autocorrelation']}. "
              f"NB2 dispersion of the sample counts: alpha = {d['nb_alpha']:.4f}.", "",
              f"Temperature anomaly (vs its centred 31-day mean) added to the count model: "
              f"{pct(d['temperature_on_sessions']['log_per_c'])} sessions per °C (95% {ci(d['temperature_on_sessions']['ci95'])}); "
              "not used, as weather acts through energy per session.", "",
              f"Observed/fitted sessions per month: {d['monthly_observed_over_fitted']}.", "",
              "Partial days (not fitted; check of the 50% mixing rule):", "",
              "| Date | Day | Observed | Model as workday | Model as holiday | Implied holiday share |", "|---|---|---:|---:|---:|---:|"]
    for row in d["partial_days"]:
        lines.append(f"| {row['date']} | {row['name']} | {row['observed']} | {row['expected_as_workday']} | {row['expected_as_holiday']} | {row['implied_holiday_weight']} |")
    lines += ["", "## Session energy and temperature", "",
              f"OLS of log energy on month, weekday and arrival-hour fixed effects plus hinge terms ({e['sessions']:,} sessions); "
              "bases by profile least squares; 95% intervals: bootstrap over days.", "",
              "| Term | Base | Effect per °C | 95% interval |", "|---|---:|---:|---:|",
              f"| Colder than base | {e['heating_base_c']:.1f} °C | {pct(e['heating_log_per_c'])} | {ci(e['heating_ci95'])} |",
              f"| Warmer than base | {e['cooling_base_c']:.1f} °C | {pct(e['cooling_log_per_c'])} | {ci(e['cooling_ci95'])} |",
              f"| Connection time, colder (not applied) | {e['heating_base_c']:.1f} °C | {pct(e['connection_heating_log_per_c'])} | {ci(e['connection_heating_ci95'])} |",
              f"| Connection time, warmer (not applied) | {e['cooling_base_c']:.1f} °C | {pct(e['connection_cooling_log_per_c'])} | {ci(e['connection_cooling_ci95'])} |",
              "", "Within-month energy effect by temperature bin:", "", "| Mean °C | Effect | Sessions |", "|---:|---:|---:|"]
    lines += [f"| {row['temperature_c']} | {pct(row['log_energy_effect'])} | {row['sessions']} |" for row in e["binned"]]
    lines += ["", "## Holiday arrival times", "",
              f"Sessions: {a['sessions']}. Total variation distance of the hourly arrival distribution of holidays against: "
              + ", ".join(f"{k} {v['total_variation']} (chi-square p = {v['chi2_p']:.3g})" for k, v in a["holiday_vs"].items()) + ".", "",
              "## Temperature climatologies (1991-2020)", "",
              "| Country | Reference | Source | Mean °C | Anomaly SD °C | AR(1) | Lag-2 (AR(1) predicts phi²) |", "|---|---|---|---:|---:|---:|---:|"]
    for code, c in result["climate"].items():
        lines.append(f"| {code} | {c['reference']} | {c['source']} | {c['mean_c']:.1f} | {c['anomaly_sd_c']:.1f} | {c['ar1']:.2f} | {c['lag2_autocorrelation']:.2f} ({c['ar1']**2:.2f}) |")
    return "\n".join(lines)+"\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=ROOT/".cache/calendar")
    parser.add_argument("--output", type=Path, default=PARAMETERS)
    parser.add_argument("--report", type=Path, default=ROOT/"reports/calendar_effects_calibration.md")
    parser.add_argument("--figures", type=Path, help="Write SVG figures here (needs matplotlib)")
    parser.add_argument("--bootstrap", type=int, default=300)
    parser.add_argument("--partial-weight", type=float, default=.5,
                        help="Share of activity behaving like a holiday on bridge days and partial holidays (assumption)")
    args = parser.parse_args()
    rng = np.random.default_rng(20261014)
    folder = args.data_dir
    folder.mkdir(parents=True, exist_ok=True)

    elaad = download(ELAAD_URL, folder/"elaadnl_open_ev_datasets.xlsx")
    if sha256(elaad) != ELAAD_SHA256:
        raise SystemExit("The ElaadNL file differs from the calibrated version; update ELAAD_SHA256 deliberately")
    knmi = download(KNMI_URL, folder/"knmi_260_tg.json", dict(stns="260", vars="TG", start="19910101", end="20201231", fmt="json"))
    transactions = pd.read_excel(elaad, "open_transactions")
    transactions["start"] = pd.to_datetime(transactions.UTCTransactionStart, utc=True).dt.tz_convert("Europe/Amsterdam")
    transactions["date"] = pd.to_datetime(transactions.start.dt.date)
    temperature = knmi_series(knmi)
    holidays_nl = holiday_calendar("NL", partial_weight=args.partial_weight)

    demand, demand_data = demand_model(transactions, holidays_nl, args.bootstrap, rng)
    energy, energy_data = energy_model(transactions, temperature, args.bootstrap, rng)
    shapes = arrival_shapes(transactions, holidays_nl)
    demand["temperature_on_sessions"] = count_temperature(transactions, holidays_nl, temperature, demand["harmonics"], args.bootstrap, rng)
    climate = {}
    for code, (name, latitude, longitude) in REFERENCE_POINTS.items():
        if code == "NL":
            series, source, digest = temperature[NORMALS[0]:NORMALS[1]], "KNMI daily observations", sha256(knmi)
        else:
            path = download(f"{OPEN_METEO_URL}?latitude={latitude}&longitude={longitude}&start_date={NORMALS[0]}&end_date={NORMALS[1]}"
                            "&daily=temperature_2m_mean&timezone=UTC&models=era5", folder/f"era5_{code}.json")
            series, source, digest = era5_series(path), "ERA5 (Open-Meteo archive)", sha256(path)
        climate[code] = dict(reference=name, latitude=latitude, longitude=longitude, source=source, sha256=digest, **climatology(series))
        print(json.dumps(dict(country=code, mean_c=round(climate[code]["mean_c"], 2), ar1=round(climate[code]["ar1"], 3))), flush=True)

    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sources = dict(
        elaadnl=dict(description="ElaadNL open EV datasets: 10,000 random public charging transactions in 2019",
                     publisher="ElaadNL", original="https://platform.elaad.io (open data download)", url=ELAAD_URL, sha256=ELAAD_SHA256),
        knmi=dict(description="KNMI daily mean temperature (TG), De Bilt station 260, 1991-2020", url=KNMI_URL, sha256=sha256(knmi)),
        era5=dict(description="ERA5 reanalysis daily mean 2 m temperature via the Open-Meteo historical weather API", url=OPEN_METEO_URL))
    parameters = dict(
        version=f"calendar-{generated[:10]}", generated_at=generated, sources=sources,
        demand=dict(seasonal_harmonics=demand["seasonal"], fleet_growth_offset=demand["growth"], weekday_log=demand["weekday_log"], holiday_log=demand["holiday_log"],
                    shock_sigma=demand["shock"]["sigma"], shock_phi=demand["shock"]["phi"]),
        holidays=dict(partial_weight=args.partial_weight, partial_names={"NL": ["Goede vrijdag"]}, bridge_days=True,
                      note="Public holidays from the python-holidays package (national level). Partial holidays and bridge days "
                           "behave as a holiday for partial_weight of the population (assumption)."),
        energy=dict(heating_base_c=energy["heating_base_c"], heating_log_per_c=energy["heating_log_per_c"],
                    cooling_base_c=energy["cooling_base_c"], cooling_log_per_c=energy["cooling_log_per_c"], reference_climate="NL"),
        climate={code: {key: value[key] for key in ("reference", "source", "mean_harmonics", "variance_harmonics", "ar1")}
                 for code, value in climate.items()},
        default_country="NL")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(parameters, indent=1), encoding="utf-8")
    result = dict(generated_at=generated, sources=sources, demand=demand, energy=energy, arrival_shapes=shapes, climate=climate)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.with_suffix(".json").write_text(json.dumps(result, indent=1, default=float), encoding="utf-8")
    args.report.write_text(report_markdown(result), encoding="utf-8")
    if args.figures:
        figures(args.figures, demand_data, energy_data, demand, energy)
    print(args.report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
