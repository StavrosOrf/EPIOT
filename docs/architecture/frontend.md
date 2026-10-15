# Frontend

The frontend is a single HTML page (`templates/index.html`) driven by native ES modules in
`static/scripts/`. There is no build step: third-party libraries load from public CDNs, and the
application modules are served as-is by Flask.

## Modules

```{mermaid}
flowchart LR
    idx[index.html] --> landing[landing.js<br/>welcome dialog]
    idx --> script[script.js<br/>entry point · state · events]
    script --> loaders[loaders.js<br/>map markers]
    script --> plotter[plotter.js<br/>Plotly charts · area cards]
    script --> actions[group_actions.js<br/>move · copy · remove helpers]
    script --> utils[utils.js<br/>status bar · Excel export]
    script --> fetch[data_fetch.js<br/>KPI requests]
    fetch --> plotter
    fetch --> utils
```

| Module | Responsibility |
|---|---|
| `landing.js` | Opens or hides the welcome dialog (first visit, `?landing`, *About*), remembers *Don't show again*, exposes `window.EPIOT.openLanding / closeLanding / isLandingOpen`. Loaded as a deferred classic script. |
| `script.js` | Creates the Leaflet map and the draw tools, tracks drawn areas, wires every control, runs the load and flexibility analysis, manages tabs and the analysis panel, handles keyboard shortcuts, keeps each area's strategy, date and KPI range (`areaSettings`), and applies the area-card actions (move, duplicate, rename, remove) to the drawn areas and the result arrays. |
| `loaders.js` | Fetches charger and transformer markers for the not-yet-requested part of the viewport (Martinez polygon difference) and builds pop-ups. Also contains a heatmap helper (`calculateFlexibility`). |
| `data_fetch.js` | `get_KPIs`: resolves charging points per area, calls `/kpi/user` per area, and renders the active KPI dashboard. |
| `plotter.js` | All chart builders: `createGraph` (load profiles), `createPolytopeGraph` (flexibility), five KPI dashboards, and `showGraphMessage`. `renderGroupPanels` draws one card per area (rail with name and actions, plus its own Plotly plot) and handles sizing, typography, small-screen stacking and responsive re-layout on resize. The page registers the card actions through `setGroupControls`. |
| `group_actions.js` | Pure helpers for editing the area list from the cards: `moved`, `removed`, `copied`, `copyName`, `validName`, `escapeHtml`, `freeColor` and the `MAX_AREAS` limit. |
| `utils.js` | `animateSelectMessage` for the status bar, and `generateAndDownloadExcel` with its sheet builders. |
| `hexUtils.js` | H3 hexagon helpers (currently unused). |

## Application state

`script.js` keeps the state of the session in module-level variables:

| Variable | Content |
|---|---|
| `selected_polygons` | GeoJSON `Feature<Polygon>` per drawn area, in drawing order |
| `selected_area_names` | `Area N` label per area |
| `charger_ids_list` | Charging-point IDs per area |
| `transformer_ids_list` | `Middle` transformer IDs per area |
| `load_profile_data` | Per area: `pastData`, `futureData`, `past_/future_up_flex`, `past_/future_down_flex`, counts |
| `kpi_data_list` | Per area: `groupName`, `kpi` (endpoint response), counts |
| `areaSettings` | Per area name: `strategy`, `demand`, `date` (load, flexibility) and `range` (KPIs); edited on the cards, requested per area |
| `active_tab`, `active_kpi` | Current tab and KPI sub-tab |

## Event flow

```{mermaid}
flowchart TB
    subgraph Map["Map events"]
        direction LR
        D1[draw:created] --> V{valid and<br/>fewer than 3?}
        V -- yes --> ST[update areas,<br/>status bar, glow Analyse]
        D2[draw:deleted] --> ST
    end
    subgraph Panel["Analysis panel"]
        direction LR
        AN[Analyse / Enter] --> RUN{active tab}
        TAB[tab click<br/>single ↔ range date] --> RUN
        CHG[strategy · date · view] --> RUN
        RUN -- KPIs --> K[get_KPIs<br/>KPI renderer]
        RUN -- Load / Flexibility --> L[calculateLoadProfiles<br/>createGraph / createPolytopeGraph]
        SUB[KPI sub-tab] --> RR[redraw from memory]
        DL[Download report] --> X[generateAndDownloadExcel]
    end
    Map ~~~ Panel
```

## Chart rendering

All charts go through `renderPlot(data, layout)`, which:

- applies one typography and margin system (Inter, compact margins on narrow screens);
- stacks multi-column grids into one column when a column would be narrower than 300 px, keeping axis
  references valid because Plotly numbers grid cells row-major;
- wraps long subplot titles on small screens;
- re-lays out on window resize only when the layout mode (narrow/wide, stacked/grid) changes;
- configures the mode bar to export PNGs as `epiot_chart.png` at scale 2.

## Third-party libraries

| Library | Version | Loaded from |
|---|---|---|
| Leaflet | 1.9.4 | unpkg |
| Leaflet.draw | 1.0.4 | cdnjs |
| leaflet.heat | 0.2.0 | jsDelivr |
| Turf | 7.1.0 | jsDelivr |
| martinez-polygon-clipping | 0.7.4 | jsDelivr |
| Plotly.js | 2.35.2 | cdn.plot.ly |
| Flatpickr | 4.6.13 | jsDelivr |
| SheetJS (xlsx) | 0.18.5 | cdnjs |
| Bootstrap | 4.5.2 (+ jQuery 3.5.1 slim) | jsDelivr / code.jquery.com |
| Font Awesome | 4.7.0 | cdnjs |

## Styling

`static/css/styles.css` holds the application styles (app bar, floating toolbar, action bar, panel,
tabs, segmented control, responsive rules); `static/css/landing.css` styles the welcome dialog. The
`--header-h` CSS variable is kept in sync with the app bar height by a `ResizeObserver`, so floating
controls and the panel sit below the bar even when it wraps on small screens. The theme colour is
`#1f7a3f`.
