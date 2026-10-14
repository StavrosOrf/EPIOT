// Charging sites on the map: one marker per location, drawn with the charger
// icon and a count of its charging points. Clicking a site with several points
// fans them out around the icon as port markers, each with its own popup. The
// fan is laid out from the site's own screen position, so the ports always sit
// on the charger they belong to.

// Where each charger comes from, as shown in its popup
const SOURCE_LABELS = {
  pilot: "Amsterdam pilot dataset",
  ndw: "NDW DOT-NL open data",
  bnetza: "Bundesnetzagentur Ladesäulenregister",
  osm: "© OpenStreetMap contributors",
  bfe: "Swiss Federal Office of Energy (ich-tanke-strom.ch)",
  irve: "Base nationale des IRVE (data.gouv.fr)",
  digitraffic: "Fintraffic Digitraffic AFIR",
};

const FAST_KW = 50;
const POPUP_OPTIONS = {
  className: "cp-popup-wrap",
  maxWidth: 280,
  // Keep the card clear of the floating app bar
  autoPanPaddingTopLeft: L.point(24, 110),
};

const escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const isFast = (point) => String(point.type).toLowerCase() === "fast" || Number(point.power) >= FAST_KW;
const powerLabel = (point) =>
  Number(point.power) > 0 ? `${Math.round(Number(point.power) * 10) / 10} kW` : "Power unknown";

// Popup card for one charging point; every value comes from open data, so escape it all
export function chargerPopupHtml(props, { index, total } = {}) {
  const fast = String(props.type).toLowerCase() === "fast";
  const place = [props.city, props.country].filter(Boolean).join(", ");
  const position = total > 1 ? `<span class="cp-popup__port">Point ${index + 1} of ${total}</span>` : "";
  return `
    <div class="cp-popup">
      <div class="cp-popup__tags">
        <span class="cp-popup__tag ${fast ? "cp-popup__tag--fast" : ""}">${fast ? "DC fast" : "AC"}</span>
        ${position}
        <span class="cp-popup__power">${escapeHtml(powerLabel(props))}</span>
      </div>
      <div class="cp-popup__title">${escapeHtml(props.name || "Charging point")}</div>
      ${place ? `<div class="cp-popup__place">${escapeHtml(place)}</div>` : ""}
      <dl class="cp-popup__facts">
        <dt>Operator</dt><dd>${escapeHtml(props.operator || "Unknown")}</dd>
      </dl>
      <div class="cp-popup__source">${escapeHtml(SOURCE_LABELS[props.source] || SOURCE_LABELS.pilot)}</div>
    </div>`;
}

function siteIcon(points, iconUrl) {
  const count = points.length;
  const fast = points.some(isFast);
  return L.divIcon({
    html: `<img src="${iconUrl}" alt="" />${count > 1 ? `<span class="charger-site__count">${count}</span>` : ""}`,
    className: `charger-site${fast ? " charger-site--fast" : ""}`,
    iconSize: L.point(28, 28),
    iconAnchor: L.point(14, 26),
    popupAnchor: L.point(0, -24),
  });
}

function portIcon(point) {
  return L.divIcon({
    html: `<span class="charger-port__dot"><i class="fa fa-plug" aria-hidden="true"></i></span>`,
    className: `charger-port${isFast(point) ? " charger-port--fast" : ""}`,
    iconSize: L.point(26, 26),
    iconAnchor: L.point(13, 13),
    popupAnchor: L.point(0, -12),
  });
}

const siteKey = ([lon, lat]) => `${lat.toFixed(6)},${lon.toFixed(6)}`;

export function createSiteLayer(map, layer, iconUrl) {
  const sites = new Map(); // coordinates -> site marker
  let fan = null; // { site, group, ports }

  function closeFan() {
    if (!fan) return;
    map.removeLayer(fan.group);
    fan.site.getElement()?.classList.remove("charger-site--open");
    fan = null;
  }

  // Ports on rings around the middle of the charger icon, in screen pixels;
  // large hubs fill further rings 30 px apart instead of one huge circle
  function portOffsets(count) {
    const offsets = [];
    for (let radius = 38; offsets.length < count; radius += 30) {
      const capacity = Math.floor((2 * Math.PI * radius) / 30);
      const onRing = Math.min(capacity, count - offsets.length);
      for (let i = 0; i < onRing; i++) {
        const angle = -Math.PI / 2 + (2 * Math.PI * i) / onRing;
        offsets.push(L.point(radius * Math.cos(angle), radius * Math.sin(angle)));
      }
    }
    return offsets;
  }

  function openFan(site, focusId = null) {
    closeFan();
    const points = site.options.points;
    const hub = map.latLngToLayerPoint(site.getLatLng()).subtract(L.point(0, 13));
    const offsets = portOffsets(points.length);
    const group = L.layerGroup();
    const ports = points.map((point, i) => {
      const at = map.layerPointToLatLng(hub.add(offsets[i]));
      L.polyline([map.layerPointToLatLng(hub), at], {
        className: "charger-port-leg",
        interactive: false,
      }).addTo(group);
      const port = L.marker(at, {
        icon: portIcon(point),
        title: `${powerLabel(point)} · point ${point.id}`,
        riseOnHover: true,
        zIndexOffset: 1000,
        id: point.id,
      });
      port.bindPopup(() => chargerPopupHtml(point, { index: i, total: points.length }), POPUP_OPTIONS);
      port.on("popupopen", () => port.getElement()?.classList.add("charger-port--active"));
      port.on("popupclose", () => port.getElement()?.classList.remove("charger-port--active"));
      return port.addTo(group);
    });
    group.addTo(map);
    site.getElement()?.classList.add("charger-site--open");
    fan = { site, group, ports };
    return ports.find((port) => port.options.id == focusId) || null;
  }

  // Ports are placed in screen space, so a new zoom level needs a new layout
  map.on("zoomstart", closeFan);
  map.on("click", closeFan);
  layer.on("remove", closeFan);

  function siteMarker(feature) {
    const points = [feature.properties];
    const site = L.marker([feature.geometry.coordinates[1], feature.geometry.coordinates[0]], {
      icon: siteIcon(points, iconUrl),
      points,
      riseOnHover: true,
    });
    site.on("click", (event) => {
      L.DomEvent.stopPropagation(event);
      if (site.options.points.length === 1) return; // its own popup opens
      if (fan?.site === site) closeFan();
      else openFan(site);
    });
    return site;
  }

  // New features become new sites; points of a known site join it
  function add(features) {
    const created = new Set();
    const grown = new Set();
    for (const feature of features) {
      const key = siteKey(feature.geometry.coordinates);
      const site = sites.get(key);
      if (!site) {
        const marker = siteMarker(feature);
        sites.set(key, marker);
        created.add(marker);
      } else if (!site.options.points.some((p) => p.id === feature.properties.id)) {
        site.options.points.push(feature.properties);
        if (!created.has(site)) grown.add(site);
      }
    }
    for (const site of created) {
      if (site.options.points.length > 1) site.setIcon(siteIcon(site.options.points, iconUrl));
      syncPopup(site);
    }
    for (const site of grown) {
      site.setIcon(siteIcon(site.options.points, iconUrl));
      syncPopup(site);
      layer.refreshClusters?.(site);
    }
    if (layer.addLayers) layer.addLayers([...created]);
    else created.forEach((marker) => layer.addLayer(marker));
  }

  // A single-point site opens its card directly; a multi-point site fans out
  function syncPopup(site) {
    const points = site.options.points;
    if (points.length === 1 && !site.getPopup()) site.bindPopup(() => chargerPopupHtml(points[0]), POPUP_OPTIONS);
    if (points.length > 1 && site.getPopup()) site.unbindPopup();
  }

  return { add, closeFan };
}
