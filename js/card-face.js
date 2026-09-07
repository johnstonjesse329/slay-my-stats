// =========================================================================
// Card face — a real card, composited from the baked game chrome
// =========================================================================
// card_chrome/ holds the frame, portrait border, title banner, type plaque
// and energy orbs sliced out of the game's UI atlas with their materials
// already applied (see tools/bake_card_chrome.py). layout.json carries the
// element rects straight from the game's own card.tscn, in a 300x422
// center-anchored logical space, plus the font sizes in those same units.
// So rendering a card is just: place every piece at rect * scale.
//
// Everything degrades to the older hand-drawn CSS tooltip if the bake is
// absent, so a checkout without card_chrome/ still works.

function cardFaceAvailable() {
  const L = DATA.chromeLayout;
  return !!(L && L.rects && L.rects.Frame && L.rects.Portrait
            && Object.keys(DATA.cardChrome || {}).length);
}

// Union of every element rect — the energy orb and title banner overhang the
// frame on the left and top, so the drawing area is bigger than the frame.
// Cached on the function itself, not a module-level let/const: Overview's
// Personal Bests panel now renders card faces during the page's very first
// synchronous render (triggered from page-nav.js, before this file's own
// top-level code has run), and a module-level `let` there is still in its
// temporal dead zone at that point -- the same class of bug as the historical
// NODE_COLORS TDZ issue, but for a value only this function ever needs.
function cardFaceBounds() {
  if (cardFaceBounds._cache) return cardFaceBounds._cache;
  const rects = Object.values(DATA.chromeLayout.rects);
  return (cardFaceBounds._cache = {
    x0: Math.min(...rects.map(r => r[0])), y0: Math.min(...rects.map(r => r[1])),
    x1: Math.max(...rects.map(r => r[2])), y1: Math.max(...rects.map(r => r[3])),
  });
}

function cardFaceAspect() {
  const b = cardFaceBounds();
  return (b.y1 - b.y0) / (b.x1 - b.x0);
}

// A card face renders in three different contexts (deck tile, node-tooltip
// card, hover preview), each its own max size. Picking each one's clamp()
// independently -- as the first pass at this did -- gives each context its
// own vw-breakpoint, so resizing the window shrinks them at different rates
// and points: exactly the "inconsistent sizing" this produces. Deriving every
// clamp from the same breakpoint keeps them shrinking in lockstep (down to
// wherever a given context hits its own min and clamps flat). A plain literal
// inside the function, not a module-level const, for the same early-call
// reason as cardFaceBounds() above.
function cardFaceWidth(minPx, maxPx) {
  const BREAKPOINT = 600;
  const vw = (maxPx / BREAKPOINT * 100).toFixed(3);
  return `clamp(${minPx}px, ${vw}vw, ${maxPx}px)`;
}

// Which baked variant a card uses. Frame colour follows the character pool,
// while banner/border/plaque follow rarity — that split is the game's, not
// ours (card.tscn assigns the two material families separately).
function cardFaceVariant(id) {
  const L = DATA.chromeLayout, info = cardInfo(id) || {};
  const pool = String(info.pool || "colorless").toLowerCase();
  const type = String(info.type || "").toLowerCase();
  const rarity = String(info.rarity || "").toLowerCase();
  return {
    color:  (L.poolToColor || {})[pool] || "colorless",
    sprite: (L.typeToSprite || {})[type] || L.defaultTypeSprite || "skill",
    mat:    (L.rarityToMaterial || {})[rarity] || L.defaultMaterial || "common",
    pool, info,
  };
}

function renderCardFace(id, upgrade = 0, width = 200) {
  if (!cardFaceAvailable()) return "";
  const L = DATA.chromeLayout, R = L.rects, C = DATA.cardChrome;
  const b = cardFaceBounds();
  const BW = b.x1 - b.x0, BH = b.y1 - b.y0;
  // A bare number keeps meaning px for the existing fixed-width call sites;
  // any other CSS length (%, vw, clamp(...)) lets the card scale with its
  // container instead of being pinned to one pixel size.
  const w = typeof width === "number" ? `${width}px` : width;
  const { color, sprite, mat, pool, info } = cardFaceVariant(id);

  // Rect -> CSS box, as a percentage of the card's own bounds box (not the
  // raw 300x422 logical space) so it holds regardless of the card's actual
  // rendered width.
  const box = key => {
    const [l, t, r, bt] = R[key];
    return `left:${((l - b.x0) / BW * 100).toFixed(3)}%;top:${((t - b.y0) / BH * 100).toFixed(3)}%;` +
           `width:${((r - l) / BW * 100).toFixed(3)}%;height:${((bt - t) / BH * 100).toFixed(3)}%`;
  };
  const layer = (key, src, z) => src
    ? `<img class="cf-layer" style="${box(key)};z-index:${z}" src="${src}" alt="">` : "";

  const F = L.fontSizes || { title: 26, description: 21, type: 16, cost: 34 };
  // Font sizes live in the same logical units as the rects, so normalising by
  // BW is the same treatment the rects get above — the result is a container
  // query width unit, which resolves against .cardface's own inline size
  // (see `container-type: inline-size` in dashboard.css).
  const cqw = n => `${(n / BW * 100).toFixed(3)}cqw`;

  const portrait = cardImgSrc(id);
  // Upgrading can change the cost, not just the numbers in the text — 60 cards
  // do (Body Slam 1->0, Barricade 3->2), so an upgraded card that ignored
  // energyUpgraded would show the wrong orb.
  const energy = (upgrade > 0 && info.energyUpgraded != null)
    ? info.energyUpgraded : (info.energy ?? -1);
  const hasCost = info.costsX || energy >= 0;
  const costText = info.costsX ? "X" : String(energy);
  // Curses, statuses and tokens have no cost; the game draws no orb for them.
  const orb = hasCost
    ? (C[`energy_${pool}`] ? `energy_${pool}` : "energy_colorless") : null;

  // The game shows an upgraded card's whole title in green, not a green "+"
  // bolted onto a white name.
  const name = (info.title || fmtCardLabel(id))
    + (upgrade > 0 ? `+${upgrade > 1 ? upgrade : ""}` : "");
  const baseVars = (upgrade > 0 && info.varsUpgraded) ? info.varsUpgraded : info.vars;
  const vars = { ...(baseVars || {}), IfUpgraded: upgrade > 0 ? 1 : 0 };
  // There is no descUpgraded in card_data.json — one desc string serves both
  // forms, and varsUpgraded above is what makes it read differently.
  const desc = info.desc ? substituteDescVars(info.desc, vars) : "";

  return `<div class="cardface" style="width:${w};aspect-ratio:${BW}/${BH}">
    ${portrait ? `<img class="cf-layer cf-portrait" style="${box("Portrait")};z-index:1" src="${portrait}" alt="">` : ""}
    ${layer("Frame",          C[`frame_${sprite}_${color}`], 2)}
    ${layer("PortraitBorder", C[`portrait_border_${sprite}_${mat}`], 3)}
    ${layer("TitleBanner",    C[`banner_${mat}`], 4)}
    ${layer("TypePlaque",     C[`plaque_${mat}`], 5)}
    ${orb ? layer("EnergyIcon", C[orb], 6) : ""}
    <div class="cf-text cf-title${upgrade > 0 ? " cf-upgraded" : ""}" style="${box("TitleLabel")};font-size:${cqw(F.title)};z-index:7"><span>${name}</span></div>
    <div class="cf-text cf-type" style="${box("TypePlaque")};font-size:${cqw(F.type)};z-index:7"><span>${info.type || ""}</span></div>
    ${hasCost ? `<div class="cf-text cf-cost" style="${box("EnergyIcon")};font-size:${cqw(F.cost)};z-index:7"><span>${costText}</span></div>` : ""}
    <div class="cf-text cf-desc" style="${box("DescriptionLabel")};font-size:${cqw(F.description)};z-index:7"><span>${desc.replace(/\n/g, "<br>")}</span></div>
  </div>`;
}

function buildCardTooltip(id, upgrade) {
  // Prefer the real composited card when the chrome bake is present.
  if (cardFaceAvailable()) {
    return `<div class="card-tooltip card-tooltip-face">${renderCardFace(id, upgrade, cardFaceWidth(150, 210))}</div>`;
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
    ? `<div class="ct-art-wrap">${costsHtml}<img class="ct-art" src="${src}" alt="${name}"></div>`
    : `<div class="ct-art-wrap">${costsHtml}<div class="ct-art ct-art-missing"></div></div>`;

  const type = info?.type || null;
  const typePill = type ? `<span class="ct-type-pill">${type}</span>` : "";

  // IfUpgraded isn't a card stat, so it's not in vars — it's the flag behind
  // {{IfUpgraded:show:ALL cards|a card}} and friends. Supply it here, where
  // the upgrade level is actually known.
  const baseVars = (upgrade > 0 && info?.varsUpgraded) ? info.varsUpgraded : info?.vars;
  const vars = { ...(baseVars || {}), IfUpgraded: upgrade > 0 ? 1 : 0 };
  const rawDesc = (upgrade > 0 && info?.descUpgraded) ? info.descUpgraded : info?.desc;
  const desc = rawDesc ? substituteDescVars(rawDesc, vars) : null;
  const descHtml = desc ? `<div class="ct-desc">${desc.replace(/\n/g, "<br>")}</div>` : "";

  return `<div class="card-tooltip">
    ${artHtml}
    <div class="ct-banner">${typePill}<span class="ct-name">${nameLabel}</span></div>
    ${descHtml}
  </div>`;
}

// Width of a deck tile's card face. Big enough for the title and cost to read
// at a glance; the description is suppressed below the .cf-desc container
// query threshold in dashboard.css since it's illegible mush at this scale,
// and the hover tooltip is where you actually read a card.
const TILE_FACE_W = cardFaceWidth(104, 152);

function renderCardTile(c) {
  const info  = cardInfo(c.id);
  const name  = (info && info.title) || fmtCardLabel(c.id);
  // Count is deck state, not card identity, so it stays a badge. The upgrade
  // level does NOT — the card face renders it the way the game does, as a
  // green "Strike+" title, so a separate +1 chip would just repeat it.
  const countLabel = c.count > 1 ? `<span class="tile-count">×${c.count}</span>` : "";

  if (cardFaceAvailable()) {
    return `<div class="card-tile card-tile-face">
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
    ? `<img class="tile-art" src="${src}" alt="${name}">`
    : `<div class="tile-art tile-art-missing">${name.charAt(0)}</div>`;
  const badgesHtml = (upgradeLabel || countLabel)
    ? `<div class="tile-badges">${upgradeLabel}${countLabel}</div>`
    : "";

  return `<div class="card-tile" style="--tile-color:${typeColor}">
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
    if (src) {
      return `<div class="relic-tile">
        <img class="relic-tile-art" src="${src}" alt="${label}">
        <div class="relic-tile-name">${label}</div>
        ${tip ? `<div class="relic-tooltip-wrap">${tip}</div>` : ""}
      </div>`;
    }
    return `<div class="relic-tile relic-tile-no-img">
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

