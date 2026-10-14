# On-request scenarios

EPIOT receives no live charging data. Every session the application analyses is
synthetic, and a synthetic scenario depends only on fixed inputs: the charging
point, its spatial profile, the bundled priors, the demand assumption, the seed
and the calendar. Nothing about it changes from one day to the next, so there is
no reason to forecast or generate sessions on a daily schedule.

EPIOT therefore computes every scenario when it is requested, for any past or
future date, and stores nothing. Days still differ: season, day of week,
holidays, a common demand shock and synthetic weather are applied per day
({doc}`calendar-effects`).

| | Previous design | On-request design |
|---|---|---|
| Simple / spatial sessions | Generated per target day, cached in `instance/session_scenarios.sqlite`, pre-warmed by an 18:00 systemd timer | Sampled per request from one fixed synthetic world, vectorized over all points |
| CPFT sessions | TensorFlow inference in the web process on a cache miss (about 0.1 s per point and day) | Real checkpoint trajectories, built once per model version and sampled per request |
| Grid carbon / renewables | Resolved by a daily timer into a cache | Resolved per request from the imported observations |
| Dates | Up to today | Any date |
| Scheduled jobs | Scenario timer, grid timer, daily `update_database.py` cron | None |

## One synthetic world per point

A scenario is a view of one continuous synthetic world per point, source and
seed (`backend/scenario_world.py`). Two choices make any window of it cheap to
compute on its own:

- **Counter-based randomness.** Each point's random numbers are a hash of its ID,
  the source, the seed and the absolute UTC quarter-hour, not a sequence drawn
  from a start date. A given quarter-hour always gets the same numbers,
  whatever window asks for it.
- **Occupancy in fixed daily blocks.** A charger cannot accept an arrival while
  occupied, which makes sessions depend on earlier ones. Each UTC day is
  simulated from empty three days earlier (the longest connection is 72 hours)
  and keeps only its own arrivals. Because the random numbers are shared, the
  warm-up almost always reproduces the earlier days exactly. If it does not, an
  arrival that would overlap a connection kept by one of the three previous days
  is dropped. The rule depends only on fixed blocks, never on the request.

```{mermaid}
flowchart LR
    R[Request: points, dates,<br/>source, demand, seed] --> W[Blocks covering the window<br/>+ 72 h of earlier arrivals]
    W --> H[Hash per point and quarter-hour<br/>vs arrival probability]
    H --> A[Duration and energy<br/>from the same hash]
    A --> B[Blocked walk per point and day<br/>3-day warm-up]
    B --> S[Sessions overlapping the window]
```

As a result:

- a day sampled alone is identical to the same day inside a month-long KPI range,
  so a range equals the sum of its days;
- sessions never overlap on a point, cross midnight without restarting and obey
  `energy <= power * connected hours`;
- low, base and high demand share their random numbers, so they differ only by
  demand;
- arrival times, durations and energies follow the same priors as the previous
  sequential sampler (two-sample tests show no difference).

## CPFT without TensorFlow at request time

CPFT forecasts the next day recursively from 72 hours of hourly features, with
two bidirectional LSTM models. Every step re-reads the whole window, about 1.7
GFLOP per point and day, and the measured cost was about 0.1 s per point and
day. A 500-point, 7-day KPI range would take about six minutes, which is why
the previous design needed a daily pre-warm.

Without live data, CPFT's input history is itself synthetic. Its forecast
therefore depends only on the calendar and on how that history was generated.
Running the real checkpoints showed which of these matter (mean absolute change
in hourly occupancy probability against a Thursday-in-October baseline):

| Input | Effect | Library dimension |
|---|---|---|
| Point power (3.7–22 kW) | 0.005 | no: energy is capped at the point's power per request |
| UTC offset at issue | ≤ 0.03 | yes, for March and October |
| Month | 0.09–0.17 | yes, 12 |
| Weekday | 0.08–0.20 | yes, 7 |
| Attempted arrivals per day | 0.13–0.29 | yes, 10 log-spaced bins from 0.35 to 10 |
| Land-use mixture, fast point | 0.07–0.21 | yes: generic profile plus 3 atlas clusters; regular/fast |
| Variation between points | SD 0.33 | many trajectories per cell |

`scripts/build_cpft_library.py` runs the checkpoints once per model or prior
version over synthetic histories for every combination. CPFT outcomes are
nearly all-or-nothing: a point is typically forecast occupied for all or none
of the 30 hours, so occupied hours have an SD of about 15 h within a cell. A
cell's mean is therefore known to about 15 h/√K for K trajectories, and every
point using that cell on a day shares this error. The build spends trajectories
where points fall: 160 per cell for the generic profile (about 98% of points)
at 1–4.5 attempted arrivals per day, 48 at its other volumes, and 12 for the
atlas mixture clusters. The output is `backend/data/cpft_library.npz`. Each entry stores its own history around the
18:00 issue and its 31-hour recursive forecast. The build uses batched feature
construction that tests show reproduces the row-by-row reference and its
recursive forecasts.

Per request, `backend/cpft_library.py` picks one entry per point and day with a
counter-based random number and maps it onto the date. Occupied hours become
sessions, and energy is capped by the point's power. A volume between two bins
picks either neighbour with log-linear odds. Day effects enter the same way: the
day's demand factor scales the volume before the bin is chosen, a holiday uses
the Sunday calendar context, and energy follows the day's temperature
({doc}`calendar-effects`). There is no model call, so 5,000 points take about 40 ms.

The entries are real CPFT outputs. The library's approximations are its cells:
the nearest mixture cluster, the neighbouring volume bins, a representative
regular (11 kW) or fast (50 kW) point for the history, and the representative
mid-month date of each calendar context. The library records the SHA-256 of its
inputs (checkpoints, preprocessing, priors, world version). If any of them
change, CPFT requests return an explicit error asking for a rebuild.

## Speed and fidelity

Measured with `scripts/benchmark_on_the_fly.py` against the previous design (revision
`9ef972c`), in process, excluding imports and model/library loading. "Cold" is a
day the daily job had not prepared (a new date, seed or demand level); "warm" was
served from the prepared cache. On-request generation is faster than both:

| Case | Before, cold | Before, warm | On request |
|---|---:|---:|---:|
| Load profile, spatial, 1,000 points | 8.4 s | 102 ms | 54 ms |
| Load profile, CPFT, 64 points | 6.1 s | 11 ms | 3 ms |
| Basic KPIs, spatial, 500 points × 7 days | 29.7 s | 510 ms | 53 ms |
| Environment KPIs, 500 points × 7 days | 29.4 s | 588 ms | 66 ms |
| Basic KPIs, CPFT, 64 points × 3 days | 18.2 s | 33 ms | 11 ms |

On-request timings include the calendar, weather and demand effects.

Full results are in `reports/on_the_fly_speed.md`. `scripts/validate_cpft_library.py`
compares library samples with exact checkpoint runs on each point's own history,
profile and power (`reports/cpft_library_validation.md`). Its standard error
includes the finite trajectories of each cell, which all points using that cell
share. On 12 random dates, 300 points each (60% in the Amsterdam atlas), every
date agrees within 1.3 standard errors (chi-square 7.2 on 12 degrees of freedom,
p = 0.85). On average the library gives 14.7 occupied hours per point against
15.1 for exact runs (−3%, within its error, but negative on 9 of 12 dates). Per
date, the library's error is about ±1.2 h (8%); it is smaller for generic points
(160 trajectories per core cell) than for atlas points (12 per cell).

## What still needs occasional action

- **Rebuild the CPFT library** after changing the checkpoints, preprocessing,
  session priors, sampler version or timezone (about 100 minutes on 16 cores, offline).
- **Recalibrate the day effects** if better data become available:
  `scripts/calibrate_calendar_effects.py` ({doc}`calendar-effects`).
- **Import new grid observations** when a new free hourly dataset becomes
  available: `scripts/prepare_grid_data.py --csv FILE`. Requests use them
  immediately; nothing is pre-resolved.
- **Refresh charging-point infrastructure** with `scripts/update_charger_data.py`
  when the open-data sources publish (monthly). This is static infrastructure,
  not demand data.
