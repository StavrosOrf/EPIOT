// Bounded viewport reuse and incremental overview drawing. Each map owns its
// request state, so an old response cannot replace a more recent pan or zoom.
const countryName = code => {
  try { return new Intl.DisplayNames(["en"], { type: "region" }).of(code) || code; } catch { return code; }
};

export function createDensityLoader({ fetch: request = globalThis.fetch, marker, icon,
  detailZoom = 12, now = Date.now, ttl = 30000, limit = 16,
  yieldFrame = () => new Promise(resolve => requestAnimationFrame(resolve)) } = {}) {
  const states = new WeakMap();

  return function load(map, layer) {
    let state = states.get(layer);
    if (!state) {
      state = { revision: 0, cache: new Map(), markers: new Map(), pending: null };
      states.set(layer, state);
    }
    const zoom = map.getZoom();
    if (zoom >= detailZoom) {
      state.revision++;
      state.pending?.controller.abort();
      state.pending = null;
      return Promise.resolve();
    }
    const bounds = map.getBounds();
    const bbox = [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()]
      .map(value => value.toFixed(4)).join(",");
    const key = `${zoom}:${bbox}`;
    if (state.pending?.key === key) return state.pending.promise;
    state.pending?.controller.abort();
    const revision = ++state.revision;
    const controller = new AbortController();
    const pending = { key, controller };
    state.pending = pending;
    pending.promise = (async () => {
      try {
        let entry = state.cache.get(key);
        if (!entry || now() - entry.time >= ttl) {
          const response = await request(`/stations/density?zoom=${zoom}&bbox=${bbox}`, { signal: controller.signal });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          entry = { data: await response.json(), time: now() };
          if (state.revision !== revision) return;
        }
        // LRU includes hits; failed or cancelled requests never become cached.
        state.cache.delete(key);
        state.cache.set(key, entry);
        while (state.cache.size > limit) state.cache.delete(state.cache.keys().next().value);
        if (state.revision !== revision || map.getZoom() !== zoom) return;
        const cells = entry.data.cells;
        const occurrences = new Map();
        const wanted = new Map(cells.map(cell => {
          // Counts belong in the key: an import that changes a cell replaces
          // its marker. Preserve even coincident rounded representatives.
          const base = `${zoom}:${cell.join(":")}`;
          const count = (occurrences.get(base) || 0) + 1;
          occurrences.set(base, count);
          return [`${base}:${count}`, cell];
        }));
        const removed = [];
        for (const [id, existing] of state.markers) {
          if (!wanted.has(id)) {
            removed.push(existing);
            state.markers.delete(id);
          }
        }
        if (removed.length) layer.removeLayers(removed);
        const added = [...wanted].filter(([id]) => !state.markers.has(id));
        // Small batches let the browser paint/respond during a large first
        // overview. Unchanged cells never recreate DOM or clustering objects.
        for (let start = 0; start < added.length; start += 200) {
          if (state.revision !== revision) return;
          const batch = added.slice(start, start + 200).map(([id, [lat, lon, points, fast, sites, country]]) => {
            const item = marker([lat, lon], {
              icon: icon(points, fast / points), points, fast,
              title: `${country ? countryName(country) + ": " : ""}${points.toLocaleString("en-GB")} charging points at ${sites.toLocaleString("en-GB")} sites` +
                (fast ? ` · ${fast.toLocaleString("en-GB")} fast` : ""),
              riseOnHover: true,
            });
            item.on("click", () => map.flyTo([lat, lon], Math.min(zoom + 3, detailZoom), { duration: 0.8 }));
            state.markers.set(id, item);
            return item;
          });
          layer.addLayers(batch);
          if (start + 200 < added.length) await yieldFrame();
        }
      } catch (error) {
        if (error.name !== "AbortError") console.error("Error fetching charger overview:", error);
      } finally {
        if (state.pending === pending) state.pending = null;
      }
    })();
    return pending.promise;
  };
}
