# Quickstart

This five-minute tour takes you from an empty map to a downloaded report. It assumes the app is
running (see {doc}`installation`) or that you have access to a hosted instance.

```{mermaid}
flowchart TB
    A[1 · Find your area] --> B[2 · Draw up to 3 areas]
    B --> C[3 · Analyse]
    C --> D[4 · Pick date & strategy]
    D --> E[5 · Switch views]
    E --> F[6 · Download report]
```

## 1. Find your area

Close the welcome dialog with **Continue to the app**. Pan and zoom the map, or type a place into
**Search a location…** and press {kbd}`Enter`. Charging points appear as charger icons; switch on
**Transformers** in the app bar to see the MV/LV grid.

```{figure} ../_static/screenshots/map-overview.jpg
:class: screenshot
:alt: Map of central Amsterdam with charger icons

The map after closing the welcome dialog. The draw toolbar is on the left, the zoom buttons on the right, and the status bar with the **Analyse** button at the bottom.
```

## 2. Draw up to three areas

Click the **rectangle** (or **polygon**) tool on the left and drag across the map. Each new area gets
its own colour and a label (*Area 1*, *Area 2*, *Area 3*). The status bar confirms how many areas are
selected.

```{figure} ../_static/screenshots/areas-drawn.jpg
:class: screenshot
:alt: Three coloured rectangles drawn over Amsterdam

Three areas drawn: green, red and blue. The status bar reads "3 of 3 areas selected. Ready to analyse".
```

## 3. Analyse

Click **Analyse** (or press {kbd}`Enter` while the map has focus). The analysis panel slides in and
shows a loading timer while the backend computes the profiles.

## 4. Pick a date and a strategy

In the panel, choose a **Date** and a **Charging strategy**. The chart refreshes automatically
after each change.

```{figure} ../_static/screenshots/load-profiles.jpg
:class: screenshot
:alt: Analysis panel showing aggregated load profiles for Area 1 and Area 2

Load profiles for 15 October 2025 with the *As Fast As Possible* strategy. Green is the day before (*Yesterday*), blue the selected day (*Today*).
```

## 5. Switch views

| Tab | Shows | Guide |
|---|---|---|
| **Load profiles** | Aggregated charging power per area; toggle **Chargers / Grid** | {doc}`../user-guide/load-profiles` |
| **Flexibility** | Upward and downward flexibility per area | {doc}`../user-guide/flexibility` |
| **KPIs** | Five dashboards over a date range | {doc}`../user-guide/kpis` |

## 6. Download the report

Click **Download report**. EPIOT writes `DRIVE2X_EPIOT_report.xlsx` with the load and flexibility
time series, the charger IDs per area, and (if you opened the KPI tab) one KPI sheet per area. See
{doc}`../user-guide/reports` for the full layout.

:::{tip}
Press {kbd}`Esc` to close the analysis panel and return to the map. Your areas stay in place, so
you can add, delete or redraw areas and analyse again.
:::
