// Browser smoke test of the running app: draw an area, analyse it, edit its card,
// switch tabs, ask for several draws. It needs a running server and Chrome:
//
//   uv run python app.py                       # in one terminal
//   npm install --no-save puppeteer-core       # once (not a project dependency)
//   node scripts/e2e_smoke.mjs                 # exits non-zero on a failed check
//
// EPIOT_URL (default http://127.0.0.1:5000/) and CHROME_PATH select the server and browser.
import { existsSync } from "node:fs";
import assert from "node:assert/strict";

const { default: puppeteer } = await import("puppeteer-core").catch(() => {
  console.error("puppeteer-core is not installed: npm install --no-save puppeteer-core");
  process.exit(2);
});

const URL = process.env.EPIOT_URL || "http://127.0.0.1:5000/";
const CHROME = process.env.CHROME_PATH || [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
].find(existsSync);
if (!CHROME) {
  console.error("Chrome not found: set CHROME_PATH");
  process.exit(2);
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const browser = await puppeteer.launch({ executablePath: CHROME, headless: "new", args: ["--no-sandbox", "--disable-gpu"],
  defaultViewport: { width: 1500, height: 950 } });
const page = await browser.newPage();
const problems = [], profileRequests = [];
page.on("console", (message) => { if (["error", "warning"].includes(message.type())) problems.push(message.text()); });
page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
page.on("response", (response) => {
  if (response.status() >= 400 && !response.url().includes("tile.openstreetmap")) problems.push(`HTTP ${response.status()} ${response.url()}`);
});
page.on("request", (request) => {
  if (request.url().includes("aggregate_load")) profileRequests.push(JSON.parse(request.postData() || "{}"));
});

const graphReady = async () => {
  await page.waitForFunction(() => document.querySelector("#graph .js-plotly-plot") && !document.querySelector("#graph .loading-container"),
    { timeout: 90000 });
  await sleep(400);
};
const cards = () => page.evaluate(() => [...document.querySelectorAll("#graph .group-card")].map((card) => ({
  name: card.querySelector(".group-card__name")?.textContent, strategy: card.querySelector("[data-field=strategy]")?.value })));
const traceNames = () => page.evaluate(() => document.querySelector("#graph .js-plotly-plot").data.map((trace) => trace.name));

try {
  await page.goto(URL, { waitUntil: "networkidle2", timeout: 90000 });
  await sleep(1200);
  await page.evaluate(() => [...document.querySelectorAll("button")].find((b) => /Continue to the app/i.test(b.textContent))?.click());
  await sleep(1000);

  // Draw a quadrilateral over the city centre
  const box = await (await page.$("#map")).boundingBox();
  await page.click("#btn-draw-polygon");
  const cx = box.x + box.width * 0.4, cy = box.y + box.height * 0.5;
  const corners = [[-150, -110], [150, -110], [170, 110], [-150, 120]];
  for (const [dx, dy] of corners) { await page.mouse.click(cx + dx, cy + dy); await sleep(200); }
  await page.mouse.click(cx + corners[0][0], cy + corners[0][1]);
  await sleep(1000);

  await page.click("#calc-button");
  await graphReady();
  assert.deepEqual(await traceNames(), ["Previous day", "Target day"], "load profile for the drawn area");
  assert.equal((await cards()).length, 1);

  await page.click("#graph .group-card button[data-action=duplicate]");
  await sleep(1500); await graphReady();
  assert.deepEqual((await cards()).map((card) => card.name), ["Area 1", "Area 1 (copy)"], "copy sits below its area");

  const before = profileRequests.length;
  await page.select("#graph .group-card:nth-child(2) select[data-field=strategy]", "alap");
  await sleep(500); await graphReady();
  assert.equal(profileRequests.length - before, 1, "a card setting refreshes that area alone");
  assert.equal(profileRequests.at(-1).strategy, "alap");
  assert.deepEqual((await cards()).map((card) => card.strategy), ["afap", "alap"]);

  await page.click("#graph .group-card:nth-child(2) button[data-action=up]");
  await sleep(800); await graphReady();
  assert.deepEqual((await cards()).map((card) => card.strategy), ["alap", "afap"], "moving keeps each area's settings");
  await page.click("#graph .group-card:nth-child(1) button[data-action=remove]");
  await sleep(800); await graphReady();
  assert.equal((await cards()).length, 1);

  await page.select("#ensemble-size", "10");
  await sleep(600); await graphReady();
  assert.ok((await traceNames()).some((name) => /90th percentile of 10 draws/.test(name || "")), "draws add a band");
  assert.equal(profileRequests.at(-1).ensemble, 10);

  await page.click("#flex-tab");
  await graphReady();
  assert.ok((await traceNames()).includes("Scheduled load"), "flexibility view");

  await page.click("#stats-tab");
  await graphReady();
  assert.ok((await traceNames()).includes("Weekdays"), "KPI view");
  assert.equal(await page.$eval("#ensemble-size", (select) => select.disabled), true, "draws do not apply to KPIs");

  assert.deepEqual(problems, [], "no console errors, page errors or failed requests");
  console.log("e2e smoke test passed");
} catch (error) {
  console.error("e2e smoke test FAILED:", error.message);
  if (problems.length) console.error("page problems:", problems);
  process.exitCode = 1;
} finally {
  await browser.close();
}
