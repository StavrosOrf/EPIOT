// Render each Mermaid diagram at its natural size, shrinking (never
// enlarging) it to fit the content column. sphinxcontrib-mermaid stretches
// every SVG to 100% width, which blows small diagrams up.
(function () {
  function fit(svg) {
    const vb = svg.viewBox && svg.viewBox.baseVal;
    if (!vb || !vb.width) return;
    svg.style.setProperty("width", vb.width + "px", "important");
    svg.style.setProperty("height", "auto", "important");
    svg.style.setProperty("display", "block");
    svg.style.setProperty("margin", "0 auto");
  }
  const observer = new MutationObserver(() => {
    document.querySelectorAll("pre.mermaid > svg, div.mermaid > svg").forEach(fit);
  });
  document.addEventListener("DOMContentLoaded", () => {
    observer.observe(document.body, { childList: true, subtree: true });
  });
})();
