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
  if (!all || siteStatsForFavs.pickSlots !== 7) return null;
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
      gPickRate:   g ? winPctNum(g[0], g[4]) : null,
      gWinPicked:  g ? winPctNum(g[1], g[0]) : null,
      gWinSkipped: g ? winPctNum(g[5], gSkips) : null,
      id,
      title:    DATA.cardLabels[id] || id,
      type:     meta.type    || "—",
      rarity:   meta.rarity  || "—",
      pool,
      owner:    pool === "colorless" ? "Colorless" : fmtCharName(pool),
      offered:  b.offered,
      picked:   b.picked,
      pickRate: winPctNum(b.picked, b.offered) ?? 0,
      skipped:  b.skippedRuns,
      winPicked:  winPctNum(b.wonWhenPicked, b.picked),
      winSkipped: winPctNum(b.wonWhenSkipped, b.skippedRuns),
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
    { key: "title",      label: "Card",            align: "left",   width: "205px" },
    { key: "owner",      label: "Pool",            align: "left",   width: "95px"  },
    { key: "type",       label: "Type",            align: "left",   width: "72px"  },
    { key: "rarity",     label: "Rarity",          align: "left",   width: "86px"  },
    { key: "offered",    label: "Offered",         align: "center", width: "74px"  },
    { key: "pickRate",   label: "Pick rate",       align: "center", width: "82px"  },
    { key: "winPicked",  label: "Win % picked",    align: "center", width: "108px" },
    { key: "winSkipped", label: "Win % skipped",   align: "center", width: "108px" },
    // Everybody's, when the site totals have them: the same four figures, under
    // their own heading, to compare against.
    ...(global ? [
      { key: "gOffered",    label: "Offered",        align: "center", width: "74px",  all: true, groupStart: true },
      { key: "gPickRate",   label: "Pick rate",      align: "center", width: "82px",  all: true },
      { key: "gWinPicked",  label: "Win % picked",   align: "center", width: "108px", all: true },
      { key: "gWinSkipped", label: "Win % skipped",  align: "center", width: "108px", all: true },
    ] : []),
  ];

  const thStyle = (col) => `style="text-align:${col.align};cursor:pointer;user-select:none;white-space:nowrap;padding:0.45rem 0.6rem;font-size:var(--fs-sm);width:${col.width};color:${cardsSortKey === col.key ? COLORS.gold : "var(--text-dim)"}"`;
  // A fixed-layout table takes its column widths from the first row, which is
  // now the colspan group heading, so pin them in a colgroup. Phones hide the
  // group row and set their own column widths in dashboard.css, so they drop
  // the pin and let those widths apply.
  const table = document.getElementById("cards-table-main");
  let colgroup = table.querySelector("colgroup");
  if (isPhone()) {
    if (colgroup) colgroup.remove();
  } else {
    if (!colgroup) {
      colgroup = document.createElement("colgroup");
      table.insertBefore(colgroup, table.firstChild);
    }
    colgroup.innerHTML = cols.map(c => `<col style="width:${c.width}">`).join("");
  }
  const thClass = (col) => [col.all && "cards-all-col", col.groupStart && "cards-all-start"]
    .filter(Boolean).join(" ");
  // One heading over each block of four: the columns below share their names,
  // so which set is yours is told by the block, not by an "All " prefix that
  // read as part of the figure's name.
  const groupRow = global ? `<tr class="cards-groups">
    <th class="cards-group-you" colspan="8">Your runs</th>
    <th class="cards-group-all" colspan="4">All players</th>
  </tr>` : "";
  document.getElementById("cards-thead").innerHTML = groupRow + `<tr>
    ${cols.map(c => {
      const cls = thClass(c);
      return `<th ${thStyle(c)}${cls ? ` class="${cls}"` : ""} data-sort="${c.key}" tabindex="0">${c.label}${cardsSortKey === c.key ? (cardsSortDir < 0 ? " ▾" : " ▴") : ""}</th>`;
    }).join("")}
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
    // Prefer the baked card face at thumbnail size: the portrait alone was too
    // small to tell two similar cards apart, and the face carries the name,
    // type and cost. A checkout without the bake falls back to the portrait.
    const art = (cardFaceAvailable()
      ? renderCardFace(r.id, 0, "var(--cards-thumb-w)", { thumb: true })
      : "") || (src ? `<img loading="lazy" src="${thumbSrc(src)}" alt="" class="cards-thumb">` : "");
    // The thumbnail and the name are one trigger, so hovering, tapping or
    // tabbing to either opens the card.
    const icon = art ? `<span class="cards-thumb-wrap">${art}</span>` : "";
    return `<tr>
    <td style="padding:0.45rem 0.6rem;font-size:var(--fs-md);overflow:hidden;text-overflow:ellipsis;white-space:nowrap"><span class="fav-item" data-card-id="${r.id}" tabindex="0" style="cursor:pointer">${icon}${r.title}</span></td>
    <td style="padding:0.45rem 0.6rem;font-size:var(--fs-sm);color:var(--text-dim)">${r.pool === "colorless" ? `${charIconHtml(r.pool)}${r.owner}` : charLabelHtml(r.pool)}</td>
    <td style="padding:0.45rem 0.6rem;font-size:var(--fs-sm);color:${TYPE_COLOR[r.type] || "var(--text-dim)"}">${r.type}</td>
    <td style="padding:0.45rem 0.6rem;font-size:var(--fs-sm);color:${RARITY_COLOR[r.rarity] || "var(--text-dim)"}">${r.rarity}${isCoopCard(r.id) ? `<span class="cards-coop-tag">Multi</span>` : ""}</td>
    <td style="padding:0.45rem 0.6rem;text-align:center;font-size:var(--fs-md);color:var(--text-dim)">${r.offered}</td>
    <td style="padding:0.45rem 0.6rem;text-align:center;font-size:var(--fs-md)">${pct(r.pickRate, "#ccc")}</td>
    <td style="padding:0.45rem 0.6rem;text-align:center;font-size:var(--fs-md)">${pct(r.winPicked,  "#ccc")}</td>
    <td style="padding:0.45rem 0.6rem;text-align:center;font-size:var(--fs-md)">${pct(r.winSkipped, "#ccc")}</td>${global ? `
    <td class="cards-all cards-all-start" style="padding:0.45rem 0.6rem;text-align:center;font-size:var(--fs-md);color:var(--text-dim)">${r.gOffered ?? "—"}</td>
    <td class="cards-all" style="padding:0.45rem 0.6rem;text-align:center;font-size:var(--fs-md)">${pct(r.gPickRate, "#aaa")}</td>
    <td class="cards-all" style="padding:0.45rem 0.6rem;text-align:center;font-size:var(--fs-md)">${pct(r.gWinPicked, "#aaa")}</td>
    <td class="cards-all" style="padding:0.45rem 0.6rem;text-align:center;font-size:var(--fs-md)">${pct(r.gWinSkipped, "#aaa")}</td>` : ""}
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
// Phones show four figure columns at widths of their own (dashboard.css), so
// the table's pinned column widths follow the breakpoint.
PHONE_MQ.addEventListener("change", () => {
  if (currentPage === "cards") renderCardsPage();
});
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
      // Cards can already have been rendered once while the totals were still
      // loading (the idle pre-render of the page does exactly that), so keep it
      // dirty when it is not on screen: the next visit then draws the "All"
      // columns instead of the stale table without them.
      ["cards", "relics", "events"].forEach(page => {
        if (currentPage === page) PAGE_RENDERERS[page]();
        else pageDirty[page] = true;
      });
    })
    .catch(() => {});
}

// Cards that only turn up in multiplayer runs (DATA.cardCoop, run.py's
// build_card_coop()). They get a bucket of their own, so a co-op card doesn't
// take a rarity's spot from the cards a solo run can offer.
let favCoopIds = null;
const isCoopCard = id => (favCoopIds || (favCoopIds = new Set(DATA.cardCoop || []))).has(id);
const favRarity = r => id => (DATA.cardData[id] || {}).rarity === r && !isCoopCard(id);
const FAV_SLOTS = [
  { label: "Common",   kind: "cards", test: favRarity("Common") },
  { label: "Uncommon", kind: "cards", test: favRarity("Uncommon") },
  { label: "Rare",     kind: "cards", test: favRarity("Rare") },
  { label: "Multi",    kind: "cards", coop: true, test: isCoopCard },
];
// The Co-op bucket only while multiplayer runs are in view (and the build
// knew which cards those are). Relics have a page of their own (relics-page.js).
function favSlots() {
  return FAV_SLOTS.filter(s => !s.coop || ((DATA.cardCoop || []).length && sharedActivePlayers !== "solo"));
}
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

// The public cohorts track Standard by exact ascension and Dread separately.
// Compare only when the remaining filters match the population counted.
function favTalliesAll() {
  if (!siteStatsForFavs || !sharedActiveModes.size
      || [...sharedActiveModes].some(mode => !["standard", "dread"].includes(mode))
      || sharedActiveBuilds.size !== DATA.builds.length || sharedActiveMods !== "all"
      || sharedTsFrom !== 0 || sharedTsTo !== TS_NO_UPPER_BOUND) return null;
  // With granular view on, the ticked levels are the population even when every
  // box is ticked: the public cohorts include levels this profile has no checkbox
  // for, and "all ticked" must not switch to counting those.
  const allAscs = !sharedAscGranular && sharedActiveAscs.size === DATA.ascensions.length;
  const exact = siteStatsForFavs.ascPickVersion === 1;
  if (!exact && (!allAscs || sharedActiveModes.size !== 2)) return null;
  const parties = sharedActivePlayers === "all" ? ["solo", "multi"] : [sharedActivePlayers];
  const picks = {}, runs = {};
  parties.flatMap(party => {
    const mode = siteStatsForFavs[party] || {};
    if (!exact) return [mode];
    const cohorts = Object.entries(mode.ascPicks || {});
    return cohorts.filter(([key]) => key === "dread"
      ? sharedActiveModes.has("dread") && (allAscs || sharedActiveAscs.has(DREAD_ASC))
      : sharedActiveModes.has("standard") && (allAscs || sharedActiveAscs.has(Number(key))))
      .map(([, cohort]) => cohort);
  }).forEach(m => {
    Object.entries(m.chars || {}).forEach(([char, pair]) => { runs[char] = (runs[char] || 0) + pair[0]; });
    Object.entries(m.picks || {}).forEach(([char, kinds]) => {
      const into = picks[char] || (picks[char] = { cards: {}, relics: {}, events: {} });
      ["cards", "relics"].forEach(kind => Object.entries(kinds[kind] || {}).forEach(([id, q]) => {
        const have = into[kind][id] || (into[kind][id] = [0, 0, 0, 0, 0, 0]);
        q.forEach((n, i) => { have[i] += n; });
      }));
      // Event choices are objects, not slot lists (see events-page.js).
      Object.entries(kinds.events || {}).forEach(([id, ev]) => {
        const have = into.events[id] || (into.events[id] = { v: 0, o: {} });
        have.v += ev.v;
        Object.entries(ev.o).forEach(([opt, [n, w, grants]]) => {
          const o = have.o[opt] || (have.o[opt] = [0, 0, {}]);
          o[0] += n; o[1] += w;
          Object.entries(grants).forEach(([g, c]) => { o[2][g] = (o[2][g] || 0) + c; });
        });
      });
    });
  });
  return Object.keys(runs).length ? { picks, runs } : null;
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
  // The site totals also count offers, so an item offered but never taken is
  // in there with no picks: it can't be anyone's favorite.
  const items = Object.entries(byId).map(([id, q]) => ({ id, picks: q[0], wins: q[1], buys: q[2], buyWins: q[3], runs: q[4] }))
    .filter(it => it.picks > 0);
  const top = (list, key) => list.reduce((best, it) => !best || it[key] > best[key] ? it : best, null);
  const rated = items.filter(it => it.picks >= Math.max(1, Math.ceil(it.runs * FAV_MIN_SHARE))).map(it => ({ ...it, winPct: it.wins / it.picks * 100 }));
  return {
    picked: top(items, "picks"),
    win: top(rated, "winPct"),
    bought: top(items.filter(it => it.buys), "buys"),
  };
}

// One item: picture, name, and the card's win rate. The count behind the pick
// is the small print, so all three columns read the same way: the rate is
// what you compare, whichever way the slot chose its card. The card or relic
// opens on hover or tap as a floating tooltip (bound in renderCardFavorites),
// like the card table below: one hidden inside the cell would still widen a
// phone's page.
function favCellHtml(kind, item, winPct, detail) {
  if (!item) return `<td class="fav-cell fav-empty">—</td>`;
  return `<td class="fav-cell">${favItemHtml(kind, item, winPct, detail)}</td>`;
}

function favItemHtml(kind, item, winPct, detail, { cohort = "", comparison = null } = {}) {
  const isCard = kind === "cards";
  const label = isCard ? fmtCardLabel(item.id) : fmtRelicLabel(item.id);
  const src = isCard ? cardImgSrc(item.id) : relicImgSrc(item.id);
  const face = isCard && cardFaceAvailable()
    ? renderCardFace(item.id, 0, "var(--fav-face-w)", { thumb: true }) : "";
  const pic = face
    ? `<span class="fav-item-face">${face}</span>`
    : src ? `<img loading="lazy" src="${thumbSrc(src)}" alt="" class="fav-pic">` : "";
  const figures = [{ cohort, winPct, detail }];
  if (comparison) figures.push(comparison);
  const rateText = pct => pct == null ? "—" : `${Math.round(pct)}%`;
  const accessible = figures.map(f => [f.cohort, f.detail, `${rateText(f.winPct)} won`].filter(Boolean).join(", "));
  return `<span class="fav-item" role="group" tabindex="0" data-fav-kind="${kind}" data-fav-id="${item.id}" aria-label="${escapeHtml([label, ...accessible].join(", "))}">
    <span class="fav-icon">${pic}</span>
    <span class="fav-text">
      <span class="fav-name">${escapeHtml(label)}</span>
      <span class="fav-figs">${figures.map(f => `<span class="fav-figures">
        <span class="fav-detail">${f.cohort ? `<span class="fav-cohort${f.cohort === "All players" ? " fav-cohort-all" : ""}">${f.cohort}</span> ` : ""}<span class="fav-rate${f.winPct >= 50 ? " fav-hi" : ""}">${rateText(f.winPct)}</span><span class="fav-won"> won</span></span>
        <span class="fav-count">${f.detail}</span>
      </span>`).join("")}</span>
    </span>
  </span>`;
}

function favPanelHtml(title, tallies, chars) {
  const picks = n => `${n} pick${n !== 1 ? "s" : ""}`;
  const rows = favSlots().map(slot => {
    const f = favPicksFor(tallies, slot, chars);
    const p = f.picked, w = f.win, b = f.bought;
    return `<tr><th>${slot.label}</th>
      ${favCellHtml(slot.kind, p, p && p.wins / p.picks * 100, p && picks(p.picks))}
      ${favCellHtml(slot.kind, w, w && w.winPct, w && `${w.wins} of ${w.picks}`)}
      ${favCellHtml(slot.kind, b, b && b.buyWins / b.buys * 100, b && `${b.buys} bought`)}
    </tr>`;
  }).join("");
  return `<div class="fav-panel ${title === "You" ? "fav-panel-you" : "fav-panel-all"}">
    <h3>${title}</h3>
    <table class="pivot fav-table">
      <thead><tr><th></th><th>Most picked</th><th>Best win %</th><th>Most bought</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

// With every character in view, one row per character instead of one pool
// for all of them: the columns are the slots (the rarities, and Multi), and a
// switch picks which of the three choices (most picked, best win %, most
// bought) fills them. Each rarity compares the two favorites in the same cell.
let favByCharMetric = "picked";
const FAV_METRICS = [
  { key: "picked", label: "Most picked" },
  { key: "win",    label: "Best win %" },
  { key: "bought", label: "Most bought" },
];

// The figures one metric shows for its item: the win rate and the count
// behind it, as in the panels.
function favMetricFigures(metric, it) {
  if (!it) return [null, null];
  const picks = n => `${n} pick${n !== 1 ? "s" : ""}`;
  if (metric === "win")    return [it.winPct, `${it.wins} of ${it.picks}`];
  if (metric === "bought") return [it.buyWins / it.buys * 100, `${it.buys} bought`];
  return [it.wins / it.picks * 100, picks(it.picks)];
}

function favByCharHtml(you, all) {
  // Characters with runs in either set, in the site's roster order.
  const chars = DATA.characters.filter(c => you.runs[c] || (all && all.runs[c]));
  const slots = favSlots();
  const cell = (slot, char) => {
    const mine = favPicksFor(you, slot, [char])[favByCharMetric];
    const theirs = all && favPicksFor(all, slot, [char])[favByCharMetric];
    if (!mine && !theirs) return `<td class="fav-cell fav-empty">—</td>`;
    const myFigures = favMetricFigures(favByCharMetric, mine);
    if (!all) return favCellHtml(slot.kind, mine, ...myFigures);
    const allFigures = favMetricFigures(favByCharMetric, theirs);
    if (mine && theirs && mine.id === theirs.id) {
      const [winPct, detail] = allFigures;
      return `<td class="fav-cell fav-card-shared">${favItemHtml(slot.kind, mine, ...myFigures, {
        cohort: "You", comparison: { cohort: "All players", winPct, detail },
      })}</td>`;
    }
    const entry = (item, figures, cohort) => item
      ? favItemHtml(slot.kind, item, ...figures, { cohort })
      : `<span class="fav-empty" aria-label="${cohort}: no favorite">${cohort} —</span>`;
    return `<td class="fav-cell"><div class="fav-card-pair">
      <div class="fav-card-you">${entry(mine, myFigures, "You")}</div>
      <div class="fav-card-all">${entry(theirs, allFigures, "All players")}</div>
    </div></td>`;
  };
  const rows = chars.map(char => {
    const n = you.runs[char] || 0;
    return `<tr><th scope="row">${charLabelHtml(char)}<span class="fav-runs">${n} run${n !== 1 ? "s" : ""}</span></th>${slots.map(slot => cell(slot, char)).join("")}</tr>`;
  }).join("");
  const switcher = `<div class="filter-group fav-metric">${FAV_METRICS.map(m =>
    `<button class="toggle-btn${m.key === favByCharMetric ? " active" : ""}" data-fav-metric="${m.key}">${m.label}</button>`).join("")}</div>`;
  const who = all ? `<div class="filter-group fav-who" role="group" aria-label="Favorites population">${["you", "all"].map(w => {
    const active = (w === "all") === favByCharShowAll;
    return `<button type="button" class="toggle-btn${active ? " active" : ""}" aria-pressed="${active}" data-fav-who="${w}">${w === "all" ? "All players" : "You"}</button>`;
  }).join("")}</div>` : "";
  return `<div class="fav-bychar">
    <div class="fav-bychar-bar">${switcher}${who}</div>
    <div class="pivot-wrap fav-bychar-wrap"><table class="pivot fav-table fav-bychar-table fav-card-table${favByCharShowAll && all ? " show-all" : ""}">
      <thead><tr><th></th>${slots.map(slot => `<th scope="col">${slot.label}</th>`).join("")}</tr></thead><tbody>${rows}</tbody>
    </table></div>
  </div>`;
}
let favByCharShowAll = false; // which distinct pick to show when both cannot fit

const favCoopNote = () => favSlots().some(s => s.coop) ? ", and of the cards only multiplayer runs offer (Multi)" : "";

function renderCardFavorites() {
  loadSiteStatsForFavs();
  const all = favTalliesAll();
  const box = document.getElementById("cards-favorites");
  const caption = document.getElementById("cards-fav-caption");
  if (sharedActiveChar === "ALL") {
    box.classList.add("fav-panels-bychar");
    box.innerHTML = favByCharHtml(favTalliesYou(), all);
    if (caption) caption.textContent = `Each character's ${FAV_METRICS.find(m => m.key === favByCharMetric).label.toLowerCase()} card of each rarity${favCoopNote()}${all ? ", yours beside all players'" : ""}. Every card shows its win rate, with the count behind it underneath.`;
    box.querySelectorAll("[data-fav-metric]").forEach(btn => btn.addEventListener("click", () => {
      favByCharMetric = btn.dataset.favMetric;
      renderCardFavorites();
    }));
    box.querySelectorAll("[data-fav-who]").forEach(btn => btn.addEventListener("click", () => {
      favByCharShowAll = btn.dataset.favWho === "all";
      box.querySelector(".fav-card-table").classList.toggle("show-all", favByCharShowAll);
      box.querySelectorAll("[data-fav-who]").forEach(control => {
        const active = control === btn;
        control.classList.toggle("active", active);
        control.setAttribute("aria-pressed", String(active));
      });
    }));
  } else {
    box.classList.remove("fav-panels-bychar");
    const chars = [sharedActiveChar];
    box.innerHTML = favPanelHtml("You", favTalliesYou(), chars) + (all ? favPanelHtml("All players", all, chars) : "");
    if (caption) caption.textContent = `Your most-picked, best win rate and most-bought card of each rarity${favCoopNote()}${all ? ", beside the same for all players" : ""}. Every card shows its win rate, with the count behind it underneath.`;
  }
  box.querySelectorAll(".fav-item[data-fav-id]").forEach(el => {
    const show = () => showFloatingHtmlTooltip(el, el.dataset.favKind === "cards"
      ? buildCardTooltip(el.dataset.favId, 0) : buildRelicTooltip(el.dataset.favId));
    el.addEventListener("mouseenter", show);
    el.addEventListener("mouseleave", hideFloatingHtmlTooltip);
    el.addEventListener("focus", show);
    el.addEventListener("blur", hideFloatingHtmlTooltip);
  });
}
