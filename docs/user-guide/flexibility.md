# Flexibility

The **Flexibility** tab shows how much the EV fleet in each area could change its charging power at
any moment, given the charging strategy it follows. It uses the same sessions, date and strategy as
the load profiles.

- **Upward flexibility** (blue, positive): extra power the vehicles could draw on top of the
  scheduled load.
- **Downward flexibility** (red, negative): power by which the vehicles could reduce their load.

Flexibility is what a charge point operator or aggregator can offer to the grid, for example for
congestion management or balancing.

```{figure} ../_static/screenshots/flexibility-avg.jpg
:class: screenshot
:alt: Flexibility chart with blue upward and red downward areas

Flexibility under *Average Power* for 15 October 2025. Because each vehicle charges at half its rated power, it can go up or down by the same amount.
```

## Reading the chart

| Element | Meaning |
|---|---|
| **Subplot title** | `Aggregated EV Charging Flexibility: Area N (k chargers)` |
| **Blue area above zero** | Upward flexibility in kW |
| **Red area below zero** | Downward flexibility in kW (shown as negative values) |
| **Left half, grey** | Day before the selected date |
| **Right half** | Selected date |

The y-range is shared across areas and padded by 10 %.

## Flexibility depends on the strategy

The shape of the flexibility envelope follows directly from the charging strategy. The figure below
shows the signals EPIOT returns for a single 22 kWh session on an 11 kW charger, plugged in from
08:00 to 17:00:

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

```{figure} ../_static/screenshots/flexibility.jpg
:class: screenshot
:alt: Flexibility under As Fast As Possible showing only downward flexibility

Under *As Fast As Possible* there is no upward flexibility: every vehicle already charges at its maximum.
```

The precise definitions are in {doc}`../concepts/flexibility`.

:::{tip}
To compare strategies, keep the tab open and switch the **Charging strategy** drop-down; the chart
refreshes for the same areas and date.
:::
