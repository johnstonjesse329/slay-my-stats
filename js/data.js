/*
  All the JavaScript that powers the interactive dashboard.

  DATA is provided as a global before this bundle runs: for the local build,
  run.py's build_html() emits an inline `const DATA = ...;` ahead of the
  concatenated js/*.js; on the live site, boot.js fetches /catalog.json and
  the user's data blob, builds `window.DATA` from them, then loads /app.js.

  Shape of DATA:
    characters      : ["DEFECT", "IRONCLAD", ...]
    charColors      : ["#5b9bd5", "#e05c5c", ...]
    ascensions      : [0, 1, 2, ...]
    runsData        : [{char, asc, won, floor, mins, cards, relics, ts, mp, mode}, ...]
*/

// Dread (the game's mode past A10) is its own rung on the ascension filter and in the
// per-ascension tables: A10 is a very different game. Its runs carry asc 10 in the data,
// so everything that groups or filters by ascension asks runAsc(run) instead.
const DREAD_ASC = 11;
const runAsc = run => run.mode === "dread" ? DREAD_ASC : run.asc;
const ascLabel = asc => asc === DREAD_ASC ? "Dread" : `A${asc}`;
if (DATA.runsData.some(run => run.mode === "dread")) {
  DATA.ascensions = [...new Set(DATA.runsData.map(runAsc))].sort((a, b) => a - b);
}

// The one character roster. Every chart, table and lane iterates DATA.characters, and a
// character found only in the runs (a new one the catalog or colour list lacks) is added
// here, so none can go missing from one chart while shown in another.
{
  const seen = new Set(DATA.characters);
  DATA.runsData.forEach(run => {
    if (run.char && !seen.has(run.char)) {
      seen.add(run.char);
      DATA.characters.push(run.char);
      DATA.charColors.push("#888");
    }
  });
}

Chart.defaults.color = "#d2cdea";
Chart.defaults.scale.ticks.color = "#d2cdea";
Chart.defaults.scales.category.ticks.color = "#d2cdea";

