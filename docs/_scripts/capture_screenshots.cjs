// Capture the screenshots used in the documentation from a running EPIOT
// instance. Requires Node 18+ and `playwright-core`, and drives an installed
// Chrome rather than downloading a browser:
//
//   npm i --no-save playwright-core
//   node docs/_scripts/capture_screenshots.cjs
//
// Environment variables:
//   EPIOT_URL   app URL               (default http://127.0.0.1:5000/)
//   CHROME      path to chrome binary (default: standard Windows install path)
//   OUT_DIR     output directory      (default docs/_static/screenshots)
//   DAY         target date           (default 2026-10-14)
//   RANGE       KPI range, "from,to"  (default 2026-10-08,2026-10-14)
//
// The script draws three fixed rectangles over central Amsterdam, so it needs
// a database that contains the Amsterdam chargers.
const { chromium } = require("playwright-core");
const path = require("path");

const URL = process.env.EPIOT_URL || "http://127.0.0.1:5000/";
const CHROME = process.env.CHROME || "C:/Program Files/Google/Chrome/Application/chrome.exe";
const OUT = process.env.OUT_DIR || path.join(__dirname, "..", "_static", "screenshots");
const DAY = process.env.DAY || "2026-10-14";
const RANGE = (process.env.RANGE || "2026-10-08,2026-10-14").split(",");

const shot = (page, name, opts = {}) =>
  page.screenshot({ path: path.join(OUT, name), type: "jpeg", quality: 84, ...opts });

const pause = (page, ms) => page.waitForTimeout(ms);

// The spinner is gone, a plot is drawn and no card is waiting for its own request
async function waitForPlot(page) {
  await page.waitForFunction(
    () => !document.querySelector("#graph .loading-container") &&
      !document.querySelector("#graph .group-card--busy") &&
      document.querySelector("#graph .main-svg"),
    null, { timeout: 180000, polling: 400 });
  await pause(page, 900);
}

async function zoom(page, direction, times) {
  for (let i = 0; i < times; i++) {
    await page.click(direction > 0 ? ".leaflet-control-zoom-in" : ".leaflet-control-zoom-out");
    await pause(page, 650);
  }
  await pause(page, 1800);
}

async function drawRect(page, x1, y1, x2, y2) {
  await page.click("#btn-draw-rectangle");
  await pause(page, 250);
  await page.mouse.move(x1, y1);
  await page.mouse.down();
  await page.mouse.move(x2, y2, { steps: 14 });
  await page.mouse.up();
  await pause(page, 500);
}

async function setCardField(page, field, index, value) {
  if (field === "strategy" || field === "demand") {
    await page.locator(`select[data-field="${field}"]`).nth(index).selectOption(value);
  } else {
    await page.evaluate(([f, i, v]) => {
      const local = (text) => {
        const [year, month, day] = text.split("-").map(Number);
        return new Date(year, month - 1, day);
      };
      const input = document.querySelectorAll(`input[data-field="${f}"]`)[i];
      input._flatpickr.setDate(Array.isArray(v) ? v.map(local) : local(v), true);
    }, [field, index, value]);
  }
  await waitForPlot(page);
}

// Drop focus and hover so no tooltip or open menu ends up in a screenshot
async function settle(page) {
  await page.mouse.move(5, 5);
  await page.evaluate(() => {
    document.querySelectorAll(".flatpickr-input").forEach((input) => input._flatpickr && input._flatpickr.close());
    document.querySelectorAll("#analysis-view, #graph").forEach((element) => element.scrollTo(0, 0));
    if (document.activeElement) document.activeElement.blur();
  });
  await pause(page, 700);
}

// Numbered callouts for the interface anatomy figures
async function annotate(page, items) {
  await page.evaluate((items) => {
    document.querySelectorAll(".doc-callout").forEach((e) => e.remove());
    items.forEach(([selector, n, dx = 0, dy = 0, place = "start"]) => {
      const el = document.querySelector(selector);
      if (!el) return;
      const r = el.getBoundingClientRect();
      const b = document.createElement("div");
      b.className = "doc-callout";
      b.textContent = n;
      // "centre" puts the badge below the element's middle, "start" at its top-left corner
      const left = place === "centre" ? r.left + r.width / 2 + dx : r.left + dx;
      const top = place === "centre" ? r.bottom + dy : r.top + dy;
      Object.assign(b.style, {
        position: "fixed", zIndex: 100000, left: `${left - 12}px`, top: `${top - 12}px`,
        width: "24px", height: "24px", borderRadius: "50%", background: "#eb6834", color: "#fff",
        font: "700 13px Inter, sans-serif", display: "flex", alignItems: "center", justifyContent: "center",
        boxShadow: "0 0 0 3px #fff, 0 2px 8px rgba(0,0,0,.35)", pointerEvents: "none",
      });
      document.body.appendChild(b);
    });
  }, items);
}
const clearCallouts = (page) => page.evaluate(() => document.querySelectorAll(".doc-callout").forEach((e) => e.remove()));

async function popupShot(page, name) {
  await pause(page, 900);
  const popup = page.locator(".leaflet-popup").first();
  const box = await popup.boundingBox();
  if (!box) return console.warn(`no popup for ${name}`);
  await shot(page, name, {
    clip: { x: Math.max(0, box.x - 90), y: Math.max(0, box.y - 50), width: box.width + 180, height: box.height + 110 },
  });
  await page.click(".leaflet-popup-close-button");
  await pause(page, 300);
}

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => console.warn("page error:", e.message));

  await page.goto(URL, { waitUntil: "load" });
  await pause(page, 2500);
  await shot(page, "landing.jpg");
  await page.click("#continue-btn");
  await pause(page, 600);

  // Overview: aggregated bubbles across Europe
  await zoom(page, -1, 7);
  await shot(page, "map-overview.jpg");
  await zoom(page, +1, 7);

  // City level, with the interface anatomy
  await zoom(page, +1, 3);
  await page.mouse.move(700, 450);
  await shot(page, "map-city.jpg");
  await annotate(page, [
    ["#logo", 1, 0, 34],
    ["#location-input", 2, 10, 36],
    ["#checkbox-container", 3, 20, 36],
    ["#open-landing-header", 4, 20, 36],
    [".leaflet-control-zoom", 5, -14, 12],
    ["#draw-toolbar", 6, 10, -14],
    ["#select-message", 7, 10, -14],
    ["#calc-button", 8, 10, -14],
  ]);
  await shot(page, "anatomy-map.jpg");
  await clearCallouts(page);

  // A charger popup: the marker nearest the middle of the map, clear of the controls
  const markerNearCentre = (selector) => page.evaluate((selector) => {
    const cx = innerWidth / 2, cy = innerHeight / 2;
    let best = null, bestDistance = Infinity;
    document.querySelectorAll(selector).forEach((el) => {
      const r = el.getBoundingClientRect();
      const x = r.left + r.width / 2, y = r.top + r.height / 2;
      if (x < 250 || x > innerWidth - 250 || y < 170 || y > innerHeight - 220) return;
      const distance = (x - cx) ** 2 + (y - cy) ** 2;
      if (distance < bestDistance) { bestDistance = distance; best = { x, y }; }
    });
    return best;
  }, selector);

  const site = await markerNearCentre(".charger-site");
  if (site) {
    await page.mouse.click(site.x, site.y);
    await pause(page, 700);
    const port = await markerNearCentre(".charger-port");
    if (port) await page.mouse.click(port.x, port.y);
    await popupShot(page, "charger-popup.jpg");
  }

  // Transformers
  await page.click("label[title='Show MV/LV transformers']");
  await pause(page, 2500);
  await shot(page, "map-transformers.jpg");
  const transformer = await markerNearCentre("img.leaflet-marker-icon[src*='transformer']");
  if (transformer) {
    await page.mouse.click(transformer.x, transformer.y);
    await popupShot(page, "transformer-popup.jpg");
  }
  await page.click("label[title='Show MV/LV transformers']");
  await pause(page, 600);

  // Drawing tools
  await page.click("#btn-draw-polygon");
  await pause(page, 500);
  await shot(page, "draw-hint.jpg", { clip: { x: 300, y: 600, width: 840, height: 300 } });
  await page.click("#btn-draw-polygon");
  await pause(page, 300);

  await drawRect(page, 330, 190, 640, 440);
  await drawRect(page, 720, 170, 1010, 400);
  await drawRect(page, 830, 470, 1160, 700);
  await pause(page, 900);
  await shot(page, "areas-drawn.jpg");

  // Analysis panel: one strategy per area
  await page.click("#calc-button");
  await waitForPlot(page);
  await setCardField(page, "date", 0, DAY);
  await setCardField(page, "date", 1, DAY);
  await setCardField(page, "date", 2, DAY);
  await setCardField(page, "strategy", 1, "alap");
  await setCardField(page, "strategy", 2, "avg");
  await settle(page);
  await shot(page, "panel-load-profiles.jpg");

  // Badges sit under the header controls, which keeps the text readable
  await annotate(page, [
    ["#panel-title", 1, 0, 6, "centre"],
    [".tabs", 2, 0, 6, "centre"],
    ["#session-source", 3, 0, 6, "centre"],
    ["#download-btn", 4, 0, 6, "centre"],
    ["#minimize-btn", 5, 0, 6, "centre"],
    [".group-card__fields", 6, -10, 20],
    [".group-card__actions", 7, -10, 14],
  ]);
  await shot(page, "anatomy-panel.jpg");
  await clearCallouts(page);

  const card = page.locator(".group-card").first();
  const cardBox = await card.locator(".group-card__rail").boundingBox();
  if (cardBox) await shot(page, "area-card.jpg", { clip: cardBox });

  // Flexibility envelope of the same three areas
  await page.click("#flex-tab");
  await waitForPlot(page);
  await settle(page);
  await shot(page, "panel-flexibility.jpg");

  // KPIs over one explicit week
  await page.click("#stats-tab");
  await waitForPlot(page);
  for (const i of [0, 1, 2]) await setCardField(page, "range", i, RANGE);
  await settle(page);
  await shot(page, "kpi-user.jpg");
  for (const [kpi, name] of [
    ["grid_kpi", "kpi-grid.jpg"], ["environment_kpi", "kpi-environment.jpg"],
    ["mobility_kpi", "kpi-mobility.jpg"], ["city_kpi", "kpi-city.jpg"],
  ]) {
    await page.click(`.kpi-option[data-kpi='${kpi}']`);
    await waitForPlot(page);
    await pause(page, 1200);
    await settle(page);
    await shot(page, name);
    if (kpi === "environment_kpi") {
      // The charts follow the summary table
      await page.evaluate(() => document.querySelector("#graph .group-card")?.scrollIntoView({ block: "start" }));
      await settle(page);
      await shot(page, "kpi-environment-charts.jpg");
      await page.evaluate(() => document.querySelector("#analysis-view")?.scrollTo(0, 0));
    }
  }

  // The same load profile under the CPFT source
  await page.click("#load-tab");
  await waitForPlot(page);
  await page.selectOption("#session-source", "cpft");
  await waitForPlot(page);
  await settle(page);
  await shot(page, "panel-cpft.jpg");

  // Phone
  const phone = await browser.newContext({
    viewport: { width: 390, height: 844 }, deviceScaleFactor: 1.5, isMobile: true, hasTouch: true,
  });
  const small = await phone.newPage();
  await small.addInitScript(() => localStorage.setItem("epiotr_intro_seen", "1"));
  await small.goto(URL, { waitUntil: "load" });
  await pause(small, 3000);
  await shot(small, "mobile-map.jpg");

  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
