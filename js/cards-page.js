// =========================================================================
// Cards page
// =========================================================================

let cardsIncludeColorless   = true;
let cardsIncludeOtherChars = false;
let cardsActiveType   = "all";
let cardsActiveRarity = "all";
let cardsNameFilter   = "";
let cardsSortKey      = "offered";
let cardsSortDir      = -1; // -1 = descending

(function initCardsFilters() {
  // Colorless checkbox (always relevant, regardless of character selection)
  document.getElementById("cards-include-colorless").addEventListener("change", (e) => {
    cardsIncludeColorless = e.target.checked;
    renderCardsPage();
  });

  // Card name filter
  document.getElementById("cards-name-filter").addEventListener("input", (e) => {
    cardsNameFilter = e.target.value.trim().toLowerCase();
    renderCardsPage();
  });

  // "Include other characters' cards" checkbox (only relevant when one character is selected)
  document.getElementById("cards-include-other-chars").addEventListener("change", (e) => {
    cardsIncludeOtherChars = e.target.checked;
    renderCardsPage();
  });

  // You / All players: phones have room for four of the eight figure columns,
  // so this swaps which four the table shows (the CSS does the rest).
  ["you","all"].forEach(w => {
    document.getElementById(`cards-who-${w}`).addEventListener("click", () => {
      document.getElementById("cards-table-main").classList.toggle("show-all", w === "all");
      ["you","all"].forEach(x =>
        document.getElementById(`cards-who-${x}`).classList.toggle("active", x === w));
    });
  });

  // Type buttons
  ["all","attack","skill","power"].forEach(t => {
    document.getElementById(`cards-type-${t}`).addEventListener("click", () => {
      cardsActiveType = t;
      ["all","attack","skill","power"].forEach(x =>
        document.getElementById(`cards-type-${x}`).classList.toggle("active", x === t));
      renderCardsPage();
    });
  });

  // Rarity buttons
  ["all","common","uncommon","rare"].forEach(r => {
    document.getElementById(`cards-rarity-${r}`).addEventListener("click", () => {
      cardsActiveRarity = r;
      ["all","common","uncommon","rare"].forEach(x =>
        document.getElementById(`cards-rarity-${x}`).classList.toggle("active", x === r));
      renderCardsPage();
    });
  });
})();

const RARITY_COLOR = { Common: "#ccc", Uncommon: "#aad4ff", Rare: "#ffd700" };
const TYPE_COLOR   = { Attack: "#e05c5c", Skill: "#5b9bd5", Power: "#c49fe8" };

function aggregateCards() {
  const byCard = {};
  filterRuns().forEach(run => {
    Object.entries(run.cardsOffered || {}).forEach(([id, locs]) => {
      if (!byCard[id]) byCard[id] = { offered: 0, picked: 0, wonWhenPicked: 0, wonWhenSkipped: 0, skippedRuns: 0 };
      const b = byCard[id];
      // Each entry in locs is one time the card appeared in a reward screen in this run.
      // A card can appear multiple times in a run (e.g. offered twice). Count each appearance.
      locs.forEach(loc => {
        b.offered++;
        if (loc.picked) {
          b.picked++;
          if (run.won) b.wonWhenPicked++;
        } else {
          b.skippedRuns++;  // incremented per skip appearance, not per run — use carefully
          if (run.won) b.wonWhenSkipped++;
        }
      });
    });
  });
  return byCard;
}

// Everybody's tally of each card under the same filters as the player's own:
// { id: [picks, wins, buys, buyWins, offers, skipWins] }, or null while the site
// totals load, when the filters have none (Daily, Blitz, Custom), or when they
// were counted before offers were kept.
function globalCardTallies() {
  const all = favTalliesAll();
  if (!all || siteStatsForFavs.pickSlots !== 6) return null;
  const byId = {};
  const chars = sharedActiveChar === "ALL" ? Object.keys(all.picks) : [sharedActiveChar];
  chars.forEach(char => Object.entries(all.picks[char]?.cards || {}).forEach(([id, q]) => {
    const b = byId[id] || (byId[id] = [0, 0, 0, 0, 0, 0]);
    q.forEach((n, i) => { b[i] += n; });
  }));
  return byId;
}

function renderCardsPage() {
  renderCardFavorites();
  const raw  = aggregateCards();
  const global = globalCardTallies();
  // The You / All players switch only exists when there is something to switch to.
  document.getElementById("cards-who").hidden = !global;
  if (!global) {
    document.getElementById("cards-table-main").classList.remove("show-all");
    document.getElementById("cards-who-you").classList.add("active");
    document.getElementById("cards-who-all").classList.remove("active");
  }
  const cardData = DATA.cardData || {};
  const cardChar = DATA.cardChar || {};

  // The "include other characters' cards" checkbox only makes sense when one
  // character is selected (it reveals the rare case of a card from a
  // different character's pool showing up in that character's offers).
  const otherCharGroup = document.getElementById("cards-other-char-group");
  otherCharGroup.style.display = sharedActiveChar === "ALL" ? "none" : "";

  // Build rows, filtering by type/rarity
  const rows = Object.entries(raw).map(([id, b]) => {
    const meta = cardData[id] || {};
    const pool = cardChar[id] || "other";
    const g = global && global[id];
    const gSkips = g ? g[4] - g[0] : 0;
    return {
      gOffered:    g ? g[4] : null,
      gPickRate:   g && g[4]  ? +(g[0] / g[4] * 100).toFixed(1) : null,
      gWinPicked:  g && g[0]  ? +(g[1] / g[0] * 100).toFixed(1) : null,
      gWinSkipped: g && gSkips ? +(g[5] / gSkips * 100).toFixed(1) : null,
      id,
      title:    DATA.cardLabels[id] || id,
      type:     meta.type    || "—",
      rarity:   meta.rarity  || "—",
      pool,
      owner:    pool === "colorless" ? "Colorless" : fmtCharName(pool),
      offered:  b.offered,
      picked:   b.picked,
      pickRate: b.offered ? +(b.picked / b.offered * 100).toFixed(1) : 0,
      skipped:  b.skippedRuns,
      winPicked:  b.picked       ? +(b.wonWhenPicked  / b.picked       * 100).toFixed(1) : null,
      winSkipped: b.skippedRuns  ? +(b.wonWhenSkipped / b.skippedRuns  * 100).toFixed(1) : null,
    };
  }).filter(r => {
    // The game hides a couple of cards from its own library because they have no
    // canonical form before something else rolls them: Mad Science is type None
    // with a ?????? description until the Tinker Time event assigns its type and
    // rider, and DeprecatedCard is an internal placeholder. Both can still show up
    // in a deck, so their metadata stays -- only this reference table skips them.
    if (cardData[r.id]?.showInCardLibrary === false) return false;
    if (r.pool === "colorless" && !cardsIncludeColorless) return false;
    if (sharedActiveChar !== "ALL" && !cardsIncludeOtherChars) {
      if (r.pool !== sharedActiveChar && r.pool !== "colorless") return false;
    }
    if (cardsActiveType   !== "all" && r.type.toLowerCase()   !== cardsActiveType)   return false;
    if (cardsActiveRarity !== "all" && r.rarity.toLowerCase() !== cardsActiveRarity) return false;
    if (cardsNameFilter && !r.title.toLowerCase().includes(cardsNameFilter)) return false;
    return true;
  });

  // Sort
  const STRING_COLS = new Set(["title", "owner", "type", "rarity"]);
  rows.sort((a, b) => {
    const av = a[cardsSortKey], bv = b[cardsSortKey];
    let cmp;
    if (STRING_COLS.has(cardsSortKey)) {
      cmp = String(av ?? "").localeCompare(String(bv ?? ""));
    } else {
      cmp = (av ?? -Infinity) - (bv ?? -Infinity);
    }
    return cardsSortDir * (cmp || a.title.localeCompare(b.title));
  });

  // Visible caption rather than a heading tooltip, which phones never show.
  const scopeLabel = sharedActiveChar === "ALL"
    ? "all characters"
    : fmtCharName(sharedActiveChar);
  const cardsCaption = document.getElementById("cards-caption");
  if (cardsCaption) cardsCaption.textContent =
    `${rows.length} card${rows.length !== 1 ? "s" : ""} offered under the current filters (${scopeLabel}).`;

  // Header
  const cols = [
    { key: "title",      label: "Card",            align: "left",   width: "240px" },
    { key: "owner",      label: "Pool",            align: "left",   width: "120px" },
    { key: "type",       label: "Type",            align: "left",   width: "80px"  },
    { key: "rarity",     label: "Rarity",          align: "left",   width: "110px"  },
    { key: "offered",    label: "Offered",         align: "center", width: "90px"  },
    { key: "pickRate",   label: "Pick rate",       align: "center", width: "100px"  },
    { key: "winPicked",  label: "Win % if picked", align: "center", width: "130px" },
    { key: "winSkipped", label: "Win % if skipped",align: "center", width: "140px" },
    // Everybody's, when the site totals have them: the same four, to compare against.
    ...(global ? [
      { key: "gOffered",    label: "All offered",      align: "center", width: "90px"  },
      { key: "gPickRate",   label: "All pick rate",    align: "center", width: "90px"  },
      { key: "gWinPicked",  label: "All win % picked", align: "center", width: "120px" },
      { key: "gWinSkipped", label: "All win % skipped",align: "center", width: "130px" },
    ] : []),
  ];

  const thStyle = (col) => `style="text-align:${col.align};cursor:pointer;user-select:none;white-space:nowrap;padding:0.3rem 0.5rem;font-size:var(--fs-sm);width:${col.width};color:${cardsSortKey === col.key ? "#e0c468" : "var(--text-dim)"}"`;
  document.getElementById("cards-thead").innerHTML = `<tr>
    ${cols.map(c => `<th ${thStyle(c)} data-sort="${c.key}" tabindex="0">${c.label}${cardsSortKey === c.key ? (cardsSortDir < 0 ? " ▾" : " ▴") : ""}</th>`).join("")}
  </tr>`;

  // Attach sort listeners
  document.getElementById("cards-thead").querySelectorAll("th[data-sort]").forEach(th => {
    th.addEventListener("click", () => {
      const k = th.dataset.sort;
      if (cardsSortKey === k) cardsSortDir *= -1;
      else { cardsSortKey = k; cardsSortDir = -1; }
      renderCardsPage();
    });
    bindEnterSpace(th);
  });

  // Body. Win rates carry no low-sample marking: a thin rate is an outlier that
  // resolves itself as more runs are uploaded, and flagging it made this page
  // disagree with the rest of the app about what a sample size was worth
  // warning about.
  const pct = (v, color) => {
    if (v == null) return `<span style="color:var(--text-dim)">—</span>`;
    return `<span style="color:${color};font-weight:${v >= 50 ? "800" : "400"};"${v >= 50 ? ` class="cards-hi"` : ""}>${v}%</span>`;
  };

  document.getElementById("cards-tbody").innerHTML = rows.map(r => {
    // Same real-card thumbnail + hover tooltip as every other card reference
    // in the app (Personal Bests, deck tiles, node rewards) -- a bare name
    // was the odd one out here. The tooltip itself is wired up below via
    // showFloatingHtmlTooltip rather than the usual .card-tooltip-wrap
    // markup, since this table lives inside a scrolling .pivot-wrap
    // (overflow-y:auto) that would clip an absolutely-positioned popup.
    const src = cardImgSrc(r.id);
    // The thumbnail and the name are one trigger, so hovering, tapping or
    // tabbing to either opens the card.
    const icon = src
      ? `<span class="cards-thumb-wrap">
          <img loading="lazy" src="${thumbSrc(src)}" alt="" class="cards-thumb">
        </span>`
      : "";
    return `<tr>
    <td style="padding:0.3rem 0.5rem;font-size:var(--fs-md);overflow:hidden;text-overflow:ellipsis;white-space:nowrap"><span class="fav-item" data-card-id="${r.id}" tabindex="0" style="cursor:pointer">${icon}${r.title}</span></td>
    <td style="padding:0.3rem 0.5rem;font-size:var(--fs-sm);color:${CHAR_COLOR_MAP[r.owner.toUpperCase()] || "var(--text-dim)"}">${charIconHtml(r.pool)}${r.owner}</td>
    <td style="padding:0.3rem 0.5rem;font-size:var(--fs-sm);color:${TYPE_COLOR[r.type] || "var(--text-dim)"}">${r.type}</td>
    <td style="padding:0.3rem 0.5rem;font-size:var(--fs-sm);color:${RARITY_COLOR[r.rarity] || "var(--text-dim)"}">${r.rarity}</td>
    <td style="padding:0.3rem 0.5rem;text-align:center;font-size:var(--fs-md);color:var(--text-dim)">${r.offered}</td>
    <td style="padding:0.3rem 0.5rem;text-align:center;font-size:var(--fs-md)">${pct(r.pickRate, "#ccc")}</td>
    <td style="padding:0.3rem 0.5rem;text-align:center;font-size:var(--fs-md)">${pct(r.winPicked,  "#ccc")}</td>
    <td style="padding:0.3rem 0.5rem;text-align:center;font-size:var(--fs-md)">${pct(r.winSkipped, "#ccc")}</td>${global ? `
    <td class="cards-all" style="padding:0.3rem 0.5rem;text-align:center;font-size:var(--fs-md);color:var(--text-dim)">${r.gOffered ?? "—"}</td>
    <td class="cards-all" style="padding:0.3rem 0.5rem;text-align:center;font-size:var(--fs-md)">${pct(r.gPickRate, "#aaa")}</td>
    <td class="cards-all" style="padding:0.3rem 0.5rem;text-align:center;font-size:var(--fs-md)">${pct(r.gWinPicked, "#aaa")}</td>
    <td class="cards-all" style="padding:0.3rem 0.5rem;text-align:center;font-size:var(--fs-md)">${pct(r.gWinSkipped, "#aaa")}</td>` : ""}
  </tr>`;
  }).join("");

  document.getElementById("cards-tbody").querySelectorAll(".fav-item[data-card-id]").forEach(el => {
    // Wide screens show the card in the pane beside the table instead.
    const show = () => {
      if (!previewCard(el.closest("tr"))) showFloatingHtmlTooltip(el, buildCardTooltip(el.dataset.cardId, 0));
    };
    el.addEventListener("mouseenter", show);
    el.addEventListener("mouseleave", hideFloatingHtmlTooltip);
    // Tap or keyboard: focus shows it; the next tap anywhere blurs it (tooltip.js).
    el.addEventListener("focus", show);
    el.addEventListener("blur", hideFloatingHtmlTooltip);
  });

  // The pane follows the pointer over the whole row, and starts on the top card.
  const tbody = document.getElementById("cards-tbody");
  tbody.querySelectorAll("tr").forEach(tr => tr.addEventListener("mouseenter", () => previewCard(tr)));
  document.getElementById("cards-preview").innerHTML = "";
  previewCard(tbody.querySelector("tr"));
}

// The full card beside the table, on screens wide enough to have the room
// (the same width as .cards-preview in dashboard.css). Returns false when the
// pane is not showing, so the caller falls back to the floating tooltip.
const CARDS_PREVIEW_MQ = "(min-width: 1420px)";
function previewCard(tr) {
  if (!tr || !window.matchMedia(CARDS_PREVIEW_MQ).matches) return false;
  const id = tr.querySelector(".fav-item[data-card-id]").dataset.cardId;
  document.querySelectorAll("#cards-tbody tr.cards-current").forEach(row => row.classList.remove("cards-current"));
  tr.classList.add("cards-current");
  document.getElementById("cards-preview").innerHTML =
    (cardFaceAvailable() && renderCardFace(id, 0, "100%")) || buildCardTooltip(id, 0);
  return true;
}

// =========================================================================
// Favourites: the player's most picked, best win % and most bought card of
// each rarity and relic, beside the same for all players.
// =========================================================================

// Site-wide totals (/users/_stats.json.gz, the ingest Lambda's picks[char]
// [kind][id] = [picks, wins, buys, wins when bought]), fetched once. null
// until asked for; false while loading or when there are none (a page built
// from files has no site).
let siteStatsForFavs = null;
function loadSiteStatsForFavs() {
  if (siteStatsForFavs !== null) return;
  siteStatsForFavs = false;
  fetch("/users/_stats.json.gz", { cache: "no-cache" })
    .then(r => r.ok ? r.json() : null)
    .then(stats => {
      if (!stats) return;
      siteStatsForFavs = stats;
      if (currentPage === "cards") renderCardsPage(); else renderCardFavorites();
    })
    .catch(() => {});
}

const FAV_SLOTS = [
  { label: "Common",   kind: "cards",  test: id => (DATA.cardData[id] || {}).rarity === "Common" },
  { label: "Uncommon", kind: "cards",  test: id => (DATA.cardData[id] || {}).rarity === "Uncommon" },
  { label: "Rare",     kind: "cards",  test: id => (DATA.cardData[id] || {}).rarity === "Rare" },
  { label: "Relic",    kind: "relics", test: id => id in (DATA.relicData || {}) },
];
// A win rate needs the item picked in at least this share of the runs, so a
// card taken twice and won twice doesn't top the list.
const FAV_MIN_SHARE = 0.10;

// A card bought counts only from the character's own pool or colorless: a
// card from another pool in the shop is an oddity, not a choice.
const favBuyCounts = (id, char) => {
  const pool = (DATA.cardChar || {})[id] || "";
  return pool === char || pool === "colorless";
};

// { picks: { char: { cards: {id: [picks, wins, buys, buyWins]}, relics } },
//   runs: { char: n } } from the player's filtered runs.
function favTalliesYou() {
  const picks = {}, runs = {};
  filterRuns().forEach(run => {
    runs[run.char] = (runs[run.char] || 0) + 1;
    const byKind = picks[run.char] || (picks[run.char] = { cards: {}, relics: {} });
    [["cards", run.cardsOffered], ["relics", run.relicsOffered]].forEach(([kind, offered]) => {
      Object.entries(offered || {}).forEach(([id, locs]) => locs.forEach(loc => {
        if (!loc.picked) return;
        const q = byKind[kind][id] || (byKind[kind][id] = [0, 0, 0, 0]);
        q[0]++; q[1] += run.won ? 1 : 0;
        if (loc.type === "shop") { q[2]++; q[3] += run.won ? 1 : 0; }
      }));
    });
  });
  return { picks, runs };
}

// The same from the site-wide totals, for the Mode filter's runs (all = solo
// plus multiplayer; there are no daily-only totals).
function favTalliesAll() {
  if (!siteStatsForFavs) return null;
  const modes = sharedActiveMode === "solo" ? ["solo"] : sharedActiveMode === "multi" ? ["multi"]
    : sharedActiveMode === "daily" ? [] : ["solo", "multi"];
  if (!modes.length) return null;
  const picks = {}, runs = {};
  modes.forEach(mode => {
    const m = siteStatsForFavs[mode] || {};
    Object.entries(m.chars || {}).forEach(([char, pair]) => { runs[char] = (runs[char] || 0) + pair[0]; });
    Object.entries(m.picks || {}).forEach(([char, kinds]) => {
      const into = picks[char] || (picks[char] = { cards: {}, relics: {} });
      ["cards", "relics"].forEach(kind => Object.entries(kinds[kind] || {}).forEach(([id, q]) => {
        const have = into[kind][id] || (into[kind][id] = [0, 0, 0, 0, 0, 0]);
        q.forEach((n, i) => { have[i] += n; });
      }));
    });
  });
  return { picks, runs };
}

// The three picks for one slot, over the characters in view. Each item's
// win rate bar is a share of the runs of the characters that took it, so
// with every character in view a character's own card is held to that
// character's runs, not everybody's.
function favPicksFor(tallies, slot, chars) {
  const byId = {};
  chars.forEach(char => {
    const runs = tallies.runs[char] || 0;
    Object.entries(((tallies.picks[char] || {})[slot.kind]) || {}).forEach(([id, q]) => {
      if (!slot.test(id)) return;
      const b = byId[id] || (byId[id] = [0, 0, 0, 0, 0]);
      b[0] += q[0]; b[1] += q[1]; b[4] += runs;
      if (slot.kind === "relics" || favBuyCounts(id, char)) { b[2] += q[2]; b[3] += q[3]; }
    });
  });
  const items = Object.entries(byId).map(([id, q]) => ({ id, picks: q[0], wins: q[1], buys: q[2], buyWins: q[3], runs: q[4] }));
  const top = (list, key) => list.reduce((best, it) => !best || it[key] > best[key] ? it : best, null);
  const rated = items.filter(it => it.picks >= Math.max(1, Math.ceil(it.runs * FAV_MIN_SHARE))).map(it => ({ ...it, winPct: it.wins / it.picks * 100 }));
  return {
    picked: top(items, "picks"),
    win: top(rated, "winPct"),
    bought: top(items.filter(it => it.buys), "buys"),
  };
}

// One item: picture, name, and the figure it was chosen for. The card or
// relic opens on hover or tap as a floating tooltip (bound in
// renderCardFavorites), like the card table below: one hidden inside the cell
// would still widen a phone's page.
function favCellHtml(kind, item, figure, tip) {
  if (!item) return `<td class="fav-cell fav-empty">—</td>`;
  const isCard = kind === "cards";
  const label = isCard ? fmtCardLabel(item.id) : fmtRelicLabel(item.id);
  const src = isCard ? cardImgSrc(item.id) : relicImgSrc(item.id);
  const pic = isCard && cardFaceAvailable()
    ? `<span class="fav-item-face">${renderCardFace(item.id, 0, 26, { thumb: true })}</span>`
    : src ? `<img loading="lazy" src="${thumbSrc(src)}" alt="" class="fav-pic">` : "";
  return `<td class="fav-cell"><span class="fav-item" tabindex="0" data-fav-kind="${kind}" data-fav-id="${item.id}" aria-label="${label}, ${tip}">
    <span class="fav-icon">${pic}</span><span class="fav-name">${label}</span>
    <span class="fav-num" data-tip="${tip}">${figure}</span>
  </span></td>`;
}

function favPanelHtml(title, tallies, chars) {
  const pct = n => `${Math.round(n)}%`;
  const rows = FAV_SLOTS.map(slot => {
    const f = favPicksFor(tallies, slot, chars);
    const p = f.picked, w = f.win, b = f.bought;
    return `<tr><th>${slot.label}</th>
      ${favCellHtml(slot.kind, p, p && p.picks, p && `${p.picks} picks · ${pct(p.wins / p.picks * 100)} won`)}
      ${favCellHtml(slot.kind, w, w && pct(w.winPct), w && `${w.wins} of ${w.picks} picks won`)}
      ${favCellHtml(slot.kind, b, b && b.buys, b && `${b.buys} bought · ${pct(b.buyWins / b.buys * 100)} won`)}
    </tr>`;
  }).join("");
  return `<div class="fav-panel">
    <h3>${title}</h3>
    <table class="pivot fav-table">
      <thead><tr><th></th><th>Most picked</th><th>Best win %</th><th>Most bought</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

function renderCardFavorites() {
  loadSiteStatsForFavs();
  const chars = sharedActiveChar === "ALL" ? DATA.characters : [sharedActiveChar];
  const all = favTalliesAll();
  const box = document.getElementById("cards-favorites");
  box.innerHTML = favPanelHtml("You", favTalliesYou(), chars) + (all ? favPanelHtml("All players", all, chars) : "");
  box.querySelectorAll(".fav-item[data-fav-id]").forEach(el => {
    const show = () => showFloatingHtmlTooltip(el, el.dataset.favKind === "cards"
      ? buildCardTooltip(el.dataset.favId, 0) : buildRelicTooltip(el.dataset.favId));
    el.addEventListener("mouseenter", show);
    el.addEventListener("mouseleave", hideFloatingHtmlTooltip);
    el.addEventListener("focus", show);
    el.addEventListener("blur", hideFloatingHtmlTooltip);
  });
}
