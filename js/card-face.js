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
  const floors = [...(c.addedFloors || [])].sort(([a], [b]) => a - b);
  const floorLabel = floors.length
    ? `<div class="tile-added-floors">Added ${floors.map(([floor, count]) =>
        `F${floor}${count > 1 ? ` ×${count}` : ""}`).join(" · ")}</div>`
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
    // show. The chip names it; hovering is what says what it does.
    const enchTip = enchLabel
      ? `<div class="card-tooltip-wrap">${buildEnchantmentStrip(c.enchantment)}</div>`
      : "";
    // data-tile-card: what a phone's tap-to-enlarge needs to draw the card again
    // (see openCardLightbox).
    const tileData = encodeURIComponent(JSON.stringify({ id: c.id, upgrade: c.upgrade, props: c.props, enchantment: c.enchantment }));
    return `<div class="card-tile card-tile-face" data-tile-card="${tileData}">
      <div class="tile-face-art">
        ${renderCardFace(c.id, c.upgrade, TILE_FACE_W, { props: c.props })}
        ${(enchLabel || countLabel) ? `<div class="tile-badges">${enchLabel}${countLabel}</div>` : ""}
      </div>
      ${floorLabel}
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
      ${floorLabel}
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
function dedupeCardCounts(deck, added) {
  const cardMap = new Map();
  deck.forEach((c, index) => {
    const ench = c.enchantment ? `${c.enchantment.id}:${c.enchantment.amount || 1}` : "";
    const key = c.id + "|" + c.upgrade + "|" + (c.props ? JSON.stringify(c.props) : "") + "|" + ench;
    if (!cardMap.has(key)) {
      cardMap.set(key, {
        id: c.id, upgrade: c.upgrade, count: 0, props: c.props, enchantment: c.enchantment,
      });
    }
    const row = cardMap.get(key);
    row.count++;
    const floor = added?.[index];
    if (Number.isInteger(floor) && floor >= 1) {
      row.addedFloors ??= new Map();
      row.addedFloors.set(floor, (row.addedFloors.get(floor) || 0) + 1);
    }
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

  const groupsHtml = renderCardGroupsHtml(dedupeCardCounts(deck, run.deckAdded));
  const relicHtml  = renderRelicTiles(relics);

  document.getElementById("detail-deck-relics").innerHTML = `
    ${renderDeckLinksHtml(deck, relics, run.char)}
    ${groupsHtml}
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
function deckLinks(deck, relics) {
  const table = DATA.synergy;
  if (!table) return [];
  const makers = {}, users = {};
  const add = (map, key, who) => { (map[key] = map[key] || new Map()).set(who.id, who); };
  const cardRow = c => {
    const upgrade = c.upgrade > 0 ? 1 : 0;
    const rolls = table.cardRolls?.[c.id];
    if (rolls) return rolls[c.id + cardVariantSuffix(c.props)]?.[upgrade];
    return table.cardVariants?.[c.id]?.[upgrade] || table.cards[c.id];
  };
  const seen = [
    ...deck.map(c => ({ id: c.id, card: c, name: cardInfo(c.id)?.title || fmtCardLabel(c.id),
      row: cardRow(c) })),
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
overviewSynergies?.addEventListener("toggle", () => renderOverviewSynergies(overviewRuns()));

function renderOverviewSynergies(runs) {
  if (!overviewSynergies?.open) return;
  const byChar = new Map();
  for (const run of runs) {
    if (typeof run.won !== "boolean") continue;
    if (!overviewSynergyCache.has(run)) {
      const families = Object.entries(SYNERGY_FAMILIES[run.char] || {});
      const names = deckLinks(run.finalDeck || [], run.finalRelics || []).map(({ key }) =>
        families.find(([, keys]) => keys.includes(key))?.[0] || synergyLabel(key));
      overviewSynergyCache.set(run, new Set(names));
    }
    for (const name of overviewSynergyCache.get(run)) {
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
      <caption>${charIconHtml(char)} ${escapeHtml(fmtCharName(char))}</caption>
      <thead><tr><th scope="col">Synergy</th><th scope="col">Wins</th><th scope="col">Losses</th></tr></thead>
      <tbody>${records.map(([name, [wins, losses]]) =>
        `<tr><th scope="row">${escapeHtml(name)}</th><td>${wins}</td><td>${losses}</td></tr>`).join("")}</tbody>
    </table>`;
  }).join("") || "<p>No detected synergies in the selected runs.</p>";
}

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
    const src = item.id.startsWith("RELIC.") ? relicImgSrc(item.id) : cardImgSrc(item.id);
    return src ? `<img loading="lazy" src="${escapeHtml(src)}" alt="">` : `<span aria-hidden="true">?</span>`;
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
      renderCardsPage();
      pageDirty.cards = false;
    }
  };
  const tab = document.getElementById("tab-cards");
  if (tab) ["pointerenter", "focus", "touchstart"].forEach(ev =>
    tab.addEventListener(ev, prefetchCards, { once: true, passive: true }));
  setTimeout(() => (window.requestIdleCallback || setTimeout)(prefetchCards), 6000);
}

