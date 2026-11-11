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

// Run list sort, set by clicking a column header (like the seeds table).
// Ties fall back to newest first.
let detailSortCol = "date";
let detailSortAsc = false;
const DETAIL_SORT_FNS = {
  char:  (a, b) => fmtCharName(a.char).localeCompare(fmtCharName(b.char)),
  asc:   (a, b) => a.asc - b.asc,
  won:   (a, b) => a.won - b.won,
  floor: (a, b) => a.floor - b.floor,
  read:  (a, b) => runReadingRank(a) - runReadingRank(b),
  date:  (a, b) => a.ts - b.ts,
};

function getDetailRuns() {
  const fn = DETAIL_SORT_FNS[detailSortCol];
  return filterRuns().sort((a, b) => (detailSortAsc ? fn(a, b) : fn(b, a)) || b.ts - a.ts);
}

// "Modded" tag for a run the game mod reported loaded mods for (run.mods, from
// run.py's _loaded_mods), with the list on hover. A run uploaded from files
// says nothing about mods, so a run without the tag isn't known to be
// unmodded. The ids and versions are cut down to plain characters by the
// parser, which is what makes them safe to drop into data-tip here.
// The run list doesn't show it; the Mods filter and this header do.
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
    if (btn.classList.contains("run-copy-link-icon")) {
      btn.classList.add("copied");
      setTimeout(() => btn.classList.remove("copied"), 1200);
      return;
    }
    btn.textContent = "Copied!";
    setTimeout(() => { btn.textContent = "Copy link"; }, 1200);
  });
}

// ---- Run list ----

function renderDetailRunList() {
  const runs = getDetailRuns();
  const container = document.getElementById("detail-run-list");

  if (runs.length === 0) {
    container.innerHTML = `<div style="color:var(--text-dim);padding:1rem;font-size:var(--fs-sm)">No runs match the current filters.</div>`;
    return;
  }

  const fmtDate = ts => { const d = new Date(ts * 1000); return `${d.getMonth()+1}/${d.getDate()}/${String(d.getFullYear()).slice(-2)}`; };

  // A first click sorts A-Z for characters and high-to-low (wins first,
  // newest first) for the rest; a second click flips it.
  const sortHead = (col, label, tip) => {
    const on = col === detailSortCol;
    const dir = on ? (detailSortAsc ? " asc" : " desc") : "";
    return `<span class="detail-run-${col} detail-run-sort${dir}" data-col="${col}" tabindex="0" role="button"${tip ? ` data-tip="${tip}"` : ""}><span>${label}</span></span>`;
  };
  container.innerHTML = `<div class="detail-run-header-row">
    ${sortHead("char", "Char")}
    ${sortHead("asc", "Asc")}
    ${sortHead("won", "W/L")}
    ${sortHead("floor", "Floor")}
    ${sortHead("read", "+/–", `Hype, Mid or Rough against the average win on this run's fights.\nOP: Hype in Acts ${KEEP_OP_ACTS.join(" and ")}.`)}
    ${sortHead("date", "Date")}
  </div>` + runs.map((run, i) => {
    const won    = run.won;
    const label  = fmtCharName(run.char);
    const active = run.ts === detailSelectedTs;
    return `<div class="detail-run-item${active ? " active" : ""}" data-ts="${run.ts}" tabindex="0">
      <span class="detail-run-char">${label}</span>
      <span class="detail-run-asc" style="color:var(--text-dim)">A${run.asc}</span>
      <span class="detail-run-won" style="color:${won ? "#5cba7d" : "#e05c5c"}">${won ? "W" : "L"}</span>
      <span class="detail-run-floor" style="color:var(--text-dim)">F${run.floor}</span>
      <span class="detail-run-read">${runReadingHtml(run, true)}</span>
      <span class="detail-run-date" style="color:var(--text-dim)">${fmtDate(run.ts).replace(/\/\d+$/, `<span class="detail-run-year">$&</span>`)}</span>
    </div>`;
  }).join("");

  container.querySelectorAll(".detail-run-sort").forEach(el => {
    el.addEventListener("click", () => {
      if (detailSortCol === el.dataset.col) detailSortAsc = !detailSortAsc;
      else { detailSortCol = el.dataset.col; detailSortAsc = detailSortCol === "char"; }
      renderDetailRunList();
    });
    bindEnterSpace(el);
  });

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
    { label: "Gold", value: totalGold },
    { label: "Relics", value: finalRelics.length,  title: relicsTitle },
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

  // Same number-over-label pairing as the headline row above, a size down.
  const statHtml = items => items.map(i =>
    `<span class="run-headline-stat"><span class="run-headline-value">${i.value}</span><span class="run-headline-label">${i.label}</span></span>`
  ).join("");

  // Same rich hover tooltip (portrait, rarity, description) as the Relics
  // grid further down the page, not the old plain-text data-tip bubble --
  // a one-line description doesn't tell you what an ancient boon actually
  // does. .run-boon-wrap left-aligns the popup instead of centering it, since
  // a centered 180px popup runs off the viewport when the boons wrap to the
  // left edge on a phone.
  // The boons are what the run opened with, so they sit with the headline
  // numbers (the icons in the value slot, "Ancient boons" as the label).
  const ancientBoonsHtml = ancientRelics.length > 0
    ? `<span class="run-headline-stat run-boon-stat"><span class="run-boon-icons">${ancientRelics.map(id => {
        const src = relicImgSrc(id);
        const tip = buildRelicTooltip(id);
        // The id comes from the uploaded run, so its label is escaped before
        // it goes into the markup.
        const safeLabel = String(fmtRelicLabel(id)).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
        const iconHtml = src
          ? `<img loading="lazy" class="run-boon-icon" src="${thumbSrc(src)}" alt="${safeLabel}"><span class="run-boon-name">${safeLabel}</span>`
          : `<span class="run-headline-value">${safeLabel}</span>`;
        // tabindex: same touch/keyboard tooltip-reveal parity as .relic-tile.
        return `<span class="run-boon-wrap" tabindex="0">${iconHtml}${tip ? `<span class="relic-tooltip-wrap">${tip}</span>` : ""}</span>`;
      }).join("")}</span><span class="run-headline-label">Ancient boons</span></span>`
    : "";

  const allGroups = [statItems, purchaseItems, summaryItems].filter(g => g.length > 0);
  // Fights/events/shop counts, buys and damage/healing totals sit in their own
  // row as they are, with no disclosure to open first.
  // Each group wraps as a unit, so a group is never split across two lines.
  const summaryHtml = allGroups.map(g => `<div class="run-stat-group">${statHtml(g)}</div>`).join("");

  // The phone's version of the same stats: some neighbouring pairs share a cell,
  // so there are fewer rows of three. Just enough pairs join (never more than
  // two) that the last row isn't left holding one or two stats on their own;
  // when the count already divides by three, none do. Desktop keeps them all
  // separate (both are in the page, CSS shows one).
  const PHONE_PAIRS = [["Damage taken", "HP healed"], ["Fights", "Events"], ["Cards bought", "Cards skipped"]];
  const flatStats = allGroups.flat();
  const pairsToJoin = flatStats.length % 3;
  // Pairs are picked in list order, by where the first stat of each sits.
  const joinAt = new Set();
  for (const [x, y] of PHONE_PAIRS) {
    if (joinAt.size >= pairsToJoin) break;
    const i = flatStats.findIndex((s, k) => s.label === x && flatStats[k + 1]?.label === y);
    if (i >= 0) joinAt.add(i);
  }
  const phoneHtml = flatStats.map((s, i) => {
    if (joinAt.has(i - 1)) return "";
    if (joinAt.has(i)) {
      const n = flatStats[i + 1];
      return `<span class="run-headline-stat"><span class="run-headline-value">${s.value} / ${n.value}</span><span class="run-headline-label">${s.label} / ${n.label}</span></span>`;
    }
    return statHtml([s]);
  }).join("");

  document.getElementById("detail-run-header").innerHTML = `
    <div class="detail-run-header-bar">
      ${navigator.clipboard ? `<button type="button" class="run-copy-link-icon" aria-label="Copy link to this run" title="Copy link"><svg class="rci-share" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 12v7a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7"/><path d="M16 6l-4-4-4 4"/><path d="M12 2v13"/></svg><svg class="rci-done" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 13l4 4L19 7"/></svg></button>` : ""}
      <span class="dot" style="background:${color};width:14px;height:14px"></span>
      <span style="font-weight:700;font-size:1.1rem">${label}</span>
      <span style="color:var(--text-dim)">A${run.asc}</span>
      <span style="color:${won ? "#5cba7d" : "#e05c5c"};font-weight:600">${won ? "Victory" : "Defeat"}</span>
      ${runReadingHtml(run)}
      <span style="color:var(--text-dim)">Floor ${run.floor}</span>
      <span style="color:var(--text-dim)">${fmtHrsMin(run.mins)}</span>
      ${moddedTagHtml(run, true)}
      <span class="rh-meta">
        <span class="rh-date">${fmtDate(run.ts)}</span>
        ${run.seed ? `<span class="rh-seed"><span class="rh-seed-label">Seed: </span>${run.seed}</span>` : ""}
        ${navigator.clipboard ? `<button type="button" class="run-copy-link">Copy link</button>` : ""}
      </span>
    </div>
    ${runActMarksHtml(run)}
    <div class="detail-run-headline-stats">
      ${headlineHtml}${ancientBoonsHtml}
    </div>
    <div class="detail-run-header-stats">
      <div class="rh-stats-wide">${summaryHtml}</div>
      <div class="rh-stats-phone">${phoneHtml}</div>
    </div>`;

  // The boons' popup starts at the icon's left edge; slide it back in when that
  // would push it past the right edge of the screen (a phone, where the icons
  // sit well to the right).
  document.querySelectorAll("#detail-run-header .run-boon-wrap").forEach(wrap => {
    const tipEl = wrap.querySelector(".relic-tooltip-wrap");
    if (!tipEl) return;
    const fit = () => {
      tipEl.style.transform = "";
      const over = tipEl.getBoundingClientRect().right - (document.documentElement.clientWidth - 8);
      if (over > 0) tipEl.style.transform = `translateX(${-over}px)`;
    };
    // The popup is display:none until :hover/:focus-within applies, which may land
    // after this handler runs, so measure again a frame later.
    const fitSoon = () => { fit(); requestAnimationFrame(fit); };
    wrap.addEventListener("mouseenter", fitSoon);
    wrap.addEventListener("focusin", fitSoon);
  });

  document.querySelectorAll("#detail-run-header .run-copy-link, #detail-run-header .run-copy-link-icon").forEach(copyBtn =>
    copyBtn.addEventListener("click", () => copyRunLink(run.ts, copyBtn)));

  renderDetailTimeline(run);
  renderDetailHpChart(run);
  renderDetailGoldChart(run);
  renderDetailDeckChart(run);
  renderDetailRelicChart(run);
  renderDetailKeepCharts(run);
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
  return id.replace(/^[A-Z]+\./, "").replace(/_EVENT(_V\d)?_ENCOUNTER$/, "").replace(/_/g, " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
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
// Most cards a row holds. Past this a floor with a long reward/skip list made
// a hover panel that covered most of a wide desktop window.
const NT_MAX_COLS = 5;
// Widest a card gets, px. The deck's hover-card size (up to 210px) dwarfs the
// tooltip's 14px text, so a floor's cards stay a glanceable size.
const NT_MAX_CARD_W = 120;
// Gap kept to the window's edge, and the least room beside a node (content
// width, px) that is worth anchoring the tooltip there for.
const NT_EDGE = 8;
const NT_MIN_ANCHOR_W = 260;

// Sizes a card-bearing node tooltip to the room the window actually has:
// picks how many cards a row holds (at most NT_MAX_COLS) and how wide each is,
// so the cards are as big as possible -- up to NT_MAX_CARD_W -- while the whole
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
  // Beside its node when there's room: the tooltip touches the node, so the
  // pointer can move straight from one into the other (to hover a card) without
  // crossing a gap that would close it. Only the room on the roomier side
  // counts. Too narrow for that (a phone) and it stays centred on the screen.
  const node = tip.closest(".node-card");
  const nr = node.getBoundingClientRect();
  const sideRoom = Math.max(document.documentElement.clientWidth - nr.right, nr.left) - NT_EDGE;
  const anchored = sideRoom - chromeW >= NT_MIN_ANCHOR_W;
  const roomW = Math.min(parseFloat(cs.maxWidth), anchored ? sideRoom : Infinity) - chromeW;
  const roomH = parseFloat(cs.maxHeight) - textH;
  tip.classList.remove("nt-measuring");

  const counts = rows.map(r => r.children.length);
  let best = { cols: 1, w: 0 };
  for (let cols = 1; cols <= Math.min(NT_MAX_COLS, Math.max(...counts)); cols++) {
    const lines = counts.reduce((n, c) => n + Math.ceil(c / cols), 0);
    const w = Math.min(deckW, NT_MAX_CARD_W,
      (roomW - (cols - 1) * NT_CARD_GAP) / cols,
      (roomH - (lines - rows.length) * NT_CARD_GAP) / lines / aspect);
    // >=: on a tie, more per row -- fewer, wider rows suit a landscape screen.
    if (w >= best.w - 0.5) best = { cols, w };
  }
  tip.style.setProperty("--nt-cols", best.cols);
  tip.style.setProperty("--nt-card-w", `${Math.floor(best.w)}px`);

  tip.classList.toggle("nt-anchored", anchored);
  if (!anchored) {
    tip.style.left = tip.style.top = "";
    return;
  }
  // Sized now, so its real box can be placed: right of the node, else left,
  // vertically centred on it but kept on screen (it is always tall enough
  // that the node stays alongside it).
  tip.classList.add("nt-measuring");
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.classList.remove("nt-measuring");
  const vw = document.documentElement.clientWidth;
  const left = vw - nr.right - NT_EDGE >= w ? nr.right - 1 : nr.left - w + 1;
  const top = Math.min(Math.max(NT_EDGE, nr.top + nr.height / 2 - h / 2), window.innerHeight - h - NT_EDGE);
  tip.style.left = `${left}px`;
  tip.style.top = `${top}px`;
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
// Anchored tooltips are placed from where the node sat; scrolling moves it.
window.addEventListener("scroll", () => { _fittedNode = null; }, { passive: true });
window.addEventListener("resize", () => {
  const open = document.querySelector(".node-card:hover, .node-card:focus");
  if (open) fitNodeTooltipOf(open);
});

// The tooltip's cards are small so a floor's whole list fits, which leaves
// their text too small to read. Hovering (or tapping) one pops it at the
// deck's full size beside it. One popup on <body> rather than one per card:
// the tooltip scrolls and clips, so a popup inside it would be cut off, and
// pointer-events:none keeps the pointer "on" the node so the tooltip stays open.
let _ntZoom = null;
function ntZoomHide() {
  if (_ntZoom) _ntZoom.classList.remove("open");
}
function ntZoomShow(face) {
  if (!_ntZoom) {
    _ntZoom = document.createElement("div");
    _ntZoom.className = "nt-card-zoom";
    document.body.appendChild(_ntZoom);
  }
  _ntZoom.innerHTML = renderCardFace(face.dataset.card, 0, cardFaceWidth(150, 210));
  _ntZoom.style.visibility = "hidden";
  _ntZoom.classList.add("open");
  const r = face.getBoundingClientRect();
  const w = _ntZoom.offsetWidth, h = _ntZoom.offsetHeight, gap = 8;
  // Nothing to gain when the tooltip's card is already about this size.
  if (r.width >= w * 0.9) { ntZoomHide(); return; }
  let left = r.right + gap;
  if (left + w > window.innerWidth - gap) left = r.left - gap - w;
  left = Math.max(gap, left);
  const top = Math.min(Math.max(gap, r.top + r.height / 2 - h / 2), window.innerHeight - h - gap);
  _ntZoom.style.left = `${left}px`;
  _ntZoom.style.top = `${top}px`;
  _ntZoom.style.visibility = "";
}
document.addEventListener("mouseover", e => {
  const face = e.target.closest?.(".node-tooltip .nt-cardface");
  if (face && face.dataset.card) ntZoomShow(face);
  else ntZoomHide();
});

// A relic or potion in a floor tooltip: the full tooltip (portrait, rarity,
// description) as it shows elsewhere, in the shared floating box on <body> so
// the floor tooltip's own clipping can't cut it.
document.addEventListener("mouseover", e => {
  const chip = e.target.closest?.(".node-tooltip [data-pick]");
  if (!chip) return;
  const [kind, id] = chip.dataset.pick.split(":");
  // Passive: the box opens over the tooltip's lower rows, and one the pointer
  // can land on would take the hover from the floor tooltip and close it.
  showFloatingHtmlTooltip(chip, kind === "potion" ? buildPotionTooltip(id) : buildRelicTooltip(id), true);
});
document.addEventListener("mouseout", e => {
  const chip = e.target.closest?.(".node-tooltip [data-pick]");
  if (chip && !chip.contains(e.relatedTarget)) hideFloatingHtmlTooltip();
});

function buildNodeTooltip(node) {
  // Small art beside each named item, so a floor's rewards read at a glance
  // instead of as a wall of text. Cards get the real card face; relics and
  // potions get their own icons.
  const fmtPotion = fmtPotionLabel;
  // `pick` ("relic:ID" / "potion:ID") makes hovering the chip show the item's
  // full tooltip, as it does elsewhere (see the mouseover listener above).
  const iconRow = (cls, src, label, extra = "", pick = "") =>
    `<div class="${cls} nt-item"${pick ? ` data-pick="${pick}"` : ""}>${src ? `<img loading="lazy" class="nt-item-icon" src="${thumbSrc(src)}" alt="">` : ""}<span>${label}</span>${extra}</div>`;
  const relicChip  = (cls, id) => iconRow(cls, relicImgSrc(id),  fmtRelicLabel(id), "", `relic:${id}`);
  const potionChip = (cls, id) => iconRow(cls, potionImgSrc(id), fmtPotion(id),      "", `potion:${id}`);
  // Card faces size from --nt-card-w, which fitNodeTooltip sets as the
  // tooltip opens.
  const nodeCardHtml = (id, dim = false, bought = false) => cardFaceAvailable()
    ? `<div class="nt-cardface${dim ? " nt-cardface-dim" : ""}${bought ? " nt-cardface-bought" : ""}" data-card="${id}">${renderCardFace(id, 0, "var(--nt-card-w)")}</div>`
    : `<div class="${dim ? "nt-skipped" : "nt-reward-card"}">${fmtCardLabel(id)}${bought ? ` <span class="nt-bought-tag">bought</span>` : ""}</div>`;
  // Wraps a group of cards in one grid so they lay out side by side, as many
  // a row as fitNodeTooltip picks, instead of stacking one per line. `bought`
  // cards (a shop's purchases) lead the row, full brightness and tagged; the
  // rest are dimmed.
  const cardRow = (ids, dim = false, bought = []) => {
    if (!ids.length && !bought.length) return "";
    return `<div class="nt-cardrow">${bought.map(id => nodeCardHtml(id, false, true)).join("")}${ids.map(id => nodeCardHtml(id, dim)).join("")}</div>`;
  };
  // Relics and potions share one wrapping row (it wraps at the width the cards
  // or text set, never widening the tooltip) instead of one line apiece.
  const itemRow = chips => chips.length ? `<div class="nt-itemrow">${chips.join("")}</div>` : "";
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
  const removed = node.cardsRemoved || [];
  // Not dimmed: a removal really happened (at a shop it is a purchase).
  const pushRemoved = () => {
    if (!removed.length) return;
    lines.push(`<div class="nt-section">${removed.length > 1 ? "Cards" : "Card"} removed:</div>`);
    lines.push(cardRow(removed));
  };

  if (isShop) {
    // Cards: bought (highlighted) + for sale (dimmed)
    const cardsBought  = node.cardsBought  || [];
    const cardsForSale = node.cardsSkipped || [];
    if (cardsBought.length + cardsForSale.length > 0) {
      lines.push(`<div class="nt-section">Cards offered:</div>`);
      lines.push(cardRow(cardsForSale, true, cardsBought));
    }
    // The removal is the shop's other card purchase, so it sits right under the offers.
    pushRemoved();
    // Relics, then potions: bought + for sale. Same reading as the cards
    // above: purchases glow, what was only on offer is dimmed.
    const relicChips = [
      ...(node.relicsBought  || []).map(id => relicChip("nt-reward-relic nt-item-bought", id)),
      ...(node.relicsForSale || []).map(id => relicChip("nt-skipped nt-item-dim", id)),
    ];
    const potionChips = [
      ...(node.potionsBought  || []).map(id => potionChip("nt-reward-card nt-item-bought", id)),
      ...(node.potionsForSale || []).map(id => potionChip("nt-skipped nt-item-dim", id)),
    ];
    if (relicChips.length) {
      lines.push(`<div class="nt-section">Relics:</div>`);
      lines.push(itemRow(relicChips));
    }
    if (potionChips.length) {
      lines.push(`<div class="nt-section">Potions:</div>`);
      lines.push(itemRow(potionChips));
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
      lines.push(itemRow([
        ...relicsRewarded.map(id  => relicChip("nt-reward-relic", id)),
        ...potionsRewarded.map(id => potionChip("nt-reward-card", id)),
      ]));
    }
    if (hasSkipped) {
      lines.push(`<div class="nt-section">Skipped:</div>`);
      lines.push(cardRow(node.cardsSkipped, true));
    }
  }

  if (!isShop) pushRemoved();

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
    document.getElementById("detail-timeline").innerHTML = `<div style="color:var(--text-dim);padding:1rem">No timeline data for this run.</div>`;
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
// Room reserved above the plot for the act names (see makeActBoundaryPlugin),
// clear of the top half of a point icon. The Canvas legend would otherwise
// take the top of the canvas, which is why every Run Detail chart keeps its
// legend at the bottom.
const ACT_BAND = 34;

// Your run, as a line, on the HP, damage done and damage taken charts, whatever the character:
// the site's gold (the "This run" colour in the hover boxes), so one colour and one style always
// means you. Not red: that is the Attack cards' and a rough act's.
const YOUR_LINE = "#e0c468";
const HP_LINE = YOUR_LINE;

// The floors behind each chart's big swings get the floor map's own icon as
// their point: elites, bosses, rest sites and events on HP, shops and events
// on Gold. Every other floor has no point, just a small dot on hover, so
// those few stand out.
// Images are shared between charts and redraw the chart once they decode.
const HP_ICON_KEYS   = new Set(["elite", "unknown_elite", "rest_site", "event"]);  // + any boss
const GOLD_ICON_KEYS = new Set(["shop", "unknown_shop", "event"]);
const nodePointImages = new Map();  // "size src" -> Image
// The clip for a chart's floor icons: none, or the plot's sides alone where one act is on show.
const iconClip = () => narrowScreen.matches ? { left: 0, right: 0, top: false, bottom: false } : false;
function nodePoints(nodes, getChart, highlight, size = NODE_POINT, keyOf = nodeIconKey) {
  const srcs = nodes.map((n, i) => {
    const key = keyOf(n);
    return highlight(n, key, i) && DATA.nodeIcons ? DATA.nodeIcons[key] : null;
  });
  return {
    pointStyle: srcs.map(src => {
      if (!src) return "circle";
      const sized = `${size} ${src}`;
      let img = nodePointImages.get(sized);
      if (!img) {
        img = new Image(size, size);
        img.src = src;
        nodePointImages.set(sized, img);
      }
      if (!img.complete) img.addEventListener("load", () => getChart()?.update("none"), { once: true });
      return img;
    }),
    pointRadius: srcs.map(src => src ? size / 2 : 0),
    pointHoverRadius: srcs.map(src => src ? size / 2 : 4),
    // An icon on the first or last floor overhangs the plot's side edge. Not where the chart shows
    // one act of the run (iconClip), whose neighbouring floors sit past the edge.
    clip: iconClip(),
  };
}
const NODE_POINT = 30;

// The y axis for a chart with floor icons: stretched past the data by an
// icon's height, so one on a peak or down at zero isn't cut off by the top or
// bottom of the plot. Always on top, for the same air over every peak; at the
// bottom only when an icon sits near zero. bounds "data" keeps the stretch from
// rounding up to the next tick, and the stretched ends get no label.
function iconAxis(extra = {}) {
  return {
    ...extra,
    bounds: "data",
    ticks: { color: "#ccc", includeBounds: false },
    grid: { color: "#2e3035" },
    afterDataLimits(scale) {
      // The plot's height isn't laid out yet: the canvas less the act band,
      // floor axis and legend is close enough.
      const pad = (NODE_POINT / 2 + 3) / Math.max(100, scale.chart.height - ACT_BAND - 80);
      const range = (scale.max - scale.min) || 1, grow = range * pad / (1 - pad);
      const icons = scale.chart.data.datasets.flatMap(ds =>
        Array.isArray(ds.pointRadius) ? ds.data.filter((_, i) => ds.pointRadius[i] > 0) : []);
      scale.max += grow;
      if (icons.some(v => v < scale.min + range * pad)) scale.min -= grow;
    },
    // Chart.js counts its steps from the stretched bottom (2, 12, 22...);
    // put them back on round numbers from zero, none below it.
    afterBuildTicks(scale) {
      const step = scale.ticks.length > 1 ? Math.abs(scale.ticks[1].value - scale.ticks[0].value) : 0;
      if (!step) return;
      const nice = Math.pow(10, Math.floor(Math.log10(step)));
      const s = [1, 2, 2.5, 5, 10].map(m => m * nice).find(m => m >= step - 1e-9);
      scale.ticks = [];
      for (let v = Math.max(0, Math.ceil(scale.min / s) * s); v <= scale.max; v += s) scale.ticks.push({ value: v });
    },
  };
}

// Floor numbers on the x axis: 1 and every fifth floor, so the ticks land
// on round numbers rather than wherever Chart.js's auto-skip puts them.
function floorAxis(extra = {}) {
  return {
    ...extra,
    title: { display: true, text: "Floor", color: "#ccc", font: { size: 14 } },
    ticks: {
      color: "#ccc", autoSkip: false, maxRotation: 0,
      callback(v) { const f = Number(this.getLabelForValue(v)); return f === 1 || f % 5 === 0 ? f : ""; },
    },
  };
}

// Act 1 comes in two variants with no encounter in common (the game's
// Acts/Overgrowth.cs and Underdocks.cs), so any Act 1 fight names it. Acts 2
// and 3 have one variant each.
const UNDERDOCKS_ENCS = new Set([
  "CORPSE_SLUGS_NORMAL", "CORPSE_SLUGS_WEAK", "CULTISTS_NORMAL", "FOSSIL_STALKER_NORMAL",
  "GREMLIN_MERC_NORMAL", "HAUNTED_SHIP_NORMAL", "LAGAVULIN_MATRIARCH_BOSS", "LIVING_FOG_NORMAL",
  "PHANTASMAL_GARDENERS_ELITE", "PUNCH_CONSTRUCT_NORMAL", "SEAPUNK_NORMAL", "SEAPUNK_WEAK",
  "SEWER_CLAM_NORMAL", "SKULKING_COLONY_ELITE", "SLUDGE_SPINNER_WEAK", "SOUL_FYSH_BOSS",
  "TERROR_EEL_ELITE", "TOADPOLES_WEAK", "TWO_TAILED_RATS_NORMAL", "WATERFALL_GIANT_BOSS",
].map(id => `ENCOUNTER.${id}`));
const OVERGROWTH_ENCS = new Set([
  "BYGONE_EFFIGY_ELITE", "BYRDONIS_ELITE", "CEREMONIAL_BEAST_BOSS", "CUBEX_CONSTRUCT_NORMAL",
  "FLYCONID_NORMAL", "FOGMOG_NORMAL", "FUZZY_WURM_CRAWLER_WEAK", "INKLETS_NORMAL",
  "MAWLER_NORMAL", "NIBBITS_NORMAL", "NIBBITS_WEAK", "OVERGROWTH_CRAWLERS",
  "PHROG_PARASITE_ELITE", "RUBY_RAIDERS_NORMAL", "SHRINKER_BEETLE_WEAK", "SLIMES_NORMAL",
  "SLIMES_WEAK", "SLITHERING_STRANGLER_NORMAL", "SNAPPING_JAXFRUIT_NORMAL", "THE_KIN_BOSS",
  "VANTOM_BOSS", "VINE_SHAMBLER_NORMAL",
].map(id => `ENCOUNTER.${id}`));

function actName(act, nodes) {
  if (act === 2) return "Hive";
  if (act === 3) return "Glory";
  if (act !== 1) return null;
  for (const n of nodes) {
    if (n.act !== 1) continue;
    if (UNDERDOCKS_ENCS.has(n.enc)) return "Underdocks";
    if (OVERGROWTH_ENCS.has(n.enc)) return "Overgrowth";
  }
  return null;
}

// Each act's name centred above its floors, plus a faint dotted line up
// through the plot where one act ends -- mirrors the act grouping of the
// timeline rows.
// A full run's floors in each act, as most runs play it (17, 16 and 15). Every floor chart is
// as wide as one, so an act is the same width on a run that ended in Act 2 as on one that went
// the distance, and the charts on the page line up floor for floor.
const ACT_FLOORS = { 1: 17, 2: 16, 3: 15 };
const FRAME_FLOORS = Object.values(ACT_FLOORS).reduce((a, b) => a + b, 0);
// The x axis labels: one per floor played, then the floors the run never reached, so the axis
// runs on empty where the run stopped. (No gaps in a timeline: node i is floor i + 1.)
const floorLabels = nodes => Array.from({ length: Math.max(FRAME_FLOORS, nodes.length) },
  (_, i) => nodes[i] ? nodes[i].floor + 1 : i + 1);

function actSpans(nodes) {
  const spans = [];
  nodes.forEach((n, i) => {
    if (i === 0 || n.act !== nodes[i - 1].act) spans.push({ act: n.act, from: i, to: i });
    else spans[spans.length - 1].to = i;
  });
  spans.forEach(s => { s.name = actName(s.act, nodes); });
  // The act the run ended in is named over where all of it would sit, not just what was played.
  const last = spans[spans.length - 1];
  if (last) last.reach = Math.min(floorLabels(nodes).length - 1, last.from + (ACT_FLOORS[last.act] || 1) - 1);
  return spans;
}

// On a phone the Keeping Up charts show one act at a time, picked above them: all 48 floors in a
// phone's width are too cramped to read. `keepAct` is the act on show; a run without it shows its
// first. Returns the x axis's window, or nothing where the whole run fits.
let keepAct = 1, keepActNodes = [];
const narrowScreen = window.matchMedia("(max-width: 700px)");
function keepActSpan(nodes) {
  if (!narrowScreen.matches) return null;
  const spans = actSpans(nodes);
  return spans.find(s => s.act === keepAct) || spans[0] || null;
}
// The floors on show, as indexes into the nodes: {from, to}, or null for the whole run.
function actView(nodes) {
  const s = keepActSpan(nodes);
  return s ? { from: s.from, to: Math.max(s.to, s.reach ?? s.to) } : null;
}
// The same as the x axis's options. A category axis reads a number as a label, not an index, and
// these labels are floor numbers, so the bounds are labels.
function actWindow(nodes) {
  const v = actView(nodes), labels = floorLabels(nodes);
  return v ? { min: labels[v.from], max: labels[v.to], offset: true } : {};
}

function makeActBoundaryPlugin(nodes) {
  const spans = actSpans(nodes);
  return {
    id: "actBounds",
    // Before the datasets, so the line runs behind the data and the hover
    // tooltip draws over it. Only each dataset's own drawing is clipped to the
    // plot, so this hook can still reach the band above it.
    beforeDatasetsDraw(chart) {
      const { ctx, chartArea: { top, bottom }, scales: { x } } = chart;
      // A chart showing one act has no other acts to mark or name.
      const shown = spans.filter(s => !(x.max < s.from || x.min > Math.max(s.to, s.reach ?? s.to)));
      ctx.save();
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 4]);
      ctx.strokeStyle = ACT_COLOUR + "55";
      shown.filter(({ from }) => from > x.min).forEach(({ from }) => {
        const px = x.getPixelForValue(from);
        ctx.beginPath();
        ctx.moveTo(px, top - ACT_BAND + 4);
        ctx.lineTo(px, bottom);
        ctx.stroke();
      });
      ctx.fillStyle = "#cfcbe0";
      ctx.font = "600 15px 'Segoe UI', system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      shown.forEach(({ act, name, from, to, reach }) => {
        const left = x.getPixelForValue(Math.max(from, x.min)), right = x.getPixelForValue(Math.min(Math.max(to, reach ?? to), x.max));
        // Just "Act N" when the name won't fit over the act's floors (a short
        // last act, or a narrow screen).
        const full = name ? `Act ${act} · ${name}` : `Act ${act}`;
        const label = ctx.measureText(full).width <= right - left - 4 ? full : `Act ${act}`;
        ctx.fillText(label, (left + right) / 2, top - ACT_BAND + 2);
      });
      ctx.restore();
    },
  };
}

// ---- HP chart ----

// What this player's wins on each elite and boss began with, as the Overview's HP Entering
// Fight reads it (fight-tables.js hpLane): the median HP of the lowest tenth of wins, and of all
// wins. From the same fights and the same summary, but only the ones tuned the way this run's were
// (A0-7 or A8+), so a floor reads against fights it could have been. Per node: null on every
// floor with no fight this player has won. Every fight floor gets the stats for its tooltip and
// is drawn on the chart.
// Normal fights are not in a run's `fights` (elites and bosses only), so they come from the
// timelines: the same hpBefore and damage, and a fight is won when HP is left after it.
let normalFightsCache = null;
function normalFights() {
  return normalFightsCache ||= DATA.runsData.flatMap(run => (run.timeline || [])
    .filter(n => n.type === "monster" && n.enc)
    .map(n => ({ enc: n.enc, asc: run.asc, won: n.hpAfter > 0, hp: n.hpBefore, maxHp: n.maxHp, dmg: n.dmg,
      cards: 0, relics: 0, potions: 0 })));   // unused here; addFight sums them
}
function hpWinsByNode(run, nodes) {
  const tier = keepTier(run.asc), by = {};
  ALL_FIGHTS.concat(normalFights()).forEach(f => { if (keepTier(f.asc) === tier) addFight(by[f.enc] ||= fightBucket(), f); });
  const left = winsLeftWith(tier);
  return nodes.map(n => {
    const fought = n.type === "monster" || n.type === "elite" || n.type === "boss";
    const s = fought && by[n.enc] ? summarizeFights(by[n.enc]) : null;
    if (!s || !s.wins) return null;
    // The HP the wins left it with, which is what the chart's HP line shows for the floor.
    const out = (left[n.enc] || []).sort((a, b) => a - b);
    const lowest = out.slice(0, Math.max(1, Math.round(out.length * BAND_SHARE)));
    const highest = out.slice(-lowest.length);
    return { ...s, left_avg: median(out), left_low: median(lowest), left_high: median(highest) };
  });
}

// HP left after each won fight, by encounter, across every run at one tuning tier. Read off the
// timelines (the fight records only carry the HP entering), so it counts healing after the fight.
function winsLeftWith(tier) {
  const by = {};
  DATA.runsData.forEach(run => {
    if (keepTier(run.asc) !== tier) return;
    (run.timeline || []).forEach(n => {
      if (n.enc && n.hpAfter > 0 && (n.type === "monster" || n.type === "elite" || n.type === "boss")) (by[n.enc] ||= []).push(n.hpAfter);
    });
  });
  return by;
}

// On each fight floor, a bar from the best quarter of this player's wins to the worst: a green cap at
// the good end, a red cap at the bad one. Drawn before the datasets, so the floor's icon and the
// line sit over it; the dotted average line crosses it where the middle is.
const HP_WIN_COLOUR = "#e6e2f2";
const GOOD_COLOUR = "#5fd08a", BAD_COLOUR = "#e8605d";
// Legend key for the bars: the same bar and dots. `goodDown` for damage taken, where less is better.
const rangeKey = (what, goodDown) => `<span class="fl-item"><span style="position:relative;display:inline-block;width:11px;height:17px"><span style="position:absolute;left:3px;width:5px;height:15px;top:1px;box-sizing:border-box;border-radius:3px;background:${HP_WIN_COLOUR}26;border:1px solid ${HP_WIN_COLOUR}55"></span><span style="position:absolute;left:0;width:11px;height:2.5px;border-radius:2px;top:0;background:${goodDown ? BAD_COLOUR : GOOD_COLOUR}"></span><span style="position:absolute;left:0;width:11px;height:2.5px;border-radius:2px;bottom:0;background:${goodDown ? GOOD_COLOUR : BAD_COLOUR}"></span></span>${what}</span>`;
// marks[i] is {bad, good} for a floor, or null. The same narrow bar and caps on all three charts.
function makeWinRangePlugin(marks, { width = 0.12 } = {}) {
  return {
    id: "winRanges",
    beforeDatasetsDraw(chart) {
      const { ctx, scales: { x, y } } = chart;
      ctx.save();
      marks.forEach((m, i) => {
        if (!m || i < x.min || i > x.max) return;
        const px = x.getPixelForValue(i), bad = y.getPixelForValue(m.bad), good = y.getPixelForValue(m.good);
        const half = Math.abs(x.getPixelForValue(1) - x.getPixelForValue(0)) * width;
        ctx.beginPath();
        ctx.roundRect(px - half, Math.min(bad, good), half * 2, Math.abs(bad - good) || 1, 4);
        ctx.fillStyle = HP_WIN_COLOUR + "26";
        ctx.fill();
        ctx.lineWidth = 1;
        ctx.strokeStyle = HP_WIN_COLOUR + "55";
        ctx.stroke();
        // A short cap at each end, rather than a dot: the charts are busy enough.
        ctx.lineWidth = 2.5;
        ctx.lineCap = "round";
        [[good, GOOD_COLOUR], [bad, BAD_COLOUR]].forEach(([py, colour]) => {
          ctx.strokeStyle = colour;
          ctx.beginPath();
          ctx.moveTo(px - half - 2, py);
          ctx.lineTo(px + half + 2, py);
          ctx.stroke();
        });
      });
      ctx.restore();
    },
  };
}

// The HP chart's hover box. Every floor: the HP left after it. A fight this player has won: first
// what it cost this run beside what their wins lose, a lane each for HP lost and HP left to see
// where this run falls, and a key to their marks; then the HP this run entered it with, beside the
// median and the worst quarter of their wins, and how often they won. `s` is hpWinsByNode's entry,
// or null.
// A hover box's lane: a track from 0 to `top`, a bar where this run's figure is (`you`, in the
// chart's own colour), the zone of the wins from their best quarter to their worst, a green cap at the
// good end, a red one at the bad end, and a thin line at the median or average win. `what` is the
// reading for a screen reader.
function tipLane(top, { you, youColour, mid, good, bad, what }) {
  const at = v => (v / top * 100).toFixed(1) + "%";
  const end = (v, colour) => `<span class="ft-end" style="left:${at(v)};background:${colour}"></span>`;
  return `<div class="ft-lane" role="img" aria-label="${what}">` +
    (good != null && bad != null ? `<span class="ft-zone" style="left:${at(Math.min(good, bad))};width:${at(Math.abs(good - bad))}"></span>` +
      end(good, GOOD_COLOUR) + end(bad, BAD_COLOUR) : "") +
    `<span class="ft-med" style="left:${at(mid)}"></span>` +
    `<span class="ft-you" style="left:${at(you)};background:${youColour}"></span></div>`;
}

// What the marks in a hover box's lanes are. One key, under every lane the box has, since the
// same marks mean the same thing in each.
function tipKey() {
  return `<div class="ft-key"><span><i class="ft-you" style="background:var(--gold)"></i>This run</span>` +
    `<span><i class="ft-med"></i>Median win</span>` +
    `<span><i class="ft-end" style="background:${GOOD_COLOUR}"></i>Best 25% of wins</span>` +
    `<span><i class="ft-end" style="background:${BAD_COLOUR}"></i>Worst 25% of wins</span></div>`;
}

function hpTip(run, n, s) {
  const head = floorTipHead(n);
  const row = (label, you, med, low) => `<tr><td>${label}</td><td><b>${you}</b></td>` +
    (s ? `<td class="ft-win">${med ?? ""}</td><td class="ft-win">${low ?? ""}</td>` : "") + `</tr>`;
  const left = row("Left with", `${n.hpAfter}<small>/${n.maxHp}</small>`, s?.left_avg, s?.left_low);
  const healed = n.healed > 0 ? row("Healed", `+${n.healed}`) : "";
  if (!s) return `${head}<table>${healed}${left}</table>`;
  // The lanes lead, then the table. Both share one track, 0 to whichever is highest of max HP, the
  // wins' medians and this run's own figures, so HP lost and HP left read against each other. The
  // worst quarter is at the high end for HP lost and the low end for HP left.
  const top = Math.max(n.maxHp, s.left_avg, s.left_high, n.dmg, s.heavy_wins_dmg);
  const lost = tipLane(top, { you: n.dmg, youColour: "var(--gold)", mid: s.avg_dmg, good: s.light_wins_dmg, bad: s.heavy_wins_dmg,
    what: `Lost ${n.dmg} HP; your wins' median ${s.avg_dmg}, worst quarter ${s.heavy_wins_dmg}, best quarter ${s.light_wins_dmg}` });
  const kept = tipLane(top, { you: n.hpAfter, youColour: "var(--gold)", mid: s.left_avg, good: s.left_high, bad: s.left_low,
    what: `Left with ${n.hpAfter}; your wins' median ${s.left_avg}, worst quarter ${s.left_low}, best quarter ${s.left_high}` });
  return `${head}<div class="ft-lost"><div class="ft-lost-big">Lost <b${n.dmg > s.avg_dmg ? ` class="ft-worse"` : ""}>${n.dmg} HP</b></div>` +
    `<div class="ft-cap">Wins usually lose ${s.avg_dmg} · the worst quarter lose ${s.heavy_wins_dmg}</div></div>` +
    `<div class="ft-lanelabel">HP lost</div>${lost}<div class="ft-lanelabel">HP left</div>${kept}${tipKey()}` +
    `<table><thead><tr><th></th><th colspan="1">This run</th><th colspan="2" class="ft-win">Your wins</th></tr>` +
    `<tr class="ft-sub"><th></th><th></th><th class="ft-win">Median</th><th class="ft-win">Worst 25%</th></tr></thead>` +
    `${row("Entered with", n.hpBefore, s.avg_hp, s.band_wins_hp)}${healed}${left}</table>` +
    `<div class="ft-cap">Won ${s.wins} of ${s.runs} (${s.win_pct}%) at ${KEEP_TIER_NAMES[keepTier(run.asc)]}</div>`;
}

function renderDetailHpChart(run) {
  const nodes = run.timeline || [];
  if (nodes.length === 0) {
    document.getElementById("detail-hp-box").style.display = "none";
    return;
  }
  document.getElementById("detail-hp-box").style.display = "";

  // Not the character's colour: Regent's is gold, which sat too close to the
  // gold chart under it, and the Silent's green reads as HP anyway.
  const color = HP_LINE;
  const labels = floorLabels(nodes);
  const hpData = nodes.map(n => n.hpAfter);
  const maxHpData = nodes.map(n => n.maxHp);

  if (detailHpChart) { detailHpChart.destroy(); detailHpChart = null; }

  const wins = hpWinsByNode(run, nodes);
  const anyWins = wins.some(s => s);
  // The HP your wins left each fight with, floor by floor: a dotted line, the same dotted grey as
  // "Average win" on the damage charts. Floors with no fight, or no win to read, are skipped over.
  const winHp = wins.map(w => w ? w.left_avg : null);

  // HP's swatch is the area's own fill; Max HP's is its thin line. The dot on each fight floor is
  // the HP this player's wins left that fight with; its bar runs down to the worst quarter.
  document.getElementById("detail-hp-legend").innerHTML = `<div class="fl-items">` +
    `<span class="fl-item"><span class="fl-swatch" style="background:${color}33;border:2px solid ${color}"></span>HP</span>` +
    `<span class="fl-item"><span class="strength-key" style="background:#8a8aa0"></span>Max HP</span>` +
    `<span class="fl-item"><span class="strength-key" style="background:repeating-linear-gradient(90deg, #b9b9c4 0 2px, transparent 2px 6px)"></span>HP left, median win</span>` +
    (anyWins ? rangeKey("Best and worst 25% of wins", false) : "") + `</div>`;

  // Room for a median win, or the best quarter's bar, that finished above this run's own max HP.
  const yAxis = iconAxis({ min: 0 });
  const stretch = yAxis.afterDataLimits;
  yAxis.afterDataLimits = scale => {
    wins.forEach(s => { if (s) scale.max = Math.max(scale.max, s.left_avg, s.left_high); });
    stretch(scale);
  };

  const ctx = document.getElementById("detail-hp-chart").getContext("2d");
  detailHpChart = new Chart(ctx, {
    type: "line",
    plugins: [makeActBoundaryPlugin(nodes), makeWinRangePlugin(wins.map(s => s ? { bad: s.left_low, good: s.left_high } : null))],
    data: {
      labels,
      datasets: [
        {
          label: "HP",
          data: hpData,
          borderColor: color,
          backgroundColor: color + "33",
          borderWidth: 2,
          pointBackgroundColor: color,
          ...nodePoints(nodes, () => detailHpChart, (n, key) => n.type === "boss" || HP_ICON_KEYS.has(key)),
          fill: true,
          cubicInterpolationMode: "monotone",
        },
        {
          label: "Max HP",
          data: maxHpData,
          borderColor: "#8a8aa0",
          borderWidth: 1,
          pointRadius: 0,
          stepped: "before",
          fill: false,
        },
        {
          label: "HP left, median win",
          data: winHp,
          borderColor: "#b9b9c4",
          borderDash: [2, 4],
          borderWidth: 1.5,
          pointRadius: 0,
          pointHoverRadius: 0,
          spanGaps: true,
          cubicInterpolationMode: "monotone",
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      // Right: room for an icon on the last floor, and the same plot edge
      // as the deck and relic charts below.
      layout: { padding: { top: ACT_BAND, right: 24 } },
      interaction: { mode: "index", intersect: false },
      plugins: {
        // The key sits under the chart as HTML, like the deck, relic and
        // keeping-up charts, so all of them read the same.
        legend: { display: false },
        // The same hover box as Keeping Up by Floor: the floor, a small table, what it means.
        tooltip: { enabled: false, external: context => showFloorTip(context, i => hpTip(run, nodes[i], wins[i])) },
      },
      scales: {
        x: floorAxis({ grid: { color: "#2e3035" }, ...actWindow(nodes) }),
        y: yAxis,
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

  const labels   = floorLabels(nodes);
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
        pointBackgroundColor: "#e0c468",
        ...nodePoints(nodes, () => detailGoldChart, (n, key) => GOLD_ICON_KEYS.has(key)),
        fill: true,
        cubicInterpolationMode: "monotone",
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      // Right: room for an icon on the last floor, and the same plot edge
      // as the deck and relic charts below.
      layout: { padding: { top: ACT_BAND, right: 24 } },
      interaction: { mode: "index", intersect: false },
      plugins: {
        // One line, named by the heading above, so no key.
        legend: { display: false },
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
        y: iconAxis({ min: 0 }),
      },
    },
  });
}

// ---- Deck and relics by floor ----

// What the deck and relic bar held after each floor, one point per timeline
// node, rebuilt from run.py's extract_deck_history: a card counts at floor F
// if it was added by F and not yet removed or transformed away. Runs parsed
// before PARSER_VERSION 5 have no deckAdded and hide both charts.
//
// The deck chart is a mirror: card type stacked above the zero line, rarity
// below it, both adding up to the deck size. Categories stack outward in
// order, so what the run started with sits at the zero line and the rarer
// picks pile on the outside.
//
// Rarity wears the game's own colours -- grey Common, blue Uncommon, gold
// Rare -- the same in both charts. Type stays off blue and gold so the two
// halves can't be confused, stacked Attack, Power, Skill so red never sits
// next to green. Validated on the dark panel, adjacent pairs only (the greys
// and the gold sit outside the lightness band on purpose: they are the game's).
// The starting cards and relics aren't a colour at all: see isStarter.
const isCurse = info => info?.rarity === "Curse" || info?.type === "Curse";
const DECK_GROUPS = {
  rarity: {
    order: ["Basic", "Common", "Uncommon", "Rare", "Colorless", "Other", "Curse"],
    color: { Basic: "#9a9aae", Common: "#b6b6c4", Uncommon: "#4087de", Rare: "#eab532", Colorless: "#d37db8", Other: "#a76a33", Curse: "#b83b76" },
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
    order: ["Attack", "Power", "Skill", "Curse", "Other"],
    color: { Attack: "#d25030", Power: "#8459c3", Skill: "#40a35c", Curse: "#b83b76", Other: "#a76a33" },
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
  color: { Starter: "#9a9aae", Common: "#b6b6c4", Uncommon: "#4087de", Rare: "#eab532", Shop: "#10a6ad", Event: "#d97230", Ancient: "#915dc5" },
  // The two "None" relics (deprecated ones) fold into Event, the catch-all
  // for relics no pool hands out.
  of: relic => {
    const rarity = relicInfo(relic.id)?.rarity;
    return RELIC_GROUP.order.includes(rarity) ? rarity : "Event";
  },
};

// Cards call it Basic, relics Starter; same meaning, so one name on both charts.
const rarityName = k => k === "Basic" ? "Starter" : k;
// The starting cards and relics are the given baseline: a dashed edge over
// diagonal hatching instead of a fill, so the band can't blur into Common but
// still reads as something being there.
const isStarter = k => k === "Basic" || k === "Starter";
function hatchPattern(color) {
  const tile = document.createElement("canvas");
  tile.width = tile.height = 8;
  const c = tile.getContext("2d");
  c.strokeStyle = color + "99";
  c.lineWidth = 1.5;
  c.beginPath();
  c.moveTo(-2, 10); c.lineTo(10, -2);
  c.moveTo(-2, 2);  c.lineTo(2, -2);
  c.moveTo(6, 10);  c.lineTo(10, 6);
  c.stroke();
  return c.createPattern(tile, "repeat");
}
const hatchCss = color => `repeating-linear-gradient(-45deg, ${color}99 0 1.5px, transparent 1.5px 4px)`;

// Only the notable gains get a marker over their floor: Uncommon and Rare
// cards, and Uncommon, Rare and Ancient relics. All one size; the ring colour says the rarity.
const CARD_MARK  = new Set(["Uncommon", "Rare"]);
const RELIC_MARK = new Set(["Uncommon", "Rare", "Ancient"]);
const MARK_SIZE  = { Uncommon: 38, Rare: 38, Ancient: 38 };
const MARK_RANK  = { Uncommon: 0, Rare: 1, Ancient: 2 };

let detailDeckChart  = null;
let detailRelicChart = null;

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

const floorTotals = (nodes, counts, order) => nodes.map((_, i) => order.reduce((s, k) => s + counts[k][i], 0));
const usedKeys = (counts, order) => order.filter(k => counts[k].some(v => v > 0));

// Per node, the notable gains made there: [{id, rarity, src, name, count}].
// The same card several times on one floor (a Rare that copies itself) is one
// marker with a count, so it can't build a tower.
function floorMarks(nodes, items, group, marked, imgSrc, name) {
  const lists = nodes.map(() => []);
  items.forEach(it => {
    const rarity = group.of(it);
    const i = nodes.findIndex(n => n.floor + 1 === it.added);
    if (i >= 0 && marked.has(rarity)) lists[i].push({ id: it.id, rarity, src: imgSrc(it.id), name: name(it.id) });
  });
  return lists.map(list => {
    const merged = new Map();
    list.forEach(m => {
      if (merged.has(m.id)) merged.get(m.id).count++;
      else merged.set(m.id, { ...m, count: 1 });
    });
    return [...merged.values()].sort((a, b) => MARK_RANK[a.rarity] - MARK_RANK[b.rarity]);
  });
}

// Draws each floor's markers as round thumbnails ringed in their rarity colour,
// stacked upward from the top of that floor's stack. Images are shared between
// charts and redraw the chart once they decode.
const floorMarkImages = new Map();  // src -> Image
function makeMarkPlugin(marks, totals, colors) {
  const font = "700 13px 'Segoe UI', system-ui, sans-serif";
  return {
    id: "floorMarks",
    afterDatasetsDraw(chart) {
      const { ctx, chartArea, scales: { x, y } } = chart;
      const badges = [];  // the ×N counts, drawn last so the next marker up can't cover them
      // Smaller on a narrow chart (a phone), where full-size markers bury the floors.
      const scale = Math.min(1, Math.max(0.6, chartArea.width / 700));
      marks.forEach((list, i) => {
        let lift = 4;
        list.forEach(m => {
          const size = Math.round(MARK_SIZE[m.rarity] * scale), r = size / 2;
          const cx = x.getPixelForValue(i), cy = y.getPixelForValue(totals[i]) - lift - r;
          lift += size + 2;
          ctx.save();
          ctx.beginPath();
          ctx.arc(cx, cy, r, 0, Math.PI * 2);
          ctx.fillStyle = "#16142a";
          ctx.fill();
          let img = m.src && floorMarkImages.get(m.src);
          if (m.src && !img) {
            img = new Image();
            img.src = m.src;
            floorMarkImages.set(m.src, img);
          }
          if (img && img.complete && img.naturalWidth) {
            ctx.save();
            ctx.beginPath();
            ctx.arc(cx, cy, r - 2, 0, Math.PI * 2);
            ctx.clip();
            const s = Math.max((size - 4) / img.naturalWidth, (size - 4) / img.naturalHeight);
            ctx.drawImage(img, cx - img.naturalWidth * s / 2, cy - img.naturalHeight * s / 2,
              img.naturalWidth * s, img.naturalHeight * s);
            ctx.restore();
          } else if (img) {
            img.addEventListener("load", () => chart.draw(), { once: true });
          }
          ctx.beginPath();
          ctx.arc(cx, cy, r - 1.25, 0, Math.PI * 2);
          ctx.lineWidth = 2.5;
          ctx.strokeStyle = colors[m.rarity];
          ctx.stroke();
          ctx.restore();
          if (m.count > 1) badges.push(() => {
            ctx.font = font;
            const text = "×" + m.count, w = ctx.measureText(text).width + 6;
            ctx.fillStyle = "#16142a";
            ctx.beginPath();
            ctx.roundRect(cx + r - 6, cy + r - 10, w, 15, 7);
            ctx.fill();
            ctx.fillStyle = ACT_COLOUR;
            ctx.textAlign = "left";
            ctx.textBaseline = "middle";
            ctx.fillText(text, cx + r - 3, cy + r - 2);
          });
        });
      });
      ctx.save();
      badges.forEach(draw => draw());
      ctx.restore();
    },
  };
}

// One stacked band: a 2px edge in the category colour over a 30% fill, or the
// starter hatching. Each band fills down to the band under it in its own stack,
// not to zero, so the translucent fills never pile up on each other.
function floorBands(bands) {
  return bands.map(({ key, data, color, stack }, i) => {
    const below = bands.slice(0, i).map(b => b.stack).lastIndexOf(stack);
    return {
      label: rarityName(key),
      data,
      stack,
      borderColor: color,
      backgroundColor: isStarter(key) ? hatchPattern(color) : color + "4d",
      borderWidth: 2,
      borderDash: isStarter(key) ? [5, 4] : [],
      pointRadius: 0,
      pointHoverRadius: 0,
      // Monotone curves never overshoot, so a band only moves on a floor
      // where something changed.
      cubicInterpolationMode: "monotone",
      fill: below >= 0 ? below : "origin",
    };
  });
}

// The hover box is plain HTML rather than Chart.js's canvas tooltip, so it can
// hold the floor's gains at full size: real card faces and relic text.
// One box serves every floor chart; it is rebuilt only when the floor changes.
//
// It has to be reachable. It opens straight below the pointer (above, near the bottom of
// the window), as wide as it needs and centred on it, so heading for it is a vertical move
// that stays on the same floor instead of sliding to the next one. A transparent strip
// fills the gap, and losing the point only starts a short grace period that entering the
// box cancels. Hover a pickup for its full card or relic. On touch there is no leaving, so
// the box stays until a tap elsewhere, Esc, a scroll or a resize.
let floorTip = null;
let floorTipTimer = 0;
let floorTipOver = false;
let floorTipTouch = false;
const floorTipPointer = { x: 0, y: 0 };
// Where the pointer was when the box opened, and which side of it the box is on.
const floorTipAnchor = { x: 0, y: 0, below: true };
// Listening from load, not from the box's first showing: the first tap on a chart is what
// opens the box, and its pointerdown has to be seen already to know it was a finger.
document.addEventListener("pointermove", e => {
  floorTipPointer.x = e.clientX; floorTipPointer.y = e.clientY;
  floorTipTouch = e.pointerType === "touch";
}, { passive: true, capture: true });
document.addEventListener("pointerdown", e => {
  floorTipTouch = e.pointerType === "touch";
  if (floorTipTouch && floorTip && floorTip.style.display === "block" && !floorTip.contains(e.target) && e.target.tagName !== "CANVAS") closeFloorTip();
});
const FLOOR_TIP_GRACE = 450;
// Is p on a straight line from a to some point of the rect r: on its way there?
function onTheWay(a, r, p) {
  const dx = p.x - a.x, dy = p.y - a.y;
  let lo = 0, hi = Infinity;
  for (const [d, from, min, max] of [[dx, a.x, r.left, r.right], [dy, a.y, r.top, r.bottom]]) {
    if (d === 0) { if (from < min || from > max) return false; continue; }
    const t1 = (min - from) / d, t2 = (max - from) / d;
    lo = Math.max(lo, Math.min(t1, t2));
    hi = Math.min(hi, Math.max(t1, t2));
  }
  return hi >= lo && hi >= 1;
}
// The pointer is between where it opened the box and the box, past the first few pixels
// (so scrubbing along the chart is still scrubbing): it is heading for it. The box then
// keeps its floor and stays open, however the pointer wanders on the way.
function floorTipApproached() {
  // A finger has no heading for the box: the docked sheet sits at a screen edge, far from
  // where the last mouse opened one, and holding the floor for it froze the scrub.
  if (floorTipTouch || !floorTip || floorTip.style.display !== "block" || floorTip.classList.contains("passive")) return false;
  const { x, y } = floorTipPointer, a = floorTipAnchor;
  if (a.below ? y < a.y + 6 : y > a.y - 6) return false;
  return onTheWay(a, floorTip.getBoundingClientRect(), { x, y });
}
function closeFloorTip() {
  clearTimeout(floorTipTimer);
  floorTipOver = false;
  if (!floorTip) return;
  floorTip.style.display = "none";
  hideFloatingHtmlTooltip();
}
function scheduleFloorTipClose() {
  clearTimeout(floorTipTimer);
  if (floorTipTouch) return;
  floorTipTimer = setTimeout(() => {
    if (floorTipOver) return;
    if (floorTipApproached()) scheduleFloorTipClose();
    else closeFloorTip();
  }, FLOOR_TIP_GRACE);
}
function createFloorTip() {
  floorTip = document.createElement("div");
  floorTip.className = "floor-tip";
  document.body.appendChild(floorTip);
  floorTip.addEventListener("pointerenter", () => { floorTipOver = true; clearTimeout(floorTipTimer); });
  floorTip.addEventListener("pointerleave", () => { floorTipOver = false; scheduleFloorTipClose(); });
  // A pickup chip: the full card or relic, as it shows everywhere else.
  floorTip.addEventListener("pointerover", e => {
    const chip = e.target.closest("[data-pick]");
    if (!chip) return;
    const [kind, id, up] = chip.dataset.pick.split(":");
    const html = kind === "relic" ? buildRelicTooltip(id) : buildCardTooltip(id, up === "1");
    showFloatingHtmlTooltip(chip, html);
  });
  // A finger "leaves" the chip the moment it lifts, which closed the card as the tap ended.
  // On touch it stays until a press elsewhere (tooltip.js dismissTipsOutside).
  floorTip.addEventListener("pointerout", e => {
    if (e.pointerType !== "touch" && e.target.closest("[data-pick]")) hideFloatingHtmlTooltip();
  });
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeFloorTip(); });
  // A phone's address bar sliding away mid-drag fires resize with the same width; only a real
  // change (rotation) closes the sheet.
  let tipWidth = innerWidth;
  window.addEventListener("scroll", () => { if (floorTipTouch) closeFloorTip(); }, { passive: true });
  window.addEventListener("resize", () => {
    if (floorTipTouch && innerWidth !== tipWidth) closeFloorTip();
    tipWidth = innerWidth;
  }, { passive: true });
}
function showFloorTip(context, html) {
  if (!floorTip) createFloorTip();
  // Pointer is on the box: the chart can't see it any more, and its updates mean nothing.
  if (floorTipOver) return;
  const t = context.tooltip;
  const seen = t.opacity && t.dataPoints?.length;
  // On its way to the box: the chart's view of the pointer (another floor, or none) doesn't count.
  if (floorTipApproached()) { if (seen) clearTimeout(floorTipTimer); else scheduleFloorTipClose(); return; }
  if (!seen) { scheduleFloorTipClose(); return; }
  clearTimeout(floorTipTimer);
  const key = context.chart.id + ":" + t.dataPoints[0].dataIndex;
  // Placed once per floor, not on every pointer move, so the box doesn't slide away from a
  // pointer that is heading for it.
  if (floorTip.style.display === "block" && floorTip.dataset.key === key) return;
  floorTip.innerHTML = html(t.dataPoints[0].dataIndex);
  floorTip.dataset.key = key;
  floorTip.style.display = "block";
  const { clientWidth: vw, clientHeight: vh } = document.documentElement;
  const r = context.chart.canvas.getBoundingClientRect();
  // A finger covers what it points at, and a box beside it covers the rest of a phone's
  // chart. So on touch the box is a sheet on the screen edge away from the chart (CSS
  // sizes it): the chart stays in view and the finger keeps scrubbing it.
  floorTip.classList.toggle("docked", floorTipTouch);
  if (floorTipTouch) {
    floorTip.classList.remove("above");
    floorTip.classList.toggle("docked-top", (r.top + r.bottom) / 2 > vh / 2);
    floorTip.style.left = floorTip.style.top = "";
    floorTip.scrollTop = 0;
    return;
  }
  // Measured at the origin, so the last position near an edge can't squeeze it narrower.
  // clientWidth leaves out the scrollbar.
  floorTip.style.left = floorTip.style.top = "0px";
  // Centred on the floor's column, so the pointer is over the box's width however it drifts.
  const px = r.left + t.caretX, py = floorTipPointer.y || r.top + t.caretY;
  const w = floorTip.offsetWidth, h = floorTip.offsetHeight;
  const gap = 12;
  let below = py + gap + h <= vh - 8 || py - gap - h < 8;
  let top = below ? py + gap : py - gap - h;
  // A box with nothing to hover (no pickup chips) lets the pointer through, so it can't block
  // scrubbing along the chart. One with chips has to be reachable, so it sits clear of the
  // chart instead, under it or over it, and the pointer is never stopped on the way along.
  const live = !!floorTip.querySelector("[data-pick]");
  floorTip.classList.toggle("passive", !live);
  if (live) {
    if (r.bottom + 8 + h <= vh - 8) { top = r.bottom + 8; below = true; }
    else if (r.top - 8 - h >= 8) { top = r.top - 8 - h; below = false; }
  }
  floorTip.classList.toggle("above", !below);
  floorTip.style.left = Math.max(8, Math.min(px - w / 2, vw - 8 - w)) + "px";
  floorTip.style.top = Math.max(8, top) + "px";
  Object.assign(floorTipAnchor, { x: floorTipPointer.x || px, y: py, below });
}

const floorTipHead = (node, total, unit) => {
  const enc = node.enc ? fmtNodeLabel(node.enc) : (node.type || "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  return `<div class="ft-head"><b>Floor ${node.floor + 1}</b> — ${enc}${total == null ? "" : ` · ${total} ${unit}`}</div>`;
};
const floorTipCaption = (m, colors) =>
  `<div class="ft-cap">Gained${m.count > 1 ? " ×" + m.count : ""} · ` +
  `<span style="color:${colors[m.rarity]}">${m.rarity}</span></div>`;
// A phone's sheet has no room for card faces or relic text, so the floor's marked pickups are
// chips like the ones in Keeping Up by Floor: tap one for the full card or relic.
const floorTipChips = (marks, colors, relic) => `<div class="strength-chips">${marks.map(m =>
  `<span class="strength-chip" style="border-color:${colors[m.rarity]}" data-pick="${relic ? "relic" : "card"}:${m.id}${relic ? "" : ":0"}">` +
  `${m.src ? `<img src="${m.src}" alt="">` : ""}${m.name}${m.count > 1 ? " ×" + m.count : ""}</span>`).join("")}</div>`;

// The y axis's afterDataLimits for a chart with markers: raises the top (in
// steps of `step`) until every floor's stack of markers fits under it, so a
// tall stack near the peak isn't cut off at the top. At most twice the usual
// top: past that the areas would flatten out, so a freak stack clips instead.
// Matches makeMarkPlugin's sizes; the plot isn't laid out yet, so its size is
// the canvas less the act band and the floor axis, close enough.
function markHeadroom(marks, totals, step) {
  return scale => {
    const { width, height } = scale.chart;
    const cap = scale.max * 2;
    const plotH = height - ACT_BAND - 60;
    const k = Math.min(1, Math.max(0.6, (width - 60) / 700));
    marks.forEach((list, i) => {
      if (!list.length) return;
      const h = list.reduce((n, m) => n + Math.round(MARK_SIZE[m.rarity] * k) + 2, 10);
      const need = h < plotH ? (totals[i] * plotH - scale.min * h) / (plotH - h) : Infinity;
      if (need > scale.max) scale.max = Math.min(cap, Math.ceil(need / step) * step);
    });
  };
}

function floorChartConfig(nodes, plugins, tip, y, datasets, view = {}) {
  return {
    type: "line",
    plugins: [makeActBoundaryPlugin(nodes), ...plugins],
    data: { labels: floorLabels(nodes), datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      // Right: room for a ×N badge on the last floor.
      layout: { padding: { top: ACT_BAND, right: 24 } },
      interaction: { mode: "index", intersect: false },
      // The HTML legend under the chart (floorLegend) replaces Chart.js's.
      plugins: { legend: { display: false }, tooltip: { enabled: false, external: tip } },
      scales: {
        x: floorAxis({ stacked: true, grid: { color: "#2e3035" }, ...view }),
        // includeBounds off: the top is wherever the markers needed it, not a
        // round number, so it gets no label of its own crowding the last one.
        y: { stacked: true, grid: { color: "#2e3035" }, ...y, ticks: { color: "#ccc", precision: 0, includeBounds: false, ...y.ticks } },
      },
    },
  };
}

// The legend: one row per half (or one for relics), then the marker key.
function floorLegendRow(head, keys, colors) {
  return `<div class="fl-head">${head}</div><div class="fl-items">${keys.map(k => {
    const fill = isStarter(k) ? hatchCss(colors[k]) : colors[k] + "4d";
    return `<span class="fl-item"><span class="fl-swatch" style="background:${fill};border:2px ${isStarter(k) ? "dashed" : "solid"} ${colors[k]}"></span>${rarityName(k)}</span>`;
  }).join("")}</div>`;
}
function floorMarkerRow(keys, colors) {
  return `<div class="fl-head">Markers</div><div class="fl-items">${keys.map(k => {
    const d = MARK_SIZE[k] * 0.6;
    return `<span class="fl-item"><span class="fl-ring" style="border-color:${colors[k]};width:${d}px;height:${d}px"></span>${k} gained</span>`;
  }).join("")}</div>`;
}

function renderDetailDeckChart(run) {
  const nodes = run.timeline || [];
  const box = document.getElementById("detail-deck-box");
  if (nodes.length === 0 || !run.deckAdded) { box.style.display = "none"; return; }
  box.style.display = "";
  if (detailDeckChart) { detailDeckChart.destroy(); detailDeckChart = null; }

  const { rarity: R, type: T } = DECK_GROUPS;
  const items = heldItems(run.finalDeck || [], run.deckAdded, run.cardsLost || []);
  const byR = countsByFloor(nodes, items, R), byT = countsByFloor(nodes, items, T);
  const byTR = countsByFloor(nodes, items, {
    order: T.order.flatMap(t => R.order.map(r => t + "|" + r)),
    of: c => T.of(c) + "|" + R.of(c),
  });
  const totals = floorTotals(nodes, byR, R.order);
  const cardName = id => cardInfo(id)?.title || fmtCardLabel(id);
  const marks = floorMarks(nodes, items, R, CARD_MARK, cardImgSrc, cardName);
  const tKeys = usedKeys(byT, T.order), rKeys = usedKeys(byR, R.order);

  // The breakdown is a type × rarity table; the floor's marked cards follow it
  // as real card faces.
  const tip = context => showFloorTip(context, i => {
    const rows = tKeys.filter(t => byT[t][i] > 0);
    const cols = [...new Set(["Basic", "Common", "Uncommon", "Rare", ...rKeys])];
    const cell = (t, c) => byTR[t + "|" + c][i] || "";
    // A phone's sheet is too narrow for eight rarity columns, so there the rarities run down
    // and only those with cards on this floor are listed.
    const rar = cols.filter(c => rows.some(t => cell(t, c)));
    const table = floorTipTouch
      ? `<table><tr><th></th>${rows.map(t => `<th style="color:${T.color[t]}">${t}</th>`).join("")}<th>All</th></tr>` +
        rar.map(c => `<tr><td style="color:${R.color[c]}">${rarityName(c)}</td>${rows.map(t => `<td>${cell(t, c)}</td>`).join("")}<td><b>${rows.reduce((n, t) => n + (byTR[t + "|" + c][i] || 0), 0)}</b></td></tr>`).join("") +
        `<tr class="ft-through"><td>All</td>${rows.map(t => `<td>${byT[t][i]}</td>`).join("")}<td>${totals[i]}</td></tr></table>`
      : `<table><tr><th></th>${cols.map(c => `<th style="color:${R.color[c]}">${rarityName(c)}</th>`).join("")}<th>All</th></tr>` +
        rows.map(t => `<tr><td style="color:${T.color[t]}">${t}</td>${cols.map(c => `<td>${cell(t, c)}</td>`).join("")}<td><b>${byT[t][i]}</b></td></tr>`).join("") +
        `</table>`;
    if (floorTipTouch) return `${floorTipHead(nodes[i], totals[i], "cards")}${table}${marks[i].length ? floorTipChips(marks[i], R.color, false) : ""}`;
    const big = marks[i].length ? `<div class="ft-big">${marks[i].map(m =>
      `<div class="ft-card">${renderCardFace(m.id, 0, 190) || `<b>${m.name}</b>`}${floorTipCaption(m, R.color)}</div>`).join("")}</div>` : "";
    return `<div class="ft-row"><div>${floorTipHead(nodes[i], totals[i], "cards")}${table}</div>${big}</div>`;
  });

  // Zero line, with each half named at its left end.
  const halves = {
    id: "deckHalves",
    afterDatasetsDraw(chart) {
      const { ctx, chartArea: { left, right }, scales: { y } } = chart;
      const y0 = y.getPixelForValue(0);
      ctx.save();
      ctx.strokeStyle = ACT_COLOUR;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(left, y0);
      ctx.lineTo(right, y0);
      ctx.stroke();
      ctx.font = "700 14px 'Segoe UI', system-ui, sans-serif";
      ctx.textAlign = "left";
      ctx.fillStyle = ACT_COLOUR;
      ctx.textBaseline = "bottom";
      ctx.fillText("▲ TYPE", left + 6, y0 - 5);
      ctx.textBaseline = "top";
      ctx.fillText("▼ RARITY", left + 6, y0 + 5);
      ctx.restore();
    },
  };

  // Headroom over the peak for the markers, rounded to tens, and more where
  // a floor's stack of markers needs it.
  const peak = Math.max(...totals);
  const y = {
    min: -Math.ceil((peak + 2) / 10) * 10,
    max: Math.ceil(peak * 1.3 / 10) * 10,
    afterDataLimits: markHeadroom(marks, totals, 10),
    ticks: { callback: v => Math.abs(v) },
  };
  detailDeckChart = new Chart(document.getElementById("detail-deck-chart").getContext("2d"),
    floorChartConfig(nodes, [makeMarkPlugin(marks, totals, R.color), halves], tip, y, floorBands([
      ...tKeys.map(k => ({ key: k, data: byT[k], color: T.color[k], stack: "type" })),
      ...rKeys.map(k => ({ key: k, data: byR[k].map(v => -v), color: R.color[k], stack: "rarity" })),
    ])));

  document.getElementById("detail-deck-legend").innerHTML =
    floorLegendRow("▲ Type", tKeys, T.color) +
    floorLegendRow("▼ Rarity", rKeys, R.color) +
    floorMarkerRow(["Uncommon", "Rare"], R.color);
}

function renderDetailRelicChart(run) {
  const nodes = run.timeline || [];
  const box = document.getElementById("detail-relic-box");
  if (nodes.length === 0 || !run.relicsAdded) { box.style.display = "none"; return; }
  box.style.display = "";
  if (detailRelicChart) { detailRelicChart.destroy(); detailRelicChart = null; }

  const G = RELIC_GROUP;
  const items = heldItems(run.finalRelics || [], run.relicsAdded, run.relicsLost || []);
  const counts = countsByFloor(nodes, items, G);
  const totals = floorTotals(nodes, counts, G.order);
  const marks = floorMarks(nodes, items, G, RELIC_MARK, relicImgSrc, id => relicInfo(id)?.title || fmtRelicLabel(id));
  const keys = usedKeys(counts, G.order);

  // The count per rarity; the floor's marked relics follow with their text.
  const tip = context => showFloorTip(context, i => {
    const table = `<table>${keys.filter(k => counts[k][i] > 0).map(k =>
      `<tr><td style="color:${G.color[k]}">${k}</td><td>${counts[k][i]}</td></tr>`).join("")}</table>`;
    if (floorTipTouch) return `${floorTipHead(nodes[i], totals[i], "relics")}${table}${marks[i].length ? floorTipChips(marks[i], G.color, true) : ""}`;
    const big = marks[i].length ? `<div class="ft-big ft-col">${marks[i].map(m => {
      const p = relicTextParts(m.id) || { name: m.name, desc: "" };
      return `<div class="ft-relic" style="border-color:${G.color[m.rarity]}">${m.src ? `<img src="${m.src}" alt="">` : ""}<div>
        <div class="ft-relic-name">${p.name}</div>${floorTipCaption(m, G.color)}<div class="ft-relic-desc">${p.desc}</div></div></div>`;
    }).join("")}</div>` : "";
    return `<div class="ft-row"><div>${floorTipHead(nodes[i], totals[i], "relics")}${table}</div>${big}</div>`;
  });

  const peak = Math.max(...totals);
  detailRelicChart = new Chart(document.getElementById("detail-relic-chart").getContext("2d"),
    floorChartConfig(nodes, [makeMarkPlugin(marks, totals, G.color)], tip,
      { min: 0, max: Math.ceil(peak * 1.3 / 2) * 2, afterDataLimits: markHeadroom(marks, totals, 2) },
      floorBands(keys.map(k => ({ key: k, data: counts[k], color: G.color[k], stack: "relics" })))));

  document.getElementById("detail-relic-legend").innerHTML =
    floorLegendRow("Rarity", keys, G.color) +
    floorMarkerRow(["Uncommon", "Rare", "Ancient"], G.color);
}

// ---- Keeping up by floor ----

// Charts in the order the box shows them (HP by floor leads, from renderDetailHpChart): damage
// taken, damage done, deck composition, energy and cards. Each has its own hover box, and every point is the fight on that floor:
// nothing is averaged across different monsters. An icon marks what winners did on that
// fight, and shows what kind of fight it was. Above them each act is read the same way,
// its fights summed against what winners did on each. DATA.fightDemand
// (tools/power_curve/fight_demand.py) is the fight's side: its HP, and the average turns
// and damage taken of runs that won it with the monsters tuned the same, whoever played
// them. A run the mod has been in also has what the fight did inside (run.measured on the
// site, DATA.measuredRuns for local logs; tools/power_curve/export_measured.py), and only
// those runs can show energy and cards: a run file doesn't say.
const KEEP_LINES = {
  damage: { label: "Damage done", color: YOUR_LINE },
  taken:  { label: "Damage taken", color: YOUR_LINE },
  drawn:  { label: "Cards drawn", color: "#9b7fe0" },
  played: { label: "Cards played", color: "#2fa384" },
  energy: { label: "Card cost", color: "#b5861a" },
};
// Your run is the same solid gold line (YOUR_LINE) on the HP, damage done and damage taken charts.
// In the tip's split bar the incoming damage is red, next to blocked in blue and healed in green.
const KEEP_DEMAND_COLOR = "#c4c4d4";
// What arrived on a turn, split: blocked, healed off, and what got through (red). Each has an icon and a label as well, so colour is never the only cue.
const KEEP_SPLIT = { blocked: "#5aa0e6", healed: "#5cba7d", through: "#e05252" };
// How a reading is named on the page. The keys ("ahead", "meeting", "behind") are
// fight_demand.py's and the CSS classes'; OP, above Hype, is a run's alone.
const KEEP_WORDS = { ahead: "Hype", meeting: "Mid", behind: "Rough" };
// 16px glyphs for the metrics, drawn in the colour of their line on the charts.
const KEEP_ICONS = {
  turns: `<circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M8 4.5V8l2.5 1.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>`,
  damage: `<path d="M3 13 12.5 3.5M8.5 3h4.5v4.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>`,
  taken: `<path d="M8 1.5l1.8 4.3 4.5.4-3.4 3 1 4.4L8 11.1l-3.9 2.5 1-4.4-3.4-3 4.5-.4z" fill="currentColor"/>`,
  blocked: `<path d="M8 1.5l5 2v4.2c0 3-2.1 5.1-5 6.8-2.9-1.7-5-3.8-5-6.8V3.5z" fill="currentColor"/>`,
  healed: `<path d="M8 14C3 10.5 1.8 8 1.8 5.8 1.8 4 3.2 2.8 4.8 2.8c1.2 0 2.5.7 3.2 1.9.7-1.2 2-1.9 3.2-1.9 1.6 0 3 1.2 3 3 0 2.2-1.2 4.7-6.2 8.2z" fill="currentColor"/>`,
  energy: `<path d="M9.3 1L3.5 9h4l-.8 6L12.5 7h-4z" fill="currentColor"/>`,
  draw: `<rect x="3.5" y="2" width="9" height="12" rx="1.6" fill="none" stroke="currentColor" stroke-width="1.6"/>`,
  // Drawn is the outline, played the same card filled: a card in hand and a card used.
  played: `<rect x="3.5" y="2" width="9" height="12" rx="1.6" fill="currentColor"/>`,
};
const keepIcon = (name, color) =>
  `<svg class="keep-ico" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" style="color:${color}">${KEEP_ICONS[name]}</svg>`;
// Fights an act takes before it gets a reading: fight_demand.py's ACT_MIN.
const KEEP_ACT_MIN = 3;
// The acts a run has to read ahead in to be OP: fight_demand.py's OP_ACTS, counted from 1.
const KEEP_OP_ACTS = [2, 3];
// A reading's mark: the shape says it as well as the colour.
const KEEP_SIGNS = { ahead: "▲", meeting: `<i class="bullseye"></i>`, behind: "▼" };
// Fight icons on a chart, in px: up to the HP and gold charts' size, and a floor and a
// half wide when a run has many floors; still readable on a phone.
const KEEP_ICON = { min: 16, max: NODE_POINT };
// The kinds of fight, in the order an act card lists them.
const KEEP_KINDS = { monster: "Normal", elite: "Elites", boss: "Boss" };
// How each tier is named on the page: fight_demand.py's TIER_NAMES, for a reader.
const KEEP_TIER_NAMES = ["A0–7", "A8+"];
let detailKeepCharts = [];

// The measured series for this run, aligned to the chart's nodes by floor number. The run
// carries its own when the site read its event log at upload (infra/lambda/ingest/measured.py);
// DATA.measuredRuns is the same read for the owner's logs on this machine. Null when the run
// has no event log, which is most of them.
function measuredStrengthByNode(run, nodes) {
  const rows = run.measured || (DATA.measuredRuns || {})[run.ts];
  if (!rows || !rows.length) return null;
  const byFloor = new Map(rows.map(r => [r.floor, r]));
  return nodes.map(n => byFloor.get(n.floor + 1) || null);
}

// One player's share of a co-op enemy's HP, over its solo HP: fight_demand.py's hp_share.
const keepShare = (run, node) => !run.mp ? 1 : node.act === 1 ? 1.1 : node.act === 3 && node.type === "boss" ? 1.3 : 1.2;

// How an ascension's monsters are tuned: fight_demand.py's tier.
const keepTier = asc => +(asc >= 8);

// A floor's damage taken with what it healed off it, down to 0: fight_demand.py's net_taken.
const keepTaken = n => Math.max(0, (n.dmg || 0) - (n.healed || 0));

// Which of an encounter's lines this run reads against, or null if too few have won it
// with the monsters tuned the same: fight_demand.py's winners_of.
const keepWinners = (run, d) => {
  const line = d.tiers[keepTier(run.asc)];
  const how = (run.mp && line.coop) || line;
  return how.turns ? how : null;
};

// What was fought on a node, if anything. An event's fight names the fight apart from
// the event, because the map still shows it as the event.
const keepFight = n => n.turns ? n.fight || n.enc : "";

// Whatever the map called the room: a "?" room or an event can hide a fight of either kind.
const keepRank = n => n.type === "boss" ? "Boss" : /_ELITE$/.test(keepFight(n)) ? "Elite" : "";

// A fight's map icon: fight, elite, or the boss's own portrait.
const keepIconKey = n => n.type === "boss" ? nodeIconKey(n) : keepRank(n) ? "elite" : "monster";

// fight_demand.py's readings, floor by floor: keep the two together. A logged fight's HP
// is what the log saw come off, respawns and all, because an enemy's HP rolls per run and
// the table only has its middle. A logged loss can't have left more than was there. Not
// in co-op, until a log has shown whose numbers it carries with a party in the fight.
// A lost fight has no damage figure without a log: the run file doesn't say how much HP
// came off. A death is a death, so the line drops to 0 on that floor instead of stopping
// short, and the hover box says there is no figure. That floor gets a row even when the
// data has no HP for the fight. Damage taken is the run file's on every run, because
// winners' is: all of it, whatever its source, with what the floor healed off it.
function fightReadings(run, nodes, measured) {
  if (!DATA.fightDemand) return null;
  const demand = DATA.fightDemand.encounters;
  const tough = +(run.asc >= 8);
  const lastFight = nodes.findLastIndex(keepFight);
  const rows = nodes.map((n, i) => {
    const d = demand[keepFight(n)];
    const table = d ? d.pool[tough] * keepShare(run, n) : 0;
    const lost = !run.won && i === lastFight;
    if (!table && !lost) return null;
    const how = d && keepWinners(run, d);
    const m = !run.mp && measured && measured[i];
    const pool = !m ? table : lost ? Math.max(table, m.removed) : m.removed;
    const row = { pool, lost, turns: n.turns, many: d?.many };
    if (how) { row.winTurns = how.turns; row.winN = how.n; if (pool) row.ask = pool / how.turns; }
    if (m || !lost) row.doing = (m ? m.removed : pool) / n.turns;
    // Enemies act after you, so a fight you won gives them a turn less.
    const enemyTurns = m ? m.enemyTurns : n.turns - (lost ? 0 : 1);
    if (enemyTurns) {
      row.enemyTurns = enemyTurns;
      // The fight that killed you: the run file stops at the HP you had left, the log
      // has the whole blow.
      const gross = lost && m ? m.taken : n.dmg || 0;
      row.total = Math.max(0, gross - (n.healed || 0));
      row.taken = row.total / enemyTurns;
      row.healedOff = gross - row.total;
      row.healedAll = n.healed || 0;
      row.healed = row.healedOff / enemyTurns;
      if (how) { row.winRate = how.rate; row.winTotal = how.taken; }
      // What the log blocked, and what arrived is that and all of what got through, so
      // the hover box adds up.
      if (m) { row.blocked = m.arrived - m.taken / enemyTurns; row.arrived = row.blocked + row.healed + row.taken; }
    }
    if (m) row.play = { drawn: m.draw, played: m.played, energy: m.listPrice, spent: m.spent, junk: m.junk };
    return row;
  });
  return rows.some(r => r) ? rows : null;
}

// The bars on the damage charts' fight floors: from the best quarter of the wins the average win is of
// to the worst (fight_demand.py's fast and slow, light and heavy), so the bar says how far a win can
// go either way. Damage done a turn is the fight's HP over turns, so the quickest wins do the most.
// A bar needs enough wins to have a quarter. Per floor, {bad, good} or null.
const KEEP_RANGE_MIN = 10;
function keepRanges(run, nodes, rows) {
  const demand = DATA.fightDemand.encounters;
  const done = [], taken = [];
  nodes.forEach((n, i) => {
    const r = rows[i], d = demand[keepFight(n)], how = r && d && keepWinners(run, d);
    const ok = how && how.n >= KEEP_RANGE_MIN;
    done.push(ok && r.ask !== undefined && how.slow && how.fast ? { bad: r.pool / how.slow, good: r.pool / how.fast } : null);
    taken.push(ok && r.winRate !== undefined && how.heavy !== undefined && how.light !== undefined ? { bad: how.heavy, good: how.light } : null);
  });
  return { done, taken };
}

const keepMark = (value, [low, high]) => value < low ? "behind" : value > high ? "ahead" : "meeting";

// Where the worst and best quarter of winning acts start, on guard and pace, for an act
// counted from 1, or of winning runs: fight_demand.py's act_cut and cuts_of.
const keepActCut = act => {
  const cuts = DATA.fightDemand.cuts;
  return cuts.acts[act - 1] || cuts.run;
};

// Where damage taken turns an act Hype or Rough among winners: keepMark's edges on
// guard = (winTaken+1)/(taken+1), solved for taken. Damage taken is a whole number, so
// Hype is the most that still reads Hype and Rough the least that reads Rough. hype is -1
// when winners took so little that no amount reads Hype.
const keepCuts = (winTaken, edges) => {
  const guard = taken => (winTaken + 1) / (taken + 1);
  let hype = Math.ceil((winTaken + 1) / edges[1] - 1) - 1, low = Math.floor((winTaken + 1) / edges[0] - 1) + 1;
  // The division can land a hair either side of a whole number, so settle both on
  // keepMark's own comparison.
  while (hype >= 0 && keepMark(guard(hype), edges) !== "ahead") hype--;
  while (keepMark(guard(hype + 1), edges) === "ahead") hype++;
  while (keepMark(guard(low), edges) !== "behind") low++;
  while (low > 0 && keepMark(guard(low - 1), edges) === "behind") low--;
  return { hype, low };
};
// Turns that lift a Mid on damage to Hype: winners' turns over yours past the best quarter.
const keepFastTurns = (winTurns, edges) => Math.ceil(winTurns / edges[1]) - 1;

// fight_demand.py's verdict.
const keepVerdict = (pace, guard, cut) => {
  const held = keepMark(guard, cut.guard);
  return held === "meeting" && pace > cut.pace[1] && guard >= 1 ? "ahead" : held;
};

// fight_demand.py's act_readings and lacking: keep them together. Turns and damage taken
// are the run file's on every run, logged or not, because winners' averages are built
// from them. A log adds what a run file can't say.
function actReadings(run, nodes, measured) {
  // A fight_demand.json from before the quarters has nothing to read an act against.
  if (!DATA.fightDemand?.cuts) return [];
  const demand = DATA.fightDemand.encounters;
  const lastFight = nodes.findLastIndex(keepFight);
  const acts = new Map();
  nodes.forEach((n, i) => {
    const d = demand[keepFight(n)];
    const how = d && keepWinners(run, d);
    if (!how || (!run.won && i === lastFight)) return;
    if (!acts.has(n.act)) acts.set(n.act, { act: n.act, fights: 0, kinds: {}, turns: 0, winTurns: 0, taken: 0, healed: 0, winTaken: 0, log: null });
    const a = acts.get(n.act);
    a.fights++;
    const key = keepIconKey(n);
    a.kinds[key] = (a.kinds[key] || 0) + 1;
    a.turns += n.turns;
    a.winTurns += how.turns;
    a.taken += keepTaken(n);
    a.healed += (n.dmg || 0) - keepTaken(n);
    a.winTaken += how.taken;
    const m = !run.mp && measured && measured[i];
    if (!m) return;
    a.log = a.log || { turns: 0, removed: 0, drawn: 0, played: 0, energy: 0, spent: 0 };
    a.log.turns += n.turns;
    a.log.removed += m.removed;
    a.log.drawn += m.draw * n.turns;
    a.log.played += m.played * n.turns;
    a.log.energy += m.listPrice * n.turns;
    a.log.spent += m.spent * n.turns;
  });
  const short = (pace, each) => pace < each ? "damage" : "block";
  return [...acts.values()].filter(a => a.fights >= KEEP_ACT_MIN).map(a => {
    const pace = a.winTurns / a.turns, guard = (a.winTaken + 1) / (a.taken + 1), each = guard / pace;
    const cut = keepActCut(a.act);
    const speed = keepMark(pace, cut.pace), held = keepMark(guard, cut.guard);
    const verdict = keepVerdict(pace, guard, cut);
    return { ...a, cut, pace, guard, each, speed, held, verdict, lacking: verdict === "behind" ? short(pace, each) : null };
  });
}

// fight_demand.py's run_reading: keep them together. A run as a whole, its acts' totals
// through the same verdict against winning runs' quarters, so it follows from the act
// cards. OP is both of the late acts reading ahead, and takes no win.
function runReading(acts) {
  if (!acts.length) return null;
  const sum = key => acts.reduce((total, a) => total + a[key], 0);
  const turns = sum("turns"), winTurns = sum("winTurns"), taken = sum("taken"), winTaken = sum("winTaken");
  const pace = winTurns / turns, guard = (winTaken + 1) / (taken + 1);
  const op = KEEP_OP_ACTS.every(act => acts.some(a => a.act === act && a.verdict === "ahead"));
  const cut = DATA.fightDemand.cuts.run;
  return { turns, winTurns, taken, winTaken, pace, guard, cut, verdict: keepVerdict(pace, guard, cut), op };
}

// The run list reads every run to fill a column and sort by it, so each is read once.
// Only what a run file says: the log's figures make no difference to a verdict.
const keepRunReadings = new WeakMap();
function runReadingOf(run) {
  if (!keepRunReadings.has(run)) keepRunReadings.set(run, runReading(actReadings(run, run.timeline || [], null)));
  return keepRunReadings.get(run);
}

// OP, then ahead down to behind, then runs with no reading.
function runReadingRank(run) {
  const r = runReadingOf(run);
  return !r ? 0 : r.op ? 4 : ["behind", "meeting", "ahead"].indexOf(r.verdict) + 1;
}

const keepSignal = (tone, what) => `<span class="keep-signal ${tone}" role="img" aria-label="${what}" title="${what}">${KEEP_SIGNS[tone]}</span>`;

// How the rating works, with this reading's two cut points, for a mark's hover.
function keepRule(winTaken, cut) {
  const { hype, low } = keepCuts(winTaken, cut.guard);
  return `The average win took ${+winTaken.toFixed(1)} damage on these fights. ${hype >= 0 ? `Hype: you took ${hype} or less. ` : ""}Mid: ${hype + 1} to ${low - 1}. Rough: ${low} or more. ` +
    `A Mid counts as Hype if you took no more than they did and finished faster than 3 in 4 wins.`;
}

// One measure on a tooltip's meter: Hype, Mid and Rough zones side by side, the figure on a
// pointer, and the two cut points under the zone edges. aheadEnd is where the Hype zone stops
// (0 for none) and behindAt where Rough starts, in the measure's own units.
function keepTipMeter(name, value, vs, aheadEnd, behindAt, cuts) {
  const top = Math.max(behindAt * 1.3, value * 1.1, 1);
  const pct = v => Math.min(100, Math.max(0, v / top * 100));
  const aheadW = aheadEnd > 0 ? pct(aheadEnd) : 0, lowAt = pct(behindAt), at = pct(value);
  const zone = (tone, w) => `<span class='kt-zone ${tone}' style='flex:${w} 1 0'>${KEEP_SIGNS[tone]}</span>`;
  const cut = (w, text, cls = "") => `<span class='kt-cut ${cls}' style='flex:${w} 1 0'>${text}</span>`;
  return `<div class='kt-row'><div class='kt-head'><span>${name}</span><b>${value}</b><span class='kt-vs'>vs ${vs}</span></div>` +
    `<div class='kt-bar'>${aheadW ? zone("ahead", aheadW) : ""}${zone("meeting", lowAt - aheadW)}${zone("behind", 100 - lowAt)}` +
    `<i class='kt-mark${at > 88 ? " last" : ""}' style='left:${at}%'></i></div>` +
    `<div class='kt-cuts'>${aheadW ? cut(aheadW, cuts[0]) : ""}${cut(lowAt - aheadW, "")}${cut(100 - lowAt, cuts[1], "low")}</div></div>`;
}

// Turns where winners' pace tips into fast or slow, settled on keepMark's own comparison.
function keepTurnCuts(x) {
  const fast = keepFastTurns(x.winTurns, x.cut.pace);
  let slow = Math.floor(x.winTurns / x.cut.pace[0]) + 1;
  while (slow > 1 && keepMark(x.winTurns / (slow - 1), x.cut.pace) === "behind") slow--;
  while (keepMark(x.winTurns / slow, x.cut.pace) !== "behind") slow++;
  return { fast, slow };
}

// The hover for a run's or an act's reading, built to read at a glance: the verdict, then
// damage taken and fight turns each on a Hype/Mid/Rough meter against the average win, then
// the one line that says why. x is a run's or act's totals (turns, winTurns, taken, winTaken,
// cut, verdict); extra are plain lines after it. Lines are joined by a newline for data-tip,
// so the markup has no newlines and quotes are escaped for the attribute.
function keepReadingTip(x, head, why, extra = []) {
  const { damage, turns, held, speed } = keepReadingMeters(x);
  const html = [head, damage, turns, why(held, speed), ...extra].join("\n");
  return html.replace(/&/g, "&amp;").replace(/"/g, "&quot;");
}

// A run's or act's damage taken and fight turns as two Hype/Mid/Rough meters, and how each
// holds against the average win.
function keepReadingMeters(x) {
  const { hype, low } = keepCuts(x.winTaken, x.cut.guard);
  const held = keepMark((x.winTaken + 1) / (x.taken + 1), x.cut.guard), speed = keepMark(x.winTurns / x.turns, x.cut.pace);
  const { fast, slow } = keepTurnCuts(x);
  return {
    held, speed,
    damage: keepTipMeter("Damage taken", Math.round(x.taken), Math.round(x.winTaken), hype + 1, low, [`≤ ${hype}`, `≥ ${low}`]),
    turns: keepTipMeter("Fight turns", x.turns, +x.winTurns.toFixed(1), fast + 1, slow, [`≤ ${fast}`, `≥ ${slow}`]),
  };
}

// What a reading comes to, in a line: damage taken, and whether the turns back it up.
const keepWhy = x => (held, speed) => {
  const fast = speed === "ahead", slow = speed === "behind";
  if (x.verdict === "ahead") return held === "ahead" ? "Less damage taken than 3 in 4 wins." : "Damage in the middle, but fast with it.";
  if (x.verdict === "behind") return held === "behind" ? `More damage taken than 3 in 4 wins${fast ? ", though fast." : slow ? ", and slower." : ", and no faster."}` : "";
  return "Damage in the middle of wins.";
};

// A run's reading on its header, or just its mark in the run list (short). The numbers
// are on hover, as they are on an act's mark.
function runReadingHtml(run, short = false) {
  const r = runReadingOf(run);
  if (!r) return "";
  const word = KEEP_WORDS[r.verdict];
  const opLine = `OP: Hype in Acts ${KEEP_OP_ACTS.join(" and ")}`;
  if (short) {
    const tip = keepReadingTip(r, r.op ? opLine : `${word} against the average win on this run's fights`,
      keepWhy(r), run.won ? [] : ["Not counting the fight that ended it."]);
    if (r.op) return `<span class="run-reading op" data-tip="${tip}">OP</span>`;
    return `<span class="keep-signal ${r.verdict}" role="img" aria-label="${word}" data-tip="${tip}">${KEEP_SIGNS[r.verdict]}</span>`;
  }
  // On the header the meters are shown (runReadingMetersHtml), so the pill's hover keeps only
  // what they don't say.
  const note = [r.op ? opLine : "", run.won ? "" : "Not counting the fight that ended it."].filter(Boolean).join("\n");
  const attrs = note ? ` data-tip="${note.replace(/&/g, "&amp;").replace(/"/g, "&quot;")}" tabindex="0"` : "";
  if (r.op) return `<span class="run-reading op"${attrs}><span aria-hidden="true">▲▲</span>OP</span>`;
  return `<span class="run-reading ${r.verdict}"${attrs}><span class="keep-signal ${r.verdict}" aria-hidden="true">${KEEP_SIGNS[r.verdict]}</span>${word}</span>`;
}

// Each act's own mark under the run's header, so where the run's rating comes from shows
// (OP is Acts 2 and 3 both Hype).
function runActMarksHtml(run) {
  const acts = actReadings(run, run.timeline || [], null);
  if (!acts.length) return "";
  return `<div class="run-act-marks"><span class="ram-title">By act</span>` + acts.map(a =>
    `<span class="ram-act">Act ${a.act}${keepSignal(a.verdict, `Act ${a.act}: ${KEEP_WORDS[a.verdict]}`)}</span>`).join("") + `</div>`;
}

function renderKeepActs(run, nodes, measured) {
  const box = document.getElementById("detail-keep-acts");
  const acts = actReadings(run, nodes, measured);
  box.style.display = acts.length ? "" : "none";
  // One metric on one line, as cells of the half-card's grid: icon and label take the slack,
  // then the figure and either its mark and the average win's, or (a per-turn figure) its
  // note. A sub line, when there is one, runs the half's width under it.
  const row = (icon, label, figure, { mark, vs, note, sub } = {}) =>
    `<span class="ka-label">${icon}${label}</span><b class="ka-fig">${figure}</b>` +
    (mark === undefined ? `<span class="ka-note">${note || ""}</span>` : `<span class="ka-mark">${mark}</span>${vs}`) +
    (sub ? `<span class="ka-sub">${sub}</span>` : "");
  // The average win's figure, whole, with the exact average on hover.
  const vs = (v, unit) => `<span class="ka-vs" title="Average win ${+v.toFixed(1)} ${unit}">vs ${v.toFixed(0)}</span>`;
  // Damage taken on a three-zone meter the card's width: Hype, Mid, Rough, each with its mark
  // and (when it has room) its word, the act's own figure on a pointer, and the two cut points under the zone edges they belong to. The meter runs a
  // little past Rough.
  // aheadEnd is where the Hype zone stops (0 for none), low where Rough starts.
  const meter = (taken, aheadEnd, low, label) => {
    const top = Math.max(low * 1.3, taken * 1.1, 1);
    const pct = v => Math.min(100, Math.max(0, v / top * 100));
    const hype = aheadEnd - 1;
    const hypeW = aheadEnd > 0 ? pct(aheadEnd) : 0, lowAt = pct(low);
    const zone = (tone, w, text) => `<span class="ks-zone ${tone}" style="flex:${w} 1 0"><b aria-hidden="true">${KEEP_SIGNS[tone]}</b><span class="ks-word">${text}</span></span>`;
    const cut = (cls, w, text) => `<span class="ks-cut ${cls}" style="flex:${w} 1 0">${text}</span>`;
    const at = pct(taken);
    return `<div class="keep-meter" role="img" aria-label="${label}" title="${label}">` +
      `<div class="ks-bar">` +
      (hypeW ? zone("ahead", hypeW, KEEP_WORDS.ahead) : "") + zone("meeting", lowAt - hypeW, KEEP_WORDS.meeting) + zone("behind", 100 - lowAt, KEEP_WORDS.behind) +
      `<i class="ks-mark${at < 12 ? " first" : at > 88 ? " last" : ""}" style="left:${at}%"><b>${taken}</b></i></div>` +
      `<div class="ks-cuts">` +
      (hypeW ? cut(hypeW < 16 ? "hype start" : "hype", hypeW, `≤ ${hype}`) : "") + cut("mid", lowAt - hypeW, "") + cut("low", 100 - lowAt, `≥ ${low}`) + `</div></div>`;
  };
  // How near a Mid is to either edge, said only when it is within a fifth of the meter. Hover only.
  const nearNote = a => {
    if (a.held !== "meeting") return "";
    const { hype, low } = keepCuts(a.winTaken, a.cut.guard);
    const taken = Math.round(a.taken);
    const top = Math.max(low * 1.3, taken * 1.1, 1);
    const [gap, edge] = [[low - taken, "Rough"], [hype >= 0 ? taken - hype : Infinity, "Hype"]].sort((x, y) => x[0] - y[0])[0];
    return gap <= top * 0.2 ? `${gap} HP from ${edge}` : "";
  };
  // What would lift a Mid to Hype on speed: finishing in few enough turns while taking no
  // more than the average win did. Said only while it can still matter, and ticked off once
  // it has. Hover only.
  const speedNote = a => {
    const fast = keepFastTurns(a.winTurns, a.cut.pace), cap = Math.floor(a.winTaken);
    if (a.verdict === "ahead" && a.held === "meeting") return `Hype on speed (damage ≤ ${cap})`;
    if (a.verdict !== "meeting" || fast < 1) return "";
    return a.turns <= fast ? `Fast enough; Hype if damage ≤ ${cap}` : `Hype at ${fast} or fewer, with damage ≤ ${cap}`;
  };
  // The fights an act's numbers cover, by kind: normal, elites, boss.
  const kindOf = key => key in KEEP_KINDS ? key : "boss";
  const order = Object.keys(KEEP_KINDS);
  const kinds = a => Object.entries(a.kinds).sort(([x], [y]) => order.indexOf(kindOf(x)) - order.indexOf(kindOf(y))).map(([key, n]) =>
    `<span class="keep-kind" title="${KEEP_KINDS[kindOf(key)]}: ${n}">${nodeIconHtml(key, 20, kindOf(key))}${n}</span>`).join("");
  // The run's rating first, across the grid: its totals on the same two meters, and how it is read.
  const whole = runReadingOf(run);
  const wholeMeters = whole ? keepReadingMeters(whole) : null;
  const wholeCard = whole ? `<div class="keep-run keep-act"><h3><span class="ka-title">Run rating</span>${runReadingHtml(run)}</h3>` +
    `<p class="kr-desc">Damage taken and fight turns from every act added up, against the average win on the same fights. OP means a Hype rating in both Acts ${KEEP_OP_ACTS.join(" and ")} which signals a consistently strong deck through mid and late game.</p>` +
    `<div class="kr-meters">${wholeMeters.damage}${wholeMeters.turns}</div></div>` : "";
  box.innerHTML = wholeCard + acts.map(a => {
    const log = a.log;
    const perTurn = v => (v / log.turns).toFixed(1);
    const dmgCuts = keepCuts(a.winTaken, a.cut.guard), { fast: turnFast, slow: turnSlow } = keepTurnCuts(a);
    const pill = `<span class="run-reading ${a.verdict}"><span class="keep-signal ${a.verdict}" aria-hidden="true">${KEEP_SIGNS[a.verdict]}</span>${KEEP_WORDS[a.verdict]}</span>`;
    const perTurnRow = (icon, label, value, note) => row(icon, label, `${perTurn(value)}<small>/turn</small>`, { note });
    // Against the average win on the left, what the deck did per turn on the right; a card
    // too narrow for two columns stacks them.
    return `<div class="keep-act"><h3><span class="ka-title">Act ${a.act}<span class="keep-kinds">${kinds(a)}</span></span>${pill}</h3>` +
      `<div class="ka-body"><div class="ka-half ka-main">` +
      row(keepIcon("turns", KEEP_DEMAND_COLOR), "Fight turns", a.turns,
        { mark: keepSignal(a.speed, `Fight turns: ${KEEP_WORDS[a.speed]}`), vs: vs(a.winTurns, "turns") }) +
      meter(a.turns, turnFast >= 1 ? turnFast + 1 : 0, turnSlow, `Fight turns ${a.turns}: ${KEEP_WORDS[a.speed]}. Hype at ${turnFast} or fewer, Rough at ${turnSlow} or more.`) +
      row(keepIcon("taken", KEEP_LINES.taken.color), "Damage taken", Math.round(a.taken),
        { mark: keepSignal(a.held, `Damage taken: ${KEEP_WORDS[a.held]}`), vs: vs(a.winTaken, "damage") }) +
      meter(Math.round(a.taken), dmgCuts.hype >= 0 ? dmgCuts.hype + 1 : 0, dmgCuts.low, `Damage taken ${Math.round(a.taken)}: ${KEEP_WORDS[a.held]}. ${keepRule(a.winTaken, a.cut)}`) + `</div>` +
      (log ? `<div class="ka-half ka-flow">` + perTurnRow(keepIcon("damage", KEEP_LINES.damage.color), "Damage", log.removed, `${(log.removed / log.played).toFixed(1)}/card`) +
        perTurnRow(keepIcon("energy", KEEP_LINES.energy.color), "Card cost", log.energy, `paid ${perTurn(log.spent)}`) +
        perTurnRow(keepIcon("draw", KEEP_LINES.drawn.color), "Draw", log.drawn, "") +
        perTurnRow(keepIcon("played", KEEP_LINES.played.color), "Cards played", log.played, "") + `</div>` : "") +
      `</div></div>`;
  }).join("");
}

// What each floor added and removed, per timeline node, as { cards, relics } lists of
// [id, upgraded, +1/-1]. cards and relics are heldItems() lists; a card counts as upgraded
// once a Smith or event has upgraded that many copies of it, as approaches.states does.
function floorChanges(nodes, cards, relics) {
  const order = [...cards].sort((a, b) => a.added - b.added);
  const ups = {};
  let prevCards = {}, prevRelics = new Set();
  return nodes.map(node => {
    const f = node.floor + 1;
    (node.upgradedCards || []).forEach(id => { ups[id] = (ups[id] || 0) + 1; });
    const left = { ...ups }, deck = {};
    order.forEach(c => {
      if (c.added > f || c.removed <= f) return;
      const up = (left[c.id] || 0) > 0;
      left[c.id] = (left[c.id] || 0) - 1;
      const key = c.id + (up ? "+" : "");
      deck[key] = (deck[key] || 0) + 1;
    });
    const held = new Set(relics.filter(r => r.added <= f && r.removed > f).map(r => r.id));
    const change = [];
    new Set([...Object.keys(deck), ...Object.keys(prevCards)]).forEach(key => {
      const d = (deck[key] || 0) - (prevCards[key] || 0);
      for (let i = 0; i < Math.abs(d); i++) change.push([key.replace(/\+$/, ""), key.endsWith("+"), Math.sign(d)]);
    });
    const relicChange = [...held].filter(id => !prevRelics.has(id)).map(id => [id, false, 1])
      .concat([...prevRelics].filter(id => !held.has(id)).map(id => [id, false, -1]));
    prevCards = deck; prevRelics = held;
    return { cards: change, relics: relicChange };
  });
}

// The act picker above the Keeping Up charts, for a phone: one button per act the run reached.
// Choosing one moves every chart's window; the charts themselves aren't rebuilt.
function renderKeepActPicker() {
  const box = document.getElementById("detail-keep-actpick");
  const spans = actSpans(keepActNodes);
  const on = (keepActSpan(keepActNodes) || spans[0] || {}).act;
  box.innerHTML = spans.map(s => `<button type="button" data-act="${s.act}" aria-pressed="${s.act === on}"${s.act === on ? ` class="on"` : ""}>Act ${s.act}${s.name ? `<small>${s.name}</small>` : ""}</button>`).join("");
}
function applyKeepAct() {
  [detailHpChart, ...detailKeepCharts].filter(Boolean).forEach(c => {
    const w = actWindow(keepActNodes), x = c.options.scales.x;
    x.min = w.min; x.max = w.max; x.offset = !!w.offset;
    c.data.datasets.forEach(d => { if (d.clip !== undefined) d.clip = iconClip(); });
    c.update("none");
  });
  renderKeepActPicker();
  closeFloorTip();
}
document.addEventListener("click", e => {
  const b = e.target.closest("#detail-keep-actpick button[data-act]");
  if (b) { keepAct = Number(b.dataset.act); applyKeepAct(); }
});
narrowScreen.addEventListener("change", () => { if (keepActNodes.length) applyKeepAct(); });

function renderDetailKeepCharts(run) {
  const nodes = run.timeline || [];
  keepActNodes = nodes;
  renderKeepActPicker();
  const box = document.getElementById("detail-keep-box");
  detailKeepCharts.forEach(c => c.destroy());
  detailKeepCharts = [];
  closeFloorTip();
  const measured = measuredStrengthByNode(run, nodes);
  const rows = fightReadings(run, nodes, measured);
  if (!rows) { box.style.display = "none"; return; }
  box.style.display = "";
  document.getElementById("detail-keep-tier").textContent = KEEP_TIER_NAMES[keepTier(run.asc)];
  // The caption's key draws the same marks as the pills, so the two can't drift apart.
  for (const s of box.querySelectorAll(".chart-caption .keep-signal")) s.innerHTML = KEEP_SIGNS[s.classList[1]];
  renderKeepActs(run, nodes, measured);

  const changes = nodes.length && run.deckAdded && run.relicsAdded ? floorChanges(nodes,
    heldItems(run.finalDeck || [], run.deckAdded, run.cardsLost || []),
    heldItems(run.finalRelics || [], run.relicsAdded, run.relicsLost || [])) : null;
  const name = ([id], relic) => relic ? relicInfo(id)?.title || fmtRelicLabel(id) : cardInfo(id)?.title || fmtCardLabel(id);
  // A pickup: its picture, then its name. data-pick says what to show in full on hover:
  // "card:ID:1" (upgraded) or "relic:ID".
  const chips = (list, relic) => list.map(c => {
    const src = relic ? relicImgSrc(c[0]) : cardImgSrc(c[0]);
    return `<span class="strength-chip ${c[2] > 0 ? "gain" : "loss"}" data-pick="${relic ? "relic" : "card"}:${c[0]}${relic ? "" : ":" + +c[1]}">` +
      `${src ? `<img src="${src}" alt="" loading="lazy">` : ""}${c[2] > 0 ? "+" : "−"} ${name(c, relic)}${c[1] ? "+" : ""}</span>`;
  }).join("");
  const changed = i => {
    const s = changes && i ? changes[i] : null;
    return s && (s.cards.length || s.relics.length)
      ? `<div class="strength-chips">${chips(s.cards, false)}${chips(s.relics, true)}</div>` : "";
  };

  // The simple tip table: key, label, figure, note.
  const row = (label, color, value, note) => `<tr><td><span class="strength-key" style="background:${color}"></span>` +
    `${label}</td><td><b>${value}</b></td><td class="strength-measured">${note || ""}</td></tr>`;
  const aTurn = v => `${v.toFixed(1)} a turn`;
  // The fight table: label | this run: fight, a turn | average win: fight, a turn. A cell with no
  // figure is left empty so the columns stay put. `key` is the swatch or icon before the label.
  const fightHead = `<thead><tr><th></th><th colspan="2">This run</th><th colspan="2" class="ft-win">Avg win</th></tr>` +
    `<tr class="ft-sub"><th></th><th>Fight</th><th>A turn</th><th class="ft-win">Fight</th><th class="ft-win">A turn</th></tr></thead>`;
  const frow = (key, label, you, perTurn, win, winPerTurn, cls = "") =>
    `<tr class="${cls}"><td>${key}${label}</td><td><b>${you ?? ""}</b></td><td>${perTurn ?? ""}</td>` +
    `<td class="ft-win">${win ?? ""}</td><td class="ft-win">${winPerTurn ?? ""}</td></tr>`;
  const swatch = color => `<span class="strength-key" style="background:${color}"></span>`;
  const one = v => v === undefined ? undefined : v.toFixed(1);
  // What sort of fight it was, so a bad one can be read as a lack of damage to many targets.
  const fightKind = (n, r) => r && r.many !== undefined ? `<div class="ft-cap">${[keepRank(n), r.many ? "Multi-enemy" : "Single enemy"].filter(Boolean).join(" · ")}</div>` : "";
  // Each chart's hover box: the floor, that chart's own numbers, what the floor changed.
  // `body` gets the floor's reading and returns HTML (a table, and whatever goes with it).
  const tip = body => context => showFloorTip(context, i => {
    const inner = rows[i] ? body(rows[i]) : "";
    const head = floorTipHead({ ...nodes[i], enc: nodes[i].fight || nodes[i].enc });
    return `${head}${fightKind(nodes[i], rows[i])}${inner}${changed(i)}`;
  });
  const simple = lines => r => { const list = lines(r); return list.length ? `<table>${list.join("")}</table>` : ""; };

  const damageTip = tip(r => {
    const lost = r.doing === undefined;
    const hp = r.pool ? `${Math.round(r.pool)}${run.mp ? "/player" : ""}` : "";
    const wins = r.ask === undefined ? "" : `<div class="ft-cap">Average of ${r.winN} win${r.winN === 1 ? "" : "s"}</div>`;
    const done = lost
      ? frow(swatch(KEEP_LINES.damage.color), "Damage done", "—", "—", hp, one(r.ask))
      : frow(swatch(KEEP_LINES.damage.color), "Damage done", hp, one(r.doing), r.ask === undefined ? "" : hp, one(r.ask));
    return `<table>${fightHead}${done}` +
      frow(swatch(KEEP_DEMAND_COLOR), "Fight turns", r.turns, "", r.ask === undefined ? "" : +r.winTurns.toFixed(1), "") +
      `</table>${wins}${lost ?`<div class="ft-cap">Lost here, no log to say.</div>` : ""}`;
  });

  // What arrived each turn, split into what was blocked, healed back, and got through. The
  // bar is as wide as what arrived; winners' figures are in the table.
  const inTip = tip(r => {
    if (r.taken === undefined) return "";
    const et = r.enemyTurns, k = KEEP_SPLIT;
    const share = v => r.arrived ? `<small>${Math.round(v / r.arrived * 100)}%</small>` : "";
    const through = key => frow(key, `Damage taken ${share(r.taken)}`, Math.round(r.total), one(r.taken),
      r.winRate === undefined ? "" : Math.round(r.winTotal), one(r.winRate), "ft-through");
    if (r.arrived === undefined) return `<table>${fightHead}${r.healedOff ? frow(keepIcon("healed", k.healed), "Healed", r.healedOff, one(r.healed), "", "") : ""}${through(keepIcon("taken", k.through))}</table>`;
    const seg = (v, color, what) => v > 0 ? `<span style="flex:${v} 1 0;background:${color}" title="${what}"></span>` : "";
    return `<div class="ft-split" role="img" aria-label="Of ${r.arrived.toFixed(1)} a turn arriving: ${r.blocked.toFixed(1)} blocked, ${r.healed.toFixed(1)} healed, ${r.taken.toFixed(1)} got through">` +
      seg(r.blocked, k.blocked, "Blocked") + seg(r.healed, k.healed, "Healed") + seg(r.taken, k.through, "Got through") + `</div>` +
      `<table>${fightHead}` +
      frow(swatch(KEEP_DEMAND_COLOR), "Arrived", Math.round(r.arrived * et), one(r.arrived), "", "") +
      frow(keepIcon("blocked", k.blocked), `Blocked ${share(r.blocked)}`, Math.round(r.blocked * et), one(r.blocked), "", "") +
      (r.healedOff ? frow(keepIcon("healed", k.healed), `Healed ${share(r.healed)}`, r.healedOff, one(r.healed), "", "") : "") +
      through(keepIcon("taken", k.through)) + `</table>`;
  });
  const playTip = tip(simple(r => r.play ? [
    row("Cards drawn", KEEP_LINES.drawn.color, aTurn(r.play.drawn)),
    row("Cards played", KEEP_LINES.played.color, aTurn(r.play.played)),
    row("Card cost", KEEP_LINES.energy.color, aTurn(r.play.energy), "Printed costs of the cards played, added up."),
    row("Energy paid", KEEP_DEMAND_COLOR, aTurn(r.play.spent), "What you really spent. Discounts and free plays make it lower."),
    ...(r.play.junk ? [row("Junk", KEEP_DEMAND_COLOR, r.play.junk)] : []),
  ] : []));

  const view = actView(nodes);
  const floorsShown = view ? view.to - view.from + 1 : nodes.length;
  const iconSize = Math.round(Math.min(KEEP_ICON.max, Math.max(KEEP_ICON.min, 1.7 * box.clientWidth / floorsShown)));
  // `icons` is the chart's id when its floors carry the fight icons: always on your own line,
  // as on the HP chart, so the icon never moves to somewhere else on the chart.
  const line = ({ label, color, dash }, pick, icons) => ({
    label, data: rows.map(r => { const v = r ? pick(r) : null; return v === undefined ? null : v; }),
    borderColor: color, pointHoverBackgroundColor: color,
    borderWidth: 2, borderDash: dash || [], pointRadius: 0, pointHoverRadius: 4, spanGaps: true,
    cubicInterpolationMode: "monotone",
    ...(icons && nodePoints(nodes, () => detailKeepCharts.find(c => c.canvas.id === `detail-keep-${icons}-chart`),
      (n, key, i) => rows[i] && pick(rows[i]) !== undefined, iconSize, keepIconKey)),
  });
  // The average win: a faint dotted line, no icons.
  const winners = pick => ({
    label: "Average win", data: rows.map(r => { const v = r ? pick(r) : null; return v === undefined ? null : v; }),
    borderColor: "#b9b9c4", pointHoverBackgroundColor: "#b9b9c4",
    borderWidth: 1.5, borderDash: [2, 4], pointRadius: 0, pointHoverRadius: 3, spanGaps: true,
    cubicInterpolationMode: "monotone",
  });
  const ranges = keepRanges(run, nodes, rows);
  const chart = (id, series, tipFor, marks, up) => {
    // Only the lines.
    // The ring, where the chart has any, is the HP chart's: the best quarter of the wins.
    const ring = marks && marks.some(m => m) ? rangeKey("Best and worst 25% of wins", false) : "";
    document.getElementById(`detail-keep-${id}-legend`).innerHTML = `<div class="fl-items">${series.filter(s => s.showLine !== false).map(s =>
      `<span class="fl-item"><span class="strength-key" style="background:${s.borderDash?.length ? `repeating-linear-gradient(90deg, ${s.borderColor} 0 4px, transparent 4px 7px)` : s.borderColor}"></span>${s.label}</span>`
    ).join("")}${ring}</div>`;
    // Room for a ring that sits above everything else on the chart.
    const yAxis = { ...iconAxis({ min: 0 }), stacked: false, ticks: { maxTicksLimit: 5 }, reverse: !!up };
    const stretch = yAxis.afterDataLimits;
    yAxis.afterDataLimits = scale => {
      const v = actView(nodes);   // only the bars in view, on a phone showing one act
      (marks || []).forEach((m, i) => { if (m && (!v || (i >= v.from && i <= v.to))) scale.max = Math.max(scale.max, m.bad, m.good); });
      stretch(scale);
    };
    detailKeepCharts.push(new Chart(document.getElementById(`detail-keep-${id}-chart`).getContext("2d"),
      floorChartConfig(nodes, marks ? [makeWinRangePlugin(marks)] : [], tipFor, yAxis, series, actWindow(nodes))));
  };

  // Cards in the deck after each floor: a line per type (the total is in the hover box, not drawn: it dwarfed the types), so what
  // went in can be read against the HP and damage charts either side of it. Its hover box is
  // the type counts and what the floor added, and works on every floor, fights or not.
  const deckBox = document.getElementById("detail-keep-deck");
  deckBox.style.display = run.deckAdded ? "" : "none";
  if (run.deckAdded) {
    const T = DECK_GROUPS.type;
    const held = heldItems(run.finalDeck || [], run.deckAdded, run.cardsLost || []);
    const byT = countsByFloor(nodes, held, T);
    const tKeys = usedKeys(byT, T.order);
    const sizes = floorTotals(nodes, byT, T.order);
    const deckTip = context => showFloorTip(context, i =>
      `${floorTipHead({ ...nodes[i], enc: nodes[i].fight || nodes[i].enc }, sizes[i], "cards")}` +
      `<table>${tKeys.filter(k => byT[k][i] > 0).map(k => row(k, T.color[k], byT[k][i])).join("")}</table>${changed(i)}`);
    const deckLine = (label, color, data, dash) => ({
      label, data, borderColor: color, pointHoverBackgroundColor: color,
      borderWidth: 2, borderDash: dash || [], pointRadius: 0, pointHoverRadius: 4,
      cubicInterpolationMode: "monotone",
    });
    chart("deck", tKeys.map(k => deckLine(k, T.color[k], byT[k])), deckTip);
  }

  chart("damage", [line(KEEP_LINES.damage, r => r.doing ?? 0, "damage"), winners(r => r.ask)], damageTip, ranges.done);
  chart("in", [line(KEEP_LINES.taken, r => r.taken, "in"), winners(r => r.winRate)], inTip, ranges.taken, true);

  const played = rows.some(r => r && r.play);
  document.getElementById("detail-keep-play").style.display = played ? "" : "none";
  document.getElementById("detail-keep-play-none").style.display = played ? "none" : "";
  if (played) chart("play", [
    line(KEEP_LINES.drawn, r => r.play && r.play.drawn),
    line(KEEP_LINES.played, r => r.play && r.play.played),
    line(KEEP_LINES.energy, r => r.play && r.play.energy),
  ], playTip);
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
