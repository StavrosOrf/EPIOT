# Calendar, weather and demand effects

Synthetic sessions are drawn independently for every charging point. Over an
area of hundreds of points that randomness averages out, so without further
structure every weekday of a large selection has nearly the same total and
shape (about ±3% for 1,000 points). Real charging demand varies from day to day
because of effects **shared by all points**: the season, the day of the week,
public holidays, weather and unexplained busy or quiet spells. EPIOT adds these
effects on top of the bundled ElaadNL session priors, calibrated on public data,
and applies them to all three session sources.

Everything stays on request and window-independent
({doc}`on-request-scenarios`): every effect is a fixed function of the country,
the local date and the scenario seed.

## Model

For a point $n$ in country $c$ on local day $d$, the attempted-arrival intensity
in quarter-hour $t$ of the day is

$$
\lambda_n(t) = v_n \, F_c(d) \, \big[(1-\omega_{c,d})\, a^{\text{wd}}_n(t) + \omega_{c,d}\, a^{\text{we}}_n(t)\big],
$$

where $v_n$ is the point's attempted arrivals per day (2/day times its spatial
multiplier and the demand assumption), and $a^{\text{wd}}$, $a^{\text{we}}$ are
its weekday and weekend arrival curves from the ElaadNL priors, each normalized
over the local day. The weekend share $\omega$ is 0 on workdays, 1 on weekends
and public holidays, and in between on partial days. The **day factor** is

$$
F_c(d) = \frac{S(\text{doy}_d)\, W_c(d)}{N_c}\, Z_c(d),
\qquad
\log S(\text{doy}) = \sum_{k=1}^{5} \alpha_k \cos\tfrac{2\pi k\,\text{doy}}{365.25} + \beta_k \sin\tfrac{2\pi k\,\text{doy}}{365.25}.
$$

$W_c(d)$ is the day-of-week level $w_{\text{dow}}$. On a public holiday it is
the Sunday level times the holiday effect, $w_{\text{Sun}}e^{\eta}$. On a partial
day (a bridge day, or a holiday that is not a general day off) it is the mixture
$(1-\pi)\,w_{\text{dow}} + \pi\, w_{\text{Sun}} e^{\eta}$, with the weekend share
$\omega = \pi w_{\text{Sun}}e^{\eta}/W_c(d)$. The constant $N_c$ is the mean of
$S \cdot W_c$ over 2020–2039, so the long-run attempted-arrival volume of the
priors is unchanged. The **common demand shock** is a mean-one log-normal AR(1),

$$
\log Z_c(d) = \sigma x_d - \tfrac{\sigma^2}{2}, \qquad x_d = \phi x_{d-1} + \sqrt{1-\phi^2}\,\varepsilon_d,\quad \varepsilon_d \sim \mathcal N(0,1),
$$

computed as a truncated moving average of hashed innovations, so any day is
evaluated without simulating from a start date. Given the day factor, arrivals
remain Poisson per quarter-hour (thinned by occupancy). Day counts are then
Poisson–log-normal: overdispersed, as measured in the ElaadNL data below, and
close to the negative binomial that Lahariya et al. (2020) suggest for
overdispersed charging arrivals.

Each session's energy, drawn from the ElaadNL energy prior, is multiplied by a
**temperature response** of its arrival day,

$$
E = E_{\text{prior}} \; \frac{g(T_{c,d})}{G}, \qquad
g(T) = \exp\!\big(\beta_h\,(T_h - T)_+ + \beta_c\,(T - T_c)_+\big),
$$

and is then limited by power × connection time as before. $G$ is the
session-weighted mean of $g$ over the Dutch climate, the climate of the prior,
so Dutch annual energy is preserved and colder or warmer countries differ. The
daily mean temperature comes from a **stochastic weather generator**
(Richardson, 1981; Wilks & Wilby, 1999): the country's
1991–2020 climatological mean and spread by day of year, plus AR(1) anomalies,

$$
T_{c,d} = \mu_c(\text{doy}_d) + s_c(\text{doy}_d)\, y_d, \qquad y_d = \phi_T\, y_{d-1} + \sqrt{1-\phi_T^2}\,\eta_d .
$$

Weather is synthetic: a scenario date does not reproduce the weather observed
on that date. Demand shocks and temperatures are shared by all points of a
country and by all three session sources for the same seed. Changing the seed
draws another plausible sequence of days.

## Data

| Data | Use |
|---|---|
| ElaadNL open EV dataset: 10,000 random transactions at ElaadNL public charging stations, 2019 (ElaadNL, 2020a; mirrored by Hashmi et al., 2024) | Season, day of week, holidays, demand shock, temperature response of energy |
| KNMI daily mean temperature, De Bilt (station 260), 1991–2020 | 2019 temperatures for the energy regression; Dutch climatology |
| ERA5 reanalysis daily mean 2 m temperature (Hersbach et al., 2020), via the Open-Meteo archive API, at a reference point per country (the capital), 1991–2020 | Climatologies of the other 18 supported countries |
| Dutch plug-in fleet in 2019, RVO statistics reported by ElaadNL (ElaadNL, 2020b; RVO, 2021) | Exposure offset that separates fleet growth from seasonality |
| National public holidays, `holidays` Python package | Day types per country |

ERA5 and KNMI agree closely at De Bilt (correlation 0.997, RMSE 0.5 °C, equal
30-year means), so the reanalysis is adequate for the other countries' climatologies.

## Calibration

`scripts/calibrate_calendar_effects.py` downloads the inputs (checking the
ElaadNL file's SHA-256), estimates all parameters and writes
`backend/data/calendar_effects.json` (read by the application),
`reports/calendar_effects_calibration.md` with its JSON, and, with matplotlib,
the figures below.

**Daily demand.** Sessions per day in the sample (27 per day on average) are
modelled by a negative binomial (NB2) regression (Cameron & Trivedi, 2013) with
annual harmonics, day of week and a holiday indicator. A random sample of all
transactions keeps each day's share, so the sample's day-to-day overdispersion
measures that of total demand. Within a single year a trend and an annual cycle
are poorly separable (a free trend is estimated at 0.53 log units per year with a
95% interval of −0.9 to 3.4), and 2019 was a year of rapid fleet growth.
Fleet growth therefore enters as a fixed **exposure offset** of 0.352 log units
per year: the Dutch plug-in fleet grew from about 143,000 to 204,000 vehicles
(BEV +139%, PHEV −2%). Public charge points grew similarly (+37%, 0.315), and
the report gives the seasonal profile under growth assumptions from 0 to 0.5.
The number of harmonics (five) is selected by BIC. Bridge days and partial
holidays are kept out of the fit and used as a check.

**Common shock.** Under Poisson sampling around a log-normal shock,
$\operatorname{Var}(y_d) = \mu_d + \mu_d^2(e^{\sigma^2}-1)$ and
$\operatorname{Cov}(y_d, y_{d+L}) = \mu_d\mu_{d+L}(e^{\rho_L\sigma^2}-1)$, so
$\sigma$ and the latent autocorrelations $\rho_L$ follow from the residual
moments. $\phi$ is fitted to $\rho_L = \phi^L$ over lags 1–7. Uncertainty
uses a two-week moving-block bootstrap (Künsch, 1989).

**Energy and temperature.** Energy per session rose through 2019 from 11.5 kWh
in January to 17.4 kWh in December, mostly through larger new batteries. The
coldest months have the lowest energy, so a seasonal comparison would be
confounded. ElaadNL observed the same within-year fleet effect in 2018, when
the average charging power per public session rose from 4.1 to 5.1 kW
(ElaadNL, 2020b). The response is therefore identified from
**day-to-day weather within each month** (Dell et al., 2014). Log energy is
regressed on month, weekday and arrival-hour fixed effects and two hinge
terms, with both bases chosen by profile least squares; intervals use a bootstrap over days.

**Climatology.** For each country, the day-of-year mean and variance of daily mean
temperature are fitted with annual harmonics over 1991–2020, and $\phi_T$ is the
lag-1 autocorrelation of the standardized anomalies.

## Results

| Effect | Estimate | 95% interval |
|---|---:|---:|
| Monday vs Sunday | +22.6% | +12.3% to +33.6% |
| Tuesday / Wednesday / Thursday vs Sunday | +31% | about +21% to +45% |
| Friday vs Sunday | +37.2% | +28.8% to +47.2% |
| Saturday vs Sunday | +50.8% | +41.7% to +62.8% |
| Public holiday vs a Sunday | +8.2% | −19.2% to +20.4% |
| Demand shock σ (log scale) | 0.108 | 0.00 to 0.17 |
| Demand shock persistence φ (per day) | 0.74 | 0.00 to 0.92 |
| Energy, per °C below 11.0 °C | +1.1% | +0.2% to +2.0% |
| Energy, per °C above 16.0 °C | +1.5% | +0.1% to +3.2% |
| Connection time, per °C below 11.0 °C (not applied) | +0.6% | −0.2% to +1.5% |

Seasonal demand factor (mean one):

| Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1.19 | 1.09 | 1.08 | 1.13 | 0.93 | 0.99 | 0.73 | 0.68 | 0.97 | 0.98 | 1.12 | 1.15 |

The summer dip (school holidays) holds under every growth assumption tested.
Winter factors shift by about ±0.1 with the assumed growth.

```{figure} ../_static/figures/calendar-daily-demand.svg
:class: chart
:alt: Sessions per day in the 2019 ElaadNL sample with the fitted mean

Sessions per day in the ElaadNL 2019 sample (grey), the fitted mean (blue) and public holidays (red).
```

```{figure} ../_static/figures/calendar-energy-temperature.svg
:class: chart
:alt: Energy per session against daily mean temperature, within months

Energy per session against daily mean temperature, within months: binned data and the fitted hinge model.
```

Checks that support the structure:

- **Holiday arrival times** match Sundays (total variation distance 0.11,
  chi-square p = 0.76) and differ clearly from workdays (0.30, p < 10⁻¹¹), so
  holidays use the weekend arrival curve.
- **Temperature does not change the number of sessions**: the day's deviation
  from its 31-day mean, added to the count model, gives −0.4% per °C (95%
  interval −1.7% to +1.0%), so weather acts through energy only. The connection-time response is not significant and is not applied.
- **The energy response is U-shaped**, as in vehicle studies. Consumption
  per km is lowest near room temperature, and higher with heating and
  cooling: Yuksel & Michalek, 2015, and 2.4 kWh/100 km per 5 °C below 10 °C
  (Hao et al., 2020), about 3% per °C. The per-session effect estimated here
  (1.1% per °C) is smaller, as expected: session energy also depends on trip
  length and on drivers topping up rather than refilling.
- **Partial days**: Good Friday 2019 looked like a holiday (implied holiday
  share 1.15), and the two bridge days like workdays (−0.76 and 0.06). With
  about 25 sessions a day each value has a standard error near 0.8, so the 50%
  share is an assumption that the data neither reject nor determine.
- **Weather generator**: 40 simulated years reproduce the KNMI monthly normals
  within about 0.5 °C, the anomaly spread (3.3 °C) and persistence (0.80). The
  observed lag-2 correlation (0.58) is slightly below the AR(1) value (0.64).

Effect on outputs: 1,000 regular points over 2026, compared with the same
scenario without day effects:

| | Without | With |
|---|---:|---:|
| Day-to-day variation of weekday sessions (CV) | 2.2% | 12.1% |
| Day-to-day variation of weekday energy (CV) | 3.9% | 13.7% |
| Energy per session, January / June | 11.2 / 11.2 kWh | 11.8 / 10.9 kWh |
| Sessions, August / January | 1.00 | 0.72 |
| Sessions, Saturday / Sunday | 0.99 | 1.27 |
| Sessions on King's Day / a median Monday | 0.97 | 0.84 |

Annual attempted arrivals are preserved exactly. Realized sessions and energy
are within 1.5%, because busy days saturate occupied points.

## Use by the session sources

- **Simple and spatial**: the day factor scales the arrival probability per
  quarter-hour, holidays and partial days mix in the weekend curve, and each
  session's energy follows the temperature of its arrival day. With effects
  disabled, the sampler is exactly the calendar-free one.
- **CPFT**: the day factor scales the point's arrival volume before its library
  cell is chosen, so busy days draw trajectories from higher-volume histories.
  CPFT's own calendar features know no holidays, so a holiday is forecast with
  the Sunday context (on partial days, for the partial share of points).
  Forecast and history energies follow their days' temperatures.

Each response's `source.calendar` reports, per country and day, the day type,
holiday, demand factor, synthetic temperature and energy factor, and the number
of points without a known country (which use the Netherlands). The web page
summarizes it below the chart. Set `SESSION_CALENDAR_EFFECTS=false`
(`FLASK_SESSION_CALENDAR_EFFECTS`) to disable all day effects.

## Relation to other models

| Work | Data | Day-level structure |
|---|---|---|
| ElaadNL open data dashboard (ElaadNL, 2020a) | ElaadNL 2018–2020 | Arrival, connection and energy distributions for weekdays and weekends; the source of EPIOT's priors |
| EV2Gym (Orfanoudakis et al., 2024) | ElaadNL distributions | Arrivals and energy conditioned on time and day type |
| Lahariya, Benoit & Develder (Lahariya et al., 2020) | ElaadNL transactions | Poisson arrivals with rate by month, day type and time of day; energy and connection time by month; negative binomial suggested for overdispersion |
| emobpy (Gaete-Morales et al., 2021) | German mobility survey, hourly weather | Vehicle consumption from ambient temperature (HVAC, battery) |
| Hashmi et al. (Hashmi et al., 2024) | ElaadNL 2019 sample | Scenario generation; seasonal effects on charging not considered |
| **EPIOT** | ElaadNL 2019 sample, KNMI, ERA5 | Day-type curves as above, plus season, day of week, holidays and bridge days, a persistent common demand shock, and weather-driven session energy calibrated within months |

EPIOT keeps the ElaadNL day-type arrival curves used by EV2Gym and the monthly
and day-type rate structure of Lahariya et al. It replaces their month-specific
energy distributions with a physical driver (temperature, as in emobpy),
estimated directly on session energies rather than from vehicle physics.

## Limitations

- **One year of public data.** One year of Dutch public charging is the only
  calibration source. Workplace and home charging may have other seasonal and
  weekly patterns, and the seasonal profile depends partly on the assumed fleet growth.
- **Dutch calibration elsewhere.** The demand structure and the energy response
  are transferred to the other countries. Only their holidays and climates are
  their own, and climates are taken at the capital.
- **No regional or school holidays.** Holidays are national (no German state or
  Swiss canton holidays), and school holidays are not modelled separately: the
  Dutch summer dip is part of the seasonal profile.
- **Uncertain cooling branch.** The warm response rests on 20 warm days in 2019,
  some during the summer-holiday period.
- **Synthetic weather.** Weather never reproduces a historical date, and the app
  uses one timezone (Europe/Amsterdam) for local days in every country.
- **Shape stays fixed.** Day effects scale demand and switch between the weekday
  and weekend curves; they do not otherwise change the shape of a day.

## Reproduce

```bash
uv run --with matplotlib python scripts/calibrate_calendar_effects.py --figures docs/_static/figures
uv run pytest tests/test_calendar_effects.py -q
```

Downloads are cached in `.cache/calendar/`. Recalibrating changes the version
string in the parameter file, which invalidates browser caches. The CPFT library
does not need a rebuild, because its histories are generated without day effects.

## References

- Cameron, A. C., & Trivedi, P. K. (2013). *Regression Analysis of Count Data* (2nd ed.). Cambridge University Press.
- Dell, M., Jones, B. F., & Olken, B. A. (2014). What do we learn from the weather? The new climate–economy literature. *Journal of Economic Literature*, 52(3), 740–798.
- ElaadNL (2020a). *ElaadNL shares new data sets demonstrating the rise of EVs and usage of charging stations* (open data dashboard and open EV datasets). <https://elaad.nl/en/?p=3630>, <https://platform.elaad.io>
- ElaadNL (2020b). *Jaaroverzicht 2019 – Outlook 2020*. <https://www.rvo.nl/sites/default/files/2020/04/ELAAD%20NL%20-%20Jaaroverzicht%202019%20-%20Outlook%202020.pdf>
- Gaete-Morales, C., Kramer, H., Schill, W.-P., & Zerrahn, A. (2021). An open tool for creating battery-electric vehicle time series from empirical data, emobpy. *Scientific Data*, 8, 152. <https://doi.org/10.1038/s41597-021-00932-9>
- Hao, X., Wang, H., Lin, Z., & Ouyang, M. (2020). Seasonal effects on electric vehicle energy consumption and driving range: A case study on personal, taxi, and ridesharing vehicles. *Journal of Cleaner Production*, 249, 119403. <https://doi.org/10.1016/j.jclepro.2019.119403>
- Hashmi, M. U., Gioffrè, D., Nagels, S., & Van Hertem, D. (2024). Analyzing electric vehicle, load and photovoltaic generation uncertainty using publicly available datasets. arXiv:2409.01284. Dataset mirror: <https://github.com/umar-hashmi/Public-Load-profile-Datasets>
- Hersbach, H., et al. (2020). The ERA5 global reanalysis. *Quarterly Journal of the Royal Meteorological Society*, 146(730), 1999–2049. <https://doi.org/10.1002/qj.3803>
- KNMI. Daily weather data of the Netherlands, station De Bilt (260). <https://www.daggegevens.knmi.nl>
- Künsch, H. R. (1989). The jackknife and the bootstrap for general stationary observations. *The Annals of Statistics*, 17(3), 1217–1241.
- Lahariya, M., Benoit, D. F., & Develder, C. (2020). Defining a synthetic data generator for realistic electric vehicle charging sessions. In *Proceedings of the Eleventh ACM International Conference on Future Energy Systems (e-Energy '20)*. arXiv:2203.01129.
- Open-Meteo. Historical weather API (ERA5). <https://open-meteo.com>
- Orfanoudakis, S., Diaz-Londono, C., Yılmaz, Y. E., Palensky, P., & Vergara, P. P. (2024). EV2Gym: A flexible V2G simulator for EV smart charging research and benchmarking. *IEEE Transactions on Intelligent Transportation Systems*, 26(2).
- python-holidays. <https://pypi.org/project/holidays/>
- Richardson, C. W. (1981). Stochastic simulation of daily precipitation, temperature, and solar radiation. *Water Resources Research*, 17(1), 182–190.
- RVO (2021). *Elektrisch Rijden op (de) weg – voertuigen en laadpunten – jaaroverzicht 2020*. Rijksdienst voor Ondernemend Nederland.
- Wilks, D. S., & Wilby, R. L. (1999). The weather generation game: a review of stochastic weather models. *Progress in Physical Geography*, 23(3), 329–357.
- Yuksel, T., & Michalek, J. J. (2015). Effects of regional temperature on electric vehicle efficiency, range, and emissions in the United States. *Environmental Science & Technology*, 49(6), 3974–3980.
