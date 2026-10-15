# Map and areas

The map shows the charging infrastructure. The areas drawn on it select the chargers that every
other view analyses.

```{figure} _static/screenshots/anatomy-map.jpg
:class: screenshot
:alt: The map screen with numbered callouts on each control

The map screen at city level.
```

| # | Control | Function |
|---|---|---|
| 1 | **EPIOT** | Reloads the application |
| 2 | **Search** | Finds a city, street or address and centres the map on it |
| 3 | **Show** | Switches the **Chargers** and **Transformers** layers on and off |
| 4 | **About** | Reopens the welcome dialog |
| 5 | **Zoom** | Zoom in and out |
| 6 | **Draw area** | Polygon, rectangle and delete tools, with a counter of the areas drawn (0/3) |
| 7 | **Status** | Guidance and feedback, such as how many areas are selected |
| 8 | **Analyse** | Opens the analysis panel for the drawn areas |

## Zoom levels

The map opens on Amsterdam at zoom 12 and supports zoom 4 to 16.

```{figure} _static/screenshots/map-overview.jpg
:class: screenshot
:alt: Aggregate bubbles over western Europe at zoom 5

Overview zoom. Each bubble counts the charging points in a grid cell.
```

| Zoom | The map shows |
|---|---|
| 4 – 11 | Aggregate bubbles from `/stations/density`, one per grid cell of about 64 screen pixels, labelled with the number of charging points (3.4k, 193k). Each bubble sits on a real charger. Areas cannot be drawn. |
| 12 – 15 | One marker per charging site, clustered where markers overlap |
| 16 | Every site as its own marker |

A site is one location. Its badge counts the charging points there, and fast (DC) sites have a
distinct marker. Clicking a site with several points fans them out; clicking a point opens its
popup.

## Charger and transformer popups

```{figure} _static/screenshots/charger-popup.jpg
:class: screenshot
:alt: Popup of a charging point with type, power, address, operator and data source
:width: 360px

A charging-point popup.
```

| Field | Content |
|---|---|
| Type and power | `AC` or `DC fast`, and the rated power in kW (*Power unknown* if the feed omits it) |
| Point *i* of *n* | Position among the points of the site |
| Address | Street, city and country |
| Operator | Name from the data source |
| Source | Register the record comes from, with its attribution |

The **Transformers** layer shows the medium-/low-voltage (MV/LV) installations of the Liander grid
from zoom 12. These exist for Amsterdam only, and the popup states the ID and the voltage level
(*Middle*).

```{figure} _static/screenshots/map-transformers.jpg
:class: screenshot
:alt: Charger bubbles and transformer markers in central Amsterdam

Chargers and MV/LV transformers shown together.
```

## Search

The search box suggests places while you type: PDOK for the Netherlands and Photon
(OpenStreetMap) elsewhere. The suggestions also list every supported city together with its number
of charging sites, taken from `/stations/coverage`. Choosing a result centres the map on it at a
zoom level suited to its size.

## Drawing areas

```{figure} _static/screenshots/draw-hint.jpg
:class: screenshot
:alt: The draw toolbar with the polygon tool active and its hint

Each tool shows a short hint while it is active.
```

| Tool | Use |
|---|---|
| **Polygon** | Click to place vertices. Click the first vertex or double-click to close the shape. |
| **Rectangle** | Press on one corner, drag to the opposite corner and release. |
| **Delete** | Click the areas to remove, then click the tool again. |

{kbd}`Esc` cancels the active tool. Up to **three** areas can be drawn. Each gets a colour and a
name that cards, charts and the report use:

| Area | Colour | Name |
|---|---|---|
| First | Green `#4CAF50` | Area 1 |
| Second | Dark red `#8A0606` | Area 2 |
| Third | Blue `#3357FF` | Area 3 |

Colours cycle and names keep counting: after deleting *Area 2*, the next area is *Area 4*. A shape
whose edges cross is rejected. Areas can be renamed, reordered and duplicated from the analysis
cards ({doc}`getting-started`).

```{figure} _static/screenshots/areas-drawn.jpg
:class: screenshot
:alt: Three labelled areas over central Amsterdam

Three areas ready for analysis.
```

## What an area selects

An area contains the charging points whose location lies inside its boundary, tested exactly
against the drawn shape with a spatial `ST_Within` query. Load profiles, flexibility and KPIs
use the same selection. The cards show how many chargers each area holds; compare areas of similar
size and charger density for meaningful side-by-side results.

## Welcome dialog and small screens

The welcome dialog summarises the tool and its audiences on the first visit. Tick **Don't show this
again** to hide it (stored in the browser as `epiotr_intro_seen`), reopen it with **About**, or
add `?landing` to the address to force it open.

```{figure} _static/screenshots/landing.jpg
:class: screenshot
:alt: The welcome dialog with the main functions, audiences and a four-step guide

The welcome dialog.
```

```{figure} _static/screenshots/mobile-map.jpg
:class: screenshot
:alt: EPIOT on a phone-sized screen
:width: 300px

The layout at phone width (390 px).
```

On narrow screens the app bar wraps, the layer toggles shrink to icons and the area cards stack
above their charts.
