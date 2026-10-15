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
| **Min. Charging Cost** (`ocost`) | The same problem with the day-ahead price $\pi_t$ in place of $\kappa_t$, solved by the DRIVE2X ReFlex optimiser |
| **Min. Cost with V2G** (`v2g`) | Charging $c_t \in [0, P]$ and discharging $d_t \in [0, P]$ that minimise $\int \pi_t\,(c_t - d_t)\,dt$, with net energy $E$ at departure, never more than $E$ and never less than $-D$ during the connection, solved by ReFlex |

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
| What could bidirectional vehicles earn or shift? | Min. Cost with V2G |

As Fast As Possible and As Late As Possible bracket every schedule that charges at full power, and
their difference is the basis of the headroom signals in {doc}`flexibility`.

## Requirements and limits

| Strategy | Session sources | Needs | Windows |
|---|---|---|---|
| As Fast, As Late, Average | All | Nothing external | Any, including daylight-saving changes |
| Min. Carbon Footprint | Simple, Spatial, CPFT | Grid carbon data for every candidate interval, observed or a labelled reference ({ref}`kpis:grid data`) | Any |
| Min. Charging Cost, Min. Cost with V2G | All | Energy-Charts day-ahead prices; the DRIVE2X ReFlex service in the background | Any |

- Min. Carbon Footprint is an estimate on historical or reference data, not demonstrated avoided
  emissions. It is unavailable, never replaced by another strategy, when carbon data are missing
  or a point has overlapping connections.
- The cost strategies never wait for ReFlex (see below). Until ReFlex has optimised a connection,
  it shows EPIOT's exact optimum, which ReFlex's plan later replaces.
- No strategy models network capacity or charging losses. Only *Min. Cost with V2G* discharges, and
  only as a scenario: no charger in the registers is known to be bidirectional.

## Cost optimisation with ReFlex

*Min. Charging Cost* and *Min. Cost with V2G* are optimised by the DRIVE2X ReFlex service
(OpenAPI 0.3.0) against the day-ahead price of each charger's bidding zone.

**Vehicle-to-grid assumptions.** Every connected vehicle is bidirectional at the plug's power. It
may be discharged by up to $D$ = 10 kWh below its arrival charge (`FLASK_REFLEX_V2G_DEPTH_KWH`) and
leaves with the same energy $E$ as under the other strategies. Negative load is energy returned to
the grid; the flexibility polytope describes one-way charging, so `schedule_feasible` is `null`.

**Plan store.** Without network constraints ReFlex optimises every charger independently, so the
plan of a connection depends only on its arrival, departure, energy and plug power, the strategy and
the prices while it is plugged in. Each connection is sent as a ReFlex charge point of its own, and
its plan is kept in `instance/reflex_plans.sqlite` under a key made of exactly those inputs. Any later
request containing the connection reads the plan instead of calling ReFlex: the same area again,
another area containing the charger, the neighbouring two-day window or another draw of an ensemble.
When prices are published for a day that used reference prices, the key changes and the connection
is optimised again.

**Requests never wait for ReFlex.** A connection without a stored plan gets EPIOT's exact optimum at
once (cheapest intervals first; for V2G one linear programme for all connections, about 0.2 s for
150), stored as provisional (`optimisation.reflex_pending`), and is queued for ReFlex in a
background thread. ReFlex's plan replaces it in the store, so the next request shows it; the
browser does not cache a response with pending connections. ReFlex is slow on the shared instance,
about 1 s per thousand one-way connections but some 3 s per V2G connection, which is why nothing
waits for it. If ReFlex fails, the provisional plans stay and are queued again after ten minutes.
`scripts/prepare_reflex_plans.py` waits for ReFlex instead, to fill the store ahead of time
({doc}`operations`).

**Prices.** Day-ahead prices come from Energy-Charts and are kept in
`instance/day_ahead_prices.sqlite`, so a known day is never fetched again. Quarter-hourly prices
are averaged exactly onto the 10-minute grid. A step without a published price takes the price at
the same time on the nearest day within a week that has one, or, further ahead, on the latest day with
prices; the response flags this (`optimisation.prices_use_reference`). Countries map to their bidding
zone; points without one (the United Kingdom, or no country) use the Dutch zone and are counted in
`optimisation.price_zone_stand_ins`.

**What EPIOT corrects.** ReFlex 0.3.0 was measured against the service in October 2026:

| ReFlex behaviour | What EPIOT does |
|---|---|
| Partly plugged 10-minute intervals are charged at full power | Only whole plugged-in intervals are sent; the remaining energy goes to the edge intervals, which also take charging from dearer intervals when they are cheaper |
| A one-way session's end time is inclusive, a V2X session's exclusive | The end time sent differs by mode |
| A one-interval session never finishes; several sessions on one charger are scheduled wrongly | Connections under two whole intervals are scheduled locally (cheapest first, optimal for them); every other one is its own charge point |
| V2X charges at most about 95 % of the plug's power and ends 1-3 % short; short one-way sessions on fast plugs get whole intervals at full power | The energy is adjusted to the exact amount in the cheapest (or dearest) intervals with room, within every limit (`optimisation.energy_adjusted`) |
| Anything else outside the plug or battery limits, or more than 25 % off the energy | The plan is replaced by EPIOT's exact local optimum, a linear programme for V2G (`optimisation.reflex_plans_replaced`) |

On test sessions the ReFlex plans cost 0-3 % more than the exact optimum.

`source.optimisation` in the response counts the connections taken from the store, optimised now,
adjusted, scheduled locally and replaced.
