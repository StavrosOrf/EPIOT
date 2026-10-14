---
myst:
  html_meta:
    description: "EPIOT — the Electromobility Prediction Tool of DRIVE2X. Quantify EV charging load and flexibility for any area on the map."
---

# EPIOT documentation

```{raw} html
<div class="hero">
  <span class="hero-kicker">DRIVE2X · Work Package 5</span>
  <div class="hero-title">Electromobility Prediction Tool</div>
  <p>EPIOT quantifies electric-vehicle charging demand and flexibility for any area you draw on a map.
  Pick a day and a charging strategy, compare up to three districts side by side, explore KPI
  dashboards for users, the grid, the environment, mobility and the city, and export everything to Excel.</p>
</div>
```

```{figure} _static/screenshots/areas-drawn.jpg
:class: screenshot
:alt: The EPIOT map with three analysis areas drawn over central Amsterdam
:width: 100%

Three areas drawn over central Amsterdam, ready to analyse. Every icon is a public charging point from the EPIOT database.
```

## Where to start

::::{grid} 1 2 2 3
:gutter: 3

:::{grid-item-card} {octicon}`rocket;1.2em` Getting started
:link: getting-started/introduction
:link-type: doc
:class-card: sd-card-hover

What EPIOT does, who it is for, and how to install and run it locally.
:::

:::{grid-item-card} {octicon}`device-desktop;1.2em` User guide
:link: user-guide/interface
:link-type: doc
:class-card: sd-card-hover

A tour of every screen: the map, area selection, load profiles, flexibility, KPIs and reports.
:::

:::{grid-item-card} {octicon}`light-bulb;1.2em` Concepts & methods
:link: concepts/charging-strategies
:link-type: doc
:class-card: sd-card-hover

How load and flexibility are computed, where session data comes from, and how every KPI is defined.
:::

:::{grid-item-card} {octicon}`stack;1.2em` Architecture
:link: architecture/overview
:link-type: doc
:class-card: sd-card-hover

System components, the data model, the backend and frontend modules, and the external services.
:::

:::{grid-item-card} {octicon}`plug;1.2em` REST API
:link: api/rest-api
:link-type: doc
:class-card: sd-card-hover

Every HTTP endpoint with parameters, response schemas and copy-paste examples.
:::

:::{grid-item-card} {octicon}`server;1.2em` Operations
:link: operations/database
:link-type: doc
:class-card: sd-card-hover

Building the database, scheduled data updates, and deploying behind a reverse proxy.
:::
::::

## Feature overview

| Feature | What you get | Read more |
|---|---|---|
| Interactive map | Charging points and MV/LV transformers on OpenStreetMap, location search, marker pop-ups | {doc}`user-guide/map` |
| Area selection | Up to three polygons or rectangles, compared side by side | {doc}`user-guide/areas` |
| Load profiles | Aggregated EV load over a 48-hour window at 10-minute resolution, per area | {doc}`user-guide/load-profiles` |
| Grid view | The same load seen from the medium-voltage/low-voltage transformers that serve the area | {doc}`user-guide/load-profiles` |
| Charging strategies | As fast as possible, as late as possible, average power, and cost-optimal (ReFlex) | {doc}`concepts/charging-strategies` |
| Flexibility | Upward and downward power flexibility of the EV fleet | {doc}`user-guide/flexibility` |
| KPI dashboards | User, grid, environment, mobility and city indicators over any date range | {doc}`user-guide/kpis` |
| Excel reports | One-click `.xlsx` export of profiles, charger lists and KPIs | {doc}`user-guide/reports` |

```{toctree}
:hidden:
:caption: Getting started

getting-started/introduction
getting-started/installation
getting-started/quickstart
```

```{toctree}
:hidden:
:caption: User guide

user-guide/interface
user-guide/map
user-guide/areas
user-guide/load-profiles
user-guide/flexibility
user-guide/kpis
user-guide/reports
```

```{toctree}
:hidden:
:caption: Concepts & methods

concepts/time-model
concepts/charging-strategies
concepts/flexibility
concepts/session-data
concepts/on-request-scenarios
concepts/calendar-effects
concepts/kpi-methodology
```

```{toctree}
:hidden:
:caption: Architecture

architecture/overview
architecture/data-model
architecture/backend
architecture/frontend
architecture/external-services
```

```{toctree}
:hidden:
:caption: API reference

api/rest-api
```

```{toctree}
:hidden:
:caption: Operations

operations/database
operations/scheduled-updates
operations/deployment
operations/configuration
```

```{toctree}
:hidden:
:caption: Development

development/project-structure
development/testing
map_performance
development/documentation
```

```{toctree}
:hidden:
:caption: Related tools

related-tools/cpft
related-tools/reflex
```

```{toctree}
:hidden:
:caption: Reference

reference/known-limitations
reference/troubleshooting
reference/glossary
reference/citing
```
