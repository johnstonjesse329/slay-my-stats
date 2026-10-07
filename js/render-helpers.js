// -------------------------------------------------------------------------
// Rendering helpers
// -------------------------------------------------------------------------

const CHAR_COLOR_MAP = Object.fromEntries(
  DATA.characters.map((char, index) => [char, DATA.charColors[index]])
);

// Keyboard parity for mouse-only controls: several interactive elements in
// this dashboard are divs/spans/ths/rows bound with click handlers only.
// Native buttons already fire on Enter/Space, so route those keys to click
// for the ones we make focusable with tabindex.
function bindEnterSpace(el) {
  el.addEventListener("keydown", e => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      el.click();
    }
  });
}

function avgRestOnWins(filteredRuns) {
  let healSum = 0, smithSum = 0, n = 0;
  const healVals = [], smithVals = [];
  filteredRuns.forEach(run => {
    if (!run.won) return;
    const rc = run.restChoices || {};
    if (rc["3"] === undefined) return;  // didn't reach Act 3
    const h = REST_ACTS.reduce((s, act) => s + ((rc[String(act)] || {})["HEAL"]  || 0), 0);
    const s = REST_ACTS.reduce((s, act) => s + ((rc[String(act)] || {})["SMITH"] || 0), 0);
    healSum += h; smithSum += s;
    healVals.push(h); smithVals.push(s);
    n++;
  });
  return n > 0
    ? { heal: +(healSum / n).toFixed(1), smith: +(smithSum / n).toFixed(1),
        healMedian: median(healVals), smithMedian: median(smithVals) }
    : { heal: null, smith: null, healMedian: null, smithMedian: null };
}

function renderCards(grand, charStats, restAvg) {
  const chars = DATA.characters;

  const bestIdx = charStats.reduce((bestIndex, stat, currentIndex) =>
    (stat.runs > 0 && (charStats[bestIndex].runs === 0 || stat.win_pct >= charStats[bestIndex].win_pct))
      ? currentIndex : bestIndex,
    0
  );
  const mostIdx = charStats.reduce((bestIndex, stat, currentIndex) =>
    stat.runs >= charStats[bestIndex].runs ? currentIndex : bestIndex,
    0
  );

  const mostPlayedPct = grand.runs ? +((charStats[mostIdx].runs / grand.runs) * 100).toFixed(0) : 0;
  const winPct = grand.win_pct !== null ? grand.win_pct + "%" : "—";
  const items = [
    { label: "Overall Win Rate", value: winPct },
    { label: "Best Win Rate", value: charStats[bestIdx].win_pct !== null ? charStats[bestIdx].win_pct + "%" : "—",
      tip: charStats[bestIdx].win_pct !== null ? `${fmtCharName(chars[bestIdx])} · ${charStats[bestIdx].wins}W / ${charStats[bestIdx].runs}L` : "No wins" },
    { label: "Most Played",    value: fmtCharName(chars[mostIdx]),
      // Run count is the Runs card's value — show only the share here.
      tip: `${mostPlayedPct}% of all runs` },
    { label: "Total Gold Gained", value: grand.runs ? grand.total_gold.toLocaleString() : "—",
      tip: grand.runs ? `median ${grand.median_gold.toLocaleString()} per run` : "" },
    // Elites and bosses are a card each. The row stays at 8 cards, which
    // divides evenly into 4 + 4 instead of leaving a ragged edge.
    { label: "Elites Defeated", value: grand.runs ? grand.total_elites_defeated.toLocaleString() : "—" },
    { label: "Bosses Defeated", value: grand.runs ? grand.total_bosses_defeated.toLocaleString() : "—" },
  ];

  // The scope note is worth keeping — a filtered number must not read as a
  // lifetime one — but it moves to the tooltip. The filter bar's summary line
  // states the active mode in plain sight, so nothing is lost by not repeating
  // it on the card.
  const scopeNote = sharedActiveMode !== "all"
    ? `${({ solo: "Solo", multi: "Multiplayer", daily: "Daily" }[sharedActiveMode] || sharedActiveMode)} runs only`
    : "";
  const runsTip = [`${grand.wins} win${grand.wins === 1 ? "" : "s"}`, scopeNote].filter(Boolean).join(" · ");
  const runsCard = `<div class="card" data-tip="${runsTip}" tabindex="0">
    <div class="label">Runs</div>
    <div class="value">${grand.runs}</div>
  </div>`;

  // Leads the row — total time invested is one of the most immediately
  // relevant stats, ahead of even the Runs count.
  const timeCard = `<div class="card"${grand.runs ? ` data-tip="median ${grand.median_min}m per run" tabindex="0"` : ""}>
    <div class="label">Total Time Played</div>
    <div class="value">${grand.runs ? fmtHrsMin(grand.total_min) : "—"}</div>
  </div>`;

  document.getElementById("summary-cards").innerHTML = timeCard + runsCard + items.map(card =>
    // tabindex so the data-tip is reachable by keyboard and by a phone tap, the
    // same way the Personal Bests rows do it.
    `<div class="card"${card.tip ? ` data-tip="${card.tip}" tabindex="0"` : ""}>
      <div class="label">${card.label}</div>
      <div class="value">${card.value}</div>
    </div>`
  ).join("");
}

function renderPersonalBests() {
  const chars = DATA.characters;
  const allRuns = [...filterRuns()].sort((a, b) => a.ts - b.ts);

  const bests = {};
  chars.forEach(char => {
    bests[char] = { gamesPlayed: 0, totalWins: 0, finalBossDeaths: 0, eliteDeaths: 0, currentStreak: 0, longestStreak: 0, _streak: 0, fastestWin: null, fewestElites: null, mostElitesWin: null, mostCards: null, fewestCards: null, mostRelics: null, fewestRelics: null, mostMaxHp: null, fewestMaxHp: null, mostFinalBossTurns: null, fewestFinalBossTurns: null };
  });

  allRuns.forEach(run => {
    const b = bests[run.char];
    if (!b) return;
    b.gamesPlayed = (b.gamesPlayed || 0) + 1;
    const bossFights = (run.fights || []).filter(f => f.type === "boss");
    const finalBoss  = bossFights.length ? bossFights[bossFights.length - 1] : null;
    if (finalBoss && !finalBoss.won) {
      b.finalBossDeaths = (b.finalBossDeaths || 0) + 1;
    }
    // The last fight in the list is the one the run ended on, so its type and
    // won flag are what the player actually died to.
    const lastFight = (run.fights || []).slice(-1)[0];
    if (lastFight && lastFight.type === "elite" && !lastFight.won) b.eliteDeaths++;
    // Every "best" below is { value, ts } rather than a bare number, so the
    // card can link straight to the specific run that produced it — see
    // statLink below, which routes through jumpToRun().
    if (finalBoss && finalBoss.won && finalBoss.turns != null) {
      if (b.mostFinalBossTurns === null || finalBoss.turns > b.mostFinalBossTurns.value) b.mostFinalBossTurns = { value: finalBoss.turns, ts: run.ts };
      if (b.fewestFinalBossTurns === null || finalBoss.turns < b.fewestFinalBossTurns.value) b.fewestFinalBossTurns = { value: finalBoss.turns, ts: run.ts };
    }
    if (run.won) {
      b.totalWins = (b.totalWins || 0) + 1;
      b._streak++;
      if (b._streak > b.longestStreak) b.longestStreak = b._streak;
    } else {
      b._streak = 0;
    }
    if (run.won && run.mins != null && (b.fastestWin === null || run.mins < b.fastestWin.value))
      b.fastestWin = { value: run.mins, ts: run.ts };
    if (run.won && run.timeline && run.timeline.length) {
      const finalMaxHp = run.timeline[run.timeline.length - 1].maxHp;
      if (finalMaxHp != null) {
        if (b.mostMaxHp === null || finalMaxHp > b.mostMaxHp.value) b.mostMaxHp = { value: finalMaxHp, ts: run.ts };
        if (b.fewestMaxHp === null || finalMaxHp < b.fewestMaxHp.value) b.fewestMaxHp = { value: finalMaxHp, ts: run.ts };
      }
    }
    const elites = (run.fights || []).filter(f => f.type === "elite" && f.won).length;
    if (run.won) {
      if (b.fewestElites === null || elites < b.fewestElites.value) b.fewestElites = { value: elites, ts: run.ts };
      if (b.mostElitesWin === null || elites > b.mostElitesWin.value) b.mostElitesWin = { value: elites, ts: run.ts };
      if (run.cards != null) {
        if (b.mostCards === null || run.cards > b.mostCards.value) b.mostCards = { value: run.cards, ts: run.ts };
        if (b.fewestCards === null || run.cards < b.fewestCards.value) b.fewestCards = { value: run.cards, ts: run.ts };
      }
      if (run.relics != null) {
        if (b.mostRelics === null || run.relics > b.mostRelics.value) b.mostRelics = { value: run.relics, ts: run.ts };
        if (b.fewestRelics === null || run.relics < b.fewestRelics.value) b.fewestRelics = { value: run.relics, ts: run.ts };
      }
    }
  });
  chars.forEach(char => { bests[char].currentStreak = bests[char]._streak; });


  // One line per stat, label left / value right. The panels used to stack an
  // uppercase label over every value in a two-column grid, and in a 5-wide
  // grid most labels wrapped to two or three lines, so each panel ran ~970px.
  const row = (label, valueHtml) =>
    `<div style="display:flex;justify-content:space-between;align-items:baseline;gap:0.5rem;font-size:0.8rem;line-height:1.55">
      <span style="color:#8a8aa0">${label}</span>
      <span style="font-weight:600;color:#ccc;white-space:nowrap">${valueHtml}</span>
    </div>`;

  // A value that links to the specific run that produced it (best is
  // { value, ts } or null — see the tracking above).
  const link = (best, fmt = v => v) => best
    ? `<span class="pb-stat-link" data-ts="${best.ts}" data-tip="Jump to this run" style="cursor:pointer;text-decoration:underline;text-decoration-style:dotted;text-decoration-color:#8a8aa0;text-underline-offset:2px">${fmt(best.value)}</span>`
    : "—";

  // Fewest–most as one row; each end still links to its own run.
  const range = (lo, hi, fmt) => !lo || !hi ? "—"
    : lo.value === hi.value ? link(lo, fmt)
    : `${link(lo, fmt)}<span style="color:#8a8aa0;font-weight:400"> – </span>${link(hi, fmt)}`;

  const heading = (title, note = "") =>
    `<div style="display:flex;justify-content:space-between;align-items:baseline;gap:0.5rem;border-top:1px solid #3f4147;margin-top:0.4rem;padding-top:0.35rem;margin-bottom:0.15rem">
      <span style="font-size:0.68rem;color:#a8a2c4;text-transform:uppercase;letter-spacing:.06em;font-weight:600">${title}</span>
      <span style="font-size:0.68rem;color:#8a8aa0;text-align:right">${note}</span>
    </div>`;

  // Favorites as a two-column grid: column headers once ("Most picked" /
  // "Best win %"), then one row per group with a small label spanning both
  // columns. Items use favoriteItemHtml's column layout, where names wrap to
  // two lines instead of truncating to "Bloodle…" in the narrow column.
  const colHead = text =>
    `<div style="font-size:0.7rem;color:#a8a2c4;font-weight:600">${text}</div>`;
  const groupLabel = text =>
    `<div style="grid-column:1/-1;font-size:0.66rem;color:#8a8aa0;text-transform:uppercase;letter-spacing:.06em;margin-top:0.2rem">${text}</div>`;
  const favGrid = (headA, headB, groups) =>
    `<div style="display:grid;grid-template-columns:repeat(2, minmax(0, 1fr));gap:0.15rem 0.6rem;border-top:1px solid #3f4147;margin-top:0.4rem;padding-top:0.35rem">
      ${colHead(headA)}${colHead(headB)}
      ${groups.map(([label, a, b]) => `${label ? groupLabel(label) : ""}${a}${b}`).join("")}
    </div>`;

  const favorites = aggregateCharFavorites();

  document.getElementById("personal-bests-cards").innerHTML = chars.map(char => {
    const b = bests[char];
    const color = CHAR_COLOR_MAP[char] || "#a0a0b8";
    const label = fmtCharName(char);
    const noRuns = b.fastestWin === null;
    // Deaths read as a count plus a share of every run this character has, so
    // "died 3 times" has a scale next to it.
    const deaths = n => b.gamesPlayed
      ? `${n}<span style="color:#8a8aa0;font-weight:400"> · </span>${Math.round(n / b.gamesPlayed * 100)}%`
      : "—";
    const fav = favorites[char];

    return `<div class="card" style="border-color:${color}55;box-sizing:border-box">
      <div style="font-size:0.75rem;font-weight:700;color:${color};letter-spacing:.04em;margin-bottom:0.35rem">${label.toUpperCase()}</div>
      ${row("Runs", b.gamesPlayed || "—")}
      ${row("Wins", b.gamesPlayed
        ? `${b.totalWins}<span style="color:#8a8aa0;font-weight:400"> · </span>${Math.round(b.totalWins / b.gamesPlayed * 100)}%`
        : "—")}
      ${row("Final boss deaths", deaths(b.finalBossDeaths))}
      ${row("Elite deaths", deaths(b.eliteDeaths))}
      ${noRuns
        ? `<div style="color:#8a8aa0;font-size:0.8rem;padding:0.25rem 0">No wins yet</div>`
        : `${row("Current win streak", b.currentStreak || 0)}
          ${row("Best win streak", b.longestStreak)}
          ${row("Fastest win", link(b.fastestWin, fmtHrsMinSec))}
          ${heading("Winning runs", "lowest – highest")}
          ${row("Elites", range(b.fewestElites, b.mostElitesWin))}
          ${row("Cards", range(b.fewestCards, b.mostCards))}
          ${row("Relics", range(b.fewestRelics, b.mostRelics))}
          ${row("Max HP", range(b.fewestMaxHp, b.mostMaxHp))}
          ${row("Final boss turns", range(b.fewestFinalBossTurns, b.mostFinalBossTurns))}
          ${favGrid("Most picked", "Best win %", [
              ["Cards",  favoriteItemHtml("card",  fav.card.mostPicked,      "picks", "count", true),
                         favoriteItemHtml("card",  fav.card.bestWinRate,     "picks", "win",   true)],
              ["Rares",  favoriteItemHtml("card",  fav.rareCard.mostPicked,  "picks", "count", true),
                         favoriteItemHtml("card",  fav.rareCard.bestWinRate, "picks", "win",   true)],
              ["Relics", favoriteItemHtml("relic", fav.relic.mostPicked,     "picks", "count", true),
                         favoriteItemHtml("relic", fav.relic.bestWinRate,    "picks", "win",   true)],
            ])}
          ${favGrid("Most bought card", "Most bought relic", [
              [null, favoriteItemHtml("card",  fav.shopCard.mostPicked,  "buys", "count", true),
                     favoriteItemHtml("relic", fav.shopRelic.mostPicked, "buys", "count", true)],
            ])}`
      }
    </div>`;
  }).join("");

  document.querySelectorAll("#personal-bests-cards .pb-stat-link").forEach(el => {
    el.setAttribute("role", "link");
    el.setAttribute("tabindex", "0");
    el.addEventListener("click", () => {
      const ts = +el.dataset.ts;
      if (!DATA.runsData.find(r => r.ts === ts)) return;
      jumpToRun(ts);
    });
    bindEnterSpace(el);
  });
}

// Ascension Tracker: per character, how far the climb to A10 has got, once for
// solo runs and once for multiplayer.
//
// Reads every run, not the filtered set: it is a record of what has been
// reached, and it has its own solo / multiplayer split. Only standard runs
// count. A daily or custom run sets its own ascension (a daily can be A8 for a
// character whose climb is at A2), so it says nothing about the climb.
//
// One pip per ascension, A1 to A10, so every step of the climb shows. (Pips
// for only the big difficulty jumps, A1 / A8 / A9 / A10, left a character on
// one pip all the way from A1 to its A8 win.) A pip lights on a WON run at
// that ascension or above: ascensions unlock in order, so an A10 win means
// the earlier ones were beaten too.
const ASC_TRACKER_MAX = 10;
const ASC_TRACKER_LEVELS = Array.from({ length: ASC_TRACKER_MAX }, (_, i) => i + 1);
const ASC_TRACKER_MODES = [
  { label: "Solo",        test: run => !run.mp },
  { label: "Multiplayer", test: run => !!run.mp },
];

// { highestWin: {value, ts} | null, top, topWins, topLosses } for one
// character in one mode, or null with no runs. highestWin is the first run
// that won at the highest ascension won; top is the highest ascension played.
function aggregateAscTracker(runs) {
  if (!runs.length) return null;
  let highestWin = null;
  runs.forEach(run => {
    if (run.won && (highestWin === null || run.asc > highestWin.value)) highestWin = { value: run.asc, ts: run.ts };
  });
  const top = Math.max(...runs.map(run => run.asc));
  const atTop = runs.filter(run => run.asc === top);
  const topWins = atTop.filter(run => run.won).length;
  return { highestWin, top, topWins, topLosses: atTop.length - topWins };
}

function renderAscTracker() {
  const fmtDate = ts => new Date(ts * 1000).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  const maxAsc = ASC_TRACKER_MAX;
  const standard = DATA.runsData
    .filter(run => (run.mode || "standard") === "standard" && run.asc != null)
    .sort((a, b) => a.ts - b.ts);

  const block = (char, color, mode) => {
    const t = aggregateAscTracker(standard.filter(run => run.char === char && mode.test(run)));
    const won = t && t.highestWin ? t.highestWin.value : -1;
    const pips = ASC_TRACKER_LEVELS.map(level =>
      `<span class="asc-pip" data-tip="A${level}"${won >= level ? ` style="background:${color}"` : ""}></span>`).join("");
    if (!t) {
      return `<div class="asc-mode">
        <div class="asc-mode-label">${mode.label}</div>
        <div class="asc-big asc-none">—</div>
        <div class="asc-sub">no runs</div>
        <div class="asc-pips">${pips}</div>
      </div>`;
    }
    const record = `${t.topWins}W / ${t.topLosses}L`;
    const big = t.highestWin
      ? `<span class="pb-stat-link" data-ts="${t.highestWin.ts}" data-tip="Jump to this run" style="cursor:pointer">A${won}</span>`
      : "—";
    const now = won >= maxAsc
      ? `A${maxAsc} won ${fmtDate(t.highestWin.ts)}<br>${record} at A${maxAsc}`
      : `Now on A${t.top}<br>${record} there`;
    return `<div class="asc-mode">
      <div class="asc-mode-label">${mode.label}</div>
      <div class="asc-big${t.highestWin ? "" : " asc-none"}" style="color:${color}">${big}</div>
      <div class="asc-sub">${t.highestWin ? "highest ascension won" : "no wins yet"}</div>
      <div class="asc-pips">${pips}</div>
      <div class="asc-now">${now}</div>
    </div>`;
  };

  // Beside the title: how many characters have an A10 win in each mode, and
  // the first A10 win of all.
  const a10 = standard.filter(run => run.won && run.asc >= maxAsc);
  const first = a10[0];
  const total = DATA.characters.length;
  document.getElementById("asc-tracker-stats").innerHTML = ASC_TRACKER_MODES.map(mode =>
    `<div><b>${new Set(a10.filter(mode.test).map(run => run.char)).size} / ${total}</b>A${maxAsc} ${mode.label.toLowerCase()}</div>`).join("") +
    `<div><b>${first
      ? `<span class="pb-stat-link" data-ts="${first.ts}" data-tip="Jump to this run" style="cursor:pointer">${fmtDate(first.ts)}</span>`
      : "—"}</b>first A${maxAsc} win${first ? ` · ${fmtCharName(first.char)}` : ""}</div>`;

  const el = document.getElementById("asc-tracker-cards");
  el.innerHTML = DATA.characters.map(char => {
    const color = CHAR_COLOR_MAP[char] || "#a0a0b8";
    return `<div class="asc-card" style="border-top-color:${color}">
      <div class="asc-name">${fmtCharName(char)}</div>
      ${ASC_TRACKER_MODES.map(mode => block(char, color, mode)).join("")}
    </div>`;
  }).join("");

  el.parentElement.querySelectorAll(".pb-stat-link").forEach(link => {
    link.setAttribute("role", "link");
    link.setAttribute("tabindex", "0");
    link.addEventListener("click", () => jumpToRun(+link.dataset.ts));
    bindEnterSpace(link);
  });
}

// Aggregates offer/pick/win data per character for cards and relics.
// Respects shared filters. Returns, per character:
// mostPicked (highest pick count) and bestWinRate (highest win % overall)
// — both for cards and relics.
function aggregateCharFavorites() {
  const MIN_PICKS = 5;
  const chars = DATA.characters;
  const cardData = DATA.cardData || {};
  const favorites = {};

  chars.forEach(char => {
    favorites[char] = {
      card:     { byId: {} },
      relic:    { byId: {} },
      rareCard: { byId: {} },
      shopCard: { byId: {} },
      shopRelic:{ byId: {} },
    };
  });

  filterRuns().forEach(run => {
    const fav = favorites[run.char];
    if (!fav) return;
    [["card", run.cardsOffered], ["relic", run.relicsOffered]].forEach(([kind, offered]) => {
      Object.entries(offered || {}).forEach(([id, locs]) => {
        locs.forEach(loc => {
          if (!loc.picked) return;
          const byId = fav[kind].byId;
          if (!byId[id]) byId[id] = { picked: 0, won: 0 };
          byId[id].picked++;
          if (run.won) byId[id].won++;
          if (kind === "card" && (cardData[id] || {}).rarity === "Rare") {
            const rareById = fav.rareCard.byId;
            if (!rareById[id]) rareById[id] = { picked: 0, won: 0 };
            rareById[id].picked++;
            if (run.won) rareById[id].won++;
          }
          if (loc.type === "shop") {
            if (kind === "card") {
              const pool = (cardData[id] || {}).pool || "";
              if (pool !== run.char && pool !== "colorless") return;
            }
            const shopById = fav[kind === "card" ? "shopCard" : "shopRelic"].byId;
            if (!shopById[id]) shopById[id] = { picked: 0, won: 0 };
            shopById[id].picked++;
            if (run.won) shopById[id].won++;
          }
        });
      });
    });
  });

  const result = {};
  chars.forEach(char => {
    result[char] = {};
    ["card", "relic", "rareCard", "shopCard", "shopRelic"].forEach(kind => {
      const entries = Object.entries(favorites[char][kind].byId);
      let mostPicked = null;
      // Prefer items meeting MIN_PICKS, falling back to a below-threshold item
      // only if nothing clears the bar: otherwise a single 100%-win pick would
      // always beat a well-sampled 80%-win item. This chooses which item to
      // show — it flags nothing, and no low-sample marking is rendered.
      let bestQualified = null, bestAny = null;
      entries.forEach(([id, b]) => {
        const winPct = +(b.won / b.picked * 100).toFixed(0);
        if (!mostPicked || b.picked > mostPicked.picked) mostPicked = { id, picked: b.picked, winPct };
        const candidate = { id, winPct, picked: b.picked };
        if (!bestAny || winPct > bestAny.winPct) bestAny = candidate;
        if (b.picked >= MIN_PICKS && (!bestQualified || winPct > bestQualified.winPct)) bestQualified = candidate;
      });
      const bestWinRate = bestQualified || bestAny;
      result[char][kind] = { mostPicked, bestWinRate };
    });
  });
  return result;
}

// emph ("count" | "win") brightens the number the item was chosen for, and
// leads with it. column: true is the narrow two-column layout in the
// character panes -- the thumbnail top-aligns with a name clamped to two
// lines with an ellipsis for names that don't fit (the hover/tap tooltip
// this row already has shows the full name), and the stat pieces wrap when
// they don't fit.
function favoriteItemHtml(kind, item, countLabel = "picks", emph = null, column = false) {
  // Empty state keeps the same icon + two-line footprint as populated rows
  // so the tile grid's row heights stay aligned across characters
  if (!item) return `<div style="display:flex;align-items:${column ? "flex-start" : "center"};gap:0.4rem;min-width:0;opacity:0.45">
    <span style="width:22px;height:22px;flex:0 0 auto;border:1px dashed #3f4147;border-radius:4px"></span>
    <div style="min-width:0">
      <div style="font-size:0.78rem;color:#8a8aa0">None yet</div>
      <div style="font-size:0.72rem;color:#8a8aa0">no ${countLabel}</div>
    </div>
  </div>`;
  const label = kind === "card" ? fmtCardLabel(item.id) : fmtRelicLabel(item.id);
  const hi = (text, on) => on ? `<b style="color:#e8e6f0;font-weight:700">${text}</b>` : text;
  const countText = hi(`${item.picked} ${item.picked === 1 ? countLabel.replace(/s$/, "") : countLabel}`, emph === "count");
  const winText   = item.winPct != null ? hi(`${item.winPct}% win`, emph === "win") : null;
  // One field order in both columns. The pair is there to be read across, and
  // swapping pick/win by column ("27 picks · 52% win" beside "86% win · 7
  // picks") made the reader relearn the order every time.
  const pieces = [countText, winText].filter(Boolean);
  const sub = pieces.join(" · ");
  const plainSub = sub.replace(/<[^>]+>/g, "");
  // Same real card face / relic art used everywhere else, at icon size, with
  // the same rich hover tooltip -- this row used to show a bare cropped
  // portrait with no hover at all, which read as inconsistent next to every
  // other card/relic thumbnail in the dashboard.
  let thumbHtml, tooltipHtml, tooltipClass;
  if (kind === "card") {
    thumbHtml = cardFaceAvailable()
      ? `<div class="fav-item-face">${renderCardFace(item.id, 0, 26, { thumb: true, props: item.props })}</div>`
      : (() => {
          const src = cardImgSrc(item.id);
          return src ? `<img loading="lazy" src="${thumbSrc(src)}" alt="${label}" style="width:22px;height:22px;object-fit:contain;border-radius:4px;flex:0 0 auto">` : "";
        })();
    tooltipHtml = buildCardTooltip(item.id, 0, item.props, item.enchantment);
    tooltipClass = "card-tooltip-wrap";
  } else {
    const src = relicImgSrc(item.id);
    thumbHtml = src
      ? `<img loading="lazy" src="${thumbSrc(src)}" alt="${label}" style="width:22px;height:22px;object-fit:contain;border-radius:4px;flex:0 0 auto">`
      : "";
    tooltipHtml = buildRelicTooltip(item.id);
    tooltipClass = "relic-tooltip-wrap";
  }

  return `<div class="fav-item" tabindex="0" role="img" aria-label="${label} — ${plainSub}" style="display:flex;align-items:${column ? "flex-start" : "center"};gap:0.4rem;min-width:0">
    ${thumbHtml}
    ${column
      ? `<div style="min-width:0">
      <div style="font-size:0.76rem;color:#ccc;line-height:1.2;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;hyphens:auto" lang="en">${label}</div>
      <div style="font-size:0.7rem;color:#a0a0b8;display:flex;flex-wrap:wrap;align-items:center;column-gap:0.3rem;line-height:1.35">
        ${pieces.map(p => `<span style="white-space:nowrap">${p}</span>`).join("")}
      </div>
    </div>`
      : `<div style="overflow:hidden;min-width:0">
      <div style="font-size:0.78rem;color:#ccc;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${label}</div>
      <div style="font-size:0.72rem;color:#a0a0b8;display:flex;align-items:center;gap:0.25rem;min-width:0">
        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0">${sub}</span>
      </div>
    </div>`}
    ${tooltipHtml ? `<div class="${tooltipClass}">${tooltipHtml}</div>` : ""}
  </div>`;
}

function charNameCell(char) {
  const color = CHAR_COLOR_MAP[char] || "#a0a0b8";
  const label = fmtCharName(char);
  return `<td class="char-name">
    <span class="dot" style="background:${color}"></span>${label}
  </td>`;
}

// Shared win-%-to-color mapping for every pivot-table cell in the dashboard.
// tiers is [highCutoff, midCutoff, lowCutoff] -- pass an override for a cell
// whose scale reads differently (e.g. fightWinCell's individual-fight
// thresholds).
//
// The number is coloured from the SAME cutoffs as the cell's fill, so a cell
// can't contradict itself. It used to colour the text from a second, narrower
// pair ([40, 20]), which left two bands disagreeing: 30-39% painted an amber
// number on a green cell, and 15-19% a red number on an amber one.
function winPctStyle(pct, tiers = [50, 30, 15]) {
  const high = pct >= tiers[0];
  const mid  = pct >= tiers[1];
  const low  = pct >= tiers[2];
  const bg = high ? "rgba(92,186,125,0.28)"
           : mid  ? "rgba(92,186,125,0.14)"
           : low  ? "rgba(232,169,48,0.22)"
           :        "rgba(224,92,92,0.22)";
  const color = (high || mid) ? "#5cba7d"
              : low           ? "#e8a930"
              :                 "#e05c5c";
  return { bg, color };
}

function winCell(bucket, isAll) {
  const cls = "cell" + (isAll ? " all-col" : "");

  if (!bucket) return `<td class="${cls} empty">—</td>`;

  const { bg, color } = winPctStyle(bucket.win_pct);

  // Three distinct facts, not fragments of one — each gets its own line
  // rather than being run together on one wrapped line.
  const tooltip = [
    `Runs: ${bucket.runs} (${bucket.wins}W / ${bucket.losses}L)`,
    `Avg floor: ${bucket.avg_floor}`,
    `Avg time: ${fmtHrsMin(bucket.avg_min)}`,
  ].join("\n");

  return `<td class="${cls}" style="background:${bg}" data-tip="${tooltip}">
    <div class="pct" style="color:${color}">${bucket.win_pct}%</div>
    <div class="meta">${bucket.runs} run${bucket.runs !== 1 ? "s" : ""}</div>
  </td>`;
}

function renderWinPivot(pivotData) {
  const chars = DATA.characters;
  const ascs  = ascColumns();

  let html = `<thead><tr>
    <th class="char-head">Character</th>
    ${ascs.map(col => `<th>${col.label}</th>`).join("")}
    <th class="all-col" style="border-left:2px solid #3f4147">All<br>columns</th>
  </tr></thead><tbody>`;

  chars.forEach(char => {
    html += `<tr>${charNameCell(char)}`;
    ascs.forEach(col => { html += winCell(pivotData[char]?.[col.key], false); });
    html += winCell(pivotData[char]?.["ALL"], true);
    html += `</tr>`;
  });

  html += `<tr class="total-row">
    <td class="char-name" style="color:#e0c468">All Characters</td>`;
  ascs.forEach(col => { html += winCell(pivotData["ALL"]?.[col.key], false); });
  html += winCell(pivotData["ALL"]?.["ALL"], true);
  html += `</tr></tbody>`;

  document.getElementById("pivot-table").innerHTML = html;
}

// A run's "final boss" is the last boss-type fight in its fights[] array —
// on Ascension 10, Act 3 has two separate boss nodes, and the second one is
// the one that ends the run. Runs that never reached a boss are excluded
// from both numerator and denominator (not "not won", just not applicable).
function finalBossWinCell(bucket, isAll) {
  const cls = "cell" + (isAll ? " all-col" : "");
  if (!bucket || !bucket.reached) return `<td class="${cls} empty">—</td>`;

  const pct = +(bucket.won / bucket.reached * 100).toFixed(1);
  const { bg, color } = winPctStyle(pct);

  // Both numbers behind the percentage (wins and the "reached" denominator)
  // are already shown inline below, so no hover is needed to see them.
  return `<td class="${cls}" style="background:${bg}">
    <div class="pct" style="color:${color}">${pct}%</div>
    <div class="meta">${bucket.won}W / ${bucket.reached} run${bucket.reached !== 1 ? "s" : ""}</div>
  </td>`;
}

// Ascension 10 splits Act 3 into two separate boss fights; "10-1" and "10-2"
// are pseudo-ascension columns tracking each stage separately (10-2 is the
// true final boss and matches what the "10" bucket already reports).
const A10_STAGE_KEYS = ["10-1", "10-2"];

// Act 3 boss encounter IDs, used to isolate the double-boss Act 3 finale on
// Ascension 10 from earlier-act boss fights (which also show up in fights[]).
const ACT3_BOSS_IDS = new Set(
  (DATA.encGroups || [])
    .filter(g => g.label.startsWith("Act 3") && g.label.includes("Boss"))
    .flatMap(g => g.ids)
);

function aggregateFinalBossWins(filteredRuns) {
  const chars = DATA.characters;
  const ascs  = ascColumns().map(col => col.key);

  const makeBucket = () => ({ reached: 0, won: 0 });
  const byCA = {};
  [...chars, "ALL"].forEach(char => {
    byCA[char] = {};
    [...ascs, ...A10_STAGE_KEYS, "ALL"].forEach(asc => { byCA[char][asc] = makeBucket(); });
  });

  filteredRuns.forEach(run => {
    const fights = run.fights || [];
    const bossFights = fights.filter(f => f.type === "boss");
    if (!bossFights.length) return;  // never reached a boss node

    const finalBoss = bossFights[bossFights.length - 1];
    const won = finalBoss.won;

    const mark = (bucket) => { bucket.reached += 1; if (won) bucket.won += 1; };
    const asc  = ascColumnKey(run.asc);
    if (byCA[run.char]?.[asc])     mark(byCA[run.char][asc]);
    if (byCA[run.char]?.["ALL"])   mark(byCA[run.char]["ALL"]);
    if (byCA["ALL"]?.[asc])        mark(byCA["ALL"][asc]);
    mark(byCA["ALL"]["ALL"]);

    if (run.asc === 10) {
      const act3Bosses = bossFights.filter(f => ACT3_BOSS_IDS.has(f.enc));
      if (act3Bosses.length >= 1) {
        const firstBoss = act3Bosses[0];
        const markFirst = (bucket) => { bucket.reached += 1; if (firstBoss.won) bucket.won += 1; };
        markFirst(byCA[run.char]["10-1"]);
        markFirst(byCA["ALL"]["10-1"]);
      }
      if (act3Bosses.length >= 2) {
        const secondBoss = act3Bosses[1];
        const markSecond = (bucket) => { bucket.reached += 1; if (secondBoss.won) bucket.won += 1; };
        markSecond(byCA[run.char]["10-2"]);
        markSecond(byCA["ALL"]["10-2"]);
      }
    }
  });

  return byCA;
}

function renderFinalBossWinPivot(filteredRuns) {
  const chars = DATA.characters;
  const pivotData = aggregateFinalBossWins(filteredRuns);

  // Ascension 10 has two Act 3 bosses — split its column (A10 on its own,
  // granular or bucketed) into "1st Boss" / "2nd Boss" so the double-boss
  // stage is visible on its own.
  const cols = [];
  ascColumns().forEach(col => {
    if (col.ascs.length === 1 && col.ascs[0] === 10) {
      cols.push({ key: "10-1", label: "A10<br>1st Boss" }, { key: "10-2", label: "A10<br>2nd Boss" });
    } else {
      cols.push(col);
    }
  });

  let html = `<thead><tr>
    <th class="char-head">Character</th>
    ${cols.map(c => `<th>${c.label}</th>`).join("")}
    <th class="all-col" style="border-left:2px solid #3f4147">All<br>columns</th>
  </tr></thead><tbody>`;

  chars.forEach(char => {
    html += `<tr>${charNameCell(char)}`;
    cols.forEach(c => { html += finalBossWinCell(pivotData[char]?.[c.key], false); });
    html += finalBossWinCell(pivotData[char]?.["ALL"], true);
    html += `</tr>`;
  });

  html += `<tr class="total-row">
    <td class="char-name" style="color:#e0c468">All Characters</td>`;
  cols.forEach(c => { html += finalBossWinCell(pivotData["ALL"]?.[c.key], false); });
  html += finalBossWinCell(pivotData["ALL"]?.["ALL"], true);
  html += `</tr></tbody>`;

  document.getElementById("final-boss-win-table").innerHTML = html;
}

function valCell(bucket, valueKey, color, isAll) {
  const cls = "cell" + (isAll ? " all-col" : "");
  if (!bucket || !bucket.runs) return `<td class="${cls} empty">—</td>`;
  return `<td class="${cls}">
    <div style="font-size:0.9rem;font-weight:700;color:${color}">${bucket[valueKey]}</div>
  </td>`;
}

// Deck and Relics at Run End: a row per character, a cards lane beside a
// relics lane, in the character's colour. A ring at the median in runs lost,
// a dot at the median in runs won, and a band between. Cards and relics each
// have their own scale, rounded up to a multiple of 20 so the quarter ticks
// are whole.
function renderRunEndLanes(pivotData) {
  const stats = DATA.characters.map(char => [char, pivotData[char]?.["ALL"]]).filter(([, s]) => s && s.runs);
  const scale = (winKey, lossKey) => {
    const vals = stats.flatMap(([, s]) => [s[winKey], s[lossKey]]).filter(v => v != null);
    return Math.max(20, Math.ceil(Math.max(0, ...vals) / 20) * 20);
  };
  const runCount = n => `${n} run${n !== 1 ? "s" : ""}`;
  const lane = (s, color, winKey, lossKey, max, unit) => {
    const won = s[winKey], lost = s[lossKey];
    const pos = v => +(v / max * 100).toFixed(1);
    const pts = [won, lost].filter(v => v != null);
    const lo = pos(Math.min(...pts)), hi = pos(Math.max(...pts));
    const tip = [
      lost != null ? `Lost: ${lost} ${unit}, ${runCount(s.losses)}` : null,
      won  != null ? `Won: ${won} ${unit}, ${runCount(s.wins)}` : null,
    ].filter(Boolean).join("\n");
    return `<div class="fl-lane" data-tip="${tip}">` +
      `<span class="fl-band" style="left:${lo}%;width:${(hi - lo).toFixed(1)}%;background:${color};opacity:0.4"></span>` +
      (lost != null ? `<span class="fl-dot" style="left:${pos(lost)}%;background:var(--panel);box-shadow:inset 0 0 0 2px ${color}"></span>` : "") +
      (won  != null ? `<span class="fl-dot" style="left:${pos(won)}%;background:${color}"></span>` : "") +
      `<span class="fl-value" style="left:calc(${hi}% + 10px)">${lost ?? "—"} · ${won ?? "—"}</span></div>`;
  };
  const axis = max => `<div class="fl-lane fl-axis">${
    [0, 0.25, 0.5, 0.75, 1].map(f => `<span style="left:${f * 100}%">${max * f}</span>`).join("")}</div>`;
  const cardsMax  = scale("median_win_cards",  "median_loss_cards");
  const relicsMax = scale("median_win_relics", "median_loss_relics");

  let html = `<div class="fl-legend"><i class="re-ring"></i>runs lost<i class="re-dot"></i>runs won</div>` +
    `<div class="re-rows"><span></span><div class="fl-section">Cards</div><div class="fl-section">Relics</div>`;
  stats.forEach(([char, s]) => {
    const color = CHAR_COLOR_MAP[char] || "#a0a0b8";
    html += `<div style="color:${color};font-weight:600">${fmtCharName(char)}</div>` +
      lane(s, color, "median_win_cards",  "median_loss_cards",  cardsMax,  "cards") +
      lane(s, color, "median_win_relics", "median_loss_relics", relicsMax, "relics");
  });
  document.getElementById("run-end-lanes").innerHTML = html + `<span></span>${axis(cardsMax)}${axis(relicsMax)}</div>`;
}
