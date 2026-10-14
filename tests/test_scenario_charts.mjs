import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

// Exercise the real chart functions with a plotting sink; no browser/CDN needed.
const code = readFileSync(new URL("../static/scripts/plotter.js", import.meta.url), "utf8").replace(/^export /gm, "");
function charts() {
  const captured = [];
  const container = { clientWidth: 1000, parentElement: { clientHeight: 600 }, dataset: {}, innerHTML: "" };
  const functions = new Function("window", "document", "Plotly", "structuredClone", code + ";return {createGraph, createFlexGraph};")(
    { innerWidth: 1200, addEventListener() {} }, { getElementById: () => container },
    { newPlot: (_container, data, layout) => captured.push({ data, layout }) }, structuredClone);
  return { ...functions, captured };
}

for (const targetSteps of [138, 144, 150]) {
  test(`scenario charts use ${targetSteps} actual target-day intervals`, () => {
    const api = charts();
    const times = Array.from({ length: 144 + targetSteps }, (_, i) => new Date(Date.UTC(2026, 9, 24) + i * 600000).toISOString());
    const group = { groupName: "Area", number_of_chargers: 2, number_of_transformers: 1,
      pastData: Array(144).fill(2), futureData: Array(targetSteps).fill(3),
      past_up_flex: Array(144).fill(1), past_down_flex: Array(144).fill(-1),
      future_up_flex: Array(targetSteps).fill(1), future_down_flex: Array(targetSteps).fill(-1),
      pastTimes: times.slice(0, 144), futureTimes: times.slice(144) };
    api.createGraph([group], true, "2026-10-25");
    api.createFlexGraph([group], false, "2026-10-25");
    for (const plot of api.captured) {
      for (const trace of plot.data) assert.equal(trace.x.length, trace.y.length);
      assert.equal(plot.layout.shapes[1].x0, times[144]);
      assert.equal(plot.layout.shapes[1].x1, times.at(-1));
      assert.equal(plot.layout.xaxis1.title, "Time (UTC)");
    }
  });
}

test("selector exposes the three implemented sources", () => {
  const html = readFileSync(new URL("../templates/index.html", import.meta.url), "utf8");
  const selector = /<select id="session-source"[\s\S]*?<\/select>/.exec(html)[0];
  assert.deepEqual([...selector.matchAll(/value="([^"]+)"/g)].map(match => match[1]), ["simple", "spatial", "cpft"]);
});

test("export includes source provenance, exact timestamps and kW units", () => {
  const exporter = readFileSync(new URL("../static/scripts/utils.js", import.meta.url), "utf8").replace(/^export /gm, "");
  const exportFunctions = new Function("XLSX", exporter+";return {generateLoadDataSheet};")({ utils: { aoa_to_sheet: rows => rows } });
  const time = "2026-10-24T22:00:00+00:00";
  const rows = exportFunctions.generateLoadDataSheet([{ groupName: "Area", pastData: [11], futureData: [],
    past_up_flex: [0], future_up_flex: [], past_down_flex: [-1], future_down_flex: [],
    pastTimes: [time], futureTimes: [], source: { label: "Spatial session sampler", assumption: "base", synthetic: true } }]);
  assert.equal(rows[0][2], "EV Load (kW)");
  assert.equal(rows[1][1], "2026-10-24 22:00:00");
  assert.deepEqual(rows[1].slice(5), ["Spatial session sampler", "base", true]);
});
