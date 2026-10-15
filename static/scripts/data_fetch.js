import { calendarDate } from "./date_selection.js";

// Bounded, page-local caches also share in-flight requests. Failed requests are
// removed immediately so a retry can recover. Values are never mutated by UI code.
const selections = new Map();
const profiles = new Map();
const environments = new Map();
let versionRequest = null;

async function jsonFetch(url, body) {
  const response = await fetch(url, body === undefined ? { cache: "no-store" } : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function cached(cache, key, fetchValue, limit = 64) {
  let pending = cache.get(key);
  if (pending) {
    cache.delete(key);
    cache.set(key, pending);
    return pending;
  }
  pending = Promise.resolve().then(fetchValue).catch(error => {
    if (cache.get(key) === pending) cache.delete(key);
    throw error;
  });
  cache.set(key, pending);
  while (cache.size > limit) cache.delete(cache.keys().next().value);
  return pending;
}

async function versions() {
  // One tiny freshness check per action; simultaneous area requests share it.
  if (!versionRequest) {
    versionRequest = jsonFetch("/stations/analysis-version").finally(() => { versionRequest = null; });
  }
  return versionRequest;
}

const sortedIds = ids => [...new Set(ids)].sort((a, b) => a - b);
// A setting is either shared by every area or given once per area
const forArea = (value, index) => (Array.isArray(value) ? value[index] : value);
const sourceOptions = (options, index = 0) => ({
  session_source: options.sessionSource || "simple",
  demand_assumption: forArea(options.demandAssumption, index) || "base", seed: options.seed ?? 42,
});

async function areaSelection(polygon, revision, gridView = false) {
  // Ignore non-geometric metadata such as tr_type from old map callers.
  const geometry = { type: polygon.geometry.type, coordinates: polygon.geometry.coordinates };
  const key = JSON.stringify([revision, geometry, gridView]);
  return cached(selections, key, async () => {
    if (!gridView) {
      const result = await jsonFetch("/stations/within?ids_only=1", geometry);
      return { chargerIds: sortedIds(result.ids), transformerIds: [] };
    }
    const transformers = await jsonFetch("/features/transformers/within?ids_only=1", { ...geometry, tr_type: "Middle" });
    const transformerIds = sortedIds(transformers.ids);
    const connected = transformerIds.length
      ? await jsonFetch("/stations/charging-points-by-transformers", { transformer_ids: transformerIds })
      : { charging_point_ids: [] };
    return { chargerIds: sortedIds(connected.charging_point_ids), transformerIds };
  });
}

// `date`, `options.strategy` and `options.demandAssumption` are one value for all areas or an
// array with one per area
export async function get_LoadProfiles(polygons, names, date, options = {}) {
  const revision = await versions();
  return Promise.all(polygons.map(async (polygon, index) => {
    const selection = await areaSelection(polygon, revision.infrastructure, Boolean(options.gridView));
    const query = { selected_markers: selection.chargerIds, date: forArea(date, index),
      strategy: forArea(options.strategy, index) || "avg", ...sourceOptions(options, index) };
    const response = await cached(profiles, JSON.stringify([revision.analysis, query]),
      () => jsonFetch("/stations/aggregate_load", query));
    return { ...selection, groupName: names[index], response };
  }));
}

// Return basic KPIs first. Environmental scheduling is requested independently.
// `selectedDates` is one [start, end] for all areas or an array of them, one per area
export async function get_KPIs(polygons, names, selectedDates, options = {}) {
  const shared = !Array.isArray(selectedDates[0]);
  const ranges = shared ? polygons.map(() => selectedDates) : selectedDates;
  if ((shared && selectedDates.length !== 2) || ranges.length !== polygons.length ||
      ranges.some(range => range.length !== 2)) {
    throw new Error("Select both dates for the KPI range.");
  }
  const revision = await versions();
  return Promise.all(polygons.map(async (polygon, index) => {
    const startDate = calendarDate(ranges[index][0]), endDate = calendarDate(ranges[index][1]);
    const selection = await areaSelection(polygon, revision.infrastructure);
    const query = { selected_markers: selection.chargerIds, start_date: startDate, end_date: endDate,
      ...sourceOptions(options, index) };
    const kpi = await jsonFetch("/kpi/user", { ...query, section: "basic" });
    return { ...selection, groupName: names[index], kpi, source: kpi.source,
      number_of_chargers: selection.chargerIds.length, number_of_transformers: 0,
      environmentQuery: query, analysisRevision: revision.analysis };
  }));
}

export async function get_EnvironmentKPIs(groups) {
  // Keep the exact selection/source/range captured by the completed basic request.
  const revision = await versions();
  if (groups.some(group => group.analysisRevision !== revision.analysis)) {
    throw new Error("Analysis inputs changed. Run the analysis again to refresh the KPIs.");
  }
  return Promise.all(groups.map(async group => {
    const query = { ...group.environmentQuery, section: "environment" };
    const result = await cached(environments, JSON.stringify([revision.analysis, query]),
      () => jsonFetch("/kpi/user", query));
    const { source, section, ...fields } = result;
    return { ...group, kpi: { ...group.kpi, ...fields } };
  }));
}
