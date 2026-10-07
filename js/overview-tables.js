// -------------------------------------------------------------------------
// Per-act starter cards chart (Overview page)
// -------------------------------------------------------------------------

// Returns act number (1, 2, 3) for a boss encounter ID, or null if unknown.
function bossAct(encId) {
  for (const g of DATA.encGroups) {
    if (!g.label.includes("Boss")) continue;
    if (g.ids.includes(encId)) {
      if (g.label.startsWith("Act 1")) return 1;
      if (g.label.startsWith("Act 2")) return 2;
      if (g.label.startsWith("Act 3")) return 3;
    }
  }
  return null;
}

function aggregateStarterCards(filteredRuns) {
  // bucket[char][act] = { winStrikes, lossStrikes, winDefends, lossDefends, wins, losses }
  const chars = DATA.characters;
  const acts  = [1, 2, 3];
  const bucket = {};
  [...chars, "ALL"].forEach(c => {
    bucket[c] = {};
    [...acts, "ALL"].forEach(a => {
      bucket[c][a] = { winStrikes: 0, lossStrikes: 0, winDefends: 0, lossDefends: 0, wins: 0, losses: 0 };
    });
  });

  filteredRuns.forEach(run => {
    const char = run.char;
    (run.fights || []).filter(f => f.type === "boss").forEach(f => {
      const act = bossAct(f.enc);
      if (!act) return;
      const key = f.won ? "win" : "loss";
      const countKey = f.won ? "wins" : "losses";
      const strikes = f.strikes ?? 0;
      const defends = f.defends ?? 0;

      for (const c of [char, "ALL"]) {
        for (const a of [act, "ALL"]) {
          bucket[c][a][key + "Strikes"] += strikes;
          bucket[c][a][key + "Defends"] += defends;
          bucket[c][a][countKey]        += 1;
        }
      }
    });
  });

  // Summarize to averages
  const result = {};
  [...chars, "ALL"].forEach(c => {
    result[c] = {};
    [...acts, "ALL"].forEach(a => {
      const b = bucket[c][a];
      const w = b.wins, l = b.losses;
      result[c][a] = (w + l === 0) ? null : {
        avgWinStrikes:  w ? +(b.winStrikes  / w).toFixed(1) : null,
        avgLossStrikes: l ? +(b.lossStrikes / l).toFixed(1) : null,
        avgWinDefends:  w ? +(b.winDefends  / w).toFixed(1) : null,
        avgLossDefends: l ? +(b.lossDefends / l).toFixed(1) : null,
        wins: w, losses: l,
      };
    });
  });
  return result;
}

// Strikes and Defends as two sections of a gap chart, one lane per act boss.
// Shows the filtered runs as a whole; the character filter picks a character.
function renderStarterCardsGap(data) {
  const all = data["ALL"];
  const section = key => ({
    title: key,
    rows: [1, 2, 3].map(act => ({
      label: `Act ${act} boss`,
      won:   all[act]?.[`avgWin${key}`],
      lost:  all[act]?.[`avgLoss${key}`],
    })),
  });
  // One scale for both sections, so a Strike lane and a Defend lane compare.
  renderGapChart("starter-cards-gap", [section("Strikes"), section("Defends")], true);
}


// -------------------------------------------------------------------------
// Rest site options (Overview page)
// -------------------------------------------------------------------------

const REST_ACTS = [1, 2, 3];
const REST_CHOICES = ["HEAL", "SMITH"];
const REST_CHOICE_LABELS = { HEAL: "Heal", SMITH: "Smith" };
