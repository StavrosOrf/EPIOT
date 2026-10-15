import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const code = read("../static/scripts/panel_header.js").replace(/^export /gm, "");
const { nextTabIndex, glideTo } = new Function(`${code};return {nextTabIndex,glideTo};`)();

test("arrow keys move along the tab list and wrap around", () => {
  assert.equal(nextTabIndex(0, 3, "ArrowRight"), 1);
  assert.equal(nextTabIndex(2, 3, "ArrowRight"), 0);
  assert.equal(nextTabIndex(0, 3, "ArrowLeft"), 2);
  assert.equal(nextTabIndex(1, 3, "ArrowLeft"), 0);
});

test("Home and End jump to the ends; other keys are left alone", () => {
  assert.equal(nextTabIndex(1, 3, "Home"), 0);
  assert.equal(nextTabIndex(0, 3, "End"), 2);
  for (const key of ["Enter", " ", "Tab", "a", "ArrowUp", "ArrowDown"]) {
    assert.equal(nextTabIndex(1, 3, key), -1, key);
  }
  assert.equal(nextTabIndex(0, 0, "ArrowRight"), -1);
});

test("focus outside the list starts from its first tab", () => {
  assert.equal(nextTabIndex(-1, 3, "ArrowRight"), 1);
});

test("the glider takes the active item's box from the group's padding edge", () => {
  const props = {};
  const group = { style: { setProperty: (name, value) => { props[name] = value; } } };
  glideTo(group, { offsetLeft: 112, offsetTop: 40, offsetWidth: 96, offsetHeight: 36 });
  assert.deepEqual(props, {
    "--glider-x": "112px", "--glider-y": "40px", "--glider-w": "96px", "--glider-h": "36px",
  });
});

test("tabs are wired to one labelled tabpanel with a single active tab", () => {
  const html = read("../templates/index.html");
  const tablist = /<nav class="tabs" role="tablist"[\s\S]*?<\/nav>/.exec(html)[0];
  const tabs = [...tablist.matchAll(/<button\b[\s\S]*?>/g)].map((match) => match[0]);
  assert.deepEqual(tabs.map((tab) => /id="([^"]+)"/.exec(tab)[1]), ["load-tab", "flex-tab", "stats-tab"]);
  const active = tabs.filter((tab) => /class="tab active"/.test(tab));
  assert.equal(active.length, 1);
  for (const tab of tabs) {
    assert.match(tab, /role="tab"/);
    assert.match(tab, /aria-controls="analysis-view"/);
    const selected = active.includes(tab);
    assert.match(tab, new RegExp(`aria-selected="${selected}"`));
    // roving tabindex: only the active tab is a tab stop
    assert.equal(/tabindex="-1"/.test(tab), !selected);
  }
  const panel = /<div\s+id="analysis-view"[\s\S]*?>/.exec(html)[0];
  assert.match(panel, /role="tabpanel"/);
  assert.match(panel, /aria-labelledby="load-tab"/);
});

// Header tooltips: short, and on the control they describe instead of on one
// shared info icon
const headerHtml = () => /<header class="panel__header">[\s\S]*?<\/header>/.exec(read("../templates/index.html"))[0];
const titleOf = (tag) => /\stitle="([^"]*)"/.exec(tag)?.[1];

test("the header has no catch-all info icons and every tooltip is short", () => {
  const header = headerHtml();
  assert.ok(!header.includes("info-dot"));
  const hosts = [...header.matchAll(/<[a-z]+\b[^>]*data-toggle="tooltip"[^>]*>/g)].map((match) => match[0]);
  assert.ok(hosts.length >= 9, "tabs, categories, source, export, about and close");
  for (const host of hosts) {
    const title = titleOf(host);
    assert.ok(title, host);
    assert.ok(title.length <= 40, `"${title}" is ${title.length} characters`);
  }
});

test("each KPI category and each session source has its own tooltip", () => {
  const header = headerHtml();
  const categories = [...header.matchAll(/<button[^>]*class="kpi-option[^>]*>/g)].map((match) => titleOf(match[0]));
  assert.equal(categories.length, 5);
  assert.equal(new Set(categories).size, 5);
  const selector = /<select id="session-source"[\s\S]*?<\/select>/.exec(header)[0];
  const sources = [...selector.matchAll(/<option\b[^>]*>/g)].map((match) => titleOf(match[0]));
  assert.equal(sources.length, 3);
  assert.equal(new Set(sources).size, 3);
  // The pill starts out describing the default (first) source
  const pill = /<div[^>]*class="source-pill"[^>]*>/.exec(header)[0];
  assert.equal(titleOf(pill), sources[0]);
});

test("KPI categories sit in the header's own expandable row, hidden until the KPI tab", () => {
  const html = read("../templates/index.html");
  const row = /<div class="panel__sub">[\s\S]*?id="kpi-subnav"[^>]*>/.exec(html)[0];
  assert.match(row, /class="kpi-options"/);
  assert.match(row, /\shidden/);
  const header = /<header class="panel__header">[\s\S]*?<\/header>/.exec(html)[0];
  assert.equal((header.match(/class="kpi-option( active)?"/g) || []).length, 5);
});
