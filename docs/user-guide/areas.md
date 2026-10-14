# Selecting areas

All analyses in EPIOT are done per **area**: a polygon or rectangle you draw on the map. You can
draw up to **three** areas and compare them side by side in every chart and in the report.

## Drawing tools

The floating toolbar on the left of the map has three tools. Clicking a tool shows a short hint
next to it; clicking the active tool again, or pressing {kbd}`Esc`, switches it off.

```{figure} ../_static/screenshots/draw-hint.jpg
:class: screenshot
:alt: The polygon tool active, with its usage hint displayed
:width: 620px

The polygon tool with its hint.
```

::::{tab-set}

:::{tab-item} Polygon
1. Click the **polygon** tool.
2. Click on the map to place each vertex. The running area is shown while you draw.
3. Click the **first vertex** again, or double-click, to close the shape.

Self-intersecting outlines are rejected while drawing.
:::

:::{tab-item} Rectangle
1. Click the **rectangle** tool.
2. Press on one corner, drag to the opposite corner and release.
:::

:::{tab-item} Delete
1. Click the **trash** tool.
2. Click each area you want to remove.
3. Click the trash again, or press {kbd}`Esc`, to finish.

The area's label is removed with it, and the status bar reports how many areas remain.
:::
::::

## Area identity

Each completed area gets a label at its centre and a colour. Both follow the order in which shapes
are drawn during the session:

| Shape drawn | Colour | Label |
|---|---|---|
| 1st | Green `#4CAF50` | Area 1 |
| 2nd | Dark red `#8A0606` | Area 2 |
| 3rd | Blue `#3357FF` | Area 3 |
| 4th (after a deletion) | Green again | Area 4 |

Colours cycle through the three values and labels keep counting up: if you delete *Area 2* and
draw a new area, it becomes *Area 4*. Charts,
the *Locate on map* list and report sheets always use these labels, so you can match results to
shapes on the map.

```{figure} ../_static/screenshots/areas-drawn.jpg
:class: screenshot
:alt: Three labelled areas on the map

Three areas ready for analysis.
```

## Validation rules

```{mermaid}
flowchart TD
    A[Shape finished] --> B{Already 3 areas?}
    B -- yes --> R1["Rejected:<br/>'You can compare up to 3 areas'"]
    B -- no --> C{Valid polygon?<br/>turf.booleanValid}
    C -- no --> R2["Rejected:<br/>'That shape is invalid (edges cross)'"]
    C -- yes --> D[Colour, label, store as GeoJSON]
    D --> E["Status: 'N of 3 areas selected. Ready to analyse'"]
    E --> F[Analyse button glows]
```

## What an area selects

When you click **Analyse**, each area polygon is sent to the backend as GeoJSON. What it selects
depends on the **View** setting of the load-profile tab:

```{mermaid}
flowchart LR
    P[Area polygon] -->|ST_Within| CP[Charging points<br/>inside the area]
    P -->|ST_Within, type = Middle| TR[MV/LV transformers<br/>inside the area]
    TR -->|grid_connections| GCP[Charging points served<br/>by those transformers]
    CP --> V1([Chargers view,<br/>Flexibility, KPIs])
    GCP --> V2([Grid view])
```

- **Chargers view, Flexibility, KPIs**: the charging points whose location lies *inside* the polygon.
- **Grid view**: the charging points *connected to* the MV/LV transformers inside the polygon. These
  can lie partly outside the polygon, because each charging location is linked to its nearest
  MV/LV transformer (see {doc}`../operations/database`).

The selection is a spatial `ST_Within` query against point geometries in SpatiaLite; the exact
boundary of the drawn shape is used.

:::{tip}
Compare like with like. Areas of similar size and charger density give more meaningful side-by-side
charts; the chart titles show how many chargers (or transformers) each area contains.
:::
