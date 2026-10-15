# Reports and exports

EPIOT exports results in two ways: a multi-sheet Excel report of the underlying numbers, and
images of individual charts.

## Excel report

Click the **Export** (download) icon in the analysis panel's header. The browser builds the workbook locally with
[SheetJS](https://sheetjs.com/) from the results already on screen (no extra server request) and
saves it as **`DRIVE2X_EPIOT_report.xlsx`**.

```{mermaid}
flowchart LR
    subgraph Browser memory
        LP[load_profile_data<br/>per area]
        CI[charger_ids_list<br/>per area]
        KP[kpi_data_list<br/>per area]
    end
    LP --> S1["Sheet 'Load Data'"]
    CI --> S2["Sheet 'Charger IDs'"]
    KP --> S3["Sheet 'Area N_KPIs'<br/>(one per area)"]
    S1 & S2 & S3 --> X[[DRIVE2X_EPIOT_report.xlsx]]
```

The report contains whatever has been computed in the current session: run the **Load profiles**
or **Flexibility** tab to fill the first two sheets, and the **KPIs** tab to add the KPI sheets.

:::{important}
KPI sheets take their names from the load-profile results. For a complete report, open
**Load profiles** (or **Flexibility**) first and **KPIs** second, then download.
:::

### Sheet `Load Data`

One row per area and 10-minute step (288 rows per area).

| Column | Unit | Content |
|---|---|---|
| `Area Name` | | *Area 1*, *Area 2*, … |
| `Timestamp` | `YYYY-MM-DD HH:mm:ss` | Time of the step |
| `EV Load (kWh)` | kW | Aggregated charging power for the step |
| `Upward Flexibility (kW)` | kW | Upward flexibility for the step |
| `Downward Flexibility (kW)` | kW | Downward flexibility (negative) |
| `Charging strategy` | | The strategy the area card was set to |

:::{admonition} Units and timestamps
:class: warning

The `EV Load` column holds **power in kW**, the same values that are plotted; divide by 6 to get the
energy in kWh delivered in each 10-minute step.

The `Timestamp` column is currently generated relative to the **day you download the report**, not the
date selected in the panel. Use the step order (row 1 = 00:00 of the day before the selected date) to
align rows with the chart. This is tracked in {doc}`../reference/known-limitations`.
:::

### Sheet `Charger IDs`

One row per charging point and area: `Area Name`, `Charger IDs`.

### Sheets `Area N_KPIs`

Added once per area after the KPI tab has been opened. Each row holds one distribution: the first
cell is its name, the following cells are its values.

| Row | Values | Description |
|---|---|---|
| `arrival_dist_wd`, `arrival_dist_we` | 24 | Sessions per arrival hour, weekday / weekend |
| `consumption_dist_wd`, `consumption_dist_we` | 10 | Sessions per energy bin (0–100 kWh) |
| `daily_consumption_dist_wd`, `daily_consumption_dist_we` | 10 | Count per energy bin (0–200 kWh) |
| `departure_dist_wd`, `departure_dist_we` | 24 | Sessions per departure hour |
| `duration_dist_wd`, `duration_dist_we` | 24 | Sessions per duration bin (0–24 h) |
| `hour_of_arrival_consumption_wd`, `…_we` | 24 | Mean energy per session by arrival hour (kWh) |
| `occupation_ratio_dist` | 20 | Density of charger occupancy ratio (0–1) |
| `sessions_per_day_0` … `sessions_per_day_6` | 5 | Density of sessions per charger per day, Monday (0) to Sunday (6) |
| `weekday_availability`, `weekend_availability` | 48 | Relative availability index per half-hour slot |

The environment KPIs are not part of the export. See {doc}`../concepts/kpi-methodology` for the
definition of each row.

## Chart images

Every chart has a Plotly toolbar in its top-right corner that appears when you hover over the chart.
The camera icon saves the current chart as **`epiot_chart.png`** at twice the screen resolution,
ready for slides and reports. The other buttons zoom, pan and reset the axes. On narrow screens the
toolbar is hidden so that it does not cover the legend.
