# External services

EPIOT relies on five external services. Two are called from the browser for every user; three are
called from the backend, either per request (`ocost` only) or from batch jobs.

```{mermaid}
flowchart LR
    subgraph Browser
      M[Map]
      S[Search box]
    end
    subgraph Backend
      AGG[aggregators.py<br/>ocost]
    end
    M -->|tiles| OSM[(OpenStreetMap<br/>tile.openstreetmap.org)]
    S -->|geocode| NOM[(Nominatim<br/>nominatim.openstreetmap.org)]
    AGG -->|day-ahead prices| EC[(Energy-Charts<br/>api.energy-charts.info)]
    AGG -->|optimise schedules| RF[(ReFlex<br/>drive2x-reflex.hesi.energy)]
```

| Service | Used for | Called by | When | Auth |
|---|---|---|---|---|
| **OpenStreetMap tiles** | Base map | Browser | Every map view | None (tile usage policy applies) |
| **Nominatim** | Location search | Browser | On search | None (usage policy: max 1 req/s) |
| **Energy-Charts** (Fraunhofer ISE) | NL day-ahead prices for `ocost` | `backend/api_calls/prices.py` | `ocost` requests | None |
| **ReFlex** (HESI) | Cost-optimal EV schedules | `backend/aggregators.py` | `ocost` requests | Project network |
| **Electricity Maps** | Hourly power breakdown and carbon intensity | `backend/api_calls/env_data_api.py` | Not called: EPIOT uses no live data | API token |

## Energy-Charts — day-ahead prices

```text
GET https://api.energy-charts.info/price?bzn=NL&start=2025-10-14T00:00Z&end=2025-10-15T23:59Z
```

`retrieve_day_ahead_prices(date, days_ahead=2, country_code="NL")` converts the response to a pandas
series in EUR/MWh, forward-fills it to 288 ten-minute steps starting at the first full hour, and
returns a NumPy array.

## ReFlex — optimisation

`simulate_cost_optimal_operation` submits a `singleRunConfig` to
`/services/run/single`, polls `/services/run/info/{id}` once per second until `runStatus` is
`completed`, then reads `/services/run/results/{id}`. Each entry in `devicePlans` is the energy plan of
one charging point in joules per step. See {doc}`../concepts/charging-strategies` and
{doc}`../related-tools/reflex`.

## Electricity Maps — power mix

`load_electricity_data_for_country(app, db, country_zone="NL")` calls four endpoints of the v3 API:

| Endpoint | Content |
|---|---|
| `/power-breakdown/latest`, `/power-breakdown/history` | Consumption breakdown by source, total consumption, fossil-free share |
| `/carbon-intensity/latest`, `/carbon-intensity/history` | Life-cycle carbon intensity (gCO₂eq/kWh) |

For each hour of history it computes the renewable share as
$(\text{wind} + \text{solar} + \text{hydro} + \text{biomass} + \text{geothermal}) / \text{total}$ and
upserts one `PowerMix` row per country and timestamp, removing duplicates. The history endpoint returns
the last 24 hours. No job calls it any more: EPIOT uses no live data, and
existing `power_mixes` rows serve as grid observations (see
{doc}`../operations/scheduled-updates`).

The API token is read from the `ELECTRICITYMAPS_API_TOKEN` environment variable.

## Availability and failure modes

| Service unavailable | Effect in EPIOT |
|---|---|
| OpenStreetMap tiles | Map background stays grey; markers and analysis still work |
| Nominatim | Status bar: *Location search is unavailable right now* |
| Energy-Charts or ReFlex | `ocost` fails; the chart shows *Load profiles are not available for this selection*. Other strategies are unaffected |
| Electricity Maps | No new power-mix rows; environment KPIs only cover dates already stored |
