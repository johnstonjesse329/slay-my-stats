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

// The floor-map icon for a node, as a key into DATA.nodeIcons. Boss nodes show
// the specific boss's portrait (keyed by encounter id) when one exists, falling
// back to the generic crown; Ancient nodes work the same way, falling back to
// the generic Ancient icon; "?" rooms pick theirs from how they resolved (see
// unknownNodeIconKey). Shared by the timeline cards and the chart markers, so
// the two can't disagree about what a node was.
function nodeIconKey(node) {
  if (node.type === "boss" && node.enc) return node.enc;
  if (node.type === "ancient") {
    return (node.enc && DATA.nodeIcons && DATA.nodeIcons[node.enc]) ? node.enc : "ancient";
  }
  if (node.type === "unknown") return unknownNodeIconKey(node);
  return node.type;
}

// ---- Filter state ----

let detailSelectedTs  = null;
let detailHpChart     = null;

function getDetailRuns() {
  return filterRuns().sort((a, b) => b.ts - a.ts);
}

// "Modded" tag for a run the game mod reported loaded mods for (run.mods, from
// run.py's _loaded_mods), with the list on hover. A run uploaded from files
// says nothing about mods, so a run without the tag isn't known to be
// unmodded. The ids and versions are cut down to plain characters by the
// parser, which is what makes them safe to drop into data-tip here.
function moddedTagHtml(run, focusable = false) {
  const mods = run.mods || [];
  if (mods.length === 0) return "";
  const lines = mods.map(m => `${m.id}${m.version ? ` ${m.version}` : ""}${m.gameplay ? " (changes gameplay)" : ""}`);
  return `<span class="run-modded-tag" data-tip="${["Mods loaded:", ...lines].join("\n")}"${focusable ? ` tabindex="0"` : ""}>Modded</span>`;
}

// Keeps the address bar on the run being shown (#detail/<ts>, see
// parsePageHash), so it can be copied or reloaded. Only once the hash is
// already Run Detail's: showPage() sets it on the way in, and replacing it
// before then would overwrite the previous tab's history entry.
function syncRunHash() {
  if (parsePageHash().page !== "detail") return;
  const hash = "#" + pageHash("detail");
  if (location.hash !== hash) history.replaceState(null, "", hash);
}

// The header's "Copy link" button: this page's own address with the run in
// the hash, which openRunLink() turns back into this run for whoever opens it.
function copyRunLink(ts, btn) {
  const url = location.href.split("#")[0] + `#detail/${ts}`;
  navigator.clipboard.writeText(url).then(() => {
    btn.textContent = "Copied!";
    setTimeout(() => { btn.textContent = "Copy link"; }, 1200);
  });
}

// ---- Run list ----

function renderDetailRunList() {
  const runs = getDetailRuns();
  const container = document.getElementById("detail-run-list");

  if (runs.length === 0) {
    container.innerHTML = `<div style="color:#8a8aa0;padding:1rem;font-size:var(--fs-sm)">No runs match the current filters.</div>`;
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
      ${moddedTagHtml(run)}
      <span class="detail-run-date" style="color:#8a8aa0">${fmtDate(run.ts)}</span>
    </div>`;
  }).join("");

  container.querySelectorAll(".detail-run-item").forEach(el => {
    el.addEventListener("click", () => {
      const ts = +el.dataset.ts;
      const run = DATA.runsData.find(r => r.ts === ts);
      if (!run) return;
      detailSelectedTs = ts;
      syncRunHash();
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
  syncRunHash();
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
  // Cards passed up on a reward or shop shelf. The per-node "Skipped:" lists
  // already show which ones (see nodeTooltipHtml); this is the count for the
  // run, next to what was bought.
  const totalCardsSkipped = tl.reduce((n, node) => n + (node.cardsSkipped || []).length, 0);
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
    totalCardsSkipped     > 0 ? { label: "Cards skipped",    value: totalCardsSkipped }     : null,
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
          ? `<img loading="lazy" class="run-boon-icon" src="${thumbSrc(src)}" alt="${fmtRelicLabel(id)}">`
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
      <span class="rh-date">${fmtDate(run.ts)}</span>
      ${run.seed ? `<span class="rh-seed"><span class="rh-seed-label">Seed: </span>${run.seed}</span>` : ""}
      ${moddedTagHtml(run, true)}
      ${navigator.clipboard ? `<button type="button" class="run-copy-link">Copy link</button>` : ""}
    </div>
    <div class="detail-run-headline-stats">
      ${headlineHtml}
    </div>
    <div class="detail-run-header-stats">
      ${summaryHtml}
    </div>`;

  const copyBtn = document.querySelector("#detail-run-header .run-copy-link");
  if (copyBtn) copyBtn.addEventListener("click", () => copyRunLink(run.ts, copyBtn));

  renderDetailTimeline(run);
  renderDetailHpChart(run);
  renderDetailGoldChart(run);
  detailDeckRun = run;
  renderDetailDeckChart(run);
  renderDetailRelicChart(run);
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

// A card face's height over its width, if one hasn't rendered to measure.
const NT_CARD_ASPECT = 1.37;
const NT_CARD_GAP = 4; // .nt-cardrow's gap, px

// Sizes a card-bearing node tooltip to the room the window actually has:
// picks how many cards a row holds and how wide each is, so the cards are as
// big as possible -- up to the deck's hover-card size -- while the whole
// tooltip fits on screen. It can't be scrolled (hovering is all it takes to
// show it), so height matters as much as width. Runs each time a tooltip
// opens and on resize, which is also what browser zoom fires.
function fitNodeTooltip(tip) {
  const rows = [...tip.querySelectorAll(".nt-cardrow")];
  if (!rows.length) return;
  // Laid out (unseen) while measuring: on mouseover the browser hasn't
  // applied :hover yet, so the tooltip may still be display:none.
  tip.classList.add("nt-measuring");
  const face = tip.querySelector(".nt-cardface");
  const aspect = face && face.offsetWidth ? face.offsetHeight / face.offsetWidth : NT_CARD_ASPECT;
  // The deck's hover-card width, resolved to px for this window size.
  const probe = document.createElement("div");
  probe.style.cssText = `position:absolute;visibility:hidden;width:${cardFaceWidth(150, 210)}`;
  document.body.appendChild(probe);
  const deckW = probe.offsetWidth;
  probe.remove();
  // Everything but the cards: the text lines, padding and border.
  rows.forEach(r => { r.style.display = "none"; });
  const textH = tip.offsetHeight;
  rows.forEach(r => { r.style.display = ""; });
  const cs = getComputedStyle(tip);
  const chromeW = tip.offsetWidth - tip.clientWidth + parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight);
  const roomW = parseFloat(cs.maxWidth) - chromeW;
  const roomH = parseFloat(cs.maxHeight) - textH;
  tip.classList.remove("nt-measuring");

  const counts = rows.map(r => r.children.length);
  let best = { cols: 1, w: 0 };
  for (let cols = 1; cols <= Math.max(...counts); cols++) {
    const lines = counts.reduce((n, c) => n + Math.ceil(c / cols), 0);
    const w = Math.min(deckW,
      (roomW - (cols - 1) * NT_CARD_GAP) / cols,
      (roomH - (lines - rows.length) * NT_CARD_GAP) / lines / aspect);
    // >=: on a tie, more per row -- fewer, wider rows suit a landscape screen.
    if (w >= best.w - 0.5) best = { cols, w };
  }
  tip.style.setProperty("--nt-cols", best.cols);
  tip.style.setProperty("--nt-card-w", `${Math.floor(best.w)}px`);
}

// The open tooltip is the hovered or focused node's; fit it as it opens.
let _fittedNode = null;
function fitNodeTooltipOf(nodeCard) {
  _fittedNode = nodeCard;
  const tip = nodeCard?.querySelector(".node-tooltip");
  if (tip) fitNodeTooltip(tip);
}
document.addEventListener("mouseover", e => {
  const nodeCard = e.target.closest?.(".node-card");
  if (nodeCard && nodeCard !== _fittedNode) fitNodeTooltipOf(nodeCard);
  else if (!nodeCard) _fittedNode = null;
});
document.addEventListener("focusin", e => {
  const nodeCard = e.target.closest?.(".node-card");
  if (nodeCard) fitNodeTooltipOf(nodeCard);
});
window.addEventListener("resize", () => {
  const open = document.querySelector(".node-card:hover, .node-card:focus");
  if (open) fitNodeTooltipOf(open);
});

function buildNodeTooltip(node) {
  // Small art beside each named item, so a floor's rewards read at a glance
  // instead of as a wall of text. Cards get the real card face; relics and
  // potions get their own icons.
  const fmtPotion = fmtPotionLabel;
  const iconRow = (cls, src, label, extra = "") =>
    `<div class="${cls} nt-item">${src ? `<img loading="lazy" class="nt-item-icon" src="${thumbSrc(src)}" alt="">` : ""}<span>${label}</span>${extra}</div>`;
  // Card faces size from --nt-card-w, which fitNodeTooltip sets as the
  // tooltip opens.
  const nodeCardHtml = (id, dim = false) => cardFaceAvailable()
    ? `<div class="nt-cardface${dim ? " nt-cardface-dim" : ""}">${renderCardFace(id, 0, "var(--nt-card-w)")}</div>`
    : `<div class="${dim ? "nt-skipped" : "nt-reward-card"}">${fmtCardLabel(id)}</div>`;
  // Wraps a group of cards in one grid so they lay out side by side, as many
  // a row as fitNodeTooltip picks, instead of stacking one per line.
  const cardRow = (ids, dim = false) => {
    if (!ids.length) return "";
    return `<div class="nt-cardrow">${ids.map(id => nodeCardHtml(id, dim)).join("")}</div>`;
  };
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
      const icon    = nodeIconHtml(nodeIconKey(node), 30, node.type);
      // Red for a floor that cost HP, green for one that only gave it back.
      const hpClass = node.dmg > 0 ? "node-hp damaged"
        : node.healed > 0 ? "node-hp healed" : "node-hp";
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

// ---- Shared chart pieces ----

const ACT_COLOUR = "#e6e2f2";
// The act names sit in a row under the floor numbers (see
// makeActBoundaryPlugin), so the axis title drops by ACT_ROW to make room.
// Above the plot there's only room for the top half of a point icon.
const ACT_ROW = 26;
const PLOT_TOP = 12;

// Each floor's point on the HP and Gold lines is the floor map's own icon
// (fight, rest, shop, ...), so the line says what happened where. Images are
// shared between charts and redraw the chart once they decode.
const nodePointImages = new Map();  // icon src -> Image
function nodePointStyles(nodes, getChart) {
  return nodes.map(n => {
    const src = DATA.nodeIcons && DATA.nodeIcons[nodeIconKey(n)];
    if (!src) return "circle";
    let img = nodePointImages.get(src);
    if (!img) {
      img = new Image(NODE_POINT, NODE_POINT);
      img.src = src;
      nodePointImages.set(src, img);
    }
    if (!img.complete) img.addEventListener("load", () => getChart()?.update("none"), { once: true });
    return img;
  });
}
const NODE_POINT = 24;

// Floor numbers on the x axis: 1 and every fifth floor, so the ticks land
// on round numbers rather than wherever Chart.js's auto-skip puts them.
function floorAxis(extra = {}) {
  return {
    ...extra,
    title: { display: true, text: "Floor", color: "#8a8aa0", font: { size: 12 }, padding: { top: ACT_ROW } },
    ticks: {
      color: "#8a8aa0", autoSkip: false, maxRotation: 0,
      callback(v) { const f = Number(this.getLabelForValue(v)); return f === 1 || f % 5 === 0 ? f : ""; },
    },
  };
}

// Acts as a second row under the floor numbers: each act's name centred
// under a bracket spanning its floors, plus a faint dotted line up through the
// plot where one act ends -- mirrors the act grouping of the timeline rows.
function makeActBoundaryPlugin(nodes) {
  const spans = [];
  nodes.forEach((n, i) => {
    if (i === 0 || n.act !== nodes[i - 1].act) spans.push({ act: n.act, from: i, to: i });
    else spans[spans.length - 1].to = i;
  });
  return {
    id: "actBounds",
    // Before the datasets, so the line runs behind the data and the hover
    // tooltip draws over it. Only each dataset's own drawing is clipped to the
    // plot, so this hook can still reach the row under the axis.
    beforeDatasetsDraw(chart) {
      const { ctx, chartArea: { top, bottom }, scales: { x } } = chart;
      const half = nodes.length > 1 ? Math.abs(x.getPixelForValue(1) - x.getPixelForValue(0)) / 2 : 0;
      const y = x.top + ACT_ROW;  // under the tick labels; x.bottom includes the title
      ctx.save();
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 4]);
      ctx.strokeStyle = ACT_COLOUR + "55";
      spans.slice(1).forEach(({ from }) => {
        const px = x.getPixelForValue(from);
        ctx.beginPath();
        ctx.moveTo(px, top);
        ctx.lineTo(px, bottom);
        ctx.stroke();
      });
      ctx.setLineDash([]);
      ctx.strokeStyle = ACT_COLOUR + "40";
      ctx.fillStyle = "#cfcbe0";
      ctx.font = "600 12px 'Segoe UI', system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      spans.forEach(({ act, from, to }) => {
        const a = x.getPixelForValue(from) - half + 3, z = x.getPixelForValue(to) + half - 3;
        ctx.beginPath();
        ctx.moveTo(a, y - 4);
        ctx.lineTo(a, y);
        ctx.lineTo(z, y);
        ctx.lineTo(z, y - 4);
        ctx.stroke();
        ctx.fillText(`Act ${act}`, (a + z) / 2, y + 3);
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
  const labels = nodes.map(n => n.floor + 1);
  const hpData = nodes.map(n => n.hpAfter);
  const maxHpData = nodes.map(n => n.maxHp);

  if (detailHpChart) { detailHpChart.destroy(); detailHpChart = null; }

  const ctx = document.getElementById("detail-hp-chart").getContext("2d");
  detailHpChart = new Chart(ctx, {
    type: "line",
    plugins: [makeActBoundaryPlugin(nodes)],
    data: {
      labels,
      datasets: [
        {
          label: "HP",
          data: hpData,
          borderColor: color,
          backgroundColor: color + "33",
          borderWidth: 2,
          pointStyle: nodePointStyles(nodes, () => detailHpChart),
          pointRadius: NODE_POINT / 2,
          pointHoverRadius: NODE_POINT / 2,
          fill: true,
          cubicInterpolationMode: "monotone",
        },
        {
          label: "Max HP",
          data: maxHpData,
          borderColor: "#8a8aa0",
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
      layout: { padding: { top: PLOT_TOP } },
      interaction: { mode: "index", intersect: false },
      plugins: {
        // At the bottom, like every Run Detail chart.
        legend: {
          position: "bottom",
          labels: {
            color: "#ccc",
            // Max HP's key is a short dashed line like the one on the chart,
            // not the default box, which drew a dashed line as a faint square.
            usePointStyle: true,
            pointStyleWidth: 22,
            generateLabels: chart => Chart.defaults.plugins.legend.labels.generateLabels(chart)
              .map(item => ({ ...item, pointStyle: item.text === "Max HP" ? "line" : "rect" })),
          },
        },
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
        x: floorAxis({ grid: { color: "#2e3035" } }),
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

  const labels   = nodes.map(n => n.floor + 1);
  const goldData = nodes.map(n => n.gold);

  if (detailGoldChart) { detailGoldChart.destroy(); detailGoldChart = null; }

  const ctx = document.getElementById("detail-gold-chart").getContext("2d");
  detailGoldChart = new Chart(ctx, {
    type: "line",
    plugins: [makeActBoundaryPlugin(nodes)],
    data: {
      labels,
      datasets: [{
        label: "Gold",
        data: goldData,
        borderColor: "#e0c468",
        backgroundColor: "#e0c46833",
        borderWidth: 2,
        pointStyle: nodePointStyles(nodes, () => detailGoldChart),
        pointRadius: NODE_POINT / 2,
        pointHoverRadius: NODE_POINT / 2,
        fill: true,
        cubicInterpolationMode: "monotone",
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      layout: { padding: { top: PLOT_TOP } },
      interaction: { mode: "index", intersect: false },
      plugins: {
        // At the bottom, like every Run Detail chart.
        legend: { position: "bottom", labels: { color: "#ccc", boxWidth: 14 } },
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
        x: floorAxis({ grid: { color: "#2e3035" } }),
        y: { ticks: { color: "#ccc" }, grid: { color: "#2e3035" }, min: 0 },
      },
    },
  });
}

// ---- Deck and relics by floor ----

// What the deck and relic bar held after each floor, one stacked bar per
// timeline node, rebuilt from run.py's extract_deck_history: a card counts at
// floor F if it was added by F and not yet removed or transformed away. Runs
// parsed before PARSER_VERSION 5 have no deckAdded and hide both charts.
//
// Categories stack bottom-up in this order, so what the run started with sits
// at the base and the rarer picks pile on top. Common/Uncommon/Rare are the
// same colour in both charts. The starting cards and relics get the one
// neutral, so they recede; every other colour comes from the validated
// categorical set (checked against the panel surface, adjacent pairs only).
// Curse sits on top of the stack in both views: the band you'd rather not see
// grow, kept apart from Other because curses are most of what Other used to be.
const isCurse = info => info?.rarity === "Curse" || info?.type === "Curse";
const DECK_GROUPS = {
  rarity: {
    order: ["Basic", "Common", "Uncommon", "Rare", "Colorless", "Other", "Curse"],
    color: { Basic: "#6e6a84", Common: "#199e70", Uncommon: "#3987e5", Rare: "#c98500", Colorless: "#d55181", Other: "#9085e9", Curse: "#e5484d" },
    // Colorless before rarity: a colorless Rare is a colorless card first.
    // Other is the rest outside the reward pools -- Ancient, Event, Status,
    // Token and Quest cards, each too few to read as its own band.
    of: card => {
      const info = cardInfo(card.id);
      return isCurse(info) ? "Curse"
        : info?.pool === "colorless" ? "Colorless"
        : ["Basic", "Common", "Uncommon", "Rare"].includes(info?.rarity) ? info.rarity : "Other";
    },
  },
  type: {
    order: ["Attack", "Skill", "Power", "Other", "Curse"],
    color: { Attack: "#d95926", Skill: "#3987e5", Power: "#199e70", Other: "#6e6a84", Curse: "#e5484d" },
    // cardTypeOf reads a rolled Mad Science's type from its props, which only
    // the final deck carries; one lost along the way stays Other.
    of: card => {
      if (isCurse(cardInfo(card.id))) return "Curse";
      const type = cardTypeOf(card);
      return ["Attack", "Skill", "Power"].includes(type) ? type : "Other";
    },
  },
};
const RELIC_GROUP = {
  order: ["Starter", "Common", "Uncommon", "Rare", "Shop", "Event", "Ancient"],
  color: { Starter: "#6e6a84", Common: "#199e70", Uncommon: "#3987e5", Rare: "#c98500", Shop: "#d55181", Event: "#008300", Ancient: "#9085e9" },
  // The two "None" relics (deprecated ones) fold into Event, the catch-all
  // for relics no pool hands out.
  of: relic => {
    const rarity = relicInfo(relic.id)?.rarity;
    return RELIC_GROUP.order.includes(rarity) ? rarity : "Event";
  },
};

let detailDeckChart  = null;
let detailRelicChart = null;
let detailDeckGroup  = "rarity";
let detailDeckRun    = null;  // the run on screen, for the Rarity / Type switch

// [{id, props, added, removed}] for every card or relic the run ever held: the final
// ones (never removed) plus the ones lost along the way.
function heldItems(finalItems, added, lost) {
  return finalItems.map((x, i) => ({ id: x.id, props: x.props, added: added[i], removed: Infinity }))
    .concat(lost.map(([id, a, r]) => ({ id, added: a, removed: r })));
}

// Per category, the count held after each node: floor F = node.floor + 1, the
// same 1-based floors floor_added_to_deck uses.
function countsByFloor(nodes, items, group) {
  const counts = {};
  group.order.forEach(k => { counts[k] = nodes.map(() => 0); });
  items.forEach(it => {
    const k = group.of(it);
    nodes.forEach((n, i) => {
      const f = n.floor + 1;
      if (it.added <= f && it.removed > f) counts[k][i]++;
    });
  });
  return counts;
}

function renderStackedFloorChart(canvasId, prev, nodes, counts, group, unit) {
  if (prev) prev.destroy();
  const totals = nodes.map((_, i) => group.order.reduce((s, k) => s + counts[k][i], 0));
  return new Chart(document.getElementById(canvasId).getContext("2d"), {
    type: "line",
    plugins: [makeActBoundaryPlugin(nodes)],
    data: {
      labels: nodes.map(n => n.floor + 1),
      // A category the run never held stays out of the legend too.
      // Stacked areas drawn like the HP and Gold charts above: a 2px line on
      // each band, a 20% fill, and monotone curves, which never overshoot, so
      // a band only rises on a floor where something was added.
      datasets: group.order.filter(k => counts[k].some(v => v > 0)).map((k, i) => ({
        label: k,
        data: counts[k],
        borderColor: group.color[k],
        backgroundColor: group.color[k] + "33",
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
        cubicInterpolationMode: "monotone",
        fill: i === 0 ? "origin" : "-1",
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      layout: { padding: { top: PLOT_TOP } },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { position: "bottom", labels: { color: "#ccc", boxWidth: 14 } },
        tooltip: {
          // Top of the stack first, like the bar reads; empty bands left out.
          filter: item => item.raw > 0,
          itemSort: (a, b) => b.datasetIndex - a.datasetIndex,
          callbacks: {
            title: items => {
              const idx = items[0].dataIndex;
              const node = nodes[idx];
              const enc = node.enc ? fmtNodeLabel(node.enc) : (node.type || "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
              return `Floor ${node.floor + 1} — ${enc} · ${totals[idx]} ${unit}`;
            },
            label: item => `${item.dataset.label}: ${item.raw}`,
          },
        },
      },
      scales: {
        x: floorAxis({ stacked: true, grid: { display: false } }),
        y: { stacked: true, ticks: { color: "#ccc", precision: 0 }, grid: { color: "#2e3035" }, min: 0 },
      },
    },
  });
}

function renderDetailDeckChart(run) {
  const nodes = run.timeline || [];
  const box = document.getElementById("detail-deck-box");
  if (nodes.length === 0 || !run.deckAdded) { box.style.display = "none"; return; }
  box.style.display = "";
  const items = heldItems(run.finalDeck || [], run.deckAdded, run.cardsLost || []);
  const group = DECK_GROUPS[detailDeckGroup];
  detailDeckChart = renderStackedFloorChart("detail-deck-chart", detailDeckChart, nodes,
    countsByFloor(nodes, items, group), group, "cards");
}

function renderDetailRelicChart(run) {
  const nodes = run.timeline || [];
  const box = document.getElementById("detail-relic-box");
  if (nodes.length === 0 || !run.relicsAdded) { box.style.display = "none"; return; }
  box.style.display = "";
  const items = heldItems(run.finalRelics || [], run.relicsAdded, run.relicsLost || []);
  detailRelicChart = renderStackedFloorChart("detail-relic-chart", detailRelicChart, nodes,
    countsByFloor(nodes, items, RELIC_GROUP), RELIC_GROUP, "relics");
}

// Rarity / Type switch: re-groups the deck chart for whichever run is shown.
document.querySelectorAll("#detail-deck-box .chart-toggle .toggle-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    detailDeckGroup = btn.dataset.group;
    document.querySelectorAll("#detail-deck-box .chart-toggle .toggle-btn").forEach(b =>
      b.setAttribute("aria-pressed", String(b === btn)));
    if (detailDeckRun) renderDetailDeckChart(detailDeckRun);
  });
});

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
    ${src ? `<img loading="lazy" class="rt-art" ${imgSrcAttr(src, true)} alt="${name}">` : ""}
    <div class="rt-header">${name}${info.rarity ? `<div class="rt-rarity" style="color:${rarColor}">${info.rarity}</div>` : ""}</div>
    ${desc ? `<div class="rt-desc">${desc.replace(/\n/g, "<br>")}</div>` : ""}
  </div>`;
}

// Name, rarity label and description of a relic, as HTML — shared by the hover
// tooltip and the deck's relic tiles (card-face.js).
function relicTextParts(id) {
  const info = relicInfo(id);
  if (!info) return null;
  const rarColor = { Common: "#ccc", Uncommon: "#aad4ff", Rare: "#ffd700", Boss: "#e88", Starter: "#bcbcd0" }[info.rarity] || "#bcbcd0";
  return {
    name: info.title || fmtRelicLabel(id),
    rarHtml: info.rarity ? `<div class="rt-rarity" style="color:${rarColor}">${info.rarity}</div>` : "",
    desc: substituteDescVars(info.desc || "", info.vars).replace(/\n/g, "<br>"),
  };
}

function buildRelicTooltip(id) {
  const parts = relicTextParts(id);
  if (!parts) return "";
  const { name, rarHtml, desc } = parts;
  const src  = relicImgSrc(id);
  const artHtml = src ? `<img loading="lazy" class="rt-art" ${imgSrcAttr(src, true)} alt="${name}">` : "";
  const descHtml = desc ? `<div class="rt-desc">${desc}</div>` : "";
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
// `pool`: the card's color/character (info.pool), so the inline energy glyph
// matches that card's own cost-badge color. Relics/potions aren't tied to a
// pool, so they default to colorless -- the same default DATA.energyIcons
// (run.py's build_energy_icons()) uses for any pool without its own sprite.
function substituteDescVars(desc, vars, { html = true, pool = "colorless" } = {}) {
  if (!desc) return desc;
  const v = vars || {};
  const energyIcons = DATA.energyIcons || {};
  const energyIconUrl = energyIcons[pool?.toLowerCase()] || energyIcons.colorless;
  const b = (inner, style) => html
    ? `<b${style ? ` style="${style}"` : ""}>${inner}</b>`
    : inner;
  // Token grammar, as emitted by tools/desc_tokens.py:
  //   {{Var}}                      the value
  //   {{Var:energy}} {{Var:stars}} that many glyphs
  //   {{Var:plural:one|many}}      word form chosen by the value
  //   {{Var:show:yes|no}}          branch chosen by a flag (e.g. IfUpgraded)
  //
  // plural/show can't be resolved at extract time: a card's base and upgraded
  // forms share one desc string with different vars, so "{{Combats:plural:
  // combat|combats}}" is "combat" at 1 and "combats" at 5. A branch can hold
  // tokens of its own ("{{Combats:plural:combat|{{Combats}} combats}}"), so
  // tokens are matched by depth and the chosen branch is rendered in turn.
  const tokenEnd = (text, start) => {
    for (let i = start, depth = 0; i < text.length - 1;) {
      const pair = text.substr(i, 2);
      if (pair === "{{") { depth++; i += 2; }
      else if (pair === "}}") { depth--; i += 2; if (depth === 0) return i; }
      else i++;
    }
    return -1;
  };
  // "one|many", split at the first | outside a nested token.
  const branches = arg => {
    for (let i = 0, depth = 0; i < arg.length; i++) {
      const pair = arg.substr(i, 2);
      if (pair === "{{") depth++;
      else if (pair === "}}") depth--;
      else if (arg[i] === "|" && depth === 0) return [arg.slice(0, i), arg.slice(i + 1)];
    }
    return [arg];
  };
  // The comparison in a cond: token (">1", ">=2"), or "" for a bare truthiness
  // test. Mirrors _passes_test in tools/bake_finished_cards.py.
  const passesCond = (value, test) => {
    const m = /^(>=|<=|==|!=|>|<)(-?\d+(?:\.\d+)?)$/.exec(test);
    if (!m) return !!value;
    const lhs = Number(value), rhs = Number(m[2]);
    switch (m[1]) {
      case ">=": return lhs >= rhs;
      case "<=": return lhs <= rhs;
      case "==": return lhs === rhs;
      case "!=": return lhs !== rhs;
      case ">":  return lhs > rhs;
      default:   return lhs < rhs;
    }
  };
  const token = raw => {
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

    // The actual in-game energy orb image, colored for this pool -- not a
    // lightning bolt. See .desc-energy-icon in dashboard.css.
    if (kind === "energy") return html
      ? (energyIconUrl ? `<span class="desc-energy-icon" aria-hidden="true" style="background-image:url(${energyIconUrl})"></span>` : "⚡").repeat(v[name] ?? 1)
      : "⚡".repeat(v[name] ?? 1);
    if (kind === "stars")  return b("✦".repeat(v[name] ?? 1), "color:#5b9bd5");
    // Word forms and conditional branches are prose, not values — no <b>.
    if (kind === "plural") {
      const [one, many] = branches(arg);
      return render(v[name] === 1 ? one : (many ?? one));
    }
    if (kind === "show") {
      const [yes, no] = branches(arg);
      return render(v[name] ? yes : (no ?? ""));
    }
    if (kind === "cond") {
      // {Var:cond:>1?one|many} / {Var:cond:one|many}. The variable's value picks
      // the branch, so it survives to here like plural/show. When the variable
      // isn't known at all the branch can't be determined -- show nothing rather
      // than guess, which would put invented text on the card. Mirrors the cond
      // case in tools/bake_finished_cards.py's expand_desc.
      const q = arg.indexOf("?");
      const test = q < 0 ? "" : arg.slice(0, q);
      const [yes, no] = branches(q < 0 ? arg : arg.slice(q + 1));
      if (v[name] === undefined) return "";
      return render(passesCond(v[name], test) ? yes : (no ?? ""));
    }
    if (kind === "percentMore" || kind === "percentLess") {
      // The game's Percent{More,Less}Formatter takes a MULTIPLIER and writes the
      // delta as a whole percent: percentMore is (value - 1) * 100, percentLess is
      // (1 - value) * 100. See src/Core/Localization/Formatters/. The '%' lives in
      // the template, outside this placeholder.
      const n = Number(v[name]);
      if (!Number.isFinite(n)) return "";
      const pct = Math.round((kind === "percentMore" ? n - 1 : 1 - n) * 100);
      return b(String(pct));
    }
    const val = v[name];
    return b(val !== undefined ? String(val) : "?");
  };
  const render = text => {
    let out = "";
    for (let pos = 0;;) {
      const start = text.indexOf("{{", pos);
      const end = start < 0 ? -1 : tokenEnd(text, start);
      if (end < 0) return out + text.slice(pos);
      out += text.slice(pos, start) + token(text.slice(start + 2, end - 2));
      pos = end;
    }
  };
  return render(desc);
}

