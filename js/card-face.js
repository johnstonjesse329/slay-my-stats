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
//
// The face itself (renderCardFace and the image lookups behind it) lives in
// js/item-tips.js, which the front page loads too.

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

// What the enchantment does to this card, or "" for any whose text reads a
// value off the card it is attached to. Those have
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
  // green "Strike+" title, so a separate +1 chip would just repeat it. The one
  // exception is the by-floor view: there the face is the card as it was added,
  // and `upgradedAt` says on which later floor it became the upgraded card.
  const countLabel = c.count > 1 ? `<span class="tile-count">×${c.count}</span>` : "";
  // Two upgrades on one floor (a node that upgrades a card twice) is one floor.
  const up = [...new Set(c.upgradedAt || [])];
  const upgradeMark = up.length
    ? `<span class="tile-upgraded-at" title="Upgraded on floor${up.length > 1 ? "s" : ""} ${up.join(", ")}">`
      + `↑${up.length > 1 ? `F${up[0]}–F${up[up.length - 1]}` : `F${up[0]}`}</span>`
    : "";
  const floorLabel = c.seqMark || upgradeMark
    ? `<div class="tile-added-floors">${c.seqMark || ""}${upgradeMark}</div>`
    : "";
  // The upgrade reads under the card it happened to. A separate entry beside the
  // card read as a second copy arriving on that floor. The note still pops the
  // upgraded card, so the better version is one hover away.
  const upgradeNote = up.length
    ? `<div class="tile-upgrade-note" ${cardPopAttrs(c.id, 1)} tabindex="0">↑ Upgraded ${fmtCardLabel(c.id)}${
      c.count > 1 ? ` ×${c.count}` : ""}</div>`
    : "";
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
    // show, and the floor's passed-over offers, which belong to the card that was
    // taken. The chip names the enchantment; hovering is what says what it does.
    const enchTip = enchLabel ? buildEnchantmentStrip(c.enchantment) : "";
    // data-tile-card: what a phone's tap-to-enlarge needs to draw the card again
    // (see openCardLightbox).
    const tileData = encodeURIComponent(JSON.stringify({ id: c.id, upgrade: c.upgrade, props: c.props, enchantment: c.enchantment }));
    return `<div class="card-tile card-tile-face" data-tile-card="${tileData}">
      <div class="tile-face-art">
        ${renderCardFace(c.id, c.upgrade, TILE_FACE_W, { props: c.props })}
        ${(enchLabel || countLabel) ? `<div class="tile-badges">${enchLabel}${countLabel}</div>` : ""}
      </div>
      ${floorLabel}
      ${upgradeNote}
      ${enchTip ? `<div class="card-tooltip-wrap">${enchTip}</div>` : ""}
      ${c.offersTip || ""}
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
      ${floorLabel}
      ${upgradeNote}
    </div>
    <div class="card-tooltip-wrap">${buildCardTooltip(c.id, c.upgrade, c.props, c.enchantment)}</div>
    ${c.offersTip || ""}
  </div>`;
}

// Higher is rarer; anything unrecognised sorts last.
const RARITY_RANK = { Ancient: 8, Boss: 7, Event: 6, Rare: 5, Uncommon: 4, Common: 3, Shop: 2, Starter: 1 };
function rarityRank(r) { return RARITY_RANK[r] || 0; }

// Deduplicates a deck array (entries with {id, upgrade}) into one row per
// id+upgrade combo, with a .count of how many copies are in the deck. Per-instance
// props are part of a card's rendered identity -- two Mad Sciences with different
// rolls are different cards, even though they share an id -- so they join the key
// and are carried onto the row for the face lookup. An enchantment does too: a
// Nimble Strike is a different card from a plain Strike, and merging them would
// drop the enchantment from the tile entirely. `extraKeys` names per-entry fields
// a caller also draws differently, the same way (the floor view keeps a card
// upgraded on F16 apart from its identical copy upgraded on F20).
function dedupeCardCounts(deck, extraKeys = []) {
  const cardMap = new Map();
  deck.forEach(c => {
    const ench = c.enchantment ? `${c.enchantment.id}:${c.enchantment.amount || 1}` : "";
    const extra = extraKeys.map(k => "|" + (c[k] ?? "")).join("");
    const key = c.id + "|" + c.upgrade + "|" + (c.props ? JSON.stringify(c.props) : "") + "|" + ench + extra;
    if (!cardMap.has(key)) {
      const row = {
        id: c.id, upgrade: c.upgrade, count: 0, props: c.props, enchantment: c.enchantment,
      };
      extraKeys.forEach(k => { if (c[k] !== undefined) row[k] = c[k]; });
      cardMap.set(key, row);
    }
    cardMap.get(key).count++;
  });
  // Rarest first within a deck group; the same rarity falls back to name order.
  return [...cardMap.values()].sort((a, b) => {
    const dr = rarityRank(cardInfo(b.id)?.rarity) - rarityRank(cardInfo(a.id)?.rarity);
    if (dr) return dr;
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

// A relic tile carries its own rarity and description, so on a wide screen it
// needs no hover preview. On a phone the tile shrinks to its icon (five to a
// row) and the same popup the ancient boons use opens on a tap; the popup is
// display:none everywhere else (see .relic-tile in dashboard.css).
function renderRelicTiles(relics) {
  return relics.map(r => {
    const src   = relicImgSrc(r.id);
    const parts = relicTextParts(r.id);
    const label = parts ? parts.name : fmtRelicLabel(r.id);
    const tip   = buildRelicTooltip(r.id);
    return `<div class="relic-tile" tabindex="0">
      ${src ? `<img loading="lazy" class="relic-tile-art" src="${src}" alt="${String(label).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;")}">` : ""}
      <div class="relic-tile-text">
        <div class="relic-tile-name">${label}${parts ? parts.rarHtml : ""}</div>
        ${parts && parts.desc ? `<div class="relic-tile-desc">${parts.desc}</div>` : ""}
      </div>
      ${tip ? `<div class="relic-tooltip-wrap">${tip}</div>` : ""}
    </div>`;
  }).join("");
}

// The deck view picked, kept across runs.
let deckView = "type";
document.addEventListener("click", e => {
  const button = e.target.closest("[data-deck-view]");
  if (!button) return;
  deckView = button.dataset.deckView;
  const root = button.closest("#detail-deck-relics");
  root.querySelectorAll("[data-deck-view]").forEach(b => b.setAttribute("aria-pressed", String(b === button)));
  root.querySelectorAll("[data-deck-panel]").forEach(panel => { panel.hidden = panel.dataset.deckPanel !== deckView; });
});

// In-combat upgrades (Armaments and the like) are recorded on the fight's node,
// and most of them do hold: 3,380 cards whose only recorded upgrade is on a
// fight ended upgraded, against 70 that did not. So a fight's record counts as
// evidence, but the lasting spaces are preferred where they explain the card on
// their own.
const IN_COMBAT_NODE_TYPES = new Set(["monster", "elite", "boss"]);

// When the run upgraded each card, from the timeline's per-node `upgradedCards`.
// `byIndex` pairs floors with a final-deck entry, which needs the copies to be
// tellable apart: a card is only paired when the recorded upgrades add up to the
// upgrades its copies took. Otherwise every copy keeps its final face and the
// floors are left out rather than guessed at.
function cardUpgradeFloors(deck, added, timeline) {
  const eventsById = new Map();
  timeline.forEach(node => {
    const inCombat = IN_COMBAT_NODE_TYPES.has(node.type);
    (node.upgradedCards || []).forEach(id => {
      if (!eventsById.has(id)) eventsById.set(id, []);
      eventsById.get(id).push({ floor: node.floor + 1, inCombat });
    });
  });
  const byIndex = new Map();
  eventsById.forEach((events, id) => {
    const copies = deck.map((c, i) => i)
      .filter(i => deck[i].id === id && deck[i].upgrade > 0)
      .sort((a, b) => (added[a] || 1) - (added[b] || 1));
    // `upgrade` is how many upgrades a copy took (Dingy Dagger grows at every
    // smith, up to 12). Events that don't add up to that -- a card acquired
    // already upgraded, or an upgrade spent on a copy since removed -- cannot be
    // pinned on a held copy, so this card's floors stay out of the view.
    const levels = copies.reduce((n, i) => n + deck[i].upgrade, 0);
    if (!copies.length || !levels) return;
    const ascending = (a, b) => a - b;
    const lasting = events.filter(e => !e.inCombat).map(e => e.floor).sort(ascending);
    const every = events.map(e => e.floor).sort(ascending);
    const floors = lasting.length === levels ? lasting : every.length === levels ? every : null;
    if (!floors) return;
    let at = 0;
    copies.forEach(i => {
      byIndex.set(i, floors.slice(at, at + deck[i].upgrade));
      at += deck[i].upgrade;
    });
  });
  return byIndex;
}

// What the shop asks for a card (shop_prices.json, tools/derive_shop_prices.py):
// the price that card's own recorded single-card purchases give, else its
// rarity's. null when the table is missing or the card has no known rarity.
function shopPriceOf(id) {
  const table = DATA.shopPrices;
  if (!table) return null;
  const own = table.cards?.[id]?.price;
  if (own != null) return own;
  const rarity = cardInfo(id)?.rarity;
  return rarity != null ? table.rarity?.[rarity] ?? null : null;
}

// The relics the run was holding by a floor, from the timeline's own relic
// grants: everything granted on an earlier floor, plus what it started with (its
// final relics less everything the floors granted).
function relicsHeldBefore(timeline, finalRelics, floor) {
  const byFloor = new Map();
  const granted = new Set();
  timeline.forEach(node => {
    const ids = [node.relicPicked, ...(node.relicsBought || []), ...(node.relicsRewarded || [])]
      .filter(Boolean);
    if (!ids.length) return;
    ids.forEach(id => granted.add(id));
    const key = node.floor + 1;
    if (!byFloor.has(key)) byFloor.set(key, new Set());
    ids.forEach(id => byFloor.get(key).add(id));
  });
  const held = new Set((finalRelics || []).map(r => r.id).filter(id => id && !granted.has(id)));
  byFloor.forEach((ids, grantedOn) => {
    if (grantedOn < floor) ids.forEach(id => held.add(id));
  });
  return held;
}

// The best shop discount among some relics, as {id, pct, title}; null when none
// of them discounts the shop. The percentages come from shop_prices.json, which
// reads them off the relics themselves (tools/derive_shop_prices.py).
function shopDiscountOf(relicIds) {
  const table = DATA.shopPrices?.discountRelics || {};
  let best = null;
  for (const id of relicIds) {
    const pct = table[id];
    if (!pct) continue;
    if (!best || pct > best.pct) best = { id, pct, title: relicInfo(id)?.title || fmtRelicLabel(id) };
  }
  return best;
}

// A shop's shelf with what each card cost that run: the shop's price less the
// discount the run already held. A card priced above the gold the run walked in
// with was out of reach, so its price is shown in the loss colour -- unless the
// visit also sold the discount relic, where the order of the purchases (and so
// the price) is not recorded.
function deckShelfRowHtml(ids, gold, discount, boughtHere) {
  const pct = discount?.pct || 0;
  const cells = ids.map(id => {
    const list = shopPriceOf(id);
    const price = list == null ? null : Math.round(list * (100 - pct) / 100);
    const over = price != null && gold != null && !boughtHere && price > gold;
    const why = over ? `More than the ${gold} gold the run had`
      : boughtHere ? `The shop also sold ${boughtHere.title}, so this may have cost less`
        : pct ? `${list} before ${discount.title}'s ${pct}% off` : "";
    return `<div class="nt-cardface deck-shop-card" data-card="${id}" ${cardPopAttrs(id)}>`
      + renderCardFace(id, 0, "var(--nt-card-w)")
      + (price == null ? ""
        : `<div class="deck-shop-price${over ? " deck-shop-price-over" : ""}"${
          why ? ` title="${why}"` : ""}>${price}</div>`)
      + "</div>";
  }).join("");
  return `<div class="nt-cardrow">${cells}</div>`;
}

// The cards a floor offered that were passed over, shown on the card that was
// actually taken. The same full-brightness faces the map's floor tooltip uses
// (nodeCardRow, run-detail.js), placed beside the tile rather than popping out
// over it, so hovering one of them pops it full size. A shop's shelf is not the
// same kind of choice, so it is headed as a shop and priced per card: a shelf
// card the run's gold could not cover is priced in the loss colour, which is
// what the visit was really choosing between.
function deckOffersTipHtml(node, floor, goldBefore = null, discount = null, boughtHere = null) {
  const ids = [...new Set(node.cardsSkipped || [])];
  if (!ids.length) return "";
  const shop = node.type === "shop";
  const row = shop
    ? deckShelfRowHtml(ids, goldBefore, discount, boughtHere)
    : typeof nodeCardRow === "function"
      ? nodeCardRow(ids)
      : `<div class="nt-cardrow">${ids.map(id => `<span>${fmtCardLabel(id)}</span>`).join("")}</div>`;
  return `<div class="node-tooltip deck-offers-tip">
    <div class="nt-floor">${shop ? "For sale on floor" : "Also offered on floor"} ${floor}</div>
    ${shop && goldBefore != null ? `<div class="nt-hp-gold">Had ${goldBefore} gold</div>` : ""}
    ${shop && discount ? `<div class="deck-shop-discount">${discount.title}: ${discount.pct}% off</div>` : ""}
    ${shop && !discount && boughtHere ? `<div class="deck-shop-discount">${boughtHere.title} bought here</div>` : ""}
    ${row}
  </div>`;
}

// Placed by the map's floor-tooltip code (fitNodeTooltip, run-detail.js): it
// picks the side with room for the panel, sizes the faces to the window and
// keeps the whole thing on screen.
function fitDeckOffersTipOf(tile) {
  const tip = tile?.querySelector(":scope > .deck-offers-tip");
  if (!tip || typeof fitNodeTooltip !== "function") return;
  fitNodeTooltip(tip, tile);
  // The faces load after this and grow the panel, so fit again when each lands
  // (the same re-place item-tips.js and tooltip.js do for their boxes).
  tip.querySelectorAll("img").forEach(img => {
    if (img.complete) return;
    img.addEventListener("load", () => {
      if (tile.matches(":hover, :focus-within")) fitNodeTooltip(tip, tile);
    }, { once: true });
  });
}
document.addEventListener("pointerover", e => {
  const tile = e.target.closest?.(".card-tile");
  if (tile && !tile.contains(e.relatedTarget)) fitDeckOffersTipOf(tile);
});
document.addEventListener("focusin", e => fitDeckOffersTipOf(e.target.closest?.(".card-tile")));

// The deck as it was gathered: one run of cards in the order they came, the starting cards
// first, with the floor as a small marker under each (a card marked "F12" came on floor 12).
// A card the run upgraded later keeps the face it was added with and says under it which floor
// upgraded it, so the sequence reads as one card getting better rather than a better card
// arriving. A card taken from a floor that offered others carries those others in a hover panel.
function renderCardsByFloorHtml(deck, added, timeline = [], relics = []) {
  const upgrades = cardUpgradeFloors(deck, added, timeline);
  const byFloor = new Map();
  deck.forEach((c, i) => {
    const floor = Number.isInteger(added[i]) && added[i] >= 1 ? added[i] : 0;
    if (!byFloor.has(floor)) byFloor.set(floor, []);
    const upgradedAt = upgrades.get(i);
    byFloor.get(floor).push(upgradedAt ? { ...c, upgrade: 0, upgradedAt } : c);
  });
  const nodes = new Map(timeline.map(node => [node.floor + 1, node]));
  const floors = [...byFloor.keys()].sort((a, b) => a - b);
  const tiles = floors.map(floor => {
    const cards = byFloor.get(floor) || [];
    const node = nodes.get(floor);
    // Only the card that came from that floor's offer carries it: the deck is what
    // was taken, and the passed-over cards are the story of that pick.
    const picked = node?.type === "shop" ? node.cardsBought : node?.cardsRewarded;
    // What the run was carrying on the way in: the gold the node before it ended
    // with. A shop only, where it is what decided what could be bought.
    const goldBefore = node?.type === "shop" ? nodes.get(floor - 1)?.gold ?? null : null;
    // What the shop charged this run: the discount it already held by this
    // floor. A discount relic sold by this same shop is not counted -- whether
    // it was paid for before or after the cards is not recorded -- but it does
    // stop the shelf being called unaffordable.
    const discount = node?.type === "shop"
      ? shopDiscountOf(relicsHeldBefore(timeline, relics, floor)) : null;
    const boughtHere = node?.type === "shop" ? shopDiscountOf(node.relicsBought || []) : null;
    const offers = floor && node?.cardsSkipped?.length
      ? deckOffersTipHtml(node, floor, goldBefore, discount, boughtHere) : "";
    return dedupeCardCounts(cards, ["upgradedAt"])
      .map(c => renderCardTile({
        ...c, seqMark: floor ? `F${floor}` : "Start",
        offersTip: offers && picked?.includes(c.id) ? offers : "",
      })).join("");
  });
  return `<div class="deck-tile-row deck-sequence">${tiles.join("")}</div>`;
}

function renderDetailDeckRelics(run) {
  const deck   = run.finalDeck   || [];
  // Rarest first; Array.sort is stable, so the order picked up in is kept within a rarity.
  const relics = [...(run.finalRelics || [])]
    .sort((a, b) => rarityRank(relicInfo(b.id)?.rarity) - rarityRank(relicInfo(a.id)?.rarity));

  if (deck.length === 0 && relics.length === 0) {
    document.getElementById("detail-deck-relics").innerHTML = "";
    return;
  }

  const groupsHtml = renderCardGroupsHtml(dedupeCardCounts(deck));
  // Only a run that says when each card came has a second view to offer.
  const hasFloors = Array.isArray(run.deckAdded) && run.deckAdded.length === deck.length;
  const view = hasFloors ? deckView : "type";
  const tabs = hasFloors ? `<div class="party-toggle deck-view-tabs" role="group" aria-label="Deck view">` +
    [["type", "By type"], ["floor", "By floor added"]].map(([id, label]) =>
      `<button type="button" data-deck-view="${id}" aria-pressed="${view === id}">${label}</button>`).join("") + `</div>` : "";
  const relicHtml  = renderRelicTiles(relics);

  document.getElementById("detail-deck-relics").innerHTML = `
    ${renderDeckLinksHtml(deck, relics, run.char)}
    ${tabs}
    <div data-deck-panel="type"${view === "type" ? "" : " hidden"}>${groupsHtml}</div>
    ${hasFloors ? `<div data-deck-panel="floor"${view === "floor" ? "" : " hidden"}>${renderCardsByFloorHtml(deck, run.deckAdded, run.timeline, run.finalRelics)}</div>` : ""}
    <div class="detail-section-heading" style="margin-top:16px">Relics <span class="deck-group-count">${relics.length}</span></div>
    <div class="deck-relic-list">${relicHtml}</div>`;
  // The explorer's relic panels carry their art as deferred data-src.
  loadDeferredImages(document.getElementById("detail-deck-relics"));
}

// What the final deck is built around: every archetype of the character's
// (tools/power_curve/archetypes.py) the deck has 3 or more cards of, most first.
// Starter cards aren't in the lists, so they never count. An archetype with
// "needs" (Self-damage) also needs one of those payoff cards in the deck.
const TAG_MIN = 3;
function deckTags(char, deck) {
  const sigs = DATA.archetypes && DATA.archetypes[char];
  if (!sigs) return [];
  return Object.entries(sigs)
    .filter(([, s]) => !s.needs.length || deck.some(c => s.needs.includes(c.id)))
    .map(([name, s]) => [deck.filter(c => s.cards.includes(c.id)).length, name])
    .filter(([n]) => n >= TAG_MIN)
    .sort((a, b) => b[0] - a[0])
    .map(([, name]) => name);
}

// A run's tags, worked out once (the run list filters on them on every render).
function runTags(run) {
  if (!run._tags) run._tags = deckTags(run.char, run.finalDeck || []);
  return run._tags;
}

// Cards and relics in this run that feed each other: one makes a thing (Strength,
// Poison, Osty, Shiv...) and another needs it. Listed, not scored. DATA.synergy
// holds only the specific keys; a key with no maker or no other user is dropped.
function cardSynergyRow(c, table) {
  const upgrade = c.upgrade > 0 ? 1 : 0;
  const rolls = table.cardRolls?.[c.id];
  if (rolls) return rolls[c.id + cardVariantSuffix(c.props)]?.[upgrade];
  return table.cardVariants?.[c.id]?.[upgrade] || table.cards[c.id];
}

function deckLinks(deck, relics) {
  const table = DATA.synergy;
  if (!table) return [];
  const makers = {}, users = {};
  const add = (map, key, who) => { (map[key] = map[key] || new Map()).set(who.id, who); };
  const seen = [
    ...deck.map(c => ({ id: c.id, card: c, name: cardInfo(c.id)?.title || fmtCardLabel(c.id),
      row: cardSynergyRow(c, table) })),
    ...relics.map(r => ({ id: r.id, name: relicInfo(r.id)?.title || fmtRelicLabel(r.id), row: table.relics[r.id] })),
  ];
  seen.forEach(s => {
    if (!s.row) return;
    s.row[0].forEach(k => add(makers, k, s));
    s.row[1].forEach(k => add(users, k, s));
  });
  return Object.keys(makers)
    .map(key => {
      const m = [...makers[key].values()], u = users[key] ? [...users[key].values()] : [];
      // Needs a user that isn't the only maker, or a card would link to itself.
      const feeders = m.filter(x => u.some(y => y.id !== x.id));
      return { key, feeders, users: u.filter(y => feeders.some(x => x.id !== y.id)) };
    })
    // Every deck starts with its starter cards, so a link between starters only says nothing.
    .filter(l => l.feeders.length && l.users.length &&
      [...l.feeders, ...l.users].some(x => cardInfo(x.id)?.rarity !== "Basic"))
    .sort((a, b) => (b.feeders.length + b.users.length) - (a.feeders.length + a.users.length));
}

const escapeHtml = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const synergyLabel = key => key.replace(/^power:/, "").replace(/^./, c => c.toUpperCase());
const SYNERGY_FAMILIES = {
  IRONCLAD: { Strength: ["power:Strength"], Exhaust: ["exhaust", "exhaust skills", "exhaust attacks", "Skill Exhaust"], Block: ["block scaling", "card Block"], "Self-damage": ["HP loss"], Vulnerable: ["power:Vulnerable"] },
  SILENT: { Shiv: ["shiv"], Poison: ["power:Poison"], Discard: ["discard"] },
  DEFECT: { Lightning: ["lightning", "lightning focus", "lightning slots", "lightning evoke", "lightning passive"], Frost: ["frost", "frost focus", "frost slots", "frost evoke", "frost passive"], Dark: ["dark", "dark focus", "dark slots", "dark evoke", "dark passive"], Plasma: ["plasma slots", "plasma evoke", "plasma passive"], "Zero-cost": ["zero-cost", "zero-cost attacks"], Status: ["status"] },
  NECROBINDER: { Doom: ["power:Doom", "Doom application"], Osty: ["Osty health", "Osty attacks", "Osty damage"], Souls: ["souls"], Ethereal: ["ethereal"] },
  REGENT: { Stars: ["stars", "star spending", "star gain", "star-cost cards"], Forge: ["forge", "blade upgrades"], Creation: ["creation", "colorless", "minion"] },
  FOOL: { Shots: ["aim", "shots", "arrows"], Impale: ["impale", "dislodge"], Melodies: ["melodies", "wah melody", "cho melody", "ki melody", "wah cards", "cho cards", "ki cards"], Sadness: ["sadness"], Stretch: ["stretch"] },
};

const overviewSynergies = document.getElementById("overview-synergies");
const overviewSynergyCache = new WeakMap();

// The synergy names a run's final deck has, as the overview table counts them.
function runSynergies(run) {
  if (!overviewSynergyCache.has(run)) {
    const families = Object.entries(SYNERGY_FAMILIES[run.char] || {});
    const names = deckLinks(run.finalDeck || [], run.finalRelics || []).map(({ key }) =>
      families.find(([, keys]) => keys.includes(key))?.[0] || synergyLabel(key));
    overviewSynergyCache.set(run, new Set(names));
  }
  return overviewSynergyCache.get(run);
}

// A synergy row opens Run Detail on the runs it counts: Overview's filters, that
// character, and the synergy as a picked tag (see runHasTag in run-detail.js).
function openSynergyRuns(char, name) {
  const state = { ...liveSharedFilterState(), char };
  detailTags.clear();
  detailTags.add(synergyTag(char, name));
  detailPartners.clear();
  detailActs.clear();
  pageFilterStash = state;
  lastUnlockedChar = char;
  detailSelectedTs = null;
  PAGES.forEach(p => { pageDirty[p] = true; });
  showPage("detail");
  updateUnsavedIndicator();
  document.getElementById("detail-jump-notice").hidden = true;
}

overviewSynergies?.addEventListener("click", e => {
  const b = e.target.closest("[data-synergy-name]");
  if (b) openSynergyRuns(b.dataset.synergyChar, b.dataset.synergyName);
});

function renderOverviewSynergies(runs) {
  if (!overviewSynergies) return;
  const byChar = new Map();
  for (const run of runs) {
    if (typeof run.won !== "boolean") continue;
    for (const name of runSynergies(run)) {
      if (!byChar.has(run.char)) byChar.set(run.char, new Map());
      const records = byChar.get(run.char);
      if (!records.has(name)) records.set(name, [0, 0]);
      records.get(name)[run.won ? 0 : 1]++;
    }
  }
  const characters = [...byChar.keys()].sort((a, b) => fmtCharName(a).localeCompare(fmtCharName(b)));
  overviewSynergies.querySelector(".overview-synergy-grid").innerHTML = characters.map(char => {
    const records = [...byChar.get(char)].sort(([nameA, [winsA, lossesA]], [nameB, [winsB, lossesB]]) =>
      winsB + lossesB - winsA - lossesA || nameA.localeCompare(nameB));
    return `<table class="pivot overview-synergy-table">
      <caption>${charIconHtml(char)} <span class="char-label" style="--char-color:${charColor(char)}">${escapeHtml(fmtCharName(char))}</span></caption>
      <thead><tr><th scope="col">Synergy</th><th scope="col">W–L</th><th scope="col">Win %</th></tr></thead>
      <tbody>${records.map(([name, [wins, losses]]) => {
        const pct = Math.round(wins / (wins + losses) * 100);
        return `<tr><th scope="row"><button type="button" class="osyn-link" data-synergy-char="${escapeHtml(char)}" data-synergy-name="${escapeHtml(name)}" data-tip="Show these runs">${escapeHtml(name)}</button></th><td class="osyn-record"><b class="osyn-w">${wins}</b>–<b class="osyn-l">${losses}</b></td>` +
          `<td class="osyn-pct"><span class="osyn-bar" role="img" aria-label="${pct}% won"><i style="width:${pct}%"></i></span>${pct}%</td></tr>`;
      }).join("")}</tbody>
    </table>`;
  }).join("") || "<p>No detected synergies in the selected runs.</p>";
}

const warnedMissingSynergyArt = new Set();

function renderDeckLinksHtml(deck, relics, character) {
  const links = deckLinks(deck, relics);
  if (!links.length) return "";
  const explanations = {
    "aim": "Aim boosts the next Shot; Heavy Shot multiplies it.",
    "shots": "Shots trigger rewards and enable shooting support.",
    "impale": "Shots Impale enemies for these bonuses and retrievals.",
    "dislodge": "Dislodging triggers energy and Block rewards.",
    "arrows": "Extra or returned Arrows enable more Shots.",
    "melodies": "Wah, Cho, and Ki fuel Melody rewards.",
    "wah melody": "Wah cards enable these Melody bonuses.",
    "cho melody": "Cho cards enable these Melody bonuses.",
    "ki melody": "Ki cards enable these Melody bonuses.",
    "wah cards": "Wah cards supply repeat targets and card-count bonuses.",
    "cho cards": "Cho cards supply repeat targets and card-count bonuses.",
    "ki cards": "Ki cards supply repeat targets and card-count bonuses.",
    "sadness": "Sadness fuels scaling, triggers, and transformation into Joy.",
    "stretch": "Stretch boosts the next card's Block; Cho Ki preserves it.",
    "zero-cost": "These effects retrieve cards costing 0 energy.",
    "zero-cost attacks": "Free Attacks enable damage bonuses and return effects.",
    "creation": "Created cards trigger rewards and scale damage.",
    "block scaling": "Block feeds damage, doubling, retention, and triggered rewards.",
    "HP loss": "Losing your HP triggers rewards and scales damage.",
    "power:Strength": "Strength boosts each hit, including hits from generated Attacks.",
    "power:Vulnerable": "Vulnerable enables these bonuses and scaling effects.",
    "power:Weak": "Weak enables these conditional bonuses.",
    "shiv": "Shivs enable damage bonuses and triggered rewards.",
    "discard": "Discarding triggers rewards and enables Sly plays.",
    "lightning": "Lightning Orbs enable these bonuses and triggers.",
    "frost": "Frost Orbs enable these bonuses and triggers.",
    "dark": "Dark Orbs enable growth and passive triggers.",
    "status": "Status creation fuels these rewards and conversions.",
    "souls": "Souls fuel triggered rewards and damage scaling.",
    "Osty health": "Summon raises Osty's HP for health scaling and alive checks.",
    "Osty attacks": "Osty attacks enable hit rewards, discounts, and attack-card bonuses.",
    "Osty damage": "Calcify increases the damage of Osty's attacks.",
    "forge": "Forge strengthens Sovereign Blade and triggers rewards.",
    "colorless": "Colorless cards enable these specific bonuses.",
    "minion": "Minion cards enable these specific bonuses.",
    "top of Draw Pile": "Stacking the draw pile prepares draws and automatic plays.",
    "star-cost cards": "Cards with star costs increase Crescent Spear's damage.",
    "stars": "Star generation funds these cards' star costs.",
    "star spending": "Playing star-cost cards triggers spending rewards.",
    "star gain": "Gaining stars triggers these rewards and damage scaling.",
    "blade upgrades": "These upgrades add damage, repeats, or Block to Sovereign Blade.",
    "card Block": "These cards supply Block for multipliers that require card-based Block.",
    "exhaust skills": "Exhausting a Skill activates its specific Exhaust rewards.",
    "Skill Exhaust": "Exhausting a Skill, including itself, triggers this reward.",
    "exhaust attacks": "Exhausting this Attack enables it to play from the Exhaust Pile.",
    "exhaust": "Exhausting cards triggers rewards and fuels Exhaust Pile effects.",
    "ethereal": "Ethereal cards enable rewards, replays, and discounts.",
    "power:Doom": "Doom application enables scaling and Doom-based damage.",
    "Doom application": "Applying Doom triggers these rewards, including when applied to yourself.",
    "power:Poison": "Poison enables scaling and additional Poison triggers."
};
  const image = item => {
    const isRelic = item.id.startsWith("RELIC.");
    let src = isRelic ? relicImgSrc(item.id) : cardImgSrc(item.id);
    if (!src && !isRelic) {
      const key = cardFaceKey(item.id, item.card?.upgrade || 0, item.card?.props);
      src = thumbSrc(DATA.cardFinal?.[key] || DATA.cardFinal?.[item.id]);
    }
    if (src) return `<img loading="lazy" src="${escapeHtml(src)}" alt="">`;
    if (!warnedMissingSynergyArt.has(item.id)) {
      warnedMissingSynergyArt.add(item.id);
      console.warn("Missing synergy preview art:", item.id);
    }
    return `<span aria-hidden="true">?</span>`;
  };
  const tile = item => {
    const card = item.card || deck.find(c => c.id === item.id);
    if (!card && item.id.startsWith("RELIC.")) {
      // No card face, and the lane has the room: show the relic's art and text whole.
      const relic = buildRelicTooltip(item.id);
      if (relic) return `<div class="synergy-relic">${relic}</div>`;
    }
    const data = encodeURIComponent(JSON.stringify(card || { id: item.id }));
    const face = card ? renderCardFace(card.id, card.upgrade || 0, "var(--synergy-card-width)", { props: card.props }) : "";
    return `<button type="button" class="synergy-item${face ? " synergy-item-with-face" : ""}${item.id.startsWith("RELIC.") ? " synergy-item-relic" : ""}" data-synergy-item="${data}" aria-label="Inspect ${escapeHtml(item.name)}"><span class="synergy-item-portrait">${image(item)}</span>${face ? `<span class="synergy-item-face">${face}</span>` : ""}<span class="synergy-item-name">${escapeHtml(item.name)}${card?.upgrade > 0 ? " +" : ""}</span></button>`;
  };
  for (const orb of ["lightning", "frost", "dark", "plasma"]) {
    const name = orb[0].toUpperCase() + orb.slice(1);
    explanations[orb + " focus"] = orb === "frost" ? "Focus increases Frost's Block." : `Focus increases ${name}'s damage.`;
    explanations[orb + " slots"] = `Extra slots let you keep more ${name} Orbs before channeling forces an Evoke.`;
    explanations[orb + " evoke"] = `These cards Evoke ${name} Orbs for their immediate effect.`;
    explanations[orb + " passive"] = `These effects trigger ${name}'s passive again.`;
  }
  const connection = link => `<div class="synergy-connection"><div class="synergy-connection-heading"><b>${escapeHtml(synergyLabel(link.key))}</b>
    ${explanations[link.key] ? `<span class="synergy-reason">${escapeHtml(explanations[link.key])}</span>` : ""}</div>
    <div class="synergy-flow" style="--synergy-payoff-columns:${Math.min(3, link.users.length)}"><div><div class="synergy-lane-label">Sources · ${link.feeders.length}</div><div class="synergy-items">${link.feeders.map(tile).join("")}</div></div><span class="synergy-flow-arrow" aria-hidden="true">→</span><div><div class="synergy-lane-label">Payoffs · ${link.users.length}</div><div class="synergy-items">${link.users.map(tile).join("")}</div></div></div></div>`;
  const assigned = new Set();
  const groups = Object.entries(SYNERGY_FAMILIES[character] || {}).map(([name, keys]) => {
    const matches = links.filter(l => keys.includes(l.key));
    matches.forEach(l => assigned.add(l.key));
    return [name, matches];
  }).filter(([, matches]) => matches.length);
  const other = links.filter(l => !assigned.has(l.key));
  if (other.length) groups.push(["More connections", other]);
  const groupHtml = groups.map(([name, matches]) => {
    const items = [...new Map(matches.flatMap(l => [...l.feeders, ...l.users]).map(i => [i.id, i])).values()];
    return `<details class="synergy-archetype"><summary><span class="synergy-preview" aria-hidden="true">${items.slice(0, 3).map(image).join("")}</span><span class="synergy-group-title">${escapeHtml(name)}<small>${matches.length} connection${matches.length === 1 ? "" : "s"} · ${items.length} cards & relics</small></span></summary><div class="synergy-group-body">${matches.map(connection).join("")}</div></details>`;
  }).join("");
  return `<section class="synergy-explorer" style="--synergy-card-width:${TILE_FACE_W}" aria-label="Explore deck synergies"><div class="deck-group-label">Explore synergies <span class="deck-group-count">${links.length} connections</span></div><div class="synergy-groups">${groupHtml}</div></section>`;
}

let synergyInspectTrigger = null;
function showSynergyItemTooltip(button) {
  if (!window.matchMedia("(hover: hover)").matches || document.querySelector(".card-lightbox")) return;
  const item = JSON.parse(decodeURIComponent(button.dataset.synergyItem));
  const html = item.id.startsWith("RELIC.") ? buildRelicTooltip(item.id)
    : buildCardTooltip(item.id, item.upgrade || 0, item.props, item.enchantment);
  showFloatingHtmlTooltip(button, html);
}
document.addEventListener("pointerover", e => {
  const button = e.target.closest("[data-synergy-item]");
  if (e.pointerType === "mouse" && button && !button.contains(e.relatedTarget)) showSynergyItemTooltip(button);
});
document.addEventListener("pointerout", e => {
  const button = e.target.closest("[data-synergy-item]");
  if (button && !button.contains(e.relatedTarget)) hideFloatingHtmlTooltip();
});
document.addEventListener("focusin", e => {
  const button = e.target.closest("[data-synergy-item]");
  if (button) showSynergyItemTooltip(button);
});
document.addEventListener("focusout", e => {
  if (e.target.closest("[data-synergy-item]")) hideFloatingHtmlTooltip();
});
document.addEventListener("click", e => {
  const button = e.target.closest("[data-synergy-item]");
  if (!button) return;
  hideSharedTooltip();
  const item = JSON.parse(decodeURIComponent(button.dataset.synergyItem));
  if (!item.id.startsWith("RELIC.")) {
    openCardLightbox(item);
  } else {
    closeCardLightbox();
    const box = document.createElement("div");
    box.className = "card-lightbox synergy-relic-lightbox";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    box.setAttribute("aria-label", relicInfo(item.id)?.title || item.id);
    box.innerHTML = `<div class="card-lightbox-body">${buildRelicTooltip(item.id)}</div>`;
    box.addEventListener("click", closeCardLightbox);
    document.body.appendChild(box);
    loadDeferredImages(box);
  }
  const box = document.querySelector(".card-lightbox");
  if (box) {
    synergyInspectTrigger = button;
    const close = document.createElement("button");
    close.type = "button";
    close.className = "synergy-inspect-close";
    close.textContent = "Close preview";
    box.prepend(close);
    close.focus();
  }
});

document.addEventListener("keydown", e => {
  if (e.key === "Tab" && synergyInspectTrigger && document.querySelector(".card-lightbox")) {
    e.preventDefault();
    document.querySelector(".synergy-inspect-close")?.focus();
  }
});

// A phone (isSmallPhone(), data.js) can't hover a card, and its three-per-row tiles are small for the
// card's text, so a tap opens the card large, with its enchantment's rule under
// it. Anything tapped (or Escape) closes it. Wider screens draw the cards at
// full size and use hover, so they never get this.

function closeCardLightbox() {
  document.querySelector(".card-lightbox")?.remove();
  if (synergyInspectTrigger) {
    synergyInspectTrigger.focus();
    synergyInspectTrigger = null;
  }
}

function openCardLightbox(card) {
  closeCardLightbox();
  const ench = buildEnchantmentStrip(card.enchantment);
  const box = document.createElement("div");
  box.className = "card-lightbox";
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-modal", "true");
  box.setAttribute("aria-label", "Card preview");
  box.innerHTML = `<div class="card-lightbox-body">${
    renderCardFace(card.id, card.upgrade, "min(86vw, 340px)", { props: card.props })
  }${ench ? `<div class="card-lightbox-ench">${ench}</div>` : ""}</div>`;
  box.addEventListener("click", closeCardLightbox);
  // The enchantment's icon is built deferred (data-src) for hover popups; load it now.
  loadDeferredImages(box);
  document.body.appendChild(box);
}

document.addEventListener("click", e => {
  if (!isSmallPhone()) return;
  const tile = e.target.closest?.(".card-tile-face[data-tile-card]");
  if (!tile) return;
  try { openCardLightbox(JSON.parse(decodeURIComponent(tile.dataset.tileCard))); } catch { /* leave the tile as it is */ }
});
document.addEventListener("keydown", e => { if (e.key === "Escape") closeCardLightbox(); });

// Chrome keeps :hover on whatever sits under a stationary pointer while the
// page scrolls, which can leave a card/relic tooltip pinned to a tile the
// user is no longer really hovering. Suppress hover tooltips during scroll
// until the mouse moves again.
window.addEventListener("scroll", () => document.body.classList.add("suppress-hover-tooltips"), { passive: true });
window.addEventListener("mousemove", () => document.body.classList.remove("suppress-hover-tooltips"));

// Restore tab from URL hash — runs last so all init code has already executed
(function() {
  const { page, runTs, view } = parsePageHash();
  // Keep bare profile URLs intact while rendering their initial Overview.
  if (!PAGES.includes(page)) {
    syncOverviewFilters("overview");
    PAGE_RENDERERS.overview();
    pageDirty.overview = false;
    updateFilterSummary();
    if (window.noteView) noteView(currentPage);
    return;
  }
  if (runTs != null) openRunLink(runTs, view); else showPage(page);
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
  // Six seconds after load, in idle time, or sooner when the pointer or focus reaches
  // the Cards tab. Building ~10k nodes right after first paint delayed
  // everything else on load.
  let cardsPrefetched = false;
  const prefetchCards = () => {
    if (cardsPrefetched) return;
    cardsPrefetched = true;
    if (currentPage === "overview" && pageDirty.cards) {
      // Cards reads the other pages' filters, not Overview's own.
      syncOverviewFilters("cards");
      currentPage = "cards";
      try { renderCardsPage(); } finally { currentPage = "overview"; syncOverviewFilters("overview"); }
      pageDirty.cards = false;
    }
  };
  const tab = document.getElementById("tab-cards");
  if (tab) ["pointerenter", "focus", "touchstart"].forEach(ev =>
    tab.addEventListener(ev, prefetchCards, { once: true, passive: true }));
  setTimeout(() => (window.requestIdleCallback || setTimeout)(prefetchCards), 6000);
}

