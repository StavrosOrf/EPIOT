# Session sources

EPIOT has no live charging data. Every session it analyses is a **synthetic scenario**, generated
when a request arrives, for any past or future date. The **session source** selects how sessions
are generated and applies to {doc}`load-profiles`, {doc}`flexibility` and {doc}`kpis`.

| Source | Basis | Varies with |
|---|---|---|
| **Simple** | Bundled public arrival, connection-time and energy distributions | Charger power and type |
| **Spatial** | The same distributions, reweighted by the neighbourhood around each charger | Land use and density (Amsterdam atlas) |
| **CPFT** | When points are occupied, from the CPFT neural-network checkpoints run on synthetic histories; the connections inside from the same priors | Calendar, land use and arrival volume |

Nothing is prepared in advance: there is no scheduled job, scenario cache or TensorFlow in the web
process.

## How each source works

### Simple

Arrival times, connection durations and energy per session are drawn from the public
distributions in `seed_data/distribution-*.csv`, separately for weekdays and weekends. A point
receives 2 attempted arrivals per day at base demand. Stays at fast (DC) chargers are shortened
by 40 %.

```{figure} _static/figures/session-priors.svg
:class: chart
:alt: Arrival time, connection time and energy per session priors

The bundled priors: arrival time, and the share of sessions exceeding a connection time and an
energy.
```

### Spatial

Each charger is matched to its 2022 CBS neighbourhood. Housing, population and business
densities set the weights of four profiles and an arrival multiplier (0.6 to 2.2):

| Profile | Effect |
|---|---|
| Residential | Adds an evening arrival component; stays are 1.4 × longer |
| Workplace | Uses the workplace distributions |
| Retail | Adds a daytime arrival component; stays are 0.4 × as long, energy 0.75 × |
| Mixed | Generic public profile |

Chargers outside the atlas, or with missing neighbourhood data, use the generic profile; the
response reports the matched and fallback counts. The coefficients are stated assumptions, not
fitted values.

```{figure} _static/figures/spatial-archetypes.svg
:class: chart
:alt: Weekday arrival profiles of the four neighbourhood types and their duration and energy scales

The four profiles: weekday arrival times, and the scale of stay duration and energy against the
public prior.
```

### CPFT

The CPFT checkpoints (`best_availability.keras`, `best_kwh.keras`) forecast hourly occupancy from
14 days of spatially generated history, issued at 18:00 local time on the previous day. CPFT
decides **when a point is occupied**; the connections inside an occupied stretch come from the same
priors as the other sources:

- A stretch that begins at the issue time continues the connection the history shows at that
  moment, with its own energy, instead of starting a new one at 18:00. Other stretches start
  somewhere inside their first hour.
- Hourly occupancy cannot tell one long stay from several in a row, and the recursive forecast
  often holds a point occupied for the whole horizon. A stretch is therefore covered by
  back-to-back connections whose lengths follow the duration prior and whose energy follows the
  energy prior for that length, capped by the charger's power.
- The checkpoint's own hourly kWh is not used. It is an expected value that sits far below what a
  session delivers.

The checkpoints are run once per model version and stored as a library of trajectories
(`backend/data/cpft_library.npz`); a request samples from it, so no model runs at request time.
CPFT is a research tool of the University of Salford (Apache 2.0). An earlier evaluation of the
checkpoints found poor next-day performance, and this integration does not establish local
forecasting accuracy.

### Comparing the sources

```{figure} _static/figures/source-comparison.svg
:class: chart
:alt: The same 120 chargers on the same day under the Simple, Spatial and CPFT sources

The same 120 central Amsterdam chargers on the same day. Each panel has its own scale.
```

Simple and Spatial describe both days with the same sampler. CPFT differs in two ways that
show in the chart:

- **The window joins two things.** The previous day is the synthetic history up to the 18:00
  issue time, and the forecast takes over from there.
- **Occupancy is persistent.** The checkpoints keep a point occupied for hours on end, so a CPFT day
  tends to carry more energy than the samplers: for these chargers on five October days between
  12 % below and 49 % above Spatial.

## Demand scenario

The **demand scenario** scales attempted arrivals by 0.5 (low), 1 (base) or 1.5 (high). It is a
sensitivity assumption, not a confidence interval. Sessions cannot overlap on a point, so the
realised session count is lower than the attempted count. The three scenarios share their random
numbers and differ only in demand.

## Day effects

Independent per-point randomness averages out over an area, so all three sources apply effects
that are shared by every point in a country:

| Effect | Applied to |
|---|---|
| Season and day of week | Arrival volume |
| Public holidays and bridge days | Arrival pattern and volume (Sunday-like) |
| Common demand shock | Arrival volume; busy and quiet spells last a few days |
| Synthetic daily temperature | Energy per session, higher on cold and hot days |

Parameters are calibrated on ElaadNL 2019 open data and KNMI/ERA5 temperatures
(`backend/data/calendar_effects.json`). Holidays and climate follow each point's country; points
without one use the Netherlands. Hover over a date field to see the effects of that day.
`FLASK_SESSION_CALENDAR_EFFECTS=false` disables them.

```{figure} _static/figures/day-effects.svg
:class: chart
:alt: Volume factor and temperature of five weeks, and the sessions per day they produce at three demand levels

Five weeks around the turn of the year. The top panel shows the day effects for the Netherlands;
the bottom panel the sessions generated by the Simple source at each demand level.
```

Holidays and weekends lower the volume, the common shock moves several consecutive days together,
and the three demand levels keep the same shape and differ only in level.

## Guarantees

- **Deterministic.** Point IDs, date, source, demand scenario and seed always produce the same
  sessions. The interface uses seed 42.
- **Window-independent.** A day looks the same in a load profile and inside any KPI range, so a
  range equals the sum of its days.
- **Physically consistent.** Sessions on a point never overlap, last 15 minutes to 72 hours, cross
  midnight without restarting, and satisfy `energy ≤ power × connected hours`. Unknown power
  defaults to 11 kW.
- **Daylight saving aware.** Local days of 23 and 25 hours are handled exactly.

## Request parameters

| Parameter | Values | Default |
|---|---|---|
| `session_source` | `simple`, `spatial`, `cpft` | Omitted: stored Amsterdam pilot sessions (legacy) |
| `demand_assumption` | `low`, `base`, `high` | `base` |
| `seed` | Integer, 0 to 4,294,967,295 | `42` |

Responses describe the scenario in a `source` object: `label`, `synthetic`, `assumption`, `seed`,
`point_count`, `spatial_matched_points`, `spatial_fallback_points`, `session_count` and a
per-day `calendar` summary (day type, holiday, volume factor, temperature, energy factor).

## Rebuild the CPFT library

The library records the checksum of its inputs: the checkpoints, `cpft_preprocessing.json`, the
session priors in `seed_data/` and the sampler version. If any change, or the time zone changes,
CPFT requests fail with `503` instead of falling back to random data. Rebuild it:

```bash
uv sync --locked --extra cpft
uv run --extra cpft python scripts/build_cpft_library.py
```

This takes about 100 minutes on 16 cores and writes a 15 MB file. TensorFlow is needed only here.

## Limitations

- Scenarios are not calibrated to local charging observations; demand levels are assumptions.
- The spatial atlas covers Amsterdam only; other locations fall back to the generic profile.
- No private home charger is modelled.
- *Min. Charging Cost* requires the DRIVE2X ReFlex service ({doc}`load-profiles`).
