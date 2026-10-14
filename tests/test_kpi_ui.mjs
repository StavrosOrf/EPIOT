import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

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
    const options = pickerOptions(true, new Date(2025, 8, 1), end, [start, end], () => {});
    assert.equal(options.mode, "range");
    assert.equal(calendarDate(options.maxDate), "2025-10-14");
    assert.deepEqual(options.defaultDate.map(calendarDate), ["2025-10-13", "2025-10-14"]);
    assert.equal(typeof options.onChange, "function");
  } finally {
    if (previousZone === undefined) delete process.env.TZ; else process.env.TZ = previousZone;
  }
});

test("switching tabs preserves the KPI range and the separate target date", () => {
  const day = new Date(2025, 9, 14), start = new Date(2025, 9, 10);
  const calls = [];
  const field = { classList: { toggle() {} } };
  const input = { closest: () => field };
  const factory = new Function("flatpickr", "pickerOptions", "document", "dateLabel", `
    let pickerRangeMode = true, selectedKpiRange = null, selectedTargetDate = new Date(2025,9,14);
    let starting_date = new Date(2025,8,1), today, dateInput;
    const onDateSelectionChange = () => {};
    let datepicker = { selectedDates: [new Date(2025,9,10), new Date(2025,9,14)], destroy() {} };
    ${functionBody("function resetDatepicker(", "function showTab(")}
    return resetDatepicker;
  `);
  const reset = factory((_id, options) => {
    calls.push(options);
    return { selectedDates: [options.defaultDate].flat(), destroy() {} };
  }, pickerOptions, { getElementById: () => input }, {});
  reset(false);
  reset(true);
  assert.equal(calendarDate(calls[0].defaultDate), calendarDate(day));
  assert.deepEqual(calls[1].defaultDate.map(calendarDate), [calendarDate(start), calendarDate(day)]);
});

test("the KPI tab keeps both source and demand selectors enabled", () => {
  const elements = Object.fromEntries(["session-source-field", "demand-assumption-field", "session-source-note"].map(id => [id, { hidden: true }]));
  const showTab = new Function("document", `
    let active_tab;
    const kpiSubnav = {}, strategyField = {}, viewToggleField = {};
    const $ = () => ({tooltip() {}});
    const setActiveTab = () => {}, resetDatepicker = () => {}, runActiveAnalysis = () => {};
    ${functionBody("function showTab(", 'document.getElementById("load-tab")')}
    return showTab;
  `)({ getElementById: id => elements[id] });
  showTab("stats-tab");
  assert.equal(elements["session-source-field"].hidden, false);
  assert.equal(elements["demand-assumption-field"].hidden, false);
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
    const datepicker = {selectedDates:[new Date(2025,9,13),new Date(2025,9,14)]};
    const selected_polygons = [], selected_area_names = [];
    const clear_graph = () => {}, showGraphMessage = () => {}, calculateLoadProfiles = () => {};
    const renderActiveKpi = () => render(kpi_data_list);
    ${functionBody("async function runActiveAnalysis(", 'analysisButton.addEventListener("click"')}
    return runActiveAnalysis;
  `)((_polygons, _names, _dates, options) => new Promise(resolve => requests.push({resolve, options})),
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
  const plots = [];
  const container = { clientWidth:1000, parentElement:{clientHeight:600}, dataset:{}, innerHTML:"" };
  const code = read("plotter.js").replace(/^export /gm, "");
  const charts = new Function("window", "document", "Plotly", "structuredClone", code+`;return {
    createUserKPIGraph,createGridKPIGraph,createMobilityKPIGraph,createCityKPIGraph,createEnvironmentKPIGraph
  };`)({innerWidth:1200,addEventListener(){}}, {getElementById:()=>container},
    {newPlot:(_container,data,layout)=>plots.push({data,layout})}, structuredClone);
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
  for (const chart of Object.values(charts)) chart(groups);
  assert.equal(plots.length, 5);
  for (const {data} of plots) for (const trace of data) assert.equal(trace.x.length, trace.y.length);
  assert.deepEqual(plots[3].data[0].x.slice(0,4), [0,.5,1,1.5]);
});
