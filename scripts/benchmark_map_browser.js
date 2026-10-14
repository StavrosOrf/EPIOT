// Runs in an isolated real Chrome page with the application's Leaflet versions.
window.runBenchmark = async function (variant) {
  const originalFetch = window.fetch;
  let requests = 0, bytes = 0, created = 0;
  window.fetch = async (url, options) => {
    if (typeof url === "string" && url.startsWith("/stations/")) {
      requests++;
      const response = await originalFetch(`/${variant}${url}`, options);
      // Include consumption/JSON parsing as the application does.
      const text = await response.text(); bytes += new TextEncoder().encode(text).length;
      return { ok: response.ok, status: response.status, json: async () => JSON.parse(text) };
    }
    return originalFetch(url, options);
  };
  const { fetchDensity, bubbleIcon } = await import(`/${variant}/scripts/loaders.js`);
  const appScript = await (await originalFetch(`/${variant}/scripts/script.js`)).text();
  const start = appScript.indexOf("// Draw each cluster");
  const end = appScript.indexOf("var vizualizeChargers", start);
  if (start < 0 || end < 0) throw new Error("Cannot isolate application map layer configuration");
  const { densityLayer } = new Function("L", "bubbleIcon", appScript.slice(start, end)+";return {densityLayer};")(L, bubbleIcon);
  // No basemap network requests or animated zoom: isolate charger rendering.
  const map = L.map("map", { zoomControl: false, attributionControl: false, zoomAnimation: false,
    fadeAnimation: false, markerZoomAnimation: false, maxZoom: 16 }).setView([52.37,4.9],12);
  densityLayer.options.animate = false;
  densityLayer.addTo(map);
  const originalMarker = L.marker;
  L.marker = (...args) => { created++; return originalMarker(...args); };
  const frames = () => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const longTasks = [];
  const observer = new PerformanceObserver(list => longTasks.push(...list.getEntries().map(entry => ({ start: entry.startTime, duration: entry.duration }))));
  observer.observe({ type: "longtask", buffered: false });
  const results = [];
  for (const [name, zoom, center] of [
    ["First zoom out to city overview",11,[52.37,4.9]],
    ["First visit to next zoom",10,[52.37,4.9]],
    ["First country overview",7,[52.1,5.1]],
    ["First Europe overview",4,[51,10]],
    ["Return to city overview",11,[52.37,4.9]],
    ["Repeat unchanged viewport",11,[52.37,4.9]],
    ["Small pan at city overview",11,[52.37,4.93]],
  ]) {
    const before = { requests, bytes, created };
    const began = performance.now();
    map.setView(center, zoom, { animate: false });
    await fetchDensity(map, densityLayer);
    await frames();
    const elapsed = performance.now() - began;
    const markers = densityLayer.getLayers();
    const cells = markers.map(marker => [marker.getLatLng().lat, marker.getLatLng().lng,
                                        marker.options.points, marker.options.fast]).sort((a,b)=>JSON.stringify(a).localeCompare(JSON.stringify(b)));
    results.push({ name, ms: elapsed, requests: requests-before.requests, bytes: bytes-before.bytes,
      created: created-before.created, cells, markers: markers.length,
      dom_markers: document.querySelectorAll(".leaflet-marker-icon").length,
      longest_task_ms: Math.max(0, ...longTasks.filter(task => task.start >= began).map(task=>task.duration)) });
  }
  observer.disconnect();
  return results;
};
