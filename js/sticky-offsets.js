// =========================================================================
// Sticky offsets
// =========================================================================
// The filter bar clears the sticky page tabs on desktop. Other sticky controls
// clear the combined height of the tabs and filter bar. On a phone, only the
// collapsed filter bar sticks.

function syncFilterBarOffset() {
  const bar = document.getElementById("shared-filter-bar");
  if (!bar) return;
  const tabs = document.querySelector(".page-tabs");
  const tabsHeight = tabs && getComputedStyle(tabs).position === "sticky"
    ? Math.ceil(tabs.getBoundingClientRect().height) : 0;
  const barHeight = getComputedStyle(bar).position === "sticky"
    ? Math.ceil(bar.getBoundingClientRect().height) : 0;
  document.documentElement.style.setProperty("--page-tabs-h", `${tabsHeight}px`);
  document.documentElement.style.setProperty("--filter-bar-h", `${tabsHeight + barHeight}px`);
}

(function watchFilterBarOffset() {
  const bar = document.getElementById("shared-filter-bar");
  if (!bar) return;
  if (typeof ResizeObserver === "function") {
    const ro = new ResizeObserver(syncFilterBarOffset);
    ro.observe(bar);
    const tabs = document.querySelector(".page-tabs");
    if (tabs) ro.observe(tabs);
  }
  window.addEventListener("resize", syncFilterBarOffset);
  syncFilterBarOffset();
})();
