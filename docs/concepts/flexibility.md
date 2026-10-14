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

## Interpreting aggregated flexibility

At area level, the signals answer practical questions:

| Question | Read |
|---|---|
| How much could the area reduce its EV load at 18:00? | $\lvert f^{\downarrow} \rvert$ at 18:00 |
| How much extra load could the area absorb at noon, e.g. to use solar surplus? | $f^{\uparrow}$ at 12:00 |
| Which strategy keeps the most headroom in both directions? | Compare tabs under *Average Power* versus the full-power strategies |

:::{note}
Flexibility in EPIOT is a **power** envelope per step. It does not track the energy consequences of
using it: activating upward flexibility at one step reduces what remains to be charged later. Treat
the signals as an indicator of instantaneous headroom, not as a dispatchable schedule.
:::
