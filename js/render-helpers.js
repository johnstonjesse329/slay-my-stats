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
    { label: "Win %", value: winPct },
    // The character is the point of this card, so it sits in the label where a
    // phone can see it, in their colour, with the win/loss counts after it.
    { label: "Best win %",
      what: charStats[bestIdx].win_pct !== null ? fmtCharName(chars[bestIdx]) : "",
      whatColor: CHAR_COLOR_MAP[chars[bestIdx]],
      detail: charStats[bestIdx].win_pct !== null ? `${charStats[bestIdx].wins}W / ${charStats[bestIdx].losses}L` : "No wins",
      value: charStats[bestIdx].win_pct !== null ? charStats[bestIdx].win_pct + "%" : "—" },
    // The share of runs is what makes this card mean anything, so it is in the
    // label. The run count is the Runs card's value and is not repeated.
    { label: "Most played", detail: grand.runs ? `${mostPlayedPct}% of runs` : "", value: fmtCharName(chars[mostIdx]) },
    { label: "Gold gained", detail: grand.runs ? `Median ${grand.median_gold.toLocaleString()}` : "",
      value: grand.runs ? grand.total_gold.toLocaleString() : "—" },
    // Elites and bosses are a card each. The row stays at 8 cards, which
    // divides evenly into 4 + 4 instead of leaving a ragged edge.
    { label: "Elites defeated", value: grand.runs ? grand.total_elites_defeated.toLocaleString() : "—" },
    { label: "Bosses defeated", value: grand.runs ? grand.total_bosses_defeated.toLocaleString() : "—" },
  ];

  // A filtered number must not read as a lifetime one, so the active mode is
  // in the label where a phone sees it.
  const scopeName = sharedActiveMode !== "all"
    ? ({ solo: "Solo", multi: "Multiplayer", daily: "Daily" }[sharedActiveMode] || sharedActiveMode)
    : "";
  // One card builder, three weights: `label` is what the stat is (bold), `what`
  // is who or what it is about (bold, in a character's colour), `detail` is the
  // figure behind the value (dim). Everything is on the card, nothing on hover.
  const itemCard = ({ label, what, whatColor, detail, value }) =>
    `<div class="card">
      <div class="label"><b class="name">${label}</b>${what ? ` <b class="what"${whatColor ? ` style="color:${whatColor}"` : ""}>${what}</b>` : ""}${detail ? ` <span class="detail">${detail}</span>` : ""}</div>
      <div class="value">${value}</div>
    </div>`;
  const runsCard = itemCard({ label: scopeName ? `${scopeName} runs` : "Runs",
    detail: `${grand.wins} win${grand.wins === 1 ? "" : "s"}`, value: grand.runs });
  const timeCard = itemCard({ label: "Time played", detail: grand.runs ? `Median ${grand.median_min}m` : "",
    value: grand.runs ? fmtHrsMin(grand.total_min) : "—" });

  // Win % first, totals last.
  document.getElementById("summary-cards").innerHTML =
    items.slice(0, 3).map(itemCard).join("") + timeCard + runsCard + items.slice(3).map(itemCard).join("");
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


  // Every stat is one line on the same four columns (label | low | separator |
  // high), see .pb-row in dashboard.css, so the numbers, dots and dashes sit at
  // one x on every row and every card. A single value spans the number columns
  // and ends on the same right edge.
  const row = (label, valueHtml) =>
    `<div class="pb-row"><span class="pb-label">${label}</span><span class="pb-val">${valueHtml}</span></div>`;
  const pairRow = (label, lo, sep, hi) =>
    `<div class="pb-row"><span class="pb-label">${label}</span><span class="pb-lo">${lo}</span><span class="pb-sep">${sep}</span><span class="pb-hi">${hi}</span></div>`;

  // A value that links to the specific run that produced it (best is
  // { value, ts } or null — see the tracking above).
  const link = (best, fmt = v => v) => best
    ? `<span class="pb-stat-link" data-ts="${best.ts}" data-tip="Jump to this run">${fmt(best.value)}</span>`
    : "—";

  // Fewest–most as one row; each end still links to its own run.
  const rangeRow = (label, lo, hi, fmt) => !lo || !hi ? row(label, "—")
    : lo.value === hi.value ? row(label, link(lo, fmt))
    : pairRow(label, link(lo, fmt), "", link(hi, fmt));

  const heading = (title, lo, hi) =>
    `<div class="pb-head"><span>${title}</span><span class="pb-lo">${lo}</span><span class="pb-hi">${hi}</span></div>`;

  // Favourites: a head line per list with its column names, then one row per
  // item (favoriteItemHtml).
  const favHead = (title, countHead) =>
    `<div class="pb-fav-head"><span class="pb-fav-title">${title}</span><span>${countHead}</span><span>Win</span></div>`;

  const favorites = aggregateCharFavorites();

  document.getElementById("personal-bests-cards").innerHTML = chars.map(char => {
    const b = bests[char];
    const color = CHAR_COLOR_MAP[char] || "#a0a0b8";
    const label = fmtCharName(char);
    const noRuns = b.fastestWin === null;
    // Deaths read as a count plus a share of every run this character has, so
    // "died 3 times" has a scale next to it.
    const deaths = (label, n) => b.gamesPlayed
      ? pairRow(label, n, "", `${Math.round(n / b.gamesPlayed * 100)}%`)
      : row(label, "—");
    const fav = favorites[char];

    return `<div class="card pb-card" style="border-top:2px solid ${color}">
      <div class="pb-char" style="color:${color}">${label}</div>
      ${row("Runs", b.gamesPlayed || "—")}
      ${b.gamesPlayed
        ? pairRow("Wins", b.totalWins, "", `${Math.round(b.totalWins / b.gamesPlayed * 100)}%`)
        : row("Wins", "—")}
      ${deaths("Final boss deaths", b.finalBossDeaths)}
      ${deaths("Elite deaths", b.eliteDeaths)}
      ${noRuns
        ? `<div class="pb-none">No wins yet</div>`
        : `${row("Current win streak", b.currentStreak || 0)}
          ${row("Best win streak", b.longestStreak)}
          ${row("Fastest win", link(b.fastestWin, fmtHrsMinSec))}
          ${heading("Winning runs", "lowest", "highest")}
          ${rangeRow("Elites", b.fewestElites, b.mostElitesWin)}
          ${rangeRow("Cards", b.fewestCards, b.mostCards)}
          ${rangeRow("Relics", b.fewestRelics, b.mostRelics)}
          ${rangeRow("Max HP", b.fewestMaxHp, b.mostMaxHp)}
          ${rangeRow("Final boss turns", b.fewestFinalBossTurns, b.mostFinalBossTurns)}
          ${favHead("Most picked", "Picks")}
          ${favoriteItemHtml("card",  fav.card.mostPicked,     "Card",  "count")}
          ${favoriteItemHtml("card",  fav.rareCard.mostPicked, "Rare",  "count")}
          ${favoriteItemHtml("relic", fav.relic.mostPicked,    "Relic", "count")}
          ${favHead("Best win %", "Picks")}
          ${favoriteItemHtml("card",  fav.card.bestWinRate,     "Card",  "win")}
          ${favoriteItemHtml("card",  fav.rareCard.bestWinRate, "Rare",  "win")}
          ${favoriteItemHtml("relic", fav.relic.bestWinRate,    "Relic", "win")}
          ${favHead("Most bought", "Buys")}
          ${favoriteItemHtml("card",  fav.shopCard.mostPicked,  "Card",  "count", "bought")}
          ${favoriteItemHtml("relic", fav.shopRelic.mostPicked, "Relic", "count", "bought")}`
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
// the earlier ones were beaten too. The rung they're on now is outlined.
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
    const pips = ASC_TRACKER_LEVELS.map(level => {
      return `<span class="asc-pip" data-tip="A${level}" style="--rung:${level}${won >= level ? `;background:${color}` : ""}"></span>`;
    }).join("");
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

// One favourite as a one-line row on the character card's fixed columns:
// tag | picture | name | count | win %. emph ("count" | "win") brightens the
// number the item was chosen for. A long name is cut with an ellipsis (the
// hover/tap tooltip this row has shows the whole thing), so every row is one
// line and the count and win % land in the same column on every card. An empty
// slot keeps the row's footprint so the cards stay the same height.
function favoriteItemHtml(kind, item, tag, emph = null, noun = "picked") {
  const tagHtml = `<span class="fav-tag">${tag}</span>`;
  if (!item) return `<div class="fav-item fav-empty">
    ${tagHtml}<span class="fav-icon"><span class="fav-none"></span></span>
    <span class="fav-name">None yet</span><span class="fav-num">—</span><span class="fav-num">—</span>
  </div>`;
  const label = kind === "card" ? fmtCardLabel(item.id) : fmtRelicLabel(item.id);
  const winText = item.winPct != null ? `${item.winPct}%` : "—";
  const imgHtml = src => src
    ? `<img loading="lazy" src="${thumbSrc(src)}" alt="${label}" style="width:22px;height:22px;object-fit:contain;border-radius:4px">`
    : "";
  // Same real card face / relic art used everywhere else, at icon size, with
  // the same rich hover tooltip.
  let thumbHtml, tooltipHtml, tooltipClass;
  if (kind === "card") {
    thumbHtml = cardFaceAvailable()
      ? `<div class="fav-item-face">${renderCardFace(item.id, 0, 26, { thumb: true, props: item.props })}</div>`
      : imgHtml(cardImgSrc(item.id));
    tooltipHtml = buildCardTooltip(item.id, 0, item.props, item.enchantment);
    tooltipClass = "card-tooltip-wrap";
  } else {
    thumbHtml = imgHtml(relicImgSrc(item.id));
    tooltipHtml = buildRelicTooltip(item.id);
    tooltipClass = "relic-tooltip-wrap";
  }
  const num = (text, on) => `<span class="fav-num${on ? " fav-emph" : ""}">${text}</span>`;

  return `<div class="fav-item" tabindex="0" role="img" aria-label="${label} — ${item.picked} ${noun}, ${winText} win">
    ${tagHtml}<span class="fav-icon">${thumbHtml}</span>
    <span class="fav-name">${label}</span>${num(item.picked, emph === "count")}${num(winText, emph === "win")}
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
    <th class="all-col" style="border-left:2px solid #3f4147">All<br>ascensions</th>
  </tr></thead><tbody>`;

  chars.forEach(char => {
    html += `<tr>${charNameCell(char)}`;
    ascs.forEach(col => { html += winCell(pivotData[char]?.[col.key], false); });
    html += winCell(pivotData[char]?.["ALL"], true);
    html += `</tr>`;
  });

  html += `<tr class="total-row">
    <td class="char-name" style="color:#e0c468">All characters</td>`;
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
    <th class="all-col" style="border-left:2px solid #3f4147">All<br>ascensions</th>
  </tr></thead><tbody>`;

  chars.forEach(char => {
    html += `<tr>${charNameCell(char)}`;
    cols.forEach(c => { html += finalBossWinCell(pivotData[char]?.[c.key], false); });
    html += finalBossWinCell(pivotData[char]?.["ALL"], true);
    html += `</tr>`;
  });

  html += `<tr class="total-row">
    <td class="char-name" style="color:#e0c468">All characters</td>`;
  cols.forEach(c => { html += finalBossWinCell(pivotData["ALL"]?.[c.key], false); });
  html += finalBossWinCell(pivotData["ALL"]?.["ALL"], true);
  html += `</tr></tbody>`;

  document.getElementById("final-boss-win-table").innerHTML = html;
}

function valCell(bucket, valueKey, color, isAll) {
  const cls = "cell" + (isAll ? " all-col" : "");
  if (!bucket || !bucket.runs) return `<td class="${cls} empty">—</td>`;
  return `<td class="${cls}">
    <div style="font-size:var(--fs-md);font-weight:700;color:${color}">${bucket[valueKey]}</div>
  </td>`;
}

// ---- Character lanes (Overview): Time Played, Cards & Relics ----
//
// A row per character in its colour, two lanes side by side, each with its
// own scale rounded up to a multiple of 20 so the quarter ticks are whole.

const runCount = n => `${n} run${n !== 1 ? "s" : ""}`;
const laneMax = vals => Math.max(20, Math.ceil(Math.max(0, ...vals.filter(v => v != null)) / 20) * 20);
const charLaneAxis = (max, fmt = v => v) => `<div class="fl-lane fl-axis">${
  [0, 0.25, 0.5, 0.75, 1].map(f => `<span style="left:${f * 100}%">${fmt(max * f)}</span>`).join("")}</div>`;

// A ring at the median in runs lost, a dot at the median in runs won, and a
// band between. fmt formats a value for the label and the tooltip.
function lostWonLane(s, color, lost, won, max, fmt) {
  const pos = v => +(v / max * 100).toFixed(1);
  const pts = [won, lost].filter(v => v != null);
  if (!pts.length) return `<div class="fl-lane"></div>`;
  const lo = pos(Math.min(...pts)), hi = pos(Math.max(...pts));
  const tip = [
    lost != null ? `Lost: ${fmt(lost)}, ${runCount(s.losses)}` : null,
    won  != null ? `Won: ${fmt(won)}, ${runCount(s.wins)}` : null,
  ].filter(Boolean).join("\n");
  return `<div class="fl-lane" data-tip="${tip}">` +
    `<span class="fl-band" style="left:${lo}%;width:${(hi - lo).toFixed(1)}%;background:${color}"></span>` +
    (lost != null ? `<span class="fl-dot" style="left:${pos(lost)}%;background:var(--panel);box-shadow:inset 0 0 0 2px ${color}"></span>` : "") +
    (won  != null ? `<span class="fl-dot" style="left:${pos(won)}%;background:${color}"></span>` : "") +
    `<span class="fl-value" style="left:calc(${hi}% + 10px)">${lost != null ? fmt(lost) : "—"} · ${won != null ? fmt(won) : "—"}</span></div>`;
}

const LOST_WON_KEY = `<i class="re-ring"></i>runs lost<i class="re-dot"></i>runs won`;
const LOST_WON_LEGEND = `<div class="fl-legend">${LOST_WON_KEY}</div>`;

// headers: the two lane titles; lanes(s, color): the two lanes of a row;
// axes: the two axis rows; legend: shown above both lanes, for a section
// where the ring and dot are in both.
function renderCharLanes(elId, pivotData, headers, lanes, axes, legend = "") {
  const stats = DATA.characters.map(char => [char, pivotData[char]?.["ALL"]]).filter(([, s]) => s && s.runs);
  let html = `${legend}<div class="re-rows"><span></span>${headers.map(h => `<div class="fl-section">${h}</div>`).join("")}`;
  stats.forEach(([char, s]) => {
    const color = CHAR_COLOR_MAP[char] || "#a0a0b8";
    html += `<div style="color:${color};font-weight:600">${fmtCharName(char)}</div>${lanes(s, color).join("")}`;
  });
  document.getElementById(elId).innerHTML = html + `<span></span>${axes.join("")}</div>`;
}

const charAllStats = pivotData => DATA.characters.map(char => pivotData[char]?.["ALL"]).filter(s => s && s.runs);

// Time Played: a bar of hours on the character with its share of the total,
// beside the median run length in runs lost and runs won. The ring and dot
// are only in the run length lane, so its header carries the key.
function renderTimeLanes(pivotData) {
  const stats = charAllStats(pivotData);
  const totalHrs = stats.reduce((sum, s) => sum + (s.total_hrs ?? 0), 0);
  const hrsMax = laneMax(stats.map(s => s.total_hrs));
  const minMax = laneMax(stats.flatMap(s => [s.median_win_min, s.median_loss_min]));
  const hoursLane = (s, color) => {
    const hrs = s.total_hrs ?? 0;
    const share = totalHrs > 0 ? (hrs / totalHrs * 100).toFixed(1) : "0.0";
    const width = +(hrs / hrsMax * 100).toFixed(1);
    return `<div class="fl-lane" data-tip="${hrs}h, ${share}% of time played\n${runCount(s.runs)} (${s.wins}W / ${s.losses}L)">` +
      `<span class="fl-fill" style="width:${width}%;background:${color}"></span>` +
      `<span class="fl-value" style="left:calc(${width}% + 8px)">${hrs}h · ${Math.round(share)}%</span></div>`;
  };
  renderCharLanes("time-lanes", pivotData, ["Hours", `Median run length<span class="fl-legend">${LOST_WON_KEY}</span>`],
    (s, color) => [hoursLane(s, color), lostWonLane(s, color, s.median_loss_min, s.median_win_min, minMax, fmtHrsMin)],
    [charLaneAxis(hrsMax, v => `${v}h`), charLaneAxis(minMax, v => `${v}m`)]);
}

// Cards & Relics: median cards beside median relics.
function renderRunEndLanes(pivotData) {
  const stats = charAllStats(pivotData);
  const cardsMax  = laneMax(stats.flatMap(s => [s.median_win_cards,  s.median_loss_cards]));
  const relicsMax = laneMax(stats.flatMap(s => [s.median_win_relics, s.median_loss_relics]));
  renderCharLanes("run-end-lanes", pivotData, ["Cards", "Relics"],
    (s, color) => [
      lostWonLane(s, color, s.median_loss_cards,  s.median_win_cards,  cardsMax,  v => `${v}`),
      lostWonLane(s, color, s.median_loss_relics, s.median_win_relics, relicsMax, v => `${v}`),
    ],
    [charLaneAxis(cardsMax), charLaneAxis(relicsMax)], LOST_WON_LEGEND);
}
