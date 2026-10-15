// ---------------------------------------------------------------------------
// Shared rendering. Every chart goes through renderGroupPanels: one card per
// analysed area, with a rail (name, size and move / copy / remove actions)
// beside that area's own plot. The cards split the panel's height between
// them, so results fit without scrolling until the screen is really too small.
// ---------------------------------------------------------------------------

const NARROW_WIDTH = 640;
// Below this width per subplot column, a multi-column grid is stacked
const MIN_COLUMN_WIDTH = 300;
// Height a subplot row keeps before the panel scrolls, plus the plot margins;
// stacked rows also need room for their own axis labels and subplot title
const ROW_MIN_HEIGHT = 128;
const STACKED_ROW_MIN_HEIGHT = 150;
const CARD_CHROME = 56;
// The rail (name, settings and actions) sets the least height a card can have;
// on narrow screens it moves above the plot and needs room of its own
const RAIL_MIN_HEIGHT = 212;
const NARROW_RAIL_HEIGHT = 104;
const MAX_NAME_LENGTH = 40;

// Categorical series colours (checked for colour-vision safety) and ink tokens
const SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#6250d6"];
const COLORWAY = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"];
const INK = "#18221c";
const MUTED = "#5b6a61";
const HAIRLINE = "#e8ece9";
const FONT = "Inter, system-ui, -apple-system, Segoe UI, sans-serif";

const CARD_ACTIONS = [
  { action: "up", icon: "fa-arrow-up", label: "Move up" },
  { action: "down", icon: "fa-arrow-down", label: "Move down" },
  { action: "duplicate", icon: "fa-clone", label: "Duplicate below" },
  { action: "remove", icon: "fa-trash-o", label: "Remove" },
];

// The page owns the area selection and the per-area settings. It supplies the
// card colours, fills each card's settings slot (decorate) and handles the rail
// actions. A handler returns the index of the card the area ends up in, so
// keyboard focus can follow it; rename returns an error message instead when
// the name cannot be used, or null when nothing changed.
let groupControls = {
  colorOf: () => null,
  canDuplicate: () => false,
  decorate: () => {},
  release: () => {},
  move: () => null,
  duplicate: () => null,
  remove: () => null,
  rename: () => null,
};

export function setGroupControls(controls) {
  groupControls = { ...groupControls, ...controls };
}

let cards = []; // plots on screen: { plot, narrow, stacked, columns }
let lastRender = null; // lets a resize lay the cards out again
const boundHosts = new WeakSet();

function containerWidth(container) {
  return container.clientWidth || window.innerWidth;
}

function isNarrow(container) {
  return containerWidth(container) < NARROW_WIDTH;
}

function wouldStack(plot, columns) {
  return columns > 1 && containerWidth(plot) / columns < MIN_COLUMN_WIDTH;
}

// Word-wrap a (possibly <b>-wrapped) subplot title for small screens
function wrapTitle(text, maxChars) {
  const bold = /^<b>(.*)<\/b>$/.exec(text);
  const words = (bold ? bold[1] : text).split(" ");
  const lines = [""];
  words.forEach((word) => {
    const current = lines[lines.length - 1];
    if (current && (current + " " + word).length > maxChars) lines.push(word);
    else lines[lines.length - 1] = current ? current + " " + word : word;
  });
  const wrapped = lines.join("<br>");
  return bold ? `<b>${wrapped}</b>` : wrapped;
}

function withAlpha(hex, alpha) {
  const value = parseInt(hex.slice(1), 16);
  return `rgba(${value >> 16}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
}

// Areas are a quiet wash of the line colour, never a saturated block; where
// more than two filled series share a plot the washes only turn muddy, so
// those keep their lines. Bars are drawn solid.
function washFills(data) {
  const filled = {};
  data.forEach((trace) => {
    if (trace.type === "bar") delete trace.opacity;
    if (!trace.fill || trace.fill === "none") return;
    const key = (trace.xaxis || "x") + (trace.yaxis || "y");
    filled[key] = (filled[key] || 0) + 1;
  });
  data.forEach((trace) => {
    if (!trace.fill || trace.fill === "none") return;
    if (filled[(trace.xaxis || "x") + (trace.yaxis || "y")] > 2) {
      delete trace.fill;
      delete trace.opacity;
      return;
    }
    if (trace.fillcolor) return;
    const color = trace.line && trace.line.color;
    if (!/^#[0-9a-f]{6}$/i.test(color || "")) return;
    trace.fillcolor = withAlpha(color, 0.12);
    delete trace.opacity;
  });
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function plural(count, noun) {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

function createCard(group, index, count, chart) {
  const root = element("article", "group-card");
  root.dataset.index = String(index);
  root.setAttribute("aria-label", group.groupName);
  const color = groupControls.colorOf(group, index);
  if (color) root.style.setProperty("--swatch", color);

  const rail = element("div", "group-card__rail");
  const identity = element("div", "group-card__id");
  const heading = element("div", "group-card__heading");
  const name = element("h3", "group-card__name", group.groupName);
  name.title = group.groupName;
  const rename = element("button", "group-rename");
  rename.type = "button";
  rename.dataset.action = "rename";
  rename.title = "Rename";
  rename.setAttribute("aria-label", `Rename: ${group.groupName}`);
  const pencil = element("i", "fa fa-pencil");
  pencil.setAttribute("aria-hidden", "true");
  rename.append(pencil);
  heading.append(name, rename);
  identity.append(heading, element("p", "group-card__meta", plural(group.number_of_chargers || 0, "charger")));

  const actions = element("div", "group-card__actions");
  actions.setAttribute("role", "group");
  actions.setAttribute("aria-label", `Actions for ${group.groupName}`);
  CARD_ACTIONS.forEach(({ action, icon, label }) => {
    const button = element("button", `group-action group-action--${action}`);
    button.type = "button";
    button.dataset.action = action;
    button.title = label;
    button.setAttribute("aria-label", `${label}: ${group.groupName}`);
    button.disabled =
      (action === "up" && index === 0) ||
      (action === "down" && index === count - 1) ||
      (action === "duplicate" && !groupControls.canDuplicate());
    const glyph = element("i", `fa ${icon}`);
    glyph.setAttribute("aria-hidden", "true");
    button.append(glyph);
    actions.append(button);
  });

  // Per-area settings (strategy, dates) are drawn by the page
  const fields = element("div", "group-card__fields");
  groupControls.decorate(fields, group, index);

  rail.append(identity, fields, actions);
  const plot = element("div", "group-card__plot");
  root.append(rail, plot);
  return { root, plot };
}

function focusAction(host, index, action) {
  const root = host.querySelector(`.group-card[data-index="${index}"]`);
  const target =
    root &&
    (root.querySelector(`[data-action="${action}"]:not(:disabled)`) ||
      root.querySelector("button:not(:disabled)"));
  if (target) target.focus();
}

// Swap the name for a text field. Enter or leaving the field saves, Escape
// cancels; a name the page refuses stays open with the reason shown.
function startRename(host, root) {
  const name = root.querySelector(".group-card__name");
  if (!name || name.tagName === "INPUT") return;
  const index = Number(root.dataset.index);
  const input = element("input", "group-card__rename");
  input.type = "text";
  input.value = name.textContent;
  input.maxLength = MAX_NAME_LENGTH;
  input.setAttribute("aria-label", "Area name");
  let finished = false;
  const finish = (save) => {
    if (finished) return;
    if (save) {
      const result = groupControls.rename(index, input.value);
      if (typeof result === "string") {
        input.classList.add("is-invalid");
        input.setCustomValidity(result);
        input.reportValidity();
        return;
      }
      finished = true;
      // A rename redraws the cards; otherwise nothing changed
      if (Number.isInteger(result)) focusAction(host, result, "rename");
      else input.replaceWith(name);
      return;
    }
    finished = true;
    input.replaceWith(name);
    focusAction(host, index, "rename");
  };
  input.addEventListener("input", () => {
    input.setCustomValidity("");
    input.classList.remove("is-invalid");
  });
  input.addEventListener("keydown", (event) => {
    // Typing must not reach the page's shortcuts (Escape closes the panel)
    event.stopPropagation();
    if (event.key === "Enter") finish(true);
    else if (event.key === "Escape") finish(false);
  });
  // Leaving the field saves a usable name and drops one the page refused
  input.addEventListener("blur", () => finish(!input.classList.contains("is-invalid")));
  name.replaceWith(input);
  input.focus();
  input.select();
}

// One delegated listener serves every card, however often they are rebuilt
function bindCardActions(host) {
  if (boundHosts.has(host)) return;
  boundHosts.add(host);
  host.addEventListener("dblclick", (event) => {
    const name = event.target.closest && event.target.closest(".group-card__name");
    if (name) startRename(host, name.closest(".group-card"));
  });
  host.addEventListener("click", (event) => {
    const button = event.target.closest && event.target.closest("button[data-action]");
    const root = button && button.closest(".group-card");
    if (!root || button.disabled) return;
    const index = Number(root.dataset.index);
    const action = button.dataset.action;
    if (action === "rename") {
      startRename(host, root);
      return;
    }
    const next =
      action === "up" ? groupControls.move(index, -1)
      : action === "down" ? groupControls.move(index, 1)
      : action === "duplicate" ? groupControls.duplicate(index)
      : groupControls.remove(index);
    if (Number.isInteger(next)) focusAction(host, next, action);
  });
}

function renderGroupPanels(groups, buildChart) {
  const host = document.getElementById("graph");
  if (!groups.length) {
    showGraphMessage("No areas selected", "Draw an area on the map, then press Analyse.");
    return;
  }
  groupControls.release();
  cards.forEach(({ plot }) => Plotly.purge(plot));
  cards = [];
  lastRender = { groups, buildChart };
  bindCardActions(host);

  const narrow = isNarrow(host);
  const stack = element("div", narrow ? "group-stack group-stack--narrow" : "group-stack");
  const entries = groups.map((group, index) => {
    const chart = buildChart(group, index);
    return { ...chart, ...createCard(group, index, groups.length, chart), narrow };
  });
  entries.forEach((entry) => stack.append(entry.root));
  host.innerHTML = "";
  host.append(stack);

  // Sizes depend on the laid-out width, so measure once the cards are in place
  entries.forEach((entry) => {
    if (entry.message) {
      entry.plot.append(element("p", "group-card__empty", entry.message));
      entry.root.style.minHeight = `${narrow ? NARROW_RAIL_HEIGHT + CARD_CHROME : RAIL_MIN_HEIGHT}px`;
      return;
    }
    const grid = entry.layout.grid;
    entry.columns = (grid && grid.columns) || 1;
    entry.stacked = wouldStack(entry.plot, entry.columns);
    const rows = ((grid && grid.rows) || 1) * (entry.stacked ? entry.columns : 1);
    const rowHeight = rows > 1 ? STACKED_ROW_MIN_HEIGHT : ROW_MIN_HEIGHT;
    const chrome = CARD_CHROME + (narrow ? NARROW_RAIL_HEIGHT : 0);
    const plotHeight = rows * rowHeight + chrome;
    entry.root.style.minHeight = `${narrow ? plotHeight : Math.max(plotHeight, RAIL_MIN_HEIGHT)}px`;
  });
  entries.forEach((entry) => {
    if (entry.message) return;
    drawPlot(entry);
    cards.push(entry);
  });
}

function drawPlot({ plot, data, layout, narrow, stacked, columns }) {
  const grid = layout.grid;
  if (grid) {
    let rows = grid.rows || 1;
    // Grid cells are numbered row-major, so stacking keeps every axis reference
    if (stacked) {
      rows *= columns;
      grid.rows = rows;
      grid.columns = 1;
    }
    grid.ygap = rows > 1 ? 0.42 : undefined;
    grid.xgap = columns > 1 && !stacked ? 0.1 : undefined;
  }

  const annotations = layout.annotations || [];
  // Subplot titles sit above their plot and need room; in-plot notes do not
  const top = (annotations.some((annotation) => annotation.y > 1) ? 30 : 8) + (narrow ? 24 : 0);
  layout.autosize = true;
  layout.margin = narrow ? { t: top, b: 34, l: 46, r: 8 } : { t: top, b: 36, l: 58, r: 150 };
  layout.font = { family: FONT, size: narrow ? 10 : 11, color: INK };
  layout.paper_bgcolor = "rgba(0,0,0,0)";
  layout.plot_bgcolor = "rgba(0,0,0,0)";
  layout.colorway = COLORWAY;
  layout.bargap = 0.45;
  layout.hovermode = layout.hovermode || "x unified";
  layout.hoverlabel = {
    bgcolor: "#ffffff",
    bordercolor: "#dfe5e1",
    font: { family: FONT, size: 12, color: INK },
  };
  layout.showlegend = true;
  // Beside the plot on wide cards (costs width, not the scarce height)
  layout.legend = narrow
    ? { orientation: "h", x: 0, xanchor: "left", y: 1, yanchor: "top", yref: "container", font: { size: 11 } }
    : { orientation: "v", x: 1.01, xanchor: "left", y: 0.5, yanchor: "middle", font: { size: 11 } };

  annotations.forEach((annotation) => {
    annotation.font = { family: FONT, color: INK, ...(annotation.font || {}), size: narrow ? 11 : 12 };
    if (narrow && annotation.text) {
      annotation.text = wrapTitle(annotation.text, 36);
    }
  });

  Object.keys(layout)
    .filter((key) => /^[xy]axis\d*$/.test(key))
    .forEach((key) => {
      const axis = layout[key];
      const isY = key.startsWith("y");
      const title = typeof axis.title === "string" ? axis.title : axis.title && axis.title.text;
      layout[key] = {
        automargin: true,
        showgrid: isY,
        gridcolor: HAIRLINE,
        zeroline: isY,
        zerolinecolor: "#d5dcd7",
        showline: !isY,
        linecolor: "#d5dcd7",
        ticks: "",
        tickfont: { size: narrow ? 10 : 11, color: MUTED },
        ...axis,
        title: title && title.trim() ? { text: title, font: { size: 11, color: MUTED }, standoff: 6 } : undefined,
      };
    });

  washFills(data);
  Plotly.newPlot(plot, data, layout, {
    responsive: true,
    displaylogo: false,
    // The modebar would cover the legend on small screens
    displayModeBar: narrow ? false : "hover",
    modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"],
    toImageButtonOptions: { filename: "epiot_chart", scale: 2 },
  });
}

// Replace the chart area with an explanatory message (errors, empty areas)
export function showGraphMessage(title, detail = "") {
  const container = document.getElementById("graph");
  groupControls.release();
  cards.forEach(({ plot }) => Plotly.purge(plot));
  cards = [];
  lastRender = null;
  container.innerHTML = `
    <div class="graph-message" role="status">
      <i class="fa fa-exclamation-circle" aria-hidden="true"></i>
      <div class="graph-message__title"></div>
      <div class="graph-message__detail"></div>
    </div>
  `;
  container.querySelector(".graph-message__title").textContent = title;
  container.querySelector(".graph-message__detail").textContent = detail;
}

function cardAt(index) {
  return document.getElementById("graph").querySelector(`.group-card[data-index="${index}"]`);
}

// Dim one card while its own request runs; the other cards stay usable
export function setCardBusy(index, busy) {
  const root = cardAt(index);
  if (!root) return;
  root.className = busy ? "group-card group-card--busy" : "group-card";
  root.setAttribute("aria-busy", String(busy));
}

// Replace one card's plot with a message (a failed request for that area)
export function showCardMessage(index, text) {
  const root = cardAt(index);
  const plot = root && root.querySelector(".group-card__plot");
  if (!plot) return;
  Plotly.purge(plot);
  cards = cards.filter((card) => card.plot !== plot);
  plot.innerHTML = "";
  plot.append(element("p", "group-card__empty", text));
  setCardBusy(index, false);
}

export function focusCardField(index, field) {
  const root = cardAt(index);
  const target = root && root.querySelector(`[data-field="${field}"]`);
  if (target) target.focus();
}

// Lay the cards out again when the screen crosses the narrow / stacked breakpoints
let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    const host = document.getElementById("graph");
    // Nothing to lay out while the spinner or a message has replaced the cards
    if (!lastRender || !host || !cards.length || !host.querySelector(".group-stack")) return;
    const narrow = isNarrow(host);
    const changed = cards.some(
      (card) => card.narrow !== narrow || card.stacked !== wouldStack(card.plot, card.columns)
    );
    if (changed) renderGroupPanels(lastRender.groups, lastRender.buildChart);
  }, 150);
});

// ---------------------------------------------------------------------------
// Load profiles and the flexibility (polytope) envelope
// ---------------------------------------------------------------------------

// 288 ten-minute steps from 00:00 of the day before the target date, for
// results that arrive without timestamps
function defaultTimeSteps(startDate) {
  let start;
  if (!startDate) {
    const today = new Date();
    start = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1, 0, 0, 0);
  } else {
    start = new Date(startDate);
    start.setDate(start.getDate() - 1);
    start.setHours(0, 0, 0, 0);
  }
  return Array.from({ length: 288 }, (_, i) => new Date(start.getTime() + i * 600000));
}

function chartTimes(item) {
  return item.pastTimes ? item.pastTimes.concat(item.futureTimes) : defaultTimeSteps(item.targetDate);
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

// The two calendar days a chart covers, [previous, target], as UTC-midnight
// dates. They come from the area's target date, not from the timestamps, which
// are UTC instants of local midnights and would shift with the browser's zone.
function chartDays(item, times, split) {
  let target;
  if (item.targetDate) {
    const [year, month, day] = String(item.targetDate).slice(0, 10).split("-").map(Number);
    target = Date.UTC(year, month - 1, day);
  } else {
    const first = new Date(times[split]);
    target = Date.UTC(first.getFullYear(), first.getMonth(), first.getDate());
  }
  return Number.isFinite(target) ? [new Date(target - 86400000), new Date(target)] : null;
}

// "Wed 14/10/2026"; weekend days come out bold so they stand apart
function dayText(prefix, date) {
  const pad = (number) => String(number).padStart(2, "0");
  const text = `${prefix} · ${WEEKDAYS[date.getUTCDay()]} ` +
    `${pad(date.getUTCDate())}/${pad(date.getUTCMonth() + 1)}/${date.getUTCFullYear()}`;
  const weekend = date.getUTCDay() === 0 || date.getUTCDay() === 6;
  return weekend ? `<b>${text}</b>` : text;
}

// A quiet wash per day in the day's own colour: orange before, blue on the
// target day
function dayBands(times, split, axis = "") {
  const band = (from, to, fillcolor) => ({
    type: "rect",
    xref: "x" + axis,
    yref: `y${axis} domain`,
    x0: times[from],
    y0: 0,
    x1: times[to],
    y1: 1,
    fillcolor,
    layer: "below",
    line: { width: 0 },
  });
  return [
    band(0, split - 1, withAlpha(SERIES[1], 0.045)),
    band(split, times.length - 1, withAlpha(SERIES[0], 0.045)),
  ];
}

// Direct labels name each day's band with its weekday and date, so the legend
// entries can stay short and weekends are easy to spot
function dayLabels(item, times, split, axis = "") {
  const days = chartDays(item, times, split);
  if (!days) return [];
  const label = (index, text) => ({
    text, xref: "x" + axis, yref: `y${axis} domain`, x: times[index], y: 1, xanchor: "left", yanchor: "top",
    xshift: 6, yshift: -4, showarrow: false, font: { size: 10, color: MUTED },
  });
  return [
    label(0, dayText("Previous day", days[0])),
    label(split, dayText("Target day", days[1])),
  ];
}

// Timestamps are UTC; a tiny note beats an axis title that costs plot height
function utcNote(item) {
  return item.pastTimes
    ? [{
        text: "UTC", xref: "paper", yref: "paper", x: 1, y: 0, xshift: 16, yshift: -6,
        xanchor: "left", yanchor: "top", showarrow: false,
        font: { size: 10, color: MUTED },
      }]
    : [];
}

function loadChart(item, { range }) {
  const times = chartTimes(item);
  const split = item.pastData.length;
  const trace = (from, to, y, name, color, width) => ({
    x: times.slice(from, to),
    y,
    mode: "lines",
    name,
    fill: "tozeroy",
    line: { color, shape: "hv", width },
    hovertemplate: "%{y:,.1f} kW",
  });
  return {
    data: [
      trace(0, split, item.pastData, "Previous day", SERIES[1], 1.75),
      trace(split, times.length, item.futureData, "Target day", SERIES[0], 2),
    ],
    layout: {
      xaxis: { hoverformat: "%a %d %b, %H:%M" },
      yaxis: { title: "Power (kW)", range },
      shapes: dayBands(times, split),
      annotations: dayLabels(item, times, split).concat(utcNote(item)),
    },
  };
}

// Energy-feasible envelope of the aggregate schedule: power and cumulative
// energy side by side, so a card keeps the same height as the other views
function polytopeChart(item, { range }) {
  const poly = item.polytope;
  if (!poly) {
    return { message: "The polytope envelope needs a scenario session source (simple, spatial or CPFT)." };
  }
  const load = item.pastData.concat(item.futureData);
  const times = item.pastTimes ? item.pastTimes.concat(item.futureTimes) : load.map((_, i) => i);
  let running = 0;
  const scheduled = load.map((kw) => (running += kw / 6));
  const lower = { color: SERIES[0], shape: "hv", width: 1.25, dash: "dot" };
  const upper = { color: SERIES[0], shape: "hv", width: 1.5 };
  const schedule = { color: INK, shape: "hv", width: 2 };
  const wash = withAlpha(SERIES[0], 0.14);
  // The energy axis shares the power traces' legend entries
  const trace = (axis, unit, y, name, group, extra) => ({
    x: times,
    y,
    mode: "lines",
    name,
    legendgroup: group,
    showlegend: axis === "",
    xaxis: "x" + axis,
    yaxis: "y" + axis,
    hovertemplate: `%{y:,.1f} ${unit}`,
    ...extra,
  });
  const subplotTitle = (axis, text) => ({
    text: `<b>${text}</b>`, xref: `x${axis} domain`, yref: `y${axis} domain`,
    x: 0, y: 1.05, xanchor: "left", yanchor: "bottom", showarrow: false,
  });
  const split = item.pastData.length;
  return {
    data: [
      trace("", "kW", poly.power_min_kw, "Minimum feasible power", "min", { line: lower }),
      trace("", "kW", poly.power_max_kw, "Maximum feasible power", "max", { line: upper, fill: "tonexty", fillcolor: wash }),
      trace("", "kW", load, "Scheduled load", "load", { line: schedule }),
      trace("2", "kWh", poly.cumulative_min_kwh, "Minimum cumulative energy", "min", { line: lower }),
      trace("2", "kWh", poly.cumulative_max_kwh, "Maximum cumulative energy", "max", { line: upper, fill: "tonexty", fillcolor: wash }),
      trace("2", "kWh", scheduled, "Scheduled cumulative energy", "load", { line: schedule }),
    ],
    layout: {
      grid: { rows: 1, columns: 2, pattern: "independent" },
      xaxis: { hoverformat: "%a %d %b, %H:%M" },
      yaxis: { range },
      xaxis2: { hoverformat: "%a %d %b, %H:%M" },
      yaxis2: {},
      shapes: dayBands(times, split).concat(dayBands(times, split, "2")),
      annotations: [subplotTitle("", "Power (kW)"), subplotTitle("2", "Cumulative energy (kWh)")]
        .concat(dayLabels(item, times, split), dayLabels(item, times, split, "2")),
    },
  };
}

export function createGraph(groupData) {
  // One scale for every area, so loads can be compared across cards
  const peak = Math.max(0, ...groupData.map((item) => Math.max(...item.pastData, ...item.futureData)));
  const range = [0, peak > 0 ? peak * 1.1 : 1];
  renderGroupPanels(groupData, (item) => loadChart(item, { range }));
}

// Flexibility: the energy-feasible envelope of each area's aggregate schedule
export function createPolytopeGraph(groupData) {
  if (!groupData.some((item) => item.polytope)) {
    showGraphMessage(
      "Polytope flexibility needs a scenario session source",
      "Choose a simple, spatial or CPFT session source to see the energy-feasible envelope."
    );
    return;
  }
  // One power scale for every area, with headroom above the highest curve for the day labels
  const power = groupData.flatMap((item) =>
    item.polytope ? [...item.polytope.power_max_kw, ...item.pastData, ...item.futureData] : []);
  const range = [0, Math.max(0, ...power) * 1.2 || 1];
  renderGroupPanels(groupData, (item) => polytopeChart(item, { range }));
}

function userKpiChart(groupData) {
  var data = [];

  var layout = {
    grid: {
      rows: groupData.length,
      // rows: 1,
      columns: 3,
      pattern: "independent",
    },
    showlegend: true,
    hovermode: "x unified", // Synchronize hover over x-axis
    legend: {
      orientation: "h",
      x: 0.5,
      y: 1.1,
      xanchor: "center",
      yanchor: "bottom",
      traceorder: "normal",
      ncols: 2,
    },
    // automargin: true,
    margin: { t: 80, b: 100, l: 80, r: 80 },
    xaxis1: { title: "Time (Hour)" },
    yaxis1: { title: "Sessions Count" },
    xaxis2: { title: "Time (Hour)" },
    yaxis2: { title: "Sessions Count" },
    xaxis3: { title: "Time (Hour)" },
    yaxis3: { title: "Sessions Count" },
    xaxis4: { title: "Time (Hour)" },
    yaxis4: { title: "Sessions Count" },
    xaxis5: { title: "Time (Hour)" },
    yaxis5: { title: "Sessions Count" },
    xaxis6: { title: "Time (Hour)" },
    yaxis6: { title: "Sessions Count" },
    xaxis7: { title: "Time (Hour)" },
    yaxis7: { title: "Sessions Count" },
    xaxis8: { title: "Time (Hour)" },
    yaxis8: { title: "Sessions Count" },
    xaxis9: { title: "Time (Hour)" },
    yaxis9: { title: "Sessions Count" },
  };

  layout.shapes = [];
  layout.annotations = [];

  let today = new Date();
  let startDate = new Date(
    today.getFullYear(),
    today.getMonth(),
    today.getDate() - 1,
    0,
    0,
    0
  );

  // Generate time steps as Date objects
  var timeSteps = Array.from({ length: 24 }, (_, i) => {
    let date = new Date(startDate.getTime());
    date.setHours(date.getHours() + i);
    return date.getHours();
  });

  groupData.forEach((dataItem, index) => {
    // Create traces for past and future data as step plots
    var pastTrace_up = {
      x: timeSteps,
      y: dataItem.kpi.arrival_dist_wd,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: SERIES[0], shape: "spline" },
      name: "Weekdays",
      xaxis: "x" + (3 * index + 1),
      yaxis: "y" + (3 * index + 1),
      opacity: 0.3,
      // legendgroup: "group",
      showlegend: index === 0, // Show legend only once
    };

    var pastTrace_down = {
      x: timeSteps,
      y: dataItem.kpi.arrival_dist_we,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: SERIES[1], shape: "spline" }, // Step plot
      name: "Weekends",
      xaxis: "x" + (3 * index + 1),
      yaxis: "y" + (3 * index + 1),
      // legendgroup: "group",
      showlegend: index === 0, // Show legend only once
      opacity: 0.3,
    };

    var dist_2_wd = {
      x: timeSteps,
      y: dataItem.kpi.duration_dist_wd,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: SERIES[0], shape: "spline" },
      name: "Weekdays",
      opacity: 0.3,
      xaxis: "x" + (3 * index + 2),
      yaxis: "y" + (3 * index + 2),
      // legendgroup: "group",
      showlegend: false,
    };

    var dist_2_we = {
      x: timeSteps,
      y: dataItem.kpi.duration_dist_we,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: SERIES[1], shape: "spline" },
      name: "Weekends",
      xaxis: "x" + (3 * index + 2),
      yaxis: "y" + (3 * index + 2),
      legendgroup: "group",
      showlegend: false,
    };

    var dist_3_we = {
      x: timeSteps,
      y: dataItem.kpi.departure_dist_we,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: SERIES[1], shape: "spline" },
      name: "Weekends",
      xaxis: "x" + (3 * index + 3),
      yaxis: "y" + (3 * index + 3),
      legendgroup: "group",
      showlegend: false,
    };

    var dist_3_wd = {
      x: timeSteps,
      y: dataItem.kpi.departure_dist_wd,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: SERIES[0], shape: "spline" },
      name: "Weekdays",
      opacity: 0.3,
      xaxis: "x" + (3 * index + 3),
      yaxis: "y" + (3 * index + 3),
      legendgroup: "group",
      showlegend: false,
    };

    data.push(
      pastTrace_down,
      pastTrace_up,
      dist_2_we,
      dist_2_wd,
      dist_3_we,
      dist_3_wd
    );

    if (groupData.length === 2) {
      layout.xaxis1.title = '';
      layout.xaxis2.title = '';
      layout.xaxis3.title = '';
    } else if (groupData.length === 3) {
      layout.xaxis1.title = '';
      layout.xaxis2.title = '';
      layout.xaxis3.title = '';
      layout.xaxis4.title = '';
      layout.xaxis5.title = '';
      layout.xaxis6.title = '';
    }

    if (index == 0) {
      // change y-axis title
      layout.yaxis1.title = `Sessions Count`;
    } else if (index == 1) {
      layout.yaxis4.title = `Sessions Count`;
    } else if (index == 2) {
      layout.yaxis7.title = `Sessions Count`;
    }

    let label = "";

    label =
      "<b>User Probability Distributions: " +
      dataItem.groupName +
      " (" +
      dataItem.number_of_chargers +
      " chargers)" +
      "</b>";

    let label1 = "<b>Arrival Distribution</b>";
    let label2 = "<b>Duration Distribution</b>";
    let label3 = "<b>Departure Distribution</b>";

    if (index == 0) {
      // Add titles to each subplot
      layout.annotations.push({
        text: label1,
        xref: "x" + (3 * index + 1) + " domain",
        yref: "y" + (3 * index + 1) + " domain",
        x: 0.5,
        y: 1.05,
        xanchor: "center",
        yanchor: "bottom",
        showarrow: false,
        font: { size: 16 },
      });
      layout.annotations.push({
        text: label2,
        xref: "x" + (3 * index + 2) + " domain",
        yref: "y" + (3 * index + 2) + " domain",
        x: 0.5,
        y: 1.05,
        xanchor: "center",
        yanchor: "bottom",
        showarrow: false,
        font: { size: 16 },
      });
      layout.annotations.push({
        text: label3,
        xref: "x" + (3 * index + 3) + " domain",
        yref: "y" + (3 * index + 3) + " domain",
        x: 0.5,
        y: 1.05,
        xanchor: "center",
        yanchor: "bottom",
        showarrow: false,
        font: { size: 16 },
      });
    }
  });

  // //   add the plot main x-axis

  //     layout.xaxis = {
  //         showticklabels: false, // Show tick labels only on the last subplot
  //         tickangle: -45, // Rotate labels if needed
  //         };

  return { data, layout };
}

function gridKpiChart(groupData) {
  var data = [];

  var layout = {
    grid: {
      rows: groupData.length,
      // rows: 1,
      columns: 3,
      pattern: "independent",
    },
    showlegend: true,
    hovermode: "x unified", // Synchronize hover over x-axis
    legend: {
      orientation: "h",
      x: 0.5,
      y: 1.1,
      xanchor: "center",
      yanchor: "bottom",
      traceorder: "normal",
      ncols: 2,
    },
    // automargin: true,
    margin: { t: 80, b: 100, l: 80, r: 80 },
    xaxis1: { title: "Arrival Time (Hour)" },
    yaxis1: { title: "Charged Energy (kWh)" },
    xaxis2: { title: "Daily Charged Energy (kWh)" },
    yaxis2: { title: "Days Count" },
    xaxis3: { title: "Session Energy Charged (kWh)" },
    yaxis3: { title: "Sessions Count" },

    xaxis4: { title: "Arrival Time (Hour)" },
    yaxis4: { title: "Charged Energy (kWh)" },
    xaxis5: { title: "Daily Charged Energy (kWh)" },
    yaxis5: { title: "Days Count" },
    xaxis6: { title: "Session Energy Charged (kWh)" },
    yaxis6: { title: "Sessions Count" },

    xaxis7: { title: "Arrival Time (Hour)" },
    yaxis7: { title: "Charged Energy (kWh)" },
    xaxis8: { title: "Daily Charged Energy (kWh)" },
    yaxis8: { title: "Days Count" },
    xaxis9: { title: "Session Energy Charged (kWh)" },
    yaxis9: { title: "Sessions Count" },

  };

  layout.shapes = [];
  layout.annotations = [];

  let today = new Date();
  let startDate = new Date(
    today.getFullYear(),
    today.getMonth(),
    today.getDate() - 1,
    0,
    0,
    0
  );

  // Generate time steps as Date objects
  var timeSteps = Array.from({ length: 24 }, (_, i) => {
    let date = new Date(startDate.getTime());
    date.setHours(date.getHours() + i);
    return date.getHours();
  });

  groupData.forEach((dataItem, index) => {
    // Create traces for past and future data as step plots
    var pastTrace_up = {
      x: timeSteps,
      y: dataItem.kpi.hour_of_arrival_consumption_wd,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: SERIES[0], shape: "hv" },
      name: "Weekdays",
      xaxis: "x" + (3 * index + 1),
      yaxis: "y" + (3 * index + 1),
      opacity: 0.3,
      // legendgroup: "group",
      showlegend: index === 0, // Show legend only once
    };

    var pastTrace_down = {
      x: timeSteps,
      y: dataItem.kpi.hour_of_arrival_consumption_we,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: SERIES[1], shape: "hv" }, // Step plot
      name: "Weekends",
      xaxis: "x" + (3 * index + 1),
      yaxis: "y" + (3 * index + 1),
      // legendgroup: "group",
      showlegend: index === 0, // Show legend only once
      opacity: 0.3,
    };

    var dist_2_wd = {
      x: Array.from({length: 10}, (_, i) => 10+20*i),
      y: dataItem.kpi.daily_consumption_dist_wd,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: SERIES[0], shape: "spline" },
      name: "Weekdays",
      opacity: 0.3,
      xaxis: "x" + (3 * index + 2),
      yaxis: "y" + (3 * index + 2),
      // legendgroup: "group",
      showlegend: false,
    };

    var dist_2_we = {
      x: Array.from({length: 10}, (_, i) => 10+20*i),
      y: dataItem.kpi.daily_consumption_dist_we,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: SERIES[1], shape: "spline" },
      name: "Weekends",
      xaxis: "x" + (3 * index + 2),
      yaxis: "y" + (3 * index + 2),
      legendgroup: "group",
      showlegend: false,
    };

    var dist_3_wd = {
      x: Array.from({length: 10}, (_, i) => 5+10*i),
      y: dataItem.kpi.consumption_dist_wd,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: SERIES[0], shape: "spline" },
      name: "Weekdays",
      opacity: 0.3,
      xaxis: "x" + (3 * index + 3),
      yaxis: "y" + (3 * index + 3),
      // legendgroup: "group",
      showlegend: false,
    };

    var dist_3_we = {
      x: Array.from({length: 10}, (_, i) => 5+10*i),
      y: dataItem.kpi.consumption_dist_we,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: SERIES[1], shape: "spline" },
      name: "Weekends",
      xaxis: "x" + (3 * index + 3),
      yaxis: "y" + (3 * index + 3),
      legendgroup: "group",
      showlegend: false,
    };


    data.push(
      pastTrace_down,
      pastTrace_up,
      dist_2_we,
      dist_2_wd,
      dist_3_we,
      dist_3_wd
    );

    // if (groupData.length === 2) {
    //   layout.xaxis1.title = '';
    //   layout.xaxis2.title = '';      
    // } else
     if (groupData.length === 3) {
      layout.xaxis1.title = '';
      layout.xaxis2.title = '';
      layout.xaxis3.title = '';
      layout.xaxis4.title = '';
      layout.xaxis5.title = '';
      layout.xaxis6.title = '';
    }

    if (index == 0) {
      // change y-axis title
      layout.yaxis1.title = `Charged Energy (kWh)`;
    } else if (index == 1) {
      layout.yaxis4.title = `Charged Energy (kWh)`;
    } else if (index == 2) {
      layout.yaxis7.title = `Charged Energy (kWh)`;
    }


    let label1 = "<b>Session Energy Distribution</b>";
    let label2 = "<b>Daily Charger Energy Consumption</b>";
    let label3 = "<b>Session Energy Consumption Distribution</b>";


    if (index == 0) {
      // Add titles to each subplot
      layout.annotations.push({
        text: label1,
        xref: "x" + (2 * index + 1) + " domain",
        yref: "y" + (2 * index + 1) + " domain",
        x: 0.5,
        y: 1.05,
        xanchor: "center",
        yanchor: "bottom",
        showarrow: false,
        font: { size: 16 },
      });
      layout.annotations.push({
        text: label2,
        xref: "x" + (2 * index + 2) + " domain",
        yref: "y" + (2 * index + 2) + " domain",
        x: 0.5,
        y: 1.05,
        xanchor: "center",
        yanchor: "bottom",
        showarrow: false,
        font: { size: 16 },
      });
      layout.annotations.push({
        text: label3,
        xref: "x" + (2 * index + 3) + " domain",
        yref: "y" + (2 * index + 3) + " domain",
        x: 0.5,
        y: 1.05,
        xanchor: "center",
        yanchor: "bottom",
        showarrow: false,
        font: { size: 16 },
      });
     
    }
  });

 

  return { data, layout };
}

function mobilityKpiChart(groupData) {
  var data = [];

  var layout = {
    grid: {
      rows: groupData.length,
      // rows: 1,
      columns: 1,
      pattern: "independent",
    },
    showlegend: true,
    hovermode: "x unified", // Synchronize hover over x-axis
    legend: {
      orientation: "h",
      x: 0.5,
      y: 1.1,
      xanchor: "center",
      yanchor: "bottom",
      traceorder: "normal",
      ncols: 2,
    },
    // automargin: true,
    margin: { t: 80, b: 100, l: 80, r: 80 },
    xaxis1: { title: "Number of Sessions per Charger" },
    yaxis1: { title: "Charged Energy (kWh)" },
    xaxis2: { title: "Number of Sessions per Charger" },
    yaxis2: { title: "Days Count" },
    xaxis3: { title: "Number of Sessions per Charger" },
    yaxis3: { title: "Sessions Count" },

  };

  layout.shapes = [];
  layout.annotations = [];

  let today = new Date();
  let startDate = new Date(
    today.getFullYear(),
    today.getMonth(),
    today.getDate() - 1,
    0,
    0,
    0
  );

  // Generate time steps as Date objects
  var timeSteps = Array.from({ length: 24 }, (_, i) => {
    let date = new Date(startDate.getTime());
    date.setHours(date.getHours() + i);
    return date.getHours();
  });

  groupData.forEach((dataItem, index) => {
    // Create traces for past and future data as step plots
    var day_0 = {
      x: [0,1,2,3,4,5],
      y: dataItem.kpi.sessions_per_day_0,
      type: "scatter",
      mode: "lines",
      // fill: "tozeroy", // Fills the area under the line to the x-axis
      line: {shape: "spline" },
      name: "Monday",
      xaxis: "x" + (1 * index + 1),
      yaxis: "y" + (1 * index + 1),
      opacity: 1,
      // legendgroup: "group",
      showlegend: index === 0, // Show legend only once
    };
    var day_1 = {
      x: [0,1,2,3,4,5],
      y: dataItem.kpi.sessions_per_day_1,
      type: "scatter",
      mode: "lines",
      // fill: "tozeroy", // Fills the area under the line to the x-axis
      line: {shape: "spline" },
      name: "Tuesday",
      xaxis: "x" + (1 * index + 1),
      yaxis: "y" + (1 * index + 1),
      opacity: 1,
      showlegend: index === 0,
    };

    var day_2 = {
      x: [0,1,2,3,4,5],
      y: dataItem.kpi.sessions_per_day_2,
      type: "scatter",
      mode: "lines",
      // fill: "tozeroy", // Fills the area under the line to the x-axis
      line: {shape: "spline" },
      name: "Wednesday",
      xaxis: "x" + (1 * index + 1),
      yaxis: "y" + (1 * index + 1),
      opacity: 1,
      showlegend: index === 0,
    };
    var day_3 = {
      x: [0,1,2,3,4,5],
      y: dataItem.kpi.sessions_per_day_3,
      type: "scatter",
      mode: "lines",
      // fill: "tozeroy", // Fills the area under the line to the x-axis
      line: {shape: "spline" },
      name: "Thursday",
      xaxis: "x" + (1 * index + 1),
      yaxis: "y" + (1 * index + 1),
      opacity: 1,
      showlegend: index === 0,
    };
    var day_4 = {
      x: [0,1,2,3,4,5],
      y: dataItem.kpi.sessions_per_day_4,
      type: "scatter",
      mode: "lines",
      // fill: "tozeroy", // Fills the area under the line to the x-axis
      line: {shape: "spline" },
      name: "Friday",
      xaxis: "x" + (1 * index + 1),
      yaxis: "y" + (1 * index + 1),
      opacity: 1,
      showlegend: index === 0,
    };
    var day_5 = {
      x: [0,1,2,3,4,5],
      y: dataItem.kpi.sessions_per_day_5,
      type: "scatter",
      mode: "lines",
      // fill: "tozeroy", // Fills the area under the line to the x-axis
      line: {shape: "spline" },
      name: "Saturday",
      xaxis: "x" + (1 * index + 1),
      yaxis: "y" + (1 * index + 1),
      opacity: 1,
      showlegend: index === 0,
    };

    var day_6 = {
      x: [0,1,2,3,4,5],
      y: dataItem.kpi.sessions_per_day_6,
      type: "scatter",
      mode: "lines",
      // fill: "tozeroy", // Fills the area under the line to the x-axis
      line: {shape: "spline" },
      name: "Sunday",
      xaxis: "x" + (1 * index + 1),
      yaxis: "y" + (1 * index + 1),
      opacity: 1,
      showlegend: index === 0,
    };
    


    data.push(
      day_0,
      day_1,
      day_2,
      day_3,
      day_4,
      day_5,
      day_6
    );

    // if (groupData.length === 2) {
    //   layout.xaxis1.title = '';
    //   layout.xaxis2.title = '';      
    // } else
    //  if (groupData.length === 3) {
    //   layout.xaxis1.title = '';
    //   layout.xaxis2.title = '';
    //   layout.xaxis3.title = '';
    //   layout.xaxis4.title = '';
    //   layout.xaxis5.title = '';
    //   layout.xaxis6.title = '';
    // }

    if (index == 0) {
      // change y-axis title
      layout.yaxis1.title = `Probability`;
    } else if (index == 1) {
      layout.yaxis2.title = `Probability`;
    } else if (index == 2) {
      layout.yaxis3.title = `Probability`;
    }


    let label1 = "<b>Number of Charger Sessions per Day</b>";
    // let label2 = "<b>Daily Charger Energy Consumption</b>";
    // let label3 = "<b>Session Energy Consumption Distribution</b>";


    if (index == 0) {
      // Add titles to each subplot
      layout.annotations.push({
        text: label1,
        xref: "x" + (1 * index + 1) + " domain",
        yref: "y" + (1 * index + 1) + " domain",
        x: 0.5,
        y: 1.05,
        xanchor: "center",
        yanchor: "bottom",
        showarrow: false,
        font: { size: 16 },
      });
     
    }
  });

 

  return { data, layout };
}


function cityKpiChart(groupData) {
  var data = [];

  var layout = {
    grid: {
      rows: groupData.length,
      // rows: 1,
      columns: 2,
      pattern: "independent",
    },
    showlegend: true,
    hovermode: "x unified", // Synchronize hover over x-axis
    legend: {
      orientation: "h",
      x: 0.5,
      y: 1.1,
      xanchor: "center",
      yanchor: "bottom",
      traceorder: "normal",
      ncols: 2,
    },
    // automargin: true,
    margin: { t: 80, b: 100, l: 80, r: 80 },
    xaxis1: { title: "Time of the Day (Hour)" },
    yaxis1: { title: "Probability" },
    xaxis2: { title: "Occupancy Ratio (%)" },
    yaxis2: { title: "Probability" },
    xaxis3: { title: "Time of the Day (Hour)" },
    yaxis3: { title: "Probability" },
    xaxis4: { title: "Occupancy Ratio (%)" },
    yaxis4: { title: "Probability" },
    xaxis5: { title: "Time of the Day (Hour)" },
    yaxis5: { title: "Probability" },
    xaxis6: { title: "Occupancy Ratio (%)" },
    yaxis6: { title: "Probability" },


  };

  layout.shapes = [];
  layout.annotations = [];

  let today = new Date();
  let startDate = new Date(
    today.getFullYear(),
    today.getMonth(),
    today.getDate() - 1,
    0,
    0,
    0
  );

  // Generate time steps as Date objects
  var timeSteps = Array.from({ length: 48 }, (_, i) => i/2);
  // console.log(timeSteps);
  groupData.forEach((dataItem, index) => {
    // Create traces for past and future data as step plots
    var pastTrace_up = {
      x: timeSteps,
      y: dataItem.kpi.weekday_availability,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: SERIES[0], shape: "hvh" },
      name: "Weekdays",
      xaxis: "x" + (2 * index + 1),
      yaxis: "y" + (2 * index + 1),
      opacity: 0.3,
      // legendgroup: "group",
      showlegend: index === 0, // Show legend only once
    };

    var pastTrace_down = {
      x: timeSteps,
      y: dataItem.kpi.weekend_availability,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: SERIES[1], shape: "hvh" }, // Step plot
      name: "Weekends",
      xaxis: "x" + (2 * index + 1),
      yaxis: "y" + (2 * index + 1),
      // legendgroup: "group",
      showlegend: index === 0, // Show legend only once
      opacity: 0.3,
    };

    var dist_2_wd = {
      x: Array.from({length: 20}, (_, i) => 2.5+5*i),
      y: dataItem.kpi.occupation_ratio_dist
      ,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: SERIES[2], shape: "spline" },
      name: "Whole Week",
      opacity: 0.3,
      xaxis: "x" + (2 * index + 2),
      yaxis: "y" + (2 * index + 2),
      // legendgroup: "group",
      showlegend: index === 0,
    };


    data.push(
      pastTrace_down,
      pastTrace_up,
      dist_2_wd,
    );

    // if (groupData.length === 2) {
    //   layout.xaxis1.title = '';
    //   layout.xaxis2.title = '';      
    // } else
    //  if (groupData.length === 3) {
    //   layout.xaxis1.title = '';
    //   layout.xaxis2.title = '';
    //   layout.xaxis3.title = '';
    //   layout.xaxis4.title = '';
    //   layout.xaxis5.title = '';
    //   layout.xaxis6.title = '';
    // }

    if (index == 0) {
      // change y-axis title
      layout.yaxis1.title = `Probability`;
    } else if (index == 1) {
      layout.yaxis3.title = `Probability`;
    } else if (index == 2) {
      layout.yaxis5.title = `Probability`;
    }


    let label1 = "<b>Charger Availability Probability</b>";
    let label2 = "<b>Charger Occupancy Ratio</b>";



    if (index == 0) {
      // Add titles to each subplot
      layout.annotations.push({
        text: label1,
        xref: "x" + (2 * index + 1) + " domain",
        yref: "y" + (2 * index + 1) + " domain",
        x: 0.5,
        y: 1.05,
        xanchor: "center",
        yanchor: "bottom",
        showarrow: false,
        font: { size: 16 },
      });
      layout.annotations.push({
        text: label2,
        xref: "x" + (2 * index + 2) + " domain",
        yref: "y" + (2 * index + 2) + " domain",
        x: 0.5,
        y: 1.05,
        xanchor: "center",
        yanchor: "bottom",
        showarrow: false,
        font: { size: 16 },
      });

     
    }
  });

  return { data, layout };
}



function environmentKpiChart(groupData) {
    var data = [];

  var layout = {
    grid: {
      rows: groupData.length,
      // rows: 1,
      columns: 2,
      pattern: "independent",
    },
    showlegend: true,
    hovermode: "x unified", // Synchronize hover over x-axis
    legend: {
      orientation: "h",
      x: 0.5,
      y: 1.1,
      xanchor: "center",
      yanchor: "bottom",
      traceorder: "normal",
      ncols: 2,
    },
    // automargin: true,
    margin: { t: 80, b: 100, l: 80, r: 80 },
    xaxis1: { title: "Time of the Day (Hour)" },
    yaxis1: { title: "Carbon (gCO2eq/kWh)" },    
    xaxis2: { title: " " },
    yaxis2: { title: "Percentage (%)" },
    xaxis3: { title: " " },
    yaxis3: { title: "gCO2eq/kWh" },
    xaxis4: { title: " " },
    yaxis4: { title: "Percentage (%)" },
    xaxis5: { title: "Time of the Day (Hour)" },
    yaxis5: { title: "gCO2eq/kWh" },
    xaxis6: { title: " " },
    yaxis6: { title: "Percentage (%)" },


  };

  layout.shapes = [];
  layout.annotations = [];

  let today = new Date();
  let startDate = new Date(
    today.getFullYear(),
    today.getMonth(),
    today.getDate() - 1,
    0,
    0,
    0
  );

  // Generate time steps as Date objects
  var timeSteps = Array.from({ length: 24 }, (_, i) => {
    let date = new Date(startDate.getTime());
    date.setHours(date.getHours() + i);
    return date.getHours();
  });
  // console.log(timeSteps);
  groupData.forEach((dataItem, index) => {
    // Create traces for past and future data as step plots
    var d1 = {
      x: timeSteps,
      y: dataItem.kpi.co2_intensities_uncontrolled,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: SERIES[0], shape: "hvh" },
      name: "As Fast As Possible",
      xaxis: "x" + (2 * index + 1),
      yaxis: "y" + (2 * index + 1),
      opacity: 0.3,
      // legendgroup: "group",
      showlegend: index === 0, // Show legend only once
    };

    var d2 = {
      x: timeSteps,
      y: dataItem.kpi.co2_intensities_delayed,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: SERIES[1], shape: "hvh" }, // Step plot
      name: "As Late As Possible",
      xaxis: "x" + (2 * index + 1),
      yaxis: "y" + (2 * index + 1),
      // legendgroup: "group",
      showlegend: index === 0, // Show legend only once
      opacity: 0.3,
    };

    var d3 = {
      x: timeSteps,
      y: dataItem.kpi.co2_intensities_avg,
      type: "scatter",
      mode: "lines",
      fill: "tozeroy", // Fills the area under the line to the x-axis
      line: { color: SERIES[2], shape: "hvh" }, // Step plot
      name: "Average Power",
      xaxis: "x" + (2 * index + 1),
      yaxis: "y" + (2 * index + 1),
      // legendgroup: "group",
      showlegend: index === 0, // Show legend only once
      opacity: 0.3,
    };

    var d4 = {
      x: ["As Fast As Possible"],
      y: [dataItem.kpi.renewable_energy_shared_uncontrolled],
      type: "bar",
      marker: { color: SERIES[0] },
      name: "As Fast As Possible",
      opacity: 0.7,
      xaxis: "x" + (2 * index + 2),
      yaxis: "y" + (2 * index + 2),
      showlegend: false,
    };

    var d5 = {
      x: ["As Late As Possible"],
      y: [dataItem.kpi.renewable_energy_shared_delayed],
      type: "bar",
      marker: { color: SERIES[1] },
      name: "As Late As Possible",
      opacity: 0.7,
      xaxis: "x" + (2 * index + 2),
      yaxis: "y" + (2 * index + 2),
      showlegend: false,
    };

    var d6 = {
      x: ["Average Power"],
      y: [dataItem.kpi.renewable_energy_shared_avg],
      type: "bar",
      marker: { color: SERIES[2] },
      name: "Average Power",
      opacity: 0.7,
      xaxis: "x" + (2 * index + 2),
      yaxis: "y" + (2 * index + 2),
      showlegend: false,
    };


    data.push(
      d1,
      d2,
      d3,
      d4,
      d5,
      d6
    );
    if (dataItem.kpi.co2_intensities_mincarbon) {
      data.push({
        x: timeSteps, y: dataItem.kpi.co2_intensities_mincarbon,
        type: "scatter", mode: "lines", name: "Minimum Carbon",
        line: {color: SERIES[3], shape: "hvh"},
        xaxis: "x"+(2*index+1), yaxis: "y"+(2*index+1), showlegend: index===0,
      }, {
        x: ["Minimum Carbon"], y: [dataItem.kpi.renewable_energy_shared_mincarbon],
        type: "bar", name: "Minimum Carbon", marker: {color: SERIES[3]},
        xaxis: "x"+(2*index+2), yaxis: "y"+(2*index+2), showlegend: false,
      });
    }


    if (index == 0) {
      // change y-axis title
      layout.yaxis1.title = "Carbon (gCO2eq/kWh)";
    } else if (index == 1) {
      layout.yaxis3.title = "Carbon (gCO2eq/kWh)";
    } else if (index == 2) {
      layout.yaxis5.title = "Carbon (gCO2eq/kWh)";
    }


    let label1 = "<b>Charging-weighted Carbon Intensity</b>";
    let label2 = "<b>Renewable Energy Share</b>";



    if (index == 0) {
      // Add titles to each subplot
      layout.annotations.push({
        text: label1,
        xref: "x" + (2 * index + 1) + " domain",
        yref: "y" + (2 * index + 1) + " domain",
        x: 0.5,
        y: 1.05,
        xanchor: "center",
        yanchor: "bottom",
        showarrow: false,
        font: { size: 16 },
      });
      layout.annotations.push({
        text: label2,
        xref: "x" + (2 * index + 2) + " domain",
        yref: "y" + (2 * index + 2) + " domain",
        x: 0.5,
        y: 1.05,
        xanchor: "center",
        yanchor: "bottom",
        showarrow: false,
        font: { size: 16 },
      });

     
    }
  });

  return { data, layout };
}

export function createUserKPIGraph(groupData) {
  renderGroupPanels(groupData, (group) => userKpiChart([group]));
}

export function createGridKPIGraph(groupData) {
  renderGroupPanels(groupData, (group) => gridKpiChart([group]));
}

export function createMobilityKPIGraph(groupData) {
  renderGroupPanels(groupData, (group) => mobilityKpiChart([group]));
}

export function createCityKPIGraph(groupData) {
  renderGroupPanels(groupData, (group) => cityKpiChart([group]));
}

export function createEnvironmentKPIGraph(groupData) {
  renderGroupPanels(groupData, (group) => environmentKpiChart([group]));
}
