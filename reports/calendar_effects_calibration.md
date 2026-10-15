# Calendar, weather and demand effects: calibration

Generated 2026-10-14T20:15:45+00:00 by `scripts/calibrate_calendar_effects.py`. Method and use: `docs/session-sources.md`.

## Data

- ElaadNL open data: 9,907 public charging transactions on 362 days of 2019 (SHA-256 `084aca2d35d8f05f`).
- KNMI De Bilt (station 260) daily mean temperature, 1991-2020 and 2019.
- ERA5 daily mean 2 m temperature (Open-Meteo archive) at the other countries' reference points, 1991-2020.

## Daily demand (negative binomial regression of sessions per day)

Seasonality uses 5 annual harmonics, selected by BIC from 1-6. The 2019 fleet growth enters as a fixed exposure offset of 0.352 log units per year (plug-in fleet, RVO figures via the ElaadNL 2019 annual overview), because a trend and an annual cycle are poorly separable within one year (a free trend gives 0.53). 95% intervals: two-week moving-block bootstrap.

| Effect (vs Sunday) | Value | 95% interval |
|---|---:|---:|
| Monday | +22.6% | [+12.3%, +33.6%] |
| Tuesday | +31.3% | [+22.9%, +43.5%] |
| Wednesday | +31.0% | [+23.3%, +45.2%] |
| Thursday | +31.0% | [+20.8%, +45.1%] |
| Friday | +37.2% | [+28.8%, +47.2%] |
| Saturday | +50.8% | [+41.7%, +62.8%] |
| Public holiday (vs a Sunday) | +8.2% | [-19.2%, +20.4%] |

Seasonal demand factor by month (mean one), with 95% interval:

| | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Factor | 1.19 | 1.09 | 1.08 | 1.13 | 0.93 | 0.99 | 0.73 | 0.68 | 0.97 | 0.98 | 1.12 | 1.15 |
| 95% low | 1.02 | 0.97 | 0.98 | 1.01 | 0.75 | 0.86 | 0.51 | 0.41 | 0.79 | 0.86 | 1.02 | 0.91 |
| 95% high | 1.43 | 1.21 | 1.18 | 1.27 | 1.05 | 1.19 | 0.87 | 0.88 | 1.28 | 1.15 | 1.29 | 1.25 |

Sensitivity of the seasonal factor to the assumed 2019 growth (log units per year):

| Growth | Log-likelihood | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.0 | -1228.1 | 1.06 | 0.94 | 0.98 | 1.03 | 0.89 | 0.96 | 0.74 | 0.71 | 1.05 | 1.07 | 1.28 | 1.29 |
| 0.2 | -1222.9 | 1.13 | 1.02 | 1.04 | 1.09 | 0.91 | 0.98 | 0.73 | 0.69 | 1.00 | 1.02 | 1.19 | 1.21 |
| 0.315 | -1220.9 | 1.17 | 1.07 | 1.07 | 1.12 | 0.92 | 0.98 | 0.73 | 0.69 | 0.98 | 0.99 | 1.13 | 1.16 |
| 0.352 | -1220.4 | 1.19 | 1.09 | 1.08 | 1.13 | 0.93 | 0.99 | 0.73 | 0.68 | 0.97 | 0.98 | 1.12 | 1.15 |
| 0.5 | -1219.4 | 1.24 | 1.15 | 1.12 | 1.17 | 0.94 | 0.99 | 0.72 | 0.67 | 0.94 | 0.94 | 1.05 | 1.09 |

Common daily demand shock (log-normal AR(1), mean one): sigma = 0.108 (95% 0.000-0.167), phi = 0.74 (95% 0.00-0.92); latent autocorrelation at lags 1-7: [0.673, 0.765, 0.386, 0.271, 0.171, 0.122, 0.04]. NB2 dispersion of the sample counts: alpha = 0.0161.

Temperature anomaly (vs its centred 31-day mean) added to the count model: -0.4% sessions per °C (95% [-1.7%, +1.0%]); not used, as weather acts through energy per session.

Observed/fitted sessions per month: [0.966, 1.026, 0.988, 1.012, 1.023, 0.936, 1.159, 0.922, 0.949, 1.04, 0.968, 1.031].

Partial days (not fitted; check of the 50% mixing rule):

| Date | Day | Observed | Model as workday | Model as holiday | Implied holiday share |
|---|---|---:|---:|---:|---:|
| 2019-04-19 | Goede vrijdag | 23 | 30.4 | 24.0 | 1.15 |
| 2019-05-31 | Bridge day | 31 | 26.7 | 21.1 | -0.76 |
| 2019-12-27 | Bridge day | 39 | 39.5 | 31.1 | 0.06 |

## Session energy and temperature

OLS of log energy on month, weekday and arrival-hour fixed effects plus hinge terms (9,847 sessions); bases by profile least squares; 95% intervals: bootstrap over days.

| Term | Base | Effect per °C | 95% interval |
|---|---:|---:|---:|
| Colder than base | 11.0 °C | +1.1% | [+0.2%, +2.0%] |
| Warmer than base | 16.0 °C | +1.5% | [+0.1%, +3.2%] |
| Connection time, colder (not applied) | 11.0 °C | +0.6% | [-0.2%, +1.5%] |
| Connection time, warmer (not applied) | 16.0 °C | +0.1% | [-1.2%, +1.7%] |

Within-month energy effect by temperature bin:

| Mean °C | Effect | Sessions |
|---:|---:|---:|
| -1.2 | +9.7% | 245 |
| 1.7 | +4.6% | 583 |
| 5.0 | +0.8% | 1476 |
| 7.4 | -1.2% | 2058 |
| 10.3 | -2.0% | 1640 |
| 13.7 | -1.6% | 1342 |
| 16.3 | -0.8% | 1561 |
| 19.1 | +1.0% | 604 |
| 24.0 | +7.6% | 338 |

## Holiday arrival times

Sessions: {'holiday': 221, 'partial': 93, 'saturday': 1639, 'sunday': 1068, 'workday': 6979}. Total variation distance of the hourly arrival distribution of holidays against: sunday 0.11 (chi-square p = 0.762), saturday 0.086 (chi-square p = 0.865), workday 0.295 (chi-square p = 2.25e-12).

## Temperature climatologies (1991-2020)

| Country | Reference | Source | Mean °C | Anomaly SD °C | AR(1) | Lag-2 (AR(1) predicts phi²) |
|---|---|---|---:|---:|---:|---:|
| NL | De Bilt (KNMI 260) | KNMI daily observations | 10.6 | 3.3 | 0.80 | 0.58 (0.64) |
| DE | Berlin | ERA5 (Open-Meteo archive) | 10.0 | 3.8 | 0.82 | 0.60 (0.67) |
| PT | Lisbon | ERA5 (Open-Meteo archive) | 16.2 | 1.9 | 0.79 | 0.54 (0.63) |
| IT | Rome | ERA5 (Open-Meteo archive) | 16.2 | 2.5 | 0.83 | 0.62 (0.69) |
| GB | London | ERA5 (Open-Meteo archive) | 11.0 | 2.8 | 0.77 | 0.53 (0.59) |
| CH | Bern | ERA5 (Open-Meteo archive) | 10.5 | 3.4 | 0.82 | 0.59 (0.67) |
| FR | Paris | ERA5 (Open-Meteo archive) | 11.9 | 3.3 | 0.81 | 0.57 (0.65) |
| FI | Helsinki | ERA5 (Open-Meteo archive) | 6.1 | 3.9 | 0.82 | 0.63 (0.68) |
| ES | Madrid | ERA5 (Open-Meteo archive) | 14.9 | 2.8 | 0.81 | 0.57 (0.66) |
| BE | Brussels | ERA5 (Open-Meteo archive) | 11.0 | 3.4 | 0.81 | 0.57 (0.65) |
| DK | Copenhagen | ERA5 (Open-Meteo archive) | 8.8 | 3.0 | 0.82 | 0.62 (0.67) |
| LU | Luxembourg | ERA5 (Open-Meteo archive) | 9.8 | 3.5 | 0.82 | 0.59 (0.67) |
| AT | Vienna | ERA5 (Open-Meteo archive) | 10.9 | 3.7 | 0.82 | 0.59 (0.67) |
| LI | Vaduz | ERA5 (Open-Meteo archive) | 10.5 | 3.7 | 0.82 | 0.59 (0.67) |
| SE | Stockholm | ERA5 (Open-Meteo archive) | 7.2 | 3.3 | 0.80 | 0.59 (0.64) |
| NO | Oslo | ERA5 (Open-Meteo archive) | 7.4 | 3.7 | 0.80 | 0.61 (0.65) |
| EE | Tallinn | ERA5 (Open-Meteo archive) | 6.5 | 3.6 | 0.83 | 0.64 (0.69) |
| PL | Warsaw | ERA5 (Open-Meteo archive) | 8.9 | 4.0 | 0.82 | 0.59 (0.67) |
| CZ | Prague | ERA5 (Open-Meteo archive) | 10.0 | 3.8 | 0.81 | 0.59 (0.66) |
