# Vendored front-end libraries

These files are served from the application instead of public CDNs, so the page works
without internet access to the CDNs and a CDN change or outage cannot alter or break it.
They are the exact versions `templates/index.html` loaded from the CDNs before.
`manifest.json` records every file's source URL, size and SHA-256.

| Library | Version | Licence | Used for |
|---|---|---|---|
| [Plotly.js](https://github.com/plotly/plotly.js) | 2.35.2 | MIT | All charts |
| [Leaflet](https://github.com/Leaflet/Leaflet) | 1.9.4 | BSD-2-Clause | Map |
| [Leaflet.markercluster](https://github.com/Leaflet/Leaflet.markercluster) | 1.5.3 | MIT | Charger clusters |
| [Leaflet.draw](https://github.com/Leaflet/Leaflet.draw) | 1.0.4 | MIT | Area drawing |
| [Turf.js](https://github.com/Turfjs/turf) | 7.1.0 | MIT | Polygon checks |
| [leaflet.heat](https://github.com/Leaflet/Leaflet.heat) | 0.2.0 | BSD-2-Clause | Heatmap helper |
| [martinez-polygon-clipping](https://github.com/w8r/martinez) | 0.7.4 | MIT | Incremental loading |
| [SheetJS (xlsx)](https://github.com/SheetJS/sheetjs) | 0.18.5 | Apache-2.0 | Excel report |
| [jQuery (slim)](https://github.com/jquery/jquery) | 3.5.1 | MIT | Bootstrap components |
| [Bootstrap](https://github.com/twbs/bootstrap) | 4.5.2 | MIT | Layout, tooltips |
| [flatpickr](https://github.com/flatpickr/flatpickr) | 4.6.13 | MIT | Date pickers |
| [Font Awesome](https://fontawesome.com/v4/) | 4.7.0 | SIL OFL 1.1 (fonts), MIT (CSS) | Icons |
| [Inter](https://rsms.me/inter/) | v20 via Google Fonts | SIL OFL 1.1 | Typeface |

Map tiles (OpenStreetMap), geocoding and the optional ReFlex service are still reached over
the network; see the architecture documentation.

## Updating a library

1. Download the new file from its upstream release.
2. Replace it here and update `manifest.json` (path, URL, byte size, SHA-256).
3. Update the version in the table above and the file name in `templates/index.html`.
4. Run `node --test tests/*.mjs` and load the page once.
