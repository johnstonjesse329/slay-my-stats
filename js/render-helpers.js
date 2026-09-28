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
  // A high win % from a handful of runs shouldn't read with the same
  // authority as one backed by hundreds — mute it and say why.
  const bestRuns = charStats[bestIdx].runs;
  const smallSample = bestRuns > 0 && bestRuns < 15;
  const items = [
    { label: "Overall Win Rate", value: winPct,
      // Win/run counts already sit on the Runs card — a blank sub keeps the
      // card's line-height without repeating them here.
      sub: "&nbsp;" },
    { label: "Best Win Rate", value: charStats[bestIdx].win_pct !== null ? charStats[bestIdx].win_pct + "%" : "—",
      sub: charStats[bestIdx].win_pct !== null ? `${fmtCharName(chars[bestIdx])} · ${charStats[bestIdx].wins}W / ${charStats[bestIdx].runs}L` : "No wins",
      muted: smallSample,
      tag: smallSample ? "small sample" : "",
      title: smallSample ? `Based on only ${bestRuns} run${bestRuns !== 1 ? "s" : ""} — win rates under 15 runs are statistically noisy` : "" },
    { label: "Most Played",    value: fmtCharName(chars[mostIdx]),
      // Run count is the Runs card's value — show only the share here.
      sub: `${mostPlayedPct}% of all runs` },
    { label: "Median Floor",   value: grand.median_floor !== null ? grand.median_floor : "—", sub: "All runs" },
    { label: "Median Win Time", value: grand.median_win_min !== null ? grand.median_win_min + "m" : "—", sub: grand.median_min !== null ? `${grand.median_min}m across all runs` : "No wins" },
    { label: "Total Gold Gained", value: grand.runs ? grand.total_gold.toLocaleString() : "—",
      sub: grand.runs ? `median ${grand.median_gold.toLocaleString()} per run` : "" },
    { label: "Elites/Bosses Defeated", value: grand.runs ? grand.total_elites_defeated + grand.total_bosses_defeated : "—",
      sub: grand.runs ? `${grand.total_elites_defeated} elites · ${grand.total_bosses_defeated} bosses` : "" },
  ];

  const modeTag = sharedActiveMode !== "all"
    ? `<div class="card-scope-tag">${{ solo: "Solo", multi: "Multiplayer", daily: "Daily" }[sharedActiveMode] || sharedActiveMode} runs only</div>`
    : "";
  const runsCard = `<div class="card">
    <div class="label">Runs</div>
    <div class="value">${grand.runs}</div>
    <div class="sub">${grand.wins} wins</div>
    ${modeTag}
  </div>`;

  // Leads the row — total time invested is one of the most immediately
  // relevant stats, ahead of even the Runs count.
  const timeCard = `<div class="card">
    <div class="label">Total Time Played</div>
    <div class="value">${grand.runs ? fmtHrsMin(grand.total_min) : "—"}</div>
    <div class="sub">${grand.runs ? `median ${grand.median_min}m per run` : ""}</div>
  </div>`;

  document.getElementById("summary-cards").innerHTML = timeCard + runsCard + items.map(card =>
    `<div class="card"${card.title ? ` data-tip="${card.title}"` : ""}>
      <div class="label">${card.label}</div>
      <div class="value"${card.muted ? ` style="color:#8a8aa0"` : ""}>${card.value}</div>
      <div class="sub">${card.sub}</div>
      ${card.tag ? `<div class="card-scope-tag">⚠ ${card.tag}</div>` : ""}
    </div>`
  ).join("");
}

function renderPersonalBests() {
  const chars = DATA.characters;
  const allRuns = [...filterRuns()].sort((a, b) => a.ts - b.ts);

  const bests = {};
  chars.forEach(char => {
    bests[char] = { gamesPlayed: 0, totalWins: 0, finalBossDeaths: 0, currentStreak: 0, longestStreak: 0, _streak: 0, fastestWin: null, mostElites: null, fewestElites: null, mostElitesWin: null, mostCards: null, fewestCards: null, mostRelics: null, fewestRelics: null, mostMaxHp: null, fewestMaxHp: null, mostFinalBossTurns: null, fewestFinalBossTurns: null, highestWinAsc: null };
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
      // Highest ascension this character has ever won at. Ties keep the
      // earliest such run (strict >), so the link points at the first time
      // that ceiling was reached rather than the most recent repeat of it.
      if (run.asc != null && (b.highestWinAsc === null || run.asc > b.highestWinAsc.value))
        b.highestWinAsc = { value: run.asc, ts: run.ts };
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
    if (b.mostElites === null || elites > b.mostElites.value) b.mostElites = { value: elites, ts: run.ts };
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
    const fav = favorites[char];

    return `<div class="card" style="border-color:${color}55;box-sizing:border-box">
      <div style="font-size:0.75rem;font-weight:700;color:${color};letter-spacing:.04em;margin-bottom:0.35rem">${label.toUpperCase()}</div>
      ${row("Runs", b.gamesPlayed || "—")}
      ${row("Wins", b.gamesPlayed
        ? `${b.totalWins}<span style="color:#8a8aa0;font-weight:400"> · </span>${Math.round(b.totalWins / b.gamesPlayed * 100)}%`
        : "—")}
      ${row("Highest Asc", link(b.highestWinAsc, v => `A${v}`))}
      ${row("Final boss deaths", b.finalBossDeaths || "—")}
      ${noRuns
        ? `<div style="color:#8a8aa0;font-size:0.8rem;padding:0.25rem 0">No wins yet</div>`
        : `${row("Current win streak", b.currentStreak || 0)}
          ${row("Best win streak", b.longestStreak)}
          ${row("Fastest win", link(b.fastestWin, fmtHrsMinSec))}
          ${row("Most elites", link(b.mostElites))}
          ${heading("Winning runs", "fewest – most")}
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

// Aggregates offer/pick/win data per character for cards and relics.
// Respects shared filters. Returns, per character:
// mostPicked (highest pick count) and bestWinRate (highest win % overall,
// flagged lowSample if under MIN_PICKS so the UI can flag it with an "N"
// badge) — both for cards and relics.
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
      // Prefer items meeting MIN_PICKS; only fall back to a below-threshold
      // item (flagged lowSample) if nothing clears the bar. Otherwise a
      // single 100%-win pick would always beat a well-sampled 80%-win item.
      let bestQualified = null, bestAny = null;
      entries.forEach(([id, b]) => {
        const winPct = +(b.won / b.picked * 100).toFixed(0);
        if (!mostPicked || b.picked > mostPicked.picked) mostPicked = { id, picked: b.picked, winPct };
        const candidate = { id, winPct, picked: b.picked };
        if (!bestAny || winPct > bestAny.winPct) bestAny = candidate;
        if (b.picked >= MIN_PICKS && (!bestQualified || winPct > bestQualified.winPct)) bestQualified = candidate;
      });
      const bestWinRate = bestQualified || bestAny;
      if (bestWinRate) bestWinRate.lowSample = bestWinRate.picked < MIN_PICKS;
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
  const pieces = (emph === "win" ? [winText, countText] : [countText, winText]).filter(Boolean);
  const sub = pieces.join(" · ");
  const plainSub = sub.replace(/<[^>]+>/g, "");
  // A below-threshold (lowSample) pick used to fade the whole row to 55%
  // opacity, which read as disabled/broken next to fully-inked neighbors in
  // the character panes. Drop the dim and keep the small "N" badge as the
  // honest low-sample signal instead.
  const lowSampleBadge = item.lowSample
    ? `<span data-tip="Low sample size" style="flex:0 0 auto;font-size:0.68rem;font-weight:700;color:#a8a2c4;border:1px solid #4f5158;border-radius:3px;padding:0 3px;line-height:1.3">N</span>`
    : "";

  // Same real card face / relic art used everywhere else, at icon size, with
  // the same rich hover tooltip -- this row used to show a bare cropped
  // portrait with no hover at all, which read as inconsistent next to every
  // other card/relic thumbnail in the dashboard.
  let thumbHtml, tooltipHtml, tooltipClass;
  if (kind === "card") {
    thumbHtml = cardFaceAvailable()
      ? `<div class="fav-item-face">${renderCardFace(item.id, 0, 26)}</div>`
      : (() => {
          const src = cardImgSrc(item.id);
          return src ? `<img loading="lazy" src="${src}" alt="${label}" style="width:22px;height:22px;object-fit:contain;border-radius:4px;flex:0 0 auto">` : "";
        })();
    tooltipHtml = buildCardTooltip(item.id, 0);
    tooltipClass = "card-tooltip-wrap";
  } else {
    const src = relicImgSrc(item.id);
    thumbHtml = src
      ? `<img loading="lazy" src="${src}" alt="${label}" style="width:22px;height:22px;object-fit:contain;border-radius:4px;flex:0 0 auto">`
      : "";
    tooltipHtml = buildRelicTooltip(item.id);
    tooltipClass = "relic-tooltip-wrap";
  }

  return `<div class="fav-item" tabindex="0" role="img" aria-label="${label} — ${plainSub}" style="display:flex;align-items:${column ? "flex-start" : "center"};gap:0.4rem;min-width:0">
    ${thumbHtml}
    ${column
      ? `<div style="min-width:0">
      <div style="font-size:0.76rem;color:#ccc;line-height:1.2;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere" lang="en">${label}</div>
      <div style="font-size:0.7rem;color:#a0a0b8;display:flex;flex-wrap:wrap;align-items:center;column-gap:0.3rem;line-height:1.35">
        ${pieces.map(p => `<span style="white-space:nowrap">${p}</span>`).join("")}${lowSampleBadge}
      </div>
    </div>`
      : `<div style="overflow:hidden;min-width:0">
      <div style="font-size:0.78rem;color:#ccc;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${label}</div>
      <div style="font-size:0.72rem;color:#a0a0b8;display:flex;align-items:center;gap:0.25rem;min-width:0">
        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0">${sub}</span>${lowSampleBadge}
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
// bgTiers/colorTiers are each [highCutoff, midCutoff] (bg has an extra
// [lowCutoff] step) — pass overrides for a cell whose scale reads
// differently (e.g. fightWinCell's individual-fight thresholds).
function winPctStyle(pct, bgTiers = [50, 30, 15], colorTiers = [40, 20]) {
  const bg = pct >= bgTiers[0] ? "rgba(92,186,125,0.28)"
           : pct >= bgTiers[1] ? "rgba(92,186,125,0.14)"
           : pct >= bgTiers[2] ? "rgba(232,169,48,0.22)"
           :                     "rgba(224,92,92,0.22)";
  const color = pct >= colorTiers[0] ? "#5cba7d"
              : pct >= colorTiers[1] ? "#e8a930"
              :                        "#e05c5c";
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

function rangeCell(bucket, minKey, maxKey, color) {
  if (!bucket || bucket[minKey] == null) return `<td class="cell all-col empty">—</td>`;
  const same  = bucket[minKey] === bucket[maxKey];
  const range = same ? bucket[minKey] : `${bucket[minKey]}–${bucket[maxKey]}`;
  return `<td class="cell all-col">
    <div style="font-size:0.82rem;font-weight:600;color:${color}">${range}</div>
  </td>`;
}

// One Won / Lost median pair for Cards/Relics/Elites at Run End. The Won
// cell carries the fewest–most in a win underneath (the ranges only cover
// wins, so they sit under the column that says so).
function winLossPairCells(bucket, winKey, lossKey, minKey, maxKey, border, isAll) {
  const cls = "cell" + (isAll ? " all-col" : "");
  const first = `border-left:${border} solid #3f4147;`;
  const cell = (v, isLoss, style, meta = "") => v == null
    ? `<td class="${cls} empty" style="${style}">—</td>`
    : `<td class="${cls}" style="${style}font-size:0.88rem;color:${isLoss ? "#e05c5c" : "#5cba7d"};${isLoss ? "" : "font-weight:600"}">${v}${meta}</td>`;
  const lo = minKey ? bucket?.[minKey] : null, hi = maxKey ? bucket?.[maxKey] : null;
  const range = lo != null && lo !== hi ? `<div class="meta">${lo}–${hi}</div>` : "";
  return cell(bucket?.[winKey], false, first, range) + cell(bucket?.[lossKey], true, "");
}

function renderDeckPivot(tableId, pivotData, valueKey, winKey, lossKey, minKey, maxKey, color, showRange = true) {
  const chars = DATA.characters;
  const ascs  = ascColumns();

  // Same two-row Won / Lost header as Rest Site Choices, so each cell holds
  // one number instead of a "W / L" pair the reader has to decode.
  const thSub  = `font-size:0.72rem;color:#8a8aa0;font-weight:400;text-align:center`;
  const groups = [...ascs.map(col => ({ key: col.key, label: col.label, border: "1px" })), { key: "ALL", label: "All<br>columns", border: "2px", all: true }];
  let html = `<thead><tr>
    <th class="char-head" rowspan="2">Character</th>
    ${groups.map(g => `<th colspan="2" class="${g.all ? "all-col" : ""}" style="border-left:${g.border} solid #3f4147;text-align:center">${g.label}</th>`).join("")}
  </tr><tr>
    ${groups.map(g => `<th class="${g.all ? "all-col" : ""}" style="${thSub};border-left:${g.border} solid #3f4147">Won</th><th class="${g.all ? "all-col" : ""}" style="${thSub}">Lost</th>`).join("")}
  </tr></thead><tbody>`;

  const rowCells = (byCol) => groups.map(g =>
    winLossPairCells(byCol?.[g.key], winKey, lossKey, showRange ? minKey : null, maxKey, g.border, g.all)).join("");

  chars.forEach(char => {
    html += `<tr>${charNameCell(char)}${rowCells(pivotData[char])}</tr>`;
  });

  html += `<tr class="total-row"><td class="char-name" style="color:#e0c468">All Characters</td>${rowCells(pivotData["ALL"])}</tr></tbody>`;

  document.getElementById(tableId).innerHTML = html;
}


