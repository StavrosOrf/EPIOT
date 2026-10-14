# Charging-session data

Everything EPIOT computes starts from **charging sessions**: one row per vehicle visit with a charging
point, an arrival time, a departure time and the energy charged.

| Column | Type | Meaning |
|---|---|---|
| `cp_id` | int | Charging point (foreign key to `charging_points.id`) |
| `start` | datetime | Arrival / plug-in time |
| `end` | datetime | Departure / plug-out time |
| `consumption` | float | Energy charged in kWh |

The interactive app generates its sessions **on request** from the selected session source
(simple, spatial or CPFT); see {doc}`on-request-scenarios`. This page describes the older
**stored sessions** in the `sessions` table, which API calls without a `session_source` still
read. They were produced ahead of time by a daily batch job that has been removed, since EPIOT
receives no live data.

```{mermaid}
flowchart LR
    subgraph Inputs
      CP[(Charging points<br/>in NL bounding polygon)]
      CSV[[Empirical distributions<br/>arrival · connection time · energy]]
      CFG[[backend/config.yaml<br/>session counts · gamma energy]]
    end
    subgraph Generators["load_daily_charging_sessions(method=…)"]
      MC["MC — EV2Gym-style<br/>Monte Carlo (active)"]
      ML["ML — placeholder<br/>(random sequences)"]
      G["Gamma sampler<br/>(alternative function)"]
    end
    CP --> MC & ML & G
    CSV --> MC
    CFG --> G
    MC & ML & G --> DB[(sessions table)]
    DB --> APP[Web app:<br/>load · flexibility · KPIs]
```

## Monte Carlo generator (EV2Gym-style)

`sample_charging_sessions_ev2gym` in `backend/charge_sessions.py` is the generator used by the daily
update job (`method="MC"`). It reproduces the arrival-driven spawning approach of the
[EV2Gym](https://github.com/StavrosOrf/EV2Gym) simulator.

```{figure} ../_static/figures/ev2gym-inputs.svg
:class: chart
:alt: Arrival mass, connection-time and energy-demand curves

Empirical inputs of the generator (public chargers): arrival mass per 15 minutes for weekdays and weekends, and the inverse cumulative curves for connection time and energy demand.
```

For one day and each charging point:

1. **Time grid.** The day is split into 15-minute steps (96 per day).
2. **Arrival probability.** The arrival curve for the day type (weekday or weekend) is normalised to a
   probability mass $m_k$ over the steps and scaled by the target number of sessions per charger,
   $p_k = N \cdot m_k$ (the former daily job used $N = 2$).
3. **Existing sessions.** Sessions already in the database that overlap the day are loaded; a charger
   that is still occupied at midnight only becomes eligible once it is free. (Later existing sessions
   on the same day are not checked, so each day should be generated only once.)
4. **Spawning.** At each step, for every free charger, a session is spawned when $u < 2\,p_k$ with
   $u \sim \mathcal{U}(0, 1)$.
5. **Connection time.** Drawn by inverse-transform sampling from the connection-time curve,
   multiplied by 0.6 for fast chargers, floored at one step, then stretched by a stay factor of 1.2.
6. **Energy.** Drawn from the energy-demand curve (at least 0.1 kWh) and capped at
   $P \times \text{connection hours}$ so that it is physically deliverable.
7. **Occupancy.** The charger is marked busy until the session ends, so sessions on one charger never
   overlap.

```{mermaid}
flowchart TD
    A[Step k of the day] --> B{Charger free?}
    B -- no --> N[Next charger]
    B -- yes --> C["u ~ U(0,1)"]
    C --> D{"u < 2·p_k ?"}
    D -- no --> N
    D -- yes --> E[Sample connection time<br/>× type scale × 1.2]
    E --> F[Sample energy,<br/>cap at P × hours]
    F --> G[Create session,<br/>charger busy until end]
    G --> N
    N --> A
```

The empirical curves are read from four CSV files in `./seed_data` (or `./backend/data`):

| File | Columns | Shape |
|---|---|---|
| `distribution-of-arrival.csv` | `Arrival time`, `private`, `public`, `workplace` | Relative arrival frequency per 15 min, weekdays |
| `distribution-of-arrival-weekend.csv` | `Arrival time`, `private`, `public` | Same, weekends |
| `distribution-of-connection-time.csv` | `Percentage of charging events`, site types | Hours exceeded by x % of events |
| `distribution-of-energy-demand.csv` | `Percentage of charging events`, site types | kWh exceeded by x % of events |

All charging points are currently mapped to the `public` site type.

### What the stored sessions look like

```{figure} ../_static/figures/db-session-stats.svg
:class: chart
:alt: Histograms of arrival time, duration and energy of stored sessions

Distributions of the sessions stored in the local database for 8 September – 19 October 2025.
```

## Gamma sampler (configuration-driven)

`sample_charging_sessions` is a simpler alternative driven entirely by `backend/config.yaml`:

1. Draw the number of sessions for the charger from `session_probabilities`.
2. Draw that many sorted arrival times uniformly from the day's 10-minute steps, and for each a
   departure before the next arrival.
3. Draw the energy demand from a **gamma distribution** whose shape and scale depend on the day type
   and the arrival hour (`charging_demand_distributions.weekday_<0|1>_hour_<h>`).

```{figure} ../_static/figures/config-distributions.svg
:class: chart
:alt: Session count probabilities and gamma energy demand by hour

The parameters in `backend/config.yaml`, derived from ElaadNL historical data: the number of sessions per charger per day (left), and the gamma-distributed energy demand per arrival hour with its inter-quartile band (right).
```

This sampler is kept as a reference implementation and is not called by the application.

## Machine-learning prediction (in development)

`method="ML"` is reserved for learned session prediction. The current implementation is a
**placeholder**: `predict_charging_sessions` generates random occupancy sequences of 25–70 steps per
charger with energies drawn uniformly between 5 and 50 kWh. The LSTM scaffolding in `backend/ml`
(`DataScaler`, `PredictiveModel`, `Processing`) shows the intended interface. The trained
{doc}`../related-tools/cpft` models are integrated separately, as the CPFT session source
({doc}`on-request-scenarios`).

:::{warning}
Do not use sessions generated with `method="ML"` for analysis. Use the Monte Carlo generator until
the learned predictor is integrated.
:::

## Regenerating stored sessions

Stored sessions are no longer regenerated on a schedule ({doc}`../operations/scheduled-updates`).
To add days for testing the legacy path, call
`load_daily_charging_sessions(app, db, date, method="MC", scope="NL")` from
`backend/charge_sessions.py` once per day; generating a day twice adds a second set of sessions.
