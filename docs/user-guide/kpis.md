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

1. Open the analysis panel and click **KPIs**. Each area card has its own **Date range** picker,
   pre-filled with the last seven days, and the KPIs are computed immediately.
2. Choose a start and an end date on a card. That area's KPIs refresh once both dates are picked;
   the other areas keep their own ranges.
3. Switch between the **User · Grid · Environment · Mobility · City** sub-tabs. Switching sub-tabs is
   instant: all five dashboards come from the same response, so only the chart is redrawn.

Each dashboard has one card per area, so up to three areas are compared directly, each over its own
date range. Distributions are shown as **shares of their own day type**: weekdays (five days) and
weekends (two) add up to 100 % each, so one is not dwarfed by the other, and areas of different size
or range read against each other. Counts are in the hover text. Areas share each chart's scale. There is no strategy setting here: behavioural KPIs do not depend on it, and the environment KPIs compute all
three local strategies at once.

:::{note}
Weekdays are Monday to Friday; weekends are Saturday and Sunday. Only sessions that **start on or
after** the start date and **end before** the end date are counted.
:::

## User

```{figure} ../_static/screenshots/kpi-user.jpg
:class: screenshot
:alt: User KPI dashboard with arrival, duration and departure distributions

User KPIs: arrival, duration and departure distributions, weekdays (blue) against weekends (orange).
```

| Chart | x-axis | y-axis | Question it answers |
|---|---|---|---|
| **Arrival time** | Hour of arrival (0–24) | Share of sessions (%) | When do drivers plug in? |
| **Connection time** | Hours connected (0–24+) | Share of sessions (%) | How long do vehicles stay connected? |
| **Departure time** | Hour of departure (0–24) | Share of sessions (%) | When do drivers unplug? |
| **Idle while plugged in** | Hours not needed to charge (0–24+) | Share of sessions (%) | How much of a stay could charging be moved within? |

The card beside the charts gives the number of sessions, the mean arrival time, the median and 90th
percentile stay, and the share of connected time that is idle. A "24+" label means the last bin also
holds longer stays; the card says how many there were.

## Grid

```{figure} ../_static/screenshots/kpi-grid.jpg
:class: screenshot
:alt: Grid KPI dashboard with session energy charts

Grid KPIs: uncontrolled load and the energy demand per arrival hour, per day and per session.
```

| Chart | x-axis | y-axis | Question it answers |
|---|---|---|---|
| **Uncontrolled load** | Hour of day (local) | Mean power (kW) | What does charging draw from the grid at each time of day if nothing is controlled? |
| **Load duration** | Share of time the power is exceeded (%) | Power (kW) | How peaky is the load, and for how long is it near its peak? |
| **Energy per session by arrival hour** | Hour of arrival | Mean energy (kWh) | Which arrival hours bring the most energy? Hours without arrivals are left empty |
| **Daily energy per charger** | Energy (kWh, 10 bins of 20 kWh, 200+) | Share of active charger-days (%) | How much does a charger deliver on a day it is used? |
| **Energy per session** | Energy per session (kWh, 10 bins of 10 kWh, 100+) | Share of sessions (%) | How large is a typical charging session? |

The card gives the peak load and when it happens, the **load factor** (mean over peak load; near 1 is
flat) and the **coincidence factor** (peak over the sum of rated powers; near 1 means everything
charges at once), and the share of charger-days with no charging at all. Those idle charger-days are
left out of *Daily energy per charger*, so they do not dwarf the days that charged.

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
:alt: Mobility KPI dashboard with sessions per charger for each weekday

Mobility KPIs: sessions per charger and day for each weekday.
```

| Chart | x-axis | y-axis | Question it answers |
|---|---|---|---|
| **Sessions per charger and day** | Weekday | Mean (bars) and 90th percentile (markers) | How often is a charger used on a Monday, a Tuesday, …? |
| **Charger-days by number of sessions** | Weekday | Share of charger-days (%), stacked by 0, 1, … 5+ sessions | How many charger-days are unused, or used several times? |

Weekdays that the date range does not contain are left empty, not drawn as zero. The card gives the
sessions per *used* charger-day, the median gap between two sessions on the same charger (how
quickly a charger turns over) and the share of charger-days without a session.

## City

```{figure} ../_static/screenshots/kpi-city.jpg
:class: screenshot
:alt: City KPI dashboard with free chargers by half-hour and occupancy per charger

City KPIs: free chargers and the chance that all are busy by time of day, and the use of each charger.
```

| Chart | x-axis | y-axis | Question it answers |
|---|---|---|---|
| **Free chargers** | Hour of day (local) | Share of chargers free | At what time of day is a charger most likely to be free? |
| **All chargers busy** | Hour of day (local) | Probability | When would an arriving driver find nothing free? |
| **Occupancy and utilisation** | Charger, busiest first | Share of time | Which chargers are connected most, and how much of their capacity delivers energy? |

*Occupancy* counts the time a vehicle is connected, including vehicles that have finished charging;
*utilisation* is the energy delivered against what the charger could deliver at its rated power. A big
gap between the two means chargers are occupied by vehicles that are not charging. For more than 30
chargers, the third chart shows how occupancy is spread over the chargers instead.

## Definitions

All formulas, bin edges and normalisations are listed in {doc}`../concepts/kpi-methodology`.
