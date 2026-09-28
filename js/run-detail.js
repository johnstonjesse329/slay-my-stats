// =========================================================================
// Run Detail page
// =========================================================================

const NODE_ICONS = {
  monster:   "⚔",
  elite:     "💀",
  boss:      "👑",
  rest_site: "🔥",
  shop:      "🛒",
  treasure:  "📦",
  unknown:   "❓",
  ancient:   "🗿",
  event:     "❕",
};

// key is what's looked up in DATA.nodeIcons (a node type, or for bosses an
// encounter id like "ENCOUNTER.QUEEN_BOSS"); fallbackType is the plain node
// type used for the emoji/alt-text fallback when no icon URL is found.
function nodeIconHtml(key, size = 18, fallbackType = key) {
  const src = DATA.nodeIcons && DATA.nodeIcons[key];
  if (src) return `<img loading="lazy" class="node-icon-img" src="${src}" width="${size}" height="${size}" alt="${fallbackType}">`;
  return `<span class="node-icon-emoji">${NODE_ICONS[fallbackType] || "❓"}</span>`;
}

// A resolved "?" room's `enc` field says what it turned out to be, except
// when it was a shop or treasure — both leave enc empty, so infer from the
// node's own fields instead. Returns a key into DATA.nodeIcons.
function unknownNodeIconKey(node) {
  const enc = node.enc || "";
  if (enc.startsWith("EVENT.")) return "event";           // a "?" event
  if (/_ELITE$/.test(enc)) return "unknown_elite";         // a "?" elite fight
  if (enc) return "unknown";                               // a "?" normal/weak fight
  // Empty enc: shop or treasure, undistinguished in the save. A shop's own
  // fields (for-sale lists, purchases) win even when relicsRewarded is also
  // set — in the test data, all 27 nodes with both were a shop's for-sale
  // list alongside a bonus relic reward, not a treasure room, so shop wins.
  const isShop = (node.cardsBought && node.cardsBought.length) ||
                 (node.relicsBought && node.relicsBought.length) ||
                 (node.potionsBought && node.potionsBought.length) ||
                 (node.relicsForSale && node.relicsForSale.length) ||
                 (node.potionsForSale && node.potionsForSale.length);
  // The game's "?" variants, not the plain shop/treasure icons, so the
  // timeline still shows it was a "?" room.
  if (isShop) return "unknown_shop";
  if (node.relicsRewarded && node.relicsRewarded.length) return "unknown_treasure";
  return "unknown"; // no signal either way — keep the generic "?" icon
}

const ACT_LABELS = { 1: "Act 1", 2: "Act 2", 3: "Act 3" };

// ---- Filter state ----

let detailSelectedTs  = null;
let detailHpChart     = null;

function getDetailRuns() {
  return filterRuns().sort((a, b) => b.ts - a.ts);
}

// ---- Run list ----

function renderDetailRunList() {
  const runs = getDetailRuns();
  const container = document.getElementById("detail-run-list");

  if (runs.length === 0) {
    container.innerHTML = `<div style="color:#8a8aa0;padding:1rem;font-size:0.85rem">No runs match the current filters.</div>`;
    return;
  }

  const fmtDate = ts => { const d = new Date(ts * 1000); return `${d.getMonth()+1}/${d.getDate()}/${String(d.getFullYear()).slice(-2)}`; };

  container.innerHTML = `<div class="detail-run-header-row">
    <span class="dot" style="visibility:hidden;flex-shrink:0"></span>
    <span class="detail-run-char">Char</span>
    <span class="detail-run-asc">Asc</span>
    <span class="detail-run-won">W/L</span>
    <span class="detail-run-floor">Floor</span>
    <span class="detail-run-date">Date</span>
  </div>` + runs.map((run, i) => {
    const color  = CHAR_COLOR_MAP[run.char] || "#a0a0b8";
    const won    = run.won;
    const label  = fmtCharName(run.char);
    const active = run.ts === detailSelectedTs;
    return `<div class="detail-run-item${active ? " active" : ""}" data-ts="${run.ts}" tabindex="0">
      <span class="dot" style="background:${color};flex-shrink:0"></span>
      <span class="detail-run-char">${label}</span>
      <span class="detail-run-asc" style="color:#bcbcd0">A${run.asc}</span>
      <span class="detail-run-won" style="color:${won ? "#5cba7d" : "#e05c5c"}">${won ? "W" : "L"}</span>
      <span class="detail-run-floor" style="color:#bcbcd0">F${run.floor}</span>
      <span class="detail-run-date" style="color:#8a8aa0">${fmtDate(run.ts)}</span>
    </div>`;
  }).join("");

  container.querySelectorAll(".detail-run-item").forEach(el => {
    el.addEventListener("click", () => {
      const ts = +el.dataset.ts;
      const run = DATA.runsData.find(r => r.ts === ts);
      if (!run) return;
      detailSelectedTs = ts;
      container.querySelectorAll(".detail-run-item").forEach(r => r.classList.toggle("active", +r.dataset.ts === ts));
      renderDetailRun(run);
    });
    bindEnterSpace(el);
  });

  // Render whichever run is currently selected — falls back to the first
  // run if nothing is selected or the prior selection isn't in this list
  // (e.g. filters changed). A caller can pre-set detailSelectedTs before
  // switching to this page (see jumpToRun) to land directly on a specific
  // run instead of always defaulting to the first.
  const selected = runs.find(r => r.ts === detailSelectedTs) || runs[0];
  detailSelectedTs = selected.ts;
  container.querySelector(`.detail-run-item[data-ts="${selected.ts}"]`).classList.add("active");
  renderDetailRun(selected);
}

// ---- Run header ----

function renderDetailRun(run) {
  document.getElementById("detail-placeholder").style.display = "none";
  document.getElementById("detail-content").style.display = "";

  const color  = CHAR_COLOR_MAP[run.char] || "#a0a0b8";
  const won    = run.won;
  const label  = fmtCharName(run.char);
  const fmtDate = ts => new Date(ts * 1000).toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });

  const tl = run.timeline || [];
  const totalRemoves     = tl.reduce((n, node) => n + (node.cardsRemoved || []).length, 0);
  const totalShopRemoves = tl.reduce((n, node) => n + (node.type === "shop" ? (node.cardsRemoved || []).length : 0), 0);
  const totalPotionsBought = tl.reduce((n, node) => n + (node.potionsBought  || []).length, 0);
  // Every potion that entered inventory: reward pickups (potionsRewarded) plus
  // shop purchases (potionsBought) — i.e. all potion_choices where was_picked.
  // potion_used / potion_discarded are NOT embedded per node, so consumption
  // isn't surfaced here without a run.py data change.
  const totalPotionsGained = tl.reduce((n, node) => n + (node.potionsRewarded || []).length + (node.potionsBought || []).length, 0);
  const totalRelicsBought  = tl.reduce((n, node) => n + (node.relicsBought   || []).length, 0);
  const cardsBoughtIds     = tl.reduce((arr, node) => arr.concat(node.cardsBought || []), []);
  const totalColorlessBought = cardsBoughtIds.filter(id => cardInfo(id)?.pool === "colorless").length;
  const totalOtherCardsBought = cardsBoughtIds.length - totalColorlessBought;
  const countType = type => tl.filter(n => n.type === type).length;
  const totalDmg    = tl.reduce((s, n) => s + (n.dmg       || 0), 0);
  const totalHealed = tl.reduce((s, n) => s + (n.healed    || 0), 0);
  const totalGold   = tl.reduce((s, n) => s + (n.goldGained|| 0), 0);
  const ancientRelics = tl.filter(n => n.type === "ancient" && n.relicPicked).map(n => n.relicPicked);
  const elitesKilled = (run.fights || []).filter(f => f.type === "elite" && f.won).length;

  const finalDeck   = run.finalDeck   || [];
  const finalRelics = run.finalRelics || [];

  let cardsTitle = "";
  if (finalDeck.length > 0) {
    const rarityOrder = ["Starter", "Common", "Uncommon", "Rare"];
    const byCounts = {};
    finalDeck.forEach(c => {
      const r = cardInfo(c.id)?.rarity || "Unknown";
      byCounts[r] = (byCounts[r] || 0) + 1;
    });
    cardsTitle = rarityOrder.filter(r => byCounts[r]).map(r => `${byCounts[r]} ${r}`).join(", ");
  }
  let relicsTitle = "";
  if (finalRelics.length > 0) {
    const relicRarityOrder = ["Starter", "Common", "Uncommon", "Rare", "Boss", "Event", "Ancient"];
    const byCounts = {};
    finalRelics.forEach(r => {
      const id = r?.id || r;
      const info = DATA.relicData && DATA.relicData[id];
      const rarity = info?.rarity || "Unknown";
      byCounts[rarity] = (byCounts[rarity] || 0) + 1;
    });
    relicsTitle = relicRarityOrder.filter(r => byCounts[r]).map(r => `${byCounts[r]} ${r}`).join(", ");
  }

  const headlineStats = [
    { label: "Elites", value: elitesKilled },
    { label: "Cards",  value: finalDeck.length,   title: cardsTitle },
    { label: "Relics", value: finalRelics.length,  title: relicsTitle },
    { label: "Gold", value: totalGold },
  ];
  const headlineHtml = headlineStats.map(i =>
    `<span class="run-headline-stat"${i.title ? ` data-tip="${i.title}"` : ""}><span class="run-headline-value">${i.value}</span><span class="run-headline-label">${i.label}</span></span>`
  ).join("");

  const statItems = [
    { label: "Fights", value: countType("monster") },
    { label: "Events", value: countType("unknown") },
    { label: "Rest sites",  value: countType("rest_site") },
    { label: "Shops",  value: countType("shop") },
  ];
  if (totalRemoves > 0) statItems.push({ label: "Total removes", value: totalRemoves });

  const purchaseItems = [
    totalColorlessBought  > 0 ? { label: "Colorless bought", value: totalColorlessBought }  : null,
    totalOtherCardsBought > 0 ? { label: "Cards bought",     value: totalOtherCardsBought } : null,
    totalPotionsBought    > 0 ? { label: "Potions bought",   value: totalPotionsBought }    : null,
    totalRelicsBought     > 0 ? { label: "Relics bought",    value: totalRelicsBought }     : null,
    totalShopRemoves      > 0 ? { label: "Shop removes",     value: totalShopRemoves }      : null,
  ].filter(Boolean);

  const summaryItems = [
    { label: "Damage taken", value: totalDmg },
    { label: "HP healed",    value: totalHealed },
    { label: "Potions gained", value: totalPotionsGained },
  ];

  const statHtml = items => items.map(i =>
    `<span class="run-summary-stat"><span class="run-summary-label">${i.label}</span><span class="run-summary-value">${i.value}</span></span>`
  ).join("");

  // Same rich hover tooltip (portrait, rarity, description) as the Relics
  // grid further down the page, not the old plain-text data-tip bubble --
  // a one-line description doesn't tell you what an ancient boon actually
  // does. .run-boon-wrap right-aligns the popup instead of centering it,
  // since these icons sit at the header's right edge and a centered 180px
  // tooltip would run off the viewport there.
  const ancientBoonsHtml = ancientRelics.length > 0
    ? `<span class="run-summary-stat"><span class="run-summary-label">Ancient boons</span>${ancientRelics.map(id => {
        const src = relicImgSrc(id);
        const tip = buildRelicTooltip(id);
        const iconHtml = src
          ? `<img loading="lazy" class="run-boon-icon" src="${src}" alt="${fmtRelicLabel(id)}">`
          : `<span class="run-summary-value">${fmtRelicLabel(id)}</span>`;
        // tabindex: same touch/keyboard tooltip-reveal parity as .relic-tile.
        return `<span class="run-boon-wrap" tabindex="0">${iconHtml}${tip ? `<span class="relic-tooltip-wrap">${tip}</span>` : ""}</span>`;
      }).join("")}</span>`
    : "";

  const allGroups = [statItems, purchaseItems, summaryItems].filter(g => g.length > 0);
  const statsInner = allGroups.map(statHtml).join(`<span class="run-header-stat-divider"></span>`)
    + (ancientBoonsHtml ? `<span class="run-header-stat-divider"></span>${ancientBoonsHtml}` : "");
  // Fights/events/shop counts, buys and damage/healing totals would stretch
  // the header into a wall of small text — the big numbers above (elites,
  // cards, relics, gold) are the at-a-glance story. Tuck the rest behind a
  // native disclosure so it's one tap away rather than always on screen.
  const summaryHtml = statsInner
    ? `<details class="run-detail-stats"><summary>Damage, fights &amp; purchases</summary><div class="run-detail-stats-body">${statsInner}</div></details>`
    : "";

  document.getElementById("detail-run-header").innerHTML = `
    <div class="detail-run-header-bar">
      <span class="dot" style="background:${color};width:14px;height:14px"></span>
      <span style="font-weight:700;font-size:1.1rem">${label}</span>
      <span style="color:#bcbcd0">A${run.asc}</span>
      <span style="color:${won ? "#5cba7d" : "#e05c5c"};font-weight:600">${won ? "Victory" : "Defeat"}</span>
      <span style="color:#bcbcd0">Floor ${run.floor}</span>
      <span style="color:#bcbcd0">${fmtHrsMin(run.mins)}</span>
      <span style="color:#8a8aa0;font-size:0.85rem">${fmtDate(run.ts)}</span>
      ${run.seed ? `<span style="color:#8a8aa0;font-size:0.82rem;font-family:monospace">Seed: ${run.seed}</span>` : ""}
    </div>
    <div class="detail-run-headline-stats">
      ${headlineHtml}
    </div>
    <div class="detail-run-header-stats">
      ${summaryHtml}
    </div>`;

  renderDetailTimeline(run);
  renderDetailHpChart(run);
  renderDetailGoldChart(run);
  renderDetailDeckRelics(run);
}

// ---- Timeline ----

// Pre-compute avg damage per encounter across all runs (uses fights[] which covers elites/bosses;
// for regular monsters we fall back to scanning timeline arrays).
const _encAvgDmg = (() => {
  const sums = {}, counts = {};
  DATA.runsData.forEach(r => {
    (r.fights || []).forEach(f => {
      if (!f.enc) return;
      sums[f.enc] = (sums[f.enc] || 0) + f.dmg;
      counts[f.enc] = (counts[f.enc] || 0) + 1;
    });
    // Also capture regular monsters from timeline
    (r.timeline || []).forEach(n => {
      if (!n.enc || n.type === "elite" || n.type === "boss") return;
      sums[n.enc] = (sums[n.enc] || 0) + n.dmg;
      counts[n.enc] = (counts[n.enc] || 0) + 1;
    });
  });
  const out = {};
  Object.keys(sums).forEach(k => { out[k] = sums[k] / counts[k]; });
  return out;
})();

function fmtNodeLabel(id) {
  if (!id) return "";
  if (DATA.encLabels && DATA.encLabels[id]) return DATA.encLabels[id];
  return id.replace(/^[A-Z]+\./, "").replace(/_/g, " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}

function fmtCardLabel(id) {
  if (!id) return id;
  if (DATA.cardLabels && DATA.cardLabels[id]) return DATA.cardLabels[id];
  return id.replace(/^CARD\./, "").replace(/_/g, " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}

function fmtRelicLabel(id) {
  if (!id) return id;
  if (DATA.relicLabels && DATA.relicLabels[id]) return DATA.relicLabels[id];
  return id.replace(/^RELIC\./, "").replace(/_/g, " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}

function cardImgSrc(id) {
  if (!id || !DATA.cardImages) return null;
  let stem = id.replace(/^CARD\./, "").toLowerCase();
  if (DATA.cardImageOverrides && DATA.cardImageOverrides[stem]) stem = DATA.cardImageOverrides[stem];
  return DATA.cardImages[stem] || null;
}

const _TYPE_COLORS = {
  Attack: "#a03030",
  Skill:  "#2a5a8a",
  Power:  "#5a3a8a",
  Curse:  "#4a3828",
  Status: "#3a3a28",
};
const _TYPE_DEFAULT = "#3f4147";

function cardTypeColor(id) {
  const info = cardInfo(id);
  return _TYPE_COLORS[info?.type] || _TYPE_DEFAULT;
}

function buildNodeTooltip(node) {
  // Small art beside each named item, so a floor's rewards read at a glance
  // instead of as a wall of text. Cards get the real card face; relics and
  // potions get their own icons.
  const fmtPotion = fmtPotionLabel;
  const iconRow = (cls, src, label, extra = "") =>
    `<div class="${cls} nt-item">${src ? `<img loading="lazy" class="nt-item-icon" src="${src}" alt="">` : ""}<span>${label}</span>${extra}</div>`;
  const nodeCardHtml = (id, dim = false) => cardFaceAvailable()
    ? `<div class="nt-cardface${dim ? " nt-cardface-dim" : ""}">${renderCardFace(id, 0, cardFaceWidth(84, 128))}</div>`
    : `<div class="${dim ? "nt-skipped" : "nt-reward-card"}">${fmtCardLabel(id)}</div>`;
  // Wraps a group of cards in one flex row so they lay out side by side
  // (wrapping onto further rows as needed) instead of stacking one per line.
  const cardRow = (ids, dim = false) =>
    ids.length ? `<div class="nt-cardrow">${ids.map(id => nodeCardHtml(id, dim)).join("")}</div>` : "";
  const lines = [];
  lines.push(`<div class="nt-floor">Floor ${node.floor + 1}</div>`);

  const hpStr  = `${node.hpAfter}/${node.maxHp} HP`;
  const goldStr = node.gold != null ? `  ·  ${node.gold} Gold` : "";
  lines.push(`<div class="nt-hp-gold">${hpStr}${goldStr}</div>`);

  if (node.enc) {
    lines.push(`<div class="nt-enc">${fmtNodeLabel(node.enc)}</div>`);
  }
  if (node.dmg > 0) {
    lines.push(`<div class="nt-dmg">${node.dmg} Damage</div>`);
  }
  if (node.enc && node.enc.startsWith("ENCOUNTER.") && _encAvgDmg[node.enc] != null) {
    lines.push(`<div class="nt-avg-dmg">(${Math.round(_encAvgDmg[node.enc])} dmg taken on avg)</div>`);
  }
  if (node.healed > 0) {
    lines.push(`<div class="nt-heal">Healed for ${node.healed} HP</div>`);
  }
  if (node.turns > 0) {
    lines.push(`<div class="nt-turns">${node.turns} Turn${node.turns !== 1 ? "s" : ""}</div>`);
  }
  if (node.restChoice) {
    const rc = node.restChoice;
    const upgNames = (node.upgradedCards || []).map(id => fmtCardLabel(id)).join(", ");
    const rcLabel = rc === "HEAL" ? "Rest (Heal)"
      : rc === "SMITH" ? (upgNames ? `Smith — ${upgNames}` : "Smith (upgrade a card)")
      : rc.charAt(0) + rc.slice(1).toLowerCase();
    lines.push(`<div class="nt-rest">${rcLabel}</div>`);
  }

  const isShop = node.type === "shop";

  if (isShop) {
    // Cards: bought (highlighted) + for sale (dimmed)
    const cardsBought  = node.cardsBought  || [];
    const cardsForSale = node.cardsSkipped || [];
    if (cardsBought.length + cardsForSale.length > 0) {
      lines.push(`<div class="nt-section">Cards:</div>`);
      cardsBought.forEach(id => lines.push(`<div class="nt-reward-card">${fmtCardLabel(id)} <span class="nt-bought-tag">bought</span></div>`));
      lines.push(cardRow(cardsForSale, true));
    }
    // Relics: bought + for sale
    const relicsBought  = node.relicsBought || [];
    const relicsForSale = node.relicsForSale || [];
    if (relicsBought.length + relicsForSale.length > 0) {
      lines.push(`<div class="nt-section">Relics:</div>`);
      relicsBought.forEach(id => lines.push(iconRow("nt-reward-relic", relicImgSrc(id), fmtRelicLabel(id), ` <span class="nt-bought-tag">bought</span>`)));
      relicsForSale.forEach(id => lines.push(iconRow("nt-skipped", relicImgSrc(id), fmtRelicLabel(id))));
    }
    // Potions: bought + for sale
    const potionsBought  = node.potionsBought  || [];
    const potionsForSale = node.potionsForSale || [];
    if (potionsBought.length + potionsForSale.length > 0) {
      lines.push(`<div class="nt-section">Potions:</div>`);
      potionsBought.forEach(id => lines.push(iconRow("nt-reward-card", potionImgSrc(id), fmtPotion(id), ` <span class="nt-bought-tag">bought</span>`)));
      potionsForSale.forEach(id => lines.push(iconRow("nt-skipped", potionImgSrc(id), fmtPotion(id))));
    }
  } else {
    const cardsRewarded   = node.cardsRewarded   || [];
    const relicsRewarded  = node.relicsRewarded  || [];
    const potionsRewarded = node.potionsRewarded || [];
    const hasRewards = cardsRewarded.length > 0 || relicsRewarded.length > 0 || potionsRewarded.length > 0;
    const hasSkipped = node.cardsSkipped && node.cardsSkipped.length > 0;
    if (hasRewards) {
      lines.push(`<div class="nt-section">Rewards:</div>`);
      lines.push(cardRow(cardsRewarded));
      relicsRewarded.forEach(id  => lines.push(iconRow("nt-reward-relic", relicImgSrc(id), fmtRelicLabel(id))));
      potionsRewarded.forEach(id => lines.push(iconRow("nt-reward-card", potionImgSrc(id), fmtPotion(id))));
    }
    if (hasSkipped) {
      lines.push(`<div class="nt-section">Skipped:</div>`);
      lines.push(cardRow(node.cardsSkipped, true));
    }
  }

  if ((node.cardsRemoved || []).length > 0) {
    lines.push(`<div class="nt-section">Removed:</div>`);
    lines.push(cardRow(node.cardsRemoved, true));
  }

  return lines.join("");
}

const TYPE_LABEL = {
  monster:   "Fights",
  elite:     "Elites",
  boss:      "Bosses",
  rest_site: "Rest sites",
  shop:      "Shops",
  treasure:  "Treasures",
  unknown:   "Events",
  ancient:   "Ancient Boons",
};
const TYPE_ORDER = ["elite","rest_site","unknown","monster","shop"];

function actCountPills(actNodes) {
  return TYPE_ORDER
    .map(type => ({ type, n: actNodes.filter(n => n.type === type).length }))
    .filter(r => r.n > 0)
    .map(r => `<span class="act-count-pill">${r.n} ${TYPE_LABEL[r.type]}</span>`)
    .join("");
}

function renderDetailTimeline(run) {
  const nodes = run.timeline || [];
  if (nodes.length === 0) {
    document.getElementById("detail-timeline").innerHTML = `<div style="color:#8a8aa0;padding:1rem">No timeline data for this run.</div>`;
    return;
  }

  const acts = {};
  nodes.forEach(node => {
    if (!acts[node.act]) acts[node.act] = [];
    acts[node.act].push(node);
  });

  const actNums = Object.keys(acts).map(Number).sort();

  const iconLegend = ["monster", "elite", "boss", "rest_site", "shop", "treasure", "unknown", "ancient"]
    .map(t => `<span class="timeline-legend-item">${nodeIconHtml(t, 14)} ${TYPE_LABEL[t]}</span>`)
    .join("");
  const legend = `<div class="timeline-legend">${iconLegend}<span class="timeline-legend-item"><span class="node-ind card-ind">[C]</span> Card picked</span><span class="timeline-legend-item"><span class="node-ind relic-ind">[R]</span> Relic picked</span></div>`;

  const html = legend + actNums.map(actNum => {
    const actNodes = acts[actNum];
    const nodeCards = actNodes.map(node => {
      // Boss nodes show the specific boss's portrait (keyed by encounter id)
      // when one exists, falling back to the generic crown emoji otherwise.
      // Ancient nodes work the same way but fall back to the generic Ancient
      // icon (not emoji) when a specific portrait isn't found. "?" rooms pick
      // their icon from how they resolved (see unknownNodeIconKey).
      const iconKey =
        node.type === "boss" && node.enc ? node.enc :
        node.type === "ancient" ? (node.enc && DATA.nodeIcons && DATA.nodeIcons[node.enc] ? node.enc : "ancient") :
        node.type === "unknown" ? unknownNodeIconKey(node) :
        node.type;
      const icon    = nodeIconHtml(iconKey, 30, node.type);
      const hasDmg  = node.dmg > 0;
      const hpClass = hasDmg ? "node-hp damaged" : "node-hp";
      const hpText  = `${node.hpAfter} HP`;

      const indicators = [];
      if (node.cardPicked)
        indicators.push(`<span class="node-ind card-ind" data-tip="Card: ${fmtCardLabel(node.cardPicked)}">[C]</span>`);
      if (node.relicPicked) indicators.push(`<span class="node-ind relic-ind" data-tip="Relic: ${fmtRelicLabel(node.relicPicked)}">[R]</span>`);

      const tooltip = buildNodeTooltip(node);

      return `<div class="node-card node-type-${node.type}" tabindex="0">
        <div class="node-floor">F${node.floor + 1}</div>
        <div class="node-icon">${icon}</div>
        <div class="${hpClass}">${hpText}</div>
        <div class="node-indicators">${indicators.join("")}</div>
        <div class="node-tooltip">${tooltip}</div>
      </div>`;
    }).join("");

    return `<div class="timeline-act">
      <div class="timeline-act-header">
        <span class="timeline-act-label">${ACT_LABELS[actNum] || `Act ${actNum}`}</span>
        <span class="timeline-act-counts">${actCountPills(actNodes)}</span>
      </div>
      <div class="timeline-row">${nodeCards}</div>
    </div>`;
  }).join("");

  document.getElementById("detail-timeline").innerHTML = html;
}

// ---- Shared vertical-line plugin ----

function makeVlinePlugin(nodes, matchFn, color) {
  const indices = nodes.reduce((arr, n, i) => { if (matchFn(n)) arr.push(i); return arr; }, []);
  return {
    id: "vlines",
    afterDatasetsDraw(chart) {
      const { ctx, chartArea: { top, bottom }, scales: { x } } = chart;
      ctx.save();
      ctx.setLineDash([3, 4]);
      ctx.lineWidth = 1;
      indices.forEach(i => {
        const px = x.getPixelForValue(i);
        ctx.strokeStyle = color;
        ctx.beginPath();
        ctx.moveTo(px, top);
        ctx.lineTo(px, bottom);
        ctx.stroke();
      });
      ctx.restore();
    },
  };
}

// Dotted act-boundary lines with "Act N" labels, drawn where the act of
// consecutive nodes changes — mirrors the act grouping of the timeline rows
function makeActBoundaryPlugin(nodes) {
  const bounds = [];
  nodes.forEach((n, i) => {
    if (i > 0 && n.act !== nodes[i - 1].act) bounds.push({ index: i, act: n.act });
  });
  return {
    id: "actBounds",
    afterDatasetsDraw(chart) {
      const { ctx, chartArea: { top, bottom }, scales: { x } } = chart;
      ctx.save();
      ctx.setLineDash([3, 4]);
      ctx.lineWidth = 1;
      ctx.strokeStyle = "#8a8aa088";
      ctx.font = "10px sans-serif";
      ctx.fillStyle = "#8a8aa0";
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      bounds.forEach(({ index, act }) => {
        const px = x.getPixelForValue(index);
        ctx.beginPath();
        ctx.moveTo(px, top);
        ctx.lineTo(px, bottom);
        ctx.stroke();
        ctx.fillText(`Act ${act}`, px + 3, top + 2);
      });
      ctx.restore();
    },
  };
}

// ---- HP chart ----

// Shared tooltip chrome for the Run Detail HP and Gold charts
function renderDetailHpChart(run) {
  const nodes = run.timeline || [];
  if (nodes.length === 0) {
    document.getElementById("detail-hp-box").style.display = "none";
    return;
  }
  document.getElementById("detail-hp-box").style.display = "";

  const color = CHAR_COLOR_MAP[run.char] || "#a0a0b8";
  const labels = nodes.map(n => `F${n.floor + 1}`);
  const hpData = nodes.map(n => n.hpAfter);
  const maxHpData = nodes.map(n => n.maxHp);

  if (detailHpChart) { detailHpChart.destroy(); detailHpChart = null; }

  const ctx = document.getElementById("detail-hp-chart").getContext("2d");
  detailHpChart = new Chart(ctx, {
    type: "line",
    plugins: [makeVlinePlugin(nodes, n => n.type === "elite" || n.type === "boss", "#e05c5c66"), makeActBoundaryPlugin(nodes)],
    data: {
      labels,
      datasets: [
        {
          label: "HP",
          data: hpData,
          borderColor: color,
          backgroundColor: color + "22",
          borderWidth: 2,
          pointRadius: 3,
          pointHoverRadius: 5,
          fill: true,
          tension: 0.2,
        },
        {
          label: "Max HP",
          data: maxHpData,
          borderColor: "#555",
          borderDash: [4, 4],
          borderWidth: 1,
          pointRadius: 0,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: "#ccc", boxWidth: 14 } },
        tooltip: {
          // The "Max HP" dataset only exists to draw the dashed reference
          // line — its value is already shown as the "/maxHp" half of the
          // HP line below, so it's filtered out here rather than shown as
          // its own redundant "Max HP: 99" row.
          filter: item => item.dataset.label !== "Max HP",
          callbacks: {
            title: items => {
              const idx = items[0].dataIndex;
              const node = nodes[idx];
              const enc = node.enc ? fmtNodeLabel(node.enc) : (NODE_ICONS[node.type] || "?") + " " + (node.type || "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
              return `Floor ${node.floor + 1} — ${enc}`;
            },
            label: item => `HP: ${item.raw}/${nodes[item.dataIndex].maxHp}`,
          },
        },
      },
      scales: {
        x: {
          ticks: { color: "#8a8aa0", maxTicksLimit: 20 },
          grid:  { color: "#2e3035" },
        },
        y: {
          ticks: { color: "#ccc" },
          grid:  { color: "#2e3035" },
          min: 0,
        },
      },
    },
  });
}

// ---- Gold chart ----

let detailGoldChart = null;

function renderDetailGoldChart(run) {
  const nodes = (run.timeline || []).filter(n => n.gold != null);
  if (nodes.length === 0) {
    document.getElementById("detail-gold-box").style.display = "none";
    return;
  }
  document.getElementById("detail-gold-box").style.display = "";

  const labels   = nodes.map(n => `F${n.floor + 1}`);
  const goldData = nodes.map(n => n.gold);

  if (detailGoldChart) { detailGoldChart.destroy(); detailGoldChart = null; }

  const ctx = document.getElementById("detail-gold-chart").getContext("2d");
  detailGoldChart = new Chart(ctx, {
    type: "line",
    plugins: [makeVlinePlugin(nodes, n => n.type === "shop" || (n.type === "unknown" && n.enc.startsWith("EVENT.")), "#e0c46855"), makeActBoundaryPlugin(nodes)],
    data: {
      labels,
      datasets: [{
        label: "Gold",
        data: goldData,
        borderColor: "#e0c468",
        backgroundColor: "#e0c46822",
        borderWidth: 2,
        pointRadius: 2,
        pointHoverRadius: 5,
        fill: true,
        tension: 0.2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: "#ccc", boxWidth: 14 } },
        tooltip: {
          callbacks: {
            title: items => {
              const idx = items[0].dataIndex;
              const node = nodes[idx];
              const enc = node.enc ? fmtNodeLabel(node.enc) : (node.type || "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
              return `Floor ${node.floor + 1} — ${enc}`;
            },
            label: item => `Gold: ${item.raw}`,
          },
        },
      },
      scales: {
        x: { ticks: { color: "#8a8aa0", maxTicksLimit: 20 }, grid: { color: "#2e3035" } },
        y: { ticks: { color: "#ccc" }, grid: { color: "#2e3035" }, min: 0 },
      },
    },
  });
}

// ---- Final deck + relics ----

const CARD_TYPE_ORDER  = ["Attack", "Skill", "Power", "Status", "Curse", "Quest", "None"];
const CARD_TYPE_COLOR  = {
  Attack: "#b84040",
  Skill:  "#3a6ea8",
  Power:  "#6a3fa0",
  Status: "#555",
  Curse:  "#3f4147",
  Quest:  "#7a6020",
  None:   "#444",
};

function cardInfo(id) {
  return (DATA.cardData && DATA.cardData[id]) || null;
}

function relicInfo(id) {
  return (DATA.relicData && DATA.relicData[id]) || null;
}

// A known item with no art (DEPRECATED_RELIC, DEPRECATED_POTION, MOCK_*
// test potions — the game ships none for them) gets the "?" event icon, so
// it still renders as an icon with its tooltip instead of a bare text label.
// Unknown ids stay null: with no tooltip to name them, the text label is better.
function artOrPlaceholder(info) {
  if (!info) return null;
  return info.imagePath || (DATA.nodeIcons && DATA.nodeIcons.event) || null;
}

function relicImgSrc(id) {
  return artOrPlaceholder(relicInfo(id));
}

function potionInfo(id) {
  return (DATA.potionData && DATA.potionData[id]) || null;
}

function potionImgSrc(id) {
  return artOrPlaceholder(potionInfo(id));
}

// Prefer the game's own localized name. The id-prettifying fallback gets the
// casing wrong wherever a real title contains a small word or punctuation
// ("Potion Of Binding" vs "Potion of Binding").
function fmtPotionLabel(id) {
  if (!id) return id;
  const info = potionInfo(id);
  if (info && info.title) return info.title;
  return id.replace(/^POTION\./, "").replace(/_/g, " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}

function buildPotionTooltip(id) {
  const info = potionInfo(id);
  if (!info) return "";
  const name = info.title || fmtPotionLabel(id);
  const src  = potionImgSrc(id);
  const rarColor = { Common: "#ccc", Uncommon: "#aad4ff", Rare: "#ffd700", Event: "#c49fe8" }[info.rarity] || "#bcbcd0";
  const desc = substituteDescVars(info.desc || "", info.vars);
  return `<div class="relic-tooltip">
    ${src ? `<img loading="lazy" class="rt-art" src="${src}" alt="${name}">` : ""}
    <div class="rt-header">${name}${info.rarity ? `<div class="rt-rarity" style="color:${rarColor}">${info.rarity}</div>` : ""}</div>
    ${desc ? `<div class="rt-desc">${desc.replace(/\n/g, "<br>")}</div>` : ""}
  </div>`;
}

function buildRelicTooltip(id) {
  const info = relicInfo(id);
  if (!info) return "";
  const name = info.title || fmtRelicLabel(id);
  const src  = relicImgSrc(id);
  const rarColor = { Common: "#ccc", Uncommon: "#aad4ff", Rare: "#ffd700", Boss: "#e88", Starter: "#bcbcd0" }[info.rarity] || "#bcbcd0";
  const rawDesc = info.desc || "";
  const desc = substituteDescVars(rawDesc, info.vars);
  const artHtml = src ? `<img loading="lazy" class="rt-art" src="${src}" alt="${name}">` : "";
  const rarHtml = info.rarity ? `<div class="rt-rarity" style="color:${rarColor}">${info.rarity}</div>` : "";
  const descHtml = desc ? `<div class="rt-desc">${desc.replace(/\n/g, "<br>")}</div>` : "";
  return `<div class="relic-tooltip">
    ${artHtml}
    <div class="rt-header">${name}${rarHtml}</div>
    ${descHtml}
  </div>`;
}

// Resolves {{Placeholder}} tokens in a card or relic description.
//
// Shared by cards, relics and potions: each ships a `vars` map read from the
// game's DynamicVars. `vars` is still optional here — glyph tokens default to
// one glyph, and a bare token with no value falls back to "?".
//
// `html: false` emits bare glyphs with no markup, for callers embedding
// the result in an attribute (e.g. data-tip) rather than element content.
function substituteDescVars(desc, vars, { html = true } = {}) {
  if (!desc) return desc;
  const v = vars || {};
  const b = (inner, style) => html
    ? `<b${style ? ` style="${style}"` : ""}>${inner}</b>`
    : inner;
  // Token grammar, as emitted by tools/extract_card_data.py:
  //   {{Var}}                      the value
  //   {{Var:energy}} {{Var:stars}} that many glyphs
  //   {{Var:plural:one|many}}      word form chosen by the value
  //   {{Var:show:yes|no}}          branch chosen by a flag (e.g. IfUpgraded)
  //
  // plural/show can't be resolved at extract time: a card's base and upgraded
  // forms share one desc string with different vars, so "{{Combats:plural:
  // combat|combats}}" is "combat" at 1 and "combats" at 5.
  return desc.replace(/\{\{([^}]+)\}\}/g, (_, raw) => {
    // Branch text may itself contain ':', so peel off only the first two
    // segments and keep the remainder of the payload intact.
    const c1 = raw.indexOf(":");
    if (c1 < 0) {
      const val = v[raw];
      return b(val !== undefined ? String(val) : "?");
    }
    const name  = raw.slice(0, c1);
    const after = raw.slice(c1 + 1);
    const c2    = after.indexOf(":");
    const kind  = c2 < 0 ? after : after.slice(0, c2);
    const arg   = c2 < 0 ? "" : after.slice(c2 + 1);

    if (kind === "energy") return b("⚡".repeat(v[name] ?? 1));
    if (kind === "stars")  return b("✦".repeat(v[name] ?? 1), "color:#5b9bd5");
    // Word forms and conditional branches are prose, not values — no <b>.
    if (kind === "plural") {
      const [one, many] = arg.split("|");
      return v[name] === 1 ? one : (many ?? one);
    }
    if (kind === "show") {
      const [yes, no] = arg.split("|");
      return v[name] ? yes : (no ?? "");
    }
    const val = v[name];
    return b(val !== undefined ? String(val) : "?");
  });
}

