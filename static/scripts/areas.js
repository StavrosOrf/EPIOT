// The analysis cards and the edits made from them.
//
// Each area is analysed under its own charging strategy and target date (load
// profiles, flexibility) or date range (KPIs); the cards edit those settings and
// refresh only the area that changed. The cards also move, copy, rename and
// remove areas. The drawn areas are the source of truth for the selection, so
// every edit rebuilds them in the new order and edits the result arrays to
// match, without a new request.
import { calendarDate, pickerOptions } from "./date_selection.js";
import { calendarNote } from "./calendar_note.js";
import { profileFromGroup } from "./analysis.js";
import { MAX_AREAS, moved, removed, copied, copyName, escapeHtml, freeColor, validName } from "./group_actions.js";
import { DEMANDS, STRATEGIES } from "./utils.js";

// No live data: any calendar date is a valid scenario context
const STARTING_DATE = null;

/**
 * @param {object} deps
 * @param {object} deps.state shared analysis state (see app_state.js)
 * @param {object} deps.L Leaflet
 * @param {object} deps.drawnItems the feature group holding every area polygon and its label
 * @param {string[]} deps.colors the area colour palette
 * @param {object} deps.settings {areaSettings: Map, settingsOf(name)}
 * @param {object} deps.api get_LoadProfiles and get_KPIs
 * @param {() => void} deps.renderGroupResults redraws the active tab from the result arrays
 * @param {object} deps.view sessionSource(), ensembleSize(), setCardBusy(index, busy), showCardMessage(index, text),
 *   focusCardField(index, field), animateSelectMessage(text), syncDrawPrompt(),
 *   flatpickr(element, options), document
 */
export function createAreas({ state, L, drawnItems, colors, settings, api, renderGroupResults, view }) {
  const { areaSettings, settingsOf } = settings;
  const { get_LoadProfiles, get_KPIs } = api;
  const doc = view.document;

  let cardPickers = [];

  // The cards are rebuilt on every redraw; flatpickr calendars live on <body>
  function destroyCardPickers() {
    cardPickers.forEach(picker => picker.destroy());
    cardPickers = [];
  }

  function settingField(icon, control) {
    const wrapper = doc.createElement("div");
    wrapper.className = "group-field";
    const glyph = doc.createElement("i");
    glyph.className = `fa ${icon}`;
    glyph.setAttribute("aria-hidden", "true");
    wrapper.append(glyph, control);
    return wrapper;
  }

  // A labelled-by-icon select for one of the card's settings
  function optionField(icon, field, title, options, current, onChange) {
    const select = doc.createElement("select");
    select.className = "group-field__control";
    select.dataset.field = field;
    select.title = title;
    select.setAttribute("aria-label", title);
    options.forEach(([value, label]) => {
      const option = doc.createElement("option");
      option.value = value;
      option.textContent = label;
      select.append(option);
    });
    select.value = current;
    select.addEventListener("change", () => onChange(select.value));
    return settingField(icon, select);
  }

  // Fill a card's settings slot: strategy and target date (or the KPI date range)
  // and the demand scenario
  function decorateCard(slot, group) {
    const name = group.groupName;
    const areaSetting = settingsOf(name);
    const date = doc.createElement("input");
    date.type = "text";
    date.readOnly = true;
    date.className = "group-field__control";
    const demand = optionField("fa-bar-chart", "demand", `Demand scenario for ${name}`, DEMANDS, areaSetting.demand,
      value => {
        areaSetting.demand = value;
        refreshArea(name, "demand");
      });
    if (state.active_tab === "KPIs") {
      date.className += " group-field__control--range";
      date.dataset.field = "range";
      date.title = calendarNote(group.source) || "Date range";
      date.setAttribute("aria-label", `Date range for ${name}`);
      cardPickers.push(view.flatpickr(date, pickerOptions(true, STARTING_DATE, new Date(), areaSetting.range, dates => {
        if (dates.length !== 2) return; // wait for the end date
        areaSetting.range = dates.slice();
        refreshArea(name, "range");
      })));
      slot.append(settingField("fa-calendar", date), demand);
      return;
    }
    const strategy = optionField("fa-sliders", "strategy", `Charging strategy for ${name}`, STRATEGIES,
      areaSetting.strategy, value => {
        areaSetting.strategy = value;
        refreshArea(name, "strategy");
      });
    date.dataset.field = "date";
    date.title = calendarNote(group.source) || "Target date";
    date.setAttribute("aria-label", `Target date for ${name}`);
    cardPickers.push(view.flatpickr(date, pickerOptions(false, STARTING_DATE, new Date(), [areaSetting.date], dates => {
      if (!dates.length) return;
      areaSetting.date = dates[0];
      refreshArea(name, "date");
    })));
    slot.append(strategy, settingField("fa-calendar", date), demand);
  }

  const areaRequests = new Map(); // area name -> latest request, so late answers are dropped
  const pendingAreas = new Set();

  // A card's setting changed: request that area alone and redraw. The other
  // areas keep their results, and a full analysis in between wins over this one.
  async function refreshArea(name, field) {
    const index = state.selected_area_names.indexOf(name);
    if (index < 0) return;
    const token = (areaRequests.get(name) || 0) + 1;
    const analysis = state.profileRequestVersion;
    areaRequests.set(name, token);
    pendingAreas.add(name);
    view.setCardBusy(index, true);
    const superseded = () => areaRequests.get(name) !== token || analysis !== state.profileRequestVersion;
    const areaSetting = { ...settingsOf(name) };
    const options = {
      sessionSource: view.sessionSource(),
      demandAssumption: areaSetting.demand,
      ensemble: view.ensembleSize?.() ?? 1,
    };
    try {
      let group;
      if (state.active_tab === "KPIs") {
        [group] = await get_KPIs([state.selected_polygons[index]], [name], [areaSetting.range.slice()], options);
      } else {
        [group] = await get_LoadProfiles([structuredClone(state.selected_polygons[index])], [name],
          calendarDate(areaSetting.date), { ...options, strategy: areaSetting.strategy });
      }
      if (superseded()) return;
      pendingAreas.delete(name);
      // The area may have moved, or gone, while the request ran
      const at = state.selected_area_names.indexOf(name);
      if (at < 0) return;
      state.charger_ids_list[at] = group.chargerIds;
      state.transformer_ids_list[at] = group.transformerIds;
      if (state.active_tab === "KPIs") state.kpi_data_list[at] = group;
      else state.load_profile_data[at] = profileFromGroup(group, areaSetting);
      renderGroupResults();
      view.focusCardField(at, field);
    } catch (error) {
      if (superseded()) return;
      pendingAreas.delete(name);
      const at = state.selected_area_names.indexOf(name);
      if (at >= 0) view.showCardMessage(at, error.message);
    }
  }

  // Each drawn area is a polygon layer plus a label marker sharing its name
  function drawnAreas() {
    const labels = new Map();
    const areas = [];
    drawnItems.eachLayer((layer) => {
      const properties = layer.feature && layer.feature.properties;
      if (!properties) return;
      if (properties.type === "marker") labels.set(properties.name, layer);
      else areas.push(layer);
    });
    return areas.map((layer) => {
      const name = layer.feature.properties.name;
      return { layer, name, label: labels.get(name) };
    });
  }

  function areaSpecs() {
    return drawnAreas().map(({ layer, name, label }) => {
      const { color, weight, fillOpacity, dashArray } = layer.options;
      return {
        name,
        latLngs: layer.getLatLngs(),
        style: { color, weight, fillOpacity, dashArray },
        labelAt: label ? label.getLatLng() : layer.getBounds().getCenter(),
      };
    });
  }

  // Leaflet keeps layers in creation order, so rebuilding them is what reorders
  function rebuildAreas(specs) {
    drawnItems.clearLayers();
    specs.forEach(({ name, latLngs, style, labelAt }) => {
      const area = L.polygon(latLngs, style);
      area.feature = { properties: { name, type: "area" } };
      drawnItems.addLayer(area);
      const label = L.marker(labelAt, {
        icon: L.divIcon({ className: "shape-label", html: `<span>${escapeHtml(name)}</span>`, iconSize: [0, 0] }),
        interactive: false,
      });
      label.feature = { properties: { name, type: "marker" } };
      drawnItems.addLayer(label);
    });
  }

  function syncSelectionFromAreas() {
    state.selected_polygons = [];
    state.selected_area_names = [];
    drawnAreas().forEach(({ layer, name }) => {
      const ring = layer.getLatLngs()[0].map((point) => [point.lng, point.lat]);
      const first = ring[0];
      const last = ring[ring.length - 1];
      if (first[0] !== last[0] || first[1] !== last[1]) ring.push(first);
      state.selected_polygons.push({ type: "Feature", geometry: { type: "Polygon", coordinates: [ring] } });
      state.selected_area_names.push(name);
    });
    view.syncDrawPrompt();
  }

  // Apply one edit to the map areas and to every result array parallel to them
  function applyGroupEdit(specs, editResults) {
    const count = state.selected_area_names.length;
    const edit = (items) => (items.length === count ? editResults(items) : items);
    rebuildAreas(specs);
    syncSelectionFromAreas();
    state.charger_ids_list = edit(state.charger_ids_list);
    state.transformer_ids_list = edit(state.transformer_ids_list);
    state.load_profile_data = edit(state.load_profile_data);
    state.kpi_data_list = edit(state.kpi_data_list);
    renderGroupResults();
  }

  const selectionStatus = () => `${state.selected_polygons.length} of ${MAX_AREAS} areas selected. Ready to analyse`;

  function moveGroup(index, delta) {
    const target = index + delta;
    const specs = areaSpecs();
    if (target < 0 || target >= specs.length) return null;
    applyGroupEdit(moved(specs, index, target), (items) => moved(items, index, target));
    view.animateSelectMessage(selectionStatus());
    return target;
  }

  function duplicateGroup(index) {
    const specs = areaSpecs();
    if (specs.length >= MAX_AREAS) {
      view.animateSelectMessage(`You can compare up to ${MAX_AREAS} areas. Remove one to add a copy`);
      return null;
    }
    const source = specs[index];
    const name = copyName(source.name, specs.map((spec) => spec.name));
    // The copy starts from the same strategy and dates, to be changed on its card
    const sourceSettings = settingsOf(source.name);
    areaSettings.set(name, { ...sourceSettings, range: sourceSettings.range.slice() });
    const lats = source.latLngs[0].map((point) => point.lat);
    const spread = Math.max(...lats) - Math.min(...lats);
    const copy = {
      ...source,
      name,
      // Dashed over the original, so both outlines and labels stay visible
      style: { ...source.style, color: freeColor(colors, specs.map((spec) => spec.style.color)), dashArray: "10 8" },
      labelAt: L.latLng(source.labelAt.lat - spread * 0.14, source.labelAt.lng),
    };
    applyGroupEdit(copied(specs, index, () => copy), (items) =>
      copied(items, index, (item) => (Array.isArray(item) ? item.slice() : { ...item, groupName: name })));
    // A request still running for the original would otherwise leave the copy stale
    if (pendingAreas.has(source.name)) refreshArea(name);
    view.animateSelectMessage(selectionStatus());
    return index + 1;
  }

  function renameGroup(index, requested) {
    const specs = areaSpecs();
    const current = specs[index].name;
    const check = validName(requested, specs.filter((_, at) => at !== index).map((spec) => spec.name));
    if (check.error) return check.error;
    const name = check.name;
    if (name === current) return null;
    areaSettings.set(name, settingsOf(current));
    areaSettings.delete(current);
    specs[index] = { ...specs[index], name };
    applyGroupEdit(specs, (items) =>
      items.map((item, at) => (at === index && !Array.isArray(item) ? { ...item, groupName: name } : item)));
    // An answer still on its way is addressed to the old name
    if (pendingAreas.delete(current)) refreshArea(name);
    return index;
  }

  function removeGroup(index) {
    const all = areaSpecs();
    areaSettings.delete(all[index].name);
    const specs = removed(all, index);
    applyGroupEdit(specs, (items) => removed(items, index));
    view.animateSelectMessage(specs.length
      ? `Area removed. ${specs.length} of ${MAX_AREAS} selected`
      : "Draw an area on the map to start");
    return specs.length ? Math.min(index, specs.length - 1) : null;
  }

  // What the analysis panel's cards call (see setGroupControls in plotter.js)
  const groupControls = {
    colorOf: (group) => {
      const area = drawnAreas().find(({ name }) => name === group.groupName);
      return area ? area.layer.options.color : null;
    },
    canDuplicate: () => state.selected_polygons.length < MAX_AREAS,
    decorate: decorateCard,
    release: destroyCardPickers,
    move: moveGroup,
    duplicate: duplicateGroup,
    remove: removeGroup,
    rename: renameGroup,
  };

  return {
    groupControls, decorateCard, destroyCardPickers, refreshArea, drawnAreas, areaSpecs,
    syncSelectionFromAreas, moveGroup, duplicateGroup, renameGroup, removeGroup, pendingAreas,
  };
}
