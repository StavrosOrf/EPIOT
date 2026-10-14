# Load profiles

The **Load profiles** tab shows the aggregated EV charging power of each area over a 48-hour window:
the selected day and the day before. It is the default tab when the analysis panel opens.

```{figure} ../_static/screenshots/load-profiles.jpg
:class: screenshot
:alt: Load profiles for two areas with yesterday in green and today in blue

Load profiles for 15 October 2025 under *As Fast As Possible*. One subplot per area.
```

## Reading the chart

| Element | Meaning |
|---|---|
| **Subplot title** | `Aggregated EV Charging Load for: Area N (k chargers)` in Chargers view, or `… at MVLV Transformer for: Area N (k tr.)` in Grid view. |
| **Green line, grey background** | *Yesterday*: the day before the selected date (steps 0–143). |
| **Blue line** | *Today*: the selected date (steps 144–287). |
| **y-axis** | Aggregated charging power in kW. All subplots share the same y-range, so areas are directly comparable. |
| **x-axis** | Time at 10-minute resolution. Values are drawn as steps: each value holds for its 10-minute interval. |
| **Hover** | A unified tooltip shows the values of all traces at the hovered time. |

The total energy in a profile is the sum of all values divided by six (kW × 1/6 h per step). See
{doc}`../concepts/time-model` for the exact time grid.

## Controls

### View: Chargers or Grid

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} Chargers view
Aggregates the **charging points located inside** each area. Use it to understand demand at a site,
street or neighbourhood level.
:::

:::{grid-item-card} Grid view
Finds the **MV/LV transformers inside** each area and aggregates the charging points **connected to
those transformers**. Use it to see what the EV fleet adds to specific grid assets.
:::
::::

```{figure} ../_static/screenshots/load-profiles-grid.jpg
:class: screenshot
:alt: Load profiles in grid view, titled per MV/LV transformer

Grid view of the same areas: the titles now count transformers ("34 tr.") rather than chargers.
```

### Charging strategy

The strategy decides *when* within each plug-in window the energy is delivered. The same sessions,
and therefore the same total energy demand, produce very different load shapes:

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

Pick any day from **1 September 2025** up to today. The chart covers that day and the previous one.
Days without stored sessions produce flat zero profiles.

## What happens when you click Analyse

```{mermaid}
sequenceDiagram
    autonumber
    actor U as User
    participant FE as Browser (script.js)
    participant ST as /stations/*
    participant FT as /features/*
    U->>FE: Analyse / change a control
    par for every area
        FE->>ST: POST /stations/within
        ST-->>FE: charging points inside
    and
        FE->>FT: POST /features/transformers/within
        FT-->>FE: transformers inside
    end
    opt Grid view
        FE->>ST: POST …/charging-points-by-transformers
        ST-->>FE: connected charging points
    end
    loop for every area
        FE->>ST: GET /stations/aggregate_load
        ST-->>FE: 288-step profiles
    end
    FE->>FE: draw Yesterday / Today subplots
```

If the backend cannot compute an area, the chart is replaced by *"Load profiles are not available for
this selection"* naming the failing areas, with a hint to try another date or strategy.
