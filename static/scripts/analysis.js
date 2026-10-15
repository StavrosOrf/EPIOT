// The analysis run: one request per area, the shared result arrays, and what the
// page shows for them. Everything the page provides (requests, charts, DOM) is
// passed in, so this module has no globals and tests can import it directly.
import { calendarDate } from "./date_selection.js";
import { calendarNote } from "./calendar_note.js";

export const DEFAULT_NOTE = "Synthetic scenarios with assumed demand, not verified local charging forecasts.";

// The day effects when every area shares them, a pointer to the per-area date
// tooltips when they differ
export function calendarSummary(sources) {
  const notes = [...new Set(sources.map(source => calendarNote(source)).filter(Boolean))];
  if (notes.length > 1) return "Day effects differ per area; hover an area's date for details.";
  return notes[0] || "";
}

// The line under the controls: source, demand assumption and day effects
export function sourceNote(sources, extra = "") {
  const metadata = sources[0];
  if (!metadata) return "No charging points in this selection.";
  const draws = metadata.ensemble
    ? ` The shaded band is the 10th to 90th percentile over ${metadata.ensemble.members} seeded draws; the line is one draw.`
    : "";
  return `${metadata.label}. ${metadata.note} ${calendarSummary(sources)}${extra}${draws}`;
}

// One area's chart data from its response and the settings it was requested with
export function profileFromGroup(group, settings) {
  const response = group.response, split = response.past_steps ?? 144;
  return {
    groupName: group.groupName,
    pastData: response.y.slice(0, split), futureData: response.y.slice(split),
    past_up_flex: response.up_flex.slice(0, split), future_up_flex: response.up_flex.slice(split),
    past_down_flex: response.down_flex.slice(0, split), future_down_flex: response.down_flex.slice(split),
    pastTimes: response.timestamps?.slice(0, split), futureTimes: response.timestamps?.slice(split),
    source: response.source, targetDate: calendarDate(settings.date), strategy: settings.strategy,
    polytope: response.flex_polytope,
    // Percentiles over several seeded draws, when more than one was requested
    band: response.source?.ensemble
      ? { p10: response.source.ensemble.p10, p90: response.source.ensemble.p90, members: response.source.ensemble.members }
      : undefined,
    number_of_chargers: group.chargerIds.length, number_of_transformers: group.transformerIds.length,
  };
}

/**
 * @param {object} deps
 * @param {object} deps.state shared analysis state (see app_state.js)
 * @param {(name: string) => object} deps.settingsOf an area's strategy, date, range and demand
 * @param {object} deps.api get_LoadProfiles, get_KPIs, get_EnvironmentKPIs
 * @param {object} deps.view what the page provides:
 *   sessionSource(), setNote(text), clearGraph(), showGraphMessage(title, text),
 *   createGraph(profiles), createPolytopeGraph(profiles), kpiRenderers {key: render(groups)},
 *   environmentSummary() (the container element), renderEnvironmentSummary(groups, container)
 */
export function createAnalysis({ state, settingsOf, api, view }) {
  const { get_LoadProfiles, get_KPIs, get_EnvironmentKPIs } = api;

  async function calculateLoadProfiles() {
    const requestVersion = ++state.profileRequestVersion;
    // Every area is analysed under its own strategy, target date and demand scenario
    const settings = state.selected_area_names.map(name => ({ ...settingsOf(name) }));
    state.load_profile_data = [];
    try {
      const groups = await get_LoadProfiles(structuredClone(state.selected_polygons), state.selected_area_names.slice(),
        settings.map(item => calendarDate(item.date)), {
          sessionSource: view.sessionSource(),
          demandAssumption: settings.map(item => item.demand),
          strategy: settings.map(item => item.strategy),
          ensemble: view.ensembleSize?.() ?? 1,
        });
      if (requestVersion !== state.profileRequestVersion) return;
      state.charger_ids_list = groups.map(group => group.chargerIds);
      state.transformer_ids_list = groups.map(group => group.transformerIds);
      state.load_profile_data = groups.map((group, index) => profileFromGroup(group, settings[index]));
      const sources = groups.map(group => group.response.source);
      view.setNote(sourceNote(sources,
        sources[0]?.grid_uses_historical_reference ? " Minimum-carbon estimates use a historical grid reference." : ""));
      if (state.active_tab === "Load Profiles") view.createGraph(state.load_profile_data);
      else if (state.active_tab === "Flexibility") view.createPolytopeGraph(state.load_profile_data);
    } catch (error) {
      if (requestVersion !== state.profileRequestVersion) return;
      view.showGraphMessage("Load profiles are not available for this selection", error.message);
    }
  }

  async function runActiveAnalysis() {
    if (state.active_tab == "KPIs") {
      const requestVersion = ++state.profileRequestVersion;
      state.kpi_data_list = [];
      state.load_profile_data = [];
      view.clearGraph();
      try {
        // Every area has its own date range and demand scenario
        const result = await get_KPIs(state.selected_polygons.slice(), state.selected_area_names.slice(),
          state.selected_area_names.map(name => settingsOf(name).range.slice()), {
            sessionSource: view.sessionSource(),
            demandAssumption: state.selected_area_names.map(name => settingsOf(name).demand),
          });
        if (requestVersion !== state.profileRequestVersion) return;
        state.kpi_data_list = result;
        state.charger_ids_list = result.map(group => group.chargerIds);
        state.transformer_ids_list = result.map(group => group.transformerIds);
        view.setNote(sourceNote(result.map(group => group.source)));
        renderActiveKpi();
      } catch (error) {
        if (requestVersion !== state.profileRequestVersion) return;
        view.showGraphMessage("KPIs are not available for this selection", error.message);
      }
    } else {
      state.kpi_data_list = [];
      view.clearGraph();
      calculateLoadProfiles();
    }
  }

  async function ensureEnvironmentKpis(groups) {
    if (!groups.length || groups.every(group => group.kpi.environment)) return groups;
    const result = await get_EnvironmentKPIs(groups);
    if (state.kpi_data_list === groups) state.kpi_data_list = result;
    return result;
  }

  async function renderActiveKpi() {
    const requestVersion = state.profileRequestVersion;
    const stale = () => requestVersion !== state.profileRequestVersion || state.active_tab !== "KPIs" ||
      state.active_kpi !== "environment_kpi";
    if (state.active_kpi === "environment_kpi" && state.kpi_data_list.some(group => !group.kpi.environment)) {
      view.clearGraph();
      try {
        await ensureEnvironmentKpis(state.kpi_data_list);
      } catch (error) {
        if (requestVersion === state.profileRequestVersion && state.active_tab === "KPIs" &&
            state.active_kpi === "environment_kpi") {
          view.showGraphMessage("Environmental KPIs are not available", error.message);
        }
        return;
      }
      if (stale()) return;
    }
    const environmentalSummary = view.environmentSummary();
    if (state.active_kpi === "environment_kpi") view.renderEnvironmentSummary(state.kpi_data_list, environmentalSummary);
    else if (environmentalSummary) environmentalSummary.hidden = true;
    if (!state.kpi_data_list.length) {
      view.showGraphMessage("Select an area for KPIs", "Draw an area containing charging points.");
      return;
    }
    if (state.active_kpi === "environment_kpi" && state.kpi_data_list.every(group => !group.kpi.environment.covered_steps &&
        !Object.values(group.kpi.environment.strategies || {}).some(value => value.renewable_energy_coverage_pct > 0))) {
      view.showGraphMessage("Environmental data are unavailable for this range",
        "Choose dates with stored grid-mix data. Other KPIs use the selected session source.");
      return;
    }
    view.kpiRenderers[state.active_kpi](state.kpi_data_list);
    if (state.active_kpi === "environment_kpi") {
      const metadata = state.kpi_data_list[0].source;
      const usesReference = state.kpi_data_list.some(group => group.kpi.environment.uses_historical_reference);
      view.setNote(`${metadata.label}. ${metadata.note} ${usesReference
        ? "Environmental estimates use a historical grid reference."
        : "Environmental estimates use matching-date grid data where available."}`);
    }
  }

  // Redraw whatever the active tab shows from the current result arrays
  function renderGroupResults() {
    if (state.active_tab === "KPIs") renderActiveKpi();
    else if (!state.selected_polygons.length) {
      view.showGraphMessage("No areas selected", "Draw an area on the map, then press Analyse.");
    } else if (state.active_tab === "Flexibility") view.createPolytopeGraph(state.load_profile_data);
    else view.createGraph(state.load_profile_data);
  }

  // The report button: a full KPI workbook includes the lazy environment section even if unopened
  async function exportReport(button, { generate, notify }) {
    if (button.disabled) return;
    button.disabled = true;
    const ids = state.charger_ids_list, profiles = state.load_profile_data, groups = state.kpi_data_list;
    try {
      const complete = await ensureEnvironmentKpis(groups);
      generate(ids, profiles, complete);
    } catch (error) {
      notify(error.message);
    } finally {
      button.disabled = false;
    }
  }

  return { calculateLoadProfiles, runActiveAnalysis, ensureEnvironmentKpis, renderActiveKpi, renderGroupResults, exportReport };
}
