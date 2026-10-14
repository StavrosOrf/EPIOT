# Testing

The test suite uses **pytest** and lives in `tests/`. Configuration is in `pyproject.toml`
(`testpaths = ["tests"]`, `pythonpath = ["."]`, and the cache provider disabled for OneDrive
checkouts).

```bash
uv run pytest
```

## What is covered

`tests/test_aggregators.py` exercises the *As Fast As Possible* simulator with hand-built sessions:

| Test | Asserts |
|---|---|
| `test_uncontrolled_profile_charges_at_full_power_from_arrival` | A 5 kWh session on a 6 kW charger produces 5 full-power steps from arrival, conserves energy, and yields downward flexibility at departure and no upward flexibility |
| `test_uncontrolled_profile_skips_sessions_outside_the_window` | Sessions outside the two-day window are ignored |
| `test_uncontrolled_profile_falls_back_to_11kw_for_unknown_limit` | A missing rated power defaults to 11 kW |

The tests build sessions as `(cp_id, start, end, consumption)` tuples, the same shape the views pass
in, so no database is needed.

## Writing new tests

Use round numbers so expectations are exact: a 6 kW charger delivers exactly 1 kWh per 10-minute step.

```python
import datetime
from backend.aggregators import simulate_delayed_profiles_from_sessions

def test_delayed_profile_finishes_at_departure():
    chargers = {1: 6.0}
    sessions = [(1, datetime.datetime(2025, 1, 15, 10), datetime.datetime(2025, 1, 15, 14), 5.0)]
    load, _, _ = simulate_delayed_profiles_from_sessions(chargers, sessions, start_date="2025-01-15")
    end_step = 14 * 6
    assert load[end_step - 4 : end_step + 1] == [6.0] * 5
```

## Exploratory notebooks

`tests/` also holds notebooks used while developing the external integrations:
`price_day_ahead.ipynb` (Energy-Charts prices), `energy_mix.ipynb` (power mix) and
`weatherAPI_forecast.ipynb` (weather forecasts). They are not part of the automated suite.
