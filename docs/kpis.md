# KPIs

The **KPIs** tab summarises each area's charging behaviour over a date range, in five dashboards:
**User**, **Grid**, **Environment**, **Mobility** and **City**. Sessions come from the selected
{doc}`session source <session-sources>`.

## Using the tab

- Each area card has its own **date range** (inclusive, at most 366 days, last seven days by
  default) and **demand scenario**. A change recalculates that area only.
- There is no strategy setting. Behavioural KPIs do not depend on it, and the Environment
  dashboard compares the strategies itself.
- Distributions are drawn as **shares of their own day type**, so weekdays (Monday to Friday) and
  weekends (Saturday and Sunday) are comparable, as are areas of different size. Counts are in the
  hover text, and areas share each chart's scale. Public holidays count as weekdays.
- Headline figures of the active dashboard are listed on each area card.

### Counting rules

- **Arrival KPIs** count a session on the day it arrives, **departure KPIs** on the day it departs
  (a connection ending exactly at local midnight departs on the new day).
- **Occupancy, load and energy** are cut at local-day boundaries and at the range ends, so a range
  equals the sum of its days.
- Energy per session is capped at `rated power × connected hours`; unknown power is 11 kW.
- The last bin of a histogram is open-ended (*24+*, *100+*, *200+*). The cards count the stays
  beyond 24 hours and the sessions beyond 100 kWh, and the API reports `overflow` for every open bin.

## User

| Chart | Content |
|---|---|
| Arrival time | Sessions by local arrival hour |
| Connection time | Sessions by hours connected (24+) |
| Departure time | Sessions by local departure hour |
| Idle while plugged in | Sessions by stay minus the time needed at rated power (24+) |

Idle time $s_i = (e_i - a_i) - E_i / P_c$ is the part of a stay in which charging can be moved. It
assumes the vehicle accepts the rated power, so it is an upper bound.
*Headline:* sessions, mean arrival time, median and 90th-percentile stay, idle share of stay time.

```{figure} _static/figures/idle-time.svg
:class: chart
:alt: A session's connection time split into charging time and idle time

Idle time for a 22 kWh session on an 11 kW charger connected for nine hours.
```

```{figure} _static/screenshots/kpi-user.jpg
:class: screenshot
:alt: User dashboard with arrival, connection, departure and idle-time distributions for two areas

The User dashboard. Weekdays are blue and weekends orange; each area card lists its headline
figures.
```

## Grid

| Chart | Content |
|---|---|
| Uncontrolled load | Mean power per half-hour of the local day under As Fast As Possible |
| Load duration | Power exceeded for 0, 5, … 100 % of the 10-minute steps |
| Energy per session by arrival hour | Mean energy of sessions arriving in each hour |
| Daily energy per charger | Active charger-days by energy delivered that day (10 bins of 20 kWh, 200+) |
| Energy per session | Sessions by energy (10 bins of 10 kWh, 100+) |

*Headline:* peak load and its time, and

$$
\text{load factor} = \frac{\bar L}{\max_t L_t}, \qquad
\text{coincidence factor} = \frac{\max_t L_t}{\sum_c P_c},
$$

with $L_t$ the 10-minute uncontrolled load and $P_c$ the rated power of charger $c$. A load factor
near 1 is a flat load; a coincidence factor near 1 means all chargers draw at once. Also the share
of charger-days without charging, which are left out of *Daily energy per charger*.

```{figure} _static/screenshots/kpi-grid.jpg
:class: screenshot
:alt: Grid dashboard with uncontrolled load, load duration and energy distributions

The Grid dashboard.
```

## Environment

Four strategies deliver identical energy and are compared on carbon intensity and renewable
share: As Fast As Possible (the baseline), As Late As Possible, Average Power and Min. Carbon
Footprint.

| Element | Content |
|---|---|
| Emissions by hour of day | kgCO₂e emitted in each local hour, summed over the range, per strategy |
| Renewable share chart | Share of charged energy from renewables, per strategy |
| Summary table | Energy, emissions (kgCO₂e), mean intensity, renewable share, grid-data coverage and difference against As Fast As Possible |

Sessions count on their arrival day and are charged from their true arrival; a connection still
running at the end of the range keeps its in-range share. A badge marks whether the grid data
matched the dates, came from a historical reference, or are partial. Results are estimated
scenario footprints, not verified emissions or demonstrated avoided emissions.

```{figure} _static/screenshots/kpi-environment.jpg
:class: screenshot
:alt: Environment summary table with four strategies for one area

The summary table, with the badge that marks a historical reference.
```

```{figure} _static/screenshots/kpi-environment-charts.jpg
:class: screenshot
:alt: Emissions by hour of day and renewable share by strategy for three areas

The charts below the tables.
```

The emissions chart shows where each strategy puts its energy and what that costs in carbon:
As Fast As Possible emits when vehicles arrive, As Late As Possible just before they leave, and
Min. Carbon Footprint in the cleanest hours. A strategy's emissions in an hour are its energy in
that hour times the grid's intensity then, so the chart separates the strategies whatever the grid
data. The grid's own intensity would not: it is the same number for every strategy that charges in
an hour. The API still returns it as `intensity_by_hour`.

As Late As Possible schedules each connection against its departure and is cropped at the end of
the range, so its emissions gather in the last hours; connections that cross the end keep only
their in-range share.

### Grid data

For each hour, EPIOT uses an observation for the matching date when one exists. Otherwise it uses
a labelled **historical reference**: the latest complete 24-hour observed profile, matched by
local hour. Hours with neither stay empty, and partial results are never extrapolated. Differences
against the baseline are shown only when carbon coverage is complete. Min. Carbon Footprint is
unavailable, and never replaced by another strategy, if any candidate interval lacks carbon data.

The bundled observations cover six days of autumn 2025, so most ranges use the reference. Import
more data from a CSV with hourly interval starts; new observations are used by the next request:

```bash
uv run python scripts/prepare_grid_data.py --csv grid.csv
```

| Column | Required | Description |
|---|---|---|
| `timestamp` | Yes | Hourly interval start with a time zone, e.g. `2026-10-14T00:00:00Z` |
| `co2_intensity` | Yes | gCO₂e/kWh |
| `renewable_percentage` | Yes | 0 – 100 |
| `carbon_is_estimated`, `renewable_is_estimated`, `source`, `basis` | – | Provenance flags and labels |

Observations are stored in `instance/grid_data.sqlite`. No network or paid data feed is used.
Set `FLASK_GRID_ALLOW_STALE=false` to disable the reference and require matching dates.

Emissions are $\sum (\text{kWh} \times \text{gCO}_2\text{e/kWh}) / 1000$ kgCO₂e, with kWh equal
to kW ÷ 6 per 10-minute step. Carbon and renewable coverage are tracked independently.

## Mobility

| Chart | Content |
|---|---|
| Sessions per charger and day | Mean (bars) and 90th percentile (markers) for each weekday |
| Charger-days by number of sessions | Share of charger-days with 0, 1, … 5+ sessions, per weekday |

Weekdays absent from the range are left empty, not drawn as zero. *Headline:* sessions per used
charger-day, the median idle gap between two connections on the same charger, and the share of
unused charger-days. Gaps are only seen inside the range.

```{figure} _static/screenshots/kpi-mobility.jpg
:class: screenshot
:alt: Mobility dashboard with sessions per charger and day and the split of charger-days

The Mobility dashboard.
```

## City

| Chart | Content |
|---|---|
| Free chargers | Share of chargers free in each half-hour of the day |
| All chargers busy | Probability that every selected charger is occupied (shown when at least 0.5 %) |
| Occupancy and utilisation | Per charger, busiest first (up to 30 chargers); otherwise the distribution of occupancy |

*Occupancy* is the share of the range a vehicle is connected, including vehicles that have
finished charging. *Utilisation* is energy delivered divided by what the charger could deliver at
its rated power. A large gap between them means chargers are held by vehicles that are not
charging. *Headline:* mean occupancy and utilisation, and the highest all-busy probability. The
all-busy probability needs 1 to 2,000 chargers.

```{figure} _static/screenshots/kpi-city.jpg
:class: screenshot
:alt: City dashboard with free chargers by time of day and the distribution of occupancy

The City dashboard. With more than 30 chargers the third chart shows the distribution of
occupancy instead of one bar per charger.
```

## API

`GET` or `POST /kpi/user`

| Parameter | Required | Description |
|---|---|---|
| `selected_markers` | Yes | Charging-point IDs |
| `start_date`, `end_date` | Yes | `YYYY-MM-DD`, inclusive; at most 366 days |
| `session_source`, `demand_assumption`, `seed` | – | Scenario settings ({doc}`session-sources`) |
| `section` | – | `basic` (User, Grid, Mobility, City), `environment`, or `all` (default) |

The interface requests `basic` first and `environment` only when that dashboard is opened.

| Response field | Content |
|---|---|
| `arrival_dist_{wd,we}`, `departure_dist_*`, `duration_dist_*`, `slack_dist_*` | 24 bins of counts |
| `consumption_dist_*`, `daily_consumption_dist_*`, `idle_charger_days_*` | 10 bins of counts; idle charger-days |
| `hour_of_arrival_consumption_*`, `load_profile_*` | 24 mean energies (kWh) and 48 mean powers (kW) |
| `load_duration_kw` | 21 values, exceeded 0 to 100 % of the time |
| `sessions_per_day_0` … `_6`, `sessions_per_day_mean`, `_p90`, `_observations` | By weekday, Monday = 0 |
| `weekday_availability`, `weekend_availability`, `weekday_blocking`, `weekend_blocking` | 48 half-hour values |
| `occupation_ratio_dist`, `charger_usage` | 20 bins; per charger when 200 or fewer |
| `overflow`, `summary`, `range`, `source` | Open-bin counts, headline figures, range and provenance |
| `environment.strategies.<strategy>` | Per strategy (`afap`, `alap`, `avg`, `mincarbon`): `energy_kwh`, `emissions_kg`, `average_intensity_g_per_kwh`, `renewable_share_pct`, coverage and `status`, `footprint_difference_vs_afap_*`, and per local hour of day `energy_by_hour_kwh`, `emissions_by_hour_kg` and `intensity_by_hour` |
| `co2_intensities_*`, `renewable_energy_shared_*` | The same intensity and renewable-share series under flat names, kept for older clients |

Fields without data are `null`. Invalid input returns `400`, and an unavailable source `503`.

```bash
curl -G http://127.0.0.1:5000/kpi/user \
  -d selected_markers=40405,40406 -d start_date=2026-10-09 -d end_date=2026-10-15 \
  -d session_source=spatial -d section=basic
```

## Export

Exporting from this tab writes **Charger IDs** and one **`<Area>_KPIs`** sheet per area, including
the Environment section even if that dashboard was not opened. The rows are listed in
{doc}`reports`.
