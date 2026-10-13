import {
  createUserKPIGraph,
  createGridKPIGraph,
  createMobilityKPIGraph,
  createCityKPIGraph,
  createEnvironmentKPIGraph,
  showGraphMessage,
} from "./plotter.js";
import { animateSelectMessage } from "./utils.js";
export function get_KPIs(
  selected_polygons,
  selected_area_names,
  datepicker,
  active_kpi
) {
  // allocate a list with selectedpolygons.length elements
  var charger_ids_list = Array(selected_polygons.length).fill(null);
  var transformer_ids_list = Array(selected_polygons.length).fill(null);
  let kpi_data_list = [];

  console.log("=================KPIs====================");

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
      // get charging strategy from the dropdown
      var chargingStrategy = document.getElementById("strategy").value;

      // Function to fetch aggregate load data for a single charger
      function fetchKPIs(chargerId, area_name) {
        let startDate = datepicker.selectedDates[0];
        let endDate = datepicker.selectedDates[1];
        console.log("Start Date:", startDate);
        console.log("End Date:", endDate);
        console.log("Charger IDs:", chargerId);
        let url = `/kpi/user?selected_markers=${encodeURIComponent(chargerId)}
        &start_date=${encodeURIComponent(
          startDate.toISOString()
        )}&end_date=${encodeURIComponent(endDate.toISOString())}`;

        return fetch(url, {
          method: "GET",
        })
          .then((response) => {
            if (!response.ok) throw new Error("Network response was not ok");
            return response.text();
          })
          .then((text) => {
            // Replace all NaN occurrences with 'null' before parsing
            const safeJson = text.replace(/NaN/g, "null");
            const data = JSON.parse(safeJson);
            return data; // Resolved data for this specific charger
          })
          .catch((error) => {
            console.error(
              `Error fetching data for chargers ${chargerId}:`,
              error
            );
            return null; // Return null in case of an error
          });
      }

      // Create promises for each chargerId and keep their order
      let fetchPromises = charger_ids_list.map((chargerIds, index) => {
        let chargerId = chargerIds;
        let area_name = index;
        return fetchKPIs(chargerId, area_name)
          .then((data) => {
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
        .then((kpi_data) => {
          const failed = kpi_data
            .map((item, i) => (item.data ? null : selected_area_names[i]))
            .filter((name) => name !== null);
          if (failed.length) {
            showGraphMessage(
              "KPIs are not available for this selection",
              `No session data could be computed for ${failed.join(", ")}. ` +
                "Make sure each area contains chargers, or try a different date range."
            );
            return;
          }

          for (let i = 0; i < kpi_data.length; i++) {
            // find area name from the selected_area_names
            let area_name = selected_area_names[i];
            console.log("---Area Name:", area_name, i);
            console.log("---KPI Data:", kpi_data[i], i);
            let temp_data = {
              groupName: area_name,
              kpi: kpi_data[i].data,

              number_of_chargers: charger_ids_list[i].length,
              number_of_transformers: transformer_ids_list[i].length,
            };
            kpi_data_list.push(temp_data);
          }

          console.log("KPI data:", kpi_data_list);
          console.log("Active KPI (request):", active_kpi);

          if (active_kpi == "user_kpi") {
            createUserKPIGraph(kpi_data_list);
          } else if (active_kpi == "grid_kpi") {
            createGridKPIGraph(kpi_data_list);
          } else if (active_kpi == "mobility_kpi") {
            createMobilityKPIGraph(kpi_data_list);
          } else if (active_kpi == "environment_kpi") {
            createEnvironmentKPIGraph(kpi_data_list);
          } else if (active_kpi == "city_kpi") {
            createCityKPIGraph(kpi_data_list);
          }
        })
        .catch((error) => {
          console.error("Error in Promise.all:", error);
          showGraphMessage("Something went wrong while drawing the KPIs", String(error));
        });
    });
  });
  return charger_ids_list, transformer_ids_list, kpi_data_list;
}
