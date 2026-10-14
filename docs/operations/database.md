# Building the database

The database is built once from open source datasets and then kept up to date by a scheduled job.
This page describes the one-off build; {doc}`scheduled-updates` covers the recurring part.

## Pipeline

```{mermaid}
flowchart TB
    subgraph Sources["./data"]
        direction LR
        J[Charging stations<br/>JSON]
        B[CBS neighbourhoods<br/>GPKG]
        G[Liander grid<br/>GPKG]
        D[Behaviour curves<br/>CSV]
    end
    M[flask db upgrade · create schema] --> L1
    J & B --> L1[load_ams_data<br/>locations · operators · columns · charging points]
    G & B --> L2[load_transformer_data<br/>transformers inside Amsterdam bounds]
    L1 & L2 --> L3[add_grid_connections<br/>nearest MV/LV transformer per column]
    L3 --> L4[load_daily_charging_sessions<br/>× N days, Monte Carlo]
    D --> L4
    L4 --> L5[load_electricity_data_…<br/>power mix]
    L5 --> DB[(instance/default.sqlite)]
```

All steps are functions in `backend/` and are called from `database_init.py`. On a fresh database,
uncomment the steps you need in its `__main__` block and run:

```bash
uv run flask --app app db upgrade
uv run python database_init.py
```

## Step 1 — Charging infrastructure

`load_ams_data(app, db)` reads `chargers_data_ams.json` (OpenChargeMap-style records) and, for each
station, merges:

| Source field | Target |
|---|---|
| `AddressInfo` | `Location` with street, town, postcode, coordinates and a `POINT` geometry |
| `AddressInfo` lon/lat → CBS polygons | `Location.supplement` = `buurtcode` of the containing neighbourhood |
| `OperatorInfo` | `Operator` (or ID 1, *(Unknown Operator)*) |
| Station `ID`, `OperatorsReference` | `Column`, with `elaadnl_id` parsed from `EVnetNL …` references |
| `Connections[]` | One `ChargingPoint` per connection: `power = PowerKW`, `type = fast` if `IsFastChargeCapable` |

Records are **merged** by primary key, so re-running the loader updates rather than duplicates.

## Step 2 — Grid assets

`load_transformer_data(app, db)` reads three layers from the Liander GeoPackage, reprojects them to
WGS 84 and keeps the features inside the bounding box of the Amsterdam neighbourhoods:

| Layer | Stored `type` |
|---|---|
| `laagspanningsverdeelkasten` | `Low` |
| `middenspanningsinstallaties` | `Middle` |
| `onderstations` | `High` |

Each transformer gets a `Location` with an ID from 30 000 upwards.

## Step 3 — Grid connections

`add_grid_connections(app, db, within_m=50_000, voltage_type="Middle")` links every column to its
nearest MV/LV transformer:

```{mermaid}
flowchart TB
    C[Columns with coordinates] --> H["Haversine distance to every<br/>Middle transformer<br/>(vectorised, batches of 2,000)"]
    T[Middle transformers] --> H
    H --> N[argmin per column]
    N --> F{distance ≤ 50 km?}
    F -- yes --> W[(grid_connections)]
    F -- no --> S[skip]
```

By default the table is cleared first (`reset_table=True`). Use `reset_grid_connections` to empty it
separately. The nearest-transformer rule is an approximation of the real feeder topology, which is not
public.

## Step 4 — Charging sessions

`load_daily_charging_sessions(app, db, date, method="MC", scope="NL")` generates one day of sessions
for every charging point inside the Netherlands bounding polygon and commits them. Loop over the
days you need:

```python
date = datetime.date(2025, 9, 1)
for _ in range(120):
    load_daily_charging_sessions(app, db, date=date, method="MC", scope="NL")
    date += datetime.timedelta(days=1)
```

The generator reads existing sessions so that a charger busy at midnight is not double-booked, but
it does not check sessions later in the day: generate each day **once**. To start over, call
`reset_charging_session_db(app, db)`. The method is described in
{doc}`../concepts/session-data`.

## Step 5 — Power mix

`load_electricity_data_for_supported_countries(app, db)` fetches the last 24 hours of power mix for
the supported zones (currently `NL`) and upserts them into `power_mixes`. It needs an Electricity Maps
API token (see {doc}`configuration`).

## Inspecting the database

The `charge_sessions` module includes diagnostics:

| Function | Shows |
|---|---|
| `charging_sessions_overview(app, db)` | Prints sessions for a sample charger and date |
| `plot_sessions_for_charger(app, db, charger_id)` | Matplotlib timeline of all sessions of one charger |

Any SQLite client works for ad-hoc queries; load `mod_spatialite` first to use spatial functions.
