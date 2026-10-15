# Reports and export

EPIOT exports the numbers behind the charts as an Excel workbook, and each chart as an image.

## Excel workbook

The **download** icon in the panel header writes `DRIVE2X_EPIOT_report.xlsx`. The browser builds the
workbook from the results already on screen with [SheetJS](https://sheetjs.com/), so a load profile
or flexibility export needs no server request. The KPI export first fetches the Environment
dashboard if it has not been opened.

```{figure} _static/figures/report-workbook.svg
:class: chart
:alt: The sheets of the workbook and their columns

The sheets of the workbook. Which sheets exist depends on the tab the export is made from.
```

| Exported from | Sheets |
|---|---|
| **Load profiles** or **Flexibility** | `Load Data`, `Charger IDs` |
| **KPIs** | `Charger IDs`, and one `<Area>_KPIs` sheet per area |

Export from the tab whose results you need; switching tabs recalculates the view and replaces the
results held for export. Sheet names are cut to 31 characters and made unique.

### Load Data

One row per area and 10-minute step (288 rows per area, 276 or 300 across a daylight-saving change).

| Column | Content |
|---|---|
| `Area Name` | Area label |
| `Timestamp (UTC)` | Start of the step, `YYYY-MM-DD HH:mm:ss` |
| `EV Load (kW)` | Aggregated power; divide by six for the energy of a step in kWh |
| `Upward Flexibility (kW)`, `Downward Flexibility (kW)` | Headroom signals ({doc}`flexibility`) |
| `Session source`, `Demand assumption`, `Synthetic` | Scenario provenance ({doc}`session-sources`) |
| `Charging strategy` | Strategy of the area card ({doc}`charging-strategies`) |
| `EV Load 10th percentile (kW)`, `EV Load 90th percentile (kW)` | Only when several draws were requested |

### Charger IDs

One row per charging point and area: `Area Name` and `Charger IDs`.

### `<Area>_KPIs`

The sheet starts with the provenance (session source, demand assumption, synthetic flag, inclusive
start and end date, time zone) and, when the Environment section is present, its method note and a
table with one row per strategy:

`Strategy`, `Energy (kWh)`, `Covered emissions (kgCO2e)`, `Mean intensity (gCO2e/kWh)`,
`Renewable share (%)`, `Carbon energy coverage (%)`, `Renewable energy coverage (%)`,
`Matching-date carbon coverage (%)`, `Estimated carbon energy (%)`, `Status`,
`Footprint difference vs AFAP (kgCO2e)`.

Then one row per series, with the name in the first cell and the values after it:

| Row | Values |
|---|---|
| `arrival_dist_wd`, `arrival_dist_we`, `departure_dist_*`, `duration_dist_*`, `slack_dist_*` | 24 counts |
| `consumption_dist_*`, `daily_consumption_dist_*` | 10 counts (0 – 100 kWh and 0 – 200 kWh) |
| `hour_of_arrival_consumption_*` | 24 mean energies (kWh); empty for hours without arrivals |
| `load_profile_*` | 48 mean powers (kW), one per half-hour |
| `load_duration_kw` | 21 values, exceeded 0, 5, … 100 % of the time |
| `occupation_ratio_dist` | 20 bins of the share of chargers |
| `sessions_per_day_0` … `sessions_per_day_6`, `_mean`, `_p90`, `_observations` | By weekday, Monday = 0 |
| `weekday_availability`, `weekend_availability`, `weekday_blocking`, `weekend_blocking` | 48 half-hour values |

After the series come a table with one row per charger (`Charger`, occupancy, utilisation,
sessions, energy; up to 200 chargers) and the headline figures: sessions, median and 90th
percentile stay, mean arrival hour, idle share, peak load and its time, load factor, coincidence
factor, idle charger-day share, sessions per used charger-day, median gap, mean utilisation and the
highest all-busy probability. The definitions are in {doc}`kpis`.

## Chart images

Every chart has a Plotly toolbar that appears on hover. The camera icon saves the chart as
`epiot_chart.png` at twice the screen resolution; the other buttons zoom, pan and reset the axes.
On narrow screens the toolbar is hidden so that it does not cover the legend.
