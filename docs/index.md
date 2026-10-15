---
myst:
  html_meta:
    description: "EPIOT, the Electromobility Prediction Tool of DRIVE2X: EV charging load, flexibility and KPIs for any area on the map."
---

# EPIOT

```{raw} html
<div class="epiot-funding epiot-funding--hero">
  <a href="https://drive2x.eu/" title="DRIVE2X project"><img src="_static/logos/drive2x.png" alt="DRIVE2X"></a>
  <a href="https://european-union.europa.eu/" title="European Union"><img src="_static/logos/eu.png" alt="Co-funded by the European Union"></a>
  <a href="https://www.ukri.org/" title="UK Research and Innovation"><img src="_static/logos/ukri.png" alt="UK Research and Innovation"></a>
</div>
<p class="epiot-eyebrow">Electromobility Prediction Tool · <a href="https://drive2x.eu/">DRIVE2X</a> Work Package 5</p>
<p class="epiot-lead">
  Quantify electric-vehicle charging load and flexibility for any area on the map. Draw up to
  three areas, choose a day, a charging strategy and a session source, and compare load profiles,
  flexibility envelopes and KPIs side by side.
</p>
```

````{div} epiot-actions
```{button-ref} getting-started
:color: primary
:shadow:
Get started
```

```{button-link} https://drive2x.eu/
:color: secondary
:outline:
The DRIVE2X project
```

```{button-link} https://github.com/StavrosOrf/EPIOT
:color: secondary
:outline:
Source on GitHub
```
````

```{raw} html
<div class="epiot-stats">
  <div class="epiot-stat"><strong>3</strong>areas compared side by side</div>
  <div class="epiot-stat"><strong>5</strong>charging strategies</div>
  <div class="epiot-stat"><strong>5</strong>KPI dashboards</div>
  <div class="epiot-stat"><strong>590k</strong>charging points on the map</div>
  <div class="epiot-stat"><strong>10 min</strong>time resolution</div>
</div>
```

```{figure} _static/screenshots/panel-load-profiles.jpg
:class: screenshot
:alt: The EPIOT analysis panel with the load profiles of three areas

Load profiles of three areas over central Amsterdam, each under its own charging strategy.
```

:::{note}
EPIOT receives no live charging data. All results are synthetic scenarios with assumed demand, not
verified forecasts of local charging.
:::

## What EPIOT can do

::::{grid} 1 2 2 4
:gutter: 3
:class-container: epiot-features

:::{grid-item-card} {octicon}`rocket;1.1em` Getting started
:link: getting-started
:link-type: doc

Install, run a first analysis and see which regions are covered.
:::

:::{grid-item-card} {octicon}`location;1.1em` Map and areas
:link: map-and-areas
:link-type: doc

Search a city, browse chargers and transformers, and draw up to three areas.
:::

:::{grid-item-card} {octicon}`database;1.1em` Session sources
:link: session-sources
:link-type: doc

Simple, Spatial and CPFT scenarios at low, base or high demand, with day effects.
:::

:::{grid-item-card} {octicon}`zap;1.1em` Charging strategies
:link: charging-strategies
:link-type: doc

Five rules for when vehicles draw their energy, from fastest to cheapest.
:::

:::{grid-item-card} {octicon}`graph;1.1em` Load profiles
:link: load-profiles
:link-type: doc

Aggregated charging power for each area over two days.
:::

:::{grid-item-card} {octicon}`arrow-switch;1.1em` Flexibility
:link: flexibility
:link-type: doc

The feasible power envelope and the upward and downward headroom.
:::

:::{grid-item-card} {octicon}`checklist;1.1em` KPIs
:link: kpis
:link-type: doc

User, Grid, Environment, Mobility and City indicators.
:::

:::{grid-item-card} {octicon}`download;1.1em` Reports
:link: reports
:link-type: doc

An Excel workbook with the data and chart images of every dashboard.
:::
::::

## EPIOT in action

::::{tab-set}

:::{tab-item} Areas on the map
```{figure} _static/screenshots/areas-drawn.jpg
:class: screenshot
:alt: Three areas drawn over central Amsterdam
Three areas drawn over central Amsterdam, ready to analyse.
```
:::

:::{tab-item} Load profiles
```{figure} _static/screenshots/panel-load-profiles.jpg
:class: screenshot
:alt: The load profiles of three areas
Aggregated charging power of the three areas over two days.
```
:::

:::{tab-item} Flexibility
```{figure} _static/screenshots/panel-flexibility.jpg
:class: screenshot
:alt: The flexibility envelope of an area
The scheduled load of each area inside its feasible power and cumulative-energy envelope.
```
:::

:::{tab-item} KPIs
```{figure} _static/screenshots/kpi-grid.jpg
:class: screenshot
:alt: The Grid KPI dashboard
The Grid dashboard, one of five KPI dashboards, shown per area.
```
:::
::::

## How it works

::::{grid} 1 2 2 4
:gutter: 3

:::{grid-item-card} 1 · Draw
Mark up to three areas as polygons or rectangles anywhere in the covered regions.
:::

:::{grid-item-card} 2 · Configure
Pick a date, a session source with its demand level and a charging strategy per area.
:::

:::{grid-item-card} 3 · Analyse
Review load profiles, flexibility and five KPI dashboards for every area.
:::

:::{grid-item-card} 4 · Export
Download the Excel report, or call the {doc}`REST API <rest-api>` from your own tools.
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

## Reference

::::{grid} 1 2 2 4
:gutter: 3

:::{grid-item-card} {octicon}`plug;1.1em` REST API
:link: rest-api
:link-type: doc

Endpoints, parameters and a worked example.
:::

:::{grid-item-card} {octicon}`table;1.1em` Data schema
:link: data-schema
:link-type: doc

Tables, relationships and input files.
:::

:::{grid-item-card} {octicon}`workflow;1.1em` Architecture
:link: architecture
:link-type: doc

Components, request flow and modules.
:::

:::{grid-item-card} {octicon}`tools;1.1em` Operations
:link: operations
:link-type: doc

Configuration, deployment and maintenance.
:::
::::

## Project and collaborators

EPIOT is developed in Work Package 5 of [DRIVE2X](https://drive2x.eu/), the Horizon Europe project
on mass deployment of vehicle-to-everything (V2X) charging. The work package brings together the
development team and three further partners.
See the [DRIVE2X consortium](https://drive2x.eu/about/) for the full project partnership.

::::{grid} 1 2 3 3
:gutter: 3

:::{grid-item-card} DLR
:class-card: epiot-partner
Deutsches Zentrum für Luft- und Raumfahrt · Germany

*Development team*
:::

:::{grid-item-card} TU Delft
:class-card: epiot-partner
Delft University of Technology · Netherlands

*Development team*
:::

:::{grid-item-card} TNO
:class-card: epiot-partner
Netherlands Organisation for Applied Scientific Research · Netherlands

*WP5 partner*
:::

:::{grid-item-card} Labelec
:class-card: epiot-partner
Labelec · Portugal

*WP5 partner*
:::

:::{grid-item-card} University of Salford
:class-card: epiot-partner
University of Salford · United Kingdom

*WP5 partner*
:::
::::

## Funding

[DRIVE2X](https://drive2x.eu/) has received funding from the European Union's Horizon Europe
research and innovation programme under Grant Agreement No. 101056934. The UK participants are
funded by UK Research and Innovation (UKRI). Views and opinions expressed are those of the
author(s) only and do not necessarily reflect those of the European Union or the granting
authority. Neither the European Union nor the granting authority can be held responsible for them.

## Citation and contact

> Ravanbach, B., Turhan, E., Wulff, N., Orfanoudakis, S., Vergara, P. P., Vahidinasab, V., Dias, L.,
> & Mendes, G. (2024). *A dynamic prediction tool for vehicle-to-grid operation and planning.* In
> *2024 IEEE 22nd Mediterranean Electrotechnical Conference (MELECON)*.

Contact: [Stavros Orfanoudakis](https://www.stavrosorfanoudakis.com/) (TU Delft,
<s.orfanoudakis@tudelft.nl>) and
[Babak Ravanbach](https://www.linkedin.com/in/babakpr/) (DLR, <babak.ravanbach@dlr.de>).

The source code is on [GitHub](https://github.com/StavrosOrf/EPIOT) and these pages are hosted on
[Read the Docs](https://epiot.readthedocs.io/en/latest/). Project news and the consortium are on the
[DRIVE2X website](https://drive2x.eu/). EPIOT is released under the BSD-3-Clause licence.

```{toctree}
:hidden:
:caption: Guide

getting-started
map-and-areas
session-sources
charging-strategies
load-profiles
flexibility
kpis
reports
```

```{toctree}
:hidden:
:caption: Reference

rest-api
data-schema
architecture
operations
```
