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

// A card's image is keyed by id and upgrade state, plus any per-instance variant.
//
// Most cards have exactly one form, but Mad Science cannot be drawn at all without
// TinkerTimeType and TinkerTimeRider: the Tinker Time event is the only thing that
// ever assigns them, so the unrolled card is type None with a ?????? description.
// tools/ExportCards.cs emits one image per combination, named by the two saved
// integers, and a variant is used only when that image exists -- so a card that
// carries state without a variant bake still falls back to its single canonical
// face rather than rendering a broken image.
function cardVariantSuffix(props) {
  if (!props) return "";
  const { TinkerTimeType: t, TinkerTimeRider: r } = props;
  if (t == null || r == null) return "";
  return `.${t}.${r}`;
}

function cardFaceKey(id, upgrade, props) {
  const upgradeSuffix = upgrade > 0 ? "_UP" : "";
  const variant = cardVariantSuffix(props);
  if (variant) {
    const key = `${id}${variant}${upgradeSuffix}`;
    if (DATA.cardFinal && DATA.cardFinal[key]) return key;
  }
  return `${id}${upgradeSuffix}`;
}

// A card face renders in three different contexts (deck tile, node-tooltip
// card, hover preview), each with its own size (the deck tile and the hover
// preview share one). Picking each one's clamp()
// independently -- as the first pass at this did -- gives each context its
// own vw-breakpoint, so resizing the window shrinks them at different rates
// and points: exactly the "inconsistent sizing" this produces. Deriving every
// clamp from the same breakpoint keeps them shrinking in lockstep (down to
// wherever a given context hits its own min and clamps flat).
// card_final/ ships each card with a transparent margin around it, because the
// game draws the energy cost orb and the frame's own bevel outside the card's
// 300x422 rect (the orb is half outside it; see tools/ExportCards.cs's Pad()).
// A width asked for here is the *card body*, so it is scaled up to the image's
// width -- otherwise every face would render ~10% smaller than before, and the
// margin would eat into the space callers laid out for the card.
//
// The numbers are local to the function on purpose: files earlier in the bundle
// call this while app.js is still executing, and reading a module-level `const`
// that early is a temporal-dead-zone ReferenceError.
function cardOuterWidth(px) {
  const BODY_W = 300;
  const MARGIN = 16;
  return Math.round(px * (BODY_W + 2 * MARGIN) / BODY_W);
}

function cardFaceWidth(minPx, maxPx) {
  const BREAKPOINT = 600;
  const vw = (cardOuterWidth(maxPx) / BREAKPOINT * 100).toFixed(3);
  return `clamp(${cardOuterWidth(minPx)}px, ${vw}vw, ${cardOuterWidth(maxPx)}px)`;
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
  let src = DATA.cardFinal && DATA.cardFinal[cardFaceKey(id, upgrade, opts.props)];
  if (!src) return "";
  if (opts.thumb) src = thumbSrc(src);
  const w = typeof width === "number" ? `${width}px` : width;
  const name = (cardInfo(id) || {}).title || fmtCardLabel(id);
  return `<img loading="lazy" class="cardface" style="width:${w}" ${imgSrcAttr(src, opts.deferred)} alt="${name}">`;
}

// The enchantment a card carries, as a line under its face. The face image is a
// baked canonical card, so without this the tooltip would silently drop the
// enchantment that the tile chip promises.
function buildEnchantmentStrip(enchantment) {
  const meta = enchantmentOf({ enchantment });
  if (!meta) return "";
  const text = enchantmentText({ enchantment }, meta);
  return `<div class="ct-enchant">
    ${renderEnchantmentIcon(meta, "ct-enchant-icon", { thumb: true, deferred: true })}
    <span class="ct-enchant-rule"><b>${enchantmentLabel({ enchantment }, meta)}</b>${
      text ? ` ${text}` : ""}</span>
  </div>`;
}

function buildCardTooltip(id, upgrade, props, enchantment) {
  // Prefer the real composited card when the chrome bake is present.
  if (cardFaceAvailable()) {
    return `<div class="card-tooltip card-tooltip-face">${
      renderCardFace(id, upgrade, cardFaceWidth(150, 210), { deferred: true, props })
    }${buildEnchantmentStrip(enchantment)}</div>`;
  }
  const info    = cardInfo(id);
  const variant = cardVariant(id, props);
  // A variant can have its own portrait: Mad Science's three Tinker Time groups
  // each ship separate art, so the canonical card's portrait would show the wrong
  // roll. Falls back to the canonical portrait when there is none.
  const variantArt = (variant && variant.portrait && DATA.cardImages)
    ? DATA.cardImages[variant.portrait] : null;
  const src   = variantArt || cardImgSrc(id);
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

  const type = variant?.type || info?.type || null;
  const typePill = type ? `<span class="ct-type-pill">${type}</span>` : "";

  // IfUpgraded isn't a card stat, so it's not in vars — it's the flag behind
  // {{IfUpgraded:show:ALL cards|a card}} and friends. Supply it here, where
  // the upgrade level is actually known.
  const baseVars = (upgrade > 0 && info?.varsUpgraded) ? info.varsUpgraded : info?.vars;
  const vars = { ...(baseVars || {}), IfUpgraded: upgrade > 0 ? 1 : 0 };
  // A variant's own text wins: it is the roll's real description, where the
  // canonical one may be a placeholder. Variant text is already final (no
  // placeholders left), so substituteDescVars passes it straight through.
  const variantDesc   = (upgrade > 0 && variant?.descUpgraded) ? variant.descUpgraded : variant?.desc;
  const canonicalDesc = (upgrade > 0 && info?.descUpgraded) ? info.descUpgraded : info?.desc;
  const rawDesc = variantDesc || canonicalDesc;
  const desc = rawDesc ? substituteDescVars(rawDesc, vars, { pool: info?.pool }) : null;
  const descHtml = desc ? `<div class="ct-desc">${desc.replace(/\n/g, "<br>")}</div>` : "";

  return `<div class="card-tooltip">
    ${artHtml}
    <div class="ct-banner">${typePill}<span class="ct-name">${nameLabel}</span></div>
    ${descHtml}
    ${buildEnchantmentStrip(enchantment)}
  </div>`;
}

// An enchantment is part of what a card *is* in a deck, not a decoration: the game
// draws it on the card face and adds text of its own, so an enchanted Strike and a
// plain one are different entries. DATA.enchantmentData (see
// tools/import_game_data.py) carries the title and the text for the amount the save
// recorded -- the text is per amount because the canonical enchantment has Amount 0.
function enchantmentOf(card) {
  const data = DATA.enchantmentData;
  const id = card && card.enchantment && card.enchantment.id;
  return (data && id && data[id]) || null;
}

// "Nimble 2". The game shows the amount only where the effect scales with it
// (ShowAmount); the rest read as just their name.
function enchantmentLabel(card, meta) {
  const amount = card && card.enchantment && card.enchantment.amount;
  return amount && meta.showAmount ? `${meta.title} ${amount}` : meta.title;
}

// What the enchantment does to this card, or "" for the few whose text reads a
// value off the card it is attached to (Adroit's "Gain {Block} Block"). Those have
// no honest number without a card, so their tooltip shows the name alone rather
// than a number that came from nowhere.
function enchantmentText(card, meta) {
  if (meta.cardDependent) return "";
  const amount = card && card.enchantment && card.enchantment.amount;
  return (meta.descByAmount && amount && meta.descByAmount[String(amount)]) || meta.desc || "";
}

function renderEnchantmentIcon(meta, cls, opts = {}) {
  const src = meta.imagePath ? (opts.thumb ? thumbSrc(meta.imagePath) : meta.imagePath) : "";
  if (!src) return "";
  return `<img class="${cls}" ${imgSrcAttr(src, opts.deferred)} alt="${meta.title}">`;
}

// Width of a deck tile's card face: the same size the hover preview draws at,
// so the description reads right on the tile and a face tile needs no preview
// of its own. Smaller than this and the browser's downscale of the baked image
// turns the card text soft.
const TILE_FACE_W = cardFaceWidth(150, 210);

function renderCardTile(c) {
  const info  = cardInfo(c.id);
  const name  = (info && info.title) || fmtCardLabel(c.id);
  // Count is deck state, not card identity, so it stays a badge. The upgrade
  // level does NOT — the card face renders it the way the game does, as a
  // green "Strike+" title, so a separate +1 chip would just repeat it.
  const countLabel = c.count > 1 ? `<span class="tile-count">×${c.count}</span>` : "";
  // An enchantment is identity, so it gets the same treatment as the count: a chip
  // on the tile rather than a second card face. The game draws it on the card
  // itself, which the baked face cannot show.
  const enchMeta = enchantmentOf(c);
  const enchLabel = enchMeta
    ? `<span class="tile-enchant" title="${enchantmentLabel(c, enchMeta)}">` +
      `${renderEnchantmentIcon(enchMeta, "tile-enchant-icon", { thumb: true })}` +
      `<span class="tile-enchant-name">${enchantmentLabel(c, enchMeta)}</span></span>`
    : "";

  if (cardFaceAvailable()) {
    // The face already carries the card's own text, so a face tile needs no
    // tooltip -- except for an enchantment, which the baked canonical face cannot
    // show. The chip names it; hovering is what says what it does.
    const enchTip = enchLabel
      ? `<div class="card-tooltip-wrap">${buildEnchantmentStrip(c.enchantment)}</div>`
      : "";
    return `<div class="card-tile card-tile-face">
      ${renderCardFace(c.id, c.upgrade, TILE_FACE_W, { props: c.props })}
      ${(enchLabel || countLabel) ? `<div class="tile-badges">${enchLabel}${countLabel}</div>` : ""}
      ${enchTip}
    </div>`;
  }

  // Fallback for a checkout without card_chrome/: cropped portrait + name.
  const src = cardImgSrc(c.id);
  const typeColor = cardTypeColor(c.id);
  const upgradeLabel = c.upgrade > 0 ? `<span class="ct-upgrade">+${c.upgrade}</span>` : "";
  const artHtml = src
    ? `<img loading="lazy" class="tile-art" src="${src}" alt="${name}">`
    : `<div class="tile-art tile-art-missing">${name.charAt(0)}</div>`;
  const badgesHtml = (upgradeLabel || countLabel || enchLabel)
    ? `<div class="tile-badges">${upgradeLabel}${enchLabel}${countLabel}</div>`
    : "";

  return `<div class="card-tile" style="--tile-color:${typeColor}" tabindex="0">
    ${artHtml}
    <div class="tile-name">
      <div class="tile-name-text">${name}</div>
      ${badgesHtml}
    </div>
    <div class="card-tooltip-wrap">${buildCardTooltip(c.id, c.upgrade, c.props, c.enchantment)}</div>
  </div>`;
}

// Deduplicates a deck array (entries with {id, upgrade}) into one row per
// id+upgrade combo, with a .count of how many copies are in the deck. Per-instance
// props are part of a card's rendered identity -- two Mad Sciences with different
// rolls are different cards, even though they share an id -- so they join the key
// and are carried onto the row for the face lookup. An enchantment does too: a
// Nimble Strike is a different card from a plain Strike, and merging them would
// drop the enchantment from the tile entirely.
function dedupeCardCounts(deck) {
  const cardMap = new Map();
  deck.forEach(c => {
    const ench = c.enchantment ? `${c.enchantment.id}:${c.enchantment.amount || 1}` : "";
    const key = c.id + "|" + c.upgrade + "|" + (c.props ? JSON.stringify(c.props) : "") + "|" + ench;
    if (!cardMap.has(key)) {
      cardMap.set(key, {
        id: c.id, upgrade: c.upgrade, count: 0, props: c.props, enchantment: c.enchantment,
      });
    }
    cardMap.get(key).count++;
  });
  return [...cardMap.values()].sort((a, b) => {
    const na = (cardInfo(a.id)?.title) || fmtCardLabel(a.id);
    const nb = (cardInfo(b.id)?.title) || fmtCardLabel(b.id);
    return na.localeCompare(nb);
  });
}

// The per-instance variant record for a card, if it has one. Mad Science's type,
// portrait and whole description come from the roll Tinker Time gave it, so both the
// face lookup and the fallback tooltip read them from here rather than from the
// canonical model -- which reports type None and a ?????? description because there is
// nothing to report until something rolls the card.
//
// Deliberately independent of cardFaceKey: that only returns a variant key when the
// variant *image* exists, and the tooltip's fallback path runs precisely when no
// images are baked at all.
function cardVariant(id, props) {
  const variants = DATA.cardVariants;
  const suffix = cardVariantSuffix(props);
  if (!variants || !suffix) return null;
  return variants[id + suffix] || null;
}

// A per-instance variant can differ from its canonical model's card type: Mad
// Science's type is whatever the Tinker Time event rolled, while the unrolled model
// reports "None" -- so a deck would otherwise file it under a "None" heading even
// though the face it is showing says Power. DATA.cardVariants (see
// tools/import_game_data.py) maps a variant key to what the game reports for that roll.
function cardTypeOf(card) {
  return cardVariant(card.id, card.props)?.type
    || cardInfo(card.id)?.type
    || "None";
}

// Renders a deduped card list (from dedupeCardCounts) as type-grouped tile rows,
// with each group's header showing the total copy count, not the distinct-entry count.
function renderCardGroupsHtml(cardList) {
  const groups = {};
  cardList.forEach(c => {
    const type = cardTypeOf(c);
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

// A relic tile carries its own rarity and description, so it has no hover
// preview.
function renderRelicTiles(relics) {
  return relics.map(r => {
    const src   = relicImgSrc(r.id);
    const parts = relicTextParts(r.id);
    const label = parts ? parts.name : fmtRelicLabel(r.id);
    return `<div class="relic-tile">
      ${src ? `<img loading="lazy" class="relic-tile-art" src="${src}" alt="">` : ""}
      <div class="relic-tile-text">
        <div class="relic-tile-name">${label}${parts ? parts.rarHtml : ""}</div>
        ${parts && parts.desc ? `<div class="relic-tile-desc">${parts.desc}</div>` : ""}
      </div>
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

