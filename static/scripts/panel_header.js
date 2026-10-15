// Behaviour of the analysis panel header that CSS alone cannot do: the glider
// that slides under the active tab / KPI category, and the tab list's keyboard
// model. It only watches the `active` class that script.js already toggles, so
// switching tabs stays defined in one place.

// Arrow keys move focus along a tab list; Home and End jump to its ends.
// Returns the index to focus, or -1 when the key is not a navigation key.
export function nextTabIndex(current, count, key) {
  if (!count) return -1;
  const from = current < 0 ? 0 : current;
  if (key === "ArrowRight") return (from + 1) % count;
  if (key === "ArrowLeft") return (from - 1 + count) % count;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  return -1;
}

// Offsets are relative to the group's padding box, which is also what the
// glider (the group's ::before) is positioned against, so they line up even
// when the group scrolls or its items wrap onto several rows.
export function glideTo(group, item) {
  group.style.setProperty("--glider-x", `${item.offsetLeft}px`);
  group.style.setProperty("--glider-y", `${item.offsetTop}px`);
  group.style.setProperty("--glider-w", `${item.offsetWidth}px`);
  group.style.setProperty("--glider-h", `${item.offsetHeight}px`);
}

// Keep the glider under the item that has the `active` class. The first
// placement and any placement caused by a layout change are instant; only
// switching the active item animates.
function initGlider(group, itemSelector) {
  const items = () => [...group.querySelectorAll(itemSelector)];
  let placed = false;

  function place(instant) {
    const active = items().find((item) => item.classList.contains("active"));
    // A hidden group has no geometry yet; the resize observer retries once shown
    if (!active || !active.offsetWidth) return;
    const jump = instant || !placed;
    if (jump) group.classList.remove("is-ready");
    glideTo(group, active);
    placed = true;
    if (jump) {
      void group.offsetWidth; // commit the jump before transitions come back
      requestAnimationFrame(() => group.classList.add("is-ready"));
    }
  }

  // From here the glider (zero-sized until first placed) draws the active
  // item's highlight, so the CSS fallback pill never shows beside it
  group.classList.add("has-glider");
  place(true);
  const resizes = new ResizeObserver(() => place(true));
  resizes.observe(group);
  items().forEach((item) => resizes.observe(item));
  new MutationObserver(() => place(false)).observe(group, {
    subtree: true,
    attributes: true,
    attributeFilter: ["class"],
  });
}

// WAI-ARIA tabs: one tab stop (the active tab), arrows move focus, Enter or
// Space activates. Activation is manual because each tab starts a calculation.
function initTablist(tablist, panel) {
  const tabs = () => [...tablist.querySelectorAll('[role="tab"]')];

  function sync() {
    tabs().forEach((tab) => {
      const active = tab.classList.contains("active");
      tab.tabIndex = active ? 0 : -1;
      if (active && panel) panel.setAttribute("aria-labelledby", tab.id);
    });
  }

  tablist.addEventListener("keydown", (event) => {
    const list = tabs();
    const current = list.indexOf(event.target.closest('[role="tab"]'));
    const index = nextTabIndex(current, list.length, event.key);
    if (index < 0) return;
    event.preventDefault();
    list[index].focus();
  });

  sync();
  new MutationObserver(sync).observe(tablist, {
    subtree: true,
    attributes: true,
    attributeFilter: ["class"],
  });
}

// Each control carries its own short tooltip (`title` + data-toggle). Hover
// shows it after a beat so a pointer crossing the header stays quiet. Keyboard
// focus shows it too, but only for focus-visible, so a mouse click never leaves
// one stuck on the button it just pressed.
function initHeaderTooltips(header) {
  const $ = window.jQuery;
  if (!$ || !$.fn.tooltip) return;
  $(header)
    .find('[data-toggle="tooltip"]')
    .tooltip({
      container: "body",
      // The tab strip scrolls horizontally, which Bootstrap would otherwise use
      // as the positioning boundary, flipping the tooltip on top of the tabs
      boundary: "window",
      trigger: "hover",
      delay: { show: 400, hide: 0 },
    });

  const host = (target) => target.closest('[data-toggle="tooltip"]');
  header.addEventListener("focusin", (event) => {
    const element = host(event.target);
    if (element && event.target.matches(":focus-visible")) $(element).tooltip("show");
  });
  header.addEventListener("focusout", (event) => {
    const element = host(event.target);
    if (element) $(element).tooltip("hide");
  });
}

// The Source pill's tooltip describes the source that is selected right now.
// The three explanations live on their own options, not in one shared bubble.
function initSourceTooltip(pill) {
  const select = pill.querySelector("select");
  if (!select) return;
  const sync = () => {
    const text = select.selectedOptions[0]?.title;
    if (!text) return;
    pill.setAttribute("data-original-title", text);
    window.jQuery?.(pill).tooltip("hide");
  };
  select.addEventListener("change", sync);
  sync();
}

export function initPanelHeader() {
  const header = document.querySelector(".panel__header");
  const tablist = document.querySelector(".panel__header .tabs");
  const kpiOptions = document.querySelector(".panel__header .kpi-options");
  const panel = document.getElementById("analysis-view");
  if (tablist) {
    initGlider(tablist, ".tab");
    initTablist(tablist, panel);
  }
  if (kpiOptions) initGlider(kpiOptions, ".kpi-option");
  if (header) {
    initHeaderTooltips(header);
    const pill = header.querySelector(".source-pill");
    if (pill) initSourceTooltip(pill);
  }
}
