import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { loadPlotter } from "./plotter_harness.mjs";

const read = file => readFileSync(new URL(`../static/scripts/${file}`, import.meta.url), "utf8");
const datesCode = read("date_selection.js").replace(/^export /gm, "");
const { calendarDate, pickerOptions } = new Function(datesCode+";return {calendarDate,pickerOptions};")();
const script = read("script.js");
const functionBody = (start, end) => script.slice(script.indexOf(start), script.indexOf(end, script.indexOf(start)));

test("local calendar dates survive UTC offsets and range endpoints stay inclusive", () => {
  const previousZone = process.env.TZ;
  process.env.TZ = "Europe/Amsterdam";
  try {
    const start = new Date(2025, 9, 13), end = new Date(2025, 9, 14);
    assert.equal(start.toISOString().slice(0, 10), "2025-10-12");
    assert.equal(calendarDate(start), "2025-10-13");
    assert.equal(calendarDate(end), "2025-10-14");
    const options = pickerOptions(true, null, end, [start, end], () => {});
    assert.equal(options.mode, "range");
    assert.equal(options.maxDate, null);
    assert.equal(options.minDate, null);
    assert.deepEqual(options.defaultDate.map(calendarDate), ["2025-10-13", "2025-10-14"]);
    assert.equal(typeof options.onChange, "function");
  } finally {
    if (previousZone === undefined) delete process.env.TZ; else process.env.TZ = previousZone;
  }
});

test("future dates are valid scenario dates and stay selected", () => {
  const today = new Date(2025, 9, 14), future = new Date(2026, 2, 29);
  const options = pickerOptions(false, null, today, [future], () => {});
  assert.equal(calendarDate(options.defaultDate), "2026-03-29");
  assert.equal(options.maxDate, null);
});

test("only the KPI tab shows the KPI category bar", () => {
  const elements = { "session-source-note": { textContent: "" } };
  const kpiSubnav = { hidden: true };
  const showTab = new Function("document", "kpiSubnav", `
    let active_tab;
    const $ = () => ({tooltip() {}});
    const setActiveTab = () => {}, runActiveAnalysis = () => {};
    ${functionBody("function showTab(", 'document.getElementById("load-tab")')}
    return showTab;
  `)({ getElementById: id => elements[id] }, kpiSubnav);
  showTab("stats-tab");
  assert.equal(kpiSubnav.hidden, false);
  showTab("flex-tab");
  assert.equal(kpiSubnav.hidden, true);
  showTab("load-tab");
  assert.equal(kpiSubnav.hidden, true);
});

test("pickers show the weekday, so weekends are visible in the field", () => {
  const day = new Date(2026, 9, 17);
  const single = pickerOptions(false, null, day, [day], () => {});
  const range = pickerOptions(true, null, day, [new Date(2026, 9, 10), day], () => {});
  assert.equal(single.dateFormat, "D Y-m-d");
  assert.equal(range.dateFormat, "D j M");
  assert.equal(range.locale.rangeSeparator, " – ");
});

function requester(fetch) {
  const code = read("data_fetch.js").replace(/^import .*\n/gm, "").replace(/^export /gm, "");
  return new Function("fetch", "calendarDate", code+";return get_KPIs;")(fetch, calendarDate);
}

test("KPI requests use JSON point IDs, local dates and the selected source", async () => {
  const calls = [];
  const getKpis = requester(async (url, request) => {
    const body = request.body ? JSON.parse(request.body) : undefined;
    calls.push({url, request, body});
    const data = url === "/kpi/user" ? { source: { label: "CPFT", source: body.session_source } }
      : url.endsWith("analysis-version") ? { infrastructure: "i1", analysis: "a1" } : { ids: [17] };
    return { ok: true, json: async () => data };
  });
  const polygon = { geometry: { type: "Polygon", coordinates: [] } };
  const result = await getKpis([polygon], ["Area"], [new Date(2025,9,13), new Date(2025,9,14)],
    { sessionSource: "cpft", demandAssumption: "high", seed: 8 });
  const request = calls.find(call => call.url === "/kpi/user");
  assert.equal(request.request.method, "POST");
  assert.deepEqual(request.body, { selected_markers: [17], start_date: "2025-10-13", end_date: "2025-10-14",
    session_source: "cpft", demand_assumption: "high", seed: 8, section: "basic" });
  assert.equal(result[0].source.source, "cpft");
  assert.equal(result[0].number_of_transformers, 0);
  assert.ok(!calls.some(call => call.url.includes("transformers")));
  assert.ok(!("tr_type" in polygon.geometry));
});

test("an incomplete range makes no request and model errors remain visible", async () => {
  let calls = 0;
  const getKpis = requester(async url => {
    calls++;
    return url === "/kpi/user" ? { ok: false, json: async () => ({ error: "CPFT checkpoint unavailable" }) }
      : { ok: true, json: async () => url.endsWith("analysis-version")
        ? { infrastructure: "i1", analysis: "a1" } : { ids: [] } };
  });
  await assert.rejects(getKpis([], [], [new Date()], {}), /both dates/);
  assert.equal(calls, 0);
  await assert.rejects(getKpis([{geometry:{}}], ["Area"], [new Date(), new Date()], {sessionSource:"cpft"}), /checkpoint unavailable/);
});

test("changing source ignores a late result from the previous KPI request", async () => {
  const requests = [], renders = [];
  let source = "spatial";
  const execute = new Function("get_KPIs", "document", "render", `
    let active_tab = "KPIs", profileRequestVersion = 0, kpi_data_list = [], load_profile_data = [], charger_ids_list, transformer_ids_list;
    const selected_polygons = [{}], selected_area_names = ["Area"];
    const settingsOf = () => ({range: [new Date(2025,9,13), new Date(2025,9,14)], demand: "high"});
    const clear_graph = () => {}, showGraphMessage = () => {}, calculateLoadProfiles = () => {}, sourceNote = () => "";
    const renderActiveKpi = () => render(kpi_data_list);
    ${functionBody("async function runActiveAnalysis(", 'analysisButton.addEventListener("click"')}
    return runActiveAnalysis;
  `)((_polygons, _names, dates, options) => new Promise(resolve => requests.push({resolve, options, dates})),
    {getElementById: id => ({value: id === "session-source" ? source : "base"})}, result => renders.push(result));
  const oldRequest = execute();
  source = "cpft";
  const newRequest = execute();
  const group = value => [{source:{label:value,note:"Synthetic",assumption:"base"},chargerIds:[],transformerIds:[]}];
  requests[1].resolve(group("cpft"));
  await newRequest;
  requests[0].resolve(group("spatial"));
  await oldRequest;
  assert.equal(requests[0].options.sessionSource, "spatial");
  assert.equal(requests[1].options.sessionSource, "cpft");
  // one date range and demand scenario per area, taken from that area's settings
  assert.deepEqual(requests[1].dates.map(range => range.map(day => day.getDate())), [[13, 14]]);
  assert.deepEqual(requests[1].options.demandAssumption, ["high"]);
  assert.equal(renders.length, 1);
  assert.equal(renders[0][0].source.label, "cpft");
});

test("KPI export works without a load chart and records source and inclusive dates", () => {
  const sheets = [];
  const code = read("utils.js").replace(/^export /gm, "");
  const save = new Function("XLSX", code+";return generateAndDownloadExcel;")({ utils: {
    aoa_to_sheet: rows => rows, book_new: () => ({}), book_append_sheet: (_book, data, name) => sheets.push({data,name}),
  }, writeFile() {} });
  const kpi = { source:{label:"Spatial session sampler",assumption:"high",synthetic:true},
    range:{start_date:"2025-10-13",end_date:"2025-10-14",timezone:"Europe/Amsterdam"} };
  for (const field of ["arrival", "consumption", "daily_consumption", "departure", "duration"]) {
    for (const kind of ["wd", "we"]) kpi[`${field}_dist_${kind}`] = [];
  }
  for (const kind of ["wd", "we"]) kpi[`hour_of_arrival_consumption_${kind}`] = [];
  for (const field of ["occupation_ratio_dist", "weekday_availability", "weekend_availability"]) kpi[field] = [];
  for (let i=0; i<7; i++) kpi[`sessions_per_day_${i}`] = [];
  save([[17]], [], [{groupName:"Area", kpi, source:kpi.source}]);
  assert.deepEqual(sheets.map(sheet => sheet.name), ["Charger IDs", "Area_KPIs"]);
  assert.deepEqual(sheets[0].data[1], ["Area", 17]);
  assert.ok(sheets[1].data.some(row => row[0] === "Session source" && row[1] === "Spatial session sampler"));
  assert.ok(sheets[1].data.some(row => row[0] === "End date (inclusive)" && row[1] === "2025-10-14"));
});

test("all five KPI chart types align their histogram bins and local half-hour axis", () => {
  const { api: charts, plots } = loadPlotter();
  const kpi = {};
  for (const field of ["arrival", "departure", "duration", "consumption", "daily_consumption"]) {
    for (const kind of ["wd", "we"]) kpi[`${field}_dist_${kind}`] = Array(["consumption","daily_consumption"].includes(field)?10:24).fill(1);
  }
  for (const kind of ["wd", "we"]) kpi[`hour_of_arrival_consumption_${kind}`] = Array(24).fill(1);
  for (let i=0;i<7;i++) kpi[`sessions_per_day_${i}`] = Array(6).fill(1/6);
  kpi.weekday_availability = kpi.weekend_availability = Array(48).fill(.8);
  kpi.occupation_ratio_dist = Array(20).fill(.05);
  for (const label of ["uncontrolled","delayed","avg"]) {
    kpi[`co2_intensities_${label}`] = Array(24).fill(100);
    kpi[`renewable_energy_shared_${label}`] = 50;
  }
  const groups = [{groupName:"Area",number_of_chargers:3,number_of_transformers:1,kpi}];
  for (const name of ["createUserKPIGraph", "createGridKPIGraph", "createMobilityKPIGraph", "createCityKPIGraph", "createEnvironmentKPIGraph"]) {
    charts[name](groups);
  }
  assert.equal(plots.length, 5);
  for (const {data} of plots) for (const trace of data) assert.equal(trace.x.length, trace.y.length);
  assert.deepEqual(plots[3].data[0].x.slice(0,4), [0,.5,1,1.5]);
});

const area = (kpi, groupName = "Area", chargers = 3) =>
  ({ groupName, number_of_chargers: chargers, number_of_transformers: 0, kpi });
const metaOf = host => host.find(node => node.className === "group-card__meta").map(node => node.textContent);

test("KPI histograms are shares of their own day type, with an open last bin marked", () => {
  const { api, plots } = loadPlotter();
  const duration = Array(24).fill(0);
  duration[2] = 3;
  duration[23] = 1;
  api.createUserKPIGraph([area({ duration_dist_wd: duration, duration_dist_we: Array(24).fill(0) })]);
  const { data, layout } = plots[0];
  const weekdays = data.find(trace => trace.name === "Weekdays");
  assert.equal(weekdays.x.length, 25);  // bin edges, so a bar sits over its own interval
  assert.equal(weekdays.y[2], 75);
  assert.equal(weekdays.y[23], 25);
  assert.equal(weekdays.y[24], weekdays.y[23]);  // closes the last bin
  assert.equal(weekdays.customdata[2], 3);
  assert.deepEqual(layout.xaxis1.tickvals, [0, 6, 12, 18, 24]);
  assert.equal(layout.xaxis1.ticktext.at(-1), "24+");
  // A day type without sessions is a flat line, not a division by zero
  assert.ok(data.find(trace => trace.name === "Weekends").y.every(value => value === 0));
});

test("arrival hours are a closed range, so only open-ended bins get a plus", () => {
  const { api, plots } = loadPlotter();
  api.createUserKPIGraph([area({ arrival_dist_wd: Array(24).fill(1) })]);
  assert.equal(plots[0].layout.xaxis1.ticktext.at(-1), "24");
});

test("idle charger-days stay out of the daily energy histogram", () => {
  const { api, plots } = loadPlotter();
  const daily = [10, 5, ...Array(8).fill(0)];
  api.createGridKPIGraph([area({ daily_consumption_dist_wd: daily, idle_charger_days_wd: 6 })]);
  const weekdays = plots[0].data.find(trace => trace.name === "Weekdays");
  assert.equal(weekdays.customdata[0], 4);
  assert.ok(Math.abs(weekdays.y[0] - 100 * 4 / 9) < 1e-9);
  assert.equal(plots[0].layout.xaxis1.ticktext.at(-1), "200+");
});

test("areas share each panel's scale and panels without data are left out", () => {
  const { api, plots } = loadPlotter();
  const peaked = (hour, count) => Object.assign(Array(24).fill(0), { [hour]: count });
  api.createUserKPIGraph([
    area({ arrival_dist_wd: peaked(8, 10) }, "Quiet"),
    area({ arrival_dist_wd: [...Array(23).fill(1), 100] }, "Sharp"),
  ]);
  assert.equal(plots.length, 2);
  const [first, second] = plots.map(plot => plot.layout.yaxis1.range);
  assert.deepEqual(first, second);
  assert.ok(first[1] > 90);  // the sharper area's peak share (~81 %)
  assert.equal(plots[0].data.length, 1);  // no weekend, duration, departure or idle series
});

test("headline figures sit in each area's card", () => {
  const { api, host } = loadPlotter();
  api.createUserKPIGraph([area({
    arrival_dist_wd: Array(24).fill(1),
    summary: { session_count: 1234, mean_arrival_hour: 17.5, median_duration_hours: 8.04, p90_duration_hours: 14.2, slack_share: 0.71 },
    overflow: { duration: { wd: 2, we: 1 } },
  })]);
  const lines = metaOf(host);
  assert.ok(lines.includes("3 chargers"));
  assert.ok(lines.some(line => /1[.,]?234 sessions · arrive ~17:30/.test(line)), lines.join("|"));
  assert.ok(lines.includes("Stay: median 8.0 h · P90 14 h"));
  assert.ok(lines.includes("71% of stay time is idle"));
  assert.ok(lines.includes("3 stays over 24 h, in the last bin"));
});

test("grid dashboard shows load, load duration and the peak in local time", () => {
  const { api, plots, host } = loadPlotter();
  const profile = Array(48).fill(1);
  profile[12] = null;
  api.createGridKPIGraph([area({
    load_profile_wd: profile, load_profile_we: Array(48).fill(0),
    load_duration_kw: Array.from({ length: 21 }, (_, i) => 20 - i),
    summary: { peak_kw: 150, peak_time: "2026-03-07T06:00:00+01:00", load_factor: 0.0226, coincidence_factor: 0.872,
      idle_charger_day_share: 0.57 },
  })]);
  const { data, layout } = plots[0];
  assert.equal(layout.annotations[0].text, "<b>Uncontrolled load</b>");
  assert.equal(data[0].x.length, 49);
  assert.equal(data[0].y[12], null);  // an hour with no data is a gap, not zero
  assert.equal(layout.annotations[1].text, "<b>Load duration</b>");
  assert.equal(data.find(trace => trace.name === "Whole range").x[20], 100);
  const lines = metaOf(host);
  assert.ok(lines.includes("Peak 150 kW · Sat 07/03 06:00"), lines.join("|"));
  assert.ok(lines.includes("Load factor 0.02 · coincidence 0.87"));
  assert.ok(lines.includes("57% of charger-days idle"));
});

test("mobility dashboard plots the mean and busiest tenth per weekday, without invented days", () => {
  const { api, plots } = loadPlotter();
  const shares = [0.5, 0.5, 0, 0, 0, 0];
  const kpi = {};
  for (let day = 0; day < 7; day++) kpi[`sessions_per_day_${day}`] = day < 2 ? shares : Array(6).fill(0);
  kpi.sessions_per_day_observations = [4, 4, 0, 0, 0, 0, 0];
  kpi.sessions_per_day_mean = [0.5, 0.5, null, null, null, null, null];
  kpi.sessions_per_day_p90 = [1, 1, null, null, null, null, null];
  api.createMobilityKPIGraph([area(kpi)]);
  const { data, layout } = plots[0];
  const mean = data.find(trace => trace.name === "Mean");
  assert.deepEqual(mean.y.slice(0, 3), [0.5, 0.5, null]);
  assert.equal(data.find(trace => trace.name === "90th percentile").y[0], 1);
  assert.equal(layout.barmode, "stack");
  const none = data.find(trace => trace.name === "0 sessions");
  assert.deepEqual(none.y.slice(0, 3), [50, 50, null]);
});

test("mobility falls back to the histograms when a response has no per-weekday statistics", () => {
  const { api, plots } = loadPlotter();
  const kpi = {};
  for (let day = 0; day < 7; day++) kpi[`sessions_per_day_${day}`] = [0, 1, 0, 0, 0, 0];
  api.createMobilityKPIGraph([area(kpi)]);
  assert.deepEqual(plots[0].data.find(trace => trace.name === "Mean").y, Array(7).fill(1));
});

test("city dashboard ranks few chargers and summarises many", () => {
  const { api, plots } = loadPlotter();
  const usage = count => ({
    id: Array.from({ length: count }, (_, i) => 100 + i),
    occupancy: Array.from({ length: count }, (_, i) => i / 100),
    utilisation: Array(count).fill(0.1), sessions: Array(count).fill(1), energy_kwh: Array(count).fill(1),
  });
  const base = { weekday_availability: Array(48).fill(0.5), weekend_availability: Array(48).fill(1),
    occupation_ratio_dist: Array(20).fill(0.05) };
  api.createCityKPIGraph([area({ ...base, charger_usage: usage(3) }, "Few")]);
  api.createCityKPIGraph([area({ ...base, charger_usage: usage(40) }, "Many")]);
  const few = plots[0].data.filter(trace => trace.type === "bar");
  assert.deepEqual(few[0].x, ["#102", "#101", "#100"]);  // busiest first
  assert.deepEqual(few.map(trace => trace.name), ["Occupied", "Utilisation"]);
  assert.equal(plots[1].data.filter(trace => trace.type === "bar").length, 0);
  assert.equal(plots[1].data.at(-1).x.length, 21);
  // Free chargers is a share of all chargers, so its axis is the same everywhere
  assert.deepEqual(plots[0].layout.yaxis1.range, [0, 1]);
});

test("the blocking panel only appears when a response measured it", () => {
  const { api, plots } = loadPlotter();
  const base = { weekday_availability: Array(48).fill(0.5), weekend_availability: Array(48).fill(1) };
  api.createCityKPIGraph([area(base)]);
  api.createCityKPIGraph([area({ ...base, weekday_blocking: Array(48).fill(0.25), weekend_blocking: Array(48).fill(null) })]);
  assert.equal(plots[0].layout.annotations.length, 1);
  const titles = plots[1].layout.annotations.map(annotation => annotation.text);
  assert.ok(titles.includes("<b>All chargers busy</b>"));
});

test("a blocking probability that is always zero is said in words, not drawn", () => {
  const { api, plots, host } = loadPlotter();
  const base = { weekday_availability: Array(48).fill(0.5), weekend_availability: Array(48).fill(1),
    weekday_blocking: Array(48).fill(0), weekend_blocking: Array(48).fill(null),
    summary: { mean_occupancy_ratio: 0.2, max_blocking_probability: 0 } };
  api.createCityKPIGraph([area(base)]);
  const titles = plots[0].layout.annotations.map(annotation => annotation.text);
  assert.ok(!titles.includes("<b>All chargers busy</b>"));
  assert.equal(plots[0].layout.grid.columns, 1);  // the remaining panel takes the width
  assert.ok(metaOf(host).includes("Never all busy at once"));
});

test("only the stacked series of the mobility dashboard get legend entries", () => {
  const { api, plots } = loadPlotter();
  const kpi = {};
  for (let day = 0; day < 7; day++) kpi[`sessions_per_day_${day}`] = [0, 1, 0, 0, 0, 0];
  kpi.sessions_per_day_p90 = Array(7).fill(1);
  api.createMobilityKPIGraph([area(kpi)]);
  const listed = plots[0].data.filter(trace => trace.showlegend).map(trace => trace.name);
  assert.deepEqual(listed, ["0 sessions", "1 session", "2 sessions", "3 sessions", "4 sessions", "5+ sessions"]);
  assert.ok(plots[0].data.every(trace => !("hideLegend" in trace)));
});

test("an area without KPI data shows a message instead of an empty chart", () => {
  const { api, plots, host } = loadPlotter();
  api.createMobilityKPIGraph([area({})]);
  assert.equal(plots.length, 0);
  assert.ok(host.find(node => node.className === "group-card__empty").length);
});

test("KPI export adds the newer series and per-charger figures when present", () => {
  const sheets = [];
  const code = read("utils.js").replace(/^export /gm, "");
  const save = new Function("XLSX", code+";return generateAndDownloadExcel;")({ utils: {
    aoa_to_sheet: rows => rows, book_new: () => ({}), book_append_sheet: (_book, data, name) => sheets.push({data,name}),
  }, writeFile() {} });
  const kpi = { source: { label: "Spatial session sampler" }, range: {} };
  for (const field of ["arrival", "consumption", "daily_consumption", "departure", "duration", "slack"]) {
    for (const kind of ["wd", "we"]) kpi[`${field}_dist_${kind}`] = [1];
  }
  for (const kind of ["wd", "we"]) kpi[`hour_of_arrival_consumption_${kind}`] = [null];
  for (const field of ["occupation_ratio_dist", "weekday_availability", "weekend_availability"]) kpi[field] = [];
  for (let i = 0; i < 7; i++) kpi[`sessions_per_day_${i}`] = [];
  kpi.weekday_blocking = [0.5];
  kpi.charger_usage = { id: [7], occupancy: [0.4], utilisation: [0.1], sessions: [3], energy_kwh: [12] };
  kpi.summary = { session_count: 9, peak_kw: 33 };
  save([[7]], [], [{ groupName: "Area", kpi, source: kpi.source }]);
  const rows = sheets.find(sheet => sheet.name === "Area_KPIs").data;
  assert.ok(rows.some(row => row[0] === "slack_dist_wd"));
  assert.deepEqual(rows.find(row => row[0] === "weekday_blocking"), ["weekday_blocking", 0.5]);
  assert.ok(rows.some(row => row[0] === 7 && row[1] === 0.4 && row[3] === 3));
  assert.ok(rows.some(row => row[0] === "Peak uncontrolled load (kW)" && row[1] === 33));
  assert.ok(!rows.some(row => row[0] === "load_duration_kw"));
});
