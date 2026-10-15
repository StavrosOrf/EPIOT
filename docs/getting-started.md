# Getting started

EPIOT is a Flask application on a SQLite/SpatiaLite database. One process serves the web interface
and the [REST endpoints](#rest-endpoints). No scheduled jobs, caches or machine-learning runtime
are needed.

## Requirements

| Component | Requirement |
|---|---|
| Python | 3.11 – 3.13 |
| [uv](https://docs.astral.sh/uv/) | Creates the environment from `uv.lock` |
| SpatiaLite | The `mod_spatialite` SQLite extension |
| Browser | A current Chrome, Edge, Firefox or Safari. The page loads Leaflet, Plotly and SheetJS from public CDNs. |
| Network | Outbound HTTPS for map tiles and location search (PDOK, Photon). ReFlex and Energy-Charts are needed only for *Min. Charging Cost*. |

## Install and run

```bash
uv sync
uv run python scripts/install_spatialite.py   # Windows only
uv run python database_init.py
uv run python app.py
```

Open <http://127.0.0.1:5000>.

- **SpatiaLite on Linux or macOS:** `sudo apt-get install libsqlite3-mod-spatialite` or
  `brew install libspatialite`. Set `SPATIALITE_LIBRARY_PATH` to use a different copy.
- **Database:** `database_init.py` builds `instance/default.sqlite` offline from the snapshots in
  `seed_data/`. It applies the migrations itself, so do not run `flask db upgrade` first. Use
  `--countries NL DE FR` to load a subset.
- **OneDrive:** OneDrive locks files while it syncs and breaks `uv sync` (`os error 396`).
  `pyproject.toml` already copies instead of hard-linking; also keep the virtual environment outside
  the synced folder and link it in:

  ```bat
  mklink /J .venv %USERPROFILE%\.venvs\EPIOT_v2
  ```

## Run an analysis

```{figure} _static/screenshots/areas-drawn.jpg
:class: screenshot
:alt: The EPIOT map with three analysis areas drawn over central Amsterdam

Three areas drawn over central Amsterdam, ready to analyse.
```

1. **Find the place.** Search for a location, or zoom to city level (zoom 12 or higher). Below that
   the map shows aggregate bubbles and areas cannot be drawn.
2. **Draw up to three areas** with the polygon or rectangle tool. The trash tool removes areas.
3. **Press Analyse** (or {kbd}`Enter`). The analysis panel opens.
4. **Choose a session source** in the panel header: *Simple*, *Spatial* or *CPFT*
   ({doc}`session-sources`). It applies to all areas.
5. **Set each area's controls** on its card. Changing one recalculates that area only.
6. **Switch tabs:** {doc}`load-profiles`, {doc}`flexibility`, {doc}`kpis`.
7. **Export** the results with the download icon (`DRIVE2X_EPIOT_report.xlsx`).

| Control | Tabs | Options |
|---|---|---|
| Charging strategy | Load profiles, Flexibility | As Fast As Possible (default), As Late As Possible, Average Power, Min. Carbon Footprint, Min. Charging Cost |
| Target date | Load profiles, Flexibility | Any date, past or future. The chart shows that day and the day before. |
| Date range | KPIs | Up to 366 days, inclusive. Defaults to the last seven days. |
| Demand scenario | All | Low, Base (default) or High demand |

Each card also renames the area (pencil), moves it up or down, duplicates it or removes it.
Duplicating is the quickest way to compare two strategies or dates on the same area.
{kbd}`Esc` closes the panel and cancels the active drawing tool.

The map has two layers: **Chargers** and **Transformers** (the medium-/low-voltage transformers
of the Liander grid, Amsterdam only). Clicking a charger shows its power, operator and data source.

## Data coverage

Charging points come from open registers and share one data model with the Amsterdam pilot data.

| Source | Coverage | Licence |
|---|---|---|
| NDW DOT-NL | Netherlands | Open data (NDW terms) |
| Bundesnetzagentur Ladesäulenregister | Germany | Open data (BNetzA terms) |
| Base nationale des IRVE | France, including overseas | Licence Ouverte 2.0 |
| ich-tanke-strom.ch (BFE) | Switzerland, Liechtenstein | Open use, credit the source |
| Digitraffic AFIR (Fintraffic) | Finland | CC BY 4.0 |
| OpenStreetMap | Lisbon, Porto, Milan, Rome, Turin, London, Manchester | ODbL 1.0 |
| Amsterdam pilot | Amsterdam | Open Charge Map export; stored sessions and grid links |

About 590,000 charging points are loaded in total. Notes:

- **Sessions are synthetic everywhere.** Only the Amsterdam pilot chargers have stored sessions,
  and only API calls without a `session_source` read them.
- **Transformers and the spatial atlas cover Amsterdam only.** Elsewhere the spatial source uses
  its generic profile ({doc}`session-sources`).
- **OpenStreetMap undercounts.** Treat United Kingdom and Italian counts as lower bounds.
- **Positions are repaired on import.** Swapped coordinates, wrong countries, placeholders and
  points at sea are corrected or dropped using offline checks and national geocoders. Verified
  manual corrections are in `backend/data/charger_position_overrides.json`.

Refresh the snapshots after a supplier update:

```bash
uv run flask --app app db upgrade              # once
uv run python scripts/update_charger_data.py   # download and import every source
uv run python scripts/export_country_data.py   # regenerate seed_data/
```

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
| `REFLEX_BASE_URL` | `https://drive2x-reflex.hesi.energy/services` | ReFlex service for *Min. Charging Cost* |
| `FLASK_MAX_POINT_DAYS` | `1000000` | Largest charging points × days a load-profile or KPI request may cover (about 25 s); `0` disables the limit |
| `FLASK_MAX_ENSEMBLE` | `30` | Most seeded draws one load-profile request may combine into a band |
| `EPIOT_DEBUG` | `1` for `python app.py`, `0` under a WSGI server | Werkzeug debugger and reloader; `0` also enables `ProxyFix` |

## Deployment

A WSGI server that imports `app:app` runs in production mode: no Werkzeug debugger, and `ProxyFix`
enabled. Run the application behind a TLS-terminating reverse proxy that forwards
`X-Forwarded-Proto`, `X-Forwarded-Host` and, for a sub-path, `X-Forwarded-Prefix`. (`python app.py`
is the development server and starts with debug on; `EPIOT_DEBUG=0` turns that off and
`EPIOT_DEBUG=1` turns it on under a WSGI server.)

```bash
gunicorn -w 4 --threads 4 --timeout 300 -b 127.0.0.1:5000 app:app
```

Threads keep a worker responsive while another request waits on the ReFlex service
(*Min. Charging Cost* polls it for up to two minutes). The in-process caches are lock-protected.

The browser sends area selections with `POST`. Scripts that pass thousands of IDs in a `GET` query
string need `--limit-request-line 18190` or higher. `GET /healthz` answers `{"status": "ok"}` when
the database responds and SpatiaLite is loaded, and `503` otherwise: use it for the proxy's health
check. The database is a single file (`instance/default.sqlite`); back it up with the application
stopped, and run `uv run flask --app app db upgrade` after updating (recent versions index the
`sessions` table, which makes stored-session day and KPI queries much faster).

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `No such module: mod_spatialite` | SpatiaLite not found. Install it or set `SPATIALITE_LIBRARY_PATH`. |
| `uv sync` fails with `os error 396` or `32` | OneDrive file locks. Move `.venv` outside the synced folder (see above). |
| No chargers on the map, or the drawing tools are disabled | Zoom to level 12 or higher, and keep the **Chargers** layer on. |
| CPFT returns `503` | The CPFT library is missing or stale. See {ref}`session-sources:rebuild the cpft library`. |
| *Min. Charging Cost* fails | ReFlex is reachable only from the DRIVE2X network, and the strategy supports ordinary 48-hour windows only (not daylight-saving changes). |
| *Min. Carbon Footprint* returns `422` | No carbon data for the window and no usable reference, or a point has overlapping connections. See {ref}`kpis:grid data`. |

## REST endpoints

The web interface uses only these endpoints, so everything it does can be scripted.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/stations/within` | Charging points inside a GeoJSON `Polygon` or `MultiPolygon`. `?ids_only=1` returns `{"ids": [...]}`. |
| `GET` | `/stations/all` | Every charging point; `?source=` filters by data source (`pilot`, `ndw`, `bnetza`, `osm`, `bfe`, `irve`, `digitraffic`). |
| `GET` | `/stations/density` | Aggregated cells for overview zooms (`zoom` 3–11, optional `bbox=west,south,east,north`). |
| `GET` | `/stations/coverage` | Searchable cities with charger counts, and the data sources with licences. |
| `POST` | `/features/transformers/within` | Transformers inside a polygon; optional `tr_type` (`Middle` is the MV/LV level). |
| `POST` | `/stations/charging-points-by-transformers` | Charging points behind `{"transformer_ids": [...]}`. |
| `GET` `POST` | `/stations/aggregate_load` | Load and flexibility profile ({doc}`load-profiles`, {doc}`flexibility`). |
| `GET` `POST` | `/kpi/user` | KPI dashboards ({doc}`kpis`). |
| `GET` | `/stations/analysis-version` | Opaque revisions of the infrastructure and calculation inputs. |

Conventions: JSON bodies; GeoJSON in WGS 84 as `[longitude, latitude]`; dates as `YYYY-MM-DD`;
power in kW and energy in kWh; no authentication. Invalid input returns `400` with
`{"error": "..."}`; an unavailable schedule `422`; an unavailable session source `503`.

```bash
curl -X POST "http://127.0.0.1:5000/stations/within?ids_only=1" \
  -H "Content-Type: application/json" \
  -d '{"type":"Polygon","coordinates":[[[4.89,52.36],[4.91,52.36],[4.91,52.375],[4.89,52.375],[4.89,52.36]]]}'
```
