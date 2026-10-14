# Open charger-location data

EPIOT shows chargers from six open sources next to the Amsterdam pilot data.
All of them are stored in the same `locations`, `columns` and `charging_points`
tables as the pilot data. Drawing areas, load profiles, flexibility and KPIs
therefore treat every charger the same way.

| Source | Coverage | Format | Licence |
|---|---|---|---|
| NDW DOT-NL | All of the Netherlands | OCPI 2.2.1 locations (gzip JSON) | Open data, free of charge |
| Bundesnetzagentur Ladesäulenregister | All of Germany | Semicolon CSV, decimal commas | Open data (BNetzA terms) |
| OpenStreetMap via Overpass | Lisbon, Porto, Milan, Rome, Turin, London, Manchester | Overpass JSON | ODbL 1.0, credit "© OpenStreetMap contributors" |
| BFE ich-tanke-strom.ch | All of Switzerland | OICP JSON, plus a live status file | Open use, credit the source |
| Base nationale des IRVE | All of France, including overseas territories | Consolidated CSV (schema v2.3.1) | Licence Ouverte 2.0 |
| Fintraffic Digitraffic AFIR | All of Finland | GeoJSON (OCPI model), plus live statuses | CC BY 4.0 |
| Amsterdam pilot (existing) | Amsterdam | Open Charge Map export | Has observed sessions and Liander grid data |

The map credits every source in its attribution line, as their licences
require.

## Folder layout

```
data/chargers/
  manifest.json           # downloads (URL, size, sha256, time), import counts, per-city counts
  raw/ndw/                # charging_point_locations_ocpi.json.gz, tariffs, GeoJSON
  raw/bnetza/             # ladesaeulenregister.csv
  raw/osm/<city>.json     # one Overpass result per city in backend/charger_sources.py REGIONS
  raw/bfe/                # evse_data.json (static), evse_status.json (live availability)
  raw/irve/               # irve_statique.csv (URL looked up daily via the data.gouv.fr API)
  raw/digitraffic/        # locations.json, statuses.json (live availability)
```

`data/` is not committed. The compact snapshots in `seed_data/` are GitHub-ready
and initialize a fresh server offline, including Amsterdam pilot/grid data and
the inputs for simple/spatial sessions:

```
uv run python database_init.py
```

The initializer runs migrations itself. Do not create the database first with
`flask db upgrade`; it deliberately refuses to overwrite an existing database.
See [the snapshot guide](../seed_data/README.md). Supplier refreshes remain optional:

```
uv run flask --app app db upgrade              # once: adds source columns and indexes
uv run python scripts/update_charger_data.py   # download and import everything
uv run python scripts/update_charger_data.py --skip-fetch --sources osm   # re-import one source
uv run python scripts/export_country_data.py  # regenerate the GitHub-ready snapshots
```

## How the data is mapped

| EPIOT table | NDW | BNetzA | OSM |
|---|---|---|---|
| `locations` (one per site) | OCPI location | devices at the same coordinates | station |
| `columns` | OCPI location | one charging device (Ladeeinrichtung) | station |
| `charging_points` | each EVSE that is not `REMOVED` | each Ladepunkt (plug 1–6) | `capacity`, else socket count, else 1 |

The Swiss records are one per EVSE, and half reuse the EVSE ID as station ID, so
a site is one operator's EVSEs at one position. France has one row per charging
point (`id_pdc_itinerance`), grouped by `id_station_itinerance`. Its checked
`consolidated_latitude/longitude` win over the raw `coordonneesXY`, which is
malformed in about 35k rows. A repeated point keeps its latest `date_maj`. Powers
above 1000 are read as watts. About 90 stations filed abroad keep their real
country from the ID prefix (e.g. `ES…`). Finland maps like NDW: location → site,
EVSE → charging point, with power from `maxElectricPower` in W.

### Positions

The feeds get some positions wrong, and `backend/charger_positions.py` repairs
them before import:

Verified station corrections are kept in `backend/data/charger_position_overrides.json`.
In particular, IRVE station `FRALLPEVCARSANGLT` (eight points for Carrefour BAB2,
Anglet) was incorrectly placed at `(50.636688, -1.499184)` near the Isle of Wight.
Its address location is `(43.486703, -1.501622)`, checked against Carrefour's
published address and the French national address geocoder. This is an address
location, not a surveyed charging-stall position. The correction works offline,
preserves every charger ID and does not overwrite future feed corrections.
`scripts/repair_charger_positions.py` applies it to existing databases and takes
a backup first. IRVE's explicit `consolidated_is_lon_lat_correct=False` flag now
forces address verification; an unverified flagged position is skipped instead
of being accepted by the generous coastal tolerance.

| Fault | Example | Repair |
|---|---|---|
| Swapped latitude/longitude | Sargans at (9.45, 47.05) | Swapped back when that lands in the country |
| Station abroad, labelled with the feed's country | German, Austrian and Italian stations in the Swiss feed; Spanish ones in the French register | Address searched in all countries (Nominatim); within 1 km of the feed's position, only the country label changes |
| Typo or placeholder | Wegberg at latitude 55 instead of 51; Swiss sites at (50, −15) | Same address search; the site moves to the address |
| Far out at sea | An Alphen aan den Rijn charger 18 km off Petten | More than about 2 km from Natural Earth's 1:10m land (`data/chargers/ne_10m_land.zip`, public domain) counts as misplaced: the address is searched, otherwise the site is dropped. The 2 km margin keeps harbour and beach chargers, which the coarse coastline would otherwise put in the water. |
| Pile-up: three or more addresses on one point | 188 German devices from many towns on one North Sea point; 42 Düsseldorf sites on the town centre | Each address geocoded with the country's own service. A result within 1 km confirms the shared position. A point shared by sites from three or more towns is a placeholder, so unresolved sites there are dropped. A one-town pile keeps its town position. |

Geocoders: PDOK for the Netherlands, geo.admin.ch for Switzerland and
Liechtenstein, the IGN Géoplateforme for France, and Nominatim (at most one
request per second) elsewhere. Results, including misses, are cached in
`data/chargers/geocode_cache.json`, so a re-import makes no repeat requests.
`--no-geocode` keeps only the offline repairs. Finally every site is checked
against its country's bounding box (France includes its overseas territories,
and other countries use a broad Europe box). Whatever still lies outside is
skipped. The manifest records each repair count under `imports.<source>.positions`.
After the repairs, each site's country is set from Natural Earth's 1:10m
borders (`data/chargers/ne_10m_admin_0_countries.zip`). A site within about 1 km
of its labelled country keeps the label, because the borders are only accurate
to a few hundred metres. One clearly inside another country takes that country.
Åland counts as Finland, and French Polynesia, New Caledonia and the other
overseas collectivities count as France. Stations a feed lists abroad are then
left out, because their country is not covered: Belgian and German ones in NDW,
Luxembourg, Swiss and Monaco ones in the French register, and Austrian, Polish
and Czech ones in BNetzA. Each source keeps only its own countries (`Source.countries`), and
the manifest counts the rest as `skipped_outside_coverage`.

Bubbles are drawn on a real charger. Leaflet.markercluster normally puts a
cluster at the average of its members, which for two river banks or a row of
coastal towns lies in the water. `script.js` moves each cluster onto its member
nearest that average, and `/stations/density` does the same for the overview
cells.
| `power` (kW) | max connector power, or V × A (× 3 for 3-phase) | plug rating, else device rating ÷ points | largest `*:output`; empty if untagged |
| `type` | `fast` when any connector is DC | `fast` for DC plugs | `fast` for CCS, CHAdeMO or Tesla sockets |

- **Source tags:** imported rows carry `source` and `external_id`. Pilot rows leave both empty.
- **Stable IDs:** an external ID keeps its integer ID on every re-import. New IDs start at 1×10¹² (NDW), 2×10¹² (BNetzA), 3×10¹² (OSM), 4×10¹² (BFE), 5×10¹² (IRVE) and 6×10¹² (Digitraffic). These stay below JavaScript's safe-integer limit and never collide with pilot IDs.
- **Pilot duplicates:** inside the Amsterdam neighbourhood atlas (the municipality), the pilot chargers stand in for NDW. They own the observed sessions and grid links, so analyses there never count a charger twice. The pilot positions come from an old Open Charge Map snapshot and lie 30–250 m from the NDW positions under different operator names, so they cannot be matched one by one. Outside the municipality, NDW sites within 30 m of a pilot charger are skipped (`--dedupe-metres`). Use `--include-pilot-area` to show both sets in Amsterdam.
- **Speed:** `/stations/within` uses a bounding-box test on an indexed latitude/longitude pair before the exact SpatiaLite polygon test.

## What works now

- The map, from all of Europe (zoom 4) to street level (16). Below zoom 12 it shows server-side aggregate bubbles from `/stations/density`; from zoom 12 it shows clustered single chargers, each with a popup naming its source. Areas can be drawn from zoom 12.
- Location search suggests every city in `REGIONS` with its site count from `/stations/coverage`. Type-ahead uses PDOK for the whole Netherlands and Photon (OpenStreetMap) for Germany and the other covered cities.
- Load profiles, flexibility and KPIs with the **simple**, **spatial** and **CPFT** session sources. These generate sessions from charger power and type, so they need nothing local.

## Known limits

- **Observed sessions:** these exist only for the Amsterdam pilot chargers. The stored-session (`database`) source returns zero load elsewhere.
- **Time zone:** profiles use one time zone (`SESSION_SCENARIO_TIMEZONE`, Europe/Amsterdam). London and Lisbon local time is one hour earlier.
- **Spatial sampler:** its neighbourhood atlas covers only Amsterdam. Other chargers fall back to the generic "mixed" profile, and the scenario metadata shows `outside_atlas`.
- **Transformers:** these are Liander data for Amsterdam only, so grid KPIs are empty elsewhere. Do not run `add_grid_connections` after an import, because it links every column to the nearest transformer within 50 km.
- **OSM completeness:** OSM undercounts chargers in some cities. A check on 14 Oct 2026 found 1,395 London stations, with about 30% missing an operator tag. Only 12% of London and 23% of Milan stations had plug (socket) tags. Treat UK and Italian counts as a lower bound.

## Plan

1. **Done: one data model for all sources.** Download, provenance manifest, tagged import with stable IDs, map clustering, city search.
2. **Local time and grid context.** Derive the time zone and the electricity-mix zone from the selected chargers' country, instead of the Amsterdam defaults in `views.py` and `kpi/user.py`. Show "No grid data here" on the transformer layer outside Amsterdam.
3. **Spatial priors outside Amsterdam.** Use a pan-European population grid (Eurostat GEOSTAT 1 km or GHSL) in `SpatialAtlas`, so the spatial sampler is not generic outside Amsterdam. Keep CBS neighbourhoods for the Netherlands.
4. **Better coverage where OSM is thin.** Switzerland, France and Finland are done. Next: Belgium's DATEX II feeds on transportdata.be, Spain's national access point (nap.dgt.es; the catalogue's CSV link is a web form), NOBIL for Norway and Sweden (free key), and Austria's E-Control API (key and usage terms). Add Open Charge Map with a free API key for the UK and Italy. Add the MOBI.E OCPI feed for Portugal once its endpoint is confirmed. Add the national access points (Mobilithek, PUN) when they publish open endpoints. Each new source only needs a parser in `backend/charger_sources.py`.
5. **Live occupancy.** NDW publishes EVSE status. Snapshots taken every 15 minutes, like the `epiot-session-scenarios` timer, would give observed occupancy for calibrating arrival rates across the Netherlands.
6. **Scheduled refresh.** Run `update_charger_data.py` monthly with a systemd timer. BNetzA publishes monthly and the script finds the newest CSV link itself.
