// Location search: suggested places when the box is empty and type-ahead
// results while typing, in an accessible combobox dropdown.
//
// Suggestions are every city with imported charger data (from
// /stations/coverage) plus the Amsterdam pilot area. Type-ahead uses PDOK
// Locatieserver (Dutch government geocoder) for the Netherlands and Photon
// (OpenStreetMap) for the other covered areas, so a result never lands on an
// empty map.

const PDOK_URL = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/suggest";
const PHOTON_URL = "https://photon.komoot.io/api/";
const MIN_CHARS = 2;
const DEBOUNCE_MS = 200;

// Countries covered nationwide; elsewhere only the listed city boxes are
const NATIONWIDE = new Set(["NL", "DE", "CH", "FR", "FI"]);
const NL_BOX = [50.7, 3.3, 53.6, 7.3]; // south, west, north, east

const PILOT_PLACES = [
  { name: "Centrum", meta: "Amsterdam · Dam Square", lat: 52.3731, lon: 4.8926 },
  { name: "Zuidas", meta: "Amsterdam · Business district", lat: 52.3383, lon: 4.8728 },
  { name: "Amsterdam Oost", meta: "Amsterdam · Oosterpark area", lat: 52.36, lon: 4.918 },
  { name: "Amsterdam West", meta: "Amsterdam · De Baarsjes, Westerpark", lat: 52.374, lon: 4.865 },
  { name: "Amsterdam Noord", meta: "Amsterdam · Buikslotermeer", lat: 52.3985, lon: 4.9255 },
  { name: "Nieuw-West", meta: "Amsterdam · Osdorp", lat: 52.359, lon: 4.8 },
  { name: "Zuidoost", meta: "Amsterdam · Bijlmer, ArenA", lat: 52.3125, lon: 4.947 },
  { name: "IJburg", meta: "Amsterdam · Residential island district", lat: 52.354, lon: 5.0 },
].map((p) => ({ ...p, icon: "fa-star-o", zoom: 16 }));

// Used until /stations/coverage answers, or if it is unavailable
const FALLBACK_CITIES = [
  ["Amsterdam", "NL", 52.3731, 4.8926], ["Rotterdam", "NL", 51.9225, 4.4792],
  ["The Hague", "NL", 52.0705, 4.3007], ["Utrecht", "NL", 52.0907, 5.1214],
  ["Berlin", "DE", 52.52, 13.405, 12], ["Munich", "DE", 48.1372, 11.5756],
  ["Lisbon", "PT", 38.7223, -9.1393], ["Porto", "PT", 41.1579, -8.6291],
  ["Milan", "IT", 45.4642, 9.19], ["Rome", "IT", 41.9028, 12.4964, 12],
  ["London", "GB", 51.5072, -0.1276, 12], ["Zurich", "CH", 47.3769, 8.5417],
  ["Geneva", "CH", 46.2044, 6.1432], ["Paris", "FR", 48.8566, 2.3522, 12],
  ["Lyon", "FR", 45.764, 4.8357], ["Helsinki", "FI", 60.1699, 24.9384, 12],
].map(([name, country, lat, lon, zoom = 13]) => ({ name, country, lat, lon, zoom }));

const COUNTRY_NAMES = {
  NL: "Netherlands", DE: "Germany", PT: "Portugal", IT: "Italy", GB: "United Kingdom",
  CH: "Switzerland", FR: "France", FI: "Finland",
};

function cityPlace(region) {
  const sites = Number(region.sites);
  const count = sites > 0 ? ` · ${sites.toLocaleString("en-GB")} charging sites` : "";
  return {
    name: region.name,
    meta: `${region.country_name || COUNTRY_NAMES[region.country] || region.country}${count}`,
    lat: region.lat,
    lon: region.lon,
    zoom: region.zoom || 13,
    badge: region.country,
    bbox: region.bbox,
  };
}

// PDOK result types: label, icon and the zoom level to show them at
const RESULT_TYPES = {
  adres: { label: "Address", icon: "fa-home", zoom: 16 },
  weg: { label: "Street", icon: "fa-road", zoom: 16 },
  postcode: { label: "Postcode", icon: "fa-envelope-o", zoom: 16 },
  buurt: { label: "Neighbourhood", icon: "fa-map-o", zoom: 16 },
  wijk: { label: "District", icon: "fa-map-o", zoom: 15 },
  woonplaats: { label: "Town", icon: "fa-building-o", zoom: 13 },
};

// Photon (OpenStreetMap) result types, same shape as above
const PHOTON_TYPES = {
  house: { label: "Address", icon: "fa-home", zoom: 16 },
  street: { label: "Street", icon: "fa-road", zoom: 16 },
  locality: { label: "Area", icon: "fa-map-o", zoom: 15 },
  district: { label: "District", icon: "fa-map-o", zoom: 15 },
  city: { label: "City", icon: "fa-building-o", zoom: 13 },
};

const inBox = (lat, lon, [south, west, north, east]) =>
  lat >= south && lat <= north && lon >= west && lon <= east;

const escapeHtml = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// Escape the text and wrap every typed word in <mark>
function highlight(text, query) {
  const words = query.trim().split(/\s+/).filter(Boolean)
    .map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!words.length) return escapeHtml(text);
  const re = new RegExp(words.join("|"), "gi");
  let html = "";
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (!m[0]) continue;
    html += escapeHtml(text.slice(last, m.index)) + `<mark>${escapeHtml(m[0])}</mark>`;
    last = m.index + m[0].length;
  }
  return html + escapeHtml(text.slice(last));
}

// PDOK document -> place
function toPlace(doc) {
  const kind = RESULT_TYPES[doc.type] || { label: "Place", icon: "fa-map-marker", zoom: 16 };
  const [, lon, lat] = doc.centroide_ll.match(/POINT\(([-\d.]+) ([-\d.]+)\)/).map(Number);
  let name;
  let where;
  if (doc.type === "wijk") [name, where] = [doc.wijknaam, doc.gemeentenaam];
  else if (doc.type === "buurt") [name, where] = [doc.buurtnaam, doc.gemeentenaam];
  else if (doc.type === "woonplaats") [name, where] = [doc.woonplaatsnaam, doc.gemeentenaam];
  else {
    // "Kalverstraat 1, 1012NX Amsterdam" -> name and location
    const i = doc.weergavenaam.indexOf(", ");
    [name, where] = i < 0 ? [doc.weergavenaam, ""] : [doc.weergavenaam.slice(0, i), doc.weergavenaam.slice(i + 2)];
  }
  const meta = where && where !== name ? `${kind.label} · ${where}` : kind.label;
  return { name, meta, lat, lon, icon: kind.icon, zoom: kind.zoom };
}

// Photon feature -> place
function photonPlace(feature) {
  const p = feature.properties || {};
  const kind = PHOTON_TYPES[p.type] || { label: "Place", icon: "fa-map-marker", zoom: 16 };
  const [lon, lat] = feature.geometry.coordinates;
  const name = p.type === "house" ? [p.street, p.housenumber].filter(Boolean).join(" ") || p.name : p.name || p.street;
  const where = [p.type === "city" ? null : p.city || p.county, COUNTRY_NAMES[p.countrycode] || p.country]
    .filter(Boolean).join(", ");
  return { name, meta: where ? `${kind.label} · ${where}` : kind.label, lat, lon, icon: kind.icon, zoom: kind.zoom };
}

export function initLocationSearch(map, { onError } = {}) {
  const form = document.getElementById("input-container");
  const input = document.getElementById("location-input");
  const menu = document.getElementById("search-results");
  const clearBtn = document.getElementById("search-clear");
  if (!form || !input || !menu) return;

  let options = []; // places currently listed, in display order
  let activeIndex = -1;
  let debounceTimer = null;
  let controller = null;
  let selectWhenLoaded = false; // Enter was pressed while results were loading
  let pin = null;
  const cache = new Map();

  // Cities with imported charger data; replaced by live counts when they load
  let cities = FALLBACK_CITIES.map(cityPlace);
  fetch("/stations/coverage")
    .then((response) => (response.ok ? response.json() : Promise.reject(response.status)))
    .then((data) => {
      if (data.regions?.length) cities = data.regions.map(cityPlace);
      if (isOpen() && !input.value.trim()) update();
    })
    .catch(() => {});

  const isOpen = () => !menu.hidden;

  function open() {
    menu.hidden = false;
    input.setAttribute("aria-expanded", "true");
  }

  function close() {
    menu.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    activeIndex = -1;
    selectWhenLoaded = false;
  }

  function setActive(index) {
    const items = menu.querySelectorAll(".search__option");
    items.forEach((el) => el.setAttribute("aria-selected", "false"));
    activeIndex = index;
    const el = items[index];
    if (!el) {
      input.removeAttribute("aria-activedescendant");
      return;
    }
    el.setAttribute("aria-selected", "true");
    input.setAttribute("aria-activedescendant", el.id);
    el.scrollIntoView({ block: "nearest" });
  }

  function optionHtml(place, index, query) {
    const icon = place.badge
      ? `<span class="search__option-icon search__option-icon--badge" aria-hidden="true">${escapeHtml(place.badge)}</span>`
      : `<span class="search__option-icon" aria-hidden="true"><i class="fa ${place.icon}"></i></span>`;
    return `
      <div class="search__option" role="option" id="search-opt-${index}" data-index="${index}" aria-selected="false">
        ${icon}
        <span class="search__option-text">
          <span class="search__option-name">${highlight(place.name, query)}</span>
          ${place.meta ? `<span class="search__option-meta">${escapeHtml(place.meta)}</span>` : ""}
        </span>
      </div>`;
  }

  // sections: [{ title, places }]; status: optional (trusted) HTML row
  function render(sections, query, status = "") {
    options = [];
    let html = "";
    for (const { title, places } of sections) {
      if (!places.length) continue;
      html += `<div class="search__group" role="presentation">${escapeHtml(title)}</div>`;
      for (const place of places) {
        html += optionHtml(place, options.length, query);
        options.push(place);
      }
    }
    if (status) html += `<div class="search__status" role="presentation">${status}</div>`;
    if (!query) {
      html += `<div class="search__footer" role="presentation">Charger data: NDW · Bundesnetzagentur · BFE · data.gouv.fr · Fintraffic · OpenStreetMap contributors</div>`;
    }
    menu.innerHTML = html;
    activeIndex = -1;
    input.removeAttribute("aria-activedescendant");
    open();
  }

  const matches = (places, q) =>
    places.filter((p) => p.name.toLowerCase().includes(q) || p.meta.toLowerCase().includes(q));

  function suggestionSections(query) {
    const q = query.toLowerCase();
    return [
      { title: "Cities with charger data", places: q ? matches(cities, q) : cities },
      { title: "Amsterdam pilot area", places: q ? matches(PILOT_PLACES, q) : PILOT_PLACES },
    ];
  }

  // A Photon result is only useful where charger data was imported
  function covered(feature) {
    const code = feature.properties?.countrycode;
    const [lon, lat] = feature.geometry.coordinates;
    if (code === "NL") return false; // PDOK answers for the Netherlands
    return NATIONWIDE.has(code) || cities.some((c) => c.bbox && inBox(lat, lon, c.bbox));
  }

  async function fetchPdok(query, signal, center) {
    // Postcode rows repeat the addresses, so only ask for them when the
    // query looks like a postcode
    const types = ["adres", "weg", "buurt", "wijk", "woonplaats"];
    if (/^\d{4}/.test(query)) types.push("postcode");
    const params = new URLSearchParams({
      q: query,
      rows: "6",
      lat: center.lat.toFixed(5),
      lon: center.lng.toFixed(5),
      fl: "type,weergavenaam,centroide_ll,gemeentenaam,woonplaatsnaam,wijknaam,buurtnaam",
    });
    params.append("fq", `type:(${types.join(" OR ")})`);
    const response = await fetch(`${PDOK_URL}?${params}`, { signal });
    if (!response.ok) throw new Error(`PDOK ${response.status}`);
    const data = await response.json();
    return (data.response?.docs || []).filter((d) => d.centroide_ll).map(toPlace);
  }

  async function fetchPhoton(query, signal, center) {
    const params = new URLSearchParams({ q: query, limit: "15", lang: "en" });
    // Bias towards the view only abroad: over the Netherlands it would rank
    // Dutch places first, which PDOK already covers
    if (!inBox(center.lat, center.lng, NL_BOX)) {
      params.set("lat", center.lat.toFixed(4));
      params.set("lon", center.lng.toFixed(4));
    }
    const response = await fetch(`${PHOTON_URL}?${params}`, { signal });
    if (!response.ok) throw new Error(`Photon ${response.status}`);
    const data = await response.json();
    return (data.features || []).filter((f) => f.geometry?.coordinates && covered(f)).slice(0, 6).map(photonPlace);
  }

  // Both geocoders run together; one failing still shows the other's results
  async function fetchPlaces(query) {
    if (cache.has(query)) return cache.get(query);
    controller?.abort();
    controller = new AbortController();
    const center = map.getCenter();
    const [dutch, european] = await Promise.allSettled([
      fetchPdok(query, controller.signal, center),
      fetchPhoton(query, controller.signal, center),
    ]);
    const failures = [dutch, european].filter((r) => r.status === "rejected").map((r) => r.reason);
    if (failures.some((e) => e?.name === "AbortError")) throw failures.find((e) => e?.name === "AbortError");
    if (failures.length === 2) throw failures[0];
    const nl = dutch.value || [];
    const eu = european.value || [];
    // Results from the country in view first
    const places = inBox(center.lat, center.lng, NL_BOX) ? [...nl, ...eu] : [...eu, ...nl];
    cache.set(query, places);
    return places;
  }

  function update() {
    const query = input.value.trim();
    if (clearBtn) clearBtn.hidden = !input.value;
    clearTimeout(debounceTimer);

    if (!query) {
      render(suggestionSections(""), "");
      return;
    }

    const suggested = suggestionSections(query);
    const anySuggested = suggested.some((section) => section.places.length);
    if (query.length < MIN_CHARS) {
      render(suggested, query,
        anySuggested ? "" : "Keep typing to search cities, streets and addresses…");
      return;
    }

    const cached = cache.get(query);
    if (cached) {
      showResults(query, suggested, cached);
      return;
    }

    // Keep the current list while typing; only show a spinner if it is empty
    if (!isOpen() || !options.length) {
      render(suggested, query, `<span class="search__spinner" aria-hidden="true"></span>Searching…`);
    }

    debounceTimer = setTimeout(async () => {
      try {
        const places = await fetchPlaces(query);
        if (input.value.trim() !== query) return; // a newer query took over
        showResults(query, suggested, places);
      } catch (err) {
        if (err.name === "AbortError") return;
        render(suggested, query, "Place search is unavailable right now.");
        onError?.("Location search is unavailable right now");
      }
    }, DEBOUNCE_MS);
  }

  function showResults(query, suggested, places) {
    const empty = !places.length && !suggested.some((section) => section.places.length);
    render(
      [...suggested, { title: "Streets, addresses & areas", places }],
      query,
      empty ? `No places found for “${escapeHtml(query)}” in the areas with charger data.` : ""
    );
    if (selectWhenLoaded && options.length) select(0);
  }

  function select(index) {
    const place = options[index];
    if (!place) return;
    input.value = place.name;
    if (clearBtn) clearBtn.hidden = false;
    close();
    input.blur();

    map.flyTo([place.lat, place.lon], place.zoom || 16, { duration: 0.8 });

    // Briefly mark the spot so the eye can find it after the map moves
    if (pin) map.removeLayer(pin);
    const thisPin = (pin = L.marker([place.lat, place.lon], {
      icon: L.divIcon({ className: "search-pin", html: "<span></span>", iconSize: [20, 20] }),
      interactive: false,
      keyboard: false,
    }).addTo(map));
    setTimeout(() => {
      if (pin !== thisPin) return;
      map.removeLayer(pin);
      pin = null;
    }, 4000);
  }

  input.addEventListener("focus", update);
  input.addEventListener("click", () => {
    if (!isOpen()) update();
  });
  input.addEventListener("input", () => {
    selectWhenLoaded = false;
    update();
  });

  input.addEventListener("keydown", (e) => {
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        if (!isOpen()) return update();
        if (options.length) setActive((activeIndex + 1) % options.length);
        break;
      case "ArrowUp":
        e.preventDefault();
        if (options.length) setActive(activeIndex <= 0 ? options.length - 1 : activeIndex - 1);
        break;
      case "Escape":
        // Keep the global Esc handler (draw tools, panel) out of it
        e.stopPropagation();
        if (isOpen()) close();
        else if (input.value) {
          input.value = "";
          if (clearBtn) clearBtn.hidden = true;
        } else input.blur();
        break;
      case "Tab":
        close();
        break;
    }
  });

  // Enter picks the highlighted option, or the best match, waiting for the
  // results if they are still loading
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const query = input.value.trim();
    if (!query) return;
    if (activeIndex >= 0) return select(activeIndex);
    if (query.length >= MIN_CHARS && !cache.has(query)) {
      selectWhenLoaded = true;
      if (!isOpen()) update();
      return;
    }
    if (options.length) select(0);
  });

  // mousedown keeps focus in the input so the menu does not close first
  menu.addEventListener("mousedown", (e) => e.preventDefault());
  menu.addEventListener("click", (e) => {
    const el = e.target.closest(".search__option");
    if (el) select(Number(el.dataset.index));
  });
  menu.addEventListener("mousemove", (e) => {
    const el = e.target.closest(".search__option");
    if (el && Number(el.dataset.index) !== activeIndex) setActive(Number(el.dataset.index));
  });

  clearBtn?.addEventListener("click", () => {
    input.value = "";
    clearBtn.hidden = true;
    input.focus();
    update();
  });

  document.addEventListener("mousedown", (e) => {
    if (isOpen() && !form.contains(e.target)) close();
  });
  input.addEventListener("blur", () => setTimeout(() => {
    if (document.activeElement !== input) close();
  }, 0));
}
