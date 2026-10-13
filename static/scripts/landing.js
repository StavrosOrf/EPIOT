(function () {
  const overlay = document.getElementById("landing-overlay");
  if (!overlay) return;

  const btnClose = document.getElementById("landing-close");
  const btnContinue = document.getElementById("continue-btn");
  const dontShow = document.getElementById("dont-show-again");
  const SEEN_KEY = "epiotr_intro_seen";

  // public API
  window.EPIOT = window.EPIOT || {};
  window.EPIOT.openLanding = () => openOverlay();
  window.EPIOT.closeLanding = () => closeOverlay();
  window.EPIOT.isLandingOpen = () => !overlay.classList.contains("hidden");

  // Decide if we should show on first load
  const urlParams = new URLSearchParams(window.location.search);
  const forceOpen = urlParams.has("landing");
  const hasSeen = localStorage.getItem(SEEN_KEY) === "1";

  if (!hasSeen || forceOpen) {
    openOverlay();
  } else {
    hideOverlay();
  }

  // Wire events
  btnClose?.addEventListener("click", closeOverlay);
  btnContinue?.addEventListener("click", closeOverlay);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !overlay.classList.contains("hidden")) closeOverlay();
  });

  // Utils
  function openOverlay() {
    overlay.classList.remove("hidden");
    overlay.setAttribute("aria-hidden", "false");
    document.body.classList.add("landing-no-scroll");
    // Focus the continue button for accessibility
    setTimeout(() => btnContinue?.focus({ preventScroll: true }), 0);
  }

  function closeOverlay() {
    if (dontShow?.checked) localStorage.setItem(SEEN_KEY, "1");
    hideOverlay();
  }

  function hideOverlay() {
    overlay.setAttribute("aria-hidden", "true");
    overlay.classList.add("hidden");
    document.body.classList.remove("landing-no-scroll");
  }
})();
