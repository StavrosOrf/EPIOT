# Getting started

EPIOT is a Flask application on a SQLite/SpatiaLite database. One process serves the web interface
and the {doc}`REST endpoints <rest-api>`. No scheduled jobs, caches or machine-learning runtime
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

```{figure} _static/screenshots/anatomy-panel.jpg
:class: screenshot
:alt: The analysis panel with numbered callouts on each control

The analysis panel on the Load profiles tab, with one card per area.
```

| # | Control | Function |
|---|---|---|
| 1 | **Analysis** | Panel title; the dot beside it pulses while results are calculated |
| 2 | **Tabs** | Load profiles, Flexibility and KPIs; KPIs adds a row for the five dashboards |
| 3 | **Source** | Simple, Spatial or CPFT, for every area |
| 4 | **Export** | Downloads the workbook ({doc}`reports`) |
| 5 | **Close** | Hides the panel; {kbd}`Esc` or a click on the map does the same |
| 6 | **Card settings** | Strategy and date (or date range) and demand scenario of that area |
| 7 | **Card actions** | Move up, move down, duplicate and remove |

The map, its layers and the drawing tools are described in {doc}`map-and-areas`.

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

## Next steps

| To | Read |
|---|---|
| Find your way around the map and draw areas | {doc}`map-and-areas` |
| Choose how sessions are generated | {doc}`session-sources` |
| Understand the strategies and their effect on the load | {doc}`charging-strategies` |
| Configure, deploy and maintain an installation | {doc}`operations` |
| Script the application | {doc}`rest-api` |
