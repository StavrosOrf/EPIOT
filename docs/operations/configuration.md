# Configuration

EPIOT has few settings. They live in environment variables, two constants in Python files, and one
YAML file.

## Environment variables

| Variable | Default | Used by | Purpose |
|---|---|---|---|
| `SPATIALITE_LIBRARY_PATH` | `mod_spatialite` (Windows), `mod_spatialite.so` (Linux), `mod_spatialite.dylib` (macOS) | `backend/spatialite.py`, GeoAlchemy2 | Name or path of the SpatiaLite extension. An existing value always wins. |
| `ELECTRICITYMAPS_API_TOKEN` | – | `backend/api_calls/env_data_api.py` | API token for the power-mix import. |
| `FLASK_*` | – | `app.config.from_prefixed_env()` | Any Flask setting, e.g. `FLASK_SQLALCHEMY_ENGINES='{"default": "sqlite:////data/epiot.sqlite"}'` to move the database. Values are parsed as JSON when possible. |

## Constants in code

| Constant | File | Default | Effect |
|---|---|---|---|
| `DEBUG` | `app.py` | `True` | Debug server vs. production mode with `ProxyFix` (see {doc}`deployment`) |
| `starting_date` | `static/scripts/script.js` | `2025-09-01` | Earliest selectable date in the date pickers; the default start of the KPI range |
| `NL_BOUNDARIES` | `backend/charge_sessions.py` | Polygon around the Netherlands | Spatial scope for session generation |
| `SEEN_KEY` | `static/scripts/landing.js` | `epiotr_intro_seen` | `localStorage` key for *Don't show again* |

## `backend/config.yaml`

Loaded at start-up into `app.config["aggregator_config"]` and read directly by the gamma session
sampler. Both sections are derived from ElaadNL historical data.

```yaml
# Probability of k sessions per charger per day (k = 1 … 15)
session_probabilities:
    1: 0.5717016003696391
    2: 0.2651671077134176
    3: 0.10165777572422677
    # …

# Gamma distribution of energy demand (kWh) by day type and arrival hour
charging_demand_distributions:
    weekday_0_hour_0:        # weekday_0 = Monday–Friday, weekday_1 = weekend
        distribution: gamma
        shape: 2.156022273433067
        loc: 0
        scale: 16.303558173116322
    # … one entry per day type × hour (48 in total)
```

The mean energy demand of an entry is $\text{shape}\times\text{scale}$; for `weekday_0_hour_0` that is
about 35 kWh. See {doc}`../concepts/session-data` for a plot of all entries.

## Map and data scope

| Setting | Where | Value |
|---|---|---|
| Initial centre and zoom | `script.js` | 52.3676 N, 4.9041 E, zoom 16 |
| Zoom range | `script.js` | 14–16 |
| Maximum number of areas | `script.js` | 3 |
| Area colours | `script.js` | `#4CAF50`, `#8A0606`, `#3357FF` |
| Transformer level shown and analysed | `script.js`, `loaders.js`, `data_fetch.js` | `Middle` |
| Grid-connection voltage level and radius | `add_grid_connections` | `Middle`, 50 km |
