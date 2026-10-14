# Scheduled updates

**None are needed.** EPIOT receives no live charging or grid feed. Every
session scenario, CPFT day-ahead scenario and grid-mix value is computed when a
request asks for it, for any past or future date (see
{doc}`../concepts/on-request-scenarios`). Do not install a cron entry or timer
for scenarios, forecasts or grid data.

The web process is the only service to keep running ({doc}`deployment`).

## Occasional, manual tasks

These run when their inputs change, not on a calendar:

| When | Command | Effect |
|---|---|---|
| CPFT checkpoints, preprocessing, session priors, sampler version or timezone change | `uv run --extra cpft python scripts/build_cpft_library.py` | Rebuilds `backend/data/cpft_library.npz` (about 100 minutes). Until then CPFT requests return an explicit 503. |
| Better demand or weather data for the day effects | `uv run --with matplotlib python scripts/calibrate_calendar_effects.py --figures docs/_static/figures` | Re-estimates `backend/data/calendar_effects.json`; see {doc}`../concepts/calendar-effects`. |
| A new free hourly grid dataset is available | `uv run python scripts/prepare_grid_data.py --csv FILE` | Imports observations; the next request uses them. |
| Open-data charging-point sources publish (BNetzA monthly) | `uv run python scripts/update_charger_data.py` | Refreshes infrastructure, not demand. See {doc}`../charger_sources`. |

## What was removed

The previous design ran three recurring jobs, all removed:

- `update_database.py` (cron, daily): generated 100 days of Monte Carlo sessions
  into `sessions` and fetched the last 24 hours of the Electricity Maps power mix.
- `epiot-session-scenarios` (systemd, 18:00): pre-generated tomorrow's simple,
  spatial and CPFT scenarios into `instance/session_scenarios.sqlite`.
- `epiot-grid-data` (systemd, 02:45): pre-resolved grid reference hours.

Existing `sessions` and `power_mixes` rows are kept and still serve the legacy
stored-session source and grid observations. An old
`instance/session_scenarios.sqlite` is no longer read and can be deleted.

## Checking an installation

```bash
# Imported grid observations
sqlite3 instance/grid_data.sqlite "SELECT count(*), min(timestamp), max(timestamp) FROM grid_observations;"

# The CPFT library matches the current inputs (prints its build time)
uv run python -c "from backend.cpft_library import get_library; l = get_library(); l.check('Europe/Amsterdam'); print(l.meta['built_at'])"
```
