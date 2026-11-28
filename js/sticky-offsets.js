// =========================================================================
// Sticky offsets
// =========================================================================
// The filter bar clears the sticky page tabs. Other sticky controls clear
// the height of the tabs and, when it is sticky, the filter bar.

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
