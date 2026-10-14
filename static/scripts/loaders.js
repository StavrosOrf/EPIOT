import { createSiteLayer } from "./charger_sites.js";
import { createDensityLoader } from "./map_density.js";

let lastRequested = null; // the polygon of the most recent request, forgotten again if it fails
let requestedPolygons = []; // Array to store previously requested polygons as GeoJSON Features


const response = await fetch("/marker_icon");
const data = await response.json();
// Extract the icon URLs
const chargerIconUrl = data.charge_icon;
const transformerIconUrl = data.transformer_icon;

function geojsonToMartinez(polygon) {
  // Convert GeoJSON Polygon to a format compatible with martinez-polygon-clipping
  return polygon.geometry.coordinates;
}

function martinezToGeojson(coordinates) {
  // Convert Martinez output back to GeoJSON Polygon
  if (!coordinates || coordinates.length === 0) return null;

  return {
    type: "Feature",
    geometry: {
      type: "Polygon",
      coordinates: coordinates[0], // Martinez output is an array of polygons
    },
    properties: {},
  };
}

function getNewBoundsQueryBody(map) {
  const bounds = map.getBounds();
  const currentSouthWest = bounds.getSouthWest();
  const currentNorthEast = bounds.getNorthEast();

  // Define the new polygon as a GeoJSON Feature
  const newPolygon = {
    type: "Feature",
    geometry: {
      type: "Polygon",
      coordinates: [
        [
          [currentSouthWest.lng, currentSouthWest.lat],
          [currentSouthWest.lng, currentNorthEast.lat],
          [currentNorthEast.lng, currentNorthEast.lat],
          [currentNorthEast.lng, currentSouthWest.lat],
          [currentSouthWest.lng, currentSouthWest.lat], // Close the polygon
        ],
      ],
    },
    properties: {},
  };

  // Convert newPolygon to martinez-compatible format
  let finalPolygon = geojsonToMartinez(newPolygon);

  // Subtract previously requested polygons
  for (const requestedPolygon of requestedPolygons) {
    if (finalPolygon && requestedPolygon) {
      try {
        const martinezRequestedPolygon = geojsonToMartinez(requestedPolygon);
        finalPolygon = martinez.diff(finalPolygon, martinezRequestedPolygon);

        if (!finalPolygon || finalPolygon.length === 0) {
          console.warn("No new area left after subtraction.");
          return null;
        }
      } catch (error) {
        console.error("Error in martinez.diff:", error, {
          finalPolygon,
          requestedPolygon,
        });
        return null;
      }
    }
  }

  let finalGeoJsonPolygon = null;
  if (requestedPolygons.length !== 0) {
    // Convert final result back to GeoJSON
    finalGeoJsonPolygon = martinezToGeojson(finalPolygon);
  } else {
    finalGeoJsonPolygon = newPolygon;
  }

  if (!finalGeoJsonPolygon) {
    console.warn("Final polygon is invalid or empty.");
    return null;
  }

  // Add the new polygon to the list of requested polygons
  requestedPolygons.push(newPolygon);
  lastRequested = newPolygon;
  return finalGeoJsonPolygon.geometry;
}

// Below this zoom the map shows server-side aggregates instead of single
// chargers: a country view would otherwise mean hundreds of thousands of points
export const DETAIL_ZOOM = 12;

// Compact count for bubble badges: 950, 1.2k, 12k, 1.4M
export const compactCount = (n) =>
  n < 1000 ? String(n)
  : n < 1e6 ? `${(n / 1000).toFixed(n < 10000 ? 1 : 0).replace(/\.0$/, "")}k`
  : `${(n / 1e6).toFixed(1).replace(/\.0$/, "")}M`;

// Count bubble shared by marker clusters and overview aggregates; an amber
// ring marks fast-charging hubs (half or more of the points >= 50 kW; national
// shares differ widely, e.g. 3.5% in the Netherlands and 24% in Germany)
export function bubbleIcon(count, fastShare = 0) {
  const size = count < 25 ? "sm" : count < 250 ? "md" : count < 5000 ? "lg" : "xl";
  const px = { sm: 34, md: 40, lg: 48, xl: 56 }[size];
  return L.divIcon({
    html: `<span>${compactCount(count)}</span>`,
    className: `charger-cluster charger-cluster--${size}${fastShare >= 0.5 ? " charger-cluster--fast" : ""}`,
    iconSize: L.point(px, px),
  });
}

export const fetchDensity = createDensityLoader({
  marker: (...args) => L.marker(...args), icon: bubbleIcon, detailZoom: DETAIL_ZOOM,
});

// One site controller per charger layer: groups points by location and fans
// them out on click (see charger_sites.js)
const siteControllers = new WeakMap();
export function chargerSites(map, chargerLayer) {
  if (!siteControllers.has(chargerLayer)) {
    siteControllers.set(chargerLayer, createSiteLayer(map, chargerLayer, chargerIconUrl));
  }
  return siteControllers.get(chargerLayer);
}

// Function to fetch charging stations from backend
async function fetchChargingStations(
  map,
  queryBody,
  chargerLayer,
  vizualizeChargers
) {

  const sites = chargerSites(map, chargerLayer);

  // Fetch the charging stations using the backend API
  const requested = lastRequested;
  try {
    const response = await fetch("/stations/within", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(queryBody),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    sites.add((await response.json()).features);
  } catch (error) {
    // Forget the area so the next pan or zoom asks for it again
    requestedPolygons = requestedPolygons.filter((polygon) => polygon !== requested);
    console.error("Error fetching data:", error);
  }

  // The user may have zoomed out to the overview while this was loading
  if (vizualizeChargers && map.getZoom() >= DETAIL_ZOOM) map.addLayer(chargerLayer);
  else map.removeLayer(chargerLayer);
}

// Transformers are only fetched while their layer is switched on, and per
// viewport: the Amsterdam view alone is several megabytes of them.
const loadedTransformerBounds = [];
const transformerIds = new Set();
let transformerRequest = 0;

async function fetchTransformers(map, transformerLayer, vizualizeTransformers) {
  if (!vizualizeTransformers || map.getZoom() < DETAIL_ZOOM) return;
  const view = map.getBounds();
  if (loadedTransformerBounds.some((loaded) => loaded.contains(view))) return;
  // Fetch a little beyond the view so small pans stay inside the loaded area
  const bounds = view.pad(0.25);
  const sw = bounds.getSouthWest();
  const ne = bounds.getNorthEast();
  const request = ++transformerRequest;

  const transformerIcon = L.icon({
    iconUrl: transformerIconUrl,
    iconSize: [25, 25],
    iconAnchor: [12, 25],
    popupAnchor: [1, -25],
  });

  try {
    const response = await fetch("/features/transformers/within", {
      method: "POST",
      body: JSON.stringify({
        type: "Polygon",
        coordinates: [[[sw.lng, sw.lat], [sw.lng, ne.lat], [ne.lng, ne.lat], [ne.lng, sw.lat], [sw.lng, sw.lat]]],
        tr_type: "Middle",
      }),
    });
    const data = await response.json();
    const markers = [];
    for (const element of data.features) {
      const props = element.properties;
      if (transformerIds.has(props.id)) continue;
      transformerIds.add(props.id);
      const coords = element.geometry.coordinates;
      const marker = L.marker([coords[1], coords[0]], {
        icon: transformerIcon,
        markerType: "transformer",
        id: props.id,
      });
      marker.bindPopup(`
                  <strong>Transformer</strong><br>
                  <strong>Type:</strong> ${props.type || "Unknown"}<br>
                `);
      markers.push(marker);
    }
    markers.forEach((marker) => transformerLayer.addLayer(marker));
    if (request === transformerRequest) loadedTransformerBounds.push(bounds);
  } catch (error) {
    console.error("Error fetching transformer data:", error);
  }
  if (vizualizeTransformers && map.getZoom() >= DETAIL_ZOOM) map.addLayer(transformerLayer);
  else map.removeLayer(transformerLayer);
}

export async function fetch_markers(
  map,
  chargerLayer,
  transformerLayer,
  vizualizeChargers,
  vizualizeTransformers
) {
  // Overview zooms use fetchDensity; skip here so the area is not marked as loaded
  if (map.getZoom() < DETAIL_ZOOM) return;
  fetchTransformers(map, transformerLayer, vizualizeTransformers);
  var queryBody = getNewBoundsQueryBody(map);
  if (!queryBody) {
    return;
  }
  fetchChargingStations(map, queryBody, chargerLayer, vizualizeChargers);
}


// Function to generate heatmap data from charger markers
function generateHeatmapData(chargerLayer) {
  const heatmapData = [];

  chargerLayer.eachLayer((layer) => {
    if (layer instanceof L.Marker) {
      // Extract the marker's latitude and longitude
      const latLng = layer.getLatLng();

      // Push the lat, lng, and intensity to the heatmap data
      // Assign a default intensity (e.g., 0.5) or calculate it based on your logic
      heatmapData.push([latLng.lat, latLng.lng, 0.5]); // 0.5 is the intensity
    }
  });

  return heatmapData;
}

export function calculateFlexibility(chargerLayer) {
  // Heatmap Data
  const heatmapData = generateHeatmapData(chargerLayer);
  // Create the Heatmap Layer
  var heatmapLayer = L.heatLayer(heatmapData, {
    radius: 25, // Radius of each point
    blur: 15, // Blur intensity
    maxZoom: 16, // Maximum zoom level for intensity
    minZoom: 12, // Minimum zoom level for intensity
    gradient: {
      // Custom gradient for the heatmap
      0.4: "blue",
      0.6: "lime",
      0.8: "red",
    },
  });

  return heatmapLayer;
}
