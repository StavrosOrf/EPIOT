# Building the documentation

The documentation is a [Sphinx](https://www.sphinx-doc.org/) project written in
[MyST Markdown](https://myst-parser.readthedocs.io/) with the [Furo](https://pradyunsg.me/furo/)
theme.

```bash
uv run --with-requirements docs/requirements.txt sphinx-build -b html docs docs/_build/html
```

Open `docs/_build/html/index.html`. `.readthedocs.yaml` in the repository root builds the same
project on Read the Docs.

## Pages

| File | Topic |
|---|---|
| `index.md` | Overview and navigation |
| `getting-started.md` | Installation, first analysis, data coverage |
| `map-and-areas.md` | The map, its layers, search and the drawing tools |
| `session-sources.md` | Simple, Spatial and CPFT scenarios, demand levels, day effects |
| `charging-strategies.md` | The five strategies and their requirements |
| `load-profiles.md` | The load-profile tab and its window |
| `flexibility.md` | Feasible envelope and headroom signals |
| `kpis.md` | The five KPI dashboards and grid data |
| `reports.md` | The Excel workbook and chart images |
| `rest-api.md` | Endpoints, conventions and a worked example |
| `data-schema.md` | Tables, relationships and input files |
| `architecture.md` | Components, request flow, modules and caching |
| `operations.md` | Configuration, deployment, maintenance and troubleshooting |

## Conventions

- One page per feature. Describe the behaviour of the code as it is, and keep modelling
  simplifications on the page of the feature they affect.
- Update the page in the same change that alters a control, parameter, response field or default.
- Use the interface's own names for controls, strategies and charts.
- Every figure gets a caption and alt text. Screenshots use `:class: screenshot`; charts and
  diagrams use `:class: chart`.

## Partner logos and footer

The partner and funder strip above every page footer comes from `_templates/page.html`, the DRIVE2X
badge under the sidebar brand from `_templates/sidebar/drive2x.html`, and the logo files from
`_static/logos`. Labelec appears as a text wordmark; drop a `labelec.svg` or `labelec.png` there and
swap it into `page.html` to use its official logo.

## Regenerating figures and screenshots

The charts and diagrams in `_static/figures` come from the application's own functions, so
regenerate them after changing a simulator, a prior or the day effects:

```bash
uv run --with matplotlib python docs/_scripts/generate_figures.py
```

The district figures need `instance/default.sqlite` and are skipped without it.

The screenshots in `_static/screenshots` are captured from a running instance with Playwright,
driving an installed Chrome:

```bash
uv run python app.py                 # in one terminal
npm i --no-save playwright-core      # once
node docs/_scripts/capture_screenshots.cjs
```

Set `EPIOT_URL` for another address, `CHROME` for the browser executable on non-Windows systems,
and `DAY` and `RANGE` for other dates. The script draws three fixed rectangles over central
Amsterdam, so it needs a database that contains the Amsterdam chargers.
