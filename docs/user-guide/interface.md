# The interface

EPIOT is a single-page application with two layers: a full-screen **map** for selecting what to
analyse, and an **analysis panel** that slides over the map to show results. This page names every
control; the following pages explain each one in depth.

## Welcome dialog

On your first visit EPIOT opens a welcome dialog that summarises the tool, its audiences, a
four-step how-to and the contact persons. Close it with **Continue to the app**, the **×** button, or
{kbd}`Esc`.

- Tick **Don't show this again** to suppress it on later visits (stored in the browser's
  `localStorage` under the key `epiotr_intro_seen`).
- Reopen it at any time with **About** in the app bar.
- Append `?landing` to the URL to force it open, for example when presenting the tool.

## Map screen

```{figure} ../_static/screenshots/anatomy-map.jpg
:class: screenshot
:alt: Map screen with numbered callouts on each control

The map screen. Numbers refer to the table below.
```

| # | Control | What it does |
|---|---|---|
| 1 | **EPIOT logo** | Reloads the application. |
| 2 | **About** | Reopens the welcome dialog. |
| 3 | **Search a location…** | Geocodes a place name with OpenStreetMap Nominatim and centres the map on the first match. See {ref}`user-guide/map:location search`. |
| 4 | **Chargers / Transformers** | Layer toggles. Chargers are on by default; Transformers shows MV/LV installations. |
| 5 | **Draw polygon** | Click points to outline an area; click the first point or double-click to finish. |
| 6 | **Draw rectangle** | Click and drag to draw a rectangular area. |
| 7 | **Delete shapes** | Click areas to remove them; click the tool again or press {kbd}`Esc` when done. |
| 8 | **Zoom** | Zoom in and out (levels 14–16). |
| 9 | **Status message** | Guidance and feedback: how many areas are selected, errors, search results. |
| 10 | **Analyse** | Opens the analysis panel and computes results for all drawn areas. Glows once an area is ready. |
| 11 | **Funding logos** | DRIVE2X, EU and UKRI attribution; links to the DRIVE2X website. |

## Analysis panel

```{figure} ../_static/screenshots/anatomy-panel.jpg
:class: screenshot
:alt: Analysis panel with numbered callouts on each control

The analysis panel on the **Load profiles** tab.
```

| # | Control | What it does |
|---|---|---|
| 1 | **Analysis** ⓘ | Panel title; the info icon explains that values are model predictions. |
| 2 | **Tabs** | *Load profiles*, *Flexibility* and *KPIs*. The KPI tab adds a row of sub-tabs: *User, Grid, Environment, Mobility, City*. |
| 3 | **Close** | Hides the panel ({kbd}`Esc` or a click on the visible map does the same). |
| 4 | **Source** ⓘ | Where the synthetic sessions come from: *Simple*, *Spatial* or *CPFT*. It applies to every area; the ⓘ explains the options. |
| 5 | **Export** (download icon) | Exports the current results to `DRIVE2X_EPIOT_report.xlsx`. |
| 6 | **Area cards** | One card per area with its own charging strategy, date and demand scenario (see below). |
| 7 | **Chart toolbar** | Plotly controls: save the chart as PNG (`epiot_chart.png`, 2× resolution), zoom, pan and reset axes. |

The ⓘ beside the KPI category bar lists what each category (*User, Grid, Environment, Mobility, City*) covers.

Which controls appear depends on the active tab:

| Control | Load profiles | Flexibility | KPIs |
|---|:---:|:---:|:---:|
| Source | ✓ | ✓ | ✓ |
| Export | ✓ | ✓ | ✓ |
| KPI sub-tabs | | | ✓ |
| Charging strategy (per area card) | ✓ | ✓ | |
| Target date (per area card) | ✓ | ✓ | |
| Date range (per area card) | | | ✓ |
| Demand scenario (per area card) | ✓ | ✓ | ✓ |

Changing the session source re-runs the analysis for every area. While the backend computes, the
chart area shows a spinner and an elapsed-seconds counter.

## Area cards

Every area gets its own card in the results. The cards share the height of the panel, so up to three
areas fit without scrolling on a normal screen; on a phone the rail sits above the plot.
The rail on the left of each card names the area (the stripe has the colour of its outline on the map),
gives its size, holds the area's own settings and four actions.

**Settings.** Each area is analysed under its own settings, so one area can be compared with itself
(or with another) under a different strategy, day or demand:

| Tab | Setting on the card | Notes |
|---|---|---|
| Load profiles, Flexibility | **Charging strategy** | *As Fast As Possible* (default), *As Late As Possible*, *Average Power*, *Min. Carbon Footprint*, *Min. Charging Cost*. |
| Load profiles, Flexibility | **Target date** | Any day; the chart covers that day and the day before. The field shows the weekday (`Sat 2026-10-17`); hover it for the day's calendar and weather effects. |
| KPIs | **Date range** | Applied once both dates are picked, shown with weekdays (`Fri 9 Oct – Thu 15 Oct`). New areas start with the last seven days. |
| All tabs | **Demand scenario** | *Low*, *Base* (default) or *High* demand: a sensitivity assumption for how many sessions start (half, 1×, 1.5×), not a confidence interval. |

Changing a setting recalculates **that area only**; its card dims while the request runs and the other
areas stay as they are. Settings are not shared between areas: a copy starts from its original's
settings and then changes independently.

**Name.** The pencil next to the name (or a double click on it) renames the area: press {kbd}`Enter`
to save, {kbd}`Esc` to cancel. Names must be unique and at most 40 characters. The new name is used
on the map label, in the cards and in the downloaded report.

**Actions.**

| Action | What it does |
|---|---|
| **Move up** / **Move down** | Reorders the areas. The map selection, the cards and the order of the downloaded report all follow. |
| **Duplicate below** | Adds a copy of the area (`Area 1 (copy)`) right below it, drawn on the map with a dashed outline. Unavailable at the limit of three areas. |
| **Remove** | Deletes the area from the map and from the results. |

Moving, copying, renaming and removing change the selection only: nothing is recalculated, and the
results already on screen are rearranged. Closing the panel shows the updated areas on the map.

## Panel state machine

```{mermaid}
stateDiagram-v2
    direction TB
    [*] --> Welcome: first visit
    Welcome --> Map: Continue / × / Esc
    Map --> Map: draw / delete areas
    Map --> Analysis: Analyse (≥ 1 area) or Enter
    Map --> Map: Analyse with no area → hint
    state Analysis {
        direction LR
        LoadProfiles --> Flexibility
        Flexibility --> KPIs
        KPIs --> LoadProfiles
    }
    Analysis --> Map: Close / Esc / click map
    Map --> Welcome: About
```

## Keyboard shortcuts

| Key | Context | Action |
|---|---|---|
| {kbd}`Enter` | Map, focus not in a form control, panel closed | Run **Analyse** |
| {kbd}`Enter` | Search box | Search for the typed location |
| {kbd}`Esc` | Welcome dialog open | Close the dialog |
| {kbd}`Esc` | Drawing or deleting | Cancel the active tool and hide its hint |
| {kbd}`Esc` | Analysis panel open | Close the panel |

## Small screens

The layout adapts to phones and narrow windows: the app bar wraps onto two rows, layer toggles
shrink to icons, and multi-column chart grids stack into a single column when a column would be
narrower than 300 px.

```{figure} ../_static/screenshots/mobile-map.jpg
:class: screenshot
:alt: EPIOT on a phone-sized screen
:width: 320px

EPIOT at phone width (390 px).
```
