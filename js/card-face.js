// =========================================================================
// Card face — a fully finished card image, baked offline
// =========================================================================
// tools/bake_finished_cards.py composites the frame, portrait border, title
// banner, type plaque, energy orb, portrait and all text (title/type/cost/
// description, with stat values substituted) into one flat WebP per
// (card, upgrade-state), so the browser just shows an <img> instead of
// redoing that layout work on every view.
//
// Everything degrades to the older hand-drawn CSS tooltip if the bake is
// absent, so a checkout without card_final/ still works.

function cardFaceAvailable() {
  return !!(DATA.cardFinal && Object.keys(DATA.cardFinal).length);
}

function cardFaceKey(id, upgrade) {
  return upgrade > 0 ? `${id}_UP` : id;
}

// A card face renders in three different contexts (deck tile, node-tooltip
// card, hover preview), each its own max size. Picking each one's clamp()
// independently -- as the first pass at this did -- gives each context its
// own vw-breakpoint, so resizing the window shrinks them at different rates
// and points: exactly the "inconsistent sizing" this produces. Deriving every
// clamp from the same breakpoint keeps them shrinking in lockstep (down to
// wherever a given context hits its own min and clamps flat).
function cardFaceWidth(minPx, maxPx) {
  const BREAKPOINT = 600;
  const vw = (maxPx / BREAKPOINT * 100).toFixed(3);
  return `clamp(${minPx}px, ${vw}vw, ${maxPx}px)`;
}

// ---- Download size: thumbnails and deferred tooltip art -----------------
//
// Icon-size art (22-26px) uses tools/bake_thumbs.py's small WebP copies
// instead of the full-size file, which can be 20x the bytes. Maps a full-size
// art URL onto its thumbnail; anything without one (no bake, or a folder
// that isn't thumbnailed) comes back unchanged.
function thumbSrc(src) {
  const t = DATA.thumbRoots;
  if (!src || !t || !t.dirs) return src;
  const prefix = t.art + "/";
  if (!src.startsWith(prefix)) return src;
  const rel = src.slice(prefix.length);
  if (!t.dirs.includes(rel.split("/")[0])) return src;
  return `${t.thumbs}/${rel.replace(/\.(png|webp)$/i, ".webp")}`;
}

// Hover tooltips are built into the page up front, hidden with
// visibility:hidden, and a hidden image still downloads. Tooltip art is
// written as data-src instead and only given its real src when its tooltip
// is first opened (hover, focus or tap below; showFloatingHtmlTooltip for
// the floating ones), so a page only downloads the art someone looks at.
function imgSrcAttr(src, deferred) {
  return deferred ? `data-src="${src}"` : `src="${src}"`;
}

function loadDeferredImages(root) {
  for (const img of root.querySelectorAll("img[data-src]")) {
    img.src = img.dataset.src;
    img.removeAttribute("data-src");
  }
}

// A tooltip's .card-tooltip-wrap / .relic-tooltip-wrap sits right inside
// the element that opens it, so walk up a few levels from whatever the
// pointer or focus landed on and load the art of any tooltip found there.
function loadTooltipArtNear(target) {
  for (let el = target, depth = 0; el && el.children && depth < 6; el = el.parentElement, depth++) {
    for (const child of el.children) {
      if (child.classList.contains("card-tooltip-wrap") || child.classList.contains("relic-tooltip-wrap")) {
        loadDeferredImages(child);
      }
    }
  }
}
document.addEventListener("pointerover", e => loadTooltipArtNear(e.target), { passive: true });
document.addEventListener("focusin", e => loadTooltipArtNear(e.target));

// opts.thumb: icon-size, use the thumbnail. opts.deferred: tooltip art, see
// imgSrcAttr().
function renderCardFace(id, upgrade = 0, width = 200, opts = {}) {
  let src = DATA.cardFinal && DATA.cardFinal[cardFaceKey(id, upgrade)];
  if (!src) return "";
  if (opts.thumb) src = thumbSrc(src);
  const w = typeof width === "number" ? `${width}px` : width;
  const name = (cardInfo(id) || {}).title || fmtCardLabel(id);
  return `<img loading="lazy" class="cardface" style="width:${w}" ${imgSrcAttr(src, opts.deferred)} alt="${name}">`;
}

function buildCardTooltip(id, upgrade) {
  // Prefer the real composited card when the chrome bake is present.
  if (cardFaceAvailable()) {
    return `<div class="card-tooltip card-tooltip-face">${renderCardFace(id, upgrade, cardFaceWidth(150, 210), { deferred: true })}</div>`;
  }
  const info  = cardInfo(id);
  const src   = cardImgSrc(id);
  const name  = (info && info.title) || fmtCardLabel(id);
  const nameLabel = upgrade > 0 ? `${name} <span class="ct-upgrade">+${upgrade}</span>` : name;

  // Cost badges (energy + stars) — top-left of art area
  const energy = info?.energy ?? -1;
  const energyCost = info?.costsX ? "X" : (energy >= 0 ? String(energy) : null);
  const starsCost  = (upgrade > 0 && info?.starsUpgraded != null) ? info.starsUpgraded : (info?.stars ?? -1);
  const costBadges = [
    energyCost !== null ? `<span class="ct-cost-energy">${energyCost}</span>` : "",
    starsCost  > 0      ? `<span class="ct-cost-stars">${"✦".repeat(starsCost)}</span>` : "",
  ].filter(Boolean).join("");
  const costsHtml = costBadges ? `<div class="ct-costs">${costBadges}</div>` : "";

  const artHtml = src
    ? `<div class="ct-art-wrap">${costsHtml}<img loading="lazy" class="ct-art" src="${src}" alt="${name}"></div>`
    : `<div class="ct-art-wrap">${costsHtml}<div class="ct-art ct-art-missing"></div></div>`;

  const type = info?.type || null;
  const typePill = type ? `<span class="ct-type-pill">${type}</span>` : "";

  // IfUpgraded isn't a card stat, so it's not in vars — it's the flag behind
  // {{IfUpgraded:show:ALL cards|a card}} and friends. Supply it here, where
  // the upgrade level is actually known.
  const baseVars = (upgrade > 0 && info?.varsUpgraded) ? info.varsUpgraded : info?.vars;
  const vars = { ...(baseVars || {}), IfUpgraded: upgrade > 0 ? 1 : 0 };
  const rawDesc = (upgrade > 0 && info?.descUpgraded) ? info.descUpgraded : info?.desc;
  const desc = rawDesc ? substituteDescVars(rawDesc, vars, { pool: info?.pool }) : null;
  const descHtml = desc ? `<div class="ct-desc">${desc.replace(/\n/g, "<br>")}</div>` : "";

  return `<div class="card-tooltip">
    ${artHtml}
    <div class="ct-banner">${typePill}<span class="ct-name">${nameLabel}</span></div>
    ${descHtml}
  </div>`;
}

// Width of a deck tile's card face. Big enough for the title and cost to read
// at a glance; the description is illegible mush at this scale, but that's
// what the hover tooltip is for.
const TILE_FACE_W = cardFaceWidth(104, 152);

function renderCardTile(c) {
  const info  = cardInfo(c.id);
  const name  = (info && info.title) || fmtCardLabel(c.id);
  // Count is deck state, not card identity, so it stays a badge. The upgrade
  // level does NOT — the card face renders it the way the game does, as a
  // green "Strike+" title, so a separate +1 chip would just repeat it.
  const countLabel = c.count > 1 ? `<span class="tile-count">×${c.count}</span>` : "";

  if (cardFaceAvailable()) {
    // tabindex: the tooltip below is a :hover/:focus-within reveal, which a
    // touch tap can't trigger on a plain, non-focusable div.
    return `<div class="card-tile card-tile-face" tabindex="0">
      ${renderCardFace(c.id, c.upgrade, TILE_FACE_W)}
      ${countLabel ? `<div class="tile-badges">${countLabel}</div>` : ""}
      <div class="card-tooltip-wrap">${buildCardTooltip(c.id, c.upgrade)}</div>
    </div>`;
  }

  // Fallback for a checkout without card_chrome/: cropped portrait + name.
  const src = cardImgSrc(c.id);
  const typeColor = cardTypeColor(c.id);
  const upgradeLabel = c.upgrade > 0 ? `<span class="ct-upgrade">+${c.upgrade}</span>` : "";
  const artHtml = src
    ? `<img loading="lazy" class="tile-art" src="${src}" alt="${name}">`
    : `<div class="tile-art tile-art-missing">${name.charAt(0)}</div>`;
  const badgesHtml = (upgradeLabel || countLabel)
    ? `<div class="tile-badges">${upgradeLabel}${countLabel}</div>`
    : "";

  return `<div class="card-tile" style="--tile-color:${typeColor}" tabindex="0">
    ${artHtml}
    <div class="tile-name">
      <div class="tile-name-text">${name}</div>
      ${badgesHtml}
    </div>
    <div class="card-tooltip-wrap">${buildCardTooltip(c.id, c.upgrade)}</div>
  </div>`;
}

// Deduplicates a deck array (entries with {id, upgrade}) into one row per
// id+upgrade combo, with a .count of how many copies are in the deck.
function dedupeCardCounts(deck) {
  const cardMap = new Map();
  deck.forEach(c => {
    const key = c.id + "|" + c.upgrade;
    if (!cardMap.has(key)) cardMap.set(key, { id: c.id, upgrade: c.upgrade, count: 0 });
    cardMap.get(key).count++;
  });
  return [...cardMap.values()].sort((a, b) => {
    const na = (cardInfo(a.id)?.title) || fmtCardLabel(a.id);
    const nb = (cardInfo(b.id)?.title) || fmtCardLabel(b.id);
    return na.localeCompare(nb);
  });
}

// Renders a deduped card list (from dedupeCardCounts) as type-grouped tile rows,
// with each group's header showing the total copy count, not the distinct-entry count.
function renderCardGroupsHtml(cardList) {
  const groups = {};
  cardList.forEach(c => {
    const type = cardInfo(c.id)?.type || "None";
    if (!groups[type]) groups[type] = [];
    groups[type].push(c);
  });
  return CARD_TYPE_ORDER
    .filter(t => groups[t] && groups[t].length > 0)
    .map(t => {
      const color = CARD_TYPE_COLOR[t] || "#444";
      const tiles = groups[t].map(renderCardTile).join("");
      const total = groups[t].reduce((sum, c) => sum + c.count, 0);
      return `<div class="deck-group">
        <div class="deck-group-label" style="color:${color}">${t} <span class="deck-group-count">${total}</span></div>
        <div class="deck-tile-row">${tiles}</div>
      </div>`;
    }).join("");
}

function renderRelicTiles(relics) {
  return relics.map(r => {
    const src   = relicImgSrc(r.id);
    const label = fmtRelicLabel(r.id);
    const tip   = buildRelicTooltip(r.id);
    // tabindex: same touch/keyboard tooltip-reveal parity as .card-tile.
    if (src) {
      return `<div class="relic-tile" tabindex="0">
        <img loading="lazy" class="relic-tile-art" src="${src}" alt="${label}">
        <div class="relic-tile-name">${label}</div>
        ${tip ? `<div class="relic-tooltip-wrap">${tip}</div>` : ""}
      </div>`;
    }
    return `<div class="relic-tile relic-tile-no-img" tabindex="0">
      <div class="relic-tile-name">${label}</div>
      ${tip ? `<div class="relic-tooltip-wrap">${tip}</div>` : ""}
    </div>`;
  }).join("");
}

function renderDetailDeckRelics(run) {
  const deck   = run.finalDeck   || [];
  const relics = run.finalRelics || [];

  if (deck.length === 0 && relics.length === 0) {
    document.getElementById("detail-deck-relics").innerHTML = "";
    return;
  }

  const groupsHtml = renderCardGroupsHtml(dedupeCardCounts(deck));
  const relicHtml  = renderRelicTiles(relics);

  document.getElementById("detail-deck-relics").innerHTML = `
    <div class="detail-section-heading">Final Deck</div>
    ${groupsHtml}
    <div class="detail-section-heading" style="margin-top:16px">Relics</div>
    <div class="deck-relic-list">${relicHtml}</div>`;
}

renderPersonalBests();

// Chrome keeps :hover on whatever sits under a stationary pointer while the
// page scrolls, which can leave a card/relic tooltip pinned to a tile the
// user is no longer really hovering. Suppress hover tooltips during scroll
// until the mouse moves again.
window.addEventListener("scroll", () => document.body.classList.add("suppress-hover-tooltips"), { passive: true });
window.addEventListener("mousemove", () => document.body.classList.remove("suppress-hover-tooltips"));

// Restore tab from URL hash — runs last so all init code has already executed
(function() {
  const hash = location.hash.replace("#", "");
  if (PAGES.includes(hash)) showPage(hash);
})();

// Card Stats is the heaviest page to render on first visit — one row per
// card, with a portrait image for every row. If the user is landing on
// Overview (the common case — no hash, or an explicit #overview), prefetch
// it once in the background so that work is already done by the time the
// tab is actually clicked, instead of paying it synchronously on the click
// itself (measurable as INP in the browser's own Performance panel).
// setTimeout(fn, 0) queues this as a task right after the current script
// finishes and the page's first paint completes — the earliest point
// there's any actual idle main-thread time — so it starts running before
// a human can realistically click a different tab on a page that just
// loaded, without delaying Overview's own visible rendering to get there.
// Skipped if the hash above already sent them straight to some other
// page, since there's nothing to get ahead of in that case. Rechecks
// currentPage in case the user still somehow navigates away first (e.g.
// the URL hash changes via history navigation during that brief window).
// Marks pageDirty.cards clean afterward so showPage("cards") skips its
// own render entirely instead of immediately redoing this same work.
if (currentPage === "overview") {
  setTimeout(() => {
    if (currentPage === "overview" && pageDirty.cards) {
      renderCardsPage();
      pageDirty.cards = false;
    }
  }, 0);
}

