# ReFlex optimiser

**ReFlex** (by HESI) optimises the energy flexibility of devices, such as EV charging points, against a
target supplied by the caller. EPIOT uses it for the **Min. Charging Cost** (`ocost`) strategy: the
target is the day-ahead electricity price, so ReFlex returns the cheapest schedule for every charging
point that still delivers each session's energy.

The OpenAPI specification (*ReFlex Insights API*, v0.3.0) and an example V2X input are kept in
`others/Reflex tool/`.

## Supported devices

- **EV charging points**, uni-directional and bi-directional (V2X).
- **Fixed-profile devices**: non-flexible loads that the optimiser must work around.

## API used by EPIOT

| Call | Purpose |
|---|---|
| `POST /services/run/single` | Start a single optimisation run (`runType: singleRunConfig`); returns a run `id` |
| `GET /services/run/info/{id}` | Run status; EPIOT polls until `runStatus` is `completed` |
| `GET /services/run/results/{id}` | Results, including `devicePlans`: one energy-per-step array per device |

The full specification also defines repeated and multiple runs, a list of all runs, and run deletion.

## Request model

```{mermaid}
classDiagram
    class SingleRunConfig {
      runType = "singleRunConfig"
      congestionPoints[]
      globalTarget
      assets
    }
    class GlobalTarget {
      start : datetime
      timeStepDuration : "PT10M"
      elements[] : TargetElement
    }
    class TargetElement {
      targetType : "price"
      value : float
    }
    class Assets {
      evChargePoints[]
      nonFlexibleAssets[]
    }
    class EvChargePoint {
      id : string
      minChargePower : W
      maxChargePower : W
      maxDischargePower : W (V2X)
      chargeSessions[]
    }
    class ChargeSession {
      startTime : datetime
      endTime : datetime
      energyToCharge : J
      minEnergyToCharge : J (V2X)
    }
    SingleRunConfig --> GlobalTarget
    GlobalTarget --> "288" TargetElement
    SingleRunConfig --> Assets
    Assets --> "*" EvChargePoint
    EvChargePoint --> "*" ChargeSession
```

EPIOT builds this structure in `backend/api_calls/reflex.py` (`create_ReFlex_Query`): one
`EvChargePoint` per charging point with `minChargePower = 0` and `maxChargePower` = rated power in W
(11 kW when unknown), one `ChargeSession` per session with the energy in joules, and 288 price
elements spanning 48 hours. No congestion points or non-flexible assets are sent.

## V2X sessions

A session is treated as V2X when its charging point declares a `maxDischargePower` (and optionally a
`minDischargePower`) **and** the session has a `minEnergyToCharge` (optionally
`minEnergyDuringCharging`). EPIOT currently sends uni-directional sessions only.

:::{admonition} Service notes from the ReFlex team
:class: note

- The instance is shared with another work package, so runs can queue for some time when it is busy.
- In V2X runs the optimiser currently aims at `minEnergyToCharge` rather than `energyToCharge`, because
  charging less is cheaper.
- The schedule may place too much energy in the first interval, and a second session on the same charge
  point is not always scheduled correctly. Both issues are being addressed.
:::

## Access

ReFlex runs at `drive2x-reflex.hesi.energy` and is reachable only from the DRIVE2X project network. When
it is unreachable, the `ocost` strategy fails and the other strategies keep working.
