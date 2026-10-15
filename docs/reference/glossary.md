# Glossary

Aggregated load
: The sum of the charging power of all sessions of a set of charging points at each time step, in kW.

Area
: A polygon or rectangle drawn on the map; the unit of comparison in every chart. Up to three per analysis.

Availability (City KPI)
: The average share of the selected chargers that are free in a half-hour of the day, counting a charger as occupied while a vehicle is connected.

Blocking probability (City KPI)
: The share of a half-hour in which every selected charger is occupied.

Charging point (CP)
: One connector at which one vehicle can charge. The unit EPIOT simulates and reports on.

Coincidence factor (Grid KPI)
: The peak of the uncontrolled load divided by the sum of the rated powers of the selected chargers; near 1 means the chargers all draw at once.

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

Idle time (User KPI)
: The part of a stay that is not needed to deliver the energy at the charger's rated power: the time charging can be moved within.

Load factor (Grid KPI)
: Mean uncontrolled load divided by its peak; near 1 is a flat load.

MV/LV transformer
: A medium-voltage to low-voltage installation feeding a neighbourhood's low-voltage network. Stored with `type = Middle`.

Occupancy ratio
: Share of time a charging point has a vehicle connected over the selected range.

Polytope flexibility
: The set of all charging schedules in which every session gets its energy within its plug-in window and power limit; for EVs it is a generalized polymatroid with a closed-form aggregate.

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

Utilisation (City KPI)
: Energy a charger delivered over the range divided by what it could deliver at its rated power in that time. Unlike occupancy, it ignores time a finished vehicle stays connected.

V2X
: Vehicle-to-everything: bidirectional charging in which vehicles can also feed energy back.

Window
: The two days, $D-1$ and $D$, covered by a load or flexibility profile for selected date $D$.
