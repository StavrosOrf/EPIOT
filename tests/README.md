# CPFT prediction, persistence, and retrieval tests

Run from the repository root using the locked project environment:

```bash
uv sync --locked
uv run pytest tests/test_cpft.py tests/test_forecast_store.py -q
uv run pytest -q
```

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
| `cpft_helpers.py` | Deterministic CPFT output fixtures and a model stub |

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
session-level forecasting, web routes, and daily scheduling remain separate work.

The forecast migration is included but not applied to the application database
by this test suite. When integrating with the app, use the existing Alembic
migration workflow first. Fetch by explicit run ID; automatic selection and
publication of the latest run are not implemented by this small adapter.
