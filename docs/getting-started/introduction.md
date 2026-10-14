# Introduction

**EPIOT** (Electromobility Prediction Tool) is a web application developed in Work Package 5 of the
[DRIVE2X](https://drive2x.eu/) project. It answers a question that charge point operators, grid
operators and city planners all share:

> *How much power will electric vehicles draw in this neighbourhood, when, and how much of it could be shifted?*

You draw an area on a map, pick a day and a charging strategy, and EPIOT returns the aggregated EV
charging load of every charging point inside that area, together with the upward and downward
flexibility the vehicles provide. A set of KPI dashboards summarises charging behaviour over longer
periods, and every result can be exported to Excel.

```{figure} ../_static/screenshots/landing.jpg
:class: screenshot
:alt: EPIOT welcome dialog listing main functions, audiences and a how-to-use guide

The welcome dialog shown on first visit. It can be reopened at any time from **About** in the app bar.
```

## What EPIOT can do

::::{grid} 1 2 2 2
:gutter: 2

:::{grid-item-card} {octicon}`pencil` Select custom areas
Draw up to **three** polygons or rectangles anywhere on the map and compare them side by side.
:::

:::{grid-item-card} {octicon}`graph` Predict EV load
Aggregated charging power for the selected day and the day before, at **10-minute** resolution.
:::

:::{grid-item-card} {octicon}`arrow-switch` Quantify flexibility
Upward and downward power flexibility of the connected vehicles under each charging strategy.
:::

:::{grid-item-card} {octicon}`zap` See the grid side
Switch to **Grid** view to aggregate the chargers behind the MV/LV transformers in an area.
:::

:::{grid-item-card} {octicon}`pulse` Explore KPI dashboards
Five dashboards (user, grid, environment, mobility, city) computed over any date range.
:::

:::{grid-item-card} {octicon}`download` Export reports
A multi-sheet `.xlsx` report with load, flexibility, charger lists and KPI distributions.
:::
::::

## Who it is for

| Audience | Typical question EPIOT helps answer |
|---|---|
| **Charge point operators (CPOs)** | How busy are my chargers, and how much flexibility could I offer to the grid? |
| **DSOs and city energy teams** | What EV load lands on this MV/LV transformer, and at which hours? |
| **Urban mobility planners** | When do people arrive and leave, and how long do they stay plugged in? |
| **Researchers and students** | How do smart-charging strategies change peak load and carbon intensity? |
| **Policymakers** | What share of EV charging is covered by renewable electricity? |

## How it works, in one picture

```{mermaid}
flowchart TB
    U([User]) -->|draws areas, picks date & strategy| UI[Web UI<br/>Leaflet · Plotly]
    UI -->|GeoJSON polygon| S[/stations/within/]
    UI -->|charger IDs + date + strategy| A[/stations/aggregate_load/]
    UI -->|charger IDs + date range| K[/kpi/user/]
    S --> DB[(SQLite +<br/>SpatiaLite)]
    A --> DB
    K --> DB
    A --> AG{{Charging-strategy<br/>simulators}}
    K --> AG
    AG -. ocost only .-> RF[ReFlex optimiser]
    AG -. ocost only .-> EC[Energy-Charts<br/>day-ahead prices]
    DB -. power mix .- EM[Electricity Maps]
    AG -->|load, up/down flexibility| UI
    K -->|distributions, CO₂, renewables| UI
```

1. The **map** shows charging points and transformers loaded from a spatial database.
2. When you click **Analyse**, the browser asks the backend which charging points lie inside each drawn area.
3. For each area, the backend loads the **charging sessions** of those points for the chosen day and the day before.
4. A **charging-strategy simulator** turns the sessions into a power profile plus flexibility signals.
5. The browser plots the result with Plotly and keeps it in memory for the Excel export.

See {doc}`../architecture/overview` for the full component diagram.

## Project context

EPIOT is part of DRIVE2X, a project funded by the European Union and UK Research and Innovation
that develops vehicle-to-everything (V2X) solutions. The current deployment covers the city of
**Amsterdam**: charging points come from an open charging-station registry, transformers from the
Liander grid dataset published on PDOK, and neighbourhood boundaries from the CBS
*wijken en buurten* dataset.

The tool is a research prototype. Some features, such as machine-learning session prediction, are
under active development; the relevant pages say so explicitly. {doc}`../reference/known-limitations`
lists the current modelling simplifications.

:::{seealso}
- {doc}`installation` to run EPIOT on your own machine.
- {doc}`quickstart` for a five-minute guided tour.
- {doc}`../reference/citing` for the related publication.
:::
