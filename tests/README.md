# Tests

Run from the repository root using the locked project environment:

```bash
uv sync --locked
uv run pytest -q
uv run --extra cpft pytest -q  # also runs the TensorFlow checkpoint tests
```

## On-request scenarios

| File | Coverage |
| --- | --- |
| `test_on_the_fly.py` | Window independence of the synthetic world across DST, session constraints, seed/source/demand behaviour, vectorized profiles and minimum-carbon schedule against the per-session versions, CPFT library sampling (issue cut, DST horizons, volume-bin mixing, day/range equality) |
| `test_calendar_effects.py` | Calibrated day effects: long-run means preserved, weather generator against the climatology, demand-shock size and persistence, window independence, Dutch and German day types, holidays on the weekend curve, larger day-to-day variation, disabled effects, CPFT holidays as Sundays and temperature-scaled energy |
| `test_calendar_note.mjs` | The page's one-line summary of the day effects |
| `test_cpft_runtime.py` | Batched CPFT observations, features and recursive forecasts against the row-by-row reference |
| `test_session_sources.py`, `test_kpi_sources.py` | Sources and KPIs through the HTTP endpoints, generated per request for any date; explicit errors for a missing or stale CPFT library |

CPFT library tests use `cpft_helpers.write_test_library`, a small library in the
real format that needs no TensorFlow.

## API behaviour and the profile engine

| File | Coverage |
| --- | --- |
| `test_scenario_profiles.py` | Hand-built sessions through the vectorised engine every source uses: as fast as possible, as late as possible and average power, energy conservation, windows, the 11 kW fallback and overnight connections |
| `test_api_hardening.py` | Stored sessions through the same engine and strategies, JSON errors, date and ID validation, the `(cp_id, start)` indexes and their migration, shared request parsing, `/healthz`, static MIME types and the debug flag |
| `test_aggregators.py` | The cost-optimal path through ReFlex (the only strategy not computed locally) with stubbed services |
| `*.mjs` | Browser modules under Node, imported directly (the root `package.json` marks them ES modules): `node --test tests/*.mjs` or `npm test`. `test_group_actions.mjs` and `test_analysis_cache.mjs` use the real `areas.js` and `analysis.js` with stand-in collaborators |
| `test_ensemble.mjs` | Seeded draws: the band in the chart data, the note, the request and the report |

`scripts/e2e_smoke.mjs` drives the running app in Chrome (draw, analyse, edit cards, draws, tabs); it is
a manual check, see its header.

CI (`.github/workflows/ci.yml`) runs both suites on every push.

## CPFT prediction, persistence, and retrieval

```bash
uv run pytest tests/test_cpft.py tests/test_forecast_store.py -q
```

The application does not persist forecasts (scenarios are generated per
request); the forecast tables remain for the CPFT audit scripts.

The tests use temporary SQLite files, apply the new forecast migration there,
and verify writes through a fresh connection. They do not import `app.py`, access
`instance/default.sqlite`, require SpatiaLite, start a server, or contact APIs.
Only a minimal charging-point ID directory is needed to exercise the forecast
tables' real foreign keys. The existing observed-session table is also created
to check that forecast writes leave observations intact.

| File | Coverage |
| --- | --- |
| `test_cpft.py` | Predictor calls for every point, exact local-day horizon, UTC normalization, 23/25-hour DST days, occupancy-to-session conversion, energy conservation, invalid inputs, model failure |
| `test_forecast_store.py` | Prediction/save/fetch round trip, zero-session forecasts, point/run filtering, idempotent retries, run identity, invalid writes, transactional rollback, concurrent readers, migration downgrade |
| `cpft_helpers.py` | Deterministic CPFT output fixtures, a model stub and a test CPFT library |

The supporting functions are:

- `backend.cpft.predict_session_forecasts(predictor, histories, ...)`: calls an
  injected predictor and validates the complete batch before any database write.
- `backend.cpft.adapt_cpft_output(cp_id, rows, ...)`: accepts the four fields in
  CPFT's `forecast_whole_period` output and derives approximate sessions.
- `backend.forecast_store.save_forecast_batch(engine, batch)`: saves one run
  atomically in dedicated forecast tables, separately from observations.
- `backend.forecast_store.fetch_forecast_batch(engine, run_id, cp_ids=None)`:
  retrieves that run, with timezone-aware UTC timestamps and optional point
  filtering. An unknown run returns `None`; known zero demand retains its hours.

The predictor must implement `forecast(cp_id=..., history=..., start=..., end=...)`
and return an iterable of records with these fields:

```python
{
    "hour": "2026-10-14T08:00:00Z",
    "availability_forecast_prob": 0.8,
    "availability_forecast_bin": 1,
    "kWh_forecast_next_whole_period": 3.5,
}
```

For a pandas CPFT output frame, return `frame.to_dict("records")`. Supply exactly
the requested day's hours; convert timezone-free CPFT Excel timestamps explicitly
to UTC before adaptation. CPFT's availability `1` means **occupied**. Runs of
occupied hours become approximate sessions. A session touching the target-window
boundary is marked censored: that boundary is not a known arrival/departure.

These tests **stub model inference**. They verify the integration contract and
real database behavior, not trained CPFT accuracy. The adapter deliberately has
no random fallback and does not import the research script, which retrains on
execution. Connecting saved CPFT models/scalers, observed-history selection,
session-level forecasting and web routes are handled by the CPFT library
(`backend/cpft_library.py`); daily scheduling is not needed.

The forecast migration is included but not applied to the application database
by this test suite. When integrating with the app, use the existing Alembic
migration workflow first. Fetch by explicit run ID; automatic selection and
publication of the latest run are not implemented by this small adapter.
