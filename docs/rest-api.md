# REST API

The web interface uses nothing but the endpoints on this page, so everything it does can be
scripted. Examples assume the development server at `http://127.0.0.1:5000`.

## Conventions

| Topic | Convention |
|---|---|
| Format | JSON. Send POST bodies as JSON with `Content-Type: application/json`. |
| Geometry | GeoJSON in WGS 84, coordinates as `[longitude, latitude]`, polygons closed |
| IDs | Integer charging-point and transformer IDs; large IDs (above 10¹²) stay below 2⁵³ |
| Dates | `YYYY-MM-DD`, interpreted as local calendar days of the scenario time zone |
| Units | Power in kW, energy in kWh, steps of 10 minutes |
| Authentication | None. Put the application behind your own proxy or VPN. |

| Status | Meaning |
|---|---|
| `400` | Invalid input: unknown strategy, source or demand level, malformed date, seed or IDs. Body: `{"error": "..."}` |
| `422` | Valid input that cannot be computed: no carbon data for minimum carbon, cost optimisation across a daylight-saving change, or a request over the size limit |
| `503` | A session source or health check is unavailable, for example a stale CPFT library |

The size limit counts charging points × days (two days per load-profile draw, the range for KPIs)
and defaults to 1,000,000; see {doc}`operations`.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | [`/stations/within`](#stationswithin) | Charging points inside a polygon |
| `GET` | [`/stations/all`](#stationsall) | Every charging point, optionally of one source |
| `GET` | [`/stations/density`](#stationsdensity) | Aggregated cells for overview zooms |
| `GET` | [`/stations/coverage`](#stationscoverage) | Searchable cities and data sources |
| `POST` | [`/features/transformers/within`](#featurestransformerswithin) | Transformers inside a polygon |
| `POST` | [`/stations/charging-points-by-transformers`](#stationscharging-points-by-transformers) | Charging points behind transformers |
| `GET` `POST` | `/stations/aggregate_load` | Load and flexibility profile ({doc}`load-profiles`, {doc}`flexibility`) |
| `GET` `POST` | `/kpi/user` | KPI dashboards ({doc}`kpis`) |
| `GET` | [`/stations/analysis-version`](#stationsanalysis-version) | Revisions for cache freshness |
| `GET` | [`/healthz`](#healthz) | Health check |
| `GET` | `/marker_icon` | URLs of the map icons and logos |

### /stations/within

`POST` a GeoJSON `Polygon` or `MultiPolygon`. The response is a `FeatureCollection` with one
`Point` per charging point inside it, or `{"ids": [...]}` with `?ids_only=1`.

```bash
curl -X POST "http://127.0.0.1:5000/stations/within?ids_only=1" \
  -H "Content-Type: application/json" \
  -d '{"type":"Polygon","coordinates":[[[4.89,52.36],[4.91,52.36],[4.91,52.375],[4.89,52.375],[4.89,52.36]]]}'
```

| Property | Description |
|---|---|
| `id` | Charging-point ID |
| `name` | Street address |
| `operator` | Operator name |
| `power` | Rated power in kW, or `null` |
| `type` | `regular` (AC) or `fast` (DC) |
| `source` | `pilot`, `ndw`, `bnetza`, `osm`, `bfe`, `irve` or `digitraffic` |
| `city`, `country` | Town and country name |
| `area_code` | CBS neighbourhood code; pilot chargers only |

### /stations/all

Every charging point in the same format, filtered with `?source=` (one of the source values
above). The unfiltered list has several hundred thousand entries.

### /stations/density

Charging points counted on a grid of about 64 screen pixels at the zoom level.

| Parameter | Description |
|---|---|
| `zoom` | Required, 3 to 11 |
| `bbox` | `west,south,east,north` in degrees; default the whole world |

The response is `{"zoom", "cell_degrees", "cells": [[lat, lon, points, fast, sites], ...]}`.
`lat` and `lon` are the real charger nearest the cell's weighted mean, and `fast` counts points of
50 kW or more. Responses carry an `ETag` and a 30-second private cache lifetime.

### /stations/coverage

`{"regions": [...], "sources": [...]}`. Each region is a searchable city with `id`, `name`,
`country`, `lat`, `lon`, `zoom`, `bbox` and its `sites` and `points` counts. Each source lists its
`label`, `publisher`, `licence`, `url`, `countries` and `imported_at`.

### /features/transformers/within

`POST` a GeoJSON geometry with an optional `tr_type` member: `Low` (LV cabinets), `Middle` (MV/LV
transformers, used by the map) or `High` (substations). The response is a `FeatureCollection` of
points with `id` and `type`, or `{"ids": [...]}` with `?ids_only=1`.

### /stations/charging-points-by-transformers

`POST {"transformer_ids": [1099526503800, ...]}` returns
`{"transformer_ids", "charging_point_ids", "count"}`, with the IDs de-duplicated and sorted. A
body that is not a list of integers returns `400`.

### /stations/analysis-version

Returns opaque `infrastructure` and `analysis` revisions with `Cache-Control: no-store`. The first
tracks the database and the charger manifest; the second also tracks calculation code, scenario
inputs, grid data and relevant settings. The interface compares them before reusing cached
selections or results.

### /healthz

`{"status": "ok", "spatialite": "5.1.0"}` when the database answers and SpatiaLite is loaded, and
`503` otherwise.

## End-to-end example

Select an area, compare three strategies, and read the weekly KPIs:

```python
import requests

BASE = "http://127.0.0.1:5000"
area = {"type": "Polygon", "coordinates": [[[4.885, 52.355], [4.93, 52.355], [4.93, 52.375],
                                            [4.885, 52.375], [4.885, 52.355]]]}

ids = requests.post(f"{BASE}/stations/within", params={"ids_only": 1}, json=area).json()["ids"]

for strategy in ("afap", "alap", "avg"):
    profile = requests.post(f"{BASE}/stations/aggregate_load", json={
        "selected_markers": ids, "date": "2026-10-14", "strategy": strategy,
        "session_source": "spatial", "demand_assumption": "base", "seed": 42,
    }).json()
    target = profile["y"][profile["past_steps"]:]
    print(f"{strategy:5s} peak {max(target):7.1f} kW   energy {sum(target) / 6:8.1f} kWh")

kpis = requests.post(f"{BASE}/kpi/user", json={
    "selected_markers": ids, "start_date": "2026-10-08", "end_date": "2026-10-14",
    "session_source": "spatial", "section": "basic",
}).json()
print(kpis["summary"]["peak_kw"], kpis["summary"]["load_factor"])
```

The three strategies deliver the same energy to within the edge effects described in
{doc}`charging-strategies`, so their peaks are directly comparable.
