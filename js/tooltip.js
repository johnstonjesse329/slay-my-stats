// -------------------------------------------------------------------------
// Shared floating tooltip — charts and plain table cells alike
// -------------------------------------------------------------------------
//
// Two problems, one fix. Chart.js's built-in canvas-drawn tooltip only
// tries to stay inside the chart's own plot area — it has no idea where
// the browser viewport ends, so a tooltip near the edge of a chart (e.g.
// the last point on a line chart) can render partly or fully off-screen.
// Separately, table cells across the dashboard used the native `title`
// attribute for hover detail, which renders in the browser's own slow,
// unstyled tooltip — visually inconsistent with everything else here.
//
// Both are replaced by one real DOM element, reused for both cases (a
// viewer only ever hovers a chart or a table cell, never both at once),
// positioned by whichever caller is active and clamped to the viewport so
// it can never render off-screen. Chart hovers go through
// chartTooltipHandler, wired in globally via Chart.defaults so every chart
// gets it for free — each chart's own `callbacks` (title/label/
// beforeLabel/afterLabel) are untouched and still drive the content, since
// Chart.js still runs them and builds tooltip.title/tooltip.body even with
// the canvas draw disabled. Table cells opt in with a `data-tip` attribute
// (instead of `title`) — see the delegated listeners at the bottom of this
// section.
let floatingTooltipEl = null;
function getFloatingTooltipEl() {
  if (!floatingTooltipEl) {
    floatingTooltipEl = document.createElement("div");
    floatingTooltipEl.className = "chart-tooltip";
    document.body.appendChild(floatingTooltipEl);
  }
  return floatingTooltipEl;
}

// Clamps a tooltip element's top-left corner so it stays fully inside the
// viewport. Call after setting innerHTML (and after resetting left/top to
// 0) so el.offsetWidth/offsetHeight reflect the current content.
function clampTooltipPosition(el, rawLeft, rawTop, margin = 8) {
  return {
    left: Math.min(Math.max(rawLeft, margin), Math.max(window.innerWidth  - el.offsetWidth  - margin, margin)),
    top:  Math.min(Math.max(rawTop,  margin), Math.max(window.innerHeight - el.offsetHeight - margin, margin)),
  };
}

function chartTooltipHandler({ chart, tooltip }) {
  const el = getFloatingTooltipEl();

  if (tooltip.opacity === 0) {
    el.style.opacity = 0;
    return;
  }

  const colors = tooltip.labelColors || [];
  el.innerHTML =
    (tooltip.title || []).map(t => `<div class="chart-tooltip-title">${t}</div>`).join("") +
    (tooltip.body || []).map((b, i) => {
      // "index" mode + intersect:false (used throughout so a near-zero bar/
      // point is still hoverable) means every dataset shows up in the
      // tooltip at every x position, even where a dataset's own label
      // callback returns null for "no data here" (e.g. no run reached a
      // 7th Act 1 elite). Chart.js's canvas tooltip quietly drew nothing
      // for those; a real DOM row can't just omit itself the same way
      // without leaving a swatch with nothing next to it, so fall back to
      // an explicit "no data" line instead.
      const lines = [...b.before, ...b.lines, ...b.after];
      const text = lines.length
        ? lines.join("<br>")
        : ` ${tooltip.dataPoints[i]?.dataset?.label ?? "—"}: N/A`;
      const swatch = colors[i]
        ? `<span class="chart-tooltip-swatch" style="background:${colors[i].backgroundColor};border-color:${colors[i].borderColor}"></span>`
        : "";
      return `<div class="chart-tooltip-row">${swatch}<span class="chart-tooltip-lines">${text}</span></div>`;
    }).join("");

  // Measure at the origin first so offsetWidth/offsetHeight reflect this
  // frame's content, then clamp the real position to the viewport.
  el.style.left = "0px";
  el.style.top = "0px";
  el.style.opacity = tooltip.opacity;

  const canvasRect = chart.canvas.getBoundingClientRect();
  const { left, top } = clampTooltipPosition(
    el,
    canvasRect.left + tooltip.caretX + 12,
    canvasRect.top + tooltip.caretY - el.offsetHeight / 2,
  );
  el.style.left = `${left}px`;
  el.style.top  = `${top}px`;
}

Chart.defaults.plugins.tooltip.enabled = false;
Chart.defaults.plugins.tooltip.external = chartTooltipHandler;
// Applies to every chart via defaults, same as enabled/external above — an
// instant pop reads as more responsive and matches the rest of the
// dashboard's hover tooltips (card/relic/node), which are plain CSS
// :hover with no fade.
Chart.defaults.plugins.tooltip.animation = false;

// `data-tip` replaces `title` on table cells (and a couple of other spots)
// so they get the same instant, styled, viewport-clamped tooltip as charts
// instead of the browser's native one. A literal "\n" in the tip text
// becomes a line break, matching how native title tooltips rendered
// multi-line content — every data-tip value in this file was written with
// that in mind.
function showTableTooltip(target, clientX = null, clientY = null) {
  const text = target.dataset.tip;
  if (!text) return;
  const el = getFloatingTooltipEl();
  el.innerHTML = text.split("\n").map(line => `<div>${line}</div>`).join("");
  el.style.left = "0px";
  el.style.top = "0px";
  el.style.opacity = 1;

  const rect = target.getBoundingClientRect();
  // Anchor next to the pointer when a mouse supplied one: data-tip targets can
  // be full-width blocks (section headings), where centering on the element
  // would pop the tooltip in the middle of the chart instead of under the
  // text being hovered. Without pointer coords (keyboard focus) fall back to
  // centering under the element.
  let left, top;
  if (clientX != null && clientY != null) {
    const pos = clampTooltipPosition(el, clientX + 14, clientY + 16);
    left = pos.left; top = pos.top;
  } else {
    const pos = clampTooltipPosition(
      el,
      rect.left + rect.width / 2 - el.offsetWidth / 2,
      rect.bottom + 6,
    );
    left = pos.left; top = pos.top;
  }
  el.style.left = `${left}px`;
  el.style.top  = `${top}px`;
}
function hideTableTooltip() {
  if (floatingTooltipEl) floatingTooltipEl.style.opacity = 0;
}
document.addEventListener("mouseover", e => {
  const target = e.target.closest("[data-tip]");
  if (target) showTableTooltip(target, e.clientX, e.clientY);
});
document.addEventListener("mouseout", e => {
  const target = e.target.closest("[data-tip]");
  if (target && !target.contains(e.relatedTarget)) hideTableTooltip();
});
// Keyboard parity: hover-only data-tip content is invisible to keyboard users.
// When a data-tip-bearing control gains focus (e.g. the tabindexed Personal
// Bests stat links), surface the same floating tooltip; dismiss on blur.
document.addEventListener("focusin", e => {
  const target = e.target.closest("[data-tip]");
  if (target) showTableTooltip(target);
});
document.addEventListener("focusout", e => {
  const target = e.target.closest("[data-tip]");
  if (target && !target.contains(e.relatedTarget)) hideTableTooltip();
});

// Rich-content variant of the same floating element, for callers that need
// the full card/relic tooltip markup (buildCardTooltip/buildRelicTooltip)
// rather than plain text lines. Needed anywhere that markup would otherwise
// sit inside a scrolling `.pivot-wrap` (overflow-y:auto clips an absolutely-
// positioned .card-tooltip-wrap child) -- appending to document.body instead
// sidesteps that clipping entirely, same as the chart tooltip above.
function showFloatingHtmlTooltip(target, html) {
  if (!html) return;
  const el = getFloatingTooltipEl();
  el.classList.add("chart-tooltip-rich");
  el.innerHTML = html;
  el.style.left = "0px";
  el.style.top = "0px";
  el.style.opacity = 1;

  const rect = target.getBoundingClientRect();
  const { left, top } = clampTooltipPosition(el, rect.left, rect.bottom + 6);
  el.style.left = `${left}px`;
  el.style.top  = `${top}px`;
}
function hideFloatingHtmlTooltip() {
  if (!floatingTooltipEl) return;
  floatingTooltipEl.style.opacity = 0;
  floatingTooltipEl.classList.remove("chart-tooltip-rich");
}

// "IRONCLAD" -> "Ironclad", for legends, labels, and tooltips
function fmtCharName(char) {
  return char.charAt(0) + char.slice(1).toLowerCase();
}

