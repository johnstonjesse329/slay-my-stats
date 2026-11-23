// =========================================================================
// Relics page: each character's favorite relics, yours above all players',
// and every relic's offer and pick rates. Shares the Cards page's tallies and
// markup (favTalliesYou, favTalliesAll, favPicksFor, favItemHtml and
// FAV_METRICS in cards-page.js), so a relic reads the same in both places.
// =========================================================================

const RELIC_SLOT = { label: "Relic", kind: "relics", test: id => id in (DATA.relicData || {}) };
let relicsNameFilter = "";
let relicsSortKey    = "offered";
let relicsSortDir    = -1; // -1 = descending
let relicsShowAll    = false; // phones: which block of the favorites shows

// You / All players: phones have room for one block of the favorites.
["you", "all"].forEach(w => {
  document.getElementById(`relics-who-${w}`).addEventListener("click", () => {
    relicsShowAll = w === "all";
    document.querySelector(".relics-fav-table")?.classList.toggle("show-all", relicsShowAll);
    ["you", "all"].forEach(x =>
      document.getElementById(`relics-who-${x}`).classList.toggle("active", (x === "all") === relicsShowAll));
  });
});

document.getElementById("relics-name-filter").addEventListener("input", (e) => {
  relicsNameFilter = e.target.value.trim().toLowerCase();
  renderRelicsTable();
});

// One row per character in view, and the three picks as columns: yours as one
// block, all players' as another beside it, as in the offer table below. A
// relic is one slot, so where the Cards page needs a switch between the three,
// here they all fit. Phones show one block at a time (#relics-who).
function relicFavoritesHtml(you, all) {
  const chars = (sharedActiveChar === "ALL" ? DATA.characters : [sharedActiveChar])
    .filter(c => you.runs[c] || (all && all.runs[c]));
  const cell = (picks, metric, cls) => {
    const it = picks && picks[metric];
    if (!it) return `<td class="fav-cell fav-empty${cls}">—</td>`;
    const [rate, detail] = favMetricFigures(metric, it);
    return `<td class="fav-cell${cls}">${favItemHtml("relics", it, rate, detail)}</td>`;
  };
  const block = (picks, who) => FAV_METRICS.map((m, i) =>
    cell(picks, m.key, ` fav-${who}${who === "all" && i === 0 ? " fav-all-start" : ""}`)).join("");
  const rows = chars.map(char => {
    const n = you.runs[char] || 0;
    const mine = favPicksFor(you, RELIC_SLOT, [char]);
    const theirs = all && favPicksFor(all, RELIC_SLOT, [char]);
    return `<tr><th scope="row">${charLabelHtml(char)}<span class="fav-runs">${n} run${n !== 1 ? "s" : ""}</span></th>${block(mine, "you")}${all ? block(theirs, "all") : ""}</tr>`;
  }).join("");
  const heads = who => FAV_METRICS.map((m, i) =>
    `<th class="fav-${who}${who === "all" && i === 0 ? " fav-all-start" : ""}">${m.label}</th>`).join("");
  const groups = all ? `<tr class="fav-groups"><th></th>
    <th class="fav-group-you" colspan="${FAV_METRICS.length}">Your runs</th>
    <th class="fav-group-all fav-all-start" colspan="${FAV_METRICS.length}">All players</th></tr>` : "";
  return `<div class="pivot-wrap fav-bychar-wrap"><table class="pivot fav-table fav-bychar-table fav-blocks-table relics-fav-table${relicsShowAll && all ? " show-all" : ""}">
    <thead>${groups}<tr><th></th>${heads("you")}${all ? heads("all") : ""}</tr></thead>
    <tbody>${rows}</tbody>
  </table></div>`;
}

// { id: {offered, picked, wonWhenPicked, skipped, wonWhenSkipped} } over the
// player's filtered runs, as aggregateCards() does for cards.
function aggregateRelics() {
  const byRelic = {};
  filterRuns().forEach(run => {
    Object.entries(run.relicsOffered || {}).forEach(([id, locs]) => {
      const b = byRelic[id] || (byRelic[id] = { offered: 0, picked: 0, wonWhenPicked: 0, skipped: 0, wonWhenSkipped: 0, granted: 0 });
      locs.forEach(loc => {
        if (loc.picked) { b.picked++; if (run.won) b.wonWhenPicked++; }
        if (loc.granted) { b.granted++; return; }   // handed over: no offer, no skip
        b.offered++;
        if (!loc.picked) { b.skipped++; if (run.won) b.wonWhenSkipped++; }
      });
    });
  });
  return byRelic;
}

// Everybody's tally of each relic under the same filters (see
// globalCardTallies()): { id: [picks, wins, buys, buyWins, offers, skipWins, handedOver] },
// or null when the site totals have none for them.
function globalRelicTallies() {
  const all = favTalliesAll();
  if (!all || siteStatsForFavs.pickSlots !== 6) return null;
  const byId = {};
  const chars = sharedActiveChar === "ALL" ? Object.keys(all.picks) : [sharedActiveChar];
  chars.forEach(char => Object.entries(all.picks[char]?.relics || {}).forEach(([id, q]) => {
    const b = byId[id] || (byId[id] = [0, 0, 0, 0, 0, 0, 0]);
    q.forEach((n, i) => { b[i] += n; });
  }));
  return byId;
}

const RELIC_RARITY_COLOR = { Common: "#ccc", Uncommon: "#aad4ff", Rare: "#ffd700", Shop: "#9fe0a8", Ancient: "#e0a8ff" };

function renderRelicsTable() {
  const raw = aggregateRelics();
  const global = globalRelicTallies();
  const relicData = DATA.relicData || {};
  const rows = Object.entries(raw).map(([id, b]) => {
    const g = global && global[id];
    const rarity = relicData[id]?.rarity || "—";
    // A run record lists an ancient's whole offer (ancient_choice), so every
    // relic has an offer count, ancient ones included.
    const hasOffers = true;
    return {
      id,
      title:      fmtRelicLabel(id),
      rarity,
      offered:    hasOffers ? b.offered : null,
      picked:     b.picked,
      pickRate:   b.offered ? winPctNum(b.picked - b.granted, b.offered) : null,
      winPicked:  winPctNum(b.wonWhenPicked, b.picked),
      winSkipped: b.offered ? winPctNum(b.wonWhenSkipped, b.skipped) : null,
      gOffered:    g && hasOffers ? g[4] : null,
      gPicked:     g ? g[0] : null,
      gPickRate:   g && g[4] ? winPctNum(g[0] - g[6], g[4]) : null,
      gWinPicked:  g ? winPctNum(g[1], g[0]) : null,
      gWinSkipped: g && g[4] ? winPctNum(g[5], g[4] - (g[0] - g[6])) : null,
    };
  }).filter(r => !relicsNameFilter || r.title.toLowerCase().includes(relicsNameFilter));

  const STRING_COLS = new Set(["title", "rarity"]);
  rows.sort((a, b) => {
    const av = a[relicsSortKey], bv = b[relicsSortKey];
    const cmp = STRING_COLS.has(relicsSortKey)
      ? String(av ?? "").localeCompare(String(bv ?? ""))
      : (av ?? -Infinity) - (bv ?? -Infinity);
    return relicsSortDir * (cmp || a.title.localeCompare(b.title));
  });

  const scope = sharedActiveChar === "ALL" ? "all characters" : fmtCharName(sharedActiveChar);
  document.getElementById("relics-caption").textContent =
    `${rows.length} relic${rows.length !== 1 ? "s" : ""} recorded under the current filters (${scope}).`;

  const cols = [
    { key: "title",      label: "Relic",         align: "left" },
    { key: "rarity",     label: "Rarity",        align: "left" },
    { key: "offered",    label: "Offered",       align: "center" },
    { key: "picked",     label: "Picked",        align: "center" },
    { key: "pickRate",   label: "Pick rate",     align: "center" },
    { key: "winPicked",  label: "Win % picked",  align: "center" },
    { key: "winSkipped", label: "Win % skipped", align: "center" },
    ...(global ? [
      { key: "gOffered",    label: "Offered",       align: "center", all: true, groupStart: true },
      { key: "gPicked",     label: "Picked",        align: "center", all: true },
      { key: "gPickRate",   label: "Pick rate",     align: "center", all: true },
      { key: "gWinPicked",  label: "Win % picked",  align: "center", all: true },
      { key: "gWinSkipped", label: "Win % skipped", align: "center", all: true },
    ] : []),
  ];
  const groupRow = global ? `<tr class="cards-groups">
    <th class="cards-group-you" colspan="7">Your runs</th>
    <th class="cards-group-all" colspan="5">All players</th>
  </tr>` : "";
  const thead = document.getElementById("relics-thead");
  thead.innerHTML = groupRow + `<tr>${cols.map(c => {
    const cls = [c.all && "cards-all-col", c.groupStart && "cards-all-start"].filter(Boolean).join(" ");
    const color = relicsSortKey === c.key ? COLORS.gold : "var(--text-dim)";
    return `<th${cls ? ` class="${cls}"` : ""} data-sort="${c.key}" tabindex="0" style="text-align:${c.align};color:${color}">${c.label}${relicsSortKey === c.key ? (relicsSortDir < 0 ? " ▾" : " ▴") : ""}</th>`;
  }).join("")}</tr>`;
  thead.querySelectorAll("th[data-sort]").forEach(th => {
    th.addEventListener("click", () => {
      const k = th.dataset.sort;
      if (relicsSortKey === k) relicsSortDir *= -1;
      else { relicsSortKey = k; relicsSortDir = -1; }
      renderRelicsTable();
    });
    bindEnterSpace(th);
  });

  const pct = (v, color, none = "—") => v == null
    ? `<span style="color:var(--text-dim)">${none}</span>`
    : `<span style="color:${color};font-weight:${v >= 50 ? "800" : "400"}"${v >= 50 ? ` class="cards-hi"` : ""}>${v}%</span>`;
  const tbody = document.getElementById("relics-tbody");
  tbody.innerHTML = rows.map(r => {
    const src = relicImgSrc(r.id);
    const pic = src ? `<img loading="lazy" src="${thumbSrc(src)}" alt="" class="fav-pic">` : "";
    return `<tr>
      <td><span class="fav-item relics-name" data-relic-id="${r.id}" tabindex="0">${pic}${r.title}</span></td>
      <td style="color:${RELIC_RARITY_COLOR[r.rarity] || "var(--text-dim)"}">${r.rarity}</td>
      <td class="relics-num" style="color:var(--text-dim)">${r.offered ?? "—"}</td>
      <td class="relics-num" style="color:var(--text-dim)">${r.picked}</td>
      <td class="relics-num">${pct(r.pickRate, "#ccc")}</td>
      <td class="relics-num">${pct(r.winPicked, "#ccc")}</td>
      <td class="relics-num">${pct(r.winSkipped, "#ccc", r.offered ? "never" : "—")}</td>${global ? `
      <td class="relics-num cards-all cards-all-start" style="color:var(--text-dim)">${r.gOffered ?? "—"}</td>
      <td class="relics-num cards-all" style="color:var(--text-dim)">${r.gPicked ?? "—"}</td>
      <td class="relics-num cards-all">${pct(r.gPickRate, "#aaa")}</td>
      <td class="relics-num cards-all">${pct(r.gWinPicked, "#aaa")}</td>
      <td class="relics-num cards-all">${pct(r.gWinSkipped, "#aaa", r.gOffered ? "never" : "—")}</td>` : ""}
    </tr>`;
  }).join("");
  bindRelicTips(tbody, "[data-relic-id]", el => el.dataset.relicId);
}

// The relic opens on hover, tap or focus as a floating tooltip, as on the
// Cards page (a popup inside the scrolling table would be clipped).
function bindRelicTips(root, selector, idOf) {
  root.querySelectorAll(selector).forEach(el => {
    const show = () => showFloatingHtmlTooltip(el, buildRelicTooltip(idOf(el)));
    el.addEventListener("mouseenter", show);
    el.addEventListener("mouseleave", hideFloatingHtmlTooltip);
    el.addEventListener("focus", show);
    el.addEventListener("blur", hideFloatingHtmlTooltip);
  });
}

function renderRelicsPage() {
  loadSiteStatsForFavs();
  const all = favTalliesAll();
  const box = document.getElementById("relics-favorites");
  box.innerHTML = relicFavoritesHtml(favTalliesYou(), all);
  bindRelicTips(box, ".fav-item[data-fav-id]", el => el.dataset.favId);
  // The switch only exists when there is something to switch to.
  document.getElementById("relics-who").hidden = !all;
  document.getElementById("relics-fav-caption").textContent =
    `Each character's most-picked, best win rate and most-bought relic${all ? ", yours beside all players'" : ""}. Every relic shows its win rate, with the count behind it underneath.`;
  renderRelicsTable();
}
