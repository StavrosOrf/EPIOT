# Offline country snapshots

These files initialize a fresh EPIOT server without the raw supplier files or a pre-existing database. Total compressed data: **27.12 MB** (about 98% smaller than the 1.22 GB raw data folder).

| Country | File | MB | Charging points | Coverage |
|---|---|---:|---:|---|
| CH | [CH.json.gz](CH.json.gz) | 0.669 | 20,277 | National |
| DE | [DE.json.gz](DE.json.gz) | 4.546 | 208,992 | National |
| FI | [FI.json.gz](FI.json.gz) | 0.329 | 19,845 | National |
| FR | [FR.json.gz](FR.json.gz) | 3.043 | 144,131 | National, including supplied overseas sites |
| GB | [GB.json.gz](GB.json.gz) | 0.074 | 3,426 | London and Manchester |
| IT | [IT.json.gz](IT.json.gz) | 0.035 | 1,408 | Milan, Rome and Turin |
| LI | [LI.json.gz](LI.json.gz) | 0.001 | 11 | Sites supplied by BFE |
| NL | [NL.json.gz](NL.json.gz) | 18.362 | 192,836 | National + Amsterdam pilot/grid |
| PT | [PT.json.gz](PT.json.gz) | 0.052 | 3,038 | Lisbon and Porto |

`shared.json.gz` (9.7 KB) holds the four session-prior CSVs, unreferenced legacy operator records, shared application tables and original download/import provenance. `manifest.json` records format version, byte sizes, SHA-256 checksums, table counts and source licences/attribution URLs.

## Fresh installation

From the repository root, install SpatiaLite using the platform instructions in [README](../README.md), then:

```
uv sync
uv run python database_init.py
uv run python app.py
```

On Windows, install SpatiaLite with `uv run python scripts/install_spatialite.py` before initialization. The initializer applies all database migrations itself and refuses an existing database. Do not run `flask db upgrade` before initializing a new database. It needs no data-download network access or API key.

To initialize only selected countries:

```
uv run python database_init.py --countries NL DE FR
```

To build a separate disposable installation:

```
uv run python scripts/bootstrap_database.py --database scratch/instance/default.sqlite --data-dir scratch/data
```

The normal app reads `instance/default.sqlite` and `data/`. Custom paths above are useful for validation; configure `FLASK_SQLALCHEMY_ENGINES`, `FLASK_SESSION_SCENARIO_ATLAS`, and the appropriate runtime inputs before serving a custom installation.

## Preserved and rebuilt data

Each country file stores the application fields for locations, operators, columns, charging points, stored sessions, power mixes, transformers, grid connections and any persisted forecasts. IDs, relationships, source/external IDs, address fields, point type and power are preserved. Missing provider power stays missing. Operators shared between countries retain the same ID. Untagged Amsterdam transformer locations and one legacy mislabelled Amsterdam charger are packaged in NL by position; their original labels are preserved.

NL also contains the full Amsterdam neighbourhood geometry and the census attributes used by the spatial sampler, plus available original grid observations with their provenance. Geometry is not simplified. The importer recreates the local atlas GeoPackage, the four session CSVs, charger coverage manifest, SpatiaLite point geometry and indexes.

The bundle retains all 593,964 charging points, 318,163 stored Amsterdam sessions, 28,260 transformers and 717 grid links. Stored sessions elsewhere remain unavailable. Original supplier downloads, live statuses, scenario caches and derived hourly-reference caches are unnecessary for initialization; scenario and grid-reference caches regenerate locally on demand. This does not add national coverage for OSM city datasets or invent missing observations.

The Isle of Wight error is corrected in FR: the eight Carrefour BAB2 Anglet points use the verified address location `(43.486703, -1.501622)`, keeping their IDs. Evidence and future-import protection are in [the correction record](../backend/data/charger_position_overrides.json).

CPFT additionally needs `uv sync --extra cpft`; its existing checkpoints/preprocessing are tracked separately in this repository. The ReFlex cost-optimal strategy still needs a reachable project service. These external/runtime requirements cannot be replaced by country data files.

## Refresh the snapshots

After an authorized supplier refresh or database correction:

```
uv run flask --app app db upgrade
uv run python scripts/update_charger_data.py
uv run python scripts/export_country_data.py
```

Keep every selected country file together with `shared.json.gz` and `manifest.json`. Upload these small files normally to GitHub; each is below 50 MB and needs no Git LFS. `data/` and `instance/` remain ignored. For the snapshot schema, see [backend/bootstrap_data.py](../backend/bootstrap_data.py).

Validated on 14 October 2026: all 12 application tables matched the working
database after reconstruction in a separate checkout without raw supplier data.
Nineteen endpoint checks passed, including spatial selections, transformer
queries, stored/simple/spatial load profiles, minimum-carbon schedules and KPIs.
The suite reported 152 passed and one skipped (the opt-in external ReFlex test).
See [the validation report](../reports/bootstrap_validation.json).
