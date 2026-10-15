// import { h3ToPolygon, generateHexGrid } from "./hexUtils.js";
import { fetch_markers, calculateFlexibility, fetchDensity, bubbleIcon, chargerSites, DETAIL_ZOOM } from "./loaders.js";
import {
  createGraph,
  createPolytopeGraph,
  createUserKPIGraph,
  createGridKPIGraph,
  createMobilityKPIGraph,
  createCityKPIGraph,
  createEnvironmentKPIGraph,
  focusCardField,
  setCardBusy,
  setGroupControls,
  showCardMessage,
  showGraphMessage,
} from "./plotter.js";
import { MAX_AREAS, moved, removed, copied, copyName, escapeHtml, freeColor, validName } from "./group_actions.js";
import { DEMANDS, STRATEGIES, animateSelectMessage, generateAndDownloadExcel } from "./utils.js";
import { get_KPIs, get_LoadProfiles, get_EnvironmentKPIs } from "./data_fetch.js";
import { calendarDate, pickerOptions } from "./date_selection.js";
import { calendarNote } from "./calendar_note.js";
import { renderEnvironmentSummary } from "./environment_summary.js";
import { initLocationSearch } from "./location_search.js";
import { initPanelHeader } from "./panel_header.js";

// Initialize Map using Leaflet.js
var map = L.map("map", { zoomControl: false }).setView([52.3547, 4.9041], 12); // All of Amsterdam, at the lowest zoom that still shows chargers
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
  chunkedLoading: true,
  chunkInterval: 80,
  chunkDelay: 4,
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
let load_profile_data = [];
let kpi_data_list = [];

var active_tab = "Load Profiles";
// No live data: any calendar date is a valid scenario context
const starting_date = null;
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

// The day effects when every area shares them, a pointer to the per-area date
// tooltips when they differ
function calendarSummary(sources) {
  const notes = [...new Set(sources.map(source => calendarNote(source)).filter(Boolean))];
  if (notes.length > 1) return "Day effects differ per area; hover an area's date for details.";
  return notes[0] || "";
}

// The line under the controls: source, demand assumption and day effects
function sourceNote(sources, extra = "") {
  const metadata = sources[0];
  if (!metadata) return "No charging points in this selection.";
  return `${metadata.label}. ${metadata.note} ${calendarSummary(sources)}${extra}`;
}

// One area's chart data from its response and the settings it was requested with
function profileFromGroup(group, settings) {
  const response = group.response, split = response.past_steps ?? 144;
  return {
    groupName: group.groupName,
    pastData: response.y.slice(0, split), futureData: response.y.slice(split),
    past_up_flex: response.up_flex.slice(0, split), future_up_flex: response.up_flex.slice(split),
    past_down_flex: response.down_flex.slice(0, split), future_down_flex: response.down_flex.slice(split),
    pastTimes: response.timestamps?.slice(0, split), futureTimes: response.timestamps?.slice(split),
    source: response.source, targetDate: calendarDate(settings.date), strategy: settings.strategy,
    polytope: response.flex_polytope,
    number_of_chargers: group.chargerIds.length, number_of_transformers: group.transformerIds.length,
  };
}

async function calculateLoadProfiles() {
  const requestVersion = ++profileRequestVersion;
  // Every area is analysed under its own strategy, target date and demand scenario
  const settings = selected_area_names.map(name => ({ ...settingsOf(name) }));
  load_profile_data = [];
  try {
    const groups = await get_LoadProfiles(structuredClone(selected_polygons), selected_area_names.slice(),
      settings.map(item => calendarDate(item.date)), {
        sessionSource: document.getElementById("session-source").value,
        demandAssumption: settings.map(item => item.demand),
        strategy: settings.map(item => item.strategy),
      });
    if (requestVersion !== profileRequestVersion) return;
    charger_ids_list = groups.map(group => group.chargerIds);
    transformer_ids_list = groups.map(group => group.transformerIds);
    load_profile_data = groups.map((group, index) => profileFromGroup(group, settings[index]));
    const sources = groups.map(group => group.response.source);
    document.getElementById("session-source-note").textContent = sourceNote(sources,
      sources[0]?.grid_uses_historical_reference ? " Minimum-carbon estimates use a historical grid reference." : "");
    if (active_tab === "Load Profiles") createGraph(load_profile_data);
    else if (active_tab === "Flexibility") createPolytopeGraph(load_profile_data);
  } catch (error) {
    if (requestVersion !== profileRequestVersion) return;
    showGraphMessage("Load profiles are not available for this selection", error.message);
  }
}

document.getElementById("session-source").addEventListener("change", () => runActiveAnalysis());


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
    clear_graph();
    try {
      // Every area has its own date range and demand scenario
      const result = await get_KPIs(selected_polygons.slice(), selected_area_names.slice(),
        selected_area_names.map(name => settingsOf(name).range.slice()), {
          sessionSource: document.getElementById("session-source").value,
          demandAssumption: selected_area_names.map(name => settingsOf(name).demand),
        });
      if (requestVersion !== profileRequestVersion) return;
      kpi_data_list = result;
      charger_ids_list = result.map(group => group.chargerIds);
      transformer_ids_list = result.map(group => group.transformerIds);
      document.getElementById("session-source-note").textContent = sourceNote(result.map(group => group.source));
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
  // Transformers load on demand, so switching them on fetches the current view
  fetch_markers(map, chargerLayer, transformerLayer, vizualizeChargers, vizualizeTransformers);
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

function setActiveTab(activeId) {
  document.querySelectorAll(".tabs .tab").forEach((tab) => {
    const isActive = tab.id === activeId;
    tab.classList.toggle("active", isActive);
    tab.setAttribute("aria-selected", isActive ? "true" : "false");
  });
}

function showTab(tabId) {
  if (tabId === "load-tab") active_tab = "Load Profiles";
  else if (tabId === "flex-tab") active_tab = "Flexibility";
  else active_tab = "KPIs";

  const isKpi = active_tab === "KPIs";
  $(".tabs [data-toggle='tooltip']").tooltip("hide");
  setActiveTab(tabId);

  kpiSubnav.hidden = !isKpi;
  document.getElementById("session-source-note").textContent = "Synthetic scenarios with assumed demand, not verified local charging forecasts.";

  runActiveAnalysis();
}

document.getElementById("load-tab").addEventListener("click", () => showTab("load-tab"));
document.getElementById("flex-tab").addEventListener("click", () => showTab("flex-tab"));
document.getElementById("stats-tab").addEventListener("click", () => showTab("stats-tab"));

// Gliding highlight and arrow-key navigation for the header's tabs
initPanelHeader();

const kpiRenderers = {
  user_kpi: createUserKPIGraph,
  grid_kpi: createGridKPIGraph,
  environment_kpi: createEnvironmentKPIGraph,
  mobility_kpi: createMobilityKPIGraph,
  city_kpi: createCityKPIGraph,
};

async function ensureEnvironmentKpis(groups) {
  if (!groups.length || groups.every(group => group.kpi.environment)) return groups;
  const result = await get_EnvironmentKPIs(groups);
  if (kpi_data_list === groups) kpi_data_list = result;
  return result;
}

async function renderActiveKpi() {
  const requestVersion = profileRequestVersion;
  if (active_kpi === "environment_kpi" && kpi_data_list.some(group => !group.kpi.environment)) {
    clear_graph();
    try {
      await ensureEnvironmentKpis(kpi_data_list);
    } catch (error) {
      if (requestVersion === profileRequestVersion && active_tab === "KPIs" && active_kpi === "environment_kpi") {
        showGraphMessage("Environmental KPIs are not available", error.message);
      }
      return;
    }
    if (requestVersion !== profileRequestVersion || active_tab !== "KPIs" || active_kpi !== "environment_kpi") return;
  }
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
    // Basic categories redraw immediately; environment loads on first opening.
    if (kpi_data_list && kpi_data_list.length) renderActiveKpi();
  });
});

document.getElementById("download-btn").addEventListener("click", async function () {
  if (this.disabled) return;
  this.disabled = true;
  const ids = charger_ids_list, profiles = load_profile_data, groups = kpi_data_list;
  try {
    // A full KPI workbook includes the lazy environment section even if unopened.
    const complete = await ensureEnvironmentKpis(groups);
    generateAndDownloadExcel(ids, profiles, complete);
  } catch (error) {
    animateSelectMessage(error.message);
  } finally {
    this.disabled = false;
  }
});

$(function () {
  // The panel header's tooltips are set up in panel_header.js; any info dot
  // elsewhere on the page gets the same hover and focus behaviour here.
  const tooltipOptions = { container: "body", boundary: "window" };
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
  destroyCardPickers();
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

// ---------------------------------------------------------------------------
// Per-area settings. Each area is analysed under its own charging strategy and
// target date (load profiles, flexibility) or date range (KPIs). They are kept
// by area name, which is unique, so they follow an area through moves, renames
// and copies; the cards edit them and refresh only the area that changed.
// ---------------------------------------------------------------------------

const DEFAULT_STRATEGY = "afap";
const DEFAULT_DEMAND = "base";
const areaSettings = new Map();

function settingsOf(name) {
  let settings = areaSettings.get(name);
  if (!settings) {
    const now = new Date();
    const weekStart = new Date(now);
    weekStart.setDate(weekStart.getDate() - 6);
    settings = { strategy: DEFAULT_STRATEGY, demand: DEFAULT_DEMAND, date: now, range: [weekStart, now] };
    areaSettings.set(name, settings);
  }
  return settings;
}

let cardPickers = [];

// The cards are rebuilt on every redraw; flatpickr calendars live on <body>
function destroyCardPickers() {
  cardPickers.forEach(picker => picker.destroy());
  cardPickers = [];
}

function settingField(icon, control) {
  const wrapper = document.createElement("div");
  wrapper.className = "group-field";
  const glyph = document.createElement("i");
  glyph.className = `fa ${icon}`;
  glyph.setAttribute("aria-hidden", "true");
  wrapper.append(glyph, control);
  return wrapper;
}

// A labelled-by-icon select for one of the card's settings
function optionField(icon, field, title, options, current, onChange) {
  const select = document.createElement("select");
  select.className = "group-field__control";
  select.dataset.field = field;
  select.title = title;
  select.setAttribute("aria-label", title);
  options.forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.append(option);
  });
  select.value = current;
  select.addEventListener("change", () => onChange(select.value));
  return settingField(icon, select);
}

// Fill a card's settings slot: strategy and target date (or the KPI date range)
// and the demand scenario
function decorateCard(slot, group) {
  const name = group.groupName;
  const settings = settingsOf(name);
  const date = document.createElement("input");
  date.type = "text";
  date.readOnly = true;
  date.className = "group-field__control";
  const demand = optionField("fa-bar-chart", "demand", `Demand scenario for ${name}`, DEMANDS, settings.demand,
    value => {
      settings.demand = value;
      refreshArea(name, "demand");
    });
  if (active_tab === "KPIs") {
    date.className += " group-field__control--range";
    date.dataset.field = "range";
    date.title = calendarNote(group.source) || "Date range";
    date.setAttribute("aria-label", `Date range for ${name}`);
    cardPickers.push(flatpickr(date, pickerOptions(true, starting_date, new Date(), settings.range, dates => {
      if (dates.length !== 2) return; // wait for the end date
      settings.range = dates.slice();
      refreshArea(name, "range");
    })));
    slot.append(settingField("fa-calendar", date), demand);
    return;
  }
  const strategy = optionField("fa-sliders", "strategy", `Charging strategy for ${name}`, STRATEGIES,
    settings.strategy, value => {
      settings.strategy = value;
      refreshArea(name, "strategy");
    });
  date.dataset.field = "date";
  date.title = calendarNote(group.source) || "Target date";
  date.setAttribute("aria-label", `Target date for ${name}`);
  cardPickers.push(flatpickr(date, pickerOptions(false, starting_date, new Date(), [settings.date], dates => {
    if (!dates.length) return;
    settings.date = dates[0];
    refreshArea(name, "date");
  })));
  slot.append(strategy, settingField("fa-calendar", date), demand);
}

const areaRequests = new Map(); // area name -> latest request, so late answers are dropped
const pendingAreas = new Set();

// A card's setting changed: request that area alone and redraw. The other
// areas keep their results, and a full analysis in between wins over this one.
async function refreshArea(name, field) {
  const index = selected_area_names.indexOf(name);
  if (index < 0) return;
  const token = (areaRequests.get(name) || 0) + 1;
  const analysis = profileRequestVersion;
  areaRequests.set(name, token);
  pendingAreas.add(name);
  setCardBusy(index, true);
  const superseded = () => areaRequests.get(name) !== token || analysis !== profileRequestVersion;
  const settings = { ...settingsOf(name) };
  const options = {
    sessionSource: document.getElementById("session-source").value,
    demandAssumption: settings.demand,
  };
  try {
    let group;
    if (active_tab === "KPIs") {
      [group] = await get_KPIs([selected_polygons[index]], [name], [settings.range.slice()], options);
    } else {
      [group] = await get_LoadProfiles([structuredClone(selected_polygons[index])], [name],
        calendarDate(settings.date), { ...options, strategy: settings.strategy });
    }
    if (superseded()) return;
    pendingAreas.delete(name);
    // The area may have moved, or gone, while the request ran
    const at = selected_area_names.indexOf(name);
    if (at < 0) return;
    charger_ids_list[at] = group.chargerIds;
    transformer_ids_list[at] = group.transformerIds;
    if (active_tab === "KPIs") kpi_data_list[at] = group;
    else load_profile_data[at] = profileFromGroup(group, settings);
    renderGroupResults();
    focusCardField(at, field);
  } catch (error) {
    if (superseded()) return;
    pendingAreas.delete(name);
    const at = selected_area_names.indexOf(name);
    if (at >= 0) showCardMessage(at, error.message);
  }
}

// ---------------------------------------------------------------------------
// Result cards: move, copy, rename and remove areas from the analysis panel.
// The drawn areas are the source of truth for the selection, so every edit
// rebuilds them in the new order and edits the result arrays to match, without
// a new request.
// ---------------------------------------------------------------------------

// Each drawn area is a polygon layer plus a label marker sharing its name
function drawnAreas() {
  const labels = new Map();
  const areas = [];
  drawnItems.eachLayer((layer) => {
    const properties = layer.feature && layer.feature.properties;
    if (!properties) return;
    if (properties.type === "marker") labels.set(properties.name, layer);
    else areas.push(layer);
  });
  return areas.map((layer) => {
    const name = layer.feature.properties.name;
    return { layer, name, label: labels.get(name) };
  });
}

function areaSpecs() {
  return drawnAreas().map(({ layer, name, label }) => {
    const { color, weight, fillOpacity, dashArray } = layer.options;
    return {
      name,
      latLngs: layer.getLatLngs(),
      style: { color, weight, fillOpacity, dashArray },
      labelAt: label ? label.getLatLng() : layer.getBounds().getCenter(),
    };
  });
}

// Leaflet keeps layers in creation order, so rebuilding them is what reorders
function rebuildAreas(specs) {
  drawnItems.clearLayers();
  specs.forEach(({ name, latLngs, style, labelAt }) => {
    const area = L.polygon(latLngs, style);
    area.feature = { properties: { name, type: "area" } };
    drawnItems.addLayer(area);
    const label = L.marker(labelAt, {
      icon: L.divIcon({ className: "shape-label", html: `<span>${escapeHtml(name)}</span>`, iconSize: [0, 0] }),
      interactive: false,
    });
    label.feature = { properties: { name, type: "marker" } };
    drawnItems.addLayer(label);
  });
}

function syncSelectionFromAreas() {
  selected_polygons = [];
  selected_area_names = [];
  drawnAreas().forEach(({ layer, name }) => {
    const ring = layer.getLatLngs()[0].map((point) => [point.lng, point.lat]);
    const first = ring[0];
    const last = ring[ring.length - 1];
    if (first[0] !== last[0] || first[1] !== last[1]) ring.push(first);
    selected_polygons.push({ type: "Feature", geometry: { type: "Polygon", coordinates: [ring] } });
    selected_area_names.push(name);
  });
  syncDrawPrompt();
}

function renderGroupResults() {
  if (active_tab === "KPIs") renderActiveKpi();
  else if (!selected_polygons.length) showGraphMessage("No areas selected", "Draw an area on the map, then press Analyse.");
  else if (active_tab === "Flexibility") createPolytopeGraph(load_profile_data);
  else createGraph(load_profile_data);
}

// Apply one edit to the map areas and to every result array parallel to them
function applyGroupEdit(specs, editResults) {
  const count = selected_area_names.length;
  const edit = (items) => (items.length === count ? editResults(items) : items);
  rebuildAreas(specs);
  syncSelectionFromAreas();
  charger_ids_list = edit(charger_ids_list);
  transformer_ids_list = edit(transformer_ids_list);
  load_profile_data = edit(load_profile_data);
  kpi_data_list = edit(kpi_data_list);
  renderGroupResults();
}

const selectionStatus = () => `${selected_polygons.length} of ${MAX_AREAS} areas selected. Ready to analyse`;

function moveGroup(index, delta) {
  const target = index + delta;
  const specs = areaSpecs();
  if (target < 0 || target >= specs.length) return null;
  applyGroupEdit(moved(specs, index, target), (items) => moved(items, index, target));
  animateSelectMessage(selectionStatus());
  return target;
}

function duplicateGroup(index) {
  const specs = areaSpecs();
  if (specs.length >= MAX_AREAS) {
    animateSelectMessage(`You can compare up to ${MAX_AREAS} areas. Remove one to add a copy`);
    return null;
  }
  const source = specs[index];
  const name = copyName(source.name, specs.map((spec) => spec.name));
  // The copy starts from the same strategy and dates, to be changed on its card
  const sourceSettings = settingsOf(source.name);
  areaSettings.set(name, { ...sourceSettings, range: sourceSettings.range.slice() });
  const lats = source.latLngs[0].map((point) => point.lat);
  const spread = Math.max(...lats) - Math.min(...lats);
  const copy = {
    ...source,
    name,
    // Dashed over the original, so both outlines and labels stay visible
    style: { ...source.style, color: freeColor(colors, specs.map((spec) => spec.style.color)), dashArray: "10 8" },
    labelAt: L.latLng(source.labelAt.lat - spread * 0.14, source.labelAt.lng),
  };
  applyGroupEdit(copied(specs, index, () => copy), (items) =>
    copied(items, index, (item) => (Array.isArray(item) ? item.slice() : { ...item, groupName: name })));
  // A request still running for the original would otherwise leave the copy stale
  if (pendingAreas.has(source.name)) refreshArea(name);
  animateSelectMessage(selectionStatus());
  return index + 1;
}

function renameGroup(index, requested) {
  const specs = areaSpecs();
  const current = specs[index].name;
  const check = validName(requested, specs.filter((_, at) => at !== index).map((spec) => spec.name));
  if (check.error) return check.error;
  const name = check.name;
  if (name === current) return null;
  areaSettings.set(name, settingsOf(current));
  areaSettings.delete(current);
  specs[index] = { ...specs[index], name };
  applyGroupEdit(specs, (items) =>
    items.map((item, at) => (at === index && !Array.isArray(item) ? { ...item, groupName: name } : item)));
  // An answer still on its way is addressed to the old name
  if (pendingAreas.delete(current)) refreshArea(name);
  return index;
}

function removeGroup(index) {
  const all = areaSpecs();
  areaSettings.delete(all[index].name);
  const specs = removed(all, index);
  applyGroupEdit(specs, (items) => removed(items, index));
  animateSelectMessage(specs.length
    ? `Area removed. ${specs.length} of ${MAX_AREAS} selected`
    : "Draw an area on the map to start");
  return specs.length ? Math.min(index, specs.length - 1) : null;
}

setGroupControls({
  colorOf: (group) => {
    const area = drawnAreas().find(({ name }) => name === group.groupName);
    return area ? area.layer.options.color : null;
  },
  canDuplicate: () => selected_polygons.length < MAX_AREAS,
  decorate: decorateCard,
  release: destroyCardPickers,
  move: moveGroup,
  duplicate: duplicateGroup,
  remove: removeGroup,
  rename: renameGroup,
});
