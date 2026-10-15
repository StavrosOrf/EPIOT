# Data schema

EPIOT stores infrastructure, not demand. The database holds chargers, grid topology and the legacy
Amsterdam sessions; every scenario is generated on request from the bundled input files described
below. The database is SQLite with the SpatiaLite extension, managed by Alembic migrations.

```{figure} _static/figures/er-diagram.svg
:class: chart
:alt: Entity-relationship diagram of the EPIOT database
:target: _static/figures/er-diagram.svg

Entity-relationship diagram (click to enlarge). `PK` marks primary keys and `FK` foreign keys.
```

## Charging infrastructure

A **location** is a site with coordinates. A **column** is a station at a location, run by an
operator. A **charging point** is one connector, the unit that EPIOT simulates and reports on.

| Table | Rows in the snapshot | Key columns |
|---|---:|---|
| `operators` | 12,385 | `id`, `name` |
| `locations` | 241,497 | `id`, `street`, `locator_designator`, `supplement`, `postal_name`, `zip_code`, `state`, `country`, `latitude`, `longitude`, `geom` (`POINT`, SRID 4326), `source`, `external_id` |
| `columns` | 256,243 | `id`, `operator_id` → `operators`, `location_id` → `locations`, `net_capacity`, `comissioning_date`, `elaadnl_id`, `source`, `external_id` |
| `charging_points` | 593,964 | `id`, `column_id` → `columns`, `type`, `power` (kW), `source`, `external_id` |

- **Sources.** `source` is `ndw`, `bnetza`, `osm`, `bfe`, `irve` or `digitraffic`. It is empty for
  the Amsterdam pilot chargers, which the interface reports as `pilot`.
- **Stable IDs.** A record keeps its integer ID on every re-import, keyed by `(source,
  external_id)`. New IDs start at 1×10¹² (NDW), 2×10¹² (BNetzA), 3×10¹² (OSM), 4×10¹² (BFE),
  5×10¹² (IRVE) and 6×10¹² (Digitraffic), above pilot IDs and below JavaScript's safe-integer limit.
- **Power and type.** `power` is the rated connector power in kW and may be empty; simulators then
  use 11 kW. `type` is `fast` when any connector is DC and `regular` otherwise.
- **Countries.** `locations.country` is a country name; calendar effects and climate are looked up
  from it.

## Grid topology

| Table | Rows in the snapshot | Key columns |
|---|---:|---|
| `transformers` | 28,260 | `id`, `location_id` → `locations`, `type` (`Low`, `Middle` or `High`) |
| `grid_connections` | 717 | `id`, `transformer_id` → `transformers`, `column_id` → `columns` |

The data are the Liander assets of Amsterdam: `Low` are LV distribution cabinets, `Middle` the MV/LV
installations used by the map, and `High` substations. Each connection links a column to its
geographically nearest `Middle` transformer within 50 km, an approximation of the feeder topology,
which is not public.

## Sessions and grid mix

| Table | Rows in the snapshot | Key columns |
|---|---:|---|
| `sessions` | 318,163 | `id`, `cp_id` → `charging_points`, `start`, `end`, `consumption` (kWh) |
| `power_mixes` | 72 | `id`, `country_zone`, `datetime`, `renewable_percentage`, `co2_intensity`, `fossil_free_percentage`, `power_consumption_total` |

`sessions` holds the stored Amsterdam pilot sessions, with timezone-free local timestamps. It is
indexed on `(cp_id, start)` and `(cp_id, end)`, and read only by API calls without a
`session_source`. `power_mixes` is the legacy Dutch grid mix; the application merges it with the
observation store described below.

## Forecast tables

`forecast_runs` (`id`, `target_date`, `timezone`, `issued_at`, `model_version`), `forecast_hourly`
and `forecast_sessions` (both keyed by `run_id`, `cp_id` and a time or session index) persist CPFT
output. They are written by the offline CPFT analysis scripts only and are empty in the snapshot.
`gamma_distributions` is a legacy table of an earlier sampler and is unused.

## Indexes and migrations

| Index | Purpose |
|---|---|
| `ix_locations_latitude_longitude` | Bounding-box test before the exact polygon test |
| `ix_<table>_source_external_id` (unique) on `locations`, `columns`, `charging_points` | Idempotent re-import of one source |
| `ix_charging_points_column_id`, `ix_columns_location_id` | Joins from point to location |
| `ix_sessions_cp_id_start`, `ix_sessions_cp_id_end` | Day and range queries on stored sessions |

Migrations live in `migrations/` and are applied by `database_init.py`. On an existing database run
`uv run flask --app app db upgrade`.

## Files outside the database

| File | Content |
|---|---|
| `instance/grid_data.sqlite` | Hourly grid observations. Tables `grid_observations` and `grid_hourly` with `zone`, `timestamp` (UTC interval start), `payload` (JSON of carbon intensity, renewable share, estimation flags, source and basis) and `prepared_at` |
| `instance/chargers/manifest.json` | Download and import provenance per source, with per-city counts |
| `seed_data/<CC>.json.gz`, `shared.json.gz`, `manifest.json` | Offline snapshots, one per country, with SHA-256 checksums (format version 2) |
| `seed_data/distribution-of-*.csv` | The four session priors: arrival (`Arrival time`, `private`, `public`, `workplace`), weekend arrival, connection time and energy demand (`Percentage of charging events` and one column per site type) |
| `seed_data/wijkenbuurten_2022_v2_amsterdam.gpkg` | CBS neighbourhood atlas used by the Spatial source: `buurtcode`, `buurtnaam`, land area, housing stock, business counts and population density |
| `backend/data/calendar_effects.json` | Calibrated day-effect parameters |
| `backend/data/cpft_library.npz`, `cpft_preprocessing.json` | Prebuilt CPFT trajectories and the preprocessing they were built with |
| `backend/data/charger_position_overrides.json` | Verified manual position corrections |

A snapshot file is gzipped JSON of the form
`{"format_version", "country", "tables": {table: {"columns": [...], "rows": [...]}}}`. Geometry
columns are rebuilt on import, and the importer rejects a file whose checksum, columns or row counts
differ from the manifest.
