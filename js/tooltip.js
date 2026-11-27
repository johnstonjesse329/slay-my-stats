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
function getFloatingTooltipEl(anchor = null) {
  if (!floatingTooltipEl) {
    floatingTooltipEl = document.createElement("div");
    floatingTooltipEl.className = "chart-tooltip";
    floatingTooltipEl.addEventListener("pointerdown", e => {
      // A touch card preview opens on pointerdown. Keep the metric focused
      // so mobile Safari doesn't close the preview when it moves focus.
      if (e.pointerType !== "mouse" && e.target.closest(".party-support-card")) e.preventDefault();
    });
    floatingTooltipEl.addEventListener("focusout", e => {
      if (tipTrigger?.classList.contains("party-support-example") &&
          !floatingTooltipEl.contains(e.relatedTarget) && e.relatedTarget !== tipTrigger) scheduleTipHide();
    });
  }
  if (anchor) {
    if (floatingTooltipEl.previousElementSibling !== anchor) anchor.after(floatingTooltipEl);
  } else if (floatingTooltipEl.parentNode !== document.body) {
    document.body.appendChild(floatingTooltipEl);
  }
  return floatingTooltipEl;
}

// Clamps a tooltip element's top-left corner so it stays fully inside the
// viewport. Call after setting innerHTML (and after resetting left/top to
// 0) so el.offsetWidth/offsetHeight reflect the current content. The
// viewport is clientWidth/Height, not innerWidth/Height: those include the
// page's scrollbar, which pushed a tooltip near the right edge under it and
// squeezed it narrower.
function clampTooltipPosition(el, rawLeft, rawTop, margin = 8) {
  const { vw, vh } = viewportSize();
  return {
    left: clampAxis(rawLeft, el.offsetWidth,  vw, margin),
    top:  clampAxis(rawTop,  el.offsetHeight, vh, margin),
  };
}

// The pieces clampTooltipPosition is built from, for the tooltips that place themselves (a node's
// tooltip, the floor box, the card zoom): every one of them fits the viewport with these, so none
// reaches for innerWidth again.
function viewportSize() {
  const { clientWidth: vw, clientHeight: vh } = document.documentElement;
  return { vw, vh };
}
// One axis: `raw` (the box's near edge) held `margin` inside a viewport `room` long, for a box
// `size` long. A box longer than the room sits at the margin.
function clampAxis(raw, size, room, margin = 8) {
  return Math.min(Math.max(raw, margin), Math.max(room - size - margin, margin));
}

// How the shared box is hidden. The three rules below are WCAG 1.4.13 (content
// on hover or focus), which is what Tippy.js and Floating UI implement too:
//   hoverable   the pointer can travel onto the box without it closing (a short
//               grace delay on leaving the trigger, cancelled by entering the box)
//   persistent  it stays until the pointer is outside both, or focus moves on
//   dismissible Esc, or a tap/click anywhere outside it, closes it
// Chart tooltips follow the pointer and aren't enterable; text tips and rich
// card/relic tips are ("tip-live").
const TIP_GRACE_MS = 150;
let tipTrigger = null;
let tipHideTimer = null;
function cancelTipHide() {
  clearTimeout(tipHideTimer);
  tipHideTimer = null;
}
function scheduleTipHide() {
  cancelTipHide();
  tipHideTimer = setTimeout(hideSharedTooltip, TIP_GRACE_MS);
}
function hideSharedTooltip() {
  cancelTipHide();
  if (tipTrigger?.classList.contains("party-support-example")) floatingTooltipEl?.replaceChildren();
  tipTrigger = null;
  if (!floatingTooltipEl) return;
  floatingTooltipEl.style.opacity = 0;
  floatingTooltipEl.classList.remove("chart-tooltip-rich", "tip-live");
}

function chartTooltipHandler({ chart, tooltip }) {
  const el = getFloatingTooltipEl();

  if (tooltip.opacity === 0) {
    el.style.opacity = 0;
    el.classList.remove("tip-live");
    return;
  }
  cancelTipHide();
  tipTrigger = null;
  el.classList.remove("tip-live", "chart-tooltip-rich");

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
  if (target.dataset.encounterTip) {
    const html = buildEncounterTooltip(target.dataset.encounterTip, text);
    if (html) {
      showFloatingHtmlTooltip(target, html);
      return;
    }
  }
  const template = target.querySelector(":scope > template");
  const el = getFloatingTooltipEl(template ? target : null);
  cancelTipHide();
  if (template && tipTrigger === target) return;
  tipTrigger = target;
  el.classList.remove("chart-tooltip-rich", "tip-passive");
  el.classList.add("tip-live");
  if (template) el.replaceChildren(template.content.cloneNode(true));
  else el.innerHTML = text.split("\n").map(line => `<div>${line}</div>`).join("");
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
  if (!template && clientX != null && clientY != null) {
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
  scheduleTipHide();
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
  if (target && !target.contains(e.relatedTarget) &&
      !(floatingTooltipEl?.previousElementSibling === target && floatingTooltipEl.contains(e.relatedTarget))) hideTableTooltip();
});
document.addEventListener("pointerup", e => {
  if (e.pointerType === "touch" || e.pointerType === "pen") {
    const target = e.target.closest("[data-encounter-tip], .event-pie-slice[data-tip], .party-support-example");
    if (target) showTableTooltip(target);
  }
});

// Rich-content variant of the same floating element, for callers that need
// the full card/relic tooltip markup (buildCardTooltip/buildRelicTooltip)
// rather than plain text lines. Needed anywhere that markup would otherwise
// sit inside a scrolling `.pivot-wrap` (overflow-y:auto clips an absolutely-
// positioned .card-tooltip-wrap child) -- appending to document.body instead
// sidesteps that clipping entirely, same as the chart tooltip above.
// `passive`: the box can't be entered (pointer-events:none), for triggers that sit
// inside another hover tooltip -- a box the pointer can land on would take the
// hover away from that tooltip and close it.
function showFloatingHtmlTooltip(target, html, passive = false) {
  if (!html) return;
  const el = getFloatingTooltipEl();
  cancelTipHide();
  tipTrigger = target;
  el.classList.add("chart-tooltip-rich", "tip-live");
  el.classList.toggle("tip-passive", passive);
  el.innerHTML = html;
  loadDeferredImages(el);
  el.style.left = "0px";
  el.style.top = "0px";
  el.style.opacity = 1;

  const rect = target.getBoundingClientRect();
  const place = () => {
    const { left, top } = clampTooltipPosition(el, rect.left, rect.bottom + 6);
    el.style.left = `${left}px`;
    el.style.top  = `${top}px`;
  };
  place();
  // A card face's art only starts loading now (loadDeferredImages), so the box
  // grows after it's placed; place it again once each image is in, or one near
  // the bottom of the window runs off it.
  el.querySelectorAll("img").forEach(img => {
    if (!img.complete) img.addEventListener("load", () => { if (el.contains(img)) place(); }, { once: true });
  });
}
function hideFloatingHtmlTooltip() {
  scheduleTipHide();
}

// Entering the box keeps it; leaving it (with a mouse) starts the same grace
// delay, so moving back onto the trigger doesn't flicker it shut.
document.addEventListener("pointerenter", e => {
  if (floatingTooltipEl && e.target === floatingTooltipEl) cancelTipHide();
}, true);
document.addEventListener("pointerleave", e => {
  if (floatingTooltipEl && e.target === floatingTooltipEl && e.pointerType === "mouse"
      && floatingTooltipEl.classList.contains("tip-live")) scheduleTipHide();
}, true);

// Card/relic/node tooltips (card-face.js, run-detail.js, render-helpers.js)
// open via :focus-within on a tabindex="0" trigger, so a touch tap can
// reveal them the same way a mouse hover does. But a tap only ever *moves*
// focus on iOS/Android when it lands on something itself focusable --
// tapping blank space elsewhere on the page doesn't blur the trigger, so
// the tooltip lingers open forever. The same goes for the shared box
// (data-tip text, rich card/relic, a chart's): no mouseout ever comes on a
// touch screen. So any press outside a tooltip and its trigger closes it; a
// press inside it (to read or scroll it) keeps it. A press on a different
// trigger closes this one and the browser's own focus-follows-tap, or the
// compat mouseover that follows, opens that one right after.
const TIP_FOCUS_TRIGGERS = ".card-tile, .relic-tile, .fav-item, .run-boon-wrap, .node-card, .site-tip, .event-art-thumbnail";
function dismissTipsOutside(target) {
  const active = document.activeElement;
  if (active && active.matches(TIP_FOCUS_TRIGGERS) && !active.contains(target)) active.blur();
  const inBox = floatingTooltipEl && floatingTooltipEl.contains(target);
  const onTrigger = tipTrigger && tipTrigger.contains(target);
  if (!inBox && !onTrigger) hideSharedTooltip();
  // Chart.js keeps its hover state until the pointer next moves over a
  // canvas, so tapping the same point again would change nothing and the box
  // would stay hidden. Clear it on every chart but the one pressed.
  if (typeof Chart !== "undefined" && Chart.instances) {
    for (const chart of Object.values(Chart.instances)) {
      if (chart.canvas.contains(target) || !chart.tooltip?.getActiveElements().length) continue;
      chart.tooltip.setActiveElements([], { x: 0, y: 0 });
      chart.setActiveElements([]);
      chart.update("none");
    }
  }
}
document.addEventListener("pointerdown", e => dismissTipsOutside(e.target), { capture: true, passive: true });

// Tap-through: on a touch screen the tap that opens a tooltip lands its click on whatever the
// tooltip put under the finger, so a link or button in it fired at once with no second tap.
// A click inside a tooltip is kept only when its press began inside one too.
const TIP_BOXES = ".chart-tooltip, .card-tooltip-wrap, .relic-tooltip-wrap, .node-tooltip, .floor-tip";
let pressStartedInTip = false, pressWasTouch = false, touchTipStart = null;
document.addEventListener("pointerdown", e => {
  pressStartedInTip = !!e.target.closest(TIP_BOXES);
  pressWasTouch = e.pointerType === "touch" || e.pointerType === "pen";
  touchTipStart = pressStartedInTip && e.pointerType === "touch" ? [e.clientX, e.clientY] : null;
}, { capture: true, passive: true });

function dismissTipSurface(box, target) {
  const control = target.closest("a, button, input, select, textarea, summary, [data-pick], [data-card-pop]");
  if (control && box.contains(control)) return false;
  if (box.classList.contains("floor-tip")) closeFloorTip();
  dismissTips();
  return true;
}

// Mobile Safari can omit click on tooltip text and images. Handle the tap
// there directly, while leaving swipes and presses on controls alone.
document.addEventListener("touchend", e => {
  const box = e.target.closest(TIP_BOXES);
  const touch = e.changedTouches[0];
  if (!box || !touch || !touchTipStart) return;
  const [x, y] = touchTipStart;
  touchTipStart = null;
  if (Math.hypot(touch.clientX - x, touch.clientY - y) > 10 || !dismissTipSurface(box, e.target)) return;
  e.preventDefault();
  e.stopPropagation();
}, { capture: true, passive: false });

document.addEventListener("click", e => {
  const box = e.target.closest(TIP_BOXES);
  if (!box) return;
  if ((pressWasTouch && !pressStartedInTip) || dismissTipSurface(box, e.target)) {
    e.preventDefault();
    e.stopPropagation();
  }
}, true);

// Close shared and inline tooltips on Escape or a click on their surface.
function dismissTips() {
  hideSharedTooltip();
  const active = document.activeElement;
  if (active && active.matches(TIP_FOCUS_TRIGGERS)) active.blur();
  document.body.classList.add("suppress-hover-tooltips");
}
document.addEventListener("keydown", e => {
  if (e.key === "Escape") dismissTips();
});

// "IRONCLAD" -> "Ironclad", for legends, labels, and tooltips
function fmtCharName(char) {
  return titleCaseId(char);
}

// "LIGHT_ATTACK" -> "Light Attack": an id's words, title-cased. The one copy, so a card, relic,
// potion, node or character with no label in the catalog reads the same everywhere. Strip any
// "CARD."-style prefix first.
function titleCaseId(id) {
  return String(id).replace(/_/g, " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}

// The colour of a character no colour list knows (see charColor in data.js).
const CHAR_FALLBACK_COLOR = "#a0a0b8";

// The character's head from the game's top panel, to sit before its name
// wherever the name is shown. A card pool with no character (colorless) keeps
// its energy icon; "" when neither exists (an unknown character).
function charIconUrl(char) {
  return (DATA.charIcons || {})[String(char).toUpperCase()]?.icon
    || (DATA.energyIcons || {})[String(char).toLowerCase()];
}
function charIconHtml(char) {
  const url = charIconUrl(char);
  return url ? `<img class="char-icon" src="${url}" alt="">` : "";
}

// A character's name as the site shows it everywhere: the head, then the name in the character's
// color (see .char-label in dashboard.css, the one place its size and weight are set). Pass large
// for a character's own pane or heading, the only place it is bigger. icon=false leaves the head out
// where the character is already shown larger beside it (the Ascension tracker's portrait).
function charLabelHtml(char, large = false, icon = true) {
  const color = charColor(char);
  return `<span class="char-label${large ? " char-label-lg" : ""}" style="--char-color:${color}">${icon ? charIconHtml(char) : ""}${fmtCharName(char)}</span>`;
}

