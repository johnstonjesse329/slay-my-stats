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
    // data-tile-card: what a phone's tap-to-enlarge needs to draw the card again
    // (see openCardLightbox).
    const tileData = encodeURIComponent(JSON.stringify({ id: c.id, upgrade: c.upgrade, props: c.props, enchantment: c.enchantment }));
    return `<div class="card-tile card-tile-face" data-tile-card="${tileData}">
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

// Higher is rarer; anything unrecognised sorts last.
const RARITY_RANK = { Ancient: 8, Boss: 7, Event: 6, Rare: 5, Uncommon: 4, Common: 3, Shop: 2, Starter: 1 };
function rarityRank(r) { return RARITY_RANK[r] || 0; }

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
  const relicHtml  = renderRelicTiles(relics);

  document.getElementById("detail-deck-relics").innerHTML = `
    <div class="detail-section-heading">Final deck${deckArchetypeHtml(run.char, deck)}</div>${renderDeckLinksHtml(deck, relics)}
    ${groupsHtml}
    <div class="detail-section-heading" style="margin-top:16px">Relics <span class="deck-group-count">${relics.length}</span></div>
    <div class="deck-relic-list">${relicHtml}</div>`;
}

// What the final deck is built around, by the rule in tools/power_curve/archetypes.py:
// count the cards that belong to each of the character's archetypes; the biggest
// names the deck when it has 3 or more, a close second (70% of it, and 3+) makes a pair.
// "Mixed" says nothing, so it isn't shown.
function deckArchetype(char, deck) {
  const sigs = DATA.archetypes && DATA.archetypes[char];
  if (!sigs) return null;
  const score = Object.entries(sigs)
    .map(([name, ids]) => [deck.filter(c => ids.includes(c.id)).length, name])
    .sort((a, b) => b[0] - a[0]);
  if (score.length < 2 || score[0][0] < 3) return null;
  const [[top, a], [second, b]] = score;
  return second >= 3 && second >= 0.7 * top ? `${a} + ${b}` : a;
}

function deckArchetypeHtml(char, deck) {
  const a = deckArchetype(char, deck);
  return a ? ` <span class="deck-group-count">· ${escapeHtml(a)} focused archetype</span>` : "";
}

// Cards and relics in this run that feed each other: one makes a thing (Strength,
// Poison, Osty, Shiv...) and another needs it. Listed, not scored. DATA.synergy
// holds only the specific keys; a key with no maker or no other user is dropped.
function deckLinks(deck, relics) {
  const table = DATA.synergy;
  if (!table) return [];
  const makers = {}, users = {};
  const add = (map, key, who) => { (map[key] = map[key] || new Map()).set(who.id, who); };
  const seen = [
    ...deck.map(c => ({ id: c.id, name: cardInfo(c.id)?.title || fmtCardLabel(c.id), row: table.cards[c.id] })),
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
    .filter(l => l.feeders.length && l.users.length)
    .sort((a, b) => (b.feeders.length + b.users.length) - (a.feeders.length + a.users.length));
}

const escapeHtml = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function renderDeckLinksHtml(deck, relics) {
  const links = deckLinks(deck, relics);
  if (!links.length) return "";
  const names = list => [...new Set(list.map(x => x.name))].map(escapeHtml).join(", ");
  const rows = links.map(l => `<li><b>${escapeHtml(l.key.replace(/^power:/, "").replace(/^./, c => c.toUpperCase()))}</b>: ${names(l.feeders)} → ${names(l.users)}</li>`).join("");
  return `<div class="deck-group-label">Archetype synergies <span class="deck-group-count">${links.length}</span></div>
    <ul class="deck-links">${rows}</ul>`;
}

// A phone can't hover a card, and its three-per-row tiles are small for the
// card's text, so a tap opens the card large, with its enchantment's rule under
// it. Anything tapped (or Escape) closes it. Wider screens draw the cards at
// full size and use hover, so they never get this.
const PHONE_DECK_MQ = window.matchMedia("(max-width: 560px)");

function closeCardLightbox() {
  document.querySelector(".card-lightbox")?.remove();
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
  if (!PHONE_DECK_MQ.matches) return;
  const tile = e.target.closest?.(".card-tile-face[data-tile-card]");
  if (!tile) return;
  try { openCardLightbox(JSON.parse(decodeURIComponent(tile.dataset.tileCard))); } catch { /* leave the tile as it is */ }
});
document.addEventListener("keydown", e => { if (e.key === "Escape") closeCardLightbox(); });

renderPersonalBests();

// Chrome keeps :hover on whatever sits under a stationary pointer while the
// page scrolls, which can leave a card/relic tooltip pinned to a tile the
// user is no longer really hovering. Suppress hover tooltips during scroll
// until the mouse moves again.
window.addEventListener("scroll", () => document.body.classList.add("suppress-hover-tooltips"), { passive: true });
window.addEventListener("mousemove", () => document.body.classList.remove("suppress-hover-tooltips"));

// Restore tab from URL hash — runs last so all init code has already executed
(function() {
  const { page, runTs } = parsePageHash();
  if (!PAGES.includes(page)) return;
  if (runTs != null) openRunLink(runTs); else showPage(page);
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

