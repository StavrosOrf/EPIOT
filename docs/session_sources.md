# Selectable session scenarios

The **Session source** control applies to Load profiles, Flexibility and KPIs. The three
options are **Simple session sampler**, **Spatial session sampler**, and **CPFT
tool — synthetic history**. Low/base/high demand are sensitivity assumptions,
not confidence intervals. KPIs use the selected source over an inclusive local
calendar-date range. No verified local charging data are assumed.
All five KPI categories appear as a button bar in the panel header, right of the analysis tabs.
The logo, About and close controls retain fixed positions when categories are
shown, and the analysis logo links to the EPIOT home page.

## Sources

- Simple: the bundled public arrival, connection-duration and energy priors used
  by the existing EV2Gym-style sampler, with a constant attempted-arrival rate.
- Spatial: the same sampling approach, with geographic mixtures of residential,
  workplace, retail and generic public profiles and a density-based arrival-rate
  multiplier. Charger access/electrical type is kept separate from land use.
- CPFT: the original `best_availability.keras` and `best_kwh.keras` weights run
  on 14 days of spatially generated history. Issue is 18:00 Europe/Amsterdam on
  the preceding day. Inputs stop at issue, including exclusion of final energy
  totals for ongoing sessions. The six-hour gap and the entire target local day
  are predicted. Occupied hours become approximate sessions. The earlier
  checkpoint evaluation found poor next-day performance; this integration does
  not establish local forecasting accuracy.

All three sources are synthetic scenarios. A fixed seed, target date, point ID
and source configuration make selections repeatable. Changing strategy does not
resample sessions. CPFT imports TensorFlow lazily, keeps its 72-hour input shape,
uses the verified frozen scalers/feature ordering, and recomputes lags, rolling
features and UTC calendar fields. It never runs the original training script.
The runtime shares feature construction with the executed checkpoint audit.

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
midnight, and obey `energy <= charger_power * connected_hours`. Unknown power
uses the application's existing 11 kW fallback. The temporal sampler uses actual
UTC quarter-hours with local-day normalization, including 23/25-hour days.

## Run and prepare

```bash
uv sync --locked --extra cpft
uv run --extra cpft python app.py
uv run --extra cpft python scripts/prepare_session_scenarios.py --date 2026-10-15
```

The preparation command defaults to tomorrow in Europe/Amsterdam and all points
in the application database. `--source`, `--assumption`, `--seed`, `--point-ids`,
`--database` and `--cache` provide explicit overrides. Its application database
connection is read-only. It can run beside Flask/Gunicorn as an independent
process; model batches are limited to 64 points.

Scenarios are saved in a **separate** SQLite cache at
`instance/session_scenarios.sqlite`, using WAL and short atomic writes. Original
`sessions` rows are never changed. Cache identity includes source, date, point
attributes, geographic profile, seed, demand assumption and input/code versions.
The app reads prepared results or computes a cache miss. Cached CPFT results can
be read without TensorFlow; uncached CPFT requests require the optional extra and
fail explicitly if inference is unavailable. They never fall back to random data.

App settings: `SESSION_SCENARIO_CACHE`, `SESSION_SCENARIO_TIMEZONE`, `SESSION_SCENARIO_ATLAS` and
`SESSION_DAILY_ARRIVALS` (Flask's `FLASK_` prefixed environment settings).
Use a local VM disk for the database/cache in production. Example systemd service
and timer files are in `scripts/systemd/`; adjust paths/user before installation.
They run at 18:00 Europe/Amsterdam and have not been enabled on this Windows
workspace. For replay of a missed target, run the command with its explicit date.

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
without exceeding server URL limits. The target date defaults to today, and all
date pickers allow only today or earlier. The separate daily preparation job can
still generate tomorrow's forecasts.

API calls omitting `session_source` retain the existing database-backed path for
backward compatibility. The web selector explicitly chooses one of the three
new sources, so it does not silently use the unverified stored sessions.

`POST /kpi/user` accepts `selected_markers`, `start_date`, `end_date`,
`session_source`, `demand_assumption` and `seed`. Dates are `YYYY-MM-DD`; both
endpoints are included, including a same-day range, and future KPI dates are
rejected. Range selections persist when switching tabs. First opening KPIs
defaults to the last seven calendar days, including today.
Each day reuses that source's cached target-day data; its previous-day history
is not counted again. Overnight occupancy/energy is restricted to each actual
local day, and full session durations are retained for arrival statistics.
Zero-use selected points are included in availability and daily distributions.

### Fast retrieval

Load Profiles and Flexibility share the same cached response for identical
charger IDs, date, strategy, source, demand assumption and seed. Area membership
is cached independently of date and strategy. Analysis requests use compact
IDs-only spatial responses; transformer membership is resolved only for the
grid view. A lightweight `GET /stations/analysis-version` checks freshness on
each analysis action, so database/configuration/input-file changes invalidate
affected results. Browser caches are page-local and bounded to 64 entries each;
simultaneous identical requests share a promise, and failures are not retained.

The UI requests `section=basic` from `POST /kpi/user` first. This returns User,
Grid, Mobility and City statistics without reading grid-mix data or simulating
charging strategies. Opening Environment requests `section=environment` using
the captured charger IDs, dates and source. Its response is merged into those
basic results. Excel export also waits for this section if it has not yet been
opened. The default `section=all` retains the combined API response for existing
clients. Basic summaries omit `scheduled_energy_kwh`; their average-energy
total is calculated analytically with the same arrival-cohort/window convention.

Scenario-cache reads use one SQLite connection per selected day, with queries
of at most 900 keys. Geographic profiles are memoized by atlas instance and
coordinates (at most 32,768 entries); changing the atlas file or coordinates
causes a fresh spatial lookup. Existing session-cache identity and source
isolation are preserved. Non-file database deployments should update the
`ANALYSIS_DATA_REVISION` Flask setting when underlying data changes.

Environmental KPIs use matching-date grid hours where available and a clearly
labelled historical hourly reference otherwise. Missing values stay null when
no valid reference exists. They report energy coverage, fixed-energy strategy
comparisons and a minimum-carbon schedule. See [environmental KPI details](environmental_kpis.md)
for provenance, the free/local data pipeline and the daily background job.

## Verification

```bash
uv run --extra cpft pytest -q
node --test tests/test_scenario_charts.mjs tests/test_kpi_ui.mjs tests/test_environment_summary.mjs
```

On restricted Windows/OneDrive checkouts where Node cannot resolve parent-folder
symlinks, use `node --preserve-symlinks --preserve-symlinks-main --test tests/test_scenario_charts.mjs tests/test_kpi_ui.mjs tests/test_environment_summary.mjs`.

Tests cover geographic assignment, missing-data fallback, source isolation,
save/fetch across repeated selections, model failure, session constraints,
energy conservation, overnight connections, both DST transitions, chart/export
timestamps and actual checkpoint reproduction against its original saved output.

### Reproducible speed comparison

Run the before/after benchmark from the repository root:

```bash
uv run python scripts/benchmark_analysis.py --repeats 5
```

It compares the exact pre-optimization code at Git revision `4ba8f16` with the
working tree, using disposable synthetic data, SQLite, real SpatiaLite and
localhost HTTP. It does not open application databases or contact external
services. The default cases use 100 chargers over 7 days for the HTTP workflow,
1,000 cached points, and a larger 500-charger/30-day KPI calculation.
Node.js, the bundled session priors, the Amsterdam atlas and SpatiaLite are
required. Startup/import/fixture preparation are outside the measured window.

Each comparison alternates execution order, discards a warmup and records every
timing sample. Profile values, basic statistics and environmental results are
checked for equivalence. The script refuses to compare different numerical
dependencies. Reports are written to `reports/analysis_speed_comparison.json`
and `.md`. Timings exclude chart rendering and real-world network latency;
CPFT inference and the external optimizer are not measured. Cold-cache timings
include real scenario generation, while cached timings measure retrieval.

For the smaller executable regression test in PowerShell:

```powershell
$env:EPIOT_BENCHMARK = "1"
uv run pytest tests/test_analysis_benchmark.py -q
Remove-Item Env:EPIOT_BENCHMARK
```

The test checks results and avoided requests, without asserting a machine-dependent
speedup. If the default uv cache is inaccessible, add
`--cache-dir .cache/uv --no-sync` to `uv run` when the project environment is
already installed.
