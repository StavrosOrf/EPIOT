// Location search: suggested places when the box is empty and type-ahead
// results while typing, in an accessible combobox dropdown.
//
// Results come from PDOK Locatieserver (Dutch government geocoder, built for
// suggest-as-you-type). It is limited to the municipalities the charger and
// grid data cover, so a result never lands on an empty map.

const SUGGEST_URL = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/suggest";
const SEARCH_MUNICIPALITIES = [
  "Amsterdam", "Amstelveen", "Diemen", "Ouder-Amstel",
  "Zaanstad", "Landsmeer", "Oostzaan", "Haarlemmermeer",
];
const MIN_CHARS = 2;
const DEBOUNCE_MS = 150;

const SUGGESTED_PLACES = [
  { name: "Centrum", meta: "City centre · Dam Square", lat: 52.3731, lon: 4.8926 },
  { name: "Zuidas", meta: "Business district", lat: 52.3383, lon: 4.8728 },
  { name: "Amsterdam Oost", meta: "Oosterpark area", lat: 52.36, lon: 4.918 },
  { name: "Amsterdam West", meta: "De Baarsjes · Westerpark", lat: 52.374, lon: 4.865 },
  { name: "Amsterdam Noord", meta: "Buikslotermeer", lat: 52.3985, lon: 4.9255 },
  { name: "Nieuw-West", meta: "Osdorp", lat: 52.359, lon: 4.8 },
  { name: "Zuidoost", meta: "Bijlmer · ArenA", lat: 52.3125, lon: 4.947 },
  { name: "IJburg", meta: "Residential island district", lat: 52.354, lon: 5.0 },
].map((p) => ({ ...p, icon: "fa-star-o", zoom: 16 }));

// PDOK result types: label, icon and the zoom level to show them at
const RESULT_TYPES = {
  adres: { label: "Address", icon: "fa-home", zoom: 16 },
  weg: { label: "Street", icon: "fa-road", zoom: 16 },
  postcode: { label: "Postcode", icon: "fa-envelope-o", zoom: 16 },
  buurt: { label: "Neighbourhood", icon: "fa-map-o", zoom: 16 },
  wijk: { label: "District", icon: "fa-map-o", zoom: 15 },
  woonplaats: { label: "Town", icon: "fa-building-o", zoom: 14 },
};

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
    return `
      <div class="search__option" role="option" id="search-opt-${index}" data-index="${index}" aria-selected="false">
        <span class="search__option-icon" aria-hidden="true"><i class="fa ${place.icon}"></i></span>
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
    menu.innerHTML = html;
    activeIndex = -1;
    input.removeAttribute("aria-activedescendant");
    open();
  }

  function matchingSuggestions(query) {
    const q = query.toLowerCase();
    return SUGGESTED_PLACES.filter(
      (p) => p.name.toLowerCase().includes(q) || p.meta.toLowerCase().includes(q)
    );
  }

  async function fetchPlaces(query) {
    if (cache.has(query)) return cache.get(query);
    controller?.abort();
    controller = new AbortController();
    const center = map.getCenter();
    // Postcode rows repeat the addresses, so only ask for them when the
    // query looks like a postcode
    const types = ["adres", "weg", "buurt", "wijk", "woonplaats"];
    if (/^\d{4}/.test(query)) types.push("postcode");
    const params = new URLSearchParams({
      q: query,
      rows: "7",
      lat: center.lat.toFixed(5),
      lon: center.lng.toFixed(5),
      fl: "type,weergavenaam,centroide_ll,gemeentenaam,woonplaatsnaam,wijknaam,buurtnaam",
    });
    params.append("fq", `gemeentenaam:(${SEARCH_MUNICIPALITIES.map((m) => `"${m}"`).join(" OR ")})`);
    params.append("fq", `type:(${types.join(" OR ")})`);
    const response = await fetch(`${SUGGEST_URL}?${params}`, { signal: controller.signal });
    if (!response.ok) throw new Error(`PDOK ${response.status}`);
    const data = await response.json();
    const places = (data.response?.docs || []).filter((d) => d.centroide_ll).map(toPlace);
    cache.set(query, places);
    return places;
  }

  function update() {
    const query = input.value.trim();
    if (clearBtn) clearBtn.hidden = !input.value;
    clearTimeout(debounceTimer);

    if (!query) {
      render([{ title: "Suggested places", places: SUGGESTED_PLACES }], "");
      return;
    }

    const suggested = matchingSuggestions(query);
    if (query.length < MIN_CHARS) {
      render([{ title: "Suggested places", places: suggested }], query,
        suggested.length ? "" : "Keep typing to search streets, addresses and neighbourhoods…");
      return;
    }

    const cached = cache.get(query);
    if (cached) {
      showResults(query, suggested, cached);
      return;
    }

    // Keep the current list while typing; only show a spinner if it is empty
    if (!isOpen() || !options.length) {
      render([{ title: "Suggested places", places: suggested }], query,
        `<span class="search__spinner" aria-hidden="true"></span>Searching…`);
    }

    debounceTimer = setTimeout(async () => {
      try {
        const places = await fetchPlaces(query);
        if (input.value.trim() !== query) return; // a newer query took over
        showResults(query, suggested, places);
      } catch (err) {
        if (err.name === "AbortError") return;
        render([{ title: "Suggested places", places: suggested }], query,
          "Place search is unavailable right now.");
        onError?.("Location search is unavailable right now");
      }
    }, DEBOUNCE_MS);
  }

  function showResults(query, suggested, places) {
    const empty = !suggested.length && !places.length;
    render(
      [
        { title: "Suggested places", places: suggested },
        { title: "Streets, addresses & areas", places },
      ],
      query,
      empty ? `No places found for “${escapeHtml(query)}” in the Amsterdam area.` : ""
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
