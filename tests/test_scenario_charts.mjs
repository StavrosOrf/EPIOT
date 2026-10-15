import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { loadPlotter } from "./plotter_harness.mjs";

// Exercise the real chart functions with a plotting sink; no browser/CDN needed.
function areaWith(name, targetSteps, scale = 1) {
  const times = Array.from({ length: 144 + targetSteps }, (_, i) => new Date(Date.UTC(2026, 9, 24) + i * 600000).toISOString());
  return { times, group: { groupName: name, number_of_chargers: 2, number_of_transformers: 1,
    pastData: Array(144).fill(2 * scale), futureData: Array(targetSteps).fill(3 * scale),
    past_up_flex: Array(144).fill(1 * scale), past_down_flex: Array(144).fill(-1 * scale),
    future_up_flex: Array(targetSteps).fill(1 * scale), future_down_flex: Array(targetSteps).fill(-1 * scale),
    pastTimes: times.slice(0, 144), futureTimes: times.slice(144) } };
}

// A flat envelope around the schedule, for the flexibility (polytope) view
function withEnvelope(group) {
  const steps = group.pastData.length + group.futureData.length;
  group.polytope = { schedule_feasible: true, power_min_kw: Array(steps).fill(0), power_max_kw: Array(steps).fill(4),
    cumulative_min_kwh: Array(steps).fill(0), cumulative_max_kwh: Array(steps).fill(9) };
  return group;
}

for (const targetSteps of [138, 144, 150]) {
  test(`scenario charts use ${targetSteps} actual target-day intervals`, () => {
    const { api, plots } = loadPlotter();
    const { times, group } = areaWith("Area", targetSteps);
    api.createGraph([group]);
    api.createPolytopeGraph([withEnvelope(group)]);
    assert.equal(plots.length, 2);
    for (const plot of plots) {
      for (const trace of plot.data) assert.equal(trace.x.length, trace.y.length);
      assert.equal(plot.layout.shapes[1].x0, times[144]);
      assert.equal(plot.layout.shapes[1].x1, times.at(-1));
    }
    // Timestamps are UTC; the note costs the compact card no plot height
    assert.ok(plots[0].layout.annotations.some(annotation => annotation.text === "UTC"));
  });
}

test("each area gets its own card; the first cannot move up and the last cannot move down", () => {
  const { api, plots, cards } = loadPlotter();
  const groups = ["Area 1", "Area 2", "Area 3"].map(name => areaWith(name, 144).group);
  api.createGraph(groups, true);
  assert.equal(plots.length, 3);
  const buttons = card => card.find(node => node.tagName === "button");
  const state = card => Object.fromEntries(buttons(card).map(button => [button.dataset.action, Boolean(button.disabled)]));
  const [first, second, third] = cards();
  assert.deepEqual(state(first), { rename: false, up: true, down: false, duplicate: true, remove: false });
  assert.deepEqual(state(second), { rename: false, up: false, down: false, duplicate: true, remove: false });
  assert.deepEqual(state(third), { rename: false, up: false, down: true, duplicate: true, remove: false });
  assert.deepEqual(cards().map(card => card.attributes["aria-label"]), ["Area 1", "Area 2", "Area 3"]);
  assert.equal(first.find(node => node.className === "group-card__name")[0].textContent, "Area 1");
});

test("copying is offered only while the page allows another area", () => {
  const { api, cards } = loadPlotter();
  api.setGroupControls({ canDuplicate: () => true });
  api.createGraph([areaWith("Area 1", 144).group], true);
  const copy = cards()[0].find(node => node.dataset && node.dataset.action === "duplicate")[0];
  assert.equal(copy.disabled, false);
});

test("areas share one scale so their loads stay comparable across cards", () => {
  const { api, plots } = loadPlotter();
  api.createGraph([areaWith("Small", 144, 1).group, areaWith("Large", 144, 10).group]);
  const [small, large] = plots.map(plot => plot.layout.yaxis.range);
  assert.deepEqual(small, large);
  assert.ok(large[1] >= 30);
});

test("the two days are told apart by colour, and each band is labelled with weekday and date", () => {
  const { api, plots } = loadPlotter();
  // 17 October 2026 is a Saturday: the target day is a weekend day
  const { group } = areaWith("Area", 144);
  group.targetDate = "2026-10-17";
  api.createGraph([group]);
  const [previous, target] = plots[0].data;
  assert.equal(previous.name, "Previous day");
  assert.equal(target.name, "Target day");
  assert.equal(previous.line.color, "#eb6834");
  assert.equal(target.line.color, "#2a78d6");
  assert.notEqual(plots[0].layout.shapes[0].fillcolor, plots[0].layout.shapes[1].fillcolor);
  const labels = plots[0].layout.annotations.map(annotation => annotation.text).filter(text => /day/.test(text));
  assert.deepEqual(labels.map(text => text.replace(/<\/?b>/g, "")), ["Previous day · Fri 16/10/2026", "Target day · Sat 17/10/2026"]);
  assert.ok(labels[1].startsWith("<b>"), "weekend days are bold");
  assert.ok(!labels[0].startsWith("<b>"));
});

test("weekday labels come from the target date, not the browser's time zone", () => {
  const previousZone = process.env.TZ;
  process.env.TZ = "America/Los_Angeles";
  try {
    const { api, plots } = loadPlotter();
    const { group } = areaWith("Area", 144);
    group.targetDate = "2026-10-15";
    api.createGraph([group]);
    const labels = plots[0].layout.annotations.map(annotation => annotation.text).filter(text => /day ·/.test(text));
    assert.deepEqual(labels, ["Previous day · Wed 14/10/2026", "Target day · Thu 15/10/2026"]);
  } finally {
    if (previousZone === undefined) delete process.env.TZ; else process.env.TZ = previousZone;
  }
});

test("the flexibility view labels the days in both subplots", () => {
  const { api, plots } = loadPlotter();
  const { group } = areaWith("Area", 144);
  group.targetDate = "2026-10-16";
  api.createPolytopeGraph([withEnvelope(group)]);
  const layout = plots[0].layout;
  assert.equal(layout.shapes.length, 4);
  assert.deepEqual(layout.shapes.map(shape => shape.xref), ["x", "x", "x2", "x2"]);
  const labels = layout.annotations.filter(annotation => /day ·/.test(annotation.text));
  assert.deepEqual(labels.map(annotation => annotation.xref), ["x", "x", "x2", "x2"]);
  assert.match(labels[0].text, /Thu 15\/10\/2026/);
  assert.match(labels[1].text, /Fri 16\/10\/2026/);
  // headroom above the curves keeps the day labels clear of them
  assert.ok(layout.yaxis.range[1] > 4);
});

test("there is no headroom chart any more", () => {
  const { api } = loadPlotter();
  assert.equal(api.createFlexGraph, undefined);
});

test("the polytope view keeps a card for areas without an envelope", () => {
  const { api, plots, cards } = loadPlotter();
  api.createPolytopeGraph([withEnvelope(areaWith("Area 1", 144).group), areaWith("Area 2", 144).group]);
  assert.equal(cards().length, 2);
  assert.equal(plots.length, 1);
  for (const trace of plots[0].data) assert.equal(trace.x.length, trace.y.length);
  assert.equal(plots[0].layout.grid.columns, 2);
});

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
    pastTimes: [time], futureTimes: [], strategy: "alap",
    source: { label: "Spatial session sampler", assumption: "base", synthetic: true } }]);
  assert.equal(rows[0][2], "EV Load (kW)");
  assert.equal(rows[0].at(-1), "Charging strategy");
  assert.equal(rows[1][1], "2026-10-24 22:00:00");
  assert.deepEqual(rows[1].slice(5), ["Spatial session sampler", "base", true, "As Late As Possible"]);
});

test("charts without timestamps fall back to each area's own target date", () => {
  const { api, plots } = loadPlotter();
  const bare = (name, targetDate) => ({ groupName: name, targetDate, number_of_chargers: 1, number_of_transformers: 0,
    pastData: Array(144).fill(1), futureData: Array(144).fill(1),
    past_up_flex: Array(144).fill(1), future_up_flex: Array(144).fill(1),
    past_down_flex: Array(144).fill(-1), future_down_flex: Array(144).fill(-1) });
  api.createGraph([bare("A", "2026-03-10"), bare("B", "2026-07-20")], true);
  const [first, second] = plots.map(plot => plot.data[0].x[0]);
  assert.equal(plots[0].data[0].x.length, 144);
  assert.ok(first instanceof Date && second instanceof Date);
  assert.equal(first.getMonth(), 2);
  assert.equal(second.getMonth(), 6);
});

test("sheet names from typed area names are valid, short and unique", () => {
  const sheets = [];
  const exporter = readFileSync(new URL("../static/scripts/utils.js", import.meta.url), "utf8").replace(/\r\n/g, "\n").replace(/^export /gm, "");
  const save = new Function("XLSX", exporter + ";return generateAndDownloadExcel;")({ utils: {
    aoa_to_sheet: rows => rows, book_new: () => ({}), book_append_sheet: (_book, data, name) => sheets.push(name),
  }, writeFile() {} });
  const kpi = { source: { label: "Spatial session sampler" }, range: {} };
  for (const field of ["arrival", "consumption", "daily_consumption", "departure", "duration"]) {
    for (const kind of ["wd", "we"]) kpi[`${field}_dist_${kind}`] = [];
  }
  for (const kind of ["wd", "we"]) kpi[`hour_of_arrival_consumption_${kind}`] = [];
  for (const field of ["occupation_ratio_dist", "weekday_availability", "weekend_availability"]) kpi[field] = [];
  for (let i = 0; i < 7; i++) kpi[`sessions_per_day_${i}`] = [];
  const long = "North harbour district, east quay and the old ferry terminal";
  const names = ["Docks: [A]/B?", long, long, "Area"];
  save(names.map(() => [1]), [], names.map(name => ({ groupName: name, kpi, source: kpi.source })));
  const kpiSheets = sheets.filter(name => name !== "Charger IDs");
  assert.equal(kpiSheets.length, 4);
  for (const name of kpiSheets) {
    assert.ok(name.length <= 31, name);
    assert.ok(!/[\\/?*\[\]:]/.test(name), name);
    assert.ok(name.endsWith("_KPIs"), name);
  }
  assert.equal(new Set(kpiSheets.map(name => name.toLowerCase())).size, 4);
});
