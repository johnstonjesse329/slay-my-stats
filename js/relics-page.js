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

document.getElementById("relics-name-filter").addEventListener("input", (e) => {
  relicsNameFilter = e.target.value.trim().toLowerCase();
  renderRelicsTable();
});

// One row per character in view, the three picks as columns: a relic is one
// slot, so where the Cards page needs a switch between them, here they all fit.
function relicFavoritesHtml(you, all) {
  const chars = (sharedActiveChar === "ALL" ? DATA.characters : [sharedActiveChar])
    .filter(c => you.runs[c] || (all && all.runs[c]));
  const one = (picks, metric, cls) => {
    const it = picks && picks[metric];
    if (!it) return `<span class="fav-item fav-none${cls}">—</span>`;
    const [rate, detail] = favMetricFigures(metric, it);
    return favItemHtml("relics", it, rate, detail, cls);
  };
  const rows = chars.map(char => {
    const n = you.runs[char] || 0;
    const mine = favPicksFor(you, RELIC_SLOT, [char]);
    const theirs = all && favPicksFor(all, RELIC_SLOT, [char]);
    const cells = FAV_METRICS.map(m =>
      `<td class="fav-cell">${one(mine, m.key, " fav-mine")}${all ? one(theirs, m.key, " fav-theirs") : ""}</td>`).join("");
    return `<tr><th scope="row">${charLabelHtml(char)}<span class="fav-runs">${n} run${n !== 1 ? "s" : ""}</span></th>${cells}</tr>`;
  }).join("");
  const legend = `<span class="fav-legend"><span class="fav-key fav-key-you">You</span>${all ? `<span class="fav-key fav-key-all">All players</span>` : ""}</span>`;
  return `<div class="fav-bychar">
    <div class="fav-bychar-bar">${legend}</div>
    <div class="pivot-wrap fav-bychar-wrap"><table class="pivot fav-table fav-bychar-table relics-fav-table">
      <thead><tr><th></th>${FAV_METRICS.map(m => `<th>${m.label}</th>`).join("")}</tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
  </div>`;
}

// { id: {offered, picked, wonWhenPicked, skipped, wonWhenSkipped} } over the
// player's filtered runs, as aggregateCards() does for cards.
function aggregateRelics() {
  const byRelic = {};
  filterRuns().forEach(run => {
    Object.entries(run.relicsOffered || {}).forEach(([id, locs]) => {
      const b = byRelic[id] || (byRelic[id] = { offered: 0, picked: 0, wonWhenPicked: 0, skipped: 0, wonWhenSkipped: 0 });
      locs.forEach(loc => {
        b.offered++;
        if (loc.picked) { b.picked++; if (run.won) b.wonWhenPicked++; }
        else            { b.skipped++; if (run.won) b.wonWhenSkipped++; }
      });
    });
  });
  return byRelic;
}

// Everybody's tally of each relic under the same filters (see
// globalCardTallies()): { id: [picks, wins, buys, buyWins, offers, skipWins] },
// or null when the site totals have none for them.
function globalRelicTallies() {
  const all = favTalliesAll();
  if (!all || siteStatsForFavs.pickSlots !== 6) return null;
  const byId = {};
  const chars = sharedActiveChar === "ALL" ? Object.keys(all.picks) : [sharedActiveChar];
  chars.forEach(char => Object.entries(all.picks[char]?.relics || {}).forEach(([id, q]) => {
    const b = byId[id] || (byId[id] = [0, 0, 0, 0, 0, 0]);
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
    return {
      id,
      title:      fmtRelicLabel(id),
      rarity:     (relicData[id] || {}).rarity || "—",
      offered:    b.offered,
      pickRate:   winPctNum(b.picked, b.offered),
      winPicked:  winPctNum(b.wonWhenPicked, b.picked),
      winSkipped: winPctNum(b.wonWhenSkipped, b.skipped),
      gOffered:    g ? g[4] : null,
      gPickRate:   g ? winPctNum(g[0], g[4]) : null,
      gWinPicked:  g ? winPctNum(g[1], g[0]) : null,
      gWinSkipped: g ? winPctNum(g[5], g[4] - g[0]) : null,
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
    `${rows.length} relic${rows.length !== 1 ? "s" : ""} offered under the current filters (${scope}).`;

  const cols = [
    { key: "title",      label: "Relic",         align: "left" },
    { key: "rarity",     label: "Rarity",        align: "left" },
    { key: "offered",    label: "Offered",       align: "center" },
    { key: "pickRate",   label: "Pick rate",     align: "center" },
    { key: "winPicked",  label: "Win % picked",  align: "center" },
    { key: "winSkipped", label: "Win % skipped", align: "center" },
    ...(global ? [
      { key: "gOffered",    label: "Offered",       align: "center", all: true, groupStart: true },
      { key: "gPickRate",   label: "Pick rate",     align: "center", all: true },
      { key: "gWinPicked",  label: "Win % picked",  align: "center", all: true },
      { key: "gWinSkipped", label: "Win % skipped", align: "center", all: true },
    ] : []),
  ];
  const groupRow = global ? `<tr class="cards-groups">
    <th class="cards-group-you" colspan="6">Your runs</th>
    <th class="cards-group-all" colspan="4">All players</th>
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

  const pct = (v, color) => v == null
    ? `<span style="color:var(--text-dim)">—</span>`
    : `<span style="color:${color};font-weight:${v >= 50 ? "800" : "400"}"${v >= 50 ? ` class="cards-hi"` : ""}>${v}%</span>`;
  const tbody = document.getElementById("relics-tbody");
  tbody.innerHTML = rows.map(r => {
    const src = relicImgSrc(r.id);
    const pic = src ? `<img loading="lazy" src="${thumbSrc(src)}" alt="" class="fav-pic">` : "";
    return `<tr>
      <td><span class="fav-item relics-name" data-relic-id="${r.id}" tabindex="0">${pic}${r.title}</span></td>
      <td style="color:${RELIC_RARITY_COLOR[r.rarity] || "var(--text-dim)"}">${r.rarity}</td>
      <td class="relics-num" style="color:var(--text-dim)">${r.offered}</td>
      <td class="relics-num">${pct(r.pickRate, "#ccc")}</td>
      <td class="relics-num">${pct(r.winPicked, "#ccc")}</td>
      <td class="relics-num">${pct(r.winSkipped, "#ccc")}</td>${global ? `
      <td class="relics-num cards-all cards-all-start" style="color:var(--text-dim)">${r.gOffered ?? "—"}</td>
      <td class="relics-num cards-all">${pct(r.gPickRate, "#aaa")}</td>
      <td class="relics-num cards-all">${pct(r.gWinPicked, "#aaa")}</td>
      <td class="relics-num cards-all">${pct(r.gWinSkipped, "#aaa")}</td>` : ""}
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
  document.getElementById("relics-fav-caption").textContent =
    `Each character's most-picked, best win rate and most-bought relic: yours on top${all ? ", all players' underneath" : ""}. Every relic shows its win rate, with the count behind it underneath.`;
  renderRelicsTable();
}
