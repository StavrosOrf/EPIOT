# Building the database

The database is initialized once, offline, from the compact country snapshots in `seed_data/`.
It holds infrastructure, not demand: session scenarios are generated per request, so no recurring
job writes to it ({doc}`scheduled-updates`).

## Initialization

```{mermaid}
flowchart TB
    subgraph Seed["./seed_data"]
        direction LR
        S[Country snapshots<br/>*.json.gz]
        D[Behaviour curves<br/>CSV]
        B[CBS neighbourhoods<br/>GPKG]
    end
    S --> I[database_init.py<br/>migrations · tables · SpatiaLite geometry]
    I --> DB[(instance/default.sqlite)]
    D & B -. read directly at runtime .-> APP[Session samplers]
```

```bash
uv run python database_init.py
```

The initializer applies all migrations itself and restores charging stations, operators, Amsterdam
sessions, transformers, grid connections and power mixes with their original IDs. It refuses to
overwrite an existing database. The behaviour-curve CSVs and the neighbourhood atlas are not copied:
the app reads them from `seed_data/`. Coverage, the snapshot format and how to refresh it are in
`seed_data/README.md`; supplier refreshes are described in `docs/charger_sources.md`.

The functions below regenerate derived tables on an existing database.

## Grid connections

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

## Charging sessions

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

## Power mix

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
