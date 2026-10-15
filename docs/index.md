---
myst:
  html_meta:
    description: "EPIOT, the Electromobility Prediction Tool of DRIVE2X: EV charging load, flexibility and KPIs for any area on the map."
---

# EPIOT

**Electromobility Prediction Tool** · DRIVE2X Work Package 5

EPIOT quantifies electric-vehicle charging load and flexibility for areas drawn on a map. Choose a
date, a charging strategy and a session source, compare up to three areas side by side, review five
KPI dashboards, and export the results to Excel.

:::{note}
EPIOT receives no live charging data. All results are synthetic scenarios with assumed demand, not
verified forecasts of local charging.
:::

::::{grid} 1 2 2 3
:gutter: 3

:::{grid-item-card} Getting started
:link: getting-started
:link-type: doc

Install, run an analysis, data coverage, configuration and endpoints.
:::

:::{grid-item-card} Session sources
:link: session-sources
:link-type: doc

Simple, Spatial and CPFT scenarios, demand levels and day effects.
:::

:::{grid-item-card} Load profiles
:link: load-profiles
:link-type: doc

Aggregated charging power and the five charging strategies.
:::

:::{grid-item-card} Flexibility
:link: flexibility
:link-type: doc

The feasible envelope and upward and downward headroom.
:::

:::{grid-item-card} KPIs
:link: kpis
:link-type: doc

User, Grid, Environment, Mobility and City indicators.
:::
::::

## At a glance

| | |
|---|---|
| **Areas** | Up to three polygons or rectangles, compared side by side |
| **Time** | Any past or future date; 10-minute resolution; local days in Europe/Amsterdam |
| **Sessions** | Synthetic scenarios from Simple, Spatial or CPFT sources, at low, base or high demand |
| **Strategies** | As Fast As Possible, As Late As Possible, Average Power, Min. Carbon Footprint, Min. Charging Cost |
| **Outputs** | Load profiles, flexibility envelopes, five KPI dashboards, Excel report |
| **Coverage** | About 590,000 charging points in the Netherlands, Germany, France, Switzerland, Finland and seven further cities; transformers and the spatial atlas for Amsterdam |

## Citation and contact

> Ravanbach, B., Turhan, E., Wulff, N., Orfanoudakis, S., Vergara, P. P., Vahidinasab, V., Dias, L.,
> & Mendes, G. (2024). *A dynamic prediction tool for vehicle-to-grid operation and planning.* In
> *2024 IEEE 22nd Mediterranean Electrotechnical Conference (MELECON)*.

Contact: Babak Ravanbach (DLR, <babak.ravanbach@dlr.de>) and Stavros Orfanoudakis (TU Delft,
<s.orfanoudakis@tudelft.nl>). EPIOT is developed in [DRIVE2X](https://drive2x.eu/), funded by the
European Union and UK Research and Innovation, and released under the BSD-3-Clause licence.

```{toctree}
:hidden:

getting-started
session-sources
load-profiles
flexibility
kpis
```
