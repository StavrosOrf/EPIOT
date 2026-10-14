# KPI dashboards

The **KPIs** tab summarises charging behaviour in each area over a **date range** rather than a
single day. It groups the indicators into five dashboards, one per stakeholder perspective:

::::{grid} 1 2 3 5
:gutter: 2

:::{grid-item-card} User
:text-align: center
When drivers arrive, how long they stay, when they leave.
:::

:::{grid-item-card} Grid
:text-align: center
Energy per session, per day and per arrival hour.
:::

:::{grid-item-card} Environment
:text-align: center
Carbon intensity and renewable share per strategy.
:::

:::{grid-item-card} Mobility
:text-align: center
Sessions per charger for each weekday.
:::

:::{grid-item-card} City
:text-align: center
Charger availability and occupancy.
:::
::::

## Using the KPI tab

1. Open the analysis panel and click **KPIs**. The date control becomes a **Date range** picker,
   pre-filled from 1 September 2025 to today, and the KPIs are computed immediately.
2. Choose a start and an end date. The KPIs refresh once both dates are picked.
3. Switch between the **User · Grid · Environment · Mobility · City** sub-tabs. Switching sub-tabs is
   instant: all five dashboards come from the same response, so only the chart is redrawn.

Each dashboard has one row per area, so up to three areas are compared directly. The strategy
drop-down is hidden here: behavioural KPIs do not depend on it, and the environment KPIs compute all
three local strategies at once.

:::{note}
Weekdays are Monday to Friday; weekends are Saturday and Sunday. Only sessions that **start on or
after** the start date and **end before** the end date are counted.
:::

## User

```{figure} ../_static/screenshots/kpi-user.jpg
:class: screenshot
:alt: User KPI dashboard with arrival, duration and departure distributions

User KPIs: arrival, duration and departure distributions, weekdays (blue) against weekends (red).
```

| Chart | x-axis | y-axis | Question it answers |
|---|---|---|---|
| **Arrival Distribution** | Hour of arrival (0–23) | Number of sessions | When do drivers plug in? |
| **Duration Distribution** | Connection time in hours (0–24) | Number of sessions | How long do vehicles stay connected? |
| **Departure Distribution** | Hour of departure (0–23) | Number of sessions | When do drivers unplug? |

## Grid

```{figure} ../_static/screenshots/kpi-grid.jpg
:class: screenshot
:alt: Grid KPI dashboard with session energy charts

Grid KPIs: energy demand per arrival hour, per day and per session.
```

| Chart | x-axis | y-axis | Question it answers |
|---|---|---|---|
| **Session Energy Distribution** | Hour of arrival | Mean energy per session (kWh) | Which arrival hours bring the most energy demand? |
| **Daily Charger Energy Consumption** | Energy (kWh, 10 bins of 20 kWh) | Count | How much energy do chargers deliver? |
| **Session Energy Consumption Distribution** | Energy per session (kWh, 10 bins of 10 kWh) | Number of sessions | How large is a typical charging session? |

## Environment

```{figure} ../_static/screenshots/kpi-environment.jpg
:class: screenshot
:alt: Environment KPI dashboard with carbon intensity per hour and renewable share bars

Environment KPIs: hourly carbon footprint and renewable share for three strategies.
```

| Chart | x-axis | y-axis | Question it answers |
|---|---|---|---|
| **Total Carbon Intensity** | Hour of day | Emissions attributed to that hour, summed over the range | At which hours does EV charging cause the most CO₂ under each strategy? |
| **Renewable Energy Share** | Strategy | % of charged energy from renewables | Which strategy uses the greenest electricity? |

The environment KPIs combine the charging profile of each strategy with the hourly Dutch power mix
(carbon intensity and renewable share). Dates with imported observations use them; other dates use a
clearly labelled historical reference day, resolved for each request; see {doc}`../environmental_kpis`.

## Mobility

```{figure} ../_static/screenshots/kpi-mobility.jpg
:class: screenshot
:alt: Mobility KPI dashboard with one curve per weekday

Mobility KPIs: distribution of sessions per charger per day, one curve per weekday.
```

| Chart | x-axis | y-axis | Question it answers |
|---|---|---|---|
| **Number of Charger Sessions per Day** | Sessions per charger per day (0–5) | Probability | How often is a charger used on a Monday, a Tuesday, …? |

## City

```{figure} ../_static/screenshots/kpi-city.jpg
:class: screenshot
:alt: City KPI dashboard with availability by half-hour and occupancy ratio distribution

City KPIs: charger availability by time of day and the occupancy-ratio distribution.
```

| Chart | x-axis | y-axis | Question it answers |
|---|---|---|---|
| **Charger Availability Probability** | Time of day (48 half-hour slots) | Relative availability index | At what time of day are chargers most likely to be free? |
| **Charger Occupancy Ratio** | Share of time a charger is occupied (%) | Probability density | Are chargers in this area under- or over-used? |

## Definitions

All formulas, bin edges and normalisations are listed in {doc}`../concepts/kpi-methodology`.
