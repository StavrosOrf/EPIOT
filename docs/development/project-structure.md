# Project structure

```text
EPIOT_v2/
├── app.py                     Flask entry point: app setup, blueprints, index, icons
├── database_init.py           One-off database population (loaders, sessions, power mix)
├── update_database.py         Scheduled job: Monte Carlo sessions + power mix
├── pyproject.toml / uv.lock   Dependencies (uv); optional extra `ml`
├── requirements.txt           Legacy pip/conda requirements
├── backend/
│   ├── models.py              SQLAlchemy models
│   ├── views.py               /stations blueprint
│   ├── features.py            /features blueprint
│   ├── kpi/user.py            /kpi blueprint
│   ├── aggregators.py         Charging-strategy simulators
│   ├── charge_sessions.py     Session generators and diagnostics
│   ├── loaders.py             Importers for stations, transformers, grid links
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
├── scripts/                   install_spatialite.py, cron and run scripts
├── tests/                     pytest suite and exploratory notebooks
├── others/                    Related DRIVE2X tools: CPFT, ReFlex specification
├── docs/                      This documentation (Sphinx)
├── data/                      Source datasets (git-ignored)
└── instance/default.sqlite    The database (git-ignored)
```

## Where to change what

| Task | Start here |
|---|---|
| Add a charging strategy | `backend/aggregators.py` (new simulator) → `backend/views.py` (dispatch on `strategy`) → `templates/index.html` (`#strategy` option) |
| Add a KPI | `backend/kpi/user.py` (compute and return the field) → `static/scripts/plotter.js` (render) → `static/scripts/utils.js` (export row) |
| Add a map layer | `backend/features.py` or `backend/views.py` (endpoint) → `static/scripts/loaders.js` (markers) → app-bar toggle in `index.html` and `script.js` |
| Support a new city | New loader in `backend/loaders.py`, new source data, and session generation over the new scope in `backend/charge_sessions.py` |
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
