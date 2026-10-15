# Load profiles

The **Load profiles** tab shows the aggregated charging power of the chargers inside each area on
a 10-minute grid, for the target date and the day before. Sessions come from the selected
{doc}`session source <session-sources>`.

## Reading the chart

| Element | Meaning |
|---|---|
| Blue line | Target day |
| Orange line | Previous day, so overnight charging into the target day is visible |
| Day labels | Weekday and date of each day; weekends are in bold |
| y-axis | Aggregated power in kW; every area card shares one range |
| x-axis | Time in UTC; each value holds for its 10-minute interval |
| Hover | The value with its weekday and time |

The energy of a profile is the sum of its values divided by six (kW × ⅙ h per step). The window
spans two local days, which is 288 steps, or 276 and 300 steps across a daylight-saving change.
The note under the controls states the source, the demand scenario and the effects of the day.

## Charging strategies

A strategy decides *when* each connection draws its energy. Every strategy follows each
connection from its true arrival to its true departure and delivers the same energy,
`E = min(requested energy, power × connected hours)`. The window only crops the result, so a car
that arrived at 21:00 is charged from 21:00 and not again at midnight.

| Strategy | Behaviour |
|---|---|
| **As Fast As Possible** (`afap`) | Full rated power from arrival until `E` is delivered. Uncontrolled charging and the baseline. |
| **As Late As Possible** (`alap`) | Full rated power, scheduled to end at departure. |
| **Average Power** (`avg`) | Constant power `E ÷ stay` for the whole connection. |
| **Min. Carbon Footprint** (`mincarbon`) | Fills the lowest-carbon 10-minute intervals first within plug power and the connection window; charging may pause. Needs a scenario source and grid carbon data ({ref}`kpis:grid data`). |
| **Min. Charging Cost** (`ocost`) | Cheapest schedule against day-ahead prices (Energy-Charts, Netherlands) from the ReFlex optimiser. Needs the DRIVE2X network, and supports ordinary 48-hour windows only. |

Minimum-carbon scheduling is an estimate on historical or reference grid data, not demonstrated
avoided emissions. For it, connections that cross the window edge contribute their
uniform-charging share inside the window.

The same sessions and total energy give very different shapes, so duplicating an area and giving
the copy another strategy is the quickest comparison.

## API

`GET` or `POST /stations/aggregate_load`

| Parameter | Required | Description |
|---|---|---|
| `selected_markers` | Yes | Charging-point IDs: a JSON array, or comma-separated in a query string |
| `date` | Yes | Target date, `YYYY-MM-DD` |
| `strategy` | Yes | `afap`, `alap`, `avg`, `mincarbon` or `ocost` |
| `session_source` | – | `simple`, `spatial` or `cpft` ({doc}`session-sources`), or `database` for the stored sessions of the Amsterdam pilot chargers (the default when omitted) |
| `demand_assumption`, `seed` | – | Scenario settings ({doc}`session-sources`) |
| `ensemble` | – | Number of seeded draws to combine into a band, 1 to 30 (default 1). Scenario sources and every strategy except `ocost` |

```bash
curl -G http://127.0.0.1:5000/stations/aggregate_load \
  -d selected_markers=40405,40406 -d date=2026-10-15 -d strategy=avg \
  -d session_source=spatial -d demand_assumption=base -d seed=42
```

| Response field | Description |
|---|---|
| `timestamps` | ISO-8601 start of each step, with local offset |
| `past_steps` | Number of steps that belong to the previous day |
| `y` | Aggregated load, kW |
| `up_flex`, `down_flex` | Flexibility signals, kW ({doc}`flexibility`) |
| `flex_polytope` | Feasible envelope ({doc}`flexibility`) |
| `source` | Scenario provenance, including `calendar` and `note` |
| `source.ensemble` | With `ensemble` above 1: `p10`, `p50`, `p90` load per step over seeds `seed` to `seed + ensemble - 1`, plus `members` and `seeds`. `y` stays the draw of `seed` itself |
| `x` | Step index |

```python
import requests

r = requests.get("http://127.0.0.1:5000/stations/aggregate_load", params={
    "selected_markers": "40405,40406", "date": "2026-10-15", "strategy": "afap",
    "session_source": "simple"}).json()
target = r["y"][r["past_steps"]:]
print(f"{sum(target) / 6:.1f} kWh, peak {max(target):.1f} kW")
```

An empty selection returns zero profiles. Unknown strategies, sources, charging points and
malformed dates or `ensemble` values return `400`; minimum-carbon scheduling without carbon data
returns `422`, as does a request over the size limit (charging points × days, see
`FLASK_MAX_POINT_DAYS` in {doc}`getting-started`). Every draw counts towards that limit.

Stored sessions use the same engine and strategies as the scenario sources. Connections that
cross the window edge are included in full and cropped to the window.

### Several draws

One seeded draw is one possible day, so a single line overstates how sure the result is. With
`ensemble=10` the page shades the 10th to 90th percentile of ten draws behind the line (the
**Draws** control in the header). Sessions, day effects and weather all vary with the seed. The band
shows how much the synthetic sampling matters; it is not a calibrated forecast interval. Ten draws
take about two seconds for a city-sized area and thirty about six. KPIs are computed from one draw.

## Export

The report's **Load Data** sheet has one row per area and step:

| Column | Content |
|---|---|
| `Area Name` | Area label |
| `Timestamp (UTC)` | Start of the step |
| `EV Load (kW)` | Aggregated power |
| `Upward Flexibility (kW)`, `Downward Flexibility (kW)` | Flexibility signals |
| `Session source`, `Demand assumption`, `Synthetic` | Scenario provenance |
| `Charging strategy` | Strategy of the area card |
| `EV Load 10th percentile (kW)`, `EV Load 90th percentile (kW)` | Only when several draws were requested |

The **Charger IDs** sheet lists the charging points of each area.
