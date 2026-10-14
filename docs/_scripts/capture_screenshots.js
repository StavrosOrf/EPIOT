// Capture the screenshots used in the documentation from a running EPIOT
// instance. Requires Node 18+ and `playwright-core`, and drives an installed
// Chrome rather than downloading a browser:
//
//   npm i --no-save playwright-core
//   node docs/_scripts/capture_screenshots.js
//
// Environment variables:
//   EPIOT_URL   app URL               (default http://127.0.0.1:5000/)
//   CHROME      path to chrome binary (default: standard Windows install path)
//   OUT_DIR     output directory      (default docs/_static/screenshots)
//
// The dates below must have sessions (and, for the environment KPIs, power-mix
// rows) in the database the app is pointed at.
const { chromium } = require("playwright-core");
const path = require("path");

const URL = process.env.EPIOT_URL || "http://127.0.0.1:5000/";
const CHROME = process.env.CHROME || "C:/Program Files/Google/Chrome/Application/chrome.exe";
const OUT = process.env.OUT_DIR || path.join(__dirname, "..", "_static", "screenshots");
const DAY = "2025-10-15";
const RANGE = ["2025-09-08", "2025-10-20"];

const shot = (page, name, opts = {}) =>
  page.screenshot({ path: path.join(OUT, name), type: "jpeg", quality: 82, ...opts });

async function waitForPlot(page) {
  await page.waitForFunction(
    () => !document.querySelector("#graph .loading-container") && document.querySelector("#graph .main-svg"),
    null,
    { timeout: 300000, polling: 500 }
  );
  await page.waitForTimeout(1200);
}

async function setDate(page, value) {
  await page.evaluate((v) => document.querySelector("#datepicker")._flatpickr.setDate(v, true), value);
}

async function drawRect(page, x1, y1, x2, y2) {
  await page.click("#btn-draw-rectangle");
  await page.waitForTimeout(300);
  await page.mouse.move(x1, y1);
  await page.mouse.down();
  await page.mouse.move(x2, y2, { steps: 12 });
  await page.mouse.up();
  await page.waitForTimeout(600);
}

// Overlay numbered callouts on elements, for the interface anatomy figures.
async function annotate(page, items) {
  await page.evaluate((items) => {
    document.querySelectorAll(".doc-callout").forEach((e) => e.remove());
    items.forEach(([selector, n, dx = 0, dy = 0]) => {
      const el = document.querySelector(selector);
      if (!el) return;
      const r = el.getBoundingClientRect();
      const b = document.createElement("div");
      b.className = "doc-callout";
      b.textContent = n;
      Object.assign(b.style, {
        position: "fixed", zIndex: 100000, left: `${r.left + dx - 13}px`, top: `${r.top + dy - 13}px`,
        width: "26px", height: "26px", borderRadius: "50%", background: "#eb6834", color: "#fff",
        font: "700 14px Inter, sans-serif", display: "flex", alignItems: "center", justifyContent: "center",
        boxShadow: "0 0 0 3px #fff, 0 2px 8px rgba(0,0,0,.35)",
      });
      document.body.appendChild(b);
    });
  }, items);
}

const clearCallouts = (page) => page.evaluate(() => document.querySelectorAll(".doc-callout").forEach((e) => e.remove()));

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  await page.goto(URL, { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  await shot(page, "landing.jpg");

  await page.click("#continue-btn");
  await page.click(".leaflet-control-zoom-out");
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(2500);
  await shot(page, "map-overview.jpg");

  await annotate(page, [
    ["#logo", 1, 0, -6],
    ["#open-landing-header", 2, 0, -14],
    ["#location-input", 3, -10, -14],
    ["#checkbox-container", 4, -6, -10],
    ["#btn-draw-polygon", 5, 26, -8],
    ["#btn-draw-rectangle", 6, 26, -8],
    ["#btn-draw-delete", 7, 26, -8],
    [".leaflet-control-zoom", 8, -10, 0],
    ["#select-message", 9, 0, -12],
    ["#calc-button", 10, 0, -12],
    [".custom-attribution", 11, 24, -12],
  ]);
  await shot(page, "anatomy-map.jpg");
  await clearCallouts(page);

  const marker = page.locator(".leaflet-marker-icon").nth(40);
  await marker.click({ force: true });
  await page.waitForTimeout(900);
  const box = await page.locator(".leaflet-popup").boundingBox();
  await shot(page, "charger-popup.jpg", {
    clip: { x: Math.max(0, box.x - 120), y: Math.max(0, box.y - 60), width: box.width + 240, height: box.height + 140 },
  });
  await page.click(".leaflet-popup-close-button");
  await page.waitForTimeout(300);

  await page.click("label[title='Show MV/LV transformers']");
  await page.waitForTimeout(1500);
  await shot(page, "map-transformers.jpg");
  const tr = page.locator(".leaflet-marker-icon[src*='transformer']").nth(60);
  await tr.click({ force: true });
  await page.waitForTimeout(900);
  const tbox = await page.locator(".leaflet-popup").boundingBox();
  await shot(page, "transformer-popup.jpg", {
    clip: { x: Math.max(0, tbox.x - 120), y: Math.max(0, tbox.y - 60), width: tbox.width + 240, height: tbox.height + 140 },
  });
  await page.click(".leaflet-popup-close-button");
  await page.click("label[title='Show MV/LV transformers']");
  await page.waitForTimeout(500);

  await page.click("#btn-draw-polygon");
  await page.waitForTimeout(500);
  await shot(page, "draw-hint.jpg", { clip: { x: 0, y: 60, width: 760, height: 260 } });
  await page.click("#btn-draw-polygon");

  await drawRect(page, 300, 260, 620, 520);
  await drawRect(page, 720, 230, 1010, 470);
  await drawRect(page, 860, 540, 1180, 760);
  await page.waitForTimeout(800);
  await shot(page, "areas-drawn.jpg");

  await page.click("#calc-button");
  await waitForPlot(page);
  await setDate(page, DAY);
  await waitForPlot(page);
  await shot(page, "load-profiles.jpg");

  await annotate(page, [
    ["#panel-title", 1, -14, 0],
    [".tabs", 2, -12, 0],
    ["#minimize-btn", 3, 34, 0],
    ["#toggle-div .segmented", 4, -12, 0],
    ["#strategy", 5, -12, 0],
    ["#datepicker", 6, -12, 0],
    ["#download-btn", 7, -12, 0],
    ["#graph .modebar-container .modebar", 8, -14, 12],
  ]);
  await shot(page, "anatomy-panel.jpg");
  await clearCallouts(page);

  await page.selectOption("#strategy", "alap");
  await waitForPlot(page);
  await shot(page, "load-profiles-alap.jpg");
  await page.selectOption("#strategy", "afap");
  await waitForPlot(page);

  await page.click("label[for='toggle']");
  await waitForPlot(page);
  await shot(page, "load-profiles-grid.jpg");
  await page.click("label[for='toggle']");
  await waitForPlot(page);

  await page.click("#flex-tab");
  await waitForPlot(page);
  await setDate(page, DAY);
  await waitForPlot(page);
  await shot(page, "flexibility.jpg");
  await page.selectOption("#strategy", "avg");
  await waitForPlot(page);
  await shot(page, "flexibility-avg.jpg");

  await page.click("#stats-tab");
  await waitForPlot(page);
  await setDate(page, RANGE);
  await waitForPlot(page);
  await shot(page, "kpi-user.jpg");
  for (const [kpi, name] of [
    ["grid_kpi", "kpi-grid.jpg"],
    ["environment_kpi", "kpi-environment.jpg"],
    ["mobility_kpi", "kpi-mobility.jpg"],
    ["city_kpi", "kpi-city.jpg"],
  ]) {
    await page.click(`.subtab[data-kpi='${kpi}']`);
    await page.waitForTimeout(2000);
    await shot(page, name);
  }

  const phone = await browser.newContext({
    viewport: { width: 390, height: 844 }, deviceScaleFactor: 1.5, isMobile: true, hasTouch: true,
  });
  const p2 = await phone.newPage();
  await p2.addInitScript(() => localStorage.setItem("epiotr_intro_seen", "1"));
  await p2.goto(URL, { waitUntil: "networkidle" });
  await p2.waitForTimeout(2500);
  await shot(p2, "mobile-map.jpg");

  await browser.close();
})();
