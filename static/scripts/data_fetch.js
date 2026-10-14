import { calendarDate } from "./date_selection.js";

// Return the completed data to the caller, which owns rendering and stale-request checks.
export async function get_KPIs(selected_polygons, selected_area_names, selectedDates, options = {}) {
  if (selectedDates.length !== 2) throw new Error("Select both dates for the KPI range.");
  const startDate = calendarDate(selectedDates[0]);
  const endDate = calendarDate(selectedDates[1]);
  async function jsonFetch(url, body) {
    const response = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }
  return Promise.all(selected_polygons.map(async (polygon, index) => {
    const [stations, transformers] = await Promise.all([
      jsonFetch("/stations/within", polygon.geometry),
      jsonFetch("/features/transformers/within", { ...polygon.geometry, tr_type: "Middle" }),
    ]);
    const chargerIds = stations.features.map(feature => feature.properties.id);
    const transformerIds = transformers.features.map(feature => feature.properties.id);
    const kpi = await jsonFetch("/kpi/user", {
      selected_markers: chargerIds, start_date: startDate, end_date: endDate,
      session_source: options.sessionSource || "simple",
      demand_assumption: options.demandAssumption || "base", seed: options.seed ?? 42,
    });
    return {
      groupName: selected_area_names[index], kpi, source: kpi.source,
      chargerIds, transformerIds, number_of_chargers: chargerIds.length,
      number_of_transformers: transformerIds.length,
    };
  }));
}