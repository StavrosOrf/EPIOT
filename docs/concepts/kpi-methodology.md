# KPI methodology

All KPIs are computed by one endpoint, `GET /kpi/user` (implemented in `backend/kpi/user.py`), for the
charging points of one area and a date range $[d_0, d_1]$. This page defines each returned field.

## Input set

Let $\mathcal{S}$ be the sessions of the area's charging points with

$$
\text{start} \ge d_0 \quad\text{and}\quad \text{end} \le d_1 .
$$

For each session $i$: arrival $a_i$, departure $e_i$, energy $E_i$ (kWh), day of week $w_i \in
\{0,\dots,6\}$ (Monday = 0). A session is a **weekday** session if $w_i < 5$ and a **weekend**
session otherwise. Every behavioural KPI is computed separately for both groups (`_wd`, `_we`).

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
| `arrival_dist_{wd,we}` | Count of sessions by arrival hour $\lfloor a_i \rfloor_h$ | 24 bins over 0–24 h |
| `duration_dist_{wd,we}` | Count of sessions by connection time $e_i - a_i$ in hours | 24 bins over 0–24 h |
| `departure_dist_{wd,we}` | Count of sessions by departure hour $\lfloor e_i \rfloor_h$ | 24 bins over 0–24 h |

Connection times are taken modulo 24 hours (the time-of-day part of $e_i - a_i$).

## Grid KPIs

| Field | Definition | Bins |
|---|---|---|
| `hour_of_arrival_consumption_{wd,we}` | Mean energy per session by arrival hour, computed as $2\sum_{i \in h} E_i \,/\, (1 + 2\lvert h\rvert)$, which approaches the plain mean for busy hours and is 0 for empty hours | 24 values |
| `consumption_dist_{wd,we}` | Count of sessions by energy $E_i$ | 10 bins over 0–100 kWh |
| `daily_consumption_dist_{wd,we}` | Count of energy totals grouped by (date, session energy) | 10 bins over 0–200 kWh |

## Mobility KPIs

For each charging point $c$ and each day in the range, count the sessions that start that day,
$n_{c,\text{day}}$. Then, for each weekday $k \in \{0,\dots,6\}$:

$$
\texttt{sessions\_per\_day\_}k = \operatorname{density}\big(\{\, n_{c,\text{day}} : \text{day has weekday } k \,\}\big),
$$

a normalised histogram with 5 unit bins over 0–5 sessions.

## City KPIs

### Availability by time of day

The range is divided into 30-minute slots. For each slot, EPIOT counts the sessions in progress
$o_s$ (occupied charger-slots). Slots are folded onto a 48-slot day and summed separately over
weekdays and weekends, giving $O^{wd}_j$ and $O^{we}_j$ for $j = 0,\dots,47$. The displayed
availability index is the complement relative to the peak:

$$
A_j = 1.1 \cdot \max_j O_j - O_j .
$$

Higher values mean more chargers are free at that time of day. The index is relative and comparable
within an area and day type, not an absolute probability.

### Occupancy ratio

For each charging point, the fraction of 30-minute slots in the range during which it is occupied:

$$
\rho_c = \frac{\#\{\text{occupied slots of } c\}}{\#\{\text{slots in range}\}} .
$$

`occupation_ratio_dist` is the density histogram of $\rho_c$ over the area's charging points (20 bins
over 0–1). Only charging points with at least one session contribute.

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
  "consumption_dist_wd": [10 ints], "consumption_dist_we": [10 ints],
  "daily_consumption_dist_wd": [10 ints], "daily_consumption_dist_we": [10 ints],
  "hour_of_arrival_consumption_wd": [24 floats], "hour_of_arrival_consumption_we": [24 floats],
  "sessions_per_day_0": [5 floats], "...": "...", "sessions_per_day_6": [5 floats],
  "weekday_availability": [48 floats], "weekend_availability": [48 floats],
  "occupation_ratio_dist": [20 floats],
  "co2_intensities_uncontrolled": [24 floats], "co2_intensities_delayed": [24 floats], "co2_intensities_avg": [24 floats],
  "renewable_energy_shared_uncontrolled": 51.6, "renewable_energy_shared_delayed": 47.4, "renewable_energy_shared_avg": 45.9
}
```

Some fields can be `NaN` when a group is empty; the frontend replaces `NaN` with `null` before
parsing.
