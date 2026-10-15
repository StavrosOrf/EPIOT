# Flexibility

The **Flexibility** tab shows what the EV fleet in each area can do **while every vehicle still
receives its energy**: the energy-feasible envelope (a *polytope*) around the schedule produced by
the area's charging strategy. It uses the same sessions, date and strategy as the load profiles.

Flexibility is what a charge point operator or aggregator can offer to the grid, for example for
congestion management or balancing: the schedule can move anywhere inside the envelope without
leaving any vehicle short of energy.

## Reading the chart

Each area card shows two panels side by side:

| Element | Meaning |
|---|---|
| **Power (kW)** | The minimum and maximum feasible power per step (blue band, dotted lower edge) around the scheduled load (black line). |
| **Cumulative energy (kWh)** | The minimum and maximum cumulative energy that can have been delivered by each step, around the scheduled cumulative energy. |
| **Orange and blue bands** | The previous day and the target day, each labelled with its weekday and date; weekend days are in bold. |
| **Area card** | One card per area; the left rail names it, gives its size and holds its strategy, date and demand scenario. |

The distance from the schedule to the upper edge is how much extra energy could have been delivered
by then; to the lower edge, how much could be postponed. The power axis is shared across areas, so
envelopes can be compared. The view needs a scenario session source (simple, spatial or CPFT).
Details: {doc}`../concepts/flexibility`.

## Upward and downward flexibility

Besides the envelope, EPIOT computes the *headroom* of the schedule at every step: how much power the
vehicles could add (upward) or shed (downward). These two series are not plotted any more, but they
are exported in the Excel report ({doc}`reports`). They follow directly from the charging strategy.
The figure below shows them for a single 22 kWh session on an 11 kW charger, plugged in from 08:00
to 17:00:

```{figure} ../_static/figures/strategy-flexibility.svg
:class: chart
:alt: Load, upward and downward flexibility for one session under three strategies

Flexibility signals for one session. The dashed line is the scheduled load; the grey band is the plug-in window.
```

| Strategy | Upward flexibility | Downward flexibility |
|---|---|---|
| **As Fast As Possible** | None: the vehicle already charges at full power. | The charging block, placed at the end of the plug-in window: the load that could still be postponed. |
| **As Late As Possible** | A single step just before charging starts: the headroom at the last point where charging could still begin. | The scheduled charging block itself. |
| **Average Power** | Half the rated power, for as long as the vehicle charges. | Half the rated power, for as long as the vehicle charges. |
| **Min. Charging Cost** | Rated power × plugged-in indicator − scheduled load. | Minus the scheduled load. |

The precise definitions are in {doc}`../concepts/flexibility`.

:::{tip}
To compare strategies, duplicate an area and give the copy another **Charging strategy** on its card;
only that card recalculates. The strategy and target date are set per area card.
:::
