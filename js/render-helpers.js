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
  // Runs, wins and the per-character split are the character table's; the
  // bars keep the totals it has no row for.
  const items = [
    { label: "Time played", detail: grand.runs ? `Median ${grand.median_min}m` : "",
      value: grand.runs ? fmtHrsMin(grand.total_min) : "—" },
    { label: "Gold gained", detail: grand.runs ? `Median ${grand.median_gold.toLocaleString()}` : "",
      value: grand.runs ? grand.total_gold.toLocaleString() : "—" },
    { label: "Elites defeated", value: grand.runs ? grand.total_elites_defeated.toLocaleString() : "—" },
    { label: "Bosses defeated", value: grand.runs ? grand.total_bosses_defeated.toLocaleString() : "—" },
  ];
  // `label` is what the stat is, then the value. `detail`, the figure behind
  // the value, is its tooltip, so nothing sits between a stat's name and its
  // number.
  const itemCard = ({ label, detail, value }) =>
    `<div class="card">
      <div class="label"><b class="name">${label}</b></div>
      <div class="value"${detail ? ` data-tip="${detail}" tabindex="0"` : ""}>${value}</div>
    </div>`;
  document.getElementById("summary-cards").innerHTML = items.map(itemCard).join("");
}

function renderPersonalBests() {
  const chars = DATA.characters;
  const allRuns = [...filterRuns()].sort((a, b) => a.ts - b.ts);

  const fresh = () => ({ gamesPlayed: 0, totalWins: 0, finalBossDeaths: 0, eliteDeaths: 0, currentStreak: 0, longestStreak: 0, _streak: 0, fastestWin: null, fewestElites: null, mostElitesWin: null, mostCards: null, fewestCards: null, mostRelics: null, fewestRelics: null, mostMaxHp: null, fewestMaxHp: null, mostFinalBossTurns: null, fewestFinalBossTurns: null, tiers: {} });
  const bests = {};
  chars.forEach(char => { bests[char] = fresh(); });
  // The Total column is the same tally over every run, so its streaks run
  // across characters in play order and its ranges span all of them.
  const total = fresh();

  const tally = (b, run) => {
    b.gamesPlayed = (b.gamesPlayed || 0) + 1;
    const tier = b.tiers[ascColumnKey(run.asc)] ||= { runs: 0, wins: 0 };
    tier.runs++;
    if (run.won) tier.wins++;
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
  };
  allRuns.forEach(run => {
    if (!bests[run.char]) return;
    tally(bests[run.char], run);
    tally(total, run);
  });
  [...chars.map(char => bests[char]), total].forEach(b => { b.currentStreak = b._streak; });


  // One table: a row per stat, a column per character with runs under the
  // filters, so the same stat reads straight across the characters.
  const shown = chars.filter(char => bests[char].gamesPlayed);
  // A column per character, then the total when there's more than one. The
  // header is the character's energy icon and name; a phone keeps the icon.
  const icons = DATA.energyIcons || {};
  const cols = shown.map(char => ({ name: fmtCharName(char), color: CHAR_COLOR_MAP[char] || "#a0a0b8", b: bests[char], icon: icons[char.toLowerCase()] }));
  if (shown.length > 1) cols.push({ name: "Total", color: "var(--text)", bar: "#c8c4dc", b: total, total: true });

  // A value that links to the specific run that produced it (best is
  // { value, ts } or null — see the tracking above).
  const link = (best, fmt = v => v) => best
    ? `<span class="pb-stat-link" data-ts="${best.ts}" data-tip="Jump to this run">${fmt(best.value)}</span>`
    : "—";
  // Fewest–most in one cell; each end still links to its own run.
  const range = (lo, hi, fmt) => !lo || !hi ? "—"
    : lo.value === hi.value ? link(lo, fmt)
    : `${link(lo, fmt)}<span class="pb-sep">–</span>${link(hi, fmt)}`;
  // One figure per cell: a share of runs, the counts behind it on hover.
  const pct = (n, d) => !d ? "—"
    : `<span data-tip="${n} of ${d} run${d !== 1 ? "s" : ""}">${Math.round(n / d * 100)}%</span>`;
  // A tier's win rate over a thin bar in the character's colour.
  const tierBar = (t, c) => !t ? "—"
    : `${pct(t.wins, t.runs)}<span class="pb-bar"><i style="width:${Math.round(t.wins / t.runs * 100)}%;background:${c.bar || c.color}"></i></span>`;

  // [label, cell, row class]
  const rows = [
    ["Win %", (b, c) => `<span style="color:${c.color}">${pct(b.totalWins, b.gamesPlayed)}</span>`, "pb-headline"],
    // The ascension tiers the other tables split by (ascColumns).
    ...ascColumns().map(col => [col.label, (b, c) => tierBar(b.tiers[col.key], c), "pb-tier"]),
    ["Runs",              b => b.gamesPlayed],
    ["Final boss deaths", b => pct(b.finalBossDeaths, b.gamesPlayed)],
    ["Elite deaths",      b => pct(b.eliteDeaths, b.gamesPlayed)],
    ["Current win streak", b => b.currentStreak],
    ["Best win streak",   b => b.longestStreak],
    ["Fastest win",       b => link(b.fastestWin, fmtHrsMin)],
    "Winning runs",
    ["Elites",            b => range(b.fewestElites, b.mostElitesWin)],
    ["Cards",             b => range(b.fewestCards, b.mostCards)],
    ["Relics",            b => range(b.fewestRelics, b.mostRelics)],
    ["Max HP",            b => range(b.fewestMaxHp, b.mostMaxHp)],
    ["Final boss turns",  b => range(b.fewestFinalBossTurns, b.mostFinalBossTurns)],
  ];

  document.getElementById("personal-bests-cards").innerHTML = !shown.length ? "" :
    `<table class="pb-table">
      <thead><tr><th></th>${cols.map(c =>
        `<th${c.total ? ` class="pb-total"` : ""} style="color:${c.color}">${c.icon
          ? `<img class="pb-char-icon" src="${c.icon}" alt="${c.name}" data-tip="${c.name}"><span class="pb-char-name">${c.name}</span>`
          : c.name}</th>`).join("")}</tr></thead>
      <tbody>${rows.map(r => typeof r === "string"
        ? `<tr class="pb-group"><th colspan="${cols.length + 1}">${r}</th></tr>`
        : `<tr${r[2] ? ` class="${r[2]}"` : ""}><th>${r[0]}</th>${cols.map(c => `<td${c.total ? ` class="pb-total"` : ""}>${r[1](c.b, c)}</td>`).join("")}</tr>`).join("")}
      </tbody>
    </table>`;

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
      : "—"}</b>first A${maxAsc} win${first ? ` · ${charIconHtml(first.char)}${fmtCharName(first.char)}` : ""}</div>`;

  const el = document.getElementById("asc-tracker-cards");
  el.innerHTML = DATA.characters.map(char => {
    const color = CHAR_COLOR_MAP[char] || "#a0a0b8";
    return `<div class="asc-card" style="border-top-color:${color}">
      <div class="asc-name">${charIconHtml(char)}${fmtCharName(char)}</div>
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

function charNameCell(char) {
  return `<td class="char-name">${charIconHtml(char)}${fmtCharName(char)}</td>`;
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
// true final boss and matches what the granular "10" column reports).
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

    const act3Bosses = run.asc === 10 ? bossFights.filter(f => ACT3_BOSS_IDS.has(f.enc)) : [];
    const mark = (bucket) => { bucket.reached += 1; if (won) bucket.won += 1; };
    // Bucketed, A10's first Act 3 boss stands in its tier's column, as A8 and
    // A9's one Act 3 boss does; its second has a column of its own (10-2).
    const tierWon = !sharedAscGranular && act3Bosses.length ? act3Bosses[0].won : won;
    const markTier = (bucket) => { bucket.reached += 1; if (tierWon) bucket.won += 1; };
    const asc  = ascColumnKey(run.asc);
    if (byCA[run.char]?.[asc])     markTier(byCA[run.char][asc]);
    if (byCA[run.char]?.["ALL"])   mark(byCA[run.char]["ALL"]);
    if (byCA["ALL"]?.[asc])        markTier(byCA["ALL"][asc]);
    mark(byCA["ALL"]["ALL"]);

    if (run.asc === 10) {
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

  // Ascension 10 has two Act 3 bosses. Granular, its column splits into
  // "1st Boss" / "2nd Boss"; bucketed, the first counts in its tier's column
  // (see aggregateFinalBossWins) and the second follows it in its own.
  const cols = [];
  ascColumns().forEach(col => {
    if (col.ascs.length === 1 && col.ascs[0] === 10) {
      cols.push({ key: "10-1", label: "A10<br>1st Boss" }, { key: "10-2", label: "A10<br>2nd Boss" });
    } else {
      cols.push(col);
      if (!sharedAscGranular && col.ascs.includes(10)) cols.push({ key: "10-2", label: "A10<br>2nd Boss" });
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
  // The caption's A10 sentence only while A10's second boss has a column.
  document.getElementById("final-boss-a10-note").hidden = !cols.some(c => c.key === "10-2");
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
    html += `<div style="color:${color};font-weight:600">${charIconHtml(char)}${fmtCharName(char)}</div>${lanes(s, color).join("")}`;
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
