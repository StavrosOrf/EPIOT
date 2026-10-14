# Backend

The backend is a Flask application assembled in `app.py` from three blueprints and a set of
plain-Python modules. It is stateless: every request reads from the database and returns JSON.

## Application setup

```{mermaid}
flowchart TD
    A[configure_spatialite] --> B[Flask app<br/>static_url_path = '']
    B --> C["SQLALCHEMY_ENGINES = sqlite:///default.sqlite<br/>+ FLASK_* environment overrides"]
    C --> D[SQLAlchemy init_app]
    D --> E["Load backend/config.yaml<br/>into app.config aggregator_config"]
    E --> F[Register blueprints<br/>/stations · /features · /kpi]
    F --> G[connect event → load_spatialite]
    G --> H[Alembic init_app]
    H --> I{DEBUG?}
    I -- yes --> J[app.run debug=True]
    I -- no --> K[ProxyFix + app.run 0.0.0.0:5000]
```

The database handle is shared with blueprints through `app.config["station_data.db"]`; the
`station_data` blueprint refuses to register without it.

## Modules

| Module | Responsibility |
|---|---|
| `app.py` | App factory code, index page, favicon, `/marker_icon`, blueprint registration |
| `backend/views.py` | Blueprint `station_data` (`/stations`): stations within a polygon, all stations, aggregate load, chargers behind transformers |
| `backend/features.py` | Blueprint `features_data` (`/features`): transformers within a polygon |
| `backend/kpi/user.py` | Blueprint `kpi` (`/kpi`): KPI computation over a date range |
| `backend/aggregators.py` | Charging-strategy simulators (`afap`, `alap`, `avg`, `ocost`) and timestamp sampling helpers |
| `backend/models.py` | SQLAlchemy models (see {doc}`data-model`) |
| `backend/utils.py` | GeoJSON serialisers and the charger-availability helper used by KPIs |
| `backend/bootstrap_data.py` | Exports and restores the `seed_data/` country snapshots (`database_init.py`) |
| `backend/loaders.py` | Grid-connection helper: nearest MV/LV transformer per column |
| `backend/charge_sessions.py` | Session generators (Monte Carlo, gamma, ML placeholder) and plotting helpers |
| `backend/api_calls/prices.py` | Day-ahead prices from Energy-Charts |
| `backend/api_calls/reflex.py` | Builds the ReFlex optimisation query |
| `backend/api_calls/env_data_api.py` | Power-mix import from Electricity Maps |
| `backend/spatialite.py` | Locates the `mod_spatialite` library per platform |
| `backend/ml/` | LSTM scaffolding for session prediction (optional `ml` extra) |
| `backend/config.yaml` | Session-count probabilities and gamma energy-demand parameters |

## Module dependencies

```{mermaid}
flowchart LR
    app[app.py] --> views[views.py]
    app --> features[features.py]
    app --> kpi[kpi/user.py]
    app --> models[models.py]
    app --> spl[spatialite.py]
    views --> agg[aggregators.py]
    views --> utils[utils.py]
    kpi --> agg
    kpi --> utils
    kpi --> views
    features --> utils
    agg --> prices[api_calls/prices.py]
    agg --> reflex[api_calls/reflex.py]
    init[database_init.py] --> boot[bootstrap_data.py]
    views --> src[session_sources.py]
    kpi --> src
    src --> world[scenario_world.py]
    src --> lib[cpft_library.py]
    world & lib --> frame[session_frame.py]
    views & features & kpi & boot --> models
```

## Endpoint handlers

| Route | Handler | Notes |
|---|---|---|
| `GET /` | `index` | Renders `templates/index.html` |
| `GET /marker_icon` | `get_marker_icon` | Absolute URLs of map icons and logos |
| `GET /favicon.ico` | `favicon` | |
| `POST /stations/within` | `get_stations_within` | Body: GeoJSON geometry |
| `GET /stations/all` | `get_all_stations` | Every charging point; optional `source` filter |
| `GET /stations/density` | `get_density` | Grid aggregates for overview zooms, cached per zoom |
| `GET /stations/coverage` | `get_coverage` | Search cities and open-data sources, from `instance/chargers/manifest.json` |
| `GET /stations/aggregate_load` | `get_aggregate_load` | Load and flexibility for one area |
| `POST /stations/charging-points-by-transformers` | `charging_points_by_transformers` | Grid view expansion |
| `POST /features/transformers/within` | `get_transformers_wtithin` | Optional `tr_type` filter |
| `GET /kpi/user` | `get_user_kpi` | All KPI dashboards |

Full request and response schemas are in {doc}`../api/rest-api`.

## Aggregate-load pipeline

```{mermaid}
flowchart TD
    R["GET /stations/aggregate_load"] --> P{selected_markers}
    P -- "'undefined' or empty" --> Z[Return 144 zeros]
    P -- IDs --> Q1[Query rated power per ID]
    Q1 --> Q2["Query sessions: start on D OR end on D-1"]
    Q2 --> S{strategy}
    S -- afap --> A[simulate_uncontrolled_…]
    S -- alap --> B[simulate_delayed_…]
    S -- avg --> C[simulate_avg_charging_…]
    S -- ocost --> O[simulate_cost_optimal_operation]
    A & B & C & O --> J["JSON {x: 0…287, y, up_flex, down_flex}"]
```

## Configuration file

`backend/config.yaml` is loaded once at start-up into `app.config["aggregator_config"]`. It holds:

- `session_probabilities`: probability of 1–15 sessions per charger per day.
- `charging_demand_distributions`: gamma parameters (`shape`, `loc`, `scale`) for each day type
  (`weekday_0` = weekday, `weekday_1` = weekend) and arrival hour.

See {doc}`../operations/configuration`.
