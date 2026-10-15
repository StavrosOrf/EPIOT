// The analysis state the page's modules share. One object, so every module reads
// and writes the same arrays instead of a module-level variable in script.js.
// The result arrays are parallel to selected_area_names.
export function createState() {
  return {
    selected_polygons: [],
    selected_area_names: [],
    charger_ids_list: [],
    transformer_ids_list: [],
    load_profile_data: [],
    kpi_data_list: [],
    active_tab: "Load Profiles",
    active_kpi: "user_kpi",
    // Bumped by every full analysis, so answers to superseded requests are dropped
    profileRequestVersion: 0,
  };
}
