# Flexibility

Flexibility is how far an area's charging can deviate from its schedule while every vehicle still
receives its energy before it leaves. EPIOT reports it as a **feasible envelope**, which is
plotted, and as **headroom signals**, which are available through the API and the Excel report.
Both use the same sessions, date and strategy as the {doc}`load profile <load-profiles>`. The
envelope needs a scenario {doc}`session source <session-sources>` (Simple, Spatial or CPFT).

## Feasible envelope

Each connection may follow any schedule $x_i$ that respects the plug and delivers its energy:

$$
0 \le x_{i,t} \le u_{i,t}, \qquad \underline{E}_i \le \sum_t x_{i,t} \le \overline{E}_i ,
$$

where $u_{i,t}$ is the energy the charger can deliver in step $t$ while the vehicle is connected.
A connection that crosses the window edge only has to deliver what does not fit outside it, so
$\underline{E}_i = \max(0,\, E_i - \text{capacity outside})$ and
$\overline{E}_i = \min(E_i,\, \text{capacity inside})$.

The flexibility of an area is the sum of these sets over its connections. Each set is a
generalised polymatroid (Mukhi & Abate, 2023; Mukhi, Loho & Abate, 2025), so the sum is exact and
needs no optimisation: for any set of steps $A$, the fleet can deliver at most
$\sum_i \min(\overline{E}_i, u_i(A))$ and at least $\sum_i \max(0, \underline{E}_i - u_i(\bar A))$.

### Reading the chart

```{figure} _static/screenshots/panel-flexibility.jpg
:class: screenshot
:alt: Feasible envelopes of three areas

The Flexibility tab for the three areas of the load-profile example.
```

Each area card has two panels with the same time axis as the load profile:

| Panel | Band | Line |
|---|---|---|
| **Power (kW)** | Least power that must run and most power that can run in each step | Scheduled load |
| **Cumulative energy (kWh)** | Least and most energy that can have been delivered by each step | Scheduled cumulative energy |

The distance from the schedule to the upper edge is how much more could have been delivered by
that time; to the lower edge, how much could have been postponed. All area cards share one power
scale.

| Question | Read |
|---|---|
| How much load could the area shed at 18:00? | Scheduled power minus the lower edge at 18:00 |
| How much could it absorb at noon, for example to use solar surplus? | Upper edge at noon minus scheduled power |
| Is the schedule itself feasible? | `schedule_feasible` in the API |

```{figure} _static/figures/flexibility-envelope.svg
:class: chart
:alt: Power and cumulative energy envelope of 60 chargers with the absorb and shed margins marked at 18:00

The envelope of 60 chargers under As Fast As Possible. At 18:00 on the target day the fleet could
absorb the distance up to the upper edge and shed the distance down to the lower edge.
```

The per-step bounds are individually attainable. Using flexibility in one step changes what is left
to charge later, which the cumulative band captures. Vehicle-to-grid, state of charge limits and
network constraints are not modelled.

## Headroom signals

Relative to the selected schedule $p^{\text{sel}}$, each response carries two power signals in kW:

$$
f^{\uparrow}_t = \max\!\big(p^{\text{afap}}_t - p^{\text{sel}}_t,\, 0\big), \qquad
f^{\downarrow}_t = \min\!\big(p^{\text{alap}}_t - p^{\text{sel}}_t,\, 0\big).
$$

Upward flexibility is the extra power the fleet would draw if it charged as early as possible;
downward flexibility is the power it could shed by deferring charging as late as possible. For a
22 kWh session on an 11 kW charger plugged in from 08:00 to 17:00:

| Strategy | Upward | Downward |
|---|---|---|
| As Fast As Possible | 0 | −11 kW, 08:00 – 10:00 |
| As Late As Possible | +11 kW, 08:00 – 10:00 | 0 |
| Average Power | +8.6 kW, 08:00 – 10:00 | −2.4 kW, 08:00 – 15:00 |

```{figure} _static/figures/flexibility-headroom.svg
:class: chart
:alt: Scheduled load and the upward and downward headroom for one session under three strategies

The headroom signals of the same session under three strategies.
```

For *Min. Charging Cost*, upward flexibility is rated power while plugged in minus the scheduled
load, and downward flexibility is the negative of the scheduled load. For *Min. Cost with V2G*,
downward flexibility also includes the discharge power while plugged in.

These signals are indicative differences between feasible schedules. They ignore the energy
consequences of using them and are not a firm capacity commitment.

## API

The fields are part of the `/stations/aggregate_load` response ({doc}`load-profiles`):

| Field | Unit | Description |
|---|---|---|
| `up_flex`, `down_flex` | kW | Headroom signals per step (≥ 0 and ≤ 0) |
| `flex_polytope.power_min_kw`, `power_max_kw` | kW | Least and most power in each step |
| `flex_polytope.cumulative_min_kwh`, `cumulative_max_kwh` | kWh | Least and most energy delivered by each step |
| `flex_polytope.total_min_kwh`, `total_max_kwh` | kWh | Energy range inside the window |
| `flex_polytope.schedule_feasible` | – | The selected schedule lies inside the envelope |

The Excel **Load Data** sheet contains the headroom signals; the envelope is not exported.
