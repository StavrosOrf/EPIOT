// Function to convert H3 hexagon coordinates to Leaflet's LatLngs
export function h3ToPolygon(h3Index) {
  const hexBoundary = h3.cellToBoundary(h3Index, true);
  return hexBoundary.map(([lat, lng]) => [lat, lng]);
}

// Function to generate the hexagonal grid based on the map bounds
export function generateHexGrid(map, hexResolution, clickedHexagons) {
  // remove all hexagons before generating new ones
  map.eachLayer(function (layer) {
    if (layer instanceof L.Polygon) {
      map.removeLayer(layer);
    }
  });

  // Get the current bounds of the visible map
  const bounds = map.getBounds();
  const northWest = bounds.getNorthWest();
  const southEast = bounds.getSouthEast();

  // Create a polygon that represents the visible area of the map
  const boundingPolygon = [
    [northWest.lat, northWest.lng],
    [northWest.lat, southEast.lng],
    [southEast.lat, southEast.lng],
    [southEast.lat, northWest.lng],
  ];

  // Use h3.polyfill to fill the bounding polygon with adjacent hexagons
  const hexagons = h3.polygonToCells(boundingPolygon, hexResolution, true);

  // Create Leaflet polygons for each hexagon
  hexagons.forEach((hex) => {
    const polygon = h3ToPolygon(hex);

    const hexPolygon = L.polygon(polygon, {
      color: "blue", // Hexagon border color
      transparency: 0.1,
      weight: 0.2, // Hexagon border width
      fillColor: "#3399ff", // Fill color of the hexagons
      fillOpacity: 0.001,
    });

    // if polygon already exists in the map dont add it again
    map.eachLayer(function (layer) {
      if (layer instanceof L.Polygon) {
        if (layer.getLatLngs() === hexPolygon.getLatLngs()) {
          console.log("Polygon already exists");
          return;
        }
      }
    });

    hexPolygon.addTo(map);

    // Add a click event listener to toggle color and store/remove from the list
    hexPolygon.on("click", function () {
      // Check if the hexagon is already clicked
      const hexIndex = clickedHexagons.indexOf(hex);
      if (hexIndex === -1) {
        // Hexagon not clicked yet, change color to blue and add to list
        this.setStyle({
          fillColor: "3399ff", // Change fill color to blue when clicked
          fillOpacity: 0.5,
        });
        clickedHexagons.push(hex); // Add to clicked list
      } else {
        // Hexagon is already clicked, revert to original color and remove from list
        this.setStyle({
          fillColor: "#3399ff", // Revert to original fill color
          fillOpacity: 0.001,
        });
        clickedHexagons.splice(hexIndex, 1); // Remove from clicked list
      }

      console.log("Clicked hexagons:", clickedHexagons);

      // Add the hexagon to the map
      map.addLayer(hexPolygon);
    });
  });

}
