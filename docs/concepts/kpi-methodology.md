# KPI methodology

All KPIs are computed by one endpoint, `GET /kpi/user` (implemented in `backend/kpi/user.py`), for the
charging points of one area and a date range $[d_0, d_1]$. This page defines each returned field.

## Input set

The range is processed one local calendar day at a time. For each day, EPIOT takes every session
connected at some time that day and attributes it as follows:

- **Arrival** KPIs (arrival, duration, idle time, energy per session, sessions per charger) count a
  session on the day it **arrives**.
- **Departure** KPIs count it on the day it **departs**; a connection that ends exactly at local
  midnight departs on the new day.
- **Occupancy, load and energy** are cut at the day boundaries and at the ends of the range, so a
  range equals the sum of its days.

For session $i$: arrival $a_i$, departure $e_i$, energy $E_i$ (kWh), capped at what the charger can
deliver in the connection, $E_i \le P_c\,(e_i - a_i)$ with $P_c$ the rated power. A day is a
**weekday** if it is Monday to Friday and a **weekend** day otherwise; public holidays are weekdays.
Every distribution is computed separately for both day types (`_wd`, `_we`).

```{mermaid}
flowchart LR
    Q[(Sessions in range)] --> BEH[Behavioural histograms<br/>arrival · duration · departure · energy]
    Q --> OCC[Occupancy grid<br/>30-min slots]
    Q --> SIM[Strategy simulators<br/>afap · alap · avg]
    PM[(Hourly power mix<br/>CO₂ · renewables)] --> ENV
    SIM --> ENV[Environment KPIs]
    BEH --> U[User / Grid / Mobility]
    OCC --> C[City]
    ENV --> E[Environment]
```

## User KPIs

| Field | Definition | Bins |
|---|---|---|
| `arrival_dist_{wd,we}` | Count of sessions by local arrival hour | 24 bins over 0–24 h |
| `duration_dist_{wd,we}` | Count of sessions by connection time $e_i - a_i$ in hours | 24 bins over 0–24 h; longer stays are counted in the last bin |
| `departure_dist_{wd,we}` | Count of sessions by local departure hour | 24 bins over 0–24 h |
| `slack_dist_{wd,we}` | Count of sessions by idle time while plugged in, $s_i = (e_i - a_i) - E_i / P_c$ hours | 24 bins over 0–24 h; larger values are counted in the last bin |

The idle time $s_i$ is the part of a stay that is not needed to deliver the energy at rated power. It
is the time a smart-charging strategy can move charging within, and it links the User KPIs to the
flexibility view. It assumes the vehicle accepts the charger's rated power, so it is an upper bound.

`summary` adds the median and 90th percentile stay, the mean arrival time (a circular mean, so
23:30 and 00:30 average to midnight), `mean_slack_hours` and
$\texttt{slack\_share} = \sum_i s_i / \sum_i (e_i - a_i)$.

Values that a last bin absorbed are counted in `overflow`, per KPI (`duration`, `slack`,
`consumption`, `daily_consumption`) and day type, so that a long stay or a very large session is
never silently relabelled.

## Grid KPIs

| Field | Definition | Bins |
|---|---|---|
| `hour_of_arrival_consumption_{wd,we}` | Mean energy $E_i$ of the sessions arriving in each hour; `null` for hours without arrivals | 24 values |
| `consumption_dist_{wd,we}` | Count of sessions by energy $E_i$ | 10 bins over 0–100 kWh; larger values are counted in the last bin |
| `daily_consumption_dist_{wd,we}` | Count of **charger-days** by the energy delivered that local day, idle charger-days included | 10 bins over 0–200 kWh; larger values are counted in the last bin |
| `idle_charger_days_{wd,we}` | Charger-days with no energy delivered (all of them are in the first bin above) | integer |
| `load_profile_{wd,we}` | Mean uncontrolled load in kW for each half-hour of the local day | 48 values |
| `load_duration_kw` | The 10-minute uncontrolled load, sorted, sampled at the values exceeded 0, 5, …, 100 % of the time | 21 values |

The **uncontrolled load** is the as-fast-as-possible schedule: each session charges at rated power
from its true arrival for $E_i / P_c$ hours. It is the worst case a distribution grid sees without any
smart charging; the other strategies are compared under Environment. From the 10-minute load $L_t$,
`summary` reports

$$
\texttt{peak\_kw} = \max_t L_t, \qquad
\texttt{load\_factor} = \frac{\bar L}{\max_t L_t}, \qquad
\texttt{coincidence\_factor} = \frac{\max_t L_t}{\sum_c P_c},
$$

with `peak_time` the local time of the peak. A load factor near 1 is a flat load; a coincidence factor
near 1 means the chargers all draw at once.

## Mobility KPIs

For each charging point $c$ and each day in the range, count the sessions that start that day,
$n_{c,\text{day}}$; chargers without a session count as 0. Then, for each weekday $k \in \{0,\dots,6\}$
(Monday = 0):

| Field | Definition |
|---|---|
| `sessions_per_day_k` | Normalised histogram of $n_{c,\text{day}}$ over weekday $k$: 6 unit bins over 0–6, the last meaning "5 or more" |
| `sessions_per_day_mean`, `sessions_per_day_p90` | Mean and 90th percentile of $n_{c,\text{day}}$ per weekday; `null` when the range has no such weekday |
| `sessions_per_day_observations` | Number of charger-days behind each weekday |

`summary` adds `sessions_per_used_charger_day` (sessions divided by charger-days with any energy) and
the **idle gap**: for each charger, the time from one connection ending to the next starting, 0 for
back-to-back connections. `median_idle_gap_hours` is its median and `idle_gap_count` the number of
gaps. Gaps are only observed inside the range, so very long idle spells are truncated by it.

## City KPIs

### Availability by time of day

Each day is divided into 10-minute steps and every step is assigned to its local half-hour of the
day. For a selected set of charging points with occupied time $o_s$ (seconds, overlapping
connections of one charger counted once) in step $s$:

$$
A_j = 1 - \frac{\sum_{s \in j} o_s}{\sum_{s \in j} C \cdot \Delta},
$$

with $C$ the number of selected charging points, including those without sessions. $A_j$ is the
average share of chargers that are free in half-hour $j$, separately for weekdays and weekends. Local
time is used, so a daylight-saving day averages the hours that actually elapsed.

### Blocking probability

`weekday_blocking` and `weekend_blocking` give, per half-hour, the share of time during which **every**
selected charging point is occupied, that is, when a driver arriving would find nothing free. They are
`null` for an empty selection and for more than 2000 charging points, where the probability is
negligible and the occupancy grid would only cost memory. `summary.max_blocking_probability` is the
highest value.

### Occupancy and utilisation

The occupancy ratio of charger $c$ is the share of the range during which it is connected:

$$
\rho_c = \frac{\text{connected seconds of } c}{\text{seconds in range}} .
$$

`occupation_ratio_dist` is the histogram of $\rho_c$ over all selected charging points (20 bins over
0–1, normalised to sum to 1). Chargers without sessions are included with $\rho_c = 0$.

Occupancy counts a plugged-in vehicle that has finished charging. The **utilisation** counts only
energy delivered:

$$
u_c = \frac{\text{energy delivered by } c}{P_c \cdot \text{hours in range}} .
$$

For up to 200 charging points, `charger_usage` lists `id`, `occupancy`, `utilisation`, `sessions` and
`energy_kwh` per charger, in ascending ID order.

## Environment KPIs

The environment KPIs combine **three charging strategies** with the **hourly Dutch power mix** stored
in the `power_mixes` table (carbon intensity $\kappa_h$ in gCO₂eq/kWh and renewable share $\varphi_h$
in %, from Electricity Maps).

The range is walked in two-day blocks. For each block that has power-mix data, and for each strategy
$\sigma \in \{\text{afap}, \text{alap}, \text{avg}\}$:

1. Simulate the 288-step load profile $p^\sigma_t$ of the block (see {doc}`charging-strategies`).
2. Convert it to hourly energy, $E^\sigma_h = \sum_{t \in h} p^\sigma_t / 6$ for the 48 hours of the block.
3. Accumulate the hourly carbon footprint onto a 24-hour profile:

$$
\texttt{co2\_intensities\_}\sigma[h] \mathrel{+}= \kappa_h E^\sigma_h + \kappa_{h+24} E^\sigma_{h+24}
\qquad (h = 0,\dots,23).
$$

4. Accumulate renewable and total energy for the share:

$$
\texttt{renewable\_energy\_shared\_}\sigma =
100 \cdot \frac{\sum \tfrac{\varphi_h}{100} E^\sigma_h}{\sum E^\sigma_h} \quad [\%].
$$

| Field | Strategy |
|---|---|
| `co2_intensities_uncontrolled`, `renewable_energy_shared_uncontrolled` | As Fast As Possible |
| `co2_intensities_delayed`, `renewable_energy_shared_delayed` | As Late As Possible |
| `co2_intensities_avg`, `renewable_energy_shared_avg` | Average Power |

```{figure} ../_static/figures/db-power-mix.svg
:class: chart
:alt: Hourly carbon intensity and renewable share for the Netherlands

The power-mix data stored in the local database: hourly carbon intensity and renewable share for the Netherlands.
```

:::{note}
Blocks without power-mix data are skipped, and missing hours inside a block are padded with zeros.
Choose a KPI date range covered by the `power_mixes` table to get meaningful environment KPIs.
:::

## Response shape

```text
{
  "arrival_dist_wd": [24 ints], "arrival_dist_we": [24 ints],
  "duration_dist_wd": [24 ints], "duration_dist_we": [24 ints],
  "departure_dist_wd": [24 ints], "departure_dist_we": [24 ints],
  "slack_dist_wd": [24 ints], "slack_dist_we": [24 ints],
  "consumption_dist_wd": [10 ints], "consumption_dist_we": [10 ints],
  "daily_consumption_dist_wd": [10 ints], "daily_consumption_dist_we": [10 ints],
  "idle_charger_days_wd": int, "idle_charger_days_we": int,
  "hour_of_arrival_consumption_wd": [24 floats|null], "hour_of_arrival_consumption_we": [24 floats|null],
  "load_profile_wd": [48 floats|null], "load_profile_we": [48 floats|null],
  "load_duration_kw": [21 floats],
  "sessions_per_day_0": [6 floats], "...": "...", "sessions_per_day_6": [6 floats],
  "sessions_per_day_mean": [7 floats|null], "sessions_per_day_p90": [7 floats|null],
  "sessions_per_day_observations": [7 ints],
  "weekday_availability": [48 floats|null], "weekend_availability": [48 floats|null],
  "weekday_blocking": [48 floats|null], "weekend_blocking": [48 floats|null],
  "occupation_ratio_dist": [20 floats],
  "charger_usage": {"id": [...], "occupancy": [...], "utilisation": [...], "sessions": [...], "energy_kwh": [...]},
  "overflow": {"duration": {"wd": 0, "we": 0}, "slack": {...}, "consumption": {...}, "daily_consumption": {...}},
  "summary": {"session_count": 0, "median_duration_hours": 0.0, "peak_kw": 0.0, "...": "..."},
  "range": {"start_date": "...", "end_date": "...", "day_count": 7, "timezone": "Europe/Amsterdam"},
  "co2_intensities_uncontrolled": [24 floats], "co2_intensities_delayed": [24 floats], "co2_intensities_avg": [24 floats],
  "renewable_energy_shared_uncontrolled": 51.6, "renewable_energy_shared_delayed": 47.4, "renewable_energy_shared_avg": 45.9
}
```

The behavioural, grid, mobility and city fields come with `section=basic` (or `all`); the
`co2_*` and `renewable_*` fields with `section=environment` (or `all`).

Fields can be `null` for an empty group: an hour without arrivals, a weekday that the range does not
contain, a half-hour that is never observed. The frontend draws them as gaps rather than zeros.
