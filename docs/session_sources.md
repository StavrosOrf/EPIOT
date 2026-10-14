# Selectable session scenarios

The **Session source** control applies to Load profiles, Flexibility and KPIs. The three
options are **Simple session sampler**, **Spatial session sampler**, and **CPFT
tool — synthetic history**. Low/base/high demand are sensitivity assumptions,
not confidence intervals. KPIs use the selected source over an inclusive local
calendar-date range. No verified local charging data are assumed.
All five KPI categories appear as a button bar in the panel header, right of the analysis tabs.
The logo, About and close controls retain fixed positions when categories are
shown, and the analysis logo links to the EPIOT home page.

Every scenario is **generated when it is requested**, for any past or future date.
There is no live charging feed, so there is nothing to forecast or prepare daily:
no scheduled job, no scenario cache and no TensorFlow in the web process. See
{doc}`concepts/on-request-scenarios` for the design and its guarantees.

## Sources

- Simple: the bundled public arrival, connection-duration and energy priors used
  by the existing EV2Gym-style sampler, with a constant attempted-arrival rate.
- Spatial: the same sampling approach, with geographic mixtures of residential,
  workplace, retail and generic public profiles and a density-based arrival-rate
  multiplier. Charger access/electrical type is kept separate from land use.
- CPFT: real outputs of the original `best_availability.keras` and `best_kwh.keras`
  weights on 14 days of spatially generated history, issued at 18:00 local on the
  preceding day. Inputs stop at issue, including exclusion of final energy totals
  for ongoing sessions; the six-hour gap and the entire target local day are
  predicted, and occupied hours become approximate sessions. The trajectories are
  computed once per model version into a library (see below) and sampled per
  request. The earlier checkpoint evaluation found poor next-day performance; this
  integration does not establish local forecasting accuracy.

All three sources are synthetic scenarios. A fixed seed, date, point ID and source
configuration always give the same sessions. Days differ through calibrated
**calendar, weather and demand effects** shared by all points of a country:
season, day of week, public holidays and bridge days, a persistent common
demand shock, and synthetic daily temperature that changes energy per session
({doc}`concepts/calendar-effects`). Each response's `source.calendar` lists
them per day; the page shows a one-line summary below the chart. Changing strategy does not resample
sessions. Simple and spatial sessions belong to one continuous synthetic world per
point, seed and source: a day looks the same in the load profile and inside any KPI
range, and sessions cross midnight without restarting.

## Spatial assumptions

The bundled 2022 Amsterdam neighbourhood atlas is joined to charger coordinates.
Housing, population and business densities determine transparent mixture weights
and an attempted-arrival multiplier, with coefficients in
`backend/spatial_profiles.py`. These coefficients are assumed, not fitted. Missing,
suppressed or out-of-area attributes use a generic public profile, and the API
reports matched and fallback counts. This atlas does not cover all Dutch points.

Residential scenarios add an evening arrival component and scale public dwell
times by 1.4; retail scenarios add a daytime component, scale dwell times by 0.4
and energy by 0.75. Workplace scenarios borrow the bundled workplace priors.
The weekend arrival CSV has no workplace column, so that case borrows the public
arrival shape, matching the existing sampler's fallback. No public residential
charger is classified as a private home charger.

Base attempted arrivals default to 2/day, multiplied by spatial exposure and
0.5/1/1.5 for low/base/high demand. Occupancy can block arrivals, so this is not a
guaranteed realized session count. A Gaussian copula with assumed correlation
0.4 relates duration and energy. Sessions do not overlap per point, may cross
midnight, last 15 minutes to 72 hours, and obey `energy <= charger_power * connected_hours`.
Unknown power uses the application's existing 11 kW fallback. The sampler uses actual
UTC quarter-hours with local-day normalization, including 23/25-hour days. Low,
base and high demand share their random numbers, so they differ only by demand.

## Run

```bash
uv sync --locked
uv run python app.py
```

Nothing else needs to run. The web process needs neither TensorFlow nor a
prepared cache; the CPFT source reads `backend/data/cpft_library.npz`.

App settings: `SESSION_SCENARIO_TIMEZONE`, `SESSION_SCENARIO_ATLAS`,
`SESSION_DAILY_ARRIVALS` and `SESSION_CALENDAR_EFFECTS` (default true; false
disables all day effects) (Flask's `FLASK_` prefixed environment settings).
Points take their holidays and climate from their stored country; points
without one use the Netherlands.

### Rebuilding the CPFT library

The library is versioned with its inputs. Rebuild it only when the checkpoints,
`backend/data/cpft_preprocessing.json`, the session priors in `seed_data/` or the
world sampler version change, or to use another timezone:

```bash
uv sync --locked --extra cpft
uv run --extra cpft python scripts/build_cpft_library.py
```

The build runs the checkpoints over synthetic histories for each calendar context
(target weekday, month and UTC offset at issue) and profile cell (land-use mixture,
attempted-arrival volume, regular or fast point). It takes about 100 minutes on a
16-core machine and produces a 15 MB file. If the inputs no longer match, CPFT requests fail with an explicit
503 asking for a rebuild; they never fall back to random data.

## API and plots

```text
GET /stations/aggregate_load?selected_markers=19291,22929&date=2026-10-15&strategy=avg&session_source=spatial&demand_assumption=base&seed=42
```

Responses retain `x`, `y`, `up_flex`, `down_flex` and add actual UTC `timestamps`,
the previous-day `past_steps` split, and `source` provenance. Sampler profiles
integrate fractional intervals to conserve energy. Charts and exports follow
actual day lengths; exports include source, demand assumption and synthetic status.
Flexibility curves are indicative differences between feasible schedules, not
firm capacity commitments. The existing cost optimizer is used for ordinary
48-hour windows; DST windows return an explicit error for that strategy because
its external service contract is fixed to 288 steps. Other strategies cover DST.

The UI uses `POST /stations/aggregate_load` with the same named fields in JSON,
and `selected_markers` as an ID array, to support regions with long point lists
without exceeding server URL limits. The target date defaults to today, and the
date pickers accept any date, past or future.

API calls omitting `session_source` retain the existing database-backed path for
backward compatibility. The web selector explicitly chooses one of the three
synthetic sources, so it does not silently use the unverified stored sessions.

`POST /kpi/user` accepts `selected_markers`, `start_date`, `end_date`,
`session_source`, `demand_assumption` and `seed`. Dates are `YYYY-MM-DD`; both
endpoints are included, including a same-day range, and ranges are limited to
366 days. Range selections persist when switching tabs. First opening KPIs
defaults to the last seven calendar days, including today.
Simple and spatial ranges are generated as one continuous window, so a range
equals the sum of its single days. CPFT forecasts each day from its own issue
time; its synthetic history before issue is never counted. Overnight
occupancy/energy is restricted to each actual local day, and full session
durations are retained for arrival statistics. Zero-use selected points are
included in availability and daily distributions.

### Fast retrieval

Generation is vectorized over all selected points, so the server needs no cache.
The browser still avoids repeated requests: Load Profiles and Flexibility share
the same response for identical charger IDs, date, strategy, source, demand
assumption and seed. Area membership is cached independently of date and
strategy. Analysis requests use compact IDs-only spatial responses; transformer
membership is resolved only for the grid view. A lightweight
`GET /stations/analysis-version` checks freshness on each analysis action, so
database, configuration, input-file and CPFT-library changes invalidate affected
results. Browser caches are page-local and bounded to 64 entries each;
simultaneous identical requests share a promise, and failures are not retained.

The UI requests `section=basic` from `POST /kpi/user` first. This returns User,
Grid, Mobility and City statistics without reading grid-mix data or simulating
charging strategies. Opening Environment requests `section=environment` using
the captured charger IDs, dates and source. Its response is merged into those
basic results. Excel export also waits for this section if it has not yet been
opened. The default `section=all` retains the combined API response for existing
clients. Basic summaries omit `scheduled_energy_kwh`; their average-energy
total is calculated analytically with the same arrival-cohort/window convention.

Geographic profiles are memoized by atlas instance and coordinates (at most
32,768 entries); changing the atlas file or coordinates causes a fresh spatial
lookup. Non-file database deployments should update the
`ANALYSIS_DATA_REVISION` Flask setting when underlying data change.

Environmental KPIs use matching-date grid hours where available and a clearly
labelled historical hourly reference otherwise, resolved per request from the
imported observations. Missing values stay null when no valid reference exists.
They report energy coverage, fixed-energy strategy comparisons and a
minimum-carbon schedule. See [environmental KPI details](environmental_kpis.md)
for provenance and importing grid data.

## Verification

```bash
uv run --extra cpft pytest -q
node --test tests/test_scenario_charts.mjs tests/test_kpi_ui.mjs tests/test_environment_summary.mjs
```

On restricted Windows/OneDrive checkouts where Node cannot resolve parent-folder
symlinks, use `node --preserve-symlinks --preserve-symlinks-main --test tests/test_scenario_charts.mjs tests/test_kpi_ui.mjs tests/test_environment_summary.mjs`.

Tests cover geographic assignment, missing-data fallback, source isolation,
window independence (a day alone equals the same day in longer windows, across
both DST transitions), session constraints, energy conservation, overnight
connections, chart/export timestamps, equivalence of the vectorized profile and
minimum-carbon schedules with the per-session versions they replaced, batched
CPFT features and recursive forecasts against the row-by-row reference, CPFT
library sampling and rejection of a stale library, and actual checkpoint
reproduction against its original saved output. Library tests use a small
generated library and need no TensorFlow.

### Reproducible speed comparison

```bash
uv run --extra cpft python scripts/benchmark_on_the_fly.py --baseline 9ef972c
```

It runs the previous cached design (revision `9ef972c`) and the working tree in
separate processes on identical synthetic points, and writes
`reports/on_the_fly_speed.json` and `.md`. For the baseline it reports both a day
the daily job had prepared (warm) and one it had not (cold: a new date, seed or
demand level). Imports, model/library/atlas loading, HTTP and the database are
outside the measured window.
