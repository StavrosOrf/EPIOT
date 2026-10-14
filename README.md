## EPIOT - Drive2X WP5
This is the development repository of the Drive2X working package 5. The purpose of the tool to be developed is 
the following:

- provide short-term load forecasting for charge point operators and grid operators

The tool is supposed to be easily accessible and to provide a range of interfaces for researchers and developpers.


## Environment setup

The project is managed with [uv](https://docs.astral.sh/uv/); `pyproject.toml`
and `uv.lock` are the source of truth, and `requirements.txt` is kept only for
the legacy conda instructions below.

```
uv sync
```

That creates `.venv` from the lockfile. Run everything through `uv run`, which
uses that environment without needing to activate it:

```
uv run python app.py
uv run pytest
```

The load-forecasting models in `backend/ml` need PyTorch, which the Flask app
does not. They live behind an optional extra:

```
uv sync --extra ml
```

### OneDrive checkouts

This repository is often cloned inside a OneDrive-synced folder. OneDrive locks
files while it uploads them, which makes `uv sync` fail part-way through with
`os error 396` or `os error 32`. Two things avoid that:

- `link-mode = "copy"` is set in `pyproject.toml`, because OneDrive rejects the
  hardlinks uv normally uses.
- Keep the virtualenv outside the synced tree. Create the real directory
  elsewhere and point `.venv` at it with a junction, which OneDrive does not
  follow:

  ```
  mkdir %USERPROFILE%\.venvs\EPIOT_v2
  mklink /J .venv %USERPROFILE%\.venvs\EPIOT_v2
  ```

  Run that before the first `uv sync`. Everything else, `uv run` included,
  keeps working through the junction.

## Setting up the database

### SpatiaLite

The app stores geometry in SQLite and needs the `mod_spatialite` extension.
GeoAlchemy2 finds it through `SPATIALITE_LIBRARY_PATH`; `backend/spatialite.py`
sets that automatically, and an existing value is always respected if you want
to point at a system copy instead.

On Windows there is no system package, so fetch the official prebuilt bundle
into `./.spatialite` once:

```
uv run python scripts/install_spatialite.py
```

On Ubuntu:

```
sudo apt-get install libsqlite3-mod-spatialite
```

On macOS:

```
brew install libspatialite
```

### Data and migrations

The GitHub-ready snapshots in **./seed_data** contain the required data in one
compressed JSON file per country, plus a small shared file and a checksum manifest.
No raw supplier downloads, large GeoPackages, existing SQLite database or API
credentials are needed. After installing SpatiaLite, initialize a fresh checkout:

```
uv run python database_init.py
uv run python app.py
```

The initializer applies all migrations, restores stable charger IDs, powers,
Amsterdam sessions, transformers/grid links and historical electricity data,
rebuilds SpatiaLite geometry/indexes, and restores the spatial atlas and session
priors. Runtime caches are regenerated on demand. It refuses to overwrite an
existing database. To install only selected countries:

```
uv run python database_init.py --countries NL DE FR
```

Details, coverage and snapshot sizes are in [seed_data/README.md](seed_data/README.md).
For an existing server, apply new migrations with `uv run flask --app app db upgrade`.
To apply the verified Anglet location correction without changing any charger IDs:

```
uv run python scripts/repair_charger_positions.py
```

To refresh chargers from their original suppliers, download the open data into
`./data/chargers` and import it (optional; initialization needs no downloads):

```
uv run python scripts/update_charger_data.py
uv run python scripts/export_country_data.py
```

Sources, licences, the field mapping and next steps are in
[docs/charger_sources.md](docs/charger_sources.md).

The standard install supports stored, simple and spatial sessions. CPFT inference
also requires `uv sync --extra cpft`; its checkpoints and preprocessing are already
in the repository. The remote ReFlex service still requires project network access.

## Running the app

```
uv run python app.py
```

The app serves on http://127.0.0.1:5000.

Note that the `ocost` (cost-optimal) charging strategy calls the ReFlex service
at `drive2x-reflex.hesi.energy`, which is only reachable from the project
network. The other strategies (`afap`, `alap`, `avg`) run entirely locally.

## Legacy conda setup

The project previously used conda. These instructions are kept for reference;
prefer `uv sync` above.

```
conda create -n epiot python=3.11
conda activate epiot
conda install libspatialite -c conda-forge
pip install -r requirements.txt
```

If you have trouble installing libspatialite, see
https://docs.djangoproject.com/en/5.1/ref/contrib/gis/install/spatialite/

The current development team consists of:

- Stavros Orfanoudakis (TU Delft, lead developper)
- Babak Ravanbach (DLR, product owner)

Past developpers:
- Arellano Ruiz, Eugenio Salvador (DLR, developper)
- Elif Turhan (DLR, developper)
- Niklas Wulff (DLR, developper)
