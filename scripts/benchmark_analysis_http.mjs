// Called by benchmark_analysis.py against its disposable local Flask server.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { performance } from "node:perf_hooks";

const spec = JSON.parse(readFileSync(process.argv[2], "utf8"));
const read = file => readFileSync(file, "utf8");
const datesCode = read(join(spec.root,"static/scripts/date_selection.js")).replace(/^export /gm,"");
const {calendarDate} = new Function(datesCode+";return {calendarDate};")();
const fromDate = value => { const [y,m,d] = value.split("-").map(Number); return new Date(y,m-1,d); };
const dates = [fromDate(spec.start_date),fromDate(spec.date)];
const quiet = {log(){},error(){},warn(){}};

function fetcher(variant, counts) {
  return async (url, options) => {
    counts.requests++;
    counts.paths.push(url);
    const response = await fetch(spec.base_url+"/"+variant+url, options);
    const text = await response.text();
    counts.bytes += Buffer.byteLength(text);
    return {ok:response.ok,status:response.status,json:async()=>JSON.parse(text)};
  };
}

function functions(variant, fetch) {
  const source = read(variant === "before" ? join(spec.work,"before-data_fetch.js")
    : join(spec.root,"static/scripts/data_fetch.js")).replace(/^import .*\r?\n/gm,"").replace(/^export /gm,"");
  return new Function("fetch","calendarDate",source+`;return {get_KPIs,
    get_LoadProfiles: typeof get_LoadProfiles==="undefined" ? null : get_LoadProfiles,
    get_EnvironmentKPIs: typeof get_EnvironmentKPIs==="undefined" ? null : get_EnvironmentKPIs};`)(fetch,calendarDate);
}

function loadRunner(variant, fetch, api) {
  const script = read(variant === "before" ? join(spec.work,"before-script.js") : join(spec.root,"static/scripts/script.js"));
  const start = script.includes("async function calculateLoadProfiles(")
    ? script.indexOf("async function calculateLoadProfiles(") : script.indexOf("function calculateLoadProfiles(");
  assert.ok(start>=0,"Load-profile function must be present in both revisions");
  const end = script.indexOf("// add event listener to the strategy-dropdown",start);
  assert.ok(end>start,"Could not isolate the real load-profile function");
  return new Function("fetch","get_LoadProfiles","console","polygon","targetDate",`
    let profileRequestVersion=0,load_profile_data=[],charger_ids_list=[],transformer_ids_list=[],connected_charger_ids_list=[];
    let active_tab="Load Profiles",currentStrategy="avg",done,failed;
    const dateInput={value:targetDate},toggle={checked:false};
    const selected_polygons=[polygon],selected_area_names=["Benchmark"];
    const document={getElementById:id=>({value:id==="session-source"?"simple":id==="demand-assumption"?"base":currentStrategy})};
    const createGraph=rows=>done(rows),createFlexGraph=createGraph;
    const showGraphMessage=(title,message)=>failed(new Error(title+": "+message));
    const animateSelectMessage=message=>failed(new Error(message));
    ${script.slice(start,end)}
    return (tab,strategy="avg")=>new Promise((resolve,reject)=>{
      const timeout=setTimeout(()=>reject(new Error("Load-profile benchmark timed out")),120000);
      done=rows=>{clearTimeout(timeout);resolve(rows);};
      failed=error=>{clearTimeout(timeout);reject(error);};
      active_tab=tab;currentStrategy=strategy;
      Promise.resolve(calculateLoadProfiles()).catch(failed);
    });
  `)(fetch,api.get_LoadProfiles,quiet,structuredClone(spec.polygon),spec.date);
}

async function workflow(variant) {
  const counts={requests:0,bytes:0,paths:[]}, fetch=fetcher(variant,counts);
  const api=functions(variant,fetch), load=loadRunner(variant,fetch,api);
  const records=[];
  async function measure(name, action) {
    const previous={requests:counts.requests,bytes:counts.bytes,paths:counts.paths.length};
    const start=performance.now(), result=await action(), elapsed=performance.now()-start;
    records.push({name,ms:elapsed,requests:counts.requests-previous.requests,bytes:counts.bytes-previous.bytes,
                  paths:counts.paths.slice(previous.paths)});
    return result;
  }
  const first=await measure("HTTP first load (warm server cache)",()=>load("Load Profiles"));
  const flex=await measure("HTTP switch Load to Flexibility",()=>load("Flexibility"));
  const strategy=await measure("HTTP change charging strategy",()=>load("Load Profiles","alap"));
  const basic=await measure("HTTP first basic KPIs",()=>api.get_KPIs([structuredClone(spec.polygon)],["Benchmark"],dates,{sessionSource:"simple",demandAssumption:"base"}));
  const complete=await measure("HTTP open Environment after basic KPIs",()=>variant==="before" ? basic : api.get_EnvironmentKPIs(basic));
  const kpiRecords=records.slice(-2);
  records.push({name:"HTTP full KPI workflow (basic + Environment)",
    ms:kpiRecords.reduce((sum,row)=>sum+row.ms,0),requests:kpiRecords.reduce((sum,row)=>sum+row.requests,0),
    bytes:kpiRecords.reduce((sum,row)=>sum+row.bytes,0),paths:kpiRecords.flatMap(row=>row.paths)});
  assert.equal(first[0].number_of_chargers,spec.points);
  if (variant==="after") {
    const switched=records.find(row=>row.name==="HTTP switch Load to Flexibility");
    assert.deepEqual(switched.paths,["/stations/analysis-version"]);
    assert.ok(!records.find(row=>row.name==="HTTP first basic KPIs").paths.some(path=>path.includes("within")));
    assert.equal(basic[0].kpi.environment,undefined);
  }
  return {records,first,flex,strategy,basic,complete};
}

function equalNumbers(left,right,path="") {
  if (typeof left==="number" && typeof right==="number") {
    assert.ok(Math.abs(left-right)<=1e-8+1e-10*Math.abs(left),path);
  } else if (Array.isArray(left)) {
    assert.equal(left.length,right.length,path);
    left.forEach((value,index)=>equalNumbers(value,right[index],path+"["+index+"]"));
  } else if (left && typeof left==="object") {
    for (const key of Object.keys(left)) equalNumbers(left[key],right[key],path+"."+key);
  } else assert.equal(left,right,path);
}

const samples=new Map(), actions=new Map();
for (let iteration=0;iteration<=spec.repeats;iteration++) {
  const runs={};
  for (const variant of iteration%2===0?["before","after"]:["after","before"]) runs[variant]=await workflow(variant);
  for (const name of ["first","flex","strategy"]) {
    for (const field of ["pastData","futureData","past_up_flex","future_up_flex","past_down_flex","future_down_flex"])
      equalNumbers(runs.before[name][0][field],runs.after[name][0][field],name+"."+field);
  }
  for (const [key,value] of Object.entries(runs.after.basic[0].kpi)) {
    if (!["source","section"].includes(key)) equalNumbers(value,runs.before.basic[0].kpi[key],key);
  }
  equalNumbers(runs.before.complete[0].kpi.environment,runs.after.complete[0].kpi.environment,"environment");
  if (!iteration) continue;
  for (let index=0;index<runs.before.records.length;index++) {
    const old=runs.before.records[index], current=runs.after.records[index];
    if (!samples.has(old.name)) samples.set(old.name,{before:[],after:[]});
    samples.get(old.name).before.push(old.ms);
    samples.get(old.name).after.push(current.ms);
    actions.set(old.name,{name:old.name,before_requests:old.requests,after_requests:current.requests,
      before_bytes:old.bytes,after_bytes:current.bytes,before_paths:old.paths,after_paths:current.paths});
  }
}
const median=values=>{const sorted=[...values].sort((a,b)=>a-b);return (sorted[Math.floor((sorted.length-1)/2)]+sorted[Math.floor(sorted.length/2)])/2;};
const summary=values=>({median_ms:median(values),min_ms:Math.min(...values),max_ms:Math.max(...values),samples_ms:values});
const results=[...samples].map(([name,times])=>{
  const before=summary(times.before),after=summary(times.after);
  // Before already paid for Environment when opening basic KPIs. A ratio against
  // its near-zero tab-switch overhead is meaningless; keep the absolute times.
  const deferred = name==="HTTP open Environment after basic KPIs";
  return {name,before,after,speedup:deferred?null:before.median_ms/after.median_ms,
    reduction_pct:deferred?null:100*(1-after.median_ms/before.median_ms)};
});
process.stdout.write(JSON.stringify({results,actions:[...actions.values()]}));
