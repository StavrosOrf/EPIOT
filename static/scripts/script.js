// import { h3ToPolygon, generateHexGrid } from "./hexUtils.js";
import { fetch_markers, calculateFlexibility, fetchDensity, bubbleIcon, chargerSites, DETAIL_ZOOM } from "./loaders.js";
import {
  createGraph,
  createFlexGraph,
  createUserKPIGraph,
  createGridKPIGraph,
  createMobilityKPIGraph,
  createCityKPIGraph,
  createEnvironmentKPIGraph,
  showGraphMessage,
} from "./plotter.js";
import { animateSelectMessage, generateAndDownloadExcel } from "./utils.js";
import { get_KPIs } from "./data_fetch.js";
import { pickerOptions } from "./date_selection.js";
import { renderEnvironmentSummary } from "./environment_summary.js";
import { initLocationSearch } from "./location_search.js";

// Initialize Map using Leaflet.js
var map = L.map("map", { zoomControl: false }).setView([52.3676, 4.9041], 16); // Centered on Amsterdam
L.control.zoom({ position: "topright" }).addTo(map);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);
// Open-data licences ask for the charger sources to be credited on the map
map.attributionControl.addAttribution(
  'Chargers: <a href="https://docs.ndw.nu/en/faq/DOT-NL/" target="_blank" rel="noopener">NDW</a>, ' +
  '<a href="https://www.bundesnetzagentur.de/DE/Fachthemen/ElektrizitaetundGas/E-Mobilitaet/start.html" target="_blank" rel="noopener">Bundesnetzagentur</a>, ' +
  '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OSM</a> (ODbL), ' +
  '<a href="https://opendata.swiss/en/dataset/ladestationen" target="_blank" rel="noopener">BFE</a>, ' +
  '<a href="https://www.data.gouv.fr/datasets/base-nationale-des-irve-data-gouv-infrastructures-de-recharge-pour-vehicules-electriques-donnees-statiques" target="_blank" rel="noopener">data.gouv.fr</a>, ' +
  '<a href="https://www.digitraffic.fi/en/road-traffic/afir/" target="_blank" rel="noopener">Fintraffic</a> (CC BY 4.0)'
);

// Keep --header-h in sync with the app bar, which wraps on small screens, so
// the floating controls and the analysis panel are positioned below it.
const appBar = document.getElementById("header-bar");
function syncHeaderHeight() {
  document.documentElement.style.setProperty(
    "--header-h",
    `${appBar.offsetHeight}px`
  );
}
new ResizeObserver(syncHeaderHeight).observe(appBar);
syncHeaderHeight();

// restrict maximum zoom level to prevent too many hexagons
map.setMaxZoom(16);
// Zoom 4 fits Europe; below DETAIL_ZOOM the map shows aggregated bubbles
map.setMinZoom(4);

// Draw each cluster on one of its own chargers, not at their average: the
// average of two river banks or of coastal towns lies in the water between them
const recalculateBounds = L.MarkerCluster.prototype._recalculateBounds;
L.MarkerCluster.prototype._recalculateBounds = function () {
  recalculateBounds.call(this);
  const mean = this._wLatLng;
  if (!mean) return;
  const scale = Math.cos((mean.lat * Math.PI) / 180);
  let best = null;
  let bestDistance = Infinity;
  // Child clusters are already placed on one of their chargers
  for (const child of [...this._markers, ...this._childClusters]) {
    const at = child._latlng;
    const distance = (at.lat - mean.lat) ** 2 + ((at.lng - mean.lng) * scale) ** 2;
    if (distance < bestDistance) {
      bestDistance = distance;
      best = at;
    }
  }
  if (best) this._latlng = best;
};

// Charging sites are clustered: a city view can hold thousands of points.
// At street level (16) every site stands alone; its points fan out on click
// (charger_sites.js), so the cluster library's own spiderfy stays off.
const chargerLayer = L.markerClusterGroup({
  chunkedLoading: false,
  showCoverageOnHover: false,
  spiderfyOnMaxZoom: false,
  disableClusteringAtZoom: 16,
  maxClusterRadius: (zoom) => (zoom >= 14 ? 48 : 64),
  iconCreateFunction(cluster) {
    let count = 0;
    let fast = 0;
    for (const site of cluster.getAllChildMarkers()) {
      count += site.options.points.length;
      fast += site.options.points.filter((p) => Number(p.power) >= 50).length;
    }
    return bubbleIcon(count, fast / count);
  },
});
// Server-side aggregates shown instead of chargerLayer below DETAIL_ZOOM.
// Clustered too, so neighbouring bubbles merge instead of overlapping; a
// merged bubble shows the summed charging points
const densityLayer = L.markerClusterGroup({
  showCoverageOnHover: false,
  spiderfyOnMaxZoom: false,
  maxClusterRadius: 56,
  iconCreateFunction(cluster) {
    let points = 0;
    let fast = 0;
    for (const m of cluster.getAllChildMarkers()) {
      points += m.options.points;
      fast += m.options.fast;
    }
    return bubbleIcon(points, fast / points);
  },
});
var vizualizeChargers = true;

// three colors for the drawn areas
const colors = ["#4CAF50", "#8A0606", "#3357FF"];
let colorIndex = -1;
let area_index = 0;

const transformerLayer = L.layerGroup();
var vizualizeTransformers = false;

var heatmapLayer = null;
var vizualizeFlexHeatmap = false;

let charger_ids_list = [];
let transformer_ids_list = [];
let connected_charger_ids_list = [];
let load_profile_data = [];
let kpi_data_list = [];

var active_tab = "Load Profiles";
// get today's date
var today = new Date();
const starting_date = new Date(2025, 8, 1);
let pickerRangeMode = false;
let selectedTargetDate = today;
let selectedKpiRange = null;
// Initialize Flatpickr on the input field
let datepicker = flatpickr("#datepicker", pickerOptions(false, starting_date, today, [today], onDateSelectionChange));

let dateInput = document.getElementById("datepicker");
let active_kpi = "user_kpi";

animateSelectMessage("Draw an area on the map to start");

// Initialize Leaflet.draw
var drawnItems = new L.FeatureGroup();
map.addLayer(drawnItems);
let selected_polygons = [];
let selected_area_names = [];
let draw_control_enabled = true;

// Reuse existing FeatureGroup if you already have it; otherwise create one.
drawnItems = (window.EPIOT && window.EPIOT.drawnItems)
  ? window.EPIOT.drawnItems
  : new L.FeatureGroup().addTo(map);
window.EPIOT = window.EPIOT || {};
window.EPIOT.drawnItems = drawnItems;

// (Optional) If you added a default draw control earlier, remove it now.
// if (window.EPIOT.drawControl) map.removeControl(window.EPIOT.drawControl);
if (window.EPIOT?.drawControl) {
  map.removeControl(window.EPIOT.drawControl);
}


// Create handlers
const polygonHandler = new L.Draw.Polygon(map, { showArea: true, allowIntersection: false, shapeOptions: { color: '#4CAF50' } });
const rectangleHandler = new L.Draw.Rectangle(map, { shapeOptions: { color: '#4CAF50' } });
const deleteHandler = new L.EditToolbar.Delete(map, { featureGroup: drawnItems });

// Buttons
const btnPoly = document.getElementById('btn-draw-polygon');
const btnRect = document.getElementById('btn-draw-rectangle');
const btnDel = document.getElementById('btn-draw-delete');

let activeHandler = null;
function setActive(btn) {
  [btnPoly, btnRect, btnDel].forEach(b => b && b.classList.remove('active'));
  btn && btn.classList.add('active');
}
function enable(handler, btn) {
  // Areas are analysed per charger, so drawing starts at city level
  if (handler !== deleteHandler && map.getZoom() < DETAIL_ZOOM) {
    clearActive();
    showHint("Zoom in to city level, or pick a city in the search, to draw an area.", { timeout: 4000 });
    return false;
  }
  // Clicking the active tool again switches it off
  if (activeHandler === handler) {
    clearActive();
    hideHint();
    return false;
  }
  if (activeHandler && activeHandler.disable) activeHandler.disable();
  handler.enable();
  activeHandler = handler;
  setActive(btn);
  return true;
}
function clearActive() {
  const handler = activeHandler;
  activeHandler = null;
  setActive(null);
  if (handler && handler.disable) handler.disable();
}

// When a new shape is created, add to group and exit draw mode
// map.on(L.Draw.Event.CREATED, (e) => {
//   drawnItems.addLayer(e.layer);
//   clearActive();
// });

// // When deletion finishes or items are deleted, exit delete mode
// map.on('draw:deleted', clearActive);
// map.on('draw:deletestop', clearActive);

// (Good citizen) If you previously had a draw:created listener with custom logic,
// keep it; adding to drawnItems here won’t break your existing code.

const hintEl = document.getElementById('draw-hint');
const drawTools = document.getElementById('draw-toolbar-wrap');
const drawCount = document.getElementById('draw-count');
let hintTimer = null;
let alertTimer = null;

function showHint(text, { alert = false, timeout = 0 } = {}) {
  if (!hintEl) return;
  clearTimeout(hintTimer);
  if (alert) {
    hintEl.innerHTML = `<strong>Start here.</strong> ${text}`;
  } else {
    hintEl.textContent = text;
  }
  hintEl.classList.toggle('draw-hint--alert', alert);
  hintEl.hidden = false;
  if (timeout) hintTimer = setTimeout(hideHint, timeout);
}

function hideHint() {
  if (!hintEl) return;
  clearTimeout(hintTimer);
  hintEl.hidden = true;
}

// Pulse the draw tools while there is nothing to analyse yet
function syncDrawPrompt() {
  const empty = selected_polygons.length === 0;
  drawTools?.classList.toggle('draw-tools--prompt', empty);
  if (drawCount) drawCount.textContent = `${selected_polygons.length}/3`;
  if (empty) document.getElementById('calc-button')?.classList.remove('glow');
}

// Analyse was pressed without an area: shake the draw tools and explain
function flagDrawTools() {
  if (!drawTools) return;
  clearActive();
  drawTools.classList.remove('draw-tools--alert');
  void drawTools.offsetWidth; // restart the animation
  drawTools.classList.add('draw-tools--alert');
  clearTimeout(alertTimer);
  alertTimer = setTimeout(() => drawTools.classList.remove('draw-tools--alert'), 4000);
  showHint('Draw a polygon or rectangle around the area you want to analyse.', {
    alert: true,
    timeout: 4000,
  });
}

// Update your button listeners:
btnPoly?.addEventListener('click', () => {
  drawTools?.classList.remove('draw-tools--alert');
  if (enable(polygonHandler, btnPoly)) {
    showHint('Polygon: click to add points, then click the first point (or double-click) to finish. Click the tool again or press Esc to cancel.');
  }
});

btnRect?.addEventListener('click', () => {
  drawTools?.classList.remove('draw-tools--alert');
  if (enable(rectangleHandler, btnRect)) {
    showHint('Rectangle: click and drag on the map, release to finish. Click the tool again or press Esc to cancel.');
  }
});

btnDel?.addEventListener('click', () => {
  if (enable(deleteHandler, btnDel)) {
    showHint('Delete: click areas to remove them. Click the trash again or press Esc when done.');
  }
});

// When a draw finishes or mode exits, hide the hint
map.on(L.Draw.Event.CREATED, hideHint);
map.on('draw:drawstop', hideHint);
map.on('draw:deletestop', hideHint);
map.on('draw:editstop', hideHint);

// When a shape is finished or deletion ends, release the toolbar button
map.on(L.Draw.Event.CREATED, clearActive);
map.on('draw:drawstop', clearActive);
map.on('draw:deletestop', clearActive);

// Also hide on ESC, and close the analysis panel if it is open
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    if (window.EPIOT.isLandingOpen?.()) return;
    hideHint();
    clearActive?.();
    if (document.body.classList.contains("analysis-open")) closePanel();
  }
});


// Add the draw control to the map
var drawControl = new L.Control.Draw({
  position: "topleft", // Place control in the top-left corner
  draw: {
    polyline: false, // Disable polyline tool
    circle: false, // Disable circle tool
    marker: false, // Disable marker tool
    circlemarker: false, // Disable circle marker tool
    rectangle: {
      shapeOptions: {
        color: "#3D3232", // Green border for rectangle
        weight: 5,
        zIndex: 10000,
        fillOpacity: 0.3, // Transparent fill
      },
    },
    polygon: {
      allowIntersection: false, // Prevent self-intersections
      shapeOptions: {
        color: "#3D3232", // Green border for polygon
        weight: 5,
        zIndex: 10000,
        fillOpacity: 0.3, // Transparent fill
      },
    },
  },
  edit: {
    featureGroup: drawnItems, // Allow editing of drawn shapes
    edit: false, // Disable the edit tool
    remove: true, // Disable the delete tool
  },
});
map.addControl(drawControl); // Add the control to the map

// Handle drawing events
map.on("draw:deleted", function (event) {
  selected_polygons = [];
  selected_area_names = [];
  // select polygons from all drawn polygons

  console.log("Deletion event:", event);

  // for each deleted area remove the marker where properties.name is the same as the deleted area
  event.layers.eachLayer(function (layer) {
    let name_to_delete = layer.feature.properties.name;

    // from drawnItems remove the layer with the same name as the deleted area
    drawnItems.eachLayer(function (temp_layer) {
      if (temp_layer.feature.properties.name == name_to_delete) {
        drawnItems.removeLayer(temp_layer);
      }
    });
  });

  drawnItems.eachLayer(function (temp_layer) {
    // if it has propery -layer return
    if (temp_layer.feature.properties.type == "marker") {
      selected_area_names.push(temp_layer.feature.properties.name);
      return;
    }

    var latLngs = temp_layer.getLatLngs(); // Returns an array of lat/lng points

    // Format the coordinates as GeoJSON
    var polygonCoordinates = latLngs[0].map((latlng) => [
      latlng.lng,
      latlng.lat,
    ]); // Convert to [lng, lat]

    // Ensure the ring is closed
    if (
      polygonCoordinates.length > 0 &&
      (polygonCoordinates[0][0] !==
        polygonCoordinates[polygonCoordinates.length - 1][0] ||
        polygonCoordinates[0][1] !==
        polygonCoordinates[polygonCoordinates.length - 1][1])
    ) {
      polygonCoordinates.push(polygonCoordinates[0]); // Close the ring
    }

    // Create a GeoJSON polygon
    var temp_polygon = {
      type: "Feature",
      geometry: {
        type: "Polygon",
        coordinates: [polygonCoordinates],
      },
    };
    selected_polygons.push(temp_polygon);
  });

  console.log("selected_polygons after deletion event:", selected_polygons);
  console.log("selected_area_names after deletion event:", selected_area_names);

  if (selected_polygons.length == 0) {
    animateSelectMessage("Draw an area on the map to start");
  } else {
    animateSelectMessage(`Area removed. ${selected_polygons.length} of 3 selected`);
  }
});

map.on("draw:deletestop", function () {
  console.log("Deletion mode deactivated");
  selected_polygons = [];
  selected_area_names = [];
  // select polygons from all drawn polygons

  drawnItems.eachLayer(function (temp_layer) {
    // if it has propery -layer return
    if (temp_layer.feature.properties.type == "marker") {
      // for every marker add the name to the selected_area_names only if there is a drawnitem with the same name
      let name_to_delete = temp_layer.feature.properties.name;
      let found = false;
      drawnItems.eachLayer(function (temp_layer) {
        if (
          temp_layer.feature.properties.name == name_to_delete &&
          temp_layer.feature.properties.type == "area"
        ) {
          found = true;
        }
      });
      if (found) {
        selected_area_names.push(temp_layer.feature.properties.name);
      } else {
        drawnItems.removeLayer(temp_layer);
      }

      return;
    }

    var latLngs = temp_layer.getLatLngs(); // Returns an array of lat/lng points

    // Format the coordinates as GeoJSON
    var polygonCoordinates = latLngs[0].map((latlng) => [
      latlng.lng,
      latlng.lat,
    ]); // Convert to [lng, lat]

    // Ensure the ring is closed
    if (
      polygonCoordinates.length > 0 &&
      (polygonCoordinates[0][0] !==
        polygonCoordinates[polygonCoordinates.length - 1][0] ||
        polygonCoordinates[0][1] !==
        polygonCoordinates[polygonCoordinates.length - 1][1])
    ) {
      polygonCoordinates.push(polygonCoordinates[0]); // Close the ring
    }

    // Create a GeoJSON polygon
    var temp_polygon = {
      type: "Feature",
      geometry: {
        type: "Polygon",
        coordinates: [polygonCoordinates],
      },
    };
    selected_polygons.push(temp_polygon);
  });

  console.log(
    "selected_polygons after deletion event completed:",
    selected_polygons
  );
  console.log(
    "selected_area_names after deletion event completed:",
    selected_area_names
  );

  if (selected_polygons.length == 0) {
    animateSelectMessage("Draw an area on the map to start");
  } else {
    animateSelectMessage(`Area removed. ${selected_polygons.length} of 3 selected`);
  }
  map.fire("draw:stop");
});

map.on(L.Draw.Event.CREATED, function (event) {
  var layer = event.layer;
  // Clear any existing layers to ensure only one shape is on the map
  // drawnItems.clearLayers();

  console.log("Creation event:", event);

  if (selected_polygons.length > 2) {
    animateSelectMessage("You can compare up to 3 areas. Delete one to draw another");
    return;
  }

  if (layer instanceof L.Polygon || layer instanceof L.Rectangle) {
    // Get the polygon or rectangle's coordinates
    var latLngs = layer.getLatLngs(); // Returns an array of lat/lng points

    // Format the coordinates as GeoJSON
    var polygonCoordinates = latLngs[0].map((latlng) => [
      latlng.lng,
      latlng.lat,
    ]); // Convert to [lng, lat]

    // Ensure the ring is closed
    if (
      polygonCoordinates.length > 0 &&
      (polygonCoordinates[0][0] !==
        polygonCoordinates[polygonCoordinates.length - 1][0] ||
        polygonCoordinates[0][1] !==
        polygonCoordinates[polygonCoordinates.length - 1][1])
    ) {
      polygonCoordinates.push(polygonCoordinates[0]); // Close the ring
    }

    // Create a GeoJSON polygon
    var polygon = {
      type: "Feature",
      geometry: {
        type: "Polygon",
        coordinates: [polygonCoordinates],
      },
    };

    console.log("Polygon shape:", polygon);

    // Check if the polygon is valid using Turf.js
    var isValid = turf.booleanValid(polygon);
    if (!isValid) {
      console.error("Invalid polygon!");
      animateSelectMessage("That shape is invalid (edges cross). Please redraw it");
      return; // Exit the handler
    }

    // Add the new layer to the map
    // drawnItems.addLayer(layer);

    colorIndex = (colorIndex + 1) % colors.length;
    // Change the style of the layer
    layer.setStyle({
      color: colors[colorIndex], // Border color
      weight: 5, // Border thickness
      fillOpacity: 0.5, // Fill transparency (0: transparent, 1: solid)
      zIndex: 10000,
    });
    area_index = area_index + 1;
    var shapeName = "Area " + area_index.toString();
    // Determine the center of the shape
    let center;
    if (layer.getBounds) {
      // For polygons and rectangles
      // get center shifted slightly left and top
      center = layer.getBounds().getCenter();
    } else if (layer.getLatLng) {
      // For circles and markers
      center = layer.getLatLng();
    }

    // Add a DivIcon at the center
    if (center) {
      const label = L.divIcon({
        className: "shape-label",
        html: `<span>${shapeName}</span>`,
        iconSize: [0, 0], // No icon size, only text
      });

      let marker = L.marker(center, { icon: label, interactive: false });
      // Combine the shape and the marker into a FeatureGroup
      // const group = L.featureGroup([layer, marker]);
      drawnItems.addLayer(layer);

      // Add the FeatureGroup to the drawn items layer
      drawnItems.addLayer(marker);
      marker.feature = {
        properties: {
          name: shapeName,
          type: "marker",
        },
      };
    }

    // console.log("Drawn items:", drawnItems);

    layer.feature = {
      properties: {
        name: shapeName,
        type: "area",
      },
    };

    console.log("Valid polygon!");
    selected_polygons = [];
    selected_area_names = [];

    // select polygons from all drawn polygons
    drawnItems.eachLayer(function (temp_layer) {
      // if it has propery -layer return
      if (temp_layer.feature.properties.type == "marker") {
        selected_area_names.push(temp_layer.feature.properties.name);
        return;
      }

      var latLngs = temp_layer.getLatLngs(); // Returns an array of lat/lng points

      // Format the coordinates as GeoJSON
      var polygonCoordinates = latLngs[0].map((latlng) => [
        latlng.lng,
        latlng.lat,
      ]); // Convert to [lng, lat]

      // Ensure the ring is closed
      if (
        polygonCoordinates.length > 0 &&
        (polygonCoordinates[0][0] !==
          polygonCoordinates[polygonCoordinates.length - 1][0] ||
          polygonCoordinates[0][1] !==
          polygonCoordinates[polygonCoordinates.length - 1][1])
      ) {
        polygonCoordinates.push(polygonCoordinates[0]); // Close the ring
      }

      // Create a GeoJSON polygon
      var temp_polygon = {
        type: "Feature",
        geometry: {
          type: "Polygon",
          coordinates: [polygonCoordinates],
        },
      };
      selected_polygons.push(temp_polygon);
    });

    console.log("selected_polygons:", selected_polygons);
    console.log("selected_area_names:", selected_area_names);

    animateSelectMessage(`${selected_polygons.length} of 3 areas selected. Ready to analyse`);

    // Add glowing effect to the Analyse button
    const analyseButton = document.getElementById("calc-button");
    if (analyseButton) {
      analyseButton.classList.add("glow");
    }
  }
});

// Registered after the handlers above, so selected_polygons is up to date
map.on("draw:created draw:deleted draw:deletestop", syncDrawPrompt);

// Load the charger and transformer markers
fetch_markers(
  map,
  chargerLayer,
  transformerLayer,
  vizualizeChargers,
  vizualizeTransformers
);

// Single markers (and drawing) at city level, aggregate bubbles above it
function syncDetailLayers() {
  const detail = map.getZoom() >= DETAIL_ZOOM;
  const show = (layer, visible) => (visible ? map.addLayer(layer) : map.removeLayer(layer));
  show(chargerLayer, vizualizeChargers && detail);
  show(densityLayer, vizualizeChargers && !detail);
  show(transformerLayer, vizualizeTransformers && detail);
}

let wasDetail = map.getZoom() >= DETAIL_ZOOM;
map.on("zoomend", function () {
  syncDetailLayers();
  const detail = map.getZoom() >= DETAIL_ZOOM;
  if (wasDetail && !detail) {
    showHint("Overview: bubbles count charging points. Zoom in to city level to see single chargers and draw areas.", { timeout: 4500 });
  }
  wasDetail = detail;
});

fetchDensity(map, densityLayer);

map.on("load moveend", function () {
  fetchDensity(map, densityLayer);
  fetch_markers(
    map,
    chargerLayer,
    transformerLayer,
    vizualizeChargers,
    vizualizeTransformers
  );
  //  wait for the markers to load before calculating flexibility
  if (vizualizeFlexHeatmap) {
    // remove the existing heatmap layer
    map.removeLayer(heatmapLayer);
    heatmapLayer = calculateFlexibility(chargerLayer);
    map.addLayer(heatmapLayer);
  }
});

// Location search with suggested places and type-ahead results
initLocationSearch(map, { onError: animateSelectMessage });

///////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////

// Initialize graph with default "Grid" tab
// createGraph("Grid");

var analysisButton = document.getElementById("calc-button");

///////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////

const toggle = document.getElementById("toggle");
toggle.addEventListener("change", function () {
  clear_graph();
  if (this.checked) {
    calculateLoadProfiles();
  } else {
    calculateLoadProfiles();
  }
});

// const flex_toggle = document.getElementById("toggle-flex");
// flex_toggle.addEventListener("change", function () {
//   if (this.checked) {
//     console.log("Feasibility option selected");
//     // Add your code here to handle the "Grid" option
//   } else {
//     console.log("Aggregate  option selected");
//     // Add your code here to handle the "Charger" option
//   }
// });

//////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////

////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////

let profileRequestVersion = 0;
function calculateLoadProfiles() {
  const requestVersion = ++profileRequestVersion;
  const sessionSource = document.getElementById("session-source").value;
  const demandAssumption = document.getElementById("demand-assumption").value;
  const selectedDate = dateInput.value;
  // allocate a list with selectedpolygons.length elements
  charger_ids_list = Array(selected_polygons.length).fill(null);
  transformer_ids_list = Array(selected_polygons.length).fill(null);
  connected_charger_ids_list = Array(selected_polygons.length).fill(null);


  console.log("=====================================");

  // Collect all fetch promises
  let fetchCSPromises = selected_polygons.map((selected_polygon, index) => {
    const queryBody = selected_polygon.geometry;

    return fetch("/stations/within", {
      method: "POST",
      body: JSON.stringify(queryBody),
    })
      .then((response) => response.json())
      .then((data) => {
        let charger_ids = data.features.map((feature) => feature.properties.id);
        // Assign the charger_ids to the correct index in charger_ids_list
        charger_ids_list[index] = charger_ids;
      })
      .catch((error) => {
        console.error("Error fetching analysis data:", error);
        animateSelectMessage("Could not fetch data. Please try again");
      });
  });

  let fetchTransformersPromises = selected_polygons.map(
    (selected_polygon, index) => {
      const queryBody = selected_polygon.geometry;
      queryBody.tr_type = "Middle";

      return fetch("/features/transformers/within", {
        method: "POST",
        body: JSON.stringify(queryBody),
      })
        .then((response) => response.json())
        .then((data) => {
          let transformer_ids = data.features.map(
            (feature) => feature.properties.id
          );
          transformer_ids_list[index] = transformer_ids;
        })
        .catch((error) => {
          console.error("Error fetching analysis data:", error);
          animateSelectMessage("Could not fetch data. Please try again");

          return null;
        });
    }
  );

  // Wait for all fetches to complete
  Promise.all(fetchCSPromises).then(() => {
    Promise.all(fetchTransformersPromises).then(() => {

      let fetchChargersByTransformersPromises = transformer_ids_list.map((transformer_ids_list, index) => {
        if (toggle.checked && active_tab == "Load Profiles") {
          console.log("Grid option selected!!!");
        } else {
          console.log("Charger option selected!!!");
          return Promise.resolve(); // Skip fetching transformers if not needed
        }
        // If no transformers in this polygon, keep an empty list
        console.log("Fetching chargers for transformers:", transformer_ids_list);

        if (!Array.isArray(transformer_ids_list) || transformer_ids_list.length === 0) {
          connected_charger_ids_list[index] = [];
          console.log("No transformers found, skipping fetch.");
          return Promise.resolve();
        }

        return fetch("/stations/charging-points-by-transformers", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ transformer_ids : transformer_ids_list }),
        })
          .then((res) => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
          })
          .then((payload) => {
            // Backend returns: { transformer_ids: [...], charging_point_ids: [...], count: N }
            console.log("Chargers by transformers payload:", payload);
            connected_charger_ids_list[index] = Array.isArray(payload.charging_point_ids)
              ? payload.charging_point_ids
              : [];
          })
          .catch((err) => {
            console.log("Error fetching chargers-by-transformers:", err);
            connected_charger_ids_list[index] = [];
            // animateSelectMessage("Error fetching connected chargers. Please try again!");
          });
      });

      // Use it like:
      Promise.all(fetchChargersByTransformersPromises)
        .then(() => {

          if (toggle.checked && active_tab == "Load Profiles") {
            console.log("Using connected chargers to transformers for analysis!!!!!\n\n");
            // connected_charger_ids_list is now ready, aligned with selected_polygons
            console.log("Connected chargers per polygon:", connected_charger_ids_list);
            console.log("Selected charger ids:", charger_ids_list);
            // #TODO check if toggle etc is checked and use the correct charger ids list
            charger_ids_list = connected_charger_ids_list;
            console.log("Selected charger ids (new):", charger_ids_list);
            // ...continue your pipeline here
          }

          // get charging strategy from the dropdown
          var chargingStrategy = document.getElementById("strategy").value;
          console.log("Charging strategy:", chargingStrategy);

          // Function to fetch aggregate load data for a single charger
          function fetchAggregateLoadForCharger(chargerId, area_name) {
            const query = {
              selected_markers: chargerId, strategy: chargingStrategy,
              date: selectedDate, session_source: sessionSource, demand_assumption: demandAssumption,
            };
            let url = "/stations/aggregate_load";

            return fetch(url, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(query),
            })
              .then(async (response) => {
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
                return data;
              })
              .then((data) => {
                // #return the area_name too
                data.area_name = area_name;
                return data; // Resolved data for this specific charger
              })
              .catch((error) => {
                console.error(
                  `Error fetching data for charger ${chargerId}:`,
                  error
                );
                return { error: error.message, area_name };
              });
          }

          // Create promises for each chargerId and keep their order
          let fetchPromises = charger_ids_list.map((chargerIds, index) => {
            let chargerId = chargerIds;
            let area_name = index;
            return fetchAggregateLoadForCharger(chargerId, area_name)
              .then((data) => {
                console.log("Data for: ", data.area_name, data);
                return { data };
              })
              .catch((error) => {
                console.error(
                  `Error fetching data for charger ID ${chargerId}:`,
                  error
                );
                return { chargerId, data: null, error };
              });
          });

          // Wait for all fetches to complete
          Promise.all(fetchPromises)
            .then((load_profiles) => {
              if (requestVersion !== profileRequestVersion) return;
              // load_profiles is an array of { chargerId, data }
              console.log("Respones:", load_profiles);

              load_profile_data = [];

              const failed = load_profiles
                .map((item, i) => (item.data && item.data.y ? null : selected_area_names[i]))
                .filter((name) => name !== null);
              if (failed.length) {
                showGraphMessage(
                  "Load profiles are not available for this selection",
                  load_profiles.map((item) => item.data?.error).filter(Boolean).join(" ") ||
                    `The prediction failed for ${failed.join(", ")}. Try another session source, date or charging strategy.`
                );
                return;
              }

              for (let i = 0; i < load_profiles.length; i++) {
                // find area name from the selected_area_names
                let area_name = selected_area_names[i];
                const response = load_profiles[i].data;
                const split = response.past_steps ?? 144;
                let temp_data = {
                  groupName: area_name,
                  // get 144 values for the y-axis y data
                  pastData: response.y.slice(0, split),
                  futureData: response.y.slice(split),
                  past_up_flex: response.up_flex.slice(0, split),
                  past_down_flex: response.down_flex.slice(0, split),
                  future_up_flex: response.up_flex.slice(split),
                  future_down_flex: response.down_flex.slice(split),
                  pastTimes: response.timestamps?.slice(0, split),
                  futureTimes: response.timestamps?.slice(split),
                  source: response.source,
                  targetDate: selectedDate,
                  number_of_chargers: charger_ids_list[i].length,
                  number_of_transformers: transformer_ids_list[i].length,
                };
                load_profile_data.push(temp_data);
              }
              const metadata = load_profiles[0]?.data?.source;
              document.getElementById("session-source-note").textContent = metadata
                ? `${metadata.label}. ${metadata.note} Demand: ${metadata.assumption}.` +
                  (metadata.grid_uses_historical_reference ? " Minimum-carbon estimates use a historical grid reference." : "")
                : "No charging points in this selection.";

              if (active_tab == "Load Profiles") {
                if (toggle.checked) {
                  createGraph(load_profile_data, false, dateInput.value);
                } else {
                  createGraph(load_profile_data, true, dateInput.value);
                }
              } else if (active_tab == "Flexibility") {
                createFlexGraph(load_profile_data, false, dateInput.value);
              }

              console.log("Load profiles:", load_profile_data);
              console.log("Selected charger ids:", charger_ids_list);
              console.log("Selected transformer ids:", transformer_ids_list);
              console.log("Selected area names:", selected_area_names);
            })
            .catch((error) => {
              console.error("Error in Promise.all:", error);
              showGraphMessage("Something went wrong while drawing the chart", String(error));
            });
        });
    });
  });
}

// add event listener to the strategy-dropdown to recalculate the load profiles
document.getElementById("strategy").addEventListener("change", function () {
  if (active_tab == "Load Profiles") {
    clear_graph();
    calculateLoadProfiles();
  } else if (active_tab == "Flexibility") {
    clear_graph();
    calculateLoadProfiles();
  }
});

for (const id of ["session-source", "demand-assumption"]) {
  document.getElementById(id).addEventListener("change", () => runActiveAnalysis());
}

function onDateSelectionChange(dates) {
  if (pickerRangeMode && dates.length !== 2) {
    ++profileRequestVersion;
    kpi_data_list = [];
    showGraphMessage("Select a KPI date range", "Choose both a start date and an end date.");
    return;
  }
  if (pickerRangeMode) selectedKpiRange = dates.slice();
  else if (dates.length) selectedTargetDate = dates[0];
  runActiveAnalysis();
}


const analysisPanel = document.getElementById("graph-container");
const minimizeButton = document.getElementById("minimize-btn");

// Show the analysis panel. The map, toolbar and action bar react to the
// body class in CSS.
function openPanel() {
  clearActive();
  hideHint();
  analysisPanel.hidden = false;
  document.body.classList.add("analysis-open");
  analysisButton.classList.remove("glow");
}

function closePanel() {
  analysisPanel.hidden = true;
  document.body.classList.remove("analysis-open");
  $('[data-toggle="tooltip"]').tooltip("hide");
}

async function runActiveAnalysis() {
  if (active_tab == "KPIs") {
    const requestVersion = ++profileRequestVersion;
    kpi_data_list = [];
    load_profile_data = [];
    if (datepicker.selectedDates.length !== 2) {
      showGraphMessage("Select a KPI date range", "Choose both a start date and an end date.");
      return;
    }
    clear_graph();
    try {
      const result = await get_KPIs(selected_polygons.slice(), selected_area_names.slice(),
        datepicker.selectedDates.slice(), {
          sessionSource: document.getElementById("session-source").value,
          demandAssumption: document.getElementById("demand-assumption").value,
        });
      if (requestVersion !== profileRequestVersion) return;
      kpi_data_list = result;
      charger_ids_list = result.map(group => group.chargerIds);
      transformer_ids_list = result.map(group => group.transformerIds);
      const metadata = result[0]?.source;
      document.getElementById("session-source-note").textContent = metadata
        ? `${metadata.label}. ${metadata.note} Demand: ${metadata.assumption}.`
        : "No charging points in this selection.";
      renderActiveKpi();
    } catch (error) {
      if (requestVersion !== profileRequestVersion) return;
      showGraphMessage("KPIs are not available for this selection", error.message);
    }
  } else {
    kpi_data_list = [];
    clear_graph();
    calculateLoadProfiles();
  }
}

analysisButton.addEventListener("click", function () {
  if (selected_polygons.length == 0) {
    animateSelectMessage("Draw an area on the map first");
    flagDrawTools();
    btnPoly?.focus();
    return;
  }

  openPanel();
  runActiveAnalysis();
});

// Close the panel when clicking the visible map or the close button
map.on("click", function () {
  if (document.body.classList.contains("analysis-open")) closePanel();
});
minimizeButton.addEventListener("click", closePanel);

////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////

function toggleChargerLayer() {
  const chargerCheckbox = document.getElementById("charger-checkbox");
  if (chargerCheckbox.checked) {
    vizualizeChargers = true;
  } else {
    vizualizeChargers = false;
  }
  syncDetailLayers();
}

function toggleTransformerLayer() {
  const transformerCheckbox = document.getElementById("transformer-checkbox");
  if (transformerCheckbox.checked) {
    vizualizeTransformers = true;
  } else {
    vizualizeTransformers = false;
  }
  syncDetailLayers();
}

// Add event listeners to checkboxes
const chargerCheckbox = document.getElementById("charger-checkbox");
const transformerCheckbox = document.getElementById("transformer-checkbox");
// const flexibilityCheckbox = document.getElementById("flexibility-checkbox");

chargerCheckbox.addEventListener("change", toggleChargerLayer); // Attach event listener
transformerCheckbox.addEventListener("change", toggleTransformerLayer); // Attach event listener
// flexibilityCheckbox.addEventListener("change", toggleFlexHeatmapLayer); // Attach event listener

// ---------------------------------------------------------------------------
// Tabs: Load profiles / Flexibility / KPIs (with KPI category buttons)
// ---------------------------------------------------------------------------

const kpiSubnav = document.getElementById("kpi-subnav");
const strategyField = document.getElementById("str-dropdown");
const viewToggleField = document.getElementById("toggle-div");
const dateLabel = document.getElementById("date_label");

function setActiveTab(activeId) {
  document.querySelectorAll(".tabs .tab").forEach((tab) => {
    const isActive = tab.id === activeId;
    tab.classList.toggle("active", isActive);
    tab.setAttribute("aria-selected", isActive ? "true" : "false");
  });
}

// Single-day picker for load/flexibility, date range for KPIs
function resetDatepicker(rangeMode) {
  if (pickerRangeMode && datepicker.selectedDates.length === 2) selectedKpiRange = datepicker.selectedDates.slice();
  if (!pickerRangeMode && datepicker.selectedDates.length) selectedTargetDate = datepicker.selectedDates[0];
  datepicker.destroy();
  pickerRangeMode = rangeMode;
  today = new Date();
  const weekStart = new Date(today);
  weekStart.setDate(weekStart.getDate() - 6);
  datepicker = flatpickr("#datepicker", pickerOptions(rangeMode, starting_date, today,
    rangeMode ? (selectedKpiRange || [weekStart, today]) : [selectedTargetDate], onDateSelectionChange));
  dateInput = document.getElementById("datepicker");
  dateLabel.textContent = rangeMode ? "Date range" : "Target date";
  // A range needs the full row on phones
  dateInput.closest(".field").classList.toggle("field--wide", rangeMode);
}

function showTab(tabId) {
  if (tabId === "load-tab") active_tab = "Load Profiles";
  else if (tabId === "flex-tab") active_tab = "Flexibility";
  else active_tab = "KPIs";

  const isKpi = active_tab === "KPIs";
  $(".tabs [data-toggle='tooltip']").tooltip("hide");
  setActiveTab(tabId);
  resetDatepicker(isKpi);

  kpiSubnav.hidden = !isKpi;
  strategyField.hidden = isKpi;
  document.getElementById("session-source-field").hidden = false;
  document.getElementById("demand-assumption-field").hidden = false;
  document.getElementById("session-source-note").textContent = "Synthetic scenarios with assumed demand, not verified local charging forecasts.";
  // The charger/grid view only applies to load profiles
  viewToggleField.hidden = active_tab !== "Load Profiles";

  runActiveAnalysis();
}

document.getElementById("load-tab").addEventListener("click", () => showTab("load-tab"));
document.getElementById("flex-tab").addEventListener("click", () => showTab("flex-tab"));
document.getElementById("stats-tab").addEventListener("click", () => showTab("stats-tab"));

const kpiRenderers = {
  user_kpi: createUserKPIGraph,
  grid_kpi: createGridKPIGraph,
  environment_kpi: createEnvironmentKPIGraph,
  mobility_kpi: createMobilityKPIGraph,
  city_kpi: createCityKPIGraph,
};

function renderActiveKpi() {
  const environmentalSummary = document.getElementById("environment-summary");
  if (active_kpi === "environment_kpi") renderEnvironmentSummary(kpi_data_list, environmentalSummary);
  else if (environmentalSummary) environmentalSummary.hidden = true;
  if (!kpi_data_list.length) {
    showGraphMessage("Select an area for KPIs", "Draw an area containing charging points.");
    return;
  }
  if (active_kpi === "environment_kpi" && kpi_data_list.every(group => !group.kpi.environment.covered_steps &&
      !Object.values(group.kpi.environment.strategies || {}).some(value => value.renewable_energy_coverage_pct > 0))) {
    showGraphMessage("Environmental data are unavailable for this range", "Choose dates with stored grid-mix data. Other KPIs use the selected session source.");
    return;
  }
  kpiRenderers[active_kpi](kpi_data_list);
  if (active_kpi === "environment_kpi") {
    const metadata = kpi_data_list[0].source;
    const usesReference = kpi_data_list.some(group => group.kpi.environment.uses_historical_reference);
    document.getElementById("session-source-note").textContent = `${metadata.label}. ${metadata.note} ${usesReference ? "Environmental estimates use a historical grid reference." : "Environmental estimates use matching-date grid data where available."}`;
  }
}

kpiSubnav.querySelectorAll(".kpi-option").forEach(button => {
  button.addEventListener("click", () => {
    active_kpi = button.dataset.kpi;
    kpiSubnav.querySelectorAll(".kpi-option").forEach(option => {
      const selected = option === button;
      option.classList.toggle("active", selected);
      option.setAttribute("aria-pressed", String(selected));
    });
    // KPI data is already loaded for the selected source and range; only redraw.
    if (kpi_data_list && kpi_data_list.length) renderActiveKpi();
  });
});

document.getElementById("download-btn").addEventListener("click", function () {
  generateAndDownloadExcel(charger_ids_list, load_profile_data, kpi_data_list);
});

$(function () {
  // The tab strip scrolls horizontally, which Bootstrap would otherwise use as
  // the positioning boundary, flipping the tooltip on top of the tabs.
  const tooltipOptions = { container: "body", boundary: "window" };
  $(".tabs [data-toggle='tooltip']").tooltip({ ...tooltipOptions, trigger: "hover" });
  $(".info-dot[data-toggle='tooltip']").tooltip({ ...tooltipOptions, trigger: "hover focus" });
});

// Enter runs the analysis, unless the user is typing in or activating a control
document.addEventListener("keydown", function (event) {
  if (event.key !== "Enter") return;
  if (window.EPIOT.isLandingOpen?.()) return;
  if (event.target.closest("input, select, textarea, button, a")) return;
  if (document.body.classList.contains("analysis-open")) return;
  analysisButton.click();
});

let loadingTimer = null;

function clear_graph() {
  const summary = document.getElementById("environment-summary");
  if (summary) {
    summary.hidden = true;
    summary.innerHTML = "";
  }
  const container = document.getElementById("graph");

  // Replace the container's content with the loading animation
  container.innerHTML = `
    <div class="loading-container" role="status">
      <div class="spinner"></div>
      <div class="text">Calculating…</div>
      <div class="timer" id="timer">0 s</div>
    </div>
  `;

  // Count the elapsed seconds while the loading message is on screen
  clearInterval(loadingTimer);
  let secondsPassed = 0;
  const timerElement = document.getElementById("timer");
  loadingTimer = setInterval(() => {
    if (!timerElement.isConnected) {
      clearInterval(loadingTimer);
      return;
    }
    secondsPassed++;
    timerElement.textContent = `${secondsPassed} s`;
  }, 1000);
}
