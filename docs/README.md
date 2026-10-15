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
| `getting-started.md` | Installation, first analysis, data coverage, configuration, endpoints |
| `session-sources.md` | Simple, Spatial and CPFT scenarios |
| `load-profiles.md` | Load profiles and charging strategies |
| `flexibility.md` | Feasible envelope and headroom signals |
| `kpis.md` | The five KPI dashboards and grid data |

## Conventions

- One page per feature. Describe the behaviour of the code as it is, and keep modelling
  simplifications on the page of the feature they affect.
- Update the page in the same change that alters a control, parameter, response field or default.
- Use the interface's own names for controls, strategies and charts.
