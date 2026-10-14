# Project structure

```text
EPIOT_v2/
├── app.py                     Flask entry point: app setup, blueprints, index, icons
├── database_init.py           Offline database initialization from seed_data/
├── pyproject.toml / uv.lock   Dependencies (uv); optional extra `ml`
├── requirements.txt           Legacy pip/conda requirements
├── backend/
│   ├── models.py              SQLAlchemy models
│   ├── views.py               /stations blueprint
│   ├── features.py            /features blueprint
│   ├── kpi/user.py            /kpi blueprint
│   ├── aggregators.py         Charging-strategy simulators
│   ├── charge_sessions.py     Session generators and diagnostics
│   ├── loaders.py             Grid-connection helper (nearest transformer per column)
│   ├── utils.py               GeoJSON serialisers, availability helper
│   ├── spatialite.py          SpatiaLite discovery
│   ├── config.yaml            Session and energy-demand distributions
│   ├── api_calls/
│   │   ├── prices.py          Energy-Charts day-ahead prices
│   │   ├── reflex.py          ReFlex query builder
│   │   └── env_data_api.py    Electricity Maps power mix
│   └── ml/                    LSTM scaffolding (predictor, preprocessing, utils)
├── templates/index.html       The single page
├── static/
│   ├── css/                   styles.css, landing.css
│   ├── scripts/               script.js, loaders.js, data_fetch.js, plotter.js, utils.js, landing.js
│   └── images/                Map icons, logos, favicon
├── migrations/                Alembic revisions
├── scripts/                   install_spatialite.py, build_cpft_library.py, import and benchmark scripts
├── tests/                     pytest suite and exploratory notebooks
├── others/                    Related DRIVE2X tools: CPFT, ReFlex specification
├── docs/                      This documentation (Sphinx)
├── seed_data/                 Compact country snapshots that initialize a fresh database
└── instance/                  Database, caches and restored runtime inputs (git-ignored)
```

## Where to change what

| Task | Start here |
|---|---|
| Add a charging strategy | `backend/aggregators.py` (new simulator) → `backend/views.py` (dispatch on `strategy`) → `templates/index.html` (`#strategy` option) |
| Add a KPI | `backend/kpi/user.py` (compute and return the field) → `static/scripts/plotter.js` (render) → `static/scripts/utils.js` (export row) |
| Add a map layer | `backend/features.py` or `backend/views.py` (endpoint) → `static/scripts/loaders.js` (markers) → app-bar toggle in `index.html` and `script.js` |
| Support a new city | Add a region or supplier in `backend/charger_sources.py`, import with `scripts/update_charger_data.py`, then re-export `seed_data/` with `scripts/export_country_data.py` |
| Change the session generator | `backend/charge_sessions.py`, then regenerate sessions |
| Change the look | `static/css/styles.css`; chart styling in `renderPlot` in `plotter.js` |

## Adding a charging strategy, step by step

```{mermaid}
flowchart TB
    A["aggregators.py<br/>def simulate_my_strategy(chargers, sessions, start_date)<br/>→ (load, up, down)"] --> B["views.py<br/>elif method == 'mine': …"]
    B --> C["index.html<br/>&lt;option value='mine'&gt;My strategy&lt;/option&gt;"]
    C --> D["tests/test_aggregators.py<br/>energy conservation, window bounds"]
```

The simulator must return three lists of 288 floats (kW) aligned with the window described in
{doc}`../concepts/time-model`.
