// =========================================================================
// Per-encounter fight tables (Overview page): boss and elite win rates,
// HP entering each fight, damage taken. These were the Character Detail
// page, one character at a time; on the Overview they cover every character.
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
  return ALL_FIGHTS.filter(f => okTs.has(f.ts));
}


// ---- Aggregation for fight data ----

function fightBucket() {
  return {
    wins: 0, runs: 0,
    winHpSum: 0, winMaxHpSum: 0,
    winCardsSum: 0, winRelicsSum: 0, winPotionsSum: 0,
    winDmgSum: 0,
    minWinHp: Infinity,  maxWinHp: 0,
    lowWin: null,  // the won fight entered at the lowest HP
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
    if (!bucket.lowWin || fight.hp < bucket.lowWin.hp) bucket.lowWin = { hp: fight.hp, maxHp };
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

// The lowest tenth of a fight's wins by HP entering, at least one fight.
// A share, not a fixed count, so it is the same kind of number for a fight
// with 200 wins and one with 20.
const LOW_WINS_SHARE = 0.1;

function summarizeFights(bucket) {
  const n = bucket.runs;
  if (!n) return null;
  const w = bucket.wins;
  const l = n - w;
  const lowWins = [...bucket.winHpVals].sort((a, b) => a - b).slice(0, Math.max(1, Math.round(w * LOW_WINS_SHARE)));
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
    low_win:         bucket.lowWin,
    low_wins_hp:     w ? median(lowWins) : null,
    low_wins_count:  w ? lowWins.length : 0,
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


// ---- Rendering: the fight sections (Overview page) ----
//
// Fight Win %, HP Entering Fight and Damage Taken share one layout: a lane
// per fight, elites beside bosses for each act. Bosses carry their own map
// icon; the game has one icon for every elite. The section header says Elites
// or Bosses, so the names drop that word; the name column is a fixed width so
// every group's scale lines up.
//
// Each lane is the filtered fights as a whole. The ascension filter narrows
// them; there is no per-ascension column.
// opts: { legend, has(s), lane(s), ticks: [[pos %, label]] }
function renderFightLanes(elId, encGroups, fightData, opts) {
  const icons = DATA.nodeIcons || {};
  const axis = `<span></span><span></span><div class="fl-lane fl-axis">${
    opts.ticks.map(([pos, label]) => `<span style="left:${pos}%">${label}</span>`).join("")}</div>`;
  let html = `${opts.legend || ""}<div class="fl-groups">`;
  encGroups.forEach(({ label, ids }) => {
    const rows = ids.filter(enc => fightData[enc]?.["ALL"] && opts.has(fightData[enc]["ALL"]));
    if (!rows.length) return;
    html += `<div><div class="fl-section">${label}</div><div class="fl-rows">`;
    rows.forEach(enc => {
      const src = icons[enc] || icons.elite;
      html += `${src ? `<img src="${src}" alt="">` : `<span></span>`}` +
        `<div class="fl-name">${(DATA.encLabels[enc] || enc).replace(/ (Boss|Elite)$/, "")}</div>` +
        opts.lane(fightData[enc]["ALL"]);
    });
    html += `${axis}</div></div>`;
  });
  document.getElementById(elId).innerHTML = html + `</div>`;
}

const WON_LOST_LEGEND = `<div class="fl-legend"><i class="fl-won"></i>won<i class="fl-lost"></i>lost</div>`;
const fightCount = n => `${n} fight${n !== 1 ? "s" : ""}`;

// A dot for fights won and a dot for fights lost, joined by a line that runs
// from the one colour to the other, on a 0..max scale.
// won / lost are the values, wonTip / lostTip their tooltip text.
function wonLostLane(s, won, lost, max, unit, wonTip, lostTip) {
  const pos = v => +(v / max * 100).toFixed(1);
  const pts = [won, lost].filter(v => v != null);
  const lo = pos(Math.min(...pts)), hi = pos(Math.max(...pts));
  const tip = [
    won  != null ? `Won: ${wonTip}, ${fightCount(s.wins)}` : null,
    lost != null ? `Lost: ${lostTip}, ${fightCount(s.runs - s.wins)}` : null,
  ].filter(Boolean).join("\n");
  return `<div class="fl-lane" data-tip="${tip}">` +
    `<span class="fl-line${won != null && lost != null && won > lost ? " fl-line-rev" : ""}" style="left:${lo}%;width:${(hi - lo).toFixed(1)}%"></span>` +
    (lost != null ? `<span class="fl-dot fl-lost" style="left:${pos(lost)}%"></span>` : "") +
    (won  != null ? `<span class="fl-dot fl-won" style="left:${pos(won)}%"></span>` : "") +
    `<span class="fl-value" style="left:calc(${hi}% + 10px)">${won ?? "—"}${unit} · ${lost ?? "—"}${unit}</span></div>`;
}

// HP Entering Fight: how healthy to be before taking the fight. A ring at the
// median HP of the lowest tenth of wins, a dot at the median HP of all wins,
// and a band between. The single lowest win is one lucky escape (an elite
// won from 6 HP), so it and the fights lost are in the tooltip only.
//
// Actual HP, not % of max: max HP differs by character and moves with relics,
// and HP reads straight against Damage Taken, which shares the scale (max).
function hpLane(s, max) {
  const low = s.low_wins_hp, med = s.avg_hp;
  const pos = v => +(v / max * 100).toFixed(1);
  const tip = [
    `Lowest 10% of wins: ${low} HP, ${fightCount(s.low_wins_count)}`,
    `Lowest win: ${s.low_win.hp} / ${s.low_win.maxHp} HP`,
    `Median when you win: ${med} HP, ${fightCount(s.wins)}`,
    s.loss_avg_hp != null ? `Median when you lost: ${s.loss_avg_hp} HP, ${fightCount(s.runs - s.wins)}` : null,
  ].filter(Boolean).join("\n");
  return `<div class="fl-lane" data-tip="${tip}">` +
    `<span class="fl-band" style="left:${pos(low)}%;width:${(pos(med) - pos(low)).toFixed(1)}%"></span>` +
    `<span class="fl-dot fl-low" style="left:${pos(low)}%"></span>` +
    `<span class="fl-dot fl-won" style="left:${pos(med)}%"></span>` +
    `<span class="fl-value" style="left:calc(${pos(med)}% + 10px)">${low} · ${med} HP</span></div>`;
}

// A bar filled to the win %, coloured by the same tiers the win tables use.
function winLane(s) {
  // Fights/turns/HP are three distinct stats, not fragments of one — each
  // gets its own line (via showTableTooltip's "\n" handling).
  const tipLines = [`Fights: ${s.runs} (${s.wins}W / ${s.runs - s.wins}L)`];
  if (s.avg_turns != null) {
    tipLines.push(`Turns: ${s.avg_turns}W${s.loss_avg_turns != null ? ` / ${s.loss_avg_turns}L` : ""}`);
  }
  if (s.avg_hp != null) {
    const win = `${s.avg_hp} HP (${s.avg_hp_pct}%)W`;
    const loss = s.loss_avg_hp != null ? ` / ${s.loss_avg_hp} HP (${s.loss_avg_hp_pct}%)L` : "";
    tipLines.push(`HP entering: ${win}${loss}`);
  }
  const { color } = winPctStyle(s.win_pct, [60, 40, 20]);
  return `<div class="fl-lane" data-tip="${tipLines.join("\n")}">` +
    `<span class="fl-fill" style="width:${s.win_pct}%;background:${color}"></span>` +
    `<span class="fl-value" style="left:calc(${s.win_pct}% + 8px)"><b style="color:${color}">${s.win_pct}%</b> · ${s.wins}W / ${s.runs - s.wins}L</span></div>`;
}

const PCT_TICKS = [0, 25, 50, 75, 100].map(v => [v, `${v}%`]);

function renderFightTables() {
  const fightData = aggregateFights(filterFights());
  const groups    = DATA.encGroups;

  renderFightLanes("win-lanes", groups, fightData, {
    has: s => s.win_pct != null, lane: winLane, ticks: PCT_TICKS,
  });

  // HP Entering Fight and Damage Taken share one scale, for every group: an
  // Act 1 elite and an Act 3 boss compare, and so do HP and damage. Rounded
  // up to a multiple of 20 so the quarter ticks are whole.
  const vals = Object.values(fightData).flatMap(byAsc => {
    const s = byAsc["ALL"];
    return s ? [s.avg_hp, s.avg_dmg, s.loss_avg_dmg] : [];
  }).filter(v => v != null);
  const max = Math.max(20, Math.ceil(Math.max(0, ...vals) / 20) * 20);
  const ticks = [0, 25, 50, 75, 100].map(v => [v, max * v / 100]);

  renderFightLanes("hp-lanes", groups, fightData, {
    legend: `<div class="fl-legend"><i class="fl-low"></i>HP at your lowest 10% of wins<i class="fl-won"></i>median HP when you win</div>`,
    ticks, has: s => s.low_win != null, lane: s => hpLane(s, max),
  });

  renderFightLanes("dmg-lanes", groups, fightData, {
    legend: WON_LOST_LEGEND, ticks,
    has:  s => s.avg_dmg != null || s.loss_avg_dmg != null,
    lane: s => wonLostLane(s, s.avg_dmg, s.loss_avg_dmg, max, "",
      `${s.avg_dmg} damage`, `${s.loss_avg_dmg} damage`),
  });
}
