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
to charge later, which the cumulative band captures. Under *Min. Cost with V2G* the envelope is the
bidirectional one below. Network constraints are not modelled.

### Vehicle-to-grid

The envelope above assumes one-way charging, $x_{i,t} \ge 0$, and limits only the total energy. Under
*Min. Cost with V2G* a vehicle can also discharge, so it needs a battery limit at every step, not
only at departure. Its envelope is therefore computed with the model below (`backend/flex_v2g.py`;
`flex_polytope.model` is `bidirectional`).

**Model.** Let $S_{i,t} = \sum_{s \le t} x_{i,s}$ be the energy a connection has taken since arrival.
With $c_{i,t}$ and $d_{i,t}$ the energy the plug can charge and discharge in step $t$ while
connected, $D$ the discharge depth (10 kWh) and $E_i$ the energy it leaves with:

$$
-d_{i,t} \le x_{i,t} \le c_{i,t}, \qquad -D \le S_{i,t} \le E_i, \qquad S_{i,\text{departure}} = E_i .
$$

These are the limits the V2G strategy gives ReFlex.

**Aggregation stays exact.** Mukhi, Loho & Abate (2025, Lemma 1 and §II-D) show that a lossless device
with per-step power bounds of either sign and state-of-charge bounds at every step is still a
generalised polymatroid. The fleet's set is therefore again the sum of the connections' sets: every
bound of the area is the sum of the connections' bounds. This symmetry fails once charging losses
are modelled (their Remark 3), so it would then need inner approximations such as homothets or
virtual batteries (Nazir et al., 2018). The EPIOT and ReFlex models are lossless.

**Computation.** The general bound functions follow a recursion (their Corollary 1). EPIOT only needs
them on time intervals, where they have a closed form. The constraints are differences between
neighbouring $S_t$, so one forward and one backward pass give the exact range
$[L_{i,t}, H_{i,t}]$ of every $S_{i,t}$:

$$
H_t = \min\big(E_i,\; H_{t-1} + c_t,\; H_{t+1} + d_{t+1}\big), \qquad
L_t = \max\big(-D,\; L_{t-1} - d_t,\; L_{t+1} - c_{t+1}\big),
$$

where the forward terms are applied first and the backward terms second. The most and least energy
over steps $j{+}1 \dots k$ is then

$$
\max x_i(j,k] = \min\Big(\textstyle\sum_{t=j+1}^{k} c_{i,t},\; H_{i,k} - L_{i,j}\Big), \qquad
\min x_i(j,k] = \max\Big(-\textstyle\sum_{t=j+1}^{k} d_{i,t},\; L_{i,k} - H_{i,j}\Big),
$$

the shortest paths of the difference-constraint graph. Summed over connections, single steps give the
power band, whose lower edge is negative where vehicles can return energy. Intervals from the window
start give the cumulative band, and the last step gives the totals. A connection crossing the window
edge is modelled over its whole stay, and the window takes $S_k - S_{\text{window start}}$, so no edge
correction is needed. The cost is $O(N \cdot T)$ in the number of connections and steps per stay.

The step, prefix and interior-interval bounds are checked against linear programming at an absolute
tolerance of $10^{-7}$ kWh, including connections crossing the window edges. Without discharge
($d = 0$, $D = 0$) they reduce to the one-way envelope. These checks are in
`tests/test_flex_v2g.py`.

**In the response.** `schedule_feasible` is checked on every step, prefix and suffix, as for one-way
charging. This is a necessary envelope check; passing it does not prove that the complete aggregate
profile can be assigned to individual vehicles. The V2G headroom signals are the distance from the schedule to this band,
$f^{\uparrow}_t = \overline{p}_t - p^{\text{sel}}_t$ and $f^{\downarrow}_t = \underline{p}_t - p^{\text{sel}}_t$,
so they respect the battery limits as well as the plug.

**Limits.** The model is lossless. The state of charge is relative to arrival, because battery size and
arrival charge are unknown. Every vehicle is assumed bidirectional, and no network is modelled.

References: K. Mukhi, G. Loho, A. Abate, *Exact Characterization of Aggregate Flexibility via
Generalized Polymatroids*, IEEE Trans. Smart Grid (2026), [arXiv:2503.23458](https://arxiv.org/abs/2503.23458);
K. Mukhi, A. Abate, *Polymatroidal Representations of Aggregate EV Flexibility Considering Network
Constraints*, [arXiv:2509.16134](https://arxiv.org/abs/2509.16134) (limits itself to one-way charging
because the bidirectional bound functions are more complex); M. S. Nazir, I. Hiskens, A. Bernstein,
E. Dall'Anese, *Inner Approximation of Minkowski Sums*, [arXiv:1810.01587](https://arxiv.org/abs/1810.01587).

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
load, and downward flexibility is the negative of the scheduled load. For *Min. Cost with V2G*, both
are the distance to the bidirectional envelope (see Vehicle-to-grid above).

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
| `flex_polytope.schedule_feasible` | – | The selected schedule passes the step, prefix and suffix envelope checks (necessary for feasibility) |
| `flex_polytope.model` | – | `one-way`, or `bidirectional` under *Min. Cost with V2G* |

The Excel **Load Data** sheet contains the headroom signals; the envelope is not exported.
