# Operations

EPIOT is one web process on one SQLite file. Nothing runs on a schedule: scenarios, CPFT
trajectories and grid values are computed when a request asks for them, so there are no cron jobs or
timers. The only stores that fill up are the ReFlex plans and day-ahead prices of the cost
strategies, which can also be prepared in advance.

## Configuration

Flask settings are read from `FLASK_`-prefixed environment variables (values are parsed as JSON
where possible).

| Name | Default | Purpose |
|---|---|---|
| `SPATIALITE_LIBRARY_PATH` | platform default | Path of the SpatiaLite extension |
| `FLASK_SQLALCHEMY_ENGINES` | `sqlite:///default.sqlite` | Database location |
| `FLASK_SESSION_SCENARIO_TIMEZONE` | `Europe/Amsterdam` | Time zone of all local days, windows and KPI hours |
| `FLASK_SESSION_DAILY_ARRIVALS` | `2` | Attempted arrivals per point and day at base demand |
| `FLASK_SESSION_CALENDAR_EFFECTS` | `true` | `false` disables season, holiday, shock and weather effects |
| `FLASK_SESSION_SCENARIO_ATLAS` | bundled Amsterdam atlas | Neighbourhood atlas for the spatial source |
| `FLASK_GRID_DATA_CACHE` | `instance/grid_data.sqlite` | Grid carbon and renewable observations |
| `FLASK_GRID_ALLOW_STALE` | `true` | `false` disables the historical reference for missing grid hours |
| `FLASK_ANALYSIS_DATA_REVISION` | – | Bump after data changes in a database that is not a file |
| `FLASK_MAX_POINT_DAYS` | `1000000` | Largest charging points × days a load-profile or KPI request may cover (about 25 s); `0` disables the limit |
| `FLASK_MAX_ENSEMBLE` | `30` | Most seeded draws one load-profile request may combine into a band |
| `REFLEX_BASE_URL` | `https://drive2x-reflex.hesi.energy/services` | ReFlex service for *Min. Charging Cost* and *Min. Cost with V2G* |
| `FLASK_REFLEX_PLAN_STORE` | `instance/reflex_plans.sqlite` | Optimised plans, keyed by their inputs ({doc}`charging-strategies`) |
| `FLASK_DAY_AHEAD_PRICE_STORE` | `instance/day_ahead_prices.sqlite` | Day-ahead prices fetched from Energy-Charts |
| `FLASK_REFLEX_V2G_DEPTH_KWH` | `10` | How far below its arrival charge a V2G vehicle may be discharged |
| `FLASK_REFLEX_BACKGROUND_TIMEOUT` | `1800` | Seconds the background queue waits for one batch of ReFlex runs; finished runs are kept |
| `FLASK_REFLEX_BATCH_SESSIONS`, `FLASK_REFLEX_V2G_BATCH_SESSIONS` | `300`, `10` | Connections per ReFlex run, one-way and V2G |
| `FLASK_REFLEX_PARALLEL_RUNS` | `4` | ReFlex runs at once; the instance is shared with WP10 and runs only a few at a time |
| `EPIOT_DEBUG` | `1` for `python app.py`, `0` under a WSGI server | Werkzeug debugger and reloader; `0` also enables `ProxyFix` |

## Deployment

A WSGI server that imports `app:app` runs in production mode: no Werkzeug debugger, and `ProxyFix`
enabled. Run the application behind a TLS-terminating reverse proxy that forwards
`X-Forwarded-Proto`, `X-Forwarded-Host` and, for a sub-path, `X-Forwarded-Prefix`.
`python app.py` is the development server and starts with debug on; `EPIOT_DEBUG=0` turns that off
and `EPIOT_DEBUG=1` turns it on under a WSGI server.

```bash
gunicorn -w 4 --threads 4 --timeout 300 -b 127.0.0.1:5000 app:app
```

Requests never wait on the ReFlex service: each worker process optimises new connections through
ReFlex in a background thread (see {doc}`charging-strategies`). The in-process caches are lock-protected.

- **Health check.** `GET /healthz` answers `{"status": "ok"}` when the database responds and
  SpatiaLite is loaded, and `503` otherwise; use it for the proxy's health check.
- **Request size.** The browser sends area selections with `POST`. Scripts that pass thousands of IDs
  in a `GET` query string need `--limit-request-line 18190` or higher.
- **Database.** The database is the single file `instance/default.sqlite`; back it up with the
  application stopped. After updating, run `uv run flask --app app db upgrade`.
- **Outbound access.** Map tiles and location search need public HTTPS. The cost strategies need
  ReFlex and Energy-Charts for plans and prices that are not stored yet.

## Maintenance tasks

These run when their inputs change, not on a calendar.

| When | Command | Effect |
|---|---|---|
| The CPFT checkpoints, preprocessing, session priors, sampler version or time zone change | `uv run --extra cpft python scripts/build_cpft_library.py` | Rebuilds `backend/data/cpft_library.npz` (about 100 minutes on 16 cores). Until then CPFT requests return `503`. |
| Better demand or weather data for the day effects | `uv run python scripts/calibrate_calendar_effects.py` | Re-estimates `backend/data/calendar_effects.json` and writes a calibration report |
| A new hourly grid dataset is available | `uv run python scripts/prepare_grid_data.py --csv FILE` | Imports observations; the next request uses them ({ref}`kpis:grid data`) |
| The charger registers publish | `uv run python scripts/update_charger_data.py` | Downloads and imports every source (monthly for BNetzA) |
| After a charger refresh | `uv run python scripts/export_country_data.py` | Regenerates the `seed_data/` snapshots |
| An area and dates will be analysed with *Min. Charging Cost* or *Min. Cost with V2G* | `uv run python scripts/prepare_reflex_plans.py --bbox W,S,E,N --from DATE --to DATE` | Waits for ReFlex to optimise the connections of those chargers and dates into the plan store, so requests show ReFlex's plans from the start. Run again after new day-ahead prices; only what is missing or provisional is optimised. |
| Positions need repair in an existing database | `uv run python scripts/repair_charger_positions.py` | Applies the repairs after taking a backup |

Check an installation:

```bash
# Imported grid observations
sqlite3 instance/grid_data.sqlite "SELECT count(*), min(timestamp), max(timestamp) FROM grid_observations;"

# The CPFT library matches the current inputs (prints its build time)
uv run python -c "from backend.cpft_library import get_library; l = get_library(); l.check('Europe/Amsterdam'); print(l.meta['built_at'])"
```

## Tests

```bash
uv run pytest                 # Python tests
node --test tests/*.mjs       # JavaScript tests
```

The CPFT checkpoint tests are skipped unless the `cpft` extra is installed. The CI workflow
(`.github/workflows/ci.yml`) runs both suites on every push and pull request.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `No such module: mod_spatialite` | SpatiaLite not found. Install it or set `SPATIALITE_LIBRARY_PATH`. |
| `uv sync` fails with `os error 396` or `32` | OneDrive file locks. Move `.venv` outside the synced folder ({doc}`getting-started`). |
| No chargers on the map, or the drawing tools are disabled | Zoom to level 12 or higher, and keep the **Chargers** layer on. |
| CPFT returns `503` | The CPFT library is missing or stale. See {ref}`session-sources:rebuild the cpft library`. |
| A cost strategy returns `503` | No day-ahead prices: Energy-Charts is unreachable or rate limiting; retry after a minute. |
| A cost strategy keeps reporting connections pending for ReFlex | ReFlex is unreachable (it is reachable only from the DRIVE2X network) or busy; the log names the failure. The exact local optimum is shown meanwhile. |
| *Min. Carbon Footprint* returns `422` | No carbon data for the window and no usable reference, or a point has overlapping connections. See {ref}`kpis:grid data`. |
| `422` with a point-days message | The selection and range exceed `FLASK_MAX_POINT_DAYS`. Select fewer chargers or a shorter range. |
| Environment KPIs show a historical reference | No observations for those dates. Import grid data or accept the labelled reference. |
| Icons missing behind a proxy | Run in production mode and forward `X-Forwarded-Proto`, `X-Forwarded-Host` and `X-Forwarded-Prefix`. |
