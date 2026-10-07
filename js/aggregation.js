// -------------------------------------------------------------------------
// Aggregation helpers
// -------------------------------------------------------------------------

function median(arr) {
  if (!arr.length) return null;
  const s = [...arr].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : +((s[m - 1] + s[m]) / 2).toFixed(1);
}

function emptyBucket() {
  return {
    wins:            0,
    runs:            0,
    losses:          0,
    floorSum:        0,
    timeSum:         0,
    floorVals:       [],
    timeVals:        [],
    winTimeVals:     [],
    cardSum:         0,
    relicSum:        0,
    goldSum:         0,
    goldVals:        [],
    winCardSum:      0,
    lossCardSum:     0,
    winRelicSum:     0,
    lossRelicSum:    0,
    winStrikeSum:    0,
    lossStrikeSum:   0,
    winDefendSum:    0,
    lossDefendSum:   0,
    winEliteSum:     0,
    lossEliteSum:    0,
    winBossSum:      0,
    lossBossSum:     0,
    winCardVals:     [],
    lossCardVals:    [],
    winRelicVals:    [],
    lossRelicVals:   [],
    winEliteVals:    [],
    lossEliteVals:   [],
    minWinElites:    Infinity,
    maxWinElites:    0,
    minWinCards:     Infinity,
    maxWinCards:     0,
    minWinRelics:    Infinity,
    maxWinRelics:    0,
  };
}

function addToBucket(bucket, run) {
  bucket.wins     += run.won ? 1 : 0;
  bucket.losses   += run.won ? 0 : 1;
  bucket.runs     += 1;
  bucket.floorSum += run.floor;
  bucket.timeSum  += run.mins;
  bucket.floorVals.push(run.floor);
  bucket.timeVals.push(run.mins);
  if (run.won) bucket.winTimeVals.push(run.mins);
  bucket.cardSum  += run.cards;
  bucket.relicSum += run.relics;
  bucket.goldSum  += run.goldGained ?? 0;
  bucket.goldVals.push(run.goldGained ?? 0);

  const elitesWon = (run.fights || []).filter(f => f.type === "elite" && f.won).length;
  const bossesWon = (run.fights || []).filter(f => f.type === "boss"  && f.won).length;
  if (run.won) {
    bucket.winCardSum    += run.cards;
    bucket.winRelicSum   += run.relics;
    bucket.winStrikeSum  += run.strikes ?? 0;
    bucket.winDefendSum  += run.defends ?? 0;
    bucket.winEliteSum   += elitesWon;
    bucket.winBossSum    += bossesWon;
    bucket.minWinElites  = Math.min(bucket.minWinElites, elitesWon);
    bucket.maxWinElites  = Math.max(bucket.maxWinElites, elitesWon);
    bucket.minWinCards   = Math.min(bucket.minWinCards,  run.cards);
    bucket.maxWinCards   = Math.max(bucket.maxWinCards,  run.cards);
    bucket.minWinRelics  = Math.min(bucket.minWinRelics, run.relics);
    bucket.maxWinRelics  = Math.max(bucket.maxWinRelics, run.relics);
    bucket.winCardVals.push(run.cards);
    bucket.winRelicVals.push(run.relics);
    bucket.winEliteVals.push(elitesWon);
  } else {
    bucket.lossCardSum   += run.cards;
    bucket.lossRelicSum  += run.relics;
    bucket.lossStrikeSum += run.strikes ?? 0;
    bucket.lossDefendSum += run.defends ?? 0;
    bucket.lossEliteSum  += elitesWon;
    bucket.lossBossSum   += bossesWon;
    bucket.lossCardVals.push(run.cards);
    bucket.lossRelicVals.push(run.relics);
    bucket.lossEliteVals.push(elitesWon);
  }
}

function summarize(bucket) {
  const n = bucket.runs;
  const w = bucket.wins;
  const l = bucket.losses;
  return {
    wins:            w,
    runs:            n,
    losses:          l,
    win_pct:         n ? +(w / n * 100).toFixed(1) : null,
    avg_floor:       n ? +(bucket.floorSum / n).toFixed(1)   : null,
    avg_min:         n ? +(bucket.timeSum  / n).toFixed(1)   : null,
    median_floor:    median(bucket.floorVals),
    median_min:      median(bucket.timeVals),
    median_win_min:  median(bucket.winTimeVals),
    total_hrs:       n ? +(bucket.timeSum / 60).toFixed(1)   : null,
    total_min:       n ? bucket.timeSum : null,
    avg_cards:       n ? +(bucket.cardSum  / n).toFixed(1)   : null,
    avg_relics:      n ? +(bucket.relicSum / n).toFixed(1)   : null,
    total_gold:      n ? bucket.goldSum : null,
    median_gold:     median(bucket.goldVals),
    total_elites_defeated: n ? bucket.winEliteSum + bucket.lossEliteSum : null,
    total_bosses_defeated: n ? bucket.winBossSum  + bucket.lossBossSum  : null,
    avg_win_cards:        w ? +(bucket.winCardSum    / w).toFixed(1) : null,
    avg_loss_cards:       l ? +(bucket.lossCardSum  / l).toFixed(1) : null,
    avg_win_relics:       w ? +(bucket.winRelicSum   / w).toFixed(1) : null,
    avg_loss_relics:      l ? +(bucket.lossRelicSum  / l).toFixed(1) : null,
    avg_win_strikes:      w ? +(bucket.winStrikeSum  / w).toFixed(1) : null,
    avg_loss_strikes:     l ? +(bucket.lossStrikeSum / l).toFixed(1) : null,
    avg_win_defends:      w ? +(bucket.winDefendSum  / w).toFixed(1) : null,
    avg_loss_defends:     l ? +(bucket.lossDefendSum / l).toFixed(1) : null,
    avg_win_elites:       w ? +(bucket.winEliteSum   / w).toFixed(1) : null,
    avg_loss_elites:      l ? +(bucket.lossEliteSum  / l).toFixed(1) : null,
    median_win_cards:     median(bucket.winCardVals),
    median_loss_cards:    median(bucket.lossCardVals),
    median_win_relics:    median(bucket.winRelicVals),
    median_loss_relics:   median(bucket.lossRelicVals),
    min_win_elites:   w ? bucket.minWinElites : null,
    max_win_elites:   w ? bucket.maxWinElites : null,
    min_win_cards:   w ? bucket.minWinCards  : null,
    max_win_cards:   w ? bucket.maxWinCards  : null,
    min_win_relics:  w ? bucket.minWinRelics : null,
    max_win_relics:  w ? bucket.maxWinRelics : null,
  };
}

function aggregateRuns(filteredRuns) {
  const chars = DATA.characters;
  const ascs  = ascColumns().map(col => col.key);

  const byCA = {};
  [...chars, "ALL"].forEach(char => {
    byCA[char] = {};
    [...ascs, "ALL"].forEach(asc => {
      byCA[char][asc] = emptyBucket();
    });
  });

  filteredRuns.forEach(run => {
    const c = run.char;
    const a = ascColumnKey(run.asc);

    if (byCA[c]) {
      if (byCA[c][a] !== undefined) addToBucket(byCA[c][a], run);
      addToBucket(byCA[c]["ALL"], run);
    }

    if (byCA["ALL"][a] !== undefined) addToBucket(byCA["ALL"][a], run);
    addToBucket(byCA["ALL"]["ALL"], run);
  });

  const pivot = {};
  [...chars, "ALL"].forEach(char => {
    pivot[char] = {};
    [...ascs, "ALL"].forEach(asc => {
      const b = byCA[char]?.[asc];
      pivot[char][asc] = (b && b.runs > 0) ? summarize(b) : null;
    });
  });

  return {
    pivot,
    grand:     summarize(byCA["ALL"]["ALL"]),
    charStats: chars.map(c => summarize(byCA[c]["ALL"])),
  };
}


