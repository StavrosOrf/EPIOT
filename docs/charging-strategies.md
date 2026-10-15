# Charging strategies

A charging strategy decides *when* each connection draws its energy between arrival and departure.
Every area card has its own strategy, so the same sessions can be compared under different rules.
The strategy changes the shape of the load, never the energy a vehicle receives.

```{figure} _static/figures/strategies-single-session.svg
:class: chart
:alt: One 22 kWh session on an 11 kW charger under four strategies

One 22 kWh session on an 11 kW charger, plugged in from 08:00 to 17:00. The dashed line in the
last panel is an illustrative grid carbon intensity.
```

## Definitions

For a connection with arrival $a$, departure $d$ and rated power $P$ (11 kW if unknown), the
energy that is delivered is

$$
E = \min\big(E_{\text{requested}},\; P\,(d - a)\big),
$$

and $p_t$ is the charging power at time $t$:

| Strategy | Schedule |
|---|---|
| **As Fast As Possible** (`afap`) | $p_t = P$ from $a$ until $E$ is delivered |
| **As Late As Possible** (`alap`) | $p_t = P$ over the last $E/P$ hours before $d$ |
| **Average Power** (`avg`) | $p_t = E/(d-a)$ for the whole connection |
| **Min. Carbon Footprint** (`mincarbon`) | The $p_t \in [0, P]$ with $\int p_t\,dt = E$ that minimises $\int \kappa_t\,p_t\,dt$, where $\kappa_t$ is the grid carbon intensity. Charging may pause. |
| **Min. Charging Cost** (`ocost`) | The same problem with the day-ahead price $\pi_t$ in place of $\kappa_t$, solved by the ReFlex optimiser |

Schedules are integrated over fractional 10-minute intervals, so energy is conserved exactly,
including on days with 23 or 25 hours. The unit of a profile is kW per step; a step holds
$\tfrac{1}{6}$ kWh per kW.

## Window edges

A profile covers two local days. Each connection is followed from its true arrival to its true
departure, and the window only crops the result: a vehicle that arrived at 21:00 is charged from
21:00 and not again at midnight. Because the strategies place a crossing connection's energy
differently, the energy inside the window can differ slightly between strategies.

Min. Carbon Footprint chooses *where* to place energy, so a crossing connection contributes its
uniform-charging share inside the window instead.

```{figure} _static/figures/strategies-district.svg
:class: chart
:alt: Aggregated load of 120 chargers under four strategies

The strategies applied to 120 central Amsterdam chargers. Min. Carbon Footprint concentrates
charging in the hours with the lowest carbon intensity because no network constraint is modelled.
```

## Choosing a strategy

| Question | Strategy |
|---|---|
| What happens without any control? | As Fast As Possible, the baseline |
| How late can charging be pushed? | As Late As Possible, the opposite bound |
| What does a smoothed profile look like? | Average Power |
| When is the grid cleanest? | Min. Carbon Footprint |
| When is electricity cheapest? | Min. Charging Cost |

As Fast As Possible and As Late As Possible bracket every schedule that charges at full power, and
their difference is the basis of the headroom signals in {doc}`flexibility`.

## Requirements and limits

| Strategy | Session sources | Needs | Windows |
|---|---|---|---|
| As Fast, As Late, Average | All | Nothing external | Any, including daylight-saving changes |
| Min. Carbon Footprint | Simple, Spatial, CPFT | Grid carbon data for every candidate interval, observed or a labelled reference ({ref}`kpis:grid data`) | Any |
| Min. Charging Cost | All | The DRIVE2X ReFlex service and Energy-Charts day-ahead prices | Ordinary 48-hour windows only |

- Min. Carbon Footprint is an estimate on historical or reference data, not demonstrated avoided
  emissions. It is unavailable, never replaced by another strategy, when carbon data are missing
  or a point has overlapping connections.
- Min. Charging Cost blocks the request while ReFlex runs (up to two minutes) and cannot be
  combined with several draws. It returns an error on a daylight-saving window.
- No strategy models network capacity, charging losses or vehicle-to-grid operation.
