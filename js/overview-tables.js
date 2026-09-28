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

  // Strikes and Defends are rows, each act a Won / Lost column pair (the
  // same header as Rest Site Choices), so every cell is one bare number.
  // Cells used to pack "W / L" for two card types under a three-level header.
  const thHead = `color:#bcbcd0;font-size:0.72rem;text-transform:uppercase;letter-spacing:.05em;padding:0.5rem 0.6rem`;
  const thSub  = `font-size:0.72rem;color:#8a8aa0;font-weight:400;text-align:center`;
  const groups = [...acts.map(a => ({ key: a, label: `Act ${a}`, border: "1px" })), { key: "ALL", label: "ALL", border: "2px", all: true }];
  let html = `<thead><tr>
    <th class="char-head" rowspan="2">Character</th>
    <th rowspan="2" style="${thHead}">Card</th>
    ${groups.map(g => `<th colspan="2" class="${g.all ? "all-col" : ""}" style="border-left:${g.border} solid #3f4147;text-align:center">${g.label}</th>`).join("")}
  </tr><tr>
    ${groups.map(g => `<th class="${g.all ? "all-col" : ""}" style="${thSub};border-left:${g.border} solid #3f4147">Won</th><th class="${g.all ? "all-col" : ""}" style="${thSub}">Lost</th>`).join("")}
  </tr></thead>`;

  const cell = (v, isLoss, style, cls) => v == null
    ? `<td class="${cls} empty" style="${style}">—</td>`
    : `<td class="${cls}" style="${style}font-size:0.88rem;color:${isLoss ? "#e05c5c" : "#5cba7d"};${isLoss ? "" : "font-weight:600"}">${v}</td>`;

  const DIVIDER = "border-top:2px solid #3f4147;";
  const blockHtml = (rowData, nameHtml, nameStyle = "") => {
    let r = `<tbody>`;
    [["Strikes", "Strikes"], ["Defends", "Defends"]].forEach(([label, key], i) => {
      const sep = i === 0 ? DIVIDER : "";
      r += `<tr>${i === 0 ? `<td class="char-name" rowspan="2" style="vertical-align:middle;${DIVIDER}${nameStyle}">${nameHtml}</td>` : ""}`;
      r += `<td class="cell" style="${sep}text-align:left;color:#ccc;font-size:0.8rem;padding:0.35rem 0.6rem">${label}</td>`;
      groups.forEach(g => {
        const d = rowData?.[g.key];
        const cls = "cell" + (g.all ? " all-col" : "");
        r += cell(d?.[`avgWin${key}`], false, `${sep}border-left:${g.border} solid #3f4147;`, cls);
        r += cell(d?.[`avgLoss${key}`], true, sep, cls);
      });
      r += `</tr>`;
    });
    return r + `</tbody>`;
  };

  chars.forEach(char => {
    html += blockHtml(data[char],
      `<span class="dot" style="background:${CHAR_COLOR_MAP[char] || "#a0a0b8"}"></span>${fmtCharName(char)}`);
  });
  html += blockHtml(data["ALL"], "All Characters", "color:#e0c468");

  document.getElementById("starter-cards-table").innerHTML = html;
}


// -------------------------------------------------------------------------
// Rest site choices table (Overview page)
// -------------------------------------------------------------------------

const REST_ACTS = [1, 2, 3];
const REST_CHOICES = ["HEAL", "SMITH"];
const REST_CHOICE_LABELS = { HEAL: "Heal", SMITH: "Smith" };

// Returns { char: { asc: { act: { choice: { avgWin, avgLoss, wins, losses } } } } }
function aggregateRestChoices(filteredRuns, allAscRuns) {
  const chars = DATA.characters;
  const ascs  = ascColumns().map(col => col.key);

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

  // ascKeys picks which asc column(s) this run feeds -- the run's own
  // column when accumulating the filtered set, or just "ALL" when
  // accumulating the ascension-unfiltered set for the ALL column.
  function accumulate(run, ascKeys) {
    const char = run.char;
    const rc   = run.restChoices || {};  // { "1": {HEAL:2,...}, "2": {...}, ... }
    const reachedAct3 = rc["3"] !== undefined;

    // Per-act buckets
    REST_ACTS.forEach(act => {
      const actChoices = rc[String(act)];
      if (actChoices === undefined) return;
      REST_CHOICES.forEach(choice => {
        const count = actChoices[choice] || 0;
        for (const c of [char, "ALL"]) {
          for (const a of ascKeys) {
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
          for (const a of ascKeys) {
            const bf = bucket[c]?.[a]?.["FULL"]?.[choice];
            if (!bf) continue;
            if (run.won) { addFreq(bf.winFreq,  totalCount); bf.wins  += 1; }
            else         { addFreq(bf.lossFreq, totalCount); bf.losses += 1; }
          }
        }
      });
    }
  }

  filteredRuns.forEach(run => accumulate(run, [ascColumnKey(run.asc)]));
  allAscRuns.forEach(run => accumulate(run, ["ALL"]));

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
  const ascs  = ascColumns();

  const hasData = filteredRuns.some(r => {
    const rc = r.restChoices || {};
    return REST_ACTS.some(act => rc[String(act)]);
  });
  if (!hasData) {
    document.getElementById("rest-choices-table").innerHTML =
      `<tbody><tr><td style="color:#8a8aa0;padding:1rem">No rest site data in filtered runs.</td></tr></tbody>`;
    return;
  }

  const DIVIDER = "border-top:2px solid #3f4147;";

  // Each ascension column splits into Won / Lost sub-columns (the same
  // two-row header as Starter Cards Entering Boss), so the header says which
  // number is which and each cell holds one bare number. Packing both
  // averages, W/L tags and a run-count line into one cell read as noise.
  const thHead = `color:#bcbcd0;font-size:0.72rem;text-transform:uppercase;letter-spacing:.05em;padding:0.5rem 0.9rem`;
  const thSub  = `font-size:0.72rem;color:#8a8aa0;font-weight:400;text-align:center`;
  const groups = [...ascs.map(col => ({ label: col.label, border: "1px" })), { label: "ALL", border: "2px", all: true }];
  let html = `<thead><tr>
    <th class="char-head" rowspan="2">Character</th>
    <th rowspan="2" style="${thHead}">Act</th>
    <th rowspan="2" style="border-right:2px solid #3f4147;${thHead}">Choice</th>
    ${groups.map(g => `<th colspan="2" class="${g.all ? "all-col" : ""}" style="border-left:${g.border} solid #3f4147;text-align:center">${g.label}</th>`).join("")}
  </tr><tr>
    ${groups.map(g => `<th class="${g.all ? "all-col" : ""}" style="${thSub};border-left:${g.border} solid #3f4147">Won</th><th class="${g.all ? "all-col" : ""}" style="${thSub}">Lost</th>`).join("")}
  </tr></thead><tbody>`;

  // Run counts live in the hover tip rather than on the face of the cell.
  const valCell = (v, n, isLoss, style) => {
    if (v == null) return `<td class="cell empty" style="${style}">—</td>`;
    const tip = `${n} ${isLoss ? "lost" : "won"} run${n === 1 ? "" : "s"}`;
    return `<td class="cell" style="${style}font-size:0.88rem;color:${isLoss ? "#e05c5c" : "#5cba7d"};${isLoss ? "" : "font-weight:600"}" data-tip="${tip}">${v}</td>`;
  };
  const pairCells = (d, extraStyle, border, isAll = false) => {
    const cls = isAll ? "all-col " : "";
    const first = `${extraStyle}border-left:${border} solid #3f4147;`;
    return (valCell(d?.avgWin, d?.wins, false, first) + valCell(d?.avgLoss, d?.losses, true, extraStyle))
      .replaceAll(`<td class="cell`, `<td class="${cls}cell`);
  };
  const dataCell = (d, extraStyle = "") => pairCells(d, extraStyle, "1px");
  const allCell  = (d, extraStyle = "") => pairCells(d, extraStyle, "2px", true);

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
      ascs.forEach(col => { html += dataCell(data[charKey]?.[col.key]?.["FULL"]?.[choice], fullSep); });
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
        // The char-name cell's rowspan can't reach into this separate tbody,
        // so the Character column needs its own blank cell here or every
        // act row shifts one column left.
        if (actI === 0 && isFirstChoice) html += `<td rowspan="${REST_ACTS.length * REST_CHOICES.length}"></td>`;
        if (isFirstChoice) html += `<td class="cell" rowspan="${REST_CHOICES.length}" style="${sep}text-align:center;color:#a0a0b8;font-size:0.78rem;padding:0.35rem 0.5rem">Act ${act}</td>`;
        html += `<td class="cell" style="${sep}text-align:left;border-right:2px solid #3f4147;color:#ccc;font-size:0.8rem;padding:0.35rem 0.7rem">${REST_CHOICE_LABELS[choice]}</td>`;
        ascs.forEach(col => { html += dataCell(data[charKey]?.[col.key]?.[act]?.[choice], sep); });
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


