import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import {loadPlotter} from "./plotter_harness.mjs";

const read = file => readFileSync(new URL(`../static/scripts/${file}`,import.meta.url),"utf8").replace(/^export /gm,"");
const render = new Function(read("environment_summary.js")+";return renderEnvironmentSummary;")();

function sample(status="historical_reference") {
  const environment = {uses_historical_reference:true,covered_steps:144,
    reference_source_start:"2025-10-22T09:00:00+00:00",reference_source_end:"2025-10-23T08:00:00+00:00",
    note:"Estimated scenario footprint, not demonstrated avoided emissions",strategies:{}};
  for (const [key,label] of [["afap","As fast as possible"],["alap","As late as possible"],["avg","Average power"],["mincarbon","Minimum carbon"]]) {
    environment.strategies[key] = {label,status,available:true,energy_kwh:10,emissions_kg:2,
      average_intensity_g_per_kwh:200,renewable_share_pct:0,carbon_energy_coverage_pct:100,
      renewable_energy_coverage_pct:100,matching_date_carbon_coverage_pct:0,footprint_difference_vs_afap_pct:0};
  }
  return {groupName:"Area",kpi:{environment}};
}

test("summary distinguishes historical coverage from matching-date coverage and preserves zero shares", () => {
  const container = {};
  render([sample()],container);
  assert.equal(container.hidden,false);
  for (const text of ["Historical reference","2025-10-22","0% on matching dates","kgCO₂e","Minimum carbon","not demonstrated avoided emissions"]) {
    assert.ok(container.innerHTML.includes(text),text);
  }
  assert.match(container.innerHTML,/0[.,]0%/);
  assert.ok(!container.innerHTML.includes("—%"));
});

test("partial and unavailable schedules are labelled and area names are escaped", () => {
  const group = sample("partial_reference");
  group.groupName = '<img src=x onerror="bad()">';
  group.kpi.environment.strategies.mincarbon = {label:"Minimum carbon",status:"unavailable",available:false,reason:"Missing carbon <data>"};
  for (const value of Object.values(group.kpi.environment.strategies)) value.footprint_difference_vs_afap_pct=null;
  const container = {};
  render([group],container);
  assert.ok(container.innerHTML.includes("Partial historical reference"));
  assert.ok(container.innerHTML.includes("Comparisons against AFAP are withheld"));
  assert.ok(container.innerHTML.includes("Missing carbon &lt;data&gt;"));
  assert.ok(!container.innerHTML.includes("<img"));
  assert.ok(container.innerHTML.includes("&lt;img"));
});

test("minimum-carbon chart adds aligned traces alongside all three baselines", () => {
  const {api,plots} = loadPlotter();
  const kpi = {};
  for (const label of ["uncontrolled","delayed","avg","mincarbon"]) {
    kpi[`co2_intensities_${label}`] = Array(24).fill(100);
    kpi[`renewable_energy_shared_${label}`] = 50;
  }
  api.createEnvironmentKPIGraph([{groupName:"Area",kpi}]);
  const captured = plots[0].data;
  assert.equal(captured.length,8);
  assert.equal(captured.filter(trace=>trace.name==="Minimum Carbon").length,2);
  for (const trace of captured) assert.equal(trace.x.length,trace.y.length);
});

test("environmental export contains energy coverage, status and the AFAP difference", () => {
  const toSheet = new Function("XLSX",read("utils.js")+";return generateKPIsSheet;")({utils:{aoa_to_sheet:rows=>rows}});
  const group = sample();
  group.kpi.environment.strategies.mincarbon.footprint_difference_vs_afap_kg=-.5;
  for (const field of ["arrival","consumption","daily_consumption","departure","duration"]) {
    for (const kind of ["wd","we"]) group.kpi[`${field}_dist_${kind}`]=[];
  }
  for (const kind of ["wd","we"]) group.kpi[`hour_of_arrival_consumption_${kind}`]=[];
  for (const field of ["occupation_ratio_dist","weekday_availability","weekend_availability"]) group.kpi[field]=[];
  for (let i=0;i<7;i++) group.kpi[`sessions_per_day_${i}`]=[];
  const rows = toSheet(group);
  assert.ok(rows.some(row=>row[0]==="Historical grid reference" && row[1]===true));
  assert.ok(rows.some(row=>row.includes("Carbon energy coverage (%)")));
  const minimum = rows.find(row=>row[0]==="Minimum carbon");
  assert.equal(minimum.at(-1),-.5);
  assert.equal(minimum.at(-2),"historical_reference");
});
