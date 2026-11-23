// =========================================================================
// Sticky offsets
// =========================================================================
// The shared filter bar sticks to the top of the viewport, so everything else
// that sticks (the Run Detail jump bar, the run list, table headings) has to
// sit below it. This publishes the bar's height as --filter-bar-h on <html>,
// counting it only while the bar is actually sticky: on a phone an opened bar
// scrolls away with the page, and then nothing needs to clear it.

function syncFilterBarOffset() {
  const bar = document.getElementById("shared-filter-bar");
  if (!bar) return;
  const stuck = getComputedStyle(bar).position === "sticky";
  const h = stuck ? Math.ceil(bar.getBoundingClientRect().height) : 0;
  document.documentElement.style.setProperty("--filter-bar-h", h + "px");
}

(function watchFilterBarOffset() {
  const bar = document.getElementById("shared-filter-bar");
  if (!bar) return;
  if (typeof ResizeObserver === "function") new ResizeObserver(syncFilterBarOffset).observe(bar);
  window.addEventListener("resize", syncFilterBarOffset);
  syncFilterBarOffset();
})();
