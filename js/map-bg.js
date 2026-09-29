// =========================================================================
// Map scroll parallax
// =========================================================================

// .map-bg pins the map scroll behind the page (dashboard.css). Pan it from
// its curled top to its torn bottom as the page scrolls, so the whole map
// goes by over any page's length instead of only its top ever showing: the
// page's scroll fraction moves the image that fraction of the way from its
// top at the viewport's top to its bottom at the viewport's bottom.
// It moves by transform on its own element, which the compositor handles
// alone. (Setting a custom property on body restyled the whole page and
// repainted the background every frame, which flickered on phones.)
// Its own file so the player finder at / can load it without app.js
// (build_site.py); run.py's local file inlines it with the rest.
(function initMapParallax() {
  const bg = document.querySelector(".map-bg");
  if (!bg) return;

  let queued = false;
  function update() {
    queued = false;
    const root = document.documentElement;
    // clientHeight, not innerHeight: it holds still while a phone's address
    // bar slides in and out, so the image doesn't jump mid-scroll.
    const view = root.clientHeight;
    const range = root.scrollHeight - view;
    const p = range > 0 ? Math.min(1, Math.max(0, scrollY / range)) : 0;
    const travel = Math.max(0, bg.offsetHeight - view);
    bg.style.transform = `translate3d(-50%, ${(-p * travel).toFixed(1)}px, 0)`;
  }
  function queue() {
    if (!queued) { queued = true; requestAnimationFrame(update); }
  }
  addEventListener("scroll", queue, { passive: true });
  addEventListener("resize", queue);
  // Tab switches and filter changes change the page's height without scrolling.
  new ResizeObserver(queue).observe(document.body);
  update();
})();
