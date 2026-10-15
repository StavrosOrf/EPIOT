import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = file => readFileSync(new URL(`../static/scripts/${file}`, import.meta.url), "utf8");
const code = read("data_fetch.js").replace(/^import .*\n/gm, "").replace(/^export /gm, "");
const calendarDate = date => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,"0")}-${String(date.getDate()).padStart(2,"0")}`;
const polygon = { geometry: { type:"Polygon", coordinates:[[[4,52],[5,52],[5,53],[4,52]]] } };
const dates = [new Date(2025,9,13), new Date(2025,9,14)];
const instantiate = fetch => new Function("fetch", "calendarDate", code+";return {get_LoadProfiles,get_KPIs,get_EnvironmentKPIs};")(fetch, calendarDate);

function fixture() {
  const calls = [], revision = { infrastructure:"i1", analysis:"a1" };
  let fail = null;
  const api = instantiate(async (url, options) => {
    const body = options.body ? JSON.parse(options.body) : null;
    calls.push({url,body});
    if (url === fail) return {ok:false,status:503,json:async()=>({error:"temporary failure"})};
    let data;
    if (url.endsWith("analysis-version")) data = {...revision};
    else if (url.startsWith("/stations/within")) data = {ids:[3,1,3]};
    else if (url.startsWith("/features/transformers/within")) data = {ids:[25]};
    else if (url.endsWith("charging-points-by-transformers")) data = {charging_point_ids:[9]};
    else if (url.endsWith("aggregate_load")) data = {y:[1,2],up_flex:[0,1],down_flex:[-1,0],past_steps:1};
    else if (url === "/kpi/user") data = body.section === "basic"
      ? {source:{source:body.session_source},arrival_dist_wd:[1],summary:{session_count:1}}
      : {environment:{strategies:{avg:{energy_kwh:2}}},source:{cache_hits:2},section:"environment",co2_intensities_avg:[100]};
    else throw new Error("Unexpected URL "+url);
    return {ok:true,json:async()=>data};
  });
  return {api,calls,revision,setFailure:url=>{fail=url;},count:part=>calls.filter(call=>call.url.includes(part)).length};
}

test("load/flex reuse one response; KPI reuses area IDs without fetching transformers", async () => {
  const f = fixture();
  const first = await f.api.get_LoadProfiles([polygon],["Area"],"2025-10-14");
  const second = await f.api.get_LoadProfiles([polygon],["Renamed"],"2025-10-14");
  assert.equal(second[0].response, first[0].response);
  assert.equal(second[0].groupName, "Renamed");
  assert.deepEqual(first[0].chargerIds, [1,3]);
  await f.api.get_KPIs([polygon],["Area"],dates);
  assert.equal(f.count("aggregate_load"),1);
  assert.equal(f.count("/stations/within"),1);
  assert.equal(f.count("transformers"),0);
  assert.deepEqual(f.calls.filter(call=>call.url==="/kpi/user").map(call=>call.body.section),["basic"]);
});

test("profile cache isolates date, strategy, source, demand, seed and grid selection", async () => {
  const f = fixture(), load = (options={},date="2025-10-14") => f.api.get_LoadProfiles([polygon],["A"],date,options);
  await load();
  for (const options of [{strategy:"afap"},{sessionSource:"cpft"},{demandAssumption:"high"},{seed:7},{gridView:true}]) await load(options);
  await load({},"2025-10-13");
  assert.equal(f.count("aggregate_load"),7);
  assert.equal(f.count("/stations/within"),1);
  assert.equal(f.count("/features/transformers/within"),1);
  assert.equal(f.count("charging-points-by-transformers"),1);
  const grid = f.calls.find(call=>call.url.endsWith("aggregate_load") && call.body.selected_markers[0]===9);
  assert.ok(grid);
});

test("data revisions and polygon edits invalidate only the affected cache keys", async () => {
  const f = fixture(), load = p => f.api.get_LoadProfiles([p],["A"],"2025-10-14");
  await load(polygon);
  f.revision.analysis = "a2";
  await load(polygon);
  assert.equal(f.count("aggregate_load"),2);
  assert.equal(f.count("/stations/within"),1);
  f.revision.infrastructure = "i2";
  f.revision.analysis = "a3";
  await load(polygon);
  assert.equal(f.count("/stations/within"),2);
  assert.equal(f.count("aggregate_load"),3);
  const moved = structuredClone(polygon);
  moved.geometry.coordinates[0][0][0] = 4.1;
  await load(moved);
  assert.equal(f.count("/stations/within"),3);
});

test("identical concurrent requests share area lookup and profile calculation", async () => {
  const f = fixture();
  await Promise.all(Array.from({length:8},()=>f.api.get_LoadProfiles([polygon],["A"],"2025-10-14")));
  assert.equal(f.count("analysis-version"),1);
  assert.equal(f.count("/stations/within"),1);
  assert.equal(f.count("aggregate_load"),1);
});

test("failed spatial and profile requests are retried rather than cached", async () => {
  const f = fixture(), load = () => f.api.get_LoadProfiles([polygon],["A"],"2025-10-14");
  f.setFailure("/stations/within?ids_only=1");
  await assert.rejects(load(),/temporary failure/);
  f.setFailure("/stations/aggregate_load");
  await assert.rejects(load(),/temporary failure/);
  f.setFailure(null);
  await load();
  assert.equal(f.count("/stations/within"),2);
  assert.equal(f.count("aggregate_load"),2);
});

test("environment is lazy, cached separately and merged without losing basic statistics", async () => {
  const f = fixture(), groups = await f.api.get_KPIs([polygon],["A"],dates,{sessionSource:"spatial"});
  assert.equal(f.count("/kpi/user"),1);
  const complete = await f.api.get_EnvironmentKPIs(groups);
  await f.api.get_EnvironmentKPIs(groups);
  assert.equal(f.count("/kpi/user"),2);
  assert.deepEqual(complete[0].kpi.summary,{session_count:1});
  assert.deepEqual(complete[0].source,{source:"spatial"});
  assert.deepEqual(complete[0].kpi.environment.strategies.avg,{energy_kwh:2});
  assert.equal(groups[0].kpi.environment,undefined);
  f.revision.analysis = "a2";
  await assert.rejects(f.api.get_EnvironmentKPIs(groups),/inputs changed/);
});

test("late load results and errors cannot overwrite a newer selection", async () => {
  const script = read("script.js");
  const start = script.indexOf("function calendarSummary(");
  const body = script.slice(start, script.indexOf('document.getElementById("session-source").addEventListener(',start));
  const pending = [], rendered = [], errors = [], requests = [];
  const run = new Function("get_LoadProfiles","document","createGraph","showGraphMessage","calendarDate",`
    let profileRequestVersion=0,load_profile_data=[],charger_ids_list=[],transformer_ids_list=[];
    const active_tab="Load Profiles";
    const selected_polygons=[{}],selected_area_names=["New"];
    const settingsOf=()=>({strategy:"alap",demand:"high",date:new Date(2025,9,14)});
    const calendarNote=()=>"",createPolytopeGraph=()=>{};
    ${body}
    return calculateLoadProfiles;
  `)((...args)=>new Promise((resolve,reject)=>{requests.push(args);pending.push({resolve,reject});}),
    {getElementById:()=>({value:"simple"})},data=>rendered.push(data),(...args)=>errors.push(args),calendarDate);
  const old = run(), current = run();
  pending[1].resolve([{chargerIds:[2],transformerIds:[],groupName:"New",
    response:{y:[1,2],up_flex:[0,1],down_flex:[-1,0],past_steps:1}}]);
  await current;
  pending[0].reject(new Error("old failure"));
  await old;
  assert.equal(rendered.length,1);
  assert.equal(rendered[0][0].groupName,"New");
  assert.equal(rendered[0][0].strategy,"alap");
  assert.equal(rendered[0][0].targetDate,"2025-10-14");
  // every area is requested with its own date and strategy
  assert.deepEqual(requests[0][2],["2025-10-14"]);
  assert.deepEqual(requests[0][3].strategy,["alap"]);
  assert.deepEqual(requests[0][3].demandAssumption,["high"]);
  assert.equal(requests[0][3].gridView,undefined);
  assert.deepEqual(errors,[]);
});

test("each area is requested with its own date and strategy", async () => {
  const f = fixture();
  await f.api.get_LoadProfiles([polygon,polygon],["A","B"],["2025-10-14","2025-10-20"],{strategy:["afap","alap"]});
  const bodies = f.calls.filter(call=>call.url.endsWith("aggregate_load")).map(call=>call.body);
  assert.deepEqual(bodies.map(body=>[body.date,body.strategy]).sort(),[["2025-10-14","afap"],["2025-10-20","alap"]]);
  assert.equal(f.count("/stations/within"),1);
});

test("each area is requested with its own demand scenario", async () => {
  const f = fixture();
  await f.api.get_LoadProfiles([polygon,polygon],["A","B"],"2025-10-14",{demandAssumption:["low","high"]});
  const load = f.calls.filter(call=>call.url.endsWith("aggregate_load")).map(call=>call.body.demand_assumption);
  assert.deepEqual(load.sort(),["high","low"]);
  await f.api.get_KPIs([polygon,polygon],["A","B"],dates,{demandAssumption:["high","base"]});
  const kpi = f.calls.filter(call=>call.url==="/kpi/user").map(call=>call.body.demand_assumption);
  assert.deepEqual(kpi.sort(),["base","high"]);
  // a single value still applies to every area
  const g = fixture();
  await g.api.get_KPIs([polygon,polygon],["A","B"],dates,{demandAssumption:"low"});
  assert.deepEqual(g.calls.filter(call=>call.url==="/kpi/user").map(call=>call.body.demand_assumption),["low","low"]);
});

test("each area is requested with its own KPI date range", async () => {
  const f = fixture();
  await f.api.get_KPIs([polygon,polygon],["A","B"],[[new Date(2025,9,1),new Date(2025,9,3)],dates]);
  const bodies = f.calls.filter(call=>call.url==="/kpi/user").map(call=>[call.body.start_date,call.body.end_date]);
  assert.deepEqual(bodies.sort(),[["2025-10-01","2025-10-03"],["2025-10-13","2025-10-14"]]);
  await assert.rejects(f.api.get_KPIs([polygon,polygon],["A","B"],[dates]),/both dates/);
  await assert.rejects(f.api.get_KPIs([polygon,polygon],["A","B"],[dates,[new Date()]]),/both dates/);
});

test("late environmental results cannot replace a newer KPI request", async () => {
  const script = read("script.js"), start = script.indexOf("async function ensureEnvironmentKpis(");
  const body = script.slice(start,script.indexOf("async function renderActiveKpi(",start));
  let finish;
  const old = [{kpi:{},groupName:"old"}], current = [{kpi:{},groupName:"new"}];
  const harness = new Function("get_EnvironmentKPIs",`
    let kpi_data_list;
    ${body}
    return {load:ensureEnvironmentKpis,set:value=>{kpi_data_list=value;},get:()=>kpi_data_list};
  `)(()=>new Promise(resolve=>{finish=resolve;}));
  harness.set(old);
  const pending = harness.load(old);
  harness.set(current);
  finish([{kpi:{environment:{}},groupName:"old"}]);
  await pending;
  assert.equal(harness.get(),current);
});

test("Excel download awaits the environmental section even when its tab was unopened", async () => {
  const script = read("script.js"), start = script.indexOf('document.getElementById("download-btn").addEventListener');
  const body = script.slice(start,script.indexOf("$(function",start));
  let handler, finish;
  const saved = [], groups = [{kpi:{}}], button = {disabled:false};
  new Function("document","ensureEnvironmentKpis","generateAndDownloadExcel",`
    const charger_ids_list=[[1]],load_profile_data=[],kpi_data_list=${JSON.stringify(groups)};
    const animateSelectMessage=()=>{};
    ${body}
  `)({getElementById:()=>({addEventListener:(_event,fn)=>{handler=fn;}})},
    ()=>new Promise(resolve=>{finish=resolve;}),(...args)=>saved.push(args));
  const pending = handler.call(button);
  assert.equal(saved.length,0);
  assert.equal(button.disabled,true);
  const complete = [{kpi:{environment:{strategies:{}}}}];
  finish(complete);
  await pending;
  assert.equal(saved[0][2],complete);
  assert.equal(button.disabled,false);
});
