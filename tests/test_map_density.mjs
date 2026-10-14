import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../static/scripts/map_density.js", import.meta.url), "utf8");
const { createDensityLoader } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const response = cells => ({ ok: true, json: async () => ({ cells }) });

function fixture(request, options = {}) {
  const counters = { created: 0, added: 0, removed: 0, yields: 0 };
  const map = { zoom: 11, west: 4, getZoom() { return this.zoom; },
    getBounds() { return { getWest: () => this.west, getEast: () => this.west+1, getSouth: () => 52, getNorth: () => 53 }; },
    flyTo() {} };
  const layer = { items: new Set(), addLayers(items) { counters.added += items.length; items.forEach(item => this.items.add(item)); },
    removeLayers(items) { counters.removed += items.length; items.forEach(item => this.items.delete(item)); } };
  const load = createDensityLoader({ fetch: request, icon: () => ({}),
    marker: (position, options) => { counters.created++; return { position, options, on() {} }; },
    yieldFrame: async () => { counters.yields++; }, ...options });
  return { load: () => load(map, layer), map, layer, counters };
}

test("returning to a viewport reuses data and markers; panning only changes new cells", async () => {
  let calls = 0;
  const a = [52.2, 4.2, 5, 1, 2], b = [52.3, 4.3, 3, 0, 1], c = [52.4, 4.4, 4, 2, 1];
  const f = fixture(async () => response(++calls === 1 ? [a,b] : [b,c]));
  await f.load(); const original = [...f.layer.items][1];
  await f.load();
  assert.equal(calls, 1); assert.equal(f.counters.created, 2);
  f.map.west = 4.1; await f.load();
  assert.ok(f.layer.items.has(original)); assert.equal(f.counters.created, 3); assert.equal(f.counters.removed, 1);
  f.map.west = 4; await f.load();
  assert.equal(calls, 2); assert.equal(f.layer.items.size, 2);
});

test("identical concurrent requests are coalesced, even before the first reply", async () => {
  let resolve, calls = 0;
  const f = fixture(() => { calls++; return new Promise(r => { resolve = r; }); });
  const first = f.load(), second = f.load();
  assert.equal(first, second); assert.equal(calls, 1);
  resolve(response([[52,4,1,0,1]])); await first;
  assert.equal(f.counters.created, 1);
});

test("late same-zoom pan responses and detail transitions cannot redraw the map", async () => {
  const replies = [], signals = [];
  const f = fixture((_url, { signal }) => { signals.push(signal); return new Promise(resolve => replies.push(resolve)); });
  const first = f.load(); f.map.west = 5; const second = f.load();
  assert.ok(signals[0].aborted);
  replies[1](response([[52,5,2,0,1]])); await second;
  replies[0](response([[52,4,1,0,1]])); await first;
  assert.deepEqual([...f.layer.items][0].position, [52,5]);
  f.map.west = 6; const third = f.load(); f.map.zoom = 12; await f.load();
  assert.ok(signals[2].aborted);
  replies[2](response([[52,6,1,0,1]])); await third;
  assert.equal(f.counters.created, 1);
});

test("failed fetches retry; cache expires and evicts least recently used viewports", async () => {
  let calls = 0, time = 0;
  const f = fixture(async () => { calls++; if (calls === 1) throw Object.assign(new Error(), { name: "AbortError" });
    return response([[52,4,calls,0,1]]); }, { now: () => time, ttl: 30, limit: 2 });
  await f.load(); await f.load(); assert.equal(calls, 2);
  time = 31; await f.load(); assert.equal(calls, 3);
  f.map.west = 5; await f.load(); f.map.west = 6; await f.load(); f.map.west = 4; await f.load();
  assert.equal(calls, 6);
});

test("large first draws yield between bounded batches and retain coincident cells", async () => {
  const cells = Array.from({ length: 601 }, () => [52,4,1,0,1]);
  const f = fixture(async () => response(cells));
  await f.load(); assert.equal(f.counters.yields, 3); assert.equal(f.layer.items.size, 601);
  await f.load(); assert.equal(f.counters.created, 601);
});
