# Flexibility model

**Flexibility** is the ability of the connected EV fleet to deviate from its scheduled load. EPIOT
reports it as two power signals on the same 288-step grid as the load:

- **Upward flexibility** $f^{\uparrow}_t \ge 0$: additional power the fleet could draw at step $t$.
- **Downward flexibility** $f^{\downarrow}_t \le 0$: power by which the fleet could reduce its load at step $t$.

Both are aggregated over all sessions of the selected charging points, exactly like the load.

```{mermaid}
flowchart TB
    subgraph Session["One session (P, E, s_a, s_d)"]
      direction LR
      W[Plug-in window<br/>s_a … s_d]
      B[Scheduled charging block]
    end
    Session --> U[Upward flexibility<br/>headroom above the schedule]
    Session --> D[Downward flexibility<br/>load that can be removed or postponed]
    U --> AG((Σ over sessions))
    D --> AG
    AG --> OUT[[up_flex, down_flex<br/>288 values each]]
```

## Definitions per strategy

With the notation of {doc}`charging-strategies` ($P$ rated power, $n$ charging steps, $s_a$ and $s_d$
arrival and departure steps, $r = (E \bmod P\Delta t)/6$ the remainder term):

::::{tab-set}

:::{tab-item} As Fast As Possible
$$
f^{\uparrow}_t = 0,
\qquad
f^{\downarrow}_t = -P \quad \text{for } s_d - n < t \le s_d .
$$

The vehicle already charges at full power, so it cannot go up. Its downward flexibility is the
charging block placed at the **end** of the window: the latest moment at which the same energy could
still be delivered, i.e. the load that could be postponed.
:::

:::{tab-item} As Late As Possible
$$
f^{\uparrow}_{s_d-n} = P - r,
\qquad
f^{\downarrow}_t = -P \quad \text{for } s_d - n < t \le s_d .
$$

Downward flexibility coincides with the scheduled block. Upward flexibility is a single step just
before charging starts: the headroom at the last moment charging could begin.
:::

:::{tab-item} Average Power
$$
f^{\uparrow}_t = +\tfrac{P}{2},
\qquad
f^{\downarrow}_t = -\tfrac{P}{2}
\qquad \text{for } s_a \le t < s_a + n .
$$

Charging at half power leaves symmetric headroom: the vehicle can go up to full power or down to zero
while it charges.
:::

:::{tab-item} Min. Charging Cost
$$
f^{\uparrow}_t = P\cdot a_t - p_t,
\qquad
f^{\downarrow}_t = -p_t ,
$$

where $a_t \in \{0, 1\}$ is 1 while the vehicle is plugged in and $p_t$ is the optimised schedule
returned by ReFlex. Any power between zero and the rated power is feasible while plugged in.
:::
::::

```{figure} ../_static/figures/strategy-flexibility.svg
:class: chart
:alt: Load, upward and downward flexibility for one session under three strategies

Flexibility signals of a single 22 kWh session on an 11 kW charger, plugged in from 08:00 to 17:00.
```

## Polytope flexibility

The per-step signals above ignore energy: using flexibility at one step changes what is left to
charge later. The **polytope** view keeps that coupling. Each connection $i$ may charge any
schedule $x_i$ with

$$
0 \le x_{i,t} \le u_{i,t}, \qquad \underline{E}_i \le \sum_t x_{i,t} \le \overline{E}_i ,
$$

where $u_{i,t}$ is the energy the plug can deliver in step $t$ while connected. A connection that
crosses the window edge only has to deliver the energy that does not fit outside the window, so
$\underline{E}_i = \max(0, E_i - \text{capacity outside})$ and
$\overline{E}_i = \min(E_i, \text{capacity inside})$. The area's flexibility is the Minkowski sum
of these sets.

Each set is a generalized polymatroid (Mukhi & Abate, 2023; Mukhi, Loho & Abate, 2025), so the sum is
exact and cheap: for any set of steps $A$, the fleet can deliver at most
$b(A)=\sum_i \min(\overline{E}_i, u_i(A))$ and at least
$p(A)=\sum_i \max(0, \underline{E}_i - u_i(\bar A))$. Evaluating a query is $O(N)$ in numpy; no
optimisation is needed.

EPIOT reports, for the selected schedule:

| Output | Meaning |
|---|---|
| `cumulative_min_kwh`, `cumulative_max_kwh` | Band of cumulative energy the fleet can have delivered by step $t$ ($p([0,t])$, $b([0,t])$) |
| `power_min_kw`, `power_max_kw` | Least power that must run, and most that can run, in step $t$ |
| `total_min_kwh`, `total_max_kwh` | Energy range delivered inside the window |
| `schedule_feasible` | Whether the selected schedule lies inside the polytope (prefix, per-step and total bounds) |

The module `backend/flex_polytope.py` also provides window queries: the energy a window can absorb
above, or shed below, a schedule (`window_flexibility`), and the largest uniform power reduction
sustained over a window (`max_sustained_reduction`, one exact LP). Vehicle-to-grid and minimum
state-of-charge limits are not modelled.

## Interpreting aggregated flexibility

At area level, the signals answer practical questions:

| Question | Read |
|---|---|
| How much could the area reduce its EV load at 18:00? | $\lvert f^{\downarrow} \rvert$ at 18:00 |
| How much extra load could the area absorb at noon, e.g. to use solar surplus? | $f^{\uparrow}$ at 12:00 |
| Which strategy keeps the most headroom in both directions? | Compare tabs under *Average Power* versus the full-power strategies |

:::{note}
The up/down signals are a **power** envelope per step. They do not track the energy consequences of
using it: activating upward flexibility at one step reduces what remains to be charged later. Treat
them as an indicator of instantaneous headroom, not as a dispatchable schedule. The
[polytope view](#polytope-flexibility) is the energy-consistent alternative.
:::
