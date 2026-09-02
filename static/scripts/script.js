// import { h3ToPolygon, generateHexGrid } from "./hexUtils.js";
import { fetch_markers, calculateFlexibility } from "./loaders.js";
import {
  createGraph,
  createFlexGraph,
  createUserKPIGraph,
  createGridKPIGraph,
  createMobilityKPIGraph,
  createCityKPIGraph,
  createEnvironmentKPIGraph,
} from "./plotter.js";
import { animateSelectMessage, generateAndDownloadExcel } from "./utils.js";
import { get_KPIs } from "./data_fetch.js";

// Initialize Map using Leaflet.js
var map = L.map("map").setView([52.3676, 4.9041], 16); // Centered on Amsterdam

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

// restrict maximum zoom level to prevent too many hexagons
map.setMaxZoom(16);
map.setMinZoom(14);

const chargerLayer = L.layerGroup();
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
const starting_date = new Date("2025-09-01");
// Initialize Flatpickr on the input field
let datepicker = flatpickr("#datepicker", {
  minDate: starting_date, // Set the minimum date to January 1, 2025
  maxDate: today, // Set the maximum date to today
  dateFormat: "Y-m-d", // Format the date as DD/MM/YYYY
  defaultDate: today, // No default date selected
  disableMobile: true, // Force desktop-style picker on mobile devices
});

let dateInput = document.getElementById("datepicker");
let active_kpi = "user_kpi";

// Trigger animation on page load
window.addEventListener("load", function () {
  animateSelectMessage("Draw area for analysis!");
});

animateSelectMessage("Draw area for analysis!");

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
  if (activeHandler && activeHandler.disable) activeHandler.disable();
  handler.enable();
  activeHandler = handler;
  setActive(btn);
}
function clearActive() {
  if (activeHandler && activeHandler.disable) activeHandler.disable();
  activeHandler = null;
  setActive(null);
}

btnPoly?.addEventListener('click', () => enable(polygonHandler, btnPoly));
btnRect?.addEventListener('click', () => enable(rectangleHandler, btnRect));
btnDel?.addEventListener('click', () => enable(deleteHandler, btnDel));

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

function showHint(text) {
  if (!hintEl) return;
  hintEl.textContent = text;
  hintEl.hidden = false;
}

function hideHint() {
  if (!hintEl) return;
  hintEl.hidden = true;
}

// Update your button listeners:
btnPoly?.addEventListener('click', () => {
  enable(polygonHandler, btnPoly);
  showHint('Polygon: Click to add vertices, double-click to finish. Press Esc to cancel.');
});

btnRect?.addEventListener('click', () => {
  enable(rectangleHandler, btnRect);
  showHint('Rectangle: Click and drag on the map to draw. Release to finish. Press Esc to cancel.');
});

btnDel?.addEventListener('click', () => {
  enable(deleteHandler, btnDel);
  showHint('Delete: Click shapes to remove them. Click the trash again or press Esc to exit.');
});

// When a draw finishes or mode exits, hide the hint
map.on(L.Draw.Event.CREATED, hideHint);
map.on('draw:drawstop', hideHint);
map.on('draw:deletestop', hideHint);
map.on('draw:editstop', hideHint);

// Also hide on ESC
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    hideHint();
    clearActive?.();
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
    animateSelectMessage("Draw area for analysis!");
  } else {
    animateSelectMessage("Area deleted! Analyse or select more areas!");
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
    animateSelectMessage("Draw area for analysis!");
  } else {
    animateSelectMessage("Area deleted! Analyse or select more areas!");
  }
  map.fire("draw:stop");
});

map.on(L.Draw.Event.CREATED, function (event) {
  var layer = event.layer;
  // Clear any existing layers to ensure only one shape is on the map
  // drawnItems.clearLayers();

  console.log("Creation event:", event);

  if (selected_polygons.length > 2) {
    animateSelectMessage("Only 3 areas can be selected at a time!");
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
      animateSelectMessage("Please redraw!");
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
      center = L.latLng(center.lat + 0.0005, center.lng - 0.0005);
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

    // Stop glowing effect on the draw toolbar
    const drawToolbar = document.querySelector(".leaflet-draw-toolbar");
    if (drawToolbar) {
      drawToolbar.style.animation = "none";
      drawToolbar.style.boxShadow = "none";
    }

    animateSelectMessage("Area selected! Analyse or select more areas!");

    // Add glowing effect to the Analyse button
    const analyseButton = document.getElementById("calc-button");
    if (analyseButton) {
      analyseButton.classList.add("glow");
    }
  }
});

// Load the charger and transformer markers
fetch_markers(
  map,
  chargerLayer,
  transformerLayer,
  vizualizeChargers,
  vizualizeTransformers
);

map.on("load moveend", function () {
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

// Handle location input
document
  .getElementById("location-button")
  .addEventListener("click", function () {
    var location = document.getElementById("location-input").value;

    if (location) {
      // Use a simple geocoding service (for simplicity, this will not work in production)
      fetch(
        `https://nominatim.openstreetmap.org/search?format=json&q=${location}`
      )
        .then((response) => response.json())
        .then((data) => {
          if (data && data.length > 0) {
            var lat = data[0].lat;
            var lon = data[0].lon;
            map.setView([lat, lon], 13);
          }
        });
    }
  });

///////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////

// Initialize CS-ID Dropdown with Random IDs
var groupDropdown = document.getElementById("cs-id-dropdown");
// var randomCsIds = Array.from(
//   { length: 5 },
//   () => `CS-${Math.floor(Math.random() * 1000)}`
// );

// randomCsIds.forEach((id) => {
//   var option = document.createElement("option");
//   option.textContent = id;
//   option.value = id;
//   csDropdown.appendChild(option);
// });

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

// Initialize the dropdown menu
function initializeDropdown(comp_ids_list, groupNames) {
  // clear the dropdown
  groupDropdown.innerHTML = "";

  comp_ids_list.forEach((group, index) => {
    var optgroup = document.createElement("optgroup");

    // Use provided group names or default to "Group X"
    var groupName =
      groupNames && groupNames[index]
        ? groupNames[index]
        : "Group " + (index + 1);
    optgroup.label = groupName;

    group.forEach((chargerId) => {
      var option = document.createElement("option");
      option.textContent = chargerId;
      option.value = chargerId;
      optgroup.appendChild(option);
    });

    groupDropdown.appendChild(optgroup);
  });

  if (!toggle.checked) {
    groupDropdown.options[groupDropdown.options.length] = new Option(
      "Selected Charger IDs",
      "",
      true,
      true
    );
  } else {
    groupDropdown.options[groupDropdown.options.length] = new Option(
      "Selected Transformer IDs",
      "",
      true,
      true
    );

    // disable the default selected option
    groupDropdown.options[groupDropdown.options.length - 1].disabled = true;
  }

  // Event listener for the dropdown menu
  groupDropdown.addEventListener("change", function () {
    clear_graph();
    if (!toggle.checked) {
      // find marker with the selected charger id
      for (let i = 0; i < chargerLayer.getLayers().length; i++) {
        let marker = chargerLayer.getLayers()[i];
        if (marker.options.id == this.value) {
          graphContainer.style.display = "none"; // Minimize the graph
          fancyBarButton.style.display = "block"; // Show the fancy button when the graph is minimized
          map.getContainer().style.filter = "none";
          message.style.display = "block"; // Show the select charger message

          // Re-enable the draw control if it was disabled
          if (!draw_control_enabled) {
            map.addControl(drawControl);
            draw_control_enabled = true;
          }

          // Center the map on the marker
          map.setView(marker.getLatLng(), 15);

          // Open the marker's popup
          marker.openPopup();

          // Highlight the marker
          highlightCSMarker(marker);
        }
      }
    } else {
      // find marker with the selected transformer id
      for (let i = 0; i < transformerLayer.getLayers().length; i++) {
        let marker = transformerLayer.getLayers()[i];
        if (marker.options.id == this.value) {
          graphContainer.style.display = "none"; // Minimize the graph
          fancyBarButton.style.display = "block"; // Show the fancy button when the graph is minimized
          map.getContainer().style.filter = "none";
          message.style.display = "block"; // Show the select charger message

          // Re-enable the draw control if it was disabled
          if (!draw_control_enabled) {
            map.addControl(drawControl);
            draw_control_enabled = true;
          }

          // Center the map on the marker
          map.setView(marker.getLatLng(), 15);

          // Open the marker's popup
          marker.openPopup();

          // Highlight the marker
          highlightTrMarker(marker);
        }
      }
    }
    inputContainer.style.display = "flex";
    checkboxContainer.style.display = "flex";
    headerButtons.style.display = "flex";
    drawButtons.style.display = "inline-flex";

    graphContainer.style.display = "none"; // Minimize the graph
    fancyBarButton.style.display = "block"; // Show the fancy button when the graph is minimized
    map.getContainer().style.filter = "none";
    message.style.display = "block"; // Show the select charger message

    // Re-enable the draw control if it was disabled
    if (!draw_control_enabled) {
      map.addControl(drawControl);
      draw_control_enabled = true;
    }
  });
}

// Function to highlight a marker
var previousMarker = null;
var defaultCSIcon = L.icon({
  iconUrl: "http://127.0.0.1:5000/images/charger_icon.png",
  iconSize: [25, 25],
  iconAnchor: [12.5, 25],
  popupAnchor: [1, -25],
});

var defaultTrIcon = L.icon({
  iconUrl: "http://127.0.0.1:5000/images/transformer_icon.png",
  iconSize: [25, 25],
  iconAnchor: [12.5, 25],
  popupAnchor: [1, -25],
});

var highlightedIcon = L.icon({
  iconUrl: "https://maps.gstatic.com/intl/en_us/mapfiles/markers2/marker.png",
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
});

function highlightCSMarker(marker) {
  // Reset previous marker icon
  if (previousMarker && previousMarker !== marker) {
    previousMarker.setIcon(defaultCSIcon);
  }

  // Set highlighted icon
  marker.setIcon(highlightedIcon);

  // Add event listener to reset icon when popup closes
  marker.on("popupclose", onCSPopupClose);

  // Update previous marker
  previousMarker = marker;
}

function highlightTrMarker(marker) {
  // Reset previous marker icon
  if (previousMarker && previousMarker !== marker) {
    previousMarker.setIcon(defaultTrIcon);
  }

  // Set highlighted icon
  marker.setIcon(highlightedIcon);

  // Add event listener to reset icon when popup closes
  marker.on("popupclose", onTrPopupClose);

  // Update previous marker
  previousMarker = marker;
}

// Event handler for popup close
function onCSPopupClose(e) {
  var marker = e.target;
  marker.setIcon(defaultCSIcon);
  // Remove this event listener to prevent multiple triggers
  marker.off("popupclose", onCSPopupClose);
}

function onTrPopupClose(e) {
  var marker = e.target;
  marker.setIcon(defaultTrIcon);
  // Remove this event listener to prevent multiple triggers
  marker.off("popupclose", onTrPopupClose);
}

////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////

function calculateLoadProfiles() {
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
        animateSelectMessage("Error fetching data. Please try again!");
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
          animateSelectMessage("Error fetching data. Please try again!");

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
            let url = `/stations/aggregate_load?selected_markers=${encodeURIComponent(
              chargerId
            )}&strategy=${encodeURIComponent(chargingStrategy)}
        &date=${encodeURIComponent(dateInput.value)}
        `;

            return fetch(url, {
              method: "GET",
            })
              .then((response) => response.json())
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
                return null; // Return null in case of an error
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
              // load_profiles is an array of { chargerId, data }
              console.log("Respones:", load_profiles);

              load_profile_data = [];

              for (let i = 0; i < load_profiles.length; i++) {
                // find area name from the selected_area_names
                let area_name = selected_area_names[i];
                let temp_data = {
                  groupName: area_name,
                  // get 144 values for the y-axis y data
                  pastData: load_profiles[i].data.y.slice(0, 144),
                  futureData: load_profiles[i].data.y.slice(144),
                  past_up_flex: load_profiles[i].data.up_flex.slice(0, 144),
                  past_down_flex: load_profiles[i].data.down_flex.slice(0, 144),
                  future_up_flex: load_profiles[i].data.up_flex.slice(144),
                  future_down_flex: load_profiles[i].data.down_flex.slice(144),
                  number_of_chargers: charger_ids_list[i].length,
                  number_of_transformers: transformer_ids_list[i].length,
                };
                load_profile_data.push(temp_data);
              }

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

              // update the dropdown with the charger ids
              if (toggle.checked) {
                initializeDropdown(transformer_ids_list, selected_area_names);
              } else {
                initializeDropdown(charger_ids_list, selected_area_names);
              }
            })
            .catch((error) => {
              console.error("Error in Promise.all:", error);
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

dateInput.addEventListener("change", () => {
  if (active_tab == "KPIs") {
    if (datepicker.selectedDates.length <= 1) {
      return;
    }
  }
  clear_graph();
  if (active_tab == "Load Profiles") {
    calculateLoadProfiles();
  } else if (active_tab == "Flexibility") {
    calculateLoadProfiles();
  } else if (active_tab == "KPIs") {
    charger_ids_list,
      transformer_ids_list,
      (kpi_data_list = get_KPIs(
        selected_polygons,
        selected_area_names,
        datepicker,
        active_kpi
      ));
  }
});

// get aelement header-bar
const headerBar = document.getElementById("header-bar");
// get teh following elements input-container checkbox-container header-buttons
const inputContainer = document.getElementById("input-container");
const checkboxContainer = document.getElementById("checkbox-container");
const headerButtons = document.getElementById("header-buttons");

const drawButtons = document.getElementById("draw-toolbar-wrap");


analysisButton.addEventListener("click", function () {
  // map.fire("draw:stop");

  if (selected_polygons.length == 0) {
    animateSelectMessage("Please draw an area first!");
    map.addControl(drawControl);
    return;
  }

  inputContainer.style.display = "none";
  checkboxContainer.style.display = "none";
  headerButtons.style.display = "none";

  drawButtons.style.display = "none";

  // remove the colorbar if it exists

  colorbarControl.remove();
  graphContainer.style.display = "block";
  fancyBarButton.style.display = "none"; // Hide the fancy button when graph expands
  // make map grayscale with a slow transition
  map.getContainer().style.filter = "grayscale(65%)";
  map.getContainer().style.transition = "filter 0.7s";
  // Hide the select charger message
  message.style.display = "none";

  // Stop glowing effect on the Analyse button
  const analyseButton = document.getElementById("calc-button");
  if (analyseButton) {
    analyseButton.classList.remove("glow");
  }

  // Disable the draw control
  map.removeControl(drawControl);
  draw_control_enabled = false;

  clear_graph();
  if (active_tab == "Load Profiles") {
    calculateLoadProfiles();
  } else if (active_tab == "Flexibility") {
    calculateLoadProfiles();
  } else if (active_tab == "KPIs") {
    charger_ids_list,
      transformer_ids_list,
      (kpi_data_list = get_KPIs(
        selected_polygons,
        selected_area_names,
        datepicker,
        active_kpi
      ));
  }
});

////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////

// Toggle Graph Container and Fancy Button
var graphContainer = document.getElementById("graph-container");
var fancyBarButton = document.getElementById("fancy-bar-button");
var minimizeButton = document.getElementById("minimize-btn");
var message = document.getElementById("select-message");

// Initially hide the fancy bar button
// fancyBarButton.style.display = "none";
graphContainer.style.display = "none"; // Initially hide the graph container

// Minimize the graph when clicking outside the graph or on the map
map.on("click", function () {
  inputContainer.style.display = "flex";
  checkboxContainer.style.display = "flex";
  headerButtons.style.display = "flex";

  drawButtons.style.display = "inline-flex";

  graphContainer.style.display = "none"; // Minimize the graph
  fancyBarButton.style.display = "block"; // Show the fancy button when the graph is minimized
  map.getContainer().style.filter = "none";
  message.style.display = "block"; // Show the select charger message

  // Re-enable the draw control if it was disabled
  if (!draw_control_enabled) {
    map.addControl(drawControl);
    draw_control_enabled = true;
  }
});

// Minimize the graph when clicking the minimize button
minimizeButton.addEventListener("click", function () {
  inputContainer.style.display = "flex";
  checkboxContainer.style.display = "flex";
  headerButtons.style.display = "flex";

  drawButtons.style.display = "inline-flex";

  graphContainer.style.display = "none"; // Minimize the graph
  fancyBarButton.style.display = "block"; // Show the fancy button when the graph is minimized
  map.getContainer().style.filter = "none";
  message.style.display = "block"; // Show the select charger message

  // Re-enable the draw control if it was disabled
  if (!draw_control_enabled) {
    map.addControl(drawControl);
    draw_control_enabled = true;
  }
});

// Create a colorbar control
const colorbarControl = L.control({ position: "bottomright" });

colorbarControl.onAdd = function () {
  const div = L.DomUtil.create("div", "leaflet-colorbar");

  // Add the gradient and labels
  div.innerHTML = `
    <div class="colorbar-container">
      <div class="colorbar-gradient"></div>
      <div class="colorbar-labels">
        <span>0</span>
        <span>25</span>
        <span>50</span>
        <span>75</span>
        <span>100</span>
      </div>
    </div>
  `;
  return div;
};

// // Add the colorbar to the map
// colorbarControl.addTo(map);

////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////

function toggleChargerLayer() {
  const chargerCheckbox = document.getElementById("charger-checkbox");
  if (chargerCheckbox.checked) {
    vizualizeChargers = true;
    map.addLayer(chargerLayer); // Show chargers
  } else {
    vizualizeChargers = false;
    map.removeLayer(chargerLayer); // Hide chargers
  }
}

function toggleTransformerLayer() {
  const transformerCheckbox = document.getElementById("transformer-checkbox");
  if (transformerCheckbox.checked) {
    vizualizeTransformers = true;
    map.addLayer(transformerLayer); // Show transformers
  } else {
    vizualizeTransformers = false;
    map.removeLayer(transformerLayer); // Hide transformers
  }
}

// Add event listeners to checkboxes
const chargerCheckbox = document.getElementById("charger-checkbox");
const transformerCheckbox = document.getElementById("transformer-checkbox");
// const flexibilityCheckbox = document.getElementById("flexibility-checkbox");

chargerCheckbox.addEventListener("change", toggleChargerLayer); // Attach event listener
transformerCheckbox.addEventListener("change", toggleTransformerLayer); // Attach event listener
// flexibilityCheckbox.addEventListener("change", toggleFlexHeatmapLayer); // Attach event listener

// Function to highlight active tab
function setActiveTab(activeId) {
  var tabs = document.querySelectorAll(".tabs button");
  tabs.forEach((tab) => tab.classList.remove("active"));
  document.getElementById(activeId).classList.add("active");
}

const kpisButton = document.getElementById("stats-tab");

// Add event listeners for each tab
document.getElementById("load-tab").addEventListener("click", function () {
  datepicker.destroy();
  datepicker = flatpickr("#datepicker", {
    minDate: starting_date, // Set the minimum date to January 1, 2025
    maxDate: today, // Set the maximum date to today
    dateFormat: "Y-m-d", // Format the date as DD/MM/YYYY
    defaultDate: today, // No default date selected
    disableMobile: true, // Force desktop-style picker on mobile devices
  });
  const label = document.getElementById("date_label");
  label.textContent = "Select Date:";
  // make strategy-dropdown siplay none
  document.getElementById("str-dropdown").style.display = "flex";

  dateInput = document.getElementById("datepicker");

  clear_graph();
  calculateLoadProfiles();

  setActiveTab("load-tab");
  active_tab = "Load Profiles";

  document.getElementById("toggle-flex-div").style.display = "none";
  document.getElementById("toggle-div").style.display = "block";

  const kpiContainer = document.querySelector(".kpi-container");
  if (kpiContainer) {
    kpiContainer.classList.remove("show");
    kpiContainer.replaceWith(kpisButton);
  }
  setActiveTab("load-tab");
});

document.getElementById("flex-tab").addEventListener("click", function () {
  datepicker.destroy();
  flatpickr("#datepicker", {
    minDate: starting_date, // Set the minimum date to January 1, 2025
    maxDate: today, // Set the maximum date to today
    dateFormat: "Y-m-d", // Format the date as DD/MM/YYYY
    defaultDate: today, // No default date selected
    disableMobile: true, // Force desktop-style picker on mobile devices
  });
  const label = document.getElementById("date_label");
  label.textContent = "Select Date:";
  // make strategy-dropdown siplay none
  document.getElementById("str-dropdown").style.display = "flex";

  dateInput = document.getElementById("datepicker");
  setActiveTab("flex-tab");
  active_tab = "Flexibility";
  clear_graph();
  calculateLoadProfiles();

  document.getElementById("toggle-flex-div").style.display = "block";
  document.getElementById("toggle-flex-div").style.visibility = "hidden";
  document.getElementById("toggle-div").style.display = "none";
  // document.getElementById("toggle-flex_div").style.display = "none";

  const kpiContainer = document.querySelector(".kpi-container");
  if (kpiContainer) {
    kpiContainer.classList.remove("show");
    kpiContainer.replaceWith(kpisButton);
  }
  setActiveTab("flex-tab");
});

document.getElementById("download-btn").addEventListener("click", function () {
  generateAndDownloadExcel(charger_ids_list, load_profile_data, kpi_data_list);
});

$(document).ready(function () {
  $('[data-toggle="tooltip"]').tooltip();
});

document.addEventListener("keydown", function (event) {
  if (event.key === "Enter") {
    // Simulate a button click
    document.getElementById("calc-button").click();
  }
});

// document.addEventListener("DOMContentLoaded", function () {
// const kpisButton = document.getElementById("stats-tab");
document.getElementById("stats-tab").addEventListener("click", function () {
  datepicker.destroy();
  datepicker = flatpickr("#datepicker", {
    mode: "range",
    minDate: starting_date, // Set the minimum date to January 1, 2025
    maxDate: today, // Set the maximum date to today
    dateFormat: "Y-m-d", // Format the date as DD/MM/YYYY
    defaultDate: [starting_date, today], // Set the default date to today
  });
  const label = document.getElementById("date_label");
  label.textContent = "Select Date Range:";
  // make strategy-dropdown siplay none
  document.getElementById("str-dropdown").style.display = "none";
  clear_graph();

  charger_ids_list,
    transformer_ids_list,
    (kpi_data_list = get_KPIs(
      selected_polygons,
      selected_area_names,
      datepicker,
      active_kpi
    ));

  setActiveTab("stats-tab");

  document.getElementById("toggle-flex-div").style.display = "none";
  document.getElementById("toggle-div").style.display = "none";

  active_tab = "KPIs";

  // 1) Create the container
  const kpiContainer = document.createElement("div");
  kpiContainer.classList.add("kpi-container");

  // 2) Create the umbrella text
  const umbrella = document.createElement("div");
  umbrella.classList.add("kpi-umbrella");
  umbrella.textContent = "KPIs ";

  // 3) Create the 5 new buttons
  const userBtn = document.createElement("button");
  userBtn.textContent = "User";

  const gridBtn = document.createElement("button");
  gridBtn.textContent = "Grid";

  const envBtn = document.createElement("button");
  envBtn.textContent = "Env.";

  const mobilityBtn = document.createElement("button");
  mobilityBtn.textContent = "Mobility";

  const cityBtn = document.createElement("button");
  cityBtn.textContent = "City";

  userBtn.addEventListener("click", function () {
    console.log("User button clicked!");
    console.log("KPI data list:", kpi_data_list);
    active_kpi = "user_kpi";
    createUserKPIGraph(kpi_data_list);
    //  make the button active
    userBtn.classList.add("active");
    gridBtn.classList.remove("active");
    envBtn.classList.remove("active");
    mobilityBtn.classList.remove("active");
    cityBtn.classList.remove("active");
  });

  gridBtn.addEventListener("click", function () {
    active_kpi = "grid_kpi";
    createGridKPIGraph(kpi_data_list);

    //  make the button active
    userBtn.classList.remove("active");
    gridBtn.classList.add("active");
    envBtn.classList.remove("active");
    mobilityBtn.classList.remove("active");
    cityBtn.classList.remove("active");
  });

  envBtn.addEventListener("click", function () {
    active_kpi = "environment_kpi";
    createEnvironmentKPIGraph(kpi_data_list);
    //  make the button active
    userBtn.classList.remove("active");
    gridBtn.classList.remove("active");
    envBtn.classList.add("active");
    mobilityBtn.classList.remove("active");
    cityBtn.classList.remove("active");
  });

  mobilityBtn.addEventListener("click", function () {
    active_kpi = "mobility_kpi";
    createMobilityKPIGraph(kpi_data_list);
    //  make the button active
    userBtn.classList.remove("active");
    gridBtn.classList.remove("active");
    envBtn.classList.remove("active");
    mobilityBtn.classList.add("active");
    cityBtn.classList.remove("active");
  });

  cityBtn.addEventListener("click", function () {
    active_kpi = "city_kpi";
    createCityKPIGraph(kpi_data_list);
    //  make the button active
    userBtn.classList.remove("active");
    gridBtn.classList.remove("active");
    envBtn.classList.remove("active");
    mobilityBtn.classList.remove("active");
    cityBtn.classList.add("active");
  });

  userBtn.classList.add("active");

  // 4) Append them to the container
  kpiContainer.appendChild(umbrella);
  kpiContainer.appendChild(userBtn);
  kpiContainer.appendChild(gridBtn);
  kpiContainer.appendChild(envBtn);
  kpiContainer.appendChild(mobilityBtn);
  kpiContainer.appendChild(cityBtn);

  // 5) Replace the old "KPIs" button with the new container
  kpisButton.replaceWith(kpiContainer);

  // 6) Force a reflow, then add the "show" class for the transition
  requestAnimationFrame(() => {
    kpiContainer.classList.add("show");
  });
});

function clear_graph() {
  const container = document.getElementById("graph");

  // Replace the container's content with the loading animation
  container.innerHTML = `
    <div class="loading-container">
      <div class="spinner"></div>
      <div class="text">Calculating...</div>
      <div class="timer" id="timer">Time passed: 0 seconds</div>
    </div>
  `;

  // Start a timer to update the "Time passed" message
  let secondsPassed = 0;
  const timerElement = document.getElementById("timer");

  const timerInterval = setInterval(() => {
    secondsPassed++;
    timerElement.textContent = `Time passed: ${secondsPassed} second${secondsPassed !== 1 ? "s" : ""
      }`;
  }, 1000);
}
