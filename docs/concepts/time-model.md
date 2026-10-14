# Time model

Every load and flexibility profile in EPIOT lives on the same discrete time grid. Understanding it
makes the charts, the API responses and the Excel export straightforward to interpret.

## The 48-hour window

When you analyse a date $D$, EPIOT computes a profile over **two consecutive days**, $D-1$ and $D$,
at a resolution of $\Delta t = 10$ minutes:

$$
T = 2 \times 24 \times 6 = 288 \text{ steps}, \qquad \Delta t = \tfrac{1}{6}\,\text{h}.
$$

```{figure} ../_static/figures/time-grid.svg
:class: chart
:alt: Two-day time grid with 288 ten-minute steps

Steps 0–143 cover the day before the selected date ("Yesterday"); steps 144–287 cover the selected date ("Today").
```

Profile values are **average power in kW** over each step. The energy of a profile is therefore

$$
E = \sum_{t=0}^{287} p_t \,\Delta t = \frac{1}{6}\sum_{t=0}^{287} p_t \quad [\text{kWh}].
$$

## Mapping a session onto the grid

A charging session has an arrival time, a departure time and an energy demand. Its arrival and
departure are converted into step indices relative to the start of day $D-1$:

$$
s = \left\lfloor 6\,h + \frac{m}{10} \right\rfloor + 144\cdot\mathbb{1}[\text{session starts on day } D],
$$

where $h$ and $m$ are the hour and minute of the timestamp. Both the arrival step $s_a$ and the
departure step $s_d$ use the **arrival day** for the 144-step offset.

## Which sessions are included

For a selected date $D$, the backend loads the sessions of the selected charging points that either

- **start on day $D$**, or
- **end on day $D-1$**,

and the simulators keep only those whose start date falls inside $[D-1, D]$.

```{mermaid}
gantt
    title Session selection for D = 15 Oct (window 14–15 Oct)
    dateFormat  YYYY-MM-DD HH:mm
    axisFormat  %d %H:%M
    section Included
    Starts and ends on D-1           :done, a1, 2025-10-14 08:00, 2025-10-14 17:00
    Starts and ends on D             :done, a2, 2025-10-15 07:30, 2025-10-15 12:00
    section Not counted
    Starts D-1, ends D (overnight)   :crit, b1, 2025-10-14 21:00, 2025-10-15 07:00
    Starts D, ends D+1 (overnight)   :crit, b2, 2025-10-15 22:00, 2025-10-16 06:00
```

:::{admonition} Sessions that cross midnight
:class: warning

Because the departure step is computed with the arrival day's offset, a session that ends on the
day after it starts gets a departure step *before* its arrival step and contributes no load. Sessions
that start on $D-1$ and end on $D$ are also not loaded by the session query. Overnight charging is
therefore under-represented, which shows as profiles dropping towards zero late in the evening.
See {doc}`../reference/known-limitations`.
:::

## Other time grids in EPIOT

| Where | Resolution | Length | Used for |
|---|---|---|---|
| Load and flexibility profiles | 10 min | 288 steps (2 days) | Charts, API, Excel `Load Data` |
| Day-ahead prices (`ocost`) | hourly prices, forward-filled to 10 min | 288 steps | ReFlex price signal |
| Power mix (environment KPIs) | 1 h | 48 values per 2-day block | CO₂ and renewable weighting |
| Availability KPIs | 30 min | 48 slots per day | City dashboard |
| Session generator (Monte Carlo) | 15 min | 96 steps per day | Arrival sampling |
