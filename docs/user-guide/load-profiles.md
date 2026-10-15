# Load profiles

The **Load profiles** tab shows the aggregated EV charging power of each area over a 48-hour window:
the selected day and the day before. It is the default tab when the analysis panel opens.

```{figure} ../_static/screenshots/load-profiles.jpg
:class: screenshot
:alt: Load profiles for two areas with yesterday in green and today in blue

Load profiles for 15 October 2025 under *As Fast As Possible*. One card per area; the screenshot predates the card layout.
```

## Reading the chart

| Element | Meaning |
|---|---|
| **Area card** | One card per area. Its left rail names the area, gives its size (`k chargers`) and holds the area's strategy, date and demand scenario. It also renames, moves, copies and removes the area ({doc}`interface`). |
| **Orange line and band** | *Previous day*: the day before the selected date (steps 0–143), labelled with its weekday and date. |
| **Blue line and band** | *Target day*: the selected date (steps 144–287), labelled with its weekday and date. Weekend days (Sat, Sun) are in bold. |
| **y-axis** | Aggregated charging power in kW. All cards share the same y-range, so areas are directly comparable. |
| **x-axis** | Time in UTC at 10-minute resolution. Values are drawn as steps: each value holds for its 10-minute interval. |
| **Hover** | A unified tooltip shows the values of all traces at the hovered time, with the weekday. |

The total energy in a profile is the sum of all values divided by six (kW × 1/6 h per step). See
{doc}`../concepts/time-model` for the exact time grid.

## Controls

Each profile aggregates the **charging points located inside** its area, so it describes demand at
a site, street or neighbourhood level.

### Charging strategy

Each area card has its own **Charging strategy** menu (default *As Fast As Possible*). The strategy
decides *when* within each plug-in window the energy is delivered. The same sessions, and therefore
the same total energy demand, produce very different load shapes, so duplicating an area and giving
the copy another strategy is the quickest way to compare two:

| Strategy | Option label | Behaviour | Runs |
|---|---|---|---|
| `afap` | As Fast As Possible | Full rated power from arrival until the energy is delivered. Uncontrolled charging. | Locally |
| `alap` | As Late As Possible | Full rated power, scheduled to finish at departure. | Locally |
| `avg` | Average Power | Half the rated power from arrival. | Locally |
| `ocost` | Min. Charging Cost | Cost-optimal schedule against day-ahead prices, computed by the ReFlex optimiser. | ReFlex service |

```{figure} ../_static/screenshots/load-profiles-alap.jpg
:class: screenshot
:alt: Load profiles under the As Late As Possible strategy

The same areas and day under *As Late As Possible*: load shifts towards departure times.
```

```{figure} ../_static/figures/district-strategies.svg
:class: chart
:alt: Three strategies compared for 100 charging points in central Amsterdam

The three local strategies compared on real sessions for 100 charging points in central Amsterdam. *As Late As Possible* moves the morning peak into the evening; *Average Power* flattens it.
```

The algorithms are specified in {doc}`../concepts/charging-strategies`.

### Date

Each area card has its own **Target date**; pick any day. The chart covers that day and the previous
one. Areas can therefore show different days side by side, and hovering the date shows the calendar
and weather effects applied to it.

## What happens when you click Analyse

```{mermaid}
sequenceDiagram
    autonumber
    actor U as User
    participant FE as Browser (script.js)
    participant ST as /stations/*
    U->>FE: Analyse / change a control
    par for every area
        FE->>ST: POST /stations/within
        ST-->>FE: charging points inside
    end
    loop for every area
        FE->>ST: GET /stations/aggregate_load
        ST-->>FE: 288-step profiles
    end
    FE->>FE: draw Yesterday / Today subplots
```

If the backend cannot compute an area, the chart is replaced by *"Load profiles are not available for
this selection"* naming the failing areas, with a hint to try another date or strategy.
