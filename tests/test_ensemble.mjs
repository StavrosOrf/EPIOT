// Seeded draws: the band reaches the chart, the note, the request and the report.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { createAnalysis, profileFromGroup, sourceNote } from "../static/scripts/analysis.js";
import { createState } from "../static/scripts/app_state.js";
import { loadPlotter } from "./plotter_harness.mjs";

const STEPS = 288;
const times = Array.from({ length: STEPS }, (_, i) => new Date(Date.UTC(2026, 9, 14) + i * 600000).toISOString());
const band = (low, high, members = 10) => ({ p10: Array(STEPS).fill(low), p50: Array(STEPS).fill((low + high) / 2),
  p90: Array(STEPS).fill(high), members, seeds: [], quantiles: [10, 50, 90] });
const response = (ensemble) => ({
  y: Array(STEPS).fill(2), up_flex: Array(STEPS).fill(0), down_flex: Array(STEPS).fill(0), past_steps: 144, timestamps: times,
  source: { label: "Simple session sampler", note: "Synthetic.", ...(ensemble ? { ensemble } : {}) },
});
const group = (ensemble) => ({ groupName: "Area 1", chargerIds: [1, 2], transformerIds: [], response: response(ensemble) });
const settings = { strategy: "afap", date: new Date(2026, 9, 15) };

test("a single draw has no band and no extra text", () => {
  const profile = profileFromGroup(group(null), settings);
  assert.equal(profile.band, undefined);
  assert.doesNotMatch(sourceNote([response(null).source]), /percentile/);
});

test("draws give the chart data a band and the note says what it is", () => {
  const profile = profileFromGroup(group(band(1, 5, 10)), settings);
  assert.equal(profile.band.members, 10);
  assert.equal(profile.band.p90.length, STEPS);
  const note = sourceNote([response(band(1, 5, 10)).source]);
  assert.match(note, /10th to 90th percentile over 10 seeded draws/);
  assert.match(note, /line is one draw/);
});

test("the load chart shades the band over the lines and the scale includes its upper edge", () => {
  const { api, plots } = loadPlotter();
  const profile = profileFromGroup(group(band(1, 9, 10)), settings);
  api.createGraph([profile]);
  const names = plots[0].data.map(trace => trace.name);
  assert.deepEqual(names.slice(0, 2), ["Previous day", "Target day"]);
  const upper = plots[0].data.find(trace => /90th percentile of 10 draws/.test(trace.name || ""));
  const lower = plots[0].data.find(trace => trace.name === "10th percentile");
  assert.equal(upper.fill, "tonexty");
  assert.equal(lower.showlegend, false);
  assert.equal(plots[0].data.indexOf(upper), plots[0].data.indexOf(lower) + 1);
  assert.equal(upper.x.length, STEPS);
  assert.equal(upper.y[0], 9);
  // the band's top (9 kW) sets the scale, not the 2 kW line
  assert.ok(plots[0].layout.yaxis.range[1] >= 9);
  for (const trace of plots[0].data) assert.equal(trace.x.length, trace.y.length);
});

test("without a band the chart keeps just its two lines", () => {
  const { api, plots } = loadPlotter();
  api.createGraph([profileFromGroup(group(null), settings)]);
  assert.equal(plots[0].data.length, 2);
});

test("the analysis asks for the selected number of draws and passes them to each area", async () => {
  const requests = [];
  const state = createState();
  Object.assign(state, { selected_polygons: [{}, {}], selected_area_names: ["A", "B"] });
  const { calculateLoadProfiles } = createAnalysis({
    state, settingsOf: () => ({ strategy: "afap", demand: "base", date: new Date(2026, 9, 15) }),
    api: { get_LoadProfiles: async (...args) => { requests.push(args); return [group(band(1, 3)), group(band(2, 4))]; } },
    view: { sessionSource: () => "simple", ensembleSize: () => 10, setNote() {}, clearGraph() {},
            createGraph() {}, createPolytopeGraph() {}, showGraphMessage() {} },
  });
  await calculateLoadProfiles();
  assert.equal(requests[0][3].ensemble, 10);
  assert.deepEqual(state.load_profile_data.map(item => item.band.p10[0]), [1, 2]);
});

test("requests carry the draw count only when there is more than one", async () => {
  const source = readFileSync(new URL("../static/scripts/data_fetch.js", import.meta.url), "utf8")
    .replace(/\r\n/g, "\n").replace(/^import .*\n/gm, "").replace(/^export /gm, "");
  const bodies = [];
  const fetch = async (url, options) => {
    const body = options?.body ? JSON.parse(options.body) : null;
    if (url.endsWith("analysis-version")) return { ok: true, json: async () => ({ infrastructure: "i", analysis: "a" }) };
    if (url.startsWith("/stations/within")) return { ok: true, json: async () => ({ ids: [1] }) };
    bodies.push(body);
    return { ok: true, json: async () => ({ y: [], up_flex: [], down_flex: [], past_steps: 0 }) };
  };
  const { get_LoadProfiles } = new Function("fetch", "calendarDate", `${source};return {get_LoadProfiles};`)(fetch, () => "2026-10-15");
  const polygon = { geometry: { type: "Polygon", coordinates: [] } };
  await get_LoadProfiles([polygon], ["A"], "2026-10-15", { sessionSource: "simple", ensemble: 1 });
  await get_LoadProfiles([polygon], ["A"], "2026-10-15", { sessionSource: "simple", ensemble: 10 });
  assert.equal("ensemble" in bodies[0], false);
  assert.equal(bodies[1].ensemble, 10);
});

test("the report adds the band's percentiles only when draws were requested", () => {
  const exporter = readFileSync(new URL("../static/scripts/utils.js", import.meta.url), "utf8").replace(/^export /gm, "");
  const { generateLoadDataSheet } = new Function("XLSX", `${exporter};return {generateLoadDataSheet};`)(
    { utils: { aoa_to_sheet: rows => rows } });
  const base = { groupName: "Area", pastData: [1], futureData: [2], past_up_flex: [0], future_up_flex: [0],
    past_down_flex: [0], future_down_flex: [0], pastTimes: [times[0]], futureTimes: [times[1]], strategy: "afap",
    source: { label: "Simple session sampler", assumption: "base", synthetic: true } };
  const plain = generateLoadDataSheet([base]);
  assert.equal(plain[0].at(-1), "Charging strategy");
  const banded = generateLoadDataSheet([{ ...base, band: { p10: [0.5, 1.5], p90: [1.5, 2.5], members: 10 } }]);
  assert.deepEqual(banded[0].slice(-2), ["EV Load 10th percentile (kW)", "EV Load 90th percentile (kW)"]);
  assert.deepEqual(banded[1].slice(-2), [0.5, 1.5]);
  assert.deepEqual(banded[2].slice(-2), [1.5, 2.5]);
});
