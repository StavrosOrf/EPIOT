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
  return finalGeoJsonPolygon.geometry;
}

// Function to fetch charging stations from backend
async function fetchChargingStations(
  map,
  queryBody,
  chargerLayer,
  vizualizeChargers
) {

  // Define Leaflet icons using the fetched URLs
  const chargerIcon = L.icon({
    iconUrl: chargerIconUrl,
    iconSize: [25, 25], // Adjust as needed
    iconAnchor: [12.5, 25],
    popupAnchor: [1, -25],
  });

  // Fetch the charging stations using the backend API
  await fetch("/stations/within", {
    method: "POST",
    body: JSON.stringify(queryBody),
  })
    .then((response) => response.json())
    .then((data) => {
      // Add markers to the map for each charging station
      data.features.forEach((element) => {
        const props = element.properties;
        const coords = element.geometry.coordinates;
        const popupContent = `
                  <strong>Charging Station</strong><br>
                  <strong>Name:</strong> ${props.name || "Unknown"}<br>
                  <strong>Id:</strong> ${props.id || "Unknown"}<br>
                  <strong>Operator:</strong> ${props.operator || "Unknown"}<br>
                  <strong>Capacity:</strong> ${props.power || "Unknown"} kW<br>
                `;
        const marker = L.marker([coords[1], coords[0]], {
          icon: chargerIcon,
          markerType: "charger",
          id: props.id,
        });
        marker.bindPopup(popupContent);
        chargerLayer.addLayer(marker);
      });
    })
    .catch((error) => console.error("Error fetching data:", error));

  if (vizualizeChargers) map.addLayer(chargerLayer);
  else map.removeLayer(chargerLayer);
}

// Function to fetch transformers from backend
async function fetchTransformers(
  map,
  queryBody,
  transformerLayer,
  vizualizeTransformers
) {
 
  const transformerIcon = L.icon({
    iconUrl: transformerIconUrl,
    iconSize: [25, 25], // Adjust as needed
    iconAnchor: [12, 25],
    popupAnchor: [1, -25],
  });

  // Get the current map bounds
  const bounds = map.getBounds();
  const southWest = bounds.getSouthWest();
  const northEast = bounds.getNorthEast();
  queryBody.tr_type = "Middle";

  // Fetch the transformer data using the backend API
  await fetch("/features/transformers/within", {
    method: "POST",
    body: JSON.stringify(queryBody),
  })
    .then((response) => response.json())
    .then((data) => {

      // Add markers to the map for each transformer
      data.features.forEach((element) => {
        const props = element.properties;
        const coords = element.geometry.coordinates;
        const popupContent = `
                  <strong>Transformer</strong><br>
                  <strong>ID:</strong> ${props.id || "Unknown"}<br>
                  <strong>Type:</strong> ${props.type || "Unknown"}<br>
                `;

        const marker = L.marker([coords[1], coords[0]], {
          icon: transformerIcon,
          markerType: "transformer",
          id: props.id,
        });
        marker.bindPopup(popupContent);
        transformerLayer.addLayer(marker);
      });
    })
    .catch((error) => console.error("Error fetching transformer data:", error));

  if (vizualizeTransformers) map.addLayer(transformerLayer);
  else map.removeLayer(transformerLayer);
}

export async function fetch_markers(
  map,
  chargerLayer,
  transformerLayer,
  vizualizeChargers,
  vizualizeTransformers
) {
  var queryBody = getNewBoundsQueryBody(map);
  if (!queryBody) {
    return;
  }
  fetchChargingStations(map, queryBody, chargerLayer, vizualizeChargers);
  fetchTransformers(map, queryBody, transformerLayer, vizualizeTransformers);
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
    minZoom: 14, // Minimum zoom level for intensity
    gradient: {
      // Custom gradient for the heatmap
      0.4: "blue",
      0.6: "lime",
      0.8: "red",
    },
  });

  return heatmapLayer;
}