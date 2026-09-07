// -------------------------------------------------------------------------
// Per-act starter cards table (Overview page)
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

function renderStarterCardsTable(data) {
  const chars = DATA.characters;
  const acts  = [1, 2, 3];

  const thAct  = `font-size:0.7rem;color:#bcbcd0;text-transform:uppercase;letter-spacing:.05em`;
  const thSub  = `font-size:0.72rem;color:#8a8aa0;font-weight:400`;
  let html = `<thead><tr>
    <th class="char-head">Character</th>
    ${acts.map(a => `<th colspan="2" style="text-align:center;border-left:1px solid #3f4147;${thAct}">Act ${a} Boss</th>`).join("")}
    <th colspan="2" class="all-col" style="border-left:2px solid #3f4147;text-align:center;${thAct}">ALL</th>
  </tr><tr>
    <th></th>
    ${acts.map(() => `<th style="${thSub};border-left:1px solid #3f4147">Strikes</th><th style="${thSub}">Defends</th>`).join("")}
    <th class="all-col" style="${thSub};border-left:2px solid #3f4147">Strikes</th>
    <th class="all-col" style="${thSub}">Defends</th>
  </tr></thead><tbody>`;

  const fmt = (val, isLoss) =>
    val != null
      ? `<span style="color:${isLoss ? "#e05c5c" : "#5cba7d"};${isLoss ? "" : "font-weight:600"}"><span class="vh">${isLoss ? "L " : "W "}</span>${val}</span>`
      : `<span style="color:#8a8aa0">—</span>`;

  const rowHtml = (rowData, labelCell) => {
    let r = `<tr>${labelCell}`;
    acts.forEach((a, i) => {
      const d = rowData[a];
      const borderStyle = i === 0 ? "border-left:1px solid #3f4147;" : "border-left:1px solid #3f4147;";
      if (!d) {
        r += `<td class="cell empty" style="${borderStyle}">—</td><td class="cell empty">—</td>`;
      } else {
        r += `<td class="cell" style="${borderStyle}font-size:0.88rem">${fmt(d.avgWinStrikes, false)} / ${fmt(d.avgLossStrikes, true)}</td>`;
        r += `<td class="cell" style="font-size:0.88rem">${fmt(d.avgWinDefends, false)} / ${fmt(d.avgLossDefends, true)}</td>`;
      }
    });
    // ALL column
    const d = rowData["ALL"];
    if (!d) {
      r += `<td class="cell all-col empty" style="border-left:2px solid #3f4147">—</td><td class="cell all-col empty">—</td>`;
    } else {
      r += `<td class="cell all-col" style="border-left:2px solid #3f4147;font-size:0.88rem">${fmt(d.avgWinStrikes, false)} / ${fmt(d.avgLossStrikes, true)}</td>`;
      r += `<td class="cell all-col" style="font-size:0.88rem">${fmt(d.avgWinDefends, false)} / ${fmt(d.avgLossDefends, true)}</td>`;
    }
    r += `</tr>`;
    return r;
  };

  chars.forEach(char => {
    html += rowHtml(data[char], charNameCell(char));
  });
  html += rowHtml(data["ALL"],
    `<td class="char-name" style="color:#e0c468">All Characters</td>`);
  html += `</tbody>`;

  document.getElementById("starter-cards-table").innerHTML = html;
}


// -------------------------------------------------------------------------
// Rest site choices table (Overview page)
// -------------------------------------------------------------------------

const REST_ACTS = [1, 2, 3];
const REST_CHOICES = ["HEAL", "SMITH"];
const REST_CHOICE_LABELS = { HEAL: "Heal", SMITH: "Smith" };

// Returns { char: { asc: { act: { choice: { avgWin, avgLoss, wins, losses } } } } }
function aggregateRestChoices(filteredRuns) {
  const chars = DATA.characters;
  const ascs  = DATA.ascensions;

  // bucket[char][asc][act][choice] — act is 1/2/3 or "FULL" (reached Act 3, all acts summed)
  // winFreq/lossFreq are arrays where index = count, value = number of runs with that count
  const newBucket = () => ({ winFreq: [], lossFreq: [], wins: 0, losses: 0 });
  const addFreq = (freq, count) => { freq[count] = (freq[count] || 0) + 1; };

  const bucket = {};
  [...chars, "ALL"].forEach(c => {
    bucket[c] = {};
    [...ascs, "ALL"].forEach(a => {
      bucket[c][a] = {};
      [...REST_ACTS, "FULL"].forEach(act => {
        bucket[c][a][act] = {};
        REST_CHOICES.forEach(ch => { bucket[c][a][act][ch] = newBucket(); });
      });
    });
  });

  filteredRuns.forEach(run => {
    const char = run.char;
    const asc  = run.asc;
    const rc   = run.restChoices || {};  // { "1": {HEAL:2,...}, "2": {...}, ... }
    const reachedAct3 = rc["3"] !== undefined;

    // Per-act buckets
    REST_ACTS.forEach(act => {
      const actChoices = rc[String(act)];
      if (actChoices === undefined) return;
      REST_CHOICES.forEach(choice => {
        const count = actChoices[choice] || 0;
        for (const c of [char, "ALL"]) {
          for (const a of [asc, "ALL"]) {
            const b = bucket[c]?.[a]?.[act]?.[choice];
            if (!b) continue;
            if (run.won) { addFreq(b.winFreq,  count); b.wins  += 1; }
            else         { addFreq(b.lossFreq, count); b.losses += 1; }
          }
        }
      });
    });

    // FULL bucket: runs that reached Act 3, total choices across all acts
    if (reachedAct3) {
      REST_CHOICES.forEach(choice => {
        const totalCount = REST_ACTS.reduce((sum, act) => sum + ((rc[String(act)] || {})[choice] || 0), 0);
        for (const c of [char, "ALL"]) {
          for (const a of [asc, "ALL"]) {
            const bf = bucket[c]?.[a]?.["FULL"]?.[choice];
            if (!bf) continue;
            if (run.won) { addFreq(bf.winFreq,  totalCount); bf.wins  += 1; }
            else         { addFreq(bf.lossFreq, totalCount); bf.losses += 1; }
          }
        }
      });
    }
  });

  const freqMean = (freq, n) => {
    if (!n) return null;
    const sum = freq.reduce((s, f, i) => s + f * i, 0);
    return +(sum / n).toFixed(1);
  };

  // Summarize to averages
  const result = {};
  [...chars, "ALL"].forEach(c => {
    result[c] = {};
    [...ascs, "ALL"].forEach(a => {
      result[c][a] = {};
      [...REST_ACTS, "FULL"].forEach(act => {
        result[c][a][act] = {};
        REST_CHOICES.forEach(choice => {
          const b = bucket[c][a][act][choice];
          result[c][a][act][choice] = {
            avgWin:  freqMean(b.winFreq,  b.wins),
            avgLoss: freqMean(b.lossFreq, b.losses),
            wins:    b.wins,
            losses:  b.losses,
          };
        });
      });
    });
  });

  return result;
}

function renderRestChoicesTable(data, filteredRuns) {
  const chars = DATA.characters;
  const ascs  = DATA.ascensions;

  const hasData = filteredRuns.some(r => {
    const rc = r.restChoices || {};
    return REST_ACTS.some(act => rc[String(act)]);
  });
  if (!hasData) {
    document.getElementById("rest-choices-table").innerHTML =
      `<tbody><tr><td style="color:#8a8aa0;padding:1rem">No rest site data in filtered runs.</td></tr></tbody>`;
    return;
  }

  const color = "#7ec8a0";
  const subStyle = `font-size:0.72rem;color:#8a8aa0;letter-spacing:0;text-transform:none;font-weight:400`;
  const DIVIDER = "border-top:2px solid #3f4147;";

  let html = `<thead><tr>
    <th class="char-head">Character</th>
    <th style="color:#bcbcd0;font-size:0.72rem;text-transform:uppercase;letter-spacing:.05em;padding:0.5rem 0.9rem">Act</th>
    <th style="border-right:2px solid #3f4147;color:#bcbcd0;font-size:0.72rem;text-transform:uppercase;letter-spacing:.05em;padding:0.5rem 0.9rem">Choice</th>
    ${ascs.map(a => `<th>A${a}</th>`).join("")}
    <th style="border-left:2px solid #3f4147;text-align:center;padding:0.5rem 0.9rem;color:#bcbcd0;font-size:0.72rem;text-transform:uppercase;letter-spacing:.05em">
      ALL<br><span style="${subStyle}">Win avg / Loss avg</span></th>
  </tr></thead><tbody>`;

  const fmtVal = (v, col) => v != null
    ? `<span style="color:${col}">${v}</span>`
    : `<span style="color:#8a8aa0">—</span>`;

  // Run count (the only part of the old hover tooltip that wasn't already
  // visible as the win/loss avg above it) is shown directly as a sub-line
  // instead, so the cell is self-contained and needs no hover at all.
  const runsMeta = d => `<div class="meta">${d.wins + d.losses} runs (${d.wins}W / ${d.losses}L)</div>`;

  const dataCell = (d, extraStyle = "") => {
    if (!d || (d.avgWin == null && d.avgLoss == null))
      return `<td class="cell empty" style="${extraStyle}">—</td>`;
    const w = fmtVal(d.avgWin,  color);
    const l = fmtVal(d.avgLoss, color + "88");
    return `<td class="cell" style="${extraStyle}font-size:0.82rem">${w} / ${l}${runsMeta(d)}</td>`;
  };

  const allCell = (d, extraStyle = "") => {
    const border = `border-left:2px solid #3f4147;`;
    if (!d || (d.avgWin == null && d.avgLoss == null))
      return `<td class="cell all-col empty" style="${border}${extraStyle}">—</td>`;
    const w = fmtVal(d.avgWin,  color);
    const l = fmtVal(d.avgLoss, color + "88");
    return `<td class="cell all-col" style="${border}${extraStyle}font-size:0.82rem">${w} / ${l}${runsMeta(d)}</td>`;
  };

  // Render each character as two <tbody> blocks:
  //   - act-rows tbody (hidden by default, toggled by clicking the char cell)
  //   - full-row tbody (always visible)
  // This avoids rowspan breakage when hiding rows.

  const renderCharBlock = (charKey, col, nameCell) => {
    const tbodyId = `rest-acts-${charKey}`;
    const fullRowspan = REST_CHOICES.length;
    const totalRowspan = fullRowspan + REST_ACTS.length * REST_CHOICES.length;

    // All Acts tbody first (always visible) — char name cell spans all rows via rowspan
    // The char name rowspan covers both this tbody and the acts tbody below via CSS tricks —
    // instead we just put the char cell in the All Acts row and use a separate column for acts.
    html += `<tbody>`;
    REST_CHOICES.forEach((choice, choiceI) => {
      const isFirst = choiceI === 0;
      const fullSep = isFirst ? DIVIDER : "";
      html += `<tr>`;
      if (isFirst) {
        html += `<td class="char-name" rowspan="${fullRowspan}" role="button" tabindex="0" aria-expanded="false" style="vertical-align:middle;${DIVIDER}cursor:pointer;user-select:none"
          onclick="const b=document.getElementById('${tbodyId}');const open=b.style.display!=='none';b.style.display=open?'none':'';const c=this.querySelector('.rest-expand-caret');if(c)c.textContent=open?'▸':'▾';this.setAttribute('aria-expanded',open?'false':'true')"
          onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}">
          ${nameCell} <span class="rest-expand-caret" aria-hidden="true" style="color:#8a8aa0">▸</span></td>`;
      }
      html += `<td class="cell" style="${fullSep}text-align:center;color:#bcbcd0;font-size:0.78rem;padding:0.35rem 0.5rem">${isFirst ? `<span style="color:#bcbcd0">All Acts</span><br><span style="font-size:0.72rem;color:#8a8aa0">Reached Act 3</span>` : ""}</td>`;
      html += `<td class="cell" style="${fullSep}text-align:left;border-right:2px solid #3f4147;color:#ccc;font-size:0.8rem;padding:0.35rem 0.7rem">${REST_CHOICE_LABELS[choice]}</td>`;
      ascs.forEach(asc => { html += dataCell(data[charKey]?.[asc]?.["FULL"]?.[choice], fullSep); });
      html += allCell(data[charKey]?.["ALL"]?.["FULL"]?.[choice], fullSep);
      html += `</tr>`;
    });
    html += `</tbody>`;

    // Act rows tbody (hidden by default, expands below All Acts row)
    html += `<tbody id="${tbodyId}" style="display:none">`;
    REST_ACTS.forEach((act, actI) => {
      REST_CHOICES.forEach((choice, choiceI) => {
        const isFirstChoice = choiceI === 0;
        const sep = isFirstChoice ? "border-top:1px solid #1a1a3a;" : "";
        html += `<tr>`;
        if (isFirstChoice) html += `<td class="cell" rowspan="${REST_CHOICES.length}" style="${sep}text-align:center;color:#a0a0b8;font-size:0.78rem;padding:0.35rem 0.5rem">Act ${act}</td>`;
        html += `<td class="cell" style="${sep}text-align:left;border-right:2px solid #3f4147;color:#ccc;font-size:0.8rem;padding:0.35rem 0.7rem">${REST_CHOICE_LABELS[choice]}</td>`;
        ascs.forEach(asc => { html += dataCell(data[charKey]?.[asc]?.[act]?.[choice], sep); });
        html += allCell(data[charKey]?.["ALL"]?.[act]?.[choice], sep);
        html += `</tr>`;
      });
    });
    html += `</tbody>`;
  };

  chars.forEach(char => {
    const col   = CHAR_COLOR_MAP[char] || "#a0a0b8";
    const label = fmtCharName(char);
    const nameCell = `<span class="dot" style="background:${col}"></span>${label}`;
    renderCharBlock(char, col, nameCell);
  });

  renderCharBlock("ALL", "#e0c468", `<span style="color:#e0c468">All Characters</span>`);

  document.getElementById("rest-choices-table").innerHTML = html;
}


