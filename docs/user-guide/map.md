# Map and layers

The map is built with [Leaflet](https://leafletjs.com/) on OpenStreetMap tiles. It opens centred on
Amsterdam (52.3676 N, 4.9041 E) and is limited to zoom levels **14 to 16**, the range in which
individual charging points remain readable and the marker queries stay small.

## Charging points

Every charger icon is one **charging point** (a connector) from the database. Several points on the
same street pole share a location, so their icons overlap. Click an icon to open its pop-up:

```{figure} ../_static/screenshots/charger-popup.jpg
:class: screenshot
:alt: Pop-up of a charging station showing name, ID, operator and capacity
:width: 520px

A charging-station pop-up.
```

| Field | Source |
|---|---|
| **Name** | Street address of the location (`locations.street`) |
| **Id** | Charging-point ID (`charging_points.id`); the same ID appears in reports and *Locate on map* |
| **Operator** | Operator name (`operators.name`) |
| **Capacity** | Rated connector power in kW (`charging_points.power`) |

The **Chargers** toggle in the app bar shows or hides the whole layer without discarding it.

## Transformers

Switch on **Transformers** to show the medium-voltage installations of the Liander distribution
grid. These are the MV/LV transformers that feed the low-voltage networks the chargers are
connected to; the *Grid* view of the load profiles aggregates load at this level.

```{figure} ../_static/screenshots/map-transformers.jpg
:class: screenshot
:alt: Map with both charger and transformer icons

Chargers and MV/LV transformers shown together.
```

```{figure} ../_static/screenshots/transformer-popup.jpg
:class: screenshot
:alt: Transformer pop-up with ID and type
:width: 460px

A transformer pop-up. *Type* is the voltage level: `Middle` for MV/LV installations.
```

The database holds three voltage levels imported from the Liander dataset, but the map and the
analysis use the `Middle` level only:

| Liander layer | Stored as `type` | Shown on map |
|---|---|:---:|
| `laagspanningsverdeelkasten` (LV distribution cabinets) | `Low` | |
| `middenspanningsinstallaties` (MV installations, MV/LV transformers) | `Middle` | ✓ |
| `onderstations` (substations) | `High` | |

## How markers are loaded

Markers are fetched lazily: when the map finishes moving, EPIOT asks the backend only for the part of
the viewport that it has not requested before. The already-requested rectangles are subtracted from
the new viewport with the Martinez polygon-clipping algorithm, so panning back over a known area
costs no request at all.

```{mermaid}
sequenceDiagram
    autonumber
    participant M as Leaflet map
    participant L as loaders.js
    participant B as Flask backend
    M->>L: moveend (new viewport)
    L->>L: subtract requested areas
    alt nothing new
        L-->>M: skip
    else new area left
        L->>B: POST /stations/within
        L->>B: POST /features/transformers/within
        B-->>L: FeatureCollections
        L->>M: add markers
        L->>L: remember viewport
    end
```

## Location search

Type a city, street, postcode or landmark into **Search a location…** and press {kbd}`Enter` or the
arrow button. EPIOT queries the
[OpenStreetMap Nominatim](https://nominatim.org/) geocoder and centres the map on the best match at
zoom 15. If nothing matches, the status bar says *No results for "…"*.

:::{note}
The charging-point and transformer data currently cover **Amsterdam**. Searching elsewhere moves the
map, but no markers will appear outside the data coverage.
:::
