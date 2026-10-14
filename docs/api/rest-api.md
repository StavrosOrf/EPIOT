# REST API

The EPIOT backend exposes a small JSON API. The web UI uses nothing else, so everything you can do in
the browser you can also script. All examples assume the development server at
`http://127.0.0.1:5000`.

## Conventions

| Topic | Convention |
|---|---|
| Format | JSON responses. POST bodies are JSON; send `Content-Type: application/json` (a form-encoded body is not read). |
| Geometry | GeoJSON geometries in WGS 84, coordinates as `[longitude, latitude]`. Polygons must be closed rings. |
| IDs | Integer charging-point and transformer IDs, as returned by the endpoints below. |
| Dates | `YYYY-MM-DD`. KPI dates may be ISO datetimes; only the date part is used. |
| Units | Power in kW, energy in kWh, time steps of 10 minutes. |
| Errors | `400 Bad Request` with an HTML message when a body cannot be parsed; `500` on server errors. |
| Auth | None. Put the app behind your own proxy or VPN when exposing it. |

## Endpoint summary

| Method | Path | Purpose |
|---|---|---|
| <span class="badge-endpoint badge-post">POST</span> | [`/stations/within`](#post-stationswithin) | Charging points inside a polygon |
| <span class="badge-endpoint badge-get">GET</span> | [`/stations/all`](#get-stationsall) | All charging points |
| <span class="badge-endpoint badge-get">GET</span> | [`/stations/density`](#get-stationsdensity) | Charging points aggregated on a grid, for overview zooms |
| <span class="badge-endpoint badge-get">GET</span> | [`/stations/coverage`](#get-stationscoverage) | Searchable cities with charger counts, and the data sources |
| <span class="badge-endpoint badge-get">GET</span> | [`/stations/aggregate_load`](#get-stationsaggregate_load) | Load and flexibility profile for a set of charging points |
| <span class="badge-endpoint badge-post">POST</span> | [`/stations/charging-points-by-transformers`](#post-stationscharging-points-by-transformers) | Charging points connected to given transformers |
| <span class="badge-endpoint badge-post">POST</span> | [`/features/transformers/within`](#post-featurestransformerswithin) | Transformers inside a polygon |
| <span class="badge-endpoint badge-get">GET</span> | [`/kpi/user`](#get-kpiuser) | KPI distributions over a date range |
| <span class="badge-endpoint badge-get">GET</span> | [`/marker_icon`](#get-marker_icon) | URLs of icons and logos |
| <span class="badge-endpoint badge-get">GET</span> | `/` | The web application |

---

## POST /stations/within

Returns the charging points whose location lies inside a polygon.

**Body**: a GeoJSON geometry (`Polygon` or `MultiPolygon`).

::::{tab-set}
:::{tab-item} curl
```bash
curl -X POST http://127.0.0.1:5000/stations/within \
  -H "Content-Type: application/json" \
  -d '{"type":"Polygon","coordinates":[[[4.89,52.36],[4.91,52.36],[4.91,52.375],[4.89,52.375],[4.89,52.36]]]}'
```
:::
:::{tab-item} Python
```python
import requests

area = {
    "type": "Polygon",
    "coordinates": [[[4.89, 52.36], [4.91, 52.36], [4.91, 52.375], [4.89, 52.375], [4.89, 52.36]]],
}
stations = requests.post("http://127.0.0.1:5000/stations/within", json=area).json()
ids = [f["properties"]["id"] for f in stations["features"]]
```
:::
:::{tab-item} JavaScript
```javascript
const res = await fetch("/stations/within", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(polygon.geometry),
});
const { features } = await res.json();
```
:::
::::

**Response** `200`: a GeoJSON `FeatureCollection`, one `Point` feature per charging point.

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": "0",
      "geometry": { "type": "Point", "coordinates": [4.891257949604189, 52.36644910230992] },
      "properties": {
        "id": 40405,
        "name": "Louis Couperussingel 15",
        "operator": "EVnetNL",
        "power": 2.3,
        "type": "regular",
        "area_code": null
      }
    }
  ]
}
```

| Property | Type | Description |
|---|---|---|
| `id` | int | Charging-point ID |
| `name` | string | Street address |
| `operator` | string | Operator name |
| `power` | float \| null | Rated power in kW |
| `type` | string | `regular` or `fast` |
| `area_code` | string \| null | CBS neighbourhood code (`buurtcode`); pilot chargers only |
| `source` | string | `pilot`, `ndw`, `bnetza` or `osm` (see `docs/charger_sources.md`) |
| `city` | string \| null | Town or city |
| `country` | string \| null | Country name |

**Errors**: `400` *Could not handle request, expected GeoJSON*.

---

## GET /stations/all

Returns every charging point in the database, in the same format as `/stations/within`. With the
national datasets imported that is several hundred thousand points, so filter by `source` where you can.

```bash
curl http://127.0.0.1:5000/stations/all?source=pilot
```

---

## GET /stations/density

Charging points from all sources counted on a grid whose cells are about 64 screen pixels at the given
zoom (90 / 2^zoom degrees). The map uses it below zoom 12, where single chargers would be too many.
Cells are computed once per zoom and import, then filtered to the bounding box.

| Query parameter | Required | Description |
|---|---|---|
| `zoom` | yes | 3 to 11 |
| `bbox` | no | `west,south,east,north` in degrees; default the whole world |

```bash
curl "http://127.0.0.1:5000/stations/density?zoom=6&bbox=-10,35,25,60"
```

**Response** `200`: `{"zoom": 6, "cell_degrees": 1.40625, "cells": [[lat, lon, points, fast, sites], ...]}`.
`lat`/`lon` is the mean position of the cell's chargers, and `fast` counts points of 50 kW or more.

---

## GET /stations/coverage

The cities offered in location search, with the charging sites and points inside each city's bounding
box, plus the open-data sources and when each was last imported. Counts are `null` until
`scripts/update_charger_data.py` has run.

```json
{
  "regions": [{ "id": "rotterdam", "name": "Rotterdam", "country": "NL", "country_name": "Netherlands",
                "lat": 51.9225, "lon": 4.4792, "zoom": 13, "bbox": [51.832, 4.339, 52.013, 4.619],
                "sites": 6845, "points": 17484 }],
  "sources": [{ "id": "ndw", "label": "NDW DOT-NL", "publisher": "Nationaal Dataportaal Wegverkeer (NDW)",
                "licence": "Open data, free of charge (NDW terms)", "url": "https://docs.ndw.nu/en/faq/DOT-NL/",
                "countries": ["NL"], "imported_at": "2026-10-14T09:23:40+00:00" }]
}
```

---

## GET /stations/aggregate_load

Simulates the charging load and flexibility of a set of charging points over the two-day window ending
on `date`.

| Query parameter | Required | Description |
|---|---|---|
| `selected_markers` | yes | Comma-separated charging-point IDs. `undefined` or empty returns a zero profile. |
| `strategy` | yes | `afap`, `alap`, `avg` or `ocost` (see {doc}`../concepts/charging-strategies`) |
| `date` | yes | Selected day $D$ as `YYYY-MM-DD`; the window is $D-1$ 00:00 to $D$ 24:00 |

::::{tab-set}
:::{tab-item} curl
```bash
curl "http://127.0.0.1:5000/stations/aggregate_load?selected_markers=40405,40406,49414&strategy=alap&date=2025-10-15"
```
:::
:::{tab-item} Python
```python
import numpy as np
import requests

r = requests.get(
    "http://127.0.0.1:5000/stations/aggregate_load",
    params={"selected_markers": ",".join(map(str, ids)), "strategy": "afap", "date": "2025-10-15"},
).json()

load = np.array(r["y"])            # kW, 288 steps
yesterday, today = load[:144], load[144:]
print(f"Energy on D: {today.sum() / 6:.1f} kWh, peak {today.max():.1f} kW")
```
:::
::::

**Response** `200`:

```json
{
  "x": [0, 1, 2, "…", 287],
  "y": [0.0, 0.0, 11.0, "…"],
  "up_flex": [0.0, "…"],
  "down_flex": [0.0, "…", -11.0, "…"]
}
```

| Field | Length | Unit | Description |
|---|---|---|---|
| `x` | 288 | step | Step index; step $t$ starts at $D-1$ 00:00 + $10t$ min |
| `y` | 288 | kW | Aggregated charging load |
| `up_flex` | 288 | kW | Upward flexibility (≥ 0) |
| `down_flex` | 288 | kW | Downward flexibility (≤ 0) |

When `selected_markers` is `undefined` or empty, the response has 144 zero values in each field.

:::{note}
`ocost` calls the Energy-Charts and ReFlex services and blocks until the optimisation finishes. Its
`y` values are the ReFlex energy plan converted from J per 10-minute step to average kW (`J / 600 / 1000`). ReFlex polling has a 120-second deadline by default; individual ReFlex requests have a 10-second timeout.
:::

---

## POST /stations/charging-points-by-transformers

Expands a list of transformers to the charging points connected to them through `grid_connections`.
Used by the **Grid** view.

**Body**:

```json
{ "transformer_ids": [1099526503800, 1099526503812] }
```

**Response** `200`:

```json
{
  "transformer_ids": [1099526503800, 1099526503812],
  "charging_point_ids": [6801, 6802, 40405],
  "count": 3
}
```

`charging_point_ids` is de-duplicated and sorted.

**Errors**: `400` *Expected JSON: {"transformer_ids":[int,...]}* when the body is missing, not a list,
or contains non-integers.

---

## POST /features/transformers/within

Returns the transformers inside a polygon, optionally filtered by voltage level.

**Body**: a GeoJSON geometry with an optional extra member `tr_type`:

```json
{
  "type": "Polygon",
  "coordinates": [[[4.89, 52.36], [4.91, 52.36], [4.91, 52.375], [4.89, 52.375], [4.89, 52.36]]],
  "tr_type": "Middle"
}
```

| `tr_type` | Assets |
|---|---|
| `Low` | LV distribution cabinets |
| `Middle` | MV installations (MV/LV transformers) — used by the UI |
| `High` | Substations |
| *omitted* | All levels |

**Response** `200`: a `FeatureCollection` of `Point` features with properties `id` and `type`.

---

## GET /kpi/user

Computes all KPI dashboards for a set of charging points over a date range.

| Query parameter | Required | Description |
|---|---|---|
| `selected_markers` | yes | Comma-separated charging-point IDs |
| `start_date` | yes | Start of the range (`YYYY-MM-DD` or ISO datetime) |
| `end_date` | yes | End of the range (`YYYY-MM-DD` or ISO datetime) |

```bash
curl "http://127.0.0.1:5000/kpi/user?selected_markers=40405,40406&start_date=2025-09-08&end_date=2025-10-20"
```

**Response** `200`: an object with 28 fields, defined in {doc}`../concepts/kpi-methodology`. Fields may
contain `NaN` literals for empty groups; replace them with `null` before strict JSON parsing:

```javascript
const data = JSON.parse((await res.text()).replace(/NaN/g, "null"));
```

---

## GET /marker_icon

Returns absolute URLs for the static images used by the map: `charge_icon`, `transformer_icon`,
`flexibility_icon`, `enter_icon`, `drive2X_LOGO`, `eu_logo`, `ukri_logo`, `info_icon`.

---

## End-to-end example

Compute and compare the three local strategies for a neighbourhood:

```python
import requests

BASE = "http://127.0.0.1:5000"
area = {
    "type": "Polygon",
    "coordinates": [[[4.885, 52.355], [4.93, 52.355], [4.93, 52.375], [4.885, 52.375], [4.885, 52.355]]],
}

ids = [f["properties"]["id"] for f in requests.post(f"{BASE}/stations/within", json=area).json()["features"]]
markers = ",".join(map(str, ids))

for strategy in ("afap", "alap", "avg"):
    r = requests.get(
        f"{BASE}/stations/aggregate_load",
        params={"selected_markers": markers, "strategy": strategy, "date": "2025-10-15"},
    ).json()
    today = r["y"][144:]
    print(f"{strategy:5s} peak {max(today):7.1f} kW   energy {sum(today) / 6:8.1f} kWh")
```
