# Architecture

EPIOT is a single Flask application with a browser front end. The server is stateless apart from
two SQLite files and a few lock-protected in-process caches, and every result is a pure function of
the request.

```{figure} _static/figures/architecture.svg
:class: chart
:alt: Components of EPIOT: browser, Flask application, session sources, calculation, stored data, bundled inputs and external services
:target: _static/figures/architecture.svg

Components and the direction of calls (click to enlarge).
```

## Principles

| Principle | How it is met |
|---|---|
| **Computed on request** | There is no live feed, so scenarios, CPFT trajectories and grid values are produced when asked for and nothing is pre-generated |
| **Deterministic** | Random numbers are hashed from the point, source, seed and absolute time, never drawn from a stream, so a window is identical on its own and inside a longer range |
| **One engine for every source** | Stored and generated sessions take the same path through `day_profile`, so a strategy means the same thing everywhere |
| **Vectorised** | Sampling, scheduling and KPIs work on arrays over all selected points, which keeps a 1,000-point scenario in the tens of milliseconds |
| **Local time first** | Windows, KPI hours and holidays follow the scenario time zone, including 23- and 25-hour days |

## Request flow

A load profile for one area:

1. **Selection.** The browser posts the area polygon to `/stations/within?ids_only=1`. The server
   narrows by an indexed bounding box and then applies an exact `ST_Within` test.
2. **Request.** The browser posts the charger IDs, date, strategy, source, demand level and seed to
   `/stations/aggregate_load`, once per area with that area's own settings.
3. **Sessions.** `SessionSourceService` samples the world for the two days, or reads stored
   sessions, and returns a `SessionFrame` with provenance.
4. **Schedule.** `day_profile` applies the strategy, derives the headroom signals and builds the
   feasible envelope.
5. **Response.** JSON with the load, signals, envelope and `source` metadata. The browser keeps it
   per area and draws it with Plotly.

KPIs follow the same path through `/kpi/user`, with one continuous sampled window for the range.
The interface asks for `section=basic` first and requests the Environment section only when that
dashboard is opened.

## Backend

| Module | Role |
|---|---|
| `views.py`, `features.py`, `kpi/user.py`, `request_args.py` | Endpoints and request validation |
| `session_sources.py` | `SessionSourceService`: Simple, Spatial and CPFT, single days and ranges |
| `scenario_world.py`, `scenario_sampling.py`, `random_streams.py` | The synthetic world, priors and counter-based randomness |
| `spatial_profiles.py` | Neighbourhood atlas and the four spatial profiles |
| `scenario_calendar.py` | Season, holidays, demand shock and temperature |
| `cpft_library.py`, `cpft.py`, `cpft_runtime.py` | CPFT sampling from the prebuilt library; the runtime is used only to build it |
| `day_profile.py`, `scenario_profiles.py`, `carbon_charging.py` | Strategies, headroom and minimum carbon |
| `aggregators.py`, `api_calls/` | Cost optimisation through ReFlex and Energy-Charts |
| `flex_polytope.py` | Feasible envelope of the aggregate |
| `kpi/statistics.py`, `kpi/environment.py` | KPI statistics and the environmental comparison |
| `grid_data.py` | Hourly grid observations and the historical reference |
| `models.py`, `charger_sources.py`, `charger_import.py`, `charger_positions.py`, `bootstrap_data.py` | Schema ({doc}`data-schema`), registers, import, position repair, snapshots |
| `map_density.py`, `station_cache.py`, `analysis_versions.py` | Overview aggregation, charger caches, revision stamps |

## Frontend

The page is plain JavaScript modules on Leaflet, Plotly, SheetJS and flatpickr, loaded from CDNs.

| Module | Role |
|---|---|
| `script.js` | Map, drawing and page wiring |
| `areas.js`, `group_actions.js`, `area_settings.js` | Area cards, edits and per-area settings |
| `analysis.js`, `tabs.js`, `app_state.js` | The analysis run, tabs and the shared state |
| `data_fetch.js` | Requests with bounded caches, shared in-flight promises and revision checks |
| `plotter.js`, `environment_summary.js`, `calendar_note.js` | Charts, environment table and day-effect notes |
| `loaders.js`, `map_density.js`, `charger_sites.js`, `location_search.js` | Map data, overview bubbles, site markers and search |
| `utils.js`, `date_selection.js`, `panel_header.js`, `landing.js` | Excel export, dates, header behaviour and the welcome dialog |

## Caching and freshness

Only two layers cache, and both are bounded.

| Where | What | Invalidated by |
|---|---|---|
| Server | Charger lists per area, overview cells per zoom | Database, WAL, manifest or `ANALYSIS_DATA_REVISION` changing |
| Browser | Area selections, profiles and environment results (64 entries each); simultaneous identical requests share one promise | A change of the `/stations/analysis-version` revisions, checked on every analysis action; failed requests are not kept |
