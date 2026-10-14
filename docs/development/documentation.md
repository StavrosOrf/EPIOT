# Building these docs

The documentation is a [Sphinx](https://www.sphinx-doc.org/) project in `docs/`, written in
[MyST Markdown](https://myst-parser.readthedocs.io/) with the [Furo](https://pradyunsg.me/furo/)
theme. Diagrams are [Mermaid](https://mermaid.js.org/) blocks rendered in the browser; cards, grids
and tabs come from [sphinx-design](https://sphinx-design.readthedocs.io/).

## Build locally

```bash
uv run --with-requirements docs/requirements.txt sphinx-build -b html docs docs/_build/html
```

Open `docs/_build/html/index.html`. For live reload while writing:

```bash
uv run --with-requirements docs/requirements.txt --with sphinx-autobuild \
  sphinx-autobuild docs docs/_build/html
```

## Publish on Read the Docs

`.readthedocs.yaml` at the repository root configures the build (Ubuntu 24.04, Python 3.12, Sphinx
with `docs/conf.py`, dependencies from `docs/requirements.txt`). Import the repository on Read the
Docs and every push builds the site; no other setup is needed.

## Layout

```text
docs/
├── conf.py                  Sphinx configuration (theme, extensions, Mermaid)
├── requirements.txt         Build dependencies
├── index.md                 Landing page and navigation tree
├── getting-started/  user-guide/  concepts/  architecture/
├── api/  operations/  development/  related-tools/  reference/
├── _static/
│   ├── custom.css           Brand styling
│   ├── logo.svg
│   ├── figures/             Generated charts (SVG)
│   └── screenshots/         Captured from the running app (JPEG)
└── _scripts/
    ├── generate_figures.py      Regenerates _static/figures
    └── capture_screenshots.js   Regenerates _static/screenshots
```

## Regenerate figures

The charts are produced by the application's own functions, so regenerate them after changing a
simulator or the session data:

```bash
uv run --with matplotlib python docs/_scripts/generate_figures.py
```

Figures that need `instance/default.sqlite` or the CSVs in `./seed_data` are skipped when those are absent.

## Regenerate screenshots

Start the app, then drive an installed Chrome with Playwright:

```bash
uv run python app.py            # in one terminal
npm i --no-save playwright-core # once
node docs/_scripts/capture_screenshots.js
```

Set `CHROME` to the browser executable on non-Windows systems and `EPIOT_URL` for a remote instance.
The script draws three fixed areas over central Amsterdam and uses dates that must have sessions and
power-mix data in the target database.

## Writing conventions

- One page per feature or concept; link with `` {doc}`../path/page` ``.
- Every figure gets a caption and alt text. Screenshots use `:class: screenshot`; charts use
  `:class: chart`.
- Describe the behaviour of the code as it is. Put modelling simplifications in
  {doc}`../reference/known-limitations` instead of hiding them.
