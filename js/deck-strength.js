// ---- Deck strength ----
//
// What the deck could do in a turn after each floor: damage, block, energy and
// cards drawn. A cheap formula, not a simulation: the damage and block the
// cards in hand can play with the energy there is, plus what builds on them
// (Strength, Dexterity, Plating, block and energy relics, poison, Frost,
// Osty). Fitted to
// real fights, these predict damage taken and turns about as well as the sim
// does (tools/power_curve: predict_fights.py; export_strength.py writes
// DATA.deckStrength). Skipping a card leaves every number where it was; junk
// thins out the cards a turn sees and pulls them down.

// predict_fights.formula_rows, line for line: change both.
function strengthFeatures(rows, relicBlk, relicEnergy, turns) {
  const g = (r, k) => r[k] || 0;
  const sum = (list, f) => list.reduce((s, r) => s + f(r), 0);
  const n = Math.max(rows.length, 1);
  const live = rows.filter(r => !g(r, "x"));
  const seen = Math.min(10, n, 5 * (1 + sum(live, r => g(r, "d")) / n));  // cards a turn sees, draw cards drawing more
  const share = seen / n;
  const energy = 3 + relicEnergy + sum(live, r => g(r, "e")) * share;
  let on = 0;  // a Power's share of turns in play: from the turn after it's drawn
  for (let k = 0; k < turns; k++) on += Math.min(1, k * share);
  on /= turns;

  // Per turn: the job's cards in hand, as many as the energy pays for, and their average worth.
  const allIn = key => {
    const cards = live.filter(r => !g(r, "p") && g(r, key) > 0);
    if (!cards.length) return [0, 0];
    const inHand = cards.length * share;
    const avgCost = sum(cards, r => g(r, "c")) / cards.length;
    const played = avgCost ? Math.min(inHand, energy / avgCost) : inHand;
    return [played, sum(cards, r => g(r, key)) / cards.length];
  };
  const [bPlayed, bAvg] = allIn("b");
  const [dPlayed, dAvg] = allIn("h");
  const hitters = live.filter(r => g(r, "n"));
  const attacks = sum(hitters, r => g(r, "n")) / Math.max(hitters.length, 1) * dPlayed;
  const liveShare = r => g(r, "p") ? on : share;  // a Skill's buff (Blur) only on the turn it's played
  return {
    f_dmg: dPlayed * dAvg, f_block: bPlayed * bAvg,
    f_dex: sum(live, r => g(r, "dx") * liveShare(r)) * bPlayed,
    f_turnblock: sum(live, r => g(r, "tb")) * on + relicBlk,
    f_frost: sum(live, r => g(r, "fr")) * share,
    f_summon: sum(live, r => g(r, "su")) * share,
    f_str: sum(live, r => g(r, "st") * liveShare(r)) * attacks,
    f_dot: sum(live, r => g(r, "fu")) * on * turns / 2 + sum(live, r => g(r, "po")) * share * 2.5,
    f_junk: n - live.length, f_seen: seen, f_energy: energy,
  };
}

// The four per-turn numbers. Frost blocks frostBlock a turn while channelled
// and Osty's HP soaks hits like block, as in the sim; dead cards drawn aren't
// counted as cards.
function strengthBuckets(feat, size, frostBlock) {
  return {
    damage: feat.f_dmg + feat.f_str + feat.f_dot,
    block: feat.f_block + feat.f_dex + feat.f_turnblock + feat.f_frost * frostBlock + feat.f_summon,
    energy: feat.f_energy,
    draw: feat.f_seen * (size - feat.f_junk) / Math.max(size, 1),
  };
}

// Per timeline node: { damage, block, energy, draw, cards, relics } for the deck after that
// floor, where cards and relics are what the floor added and removed as
// [id, upgraded, +1/-1]. cards and relics are heldItems() lists; a card counts
// as upgraded once a Smith or event has upgraded that many copies of it, as
// approaches.states does. Null when there's no card data to score with.
function deckStrengthByFloor(nodes, cards, relics) {
  const S = DATA.deckStrength;
  if (!S) return null;
  const order = [...cards].sort((a, b) => a.added - b.added);
  const ups = {};
  let prevCards = {}, prevRelics = new Set();
  return nodes.map(node => {
    const f = node.floor + 1;
    (node.upgradedCards || []).forEach(id => { ups[id] = (ups[id] || 0) + 1; });
    const left = { ...ups }, deck = {}, rows = [];
    order.forEach(c => {
      if (c.added > f || c.removed <= f) return;
      const up = (left[c.id] || 0) > 0;
      left[c.id] = (left[c.id] || 0) - 1;
      rows.push((S.cards[c.id] || [{}, {}])[up ? 1 : 0]);
      const key = c.id + (up ? "+" : "");
      deck[key] = (deck[key] || 0) + 1;
    });
    const held = new Set(relics.filter(r => r.added <= f && r.removed > f).map(r => r.id));
    const heldIds = [...held];
    const relicEnergy = S.relicEnergy || {};
    const feat = strengthFeatures(rows,
      heldIds.reduce((s, id) => s + (S.relics[id] || 0), 0),
      heldIds.reduce((s, id) => s + (relicEnergy[id] || 0), 0), S.turns);

    const change = [];
    new Set([...Object.keys(deck), ...Object.keys(prevCards)]).forEach(key => {
      const d = (deck[key] || 0) - (prevCards[key] || 0);
      for (let i = 0; i < Math.abs(d); i++) change.push([key.replace(/\+$/, ""), key.endsWith("+"), Math.sign(d)]);
    });
    const relicChange = [...held].filter(id => !prevRelics.has(id)).map(id => [id, false, 1])
      .concat([...prevRelics].filter(id => !held.has(id)).map(id => [id, false, -1]));
    prevCards = deck; prevRelics = held;
    return { ...strengthBuckets(feat, rows.length, S.frostBlock), cards: change, relics: relicChange };
  });
}
