# Glossary

Aggregated load
: The sum of the charging power of all sessions of a set of charging points at each time step, in kW.

Area
: A polygon or rectangle drawn on the map; the unit of comparison in every chart. Up to three per analysis.

Availability (City KPI)
: A relative index of how many chargers are free at a time of day, derived from summed occupancy.

Charging point (CP)
: One connector at which one vehicle can charge. The unit EPIOT simulates and reports on.

Column
: A physical charging station (pole or cabinet) holding one or more charging points.

CPO
: Charge point operator: the company that runs charging stations.

Downward flexibility
: Power by which connected vehicles could reduce their charging at a time step (≤ 0).

DSO
: Distribution system operator: the company that runs the local electricity grid (in Amsterdam, Liander).

Grid view
: Load-profile mode that aggregates the charging points connected to the MV/LV transformers inside an area.

MV/LV transformer
: A medium-voltage to low-voltage installation feeding a neighbourhood's low-voltage network. Stored with `type = Middle`.

Occupancy ratio
: Share of time a charging point has a vehicle connected over the selected range.

Power mix
: The composition of electricity consumption by source, with its carbon intensity and renewable share.

ReFlex
: HESI's flexibility-optimisation service, used by the cost-optimal strategy.

Session
: One vehicle's visit to a charging point: arrival, departure and energy charged.

Step
: One 10-minute interval of a profile. A profile has 288 steps covering two days.

Strategy
: The rule that decides when a session's energy is delivered within its plug-in window (`afap`, `alap`, `avg`, `ocost`).

Upward flexibility
: Additional power connected vehicles could draw at a time step (≥ 0).

V2X
: Vehicle-to-everything: bidirectional charging in which vehicles can also feed energy back.

Window
: The two days, $D-1$ and $D$, covered by a load or flexibility profile for selected date $D$.
