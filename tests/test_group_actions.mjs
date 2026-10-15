import assert from "node:assert/strict";
import test from "node:test";

import { createAnalysis } from "../static/scripts/analysis.js";
import { createAreaSettings } from "../static/scripts/area_settings.js";
import { createAreas } from "../static/scripts/areas.js";
import { createState } from "../static/scripts/app_state.js";
import * as helpers from "../static/scripts/group_actions.js";

test("moved, removed and copied return new arrays and leave the input alone", () => {
  const items = ["a", "b", "c"];
  assert.deepEqual(helpers.moved(items, 0, 2), ["b", "c", "a"]);
  assert.deepEqual(helpers.moved(items, 2, 1), ["a", "c", "b"]);
  assert.deepEqual(helpers.moved(items, 0, 3), items);
  assert.deepEqual(helpers.removed(items, 1), ["a", "c"]);
  assert.deepEqual(helpers.copied(items, 1, item => item + "'"), ["a", "b", "b'", "c"]);
  assert.deepEqual(items, ["a", "b", "c"]);
});

test("copy names stay unique and do not nest", () => {
  assert.equal(helpers.copyName("Area 1", ["Area 1"]), "Area 1 (copy)");
  assert.equal(helpers.copyName("Area 1", ["Area 1", "Area 1 (copy)"]), "Area 1 (copy 2)");
  assert.equal(helpers.copyName("Area 1 (copy)", ["Area 1", "Area 1 (copy)"]), "Area 1 (copy 2)");
  assert.equal(helpers.copyName("Area 1 (copy 2)", ["Area 1 (copy 2)"]), "Area 1 (copy)");
});

test("a copy takes a colour no area is wearing", () => {
  assert.equal(helpers.freeColor(["#a", "#b", "#c"], ["#a", "#c"]), "#b");
  assert.equal(helpers.freeColor(["#a", "#b"], ["#a", "#b"]), "#a");
});

test("new names are tidied, filled in, short and not taken", () => {
  assert.deepEqual(helpers.validName("  North   Docks ", ["Area 1"]), { name: "North Docks" });
  assert.match(helpers.validName("   ", []).error, /name/);
  assert.match(helpers.validName("x".repeat(helpers.MAX_NAME_LENGTH + 1), []).error, /at most/);
  assert.match(helpers.validName("area 1", ["Area 1"]).error, /already/);
  assert.equal(helpers.escapeHtml(`<img src=x onerror="a&b">`), "&lt;img src=x onerror=&quot;a&amp;b&quot;&gt;");
});

// The real card handlers (areas.js) and result renderer (analysis.js) over a
// Leaflet stand-in whose feature group visits layers in creation order, as
// Leaflet's does
function page({ tab = "Load Profiles", names = ["Area 1", "Area 2", "Area 3"], results = "load" } = {}) {
  const calls = [], messages = [], busy = [], focused = [], cardMessages = [], fetches = [], kpiFetches = [];
  let stamp = 0;
  const L = {
    polygon: (latLngs, options) => ({ _id: ++stamp, latLngs, options: { ...options },
      getLatLngs() { return this.latLngs; }, getBounds: () => ({ getCenter: () => ({ lat: 0, lng: 0 }) }) }),
    marker: (position, options) => ({ _id: ++stamp, position, options, getLatLng() { return this.position; } }),
    divIcon: options => options,
    latLng: (lat, lng) => ({ lat, lng }),
  };
  const drawnItems = {
    layers: {},
    eachLayer(visit) { Object.keys(this.layers).sort((a, b) => a - b).forEach(key => visit(this.layers[key])); },
    addLayer(layer) { this.layers[layer._id] = layer; },
    clearLayers() { this.layers = {}; },
  };
  const colors = ["#4CAF50", "#8A0606", "#3357FF"];
  names.forEach((name, index) => {
    const area = L.polygon([[{ lat: 52 + index, lng: 4 }, { lat: 52.2 + index, lng: 4 }, { lat: 52.2 + index, lng: 4.2 }]],
      { color: colors[index], weight: 5, fillOpacity: 0.5 });
    area.feature = { properties: { name, type: "area" } };
    drawnItems.addLayer(area);
    const label = L.marker({ lat: 52.1 + index, lng: 4.1 }, {});
    label.feature = { properties: { name, type: "marker" } };
    drawnItems.addLayer(label);
  });
  const group = (name, index) => ({ groupName: name, number_of_chargers: index + 1, kpi: {}, strategy: "afap",
    targetDate: "2026-10-15" });
  const state = createState();
  state.active_tab = tab;
  state.charger_ids_list = names.map((_, index) => [index + 1]);
  state.transformer_ids_list = names.map(() => []);
  state.load_profile_data = results === "load" ? names.map(group) : [];
  state.kpi_data_list = results === "kpi" ? names.map(group) : [];

  const api = {
    get_LoadProfiles: (_polygons, names, date, options) =>
      new Promise((resolve, reject) => fetches.push({ names, date, options, resolve, reject })),
    get_KPIs: (_polygons, names, ranges, options) =>
      new Promise((resolve, reject) => kpiFetches.push({ names, ranges, options, resolve, reject })),
  };
  const settings = createAreaSettings();
  const groupNames = data => data.map(item => item.groupName);
  const analysis = createAnalysis({
    state, settingsOf: settings.settingsOf, api,
    view: {
      sessionSource: () => "simple", setNote() {}, clearGraph() {},
      showGraphMessage: title => calls.push(["message", title]),
      createGraph: data => calls.push(["load", groupNames(data)]),
      createPolytopeGraph: data => calls.push(["flex", groupNames(data)]),
      kpiRenderers: { user_kpi: data => calls.push(["kpi", groupNames(data)]) },
      environmentSummary: () => null, renderEnvironmentSummary() {},
    },
  });
  const areas = createAreas({
    state, L, drawnItems, colors, settings, api, renderGroupResults: analysis.renderGroupResults,
    view: {
      sessionSource: () => "simple",
      setCardBusy: (index, value) => busy.push([index, value]),
      showCardMessage: (index, text) => cardMessages.push([index, text]),
      focusCardField: (index, field) => focused.push([index, field]),
      animateSelectMessage: text => messages.push(text),
      syncDrawPrompt() {},
      flatpickr: () => ({ destroy() {} }),
      document: {},
    },
  });
  areas.syncSelectionFromAreas();
  return {
    ...areas, settingsOf: settings.settingsOf, areaSettings: settings.areaSettings, state: () => state,
    calls, messages, busy, focused, cardMessages, fetches, kpiFetches, drawnItems,
  };
}

// An area's answer: one past step whose value tells the answers apart
const answer = (name, marker, chargers = [marker]) => [{ groupName: name, chargerIds: chargers, transformerIds: [],
  response: { y: [marker], up_flex: [0], down_flex: [0], past_steps: 1 } }];

const layerNames = drawnItems => {
  const names = [];
  drawnItems.eachLayer(layer => names.push(`${layer.feature.properties.type}:${layer.feature.properties.name}`));
  return names;
};

test("moving an area reorders the map layers, the selection and every result array together", () => {
  const app = page();
  assert.equal(app.moveGroup(0, 1), 1);
  const state = app.state();
  assert.deepEqual(state.selected_area_names, ["Area 2", "Area 1", "Area 3"]);
  assert.deepEqual(layerNames(app.drawnItems).filter(name => name.startsWith("area")), ["area:Area 2", "area:Area 1", "area:Area 3"]);
  // Each polygon still belongs to its name: the first vertex carries the area's index
  assert.deepEqual(state.selected_polygons.map(polygon => polygon.geometry.coordinates[0][0][1]), [53, 52, 54]);
  assert.deepEqual(state.load_profile_data.map(item => item.groupName), ["Area 2", "Area 1", "Area 3"]);
  assert.deepEqual(state.charger_ids_list, [[2], [1], [3]]);
  assert.deepEqual(app.calls.at(-1), ["load", ["Area 2", "Area 1", "Area 3"]]);
  assert.match(app.messages.at(-1), /3 of 3 areas selected/);
});

test("moving past either end changes nothing and does not redraw", () => {
  const app = page();
  assert.equal(app.moveGroup(0, -1), null);
  assert.equal(app.moveGroup(2, 1), null);
  assert.equal(app.calls.length, 0);
  assert.deepEqual(app.state().selected_area_names, ["Area 1", "Area 2", "Area 3"]);
});

test("copying inserts a dashed, differently coloured copy right below its area", () => {
  const app = page({ names: ["Area 1", "Area 2"] });
  assert.equal(app.duplicateGroup(0), 1);
  const state = app.state();
  assert.deepEqual(state.selected_area_names, ["Area 1", "Area 1 (copy)", "Area 2"]);
  assert.deepEqual(state.load_profile_data.map(item => item.groupName), ["Area 1", "Area 1 (copy)", "Area 2"]);
  assert.deepEqual(state.charger_ids_list, [[1], [1], [2]]);
  assert.notEqual(state.charger_ids_list[0], state.charger_ids_list[1]);
  assert.deepEqual(state.selected_polygons[0].geometry, state.selected_polygons[1].geometry);
  const areas = [];
  app.drawnItems.eachLayer(layer => { if (layer.feature.properties.type === "area") areas.push(layer); });
  assert.equal(areas[1].options.dashArray, "10 8");
  assert.equal(areas[0].options.dashArray, undefined);
  assert.notEqual(areas[1].options.color, areas[0].options.color);
  assert.notEqual(areas[1].options.color, areas[2].options.color);
});

test("a copy starts from its area's settings and changes them independently", () => {
  const app = page({ names: ["Area 1", "Area 2"] });
  const original = app.settingsOf("Area 1");
  original.strategy = "alap";
  original.demand = "high";
  original.date = new Date(2026, 0, 2);
  app.duplicateGroup(0);
  const copy = app.settingsOf("Area 1 (copy)");
  assert.equal(copy.strategy, "alap");
  assert.equal(copy.demand, "high");
  assert.deepEqual(copy.range, original.range);
  assert.notEqual(copy.range, original.range);
  copy.strategy = "avg";
  assert.equal(original.strategy, "alap");
});

test("copying is refused at the area limit and leaves the selection untouched", () => {
  const app = page();
  assert.equal(app.duplicateGroup(1), null);
  assert.deepEqual(app.state().selected_area_names, ["Area 1", "Area 2", "Area 3"]);
  assert.equal(app.calls.length, 0);
  assert.match(app.messages.at(-1), /up to 3 areas/);
});

test("removing an area drops its layers, results and settings; focus lands on a neighbour", () => {
  const app = page();
  app.settingsOf("Area 2");
  assert.equal(app.removeGroup(1), 1);
  const state = app.state();
  assert.deepEqual(state.selected_area_names, ["Area 1", "Area 3"]);
  assert.deepEqual(layerNames(app.drawnItems), ["area:Area 1", "marker:Area 1", "area:Area 3", "marker:Area 3"]);
  assert.deepEqual(state.charger_ids_list, [[1], [3]]);
  assert.equal(app.areaSettings.has("Area 2"), false);
  assert.match(app.messages.at(-1), /2 of 3 selected/);
  assert.equal(app.removeGroup(1), 0);
});

test("removing the last area clears the selection and explains the empty panel", () => {
  const app = page({ names: ["Area 1"] });
  assert.equal(app.removeGroup(0), null);
  assert.deepEqual(app.state().selected_polygons, []);
  assert.deepEqual(app.calls.at(-1), ["message", "No areas selected"]);
  assert.equal(app.messages.at(-1), "Draw an area on the map to start");
});

test("the Flexibility tab redraws through the polytope renderer", () => {
  const app = page({ tab: "Flexibility" });
  app.moveGroup(0, 1);
  assert.deepEqual(app.calls.at(-1), ["flex", ["Area 2", "Area 1", "Area 3"]]);
});

test("the KPI tab edits its own results and redraws through the KPI renderer", () => {
  const app = page({ tab: "KPIs", results: "kpi" });
  app.moveGroup(2, -1);
  const state = app.state();
  assert.deepEqual(state.kpi_data_list.map(item => item.groupName), ["Area 1", "Area 3", "Area 2"]);
  assert.deepEqual(state.load_profile_data, []);
  assert.deepEqual(app.calls.at(-1), ["kpi", ["Area 1", "Area 3", "Area 2"]]);
});

test("results from another selection are left alone rather than misaligned", () => {
  const app = page();
  app.state().load_profile_data.pop();
  app.moveGroup(0, 1);
  assert.deepEqual(app.state().load_profile_data.map(item => item.groupName), ["Area 1", "Area 2"]);
});

test("renaming updates the map label, selection, results and settings under the new name", () => {
  const app = page();
  app.settingsOf("Area 2").strategy = "alap";
  assert.equal(app.renameGroup(1, "  North   Docks "), 1);
  const state = app.state();
  assert.deepEqual(state.selected_area_names, ["Area 1", "North Docks", "Area 3"]);
  assert.deepEqual(state.load_profile_data.map(item => item.groupName), ["Area 1", "North Docks", "Area 3"]);
  assert.deepEqual(state.charger_ids_list, [[1], [2], [3]]);
  assert.deepEqual(layerNames(app.drawnItems).filter(name => name.startsWith("marker")),
    ["marker:Area 1", "marker:North Docks", "marker:Area 3"]);
  assert.equal(app.areaSettings.has("Area 2"), false);
  assert.equal(app.settingsOf("North Docks").strategy, "alap");
  assert.deepEqual(app.calls.at(-1), ["load", ["Area 1", "North Docks", "Area 3"]]);
});

test("a rename that cannot be used explains why and changes nothing", () => {
  const app = page();
  assert.match(app.renameGroup(1, "   "), /name/);
  assert.match(app.renameGroup(1, "AREA 3"), /already/);
  assert.equal(app.renameGroup(1, "Area 2"), null);
  assert.deepEqual(app.state().selected_area_names, ["Area 1", "Area 2", "Area 3"]);
  assert.equal(app.calls.length, 0);
});

test("map labels never carry markup from a typed name", () => {
  const app = page();
  app.renameGroup(0, "<img src=x onerror=alert(1)>");
  const labels = [];
  app.drawnItems.eachLayer(layer => { if (layer.feature.properties.type === "marker") labels.push(layer.options.icon.html); });
  assert.equal(labels[0], "<span>&lt;img src=x onerror=alert(1)&gt;</span>");
});

test("changing a card's setting requests that area alone and keeps the rest", async () => {
  const app = page();
  app.settingsOf("Area 2").strategy = "alap";
  app.settingsOf("Area 2").date = new Date(2026, 9, 20);
  const done = app.refreshArea("Area 2", "strategy");
  assert.equal(app.fetches.length, 1);
  assert.deepEqual(app.fetches[0].names, ["Area 2"]);
  assert.equal(app.fetches[0].date, "2026-10-20");
  assert.equal(app.fetches[0].options.strategy, "alap");
  assert.deepEqual(app.busy.at(-1), [1, true]);
  app.fetches[0].resolve(answer("Area 2", 7));
  await done;
  const state = app.state();
  assert.deepEqual(state.load_profile_data.map(item => item.strategy), ["afap", "alap", "afap"]);
  assert.equal(state.load_profile_data[1].targetDate, "2026-10-20");
  assert.deepEqual(state.charger_ids_list, [[1], [7], [3]]);
  assert.deepEqual(app.focused.at(-1), [1, "strategy"]);
  assert.deepEqual(app.calls.at(-1), ["load", ["Area 1", "Area 2", "Area 3"]]);
});

test("every new area starts on the default strategy, demand scenario and a one-week KPI range", () => {
  const app = page({ names: ["Area 1"] });
  const settings = app.settingsOf("Area 1");
  assert.equal(settings.strategy, "afap");
  assert.equal(settings.demand, "base");
  assert.equal(Math.round((settings.range[1] - settings.range[0]) / 86400000), 6);
});

test("a card's demand scenario is requested for that area only", async () => {
  const app = page();
  app.settingsOf("Area 3").demand = "high";
  const done = app.refreshArea("Area 3", "demand");
  assert.deepEqual(app.fetches[0].names, ["Area 3"]);
  assert.equal(app.fetches[0].options.demandAssumption, "high");
  assert.equal(app.fetches[0].options.gridView, undefined);
  app.fetches[0].resolve(answer("Area 3", 3));
  await done;
  assert.deepEqual(app.focused.at(-1), [2, "demand"]);
});

test("a late answer for an older setting does not overwrite a newer one", async () => {
  const app = page();
  const first = app.refreshArea("Area 1", "date");
  const second = app.refreshArea("Area 1", "date");
  app.fetches[1].resolve(answer("Area 1", 22));
  await second;
  app.fetches[0].resolve(answer("Area 1", 11));
  await first;
  assert.equal(app.state().load_profile_data[0].pastData[0], 22);
  assert.equal(app.state().charger_ids_list[0][0], 22);
});

test("an area that moved while its request ran gets the answer where it is now", async () => {
  const app = page();
  const done = app.refreshArea("Area 1", "date");
  app.moveGroup(0, 2);
  app.fetches[0].resolve(answer("Area 1", 5));
  await done;
  const state = app.state();
  assert.deepEqual(state.selected_area_names, ["Area 2", "Area 3", "Area 1"]);
  assert.equal(state.load_profile_data[2].groupName, "Area 1");
  assert.equal(state.load_profile_data[2].pastData[0], 5);
  assert.deepEqual(app.focused.at(-1), [2, "date"]);
});

test("a failed area request is reported on that card only", async () => {
  const app = page();
  const done = app.refreshArea("Area 3", "strategy");
  app.fetches[0].reject(new Error("model unavailable"));
  await done;
  assert.deepEqual(app.cardMessages, [[2, "model unavailable"]]);
  assert.equal(app.state().load_profile_data.length, 3);
});

test("a request still running when its area is renamed is asked again under the new name", () => {
  const app = page();
  app.refreshArea("Area 1", "date");
  app.renameGroup(0, "Harbour");
  assert.equal(app.fetches.length, 2);
  assert.deepEqual(app.fetches[1].names, ["Harbour"]);
});

test("the KPI tab refreshes one area with that area's date range", async () => {
  const app = page({ tab: "KPIs", results: "kpi" });
  const range = [new Date(2026, 9, 1), new Date(2026, 9, 5)];
  app.settingsOf("Area 2").range = range;
  const done = app.refreshArea("Area 2", "range");
  assert.equal(app.kpiFetches.length, 1);
  assert.deepEqual(app.kpiFetches[0].names, ["Area 2"]);
  assert.deepEqual(app.kpiFetches[0].ranges, [range]);
  app.kpiFetches[0].resolve([{ groupName: "Area 2", chargerIds: [8], transformerIds: [], kpi: { fresh: true } }]);
  await done;
  const state = app.state();
  assert.equal(state.kpi_data_list[1].kpi.fresh, true);
  assert.equal(state.kpi_data_list[0].kpi.fresh, undefined);
  assert.deepEqual(app.calls.at(-1), ["kpi", ["Area 1", "Area 2", "Area 3"]]);
});
