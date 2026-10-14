# Installation

This page sets up a local development copy of EPIOT: the Python environment, the SpatiaLite
extension, the database, and the web server.

```{mermaid}
flowchart TB
    A[Clone repository] --> B[uv sync]
    B --> C[Install SpatiaLite]
    C --> F[python database_init.py]
    F --> G[python app.py]
    G --> H((http://127.0.0.1:5000))
```

## Requirements

| Component | Version | Notes |
|---|---|---|
| Python | 3.11 – 3.13 | Pinned in `.python-version` and `pyproject.toml` |
| [uv](https://docs.astral.sh/uv/) | recent | Manages the virtual environment from `uv.lock` |
| SpatiaLite | `mod_spatialite` | SQLite extension for geometry queries |
| Browser | any evergreen browser | The UI loads Leaflet, Plotly, Turf and SheetJS from CDNs |
| Network | outbound HTTPS | Map tiles, geocoding, and (optionally) price, power-mix and ReFlex APIs |

## 1. Create the Python environment

`pyproject.toml` and `uv.lock` are the source of truth for dependencies.

```bash
uv sync
```

This creates `.venv` from the lockfile. Run every command through `uv run`; it uses the
environment without activating it.

The machine-learning modules in `backend/ml` need PyTorch, which the web app itself does not.
They live behind an optional extra:

```bash
uv sync --extra ml
```

:::{admonition} Working inside a OneDrive folder
:class: warning

OneDrive locks files while it uploads them, which makes `uv sync` fail part-way through with
`os error 396` or `os error 32`. Two settings avoid this:

- `link-mode = "copy"` is already set in `pyproject.toml`, because OneDrive rejects the hardlinks uv normally uses.
- Keep the virtualenv outside the synced tree and point `.venv` at it with a junction, which OneDrive does not follow:

  ```bat
  mkdir %USERPROFILE%\.venvs\EPIOT_v2
  mklink /J .venv %USERPROFILE%\.venvs\EPIOT_v2
  ```

  Run this before the first `uv sync`.
:::

## 2. Install SpatiaLite

EPIOT stores geometry in SQLite and needs the `mod_spatialite` extension. GeoAlchemy2 finds it
through the `SPATIALITE_LIBRARY_PATH` environment variable, which `backend/spatialite.py` sets
automatically. An existing value always wins, so you can point it at a system copy.

::::{tab-set}

:::{tab-item} Windows
There is no system package. Fetch the official prebuilt bundle into `./.spatialite` once:

```bash
uv run python scripts/install_spatialite.py
```

`configure_spatialite()` prepends `./.spatialite` to `PATH` so that `mod_spatialite.dll` can load
its own dependencies (GEOS, PROJ, FreeXL).
:::

:::{tab-item} Ubuntu / Debian
```bash
sudo apt-get install libsqlite3-mod-spatialite
```
:::

:::{tab-item} macOS
```bash
brew install libspatialite
```
:::

:::{tab-item} Conda (legacy)
```bash
conda install libspatialite -c conda-forge
```
:::
::::

## 3. Build the database

Initialize the database offline from the committed country snapshots in `seed_data/`:

```bash
uv run python database_init.py
```

The initializer applies all migrations itself, so do not run `flask db upgrade` first; it refuses
to overwrite an existing database. It writes `instance/default.sqlite` and the charger manifest in
`instance/chargers/`. The session-prior CSVs and the Amsterdam neighbourhood atlas are read directly
from `seed_data/`. No source downloads are needed. See
[seed_data/README.md](../../seed_data/README.md) for
country selection and refreshing the snapshots.

## 4. Run the app

```bash
uv run python app.py
```

The app serves on <http://127.0.0.1:5000>. With `DEBUG = True` (the default in `app.py`) Flask's
reloader and debugger are active. For a production setup see {doc}`../operations/deployment`.

:::{note}
The **Min. Charging Cost** (`ocost`) strategy calls the ReFlex optimisation service at
`drive2x-reflex.hesi.energy`, which is only reachable from the project network. The other three
strategies (`afap`, `alap`, `avg`) run entirely locally.
:::

## Verify the installation

```bash
# The index page renders
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5000/

# Charging points in a small box in central Amsterdam
curl -s -X POST http://127.0.0.1:5000/stations/within \
  -H "Content-Type: application/json" \
  -d '{"type":"Polygon","coordinates":[[[4.89,52.36],[4.91,52.36],[4.91,52.375],[4.89,52.375],[4.89,52.36]]]}'

# The test suite
uv run pytest
```
