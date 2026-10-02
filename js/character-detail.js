// =========================================================================
// Character detail page
// =========================================================================

// Each run's fights array is already embedded — flatten them all here.
// Each fight record carries a .ts field inherited from its parent run so
// it can be filtered against the shared filter state.
const ALL_FIGHTS = DATA.runsData.flatMap(run =>
  (run.fights || []).map(f => ({ ...f, ts: run.ts, mp: run.mp, mode: run.mode, build: run.build }))
);

// Encounter IDs split by type, sorted alphabetically.
const BOSS_IDS  = [...new Set(ALL_FIGHTS.filter(f => f.type === "boss").map(f => f.enc))].sort();
const ELITE_IDS = [...new Set(ALL_FIGHTS.filter(f => f.type === "elite").map(f => f.enc))].sort();

// ---- Fight filtering ----

function filterFights() {
  const okTs = filteredRunTsSet();
  const char = singleCharFallback();
  return ALL_FIGHTS.filter(f => f.char === char && okTs.has(f.ts));
}


// ---- Aggregation for fight data ----

function fightBucket() {
  return {
    wins: 0, runs: 0,
    winHpSum: 0, winMaxHpSum: 0,
    winCardsSum: 0, winRelicsSum: 0, winPotionsSum: 0,
    winDmgSum: 0,
    minWinHp: Infinity,  maxWinHp: 0,
    minWinCards: Infinity,   maxWinCards: 0,
    minWinRelics: Infinity,  maxWinRelics: 0,
    minWinPotions: Infinity, maxWinPotions: 0,
    minWinDmg: Infinity, maxWinDmg: 0,
    lossHpSum: 0, lossMaxHpSum: 0,
    lossCardsSum: 0, lossRelicsSum: 0, lossPotionsSum: 0,
    lossDmgSum: 0,
    minLossHp: Infinity,  maxLossHp: 0,
    minLossCards: Infinity,   maxLossCards: 0,
    minLossRelics: Infinity,  maxLossRelics: 0,
    minLossPotions: Infinity, maxLossPotions: 0,
    minLossDmg: Infinity, maxLossDmg: 0,
    winHpVals: [], winHpPctVals: [], winCardsVals: [], winRelicsVals: [], winPotionsVals: [], winDmgVals: [], winTurnsVals: [],
    lossHpVals: [], lossHpPctVals: [], lossCardsVals: [], lossRelicsVals: [], lossPotionsVals: [], lossDmgVals: [], lossTurnsVals: [],
  };
}

function addFight(bucket, fight) {
  bucket.wins += fight.won ? 1 : 0;
  bucket.runs += 1;

  if (fight.won) {
    const maxHp = fight.maxHp || 1;
    bucket.winHpSum      += fight.hp;
    bucket.winMaxHpSum   += maxHp;
    bucket.winCardsSum   += fight.cards;
    bucket.winRelicsSum  += fight.relics;
    bucket.winPotionsSum += fight.potions;
    bucket.minWinHp      = Math.min(bucket.minWinHp,      fight.hp);
    bucket.maxWinHp      = Math.max(bucket.maxWinHp,      fight.hp);
    bucket.minWinCards   = Math.min(bucket.minWinCards,   fight.cards);
    bucket.maxWinCards   = Math.max(bucket.maxWinCards,   fight.cards);
    bucket.minWinRelics  = Math.min(bucket.minWinRelics,  fight.relics);
    bucket.maxWinRelics  = Math.max(bucket.maxWinRelics,  fight.relics);
    bucket.minWinPotions = Math.min(bucket.minWinPotions, fight.potions);
    bucket.maxWinPotions = Math.max(bucket.maxWinPotions, fight.potions);
    bucket.winDmgSum    += fight.dmg;
    bucket.minWinDmg     = Math.min(bucket.minWinDmg, fight.dmg);
    bucket.maxWinDmg     = Math.max(bucket.maxWinDmg, fight.dmg);
    bucket.winHpVals.push(fight.hp);
    bucket.winHpPctVals.push(+(fight.hp / maxHp * 100).toFixed(1));
    bucket.winCardsVals.push(fight.cards);
    bucket.winRelicsVals.push(fight.relics);
    bucket.winPotionsVals.push(fight.potions);
    bucket.winDmgVals.push(fight.dmg);
    if (fight.turns > 0) bucket.winTurnsVals.push(fight.turns);
  } else {
    const maxHp = fight.maxHp || 1;
    bucket.lossHpSum      += fight.hp;
    bucket.lossMaxHpSum   += maxHp;
    bucket.lossCardsSum   += fight.cards;
    bucket.lossRelicsSum  += fight.relics;
    bucket.lossPotionsSum += fight.potions;
    bucket.minLossHp      = Math.min(bucket.minLossHp,      fight.hp);
    bucket.maxLossHp      = Math.max(bucket.maxLossHp,      fight.hp);
    bucket.minLossCards   = Math.min(bucket.minLossCards,   fight.cards);
    bucket.maxLossCards   = Math.max(bucket.maxLossCards,   fight.cards);
    bucket.minLossRelics  = Math.min(bucket.minLossRelics,  fight.relics);
    bucket.maxLossRelics  = Math.max(bucket.maxLossRelics,  fight.relics);
    bucket.minLossPotions = Math.min(bucket.minLossPotions, fight.potions);
    bucket.maxLossPotions = Math.max(bucket.maxLossPotions, fight.potions);
    bucket.lossDmgSum    += fight.dmg;
    bucket.minLossDmg     = Math.min(bucket.minLossDmg, fight.dmg);
    bucket.maxLossDmg     = Math.max(bucket.maxLossDmg, fight.dmg);
    bucket.lossHpVals.push(fight.hp);
    bucket.lossHpPctVals.push(+(fight.hp / maxHp * 100).toFixed(1));
    bucket.lossCardsVals.push(fight.cards);
    bucket.lossRelicsVals.push(fight.relics);
    bucket.lossPotionsVals.push(fight.potions);
    bucket.lossDmgVals.push(fight.dmg);
    if (fight.turns > 0) bucket.lossTurnsVals.push(fight.turns);
  }
}

function summarizeFights(bucket) {
  const n = bucket.runs;
  if (!n) return null;
  const w = bucket.wins;
  const l = n - w;
  return {
    wins:        w,
    losses:      l,
    runs:        n,
    win_pct:     +(w / n * 100).toFixed(1),
    avg_hp:      median(bucket.winHpVals),
    avg_hp_pct:  median(bucket.winHpPctVals),
    avg_cards:   median(bucket.winCardsVals),
    avg_relics:  median(bucket.winRelicsVals),
    avg_potions: median(bucket.winPotionsVals),
    min_win_hp:      w ? bucket.minWinHp      : null,
    max_win_hp:      w ? bucket.maxWinHp      : null,
    min_win_cards:   w ? bucket.minWinCards   : null,
    max_win_cards:   w ? bucket.maxWinCards   : null,
    min_win_relics:  w ? bucket.minWinRelics  : null,
    max_win_relics:  w ? bucket.maxWinRelics  : null,
    min_win_potions: w ? bucket.minWinPotions : null,
    max_win_potions: w ? bucket.maxWinPotions : null,
    avg_dmg:         median(bucket.winDmgVals),
    min_win_dmg:     w ? bucket.minWinDmg : null,
    max_win_dmg:     w ? bucket.maxWinDmg : null,
    loss_avg_hp:      median(bucket.lossHpVals),
    loss_avg_hp_pct:  median(bucket.lossHpPctVals),
    loss_avg_cards:   median(bucket.lossCardsVals),
    loss_avg_relics:  median(bucket.lossRelicsVals),
    loss_avg_potions: median(bucket.lossPotionsVals),
    min_loss_hp:      l ? bucket.minLossHp      : null,
    max_loss_hp:      l ? bucket.maxLossHp      : null,
    min_loss_cards:   l ? bucket.minLossCards   : null,
    max_loss_cards:   l ? bucket.maxLossCards   : null,
    min_loss_relics:  l ? bucket.minLossRelics  : null,
    max_loss_relics:  l ? bucket.maxLossRelics  : null,
    min_loss_potions: l ? bucket.minLossPotions : null,
    max_loss_potions: l ? bucket.maxLossPotions : null,
    loss_avg_dmg:     median(bucket.lossDmgVals),
    min_loss_dmg:     l ? bucket.minLossDmg : null,
    max_loss_dmg:     l ? bucket.maxLossDmg : null,
    avg_turns:        median(bucket.winTurnsVals),
    loss_avg_turns:   median(bucket.lossTurnsVals),
  };
}

function aggregateFights(fights) {
  const allEncs   = [...BOSS_IDS, ...ELITE_IDS];
  const byEncAsc  = {};
  allEncs.forEach(enc => {
    byEncAsc[enc] = {};
    ascColumns().forEach(col => { byEncAsc[enc][col.key] = fightBucket(); });
    byEncAsc[enc]["ALL"] = fightBucket();
  });

  fights.forEach(f => {
    if (!byEncAsc[f.enc]) return;
    const b = byEncAsc[f.enc][ascColumnKey(f.asc)];
    if (b) addFight(b, f);
    addFight(byEncAsc[f.enc]["ALL"],   f);
  });

  const result = {};
  allEncs.forEach(enc => {
    result[enc] = {};
    ascColumns().forEach(col => { result[enc][col.key] = summarizeFights(byEncAsc[enc][col.key]); });
    result[enc]["ALL"] = summarizeFights(byEncAsc[enc]["ALL"]);
  });
  return result;
}


function deckActBucket() {
  return { wins: 0, runs: 0, winVals: [], lossVals: [] };
}

function addDeckAct(bucket, fight) {
  bucket.runs++;
  if (fight.won) { bucket.wins++; bucket.winVals.push(fight.cards); }
  else           { bucket.lossVals.push(fight.cards); }
}

function summarizeDeckAct(bucket) {
  if (!bucket.runs) return null;
  return {
    runs:      bucket.runs,
    wins:      bucket.wins,
    win_pct:   +(bucket.wins / bucket.runs * 100).toFixed(1),
    avg_cards: median(bucket.winVals),
    loss_avg_cards: median(bucket.lossVals),
    min_win:   bucket.winVals.length  ? Math.min(...bucket.winVals)  : null,
    max_win:   bucket.winVals.length  ? Math.max(...bucket.winVals)  : null,
    min_loss:  bucket.lossVals.length ? Math.min(...bucket.lossVals) : null,
    max_loss:  bucket.lossVals.length ? Math.max(...bucket.lossVals) : null,
  };
}

// Returns { act: { asc: summarizeDeckAct, ALL: summarizeDeckAct } }
function aggregateDeckByAct(fights) {
  const acts = [1, 2, 3];
  const byActAsc = {};
  acts.forEach(act => {
    byActAsc[act] = {};
    ascColumns().forEach(col => { byActAsc[act][col.key] = deckActBucket(); });
    byActAsc[act]["ALL"] = deckActBucket();
  });

  fights.forEach(f => {
    if (f.type !== "boss") return;
    const act = bossAct(f.enc);
    if (!act) return;
    const b = byActAsc[act][ascColumnKey(f.asc)];
    if (b) addDeckAct(b, f);
    addDeckAct(byActAsc[act]["ALL"],   f);
  });

  const result = {};
  acts.forEach(act => {
    result[act] = {};
    ascColumns().forEach(col => { result[act][col.key] = summarizeDeckAct(byActAsc[act][col.key]); });
    result[act]["ALL"] = summarizeDeckAct(byActAsc[act]["ALL"]);
  });
  return result;
}

function renderDeckActTable(tableId, deckData) {
  const visAscs = ascColumns();
  const thSub = `font-size:0.72rem;color:#8a8aa0;font-weight:400;text-align:center`;
  const subHead = (cls, border) =>
    `<th class="${cls}" style="${thSub};border-left:${border} solid #3f4147">Won</th><th class="${cls}" style="${thSub};border-left:0">Lost</th>`;
  const cells = (s, isAll) => wonLostCells(s, isAll, s && s.avg_cards != null,
    s && s.avg_cards, s && s.loss_avg_cards);
  let html = `<thead><tr>
    <th class="char-head" rowspan="2">Act</th>
    ${visAscs.map(col => `<th colspan="2" style="border-left:1px solid #3f4147;text-align:center">${col.label}</th>`).join("")}
    <th colspan="2" class="all-col" style="border-left:2px solid #3f4147;text-align:center">All<br>columns</th>
  </tr><tr>
    ${visAscs.map(() => subHead("", "1px")).join("")}${subHead("all-col", "2px")}
  </tr></thead><tbody>`;
  [1, 2, 3].forEach(act => {
    const s = deckData[act];
    if (!s?.["ALL"]) return;
    html += `<tr><td class="char-name">Act ${act}</td>`;
    visAscs.forEach(col => { html += cells(s[col.key], false); });
    html += cells(s["ALL"], true);
    html += `</tr>`;
  });
  html += `</tbody>`;
  document.getElementById(tableId).innerHTML = html;
}

// ---- Rendering helpers for detail tables ----

function encNameCell(enc) {
  const label = DATA.encLabels[enc] || enc;
  return `<td class="char-name" style="font-size:0.8rem;padding-right:0.75rem">${label}</td>`;
}

function fightWinCell(s, isAll) {
  const cls = "cell" + (isAll ? " all-col" : "");
  if (!s) return `<td class="${cls} empty">—</td>`;
  const { bg, color } = winPctStyle(s.win_pct, [60, 40, 20]);
  // Fights/turns/HP are three distinct stats, not fragments of one — each
  // gets its own line (via showTableTooltip's "\n" handling) rather than
  // being run together on one wrapped line, which read as a wall of text.
  const tipLines = [`Fights: ${s.runs} (${s.wins}W / ${s.runs - s.wins}L)`];
  if (s.avg_turns != null) {
    tipLines.push(`Turns: ${s.avg_turns}W${s.loss_avg_turns != null ? ` / ${s.loss_avg_turns}L` : ""}`);
  }
  if (s.avg_hp != null) {
    const win = `${s.avg_hp} HP (${s.avg_hp_pct}%)W`;
    const loss = s.loss_avg_hp != null ? ` / ${s.loss_avg_hp} HP (${s.loss_avg_hp_pct}%)L` : "";
    tipLines.push(`HP entering: ${win}${loss}`);
  }
  return `<td class="${cls}" style="background:${bg}"
      data-tip="${tipLines.join("\n")}">
    <div class="pct" style="color:${color}">${s.win_pct}%</div>
    <div class="meta">${s.runs} fight${s.runs !== 1 ? "s" : ""}</div>
  </td>`;
}

// Won / Lost sub-columns (see renderFightTable's `split`): the header says
// which number is which, so each cell holds one value instead of a
// "win / loss" pair run together.
function wonLostCells(s, isAll, has, won, lost) {
  const cls = "cell" + (isAll ? " all-col" : "");
  const border = `border-left:${isAll ? "2px" : "1px"} solid #3f4147;`;
  // The Lost cell of the All pair must not repeat .all-col's divider.
  const emptyLost = `<td class="${cls} empty" style="border-left:0">—</td>`;
  if (!s || !has) return `<td class="${cls} empty" style="${border}">—</td>${emptyLost}`;
  const lostCell = lost == null
    ? emptyLost
    : `<td class="${cls}" style="border-left:0;font-size:0.88rem;color:#e05c5c">${lost}</td>`;
  return `<td class="${cls}" style="${border}font-size:0.88rem;color:#5cba7d;font-weight:600">${won}</td>${lostCell}`;
}

function hpCell(s, isAll) {
  return wonLostCells(s, isAll, s && s.avg_hp_pct !== null,
    s && `${s.avg_hp} HP (${s.avg_hp_pct}%)`,
    s && s.loss_avg_hp_pct !== null ? `${s.loss_avg_hp} HP (${s.loss_avg_hp_pct}%)` : null);
}

function dmgCell(s, isAll) {
  return wonLostCells(s, isAll, s && s.avg_dmg !== null,
    s && s.avg_dmg,
    s && s.loss_avg_dmg !== null ? s.loss_avg_dmg : null);
}

// Cards, relics and potions each get a line in the Won cell and the matching
// line in the Lost cell.
function loadoutCell(s, isAll) {
  const unit = `<span style="color:#8a8aa0;font-size:0.72rem;font-weight:400">`;
  const lines = (cards, relics, potions) =>
    `<div>${cards} ${unit}${cards === 1 ? "card" : "cards"}</span></div>
    <div style="margin-top:2px">${relics} ${unit}${relics === 1 ? "relic" : "relics"}</span></div>
    <div style="margin-top:2px">${potions} ${unit}${potions === 1 ? "potion" : "potions"}</span></div>`;
  return wonLostCells(s, isAll, s && s.avg_cards !== null,
    s && lines(s.avg_cards, s.avg_relics, s.avg_potions),
    s && s.loss_avg_cards !== null ? lines(s.loss_avg_cards, s.loss_avg_relics, s.loss_avg_potions) : null);
}

// encGroups: array of {label, ids} for section headers, or a flat array of IDs.
// split: cellFn returns a Won and a Lost <td> per column (wonLostCells).
function renderFightTable(tableId, encGroups, fightData, cellFn, split) {
  const visAscs = ascColumns();
  const colSpan = (visAscs.length + 1) * (split ? 2 : 1) + 1; // ascs + ALL + name
  const thSub = `font-size:0.72rem;color:#8a8aa0;font-weight:400;text-align:center`;
  const subHead = (cls, border) =>
    `<th class="${cls}" style="${thSub};border-left:${border} solid #3f4147">Won</th><th class="${cls}" style="${thSub};border-left:0">Lost</th>`;
  let html = split
    ? `<thead><tr>
    <th class="char-head" rowspan="2">Encounter</th>
    ${visAscs.map(col => `<th colspan="2" style="border-left:1px solid #3f4147;text-align:center">${col.label}</th>`).join("")}
    <th colspan="2" class="all-col" style="border-left:2px solid #3f4147;text-align:center">All<br>columns</th>
  </tr><tr>
    ${visAscs.map(() => subHead("", "1px")).join("")}${subHead("all-col", "2px")}
  </tr></thead><tbody>`
    : `<thead><tr>
    <th class="char-head">Encounter</th>
    ${visAscs.map(col => `<th>${col.label}</th>`).join("")}
    <th class="all-col" style="border-left:2px solid #3f4147">All<br>columns</th>
  </tr></thead><tbody>`;

  // Normalise: flat array → single unlabelled group
  const groups = Array.isArray(encGroups[0])
    ? encGroups.map((ids, i) => ({ label: `Act ${i + 1}`, ids }))
    : (encGroups[0]?.ids !== undefined ? encGroups : [{ label: null, ids: encGroups }]);

  groups.forEach(({ label, ids }) => {
    const rows = ids.filter(enc => fightData[enc]?.["ALL"]);
    if (!rows.length) return;

    if (label) {
      html += `<tr><td colspan="${colSpan}" class="act-header">${label}</td></tr>`;
    }

    rows.forEach(enc => {
      html += `<tr>${encNameCell(enc)}`;
      visAscs.forEach(col => { html += cellFn(fightData[enc][col.key], false); });
      html += cellFn(fightData[enc]["ALL"], true);
      html += `</tr>`;
    });
  });

  html += `</tbody>`;
  document.getElementById(tableId).innerHTML = html;
}

function updateDetail() {
  const note = document.getElementById("detail-char-fallback-note");
  if (sharedActiveChar === "ALL") {
    const label = singleCharFallback();
    note.textContent = `Showing data for ${fmtCharName(label)}. Pick a character above to change.`;
    note.style.display = "";
  } else {
    note.style.display = "none";
  }

  const fights    = filterFights();
  const fightData = aggregateFights(fights);
  const deckData  = aggregateDeckByAct(fights);
  const groups    = DATA.encGroups;

  const bossGroups  = groups.filter(g => g.label.includes("Boss"));
  const eliteGroups = groups.filter(g => g.label.includes("Elite"));

  renderFightTable("boss-win-table",  bossGroups,  fightData, fightWinCell);
  renderFightTable("elite-win-table", eliteGroups, fightData, fightWinCell);
  renderFightTable("hp-table",      groups, fightData, hpCell, true);
  renderFightTable("loadout-table", groups, fightData, loadoutCell, true);
  renderFightTable("dmg-table",     groups, fightData, dmgCell, true);
  renderDeckActTable("deck-act-table", deckData);
}


