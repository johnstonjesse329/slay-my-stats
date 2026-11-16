/*
  All the JavaScript that powers the interactive dashboard.

  DATA is provided as a global before this bundle runs: for the local build,
  run.py's build_html() emits an inline `const DATA = ...;` ahead of the
  concatenated js/*.js; on the live site, boot.js fetches /catalog.json and
  the user's data blob, builds `window.DATA` from them, then loads /app.js.

  Shape of DATA:
    characters      : ["DEFECT", "IRONCLAD", ...]
    charColors      : ["#5b9bd5", "#e05c5c", ...]   (read through charColor(char), not by index)
    ascensions      : [0, 1, 2, ...]
    runsData        : [{char, asc, won, floor, mins, cards, relics, ts, mp, mode}, ...]
*/

// Dread (the game's mode past A10) is its own rung on the ascension filter and in the
// per-ascension tables: A10 is a very different game. Its runs carry asc 10 in the data,
// so everything that groups or filters by ascension asks runAsc(run) instead.
const DREAD_ASC = 11;
const runAsc = run => run.mode === "dread" ? DREAD_ASC : run.asc;
const ascLabel = asc => asc === DREAD_ASC ? "Dread" : `A${asc}`;
// Win rate and record, formatted once. winPctNum is the stored/charted number, one decimal
// (what a chart plots and a table sorts by); fmtWinPct is the whole-percent text a table cell
// or caption shows. Both read an empty bucket as "no data" (null, "—"), never 0%.
const winPctNum = (wins, runs) => runs ? +(wins / runs * 100).toFixed(1) : null;
const fmtWinPct = (wins, runs) => runs ? `${Math.round(wins / runs * 100)}%` : "—";
const fmtRecord = (wins, losses) => `${wins}W / ${losses}L`;

// The ascension as a label's html: "A7", or Dread's own icon and name. Takes a runAsc(), never
// run.asc, so a Dread run never reads as A10. `cls` is the icon's class, since each place sizes it.
const ascHtml = (asc, cls = "asc-filter-dread", iconTip = false) => asc === DREAD_ASC
  ? `<img class="${cls}" src="/ui_icons/dread.png" alt="${iconTip ? "Dread" : ""}"${iconTip ? ` data-tip="Dread"` : ""}>${iconTip ? "" : "Dread"}`
  : ascLabel(asc);
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
      DATA.charColors.push(CHAR_FALLBACK_COLOR);
    }
  });
}

// A character's colour, by name: the one lookup (DATA.charColors is parallel to the roster
// above and is not read by position anywhere else), with one fallback for a character no colour
// list knows. CHAR_FALLBACK_COLOR lives in tooltip.js so the finder page can use it too.
const CHAR_COLORS = Object.fromEntries(DATA.characters.map((char, i) => [char, DATA.charColors[i]]));
const charColor = char => CHAR_COLORS[char] || CHAR_FALLBACK_COLOR;

// The win/loss/accent colours, read from the tokens in dashboard.css's :root (--win, --loss,
// --gold, --warn) so a script and the stylesheet never hold two copies. The literals are the
// fallback for a page without the stylesheet. Character, card-type and act reds mean something
// else and keep their own values.
const COLORS = (() => {
  const css = getComputedStyle(document.documentElement);
  const read = (name, fallback) => css.getPropertyValue(name).trim() || fallback;
  return {
    win:  read("--win",  "#5cba7d"),
    loss: read("--loss", "#e05c5c"),
    gold: read("--gold", "#e0c468"),
    warn: read("--warn", "#e0c468"),
  };
})();

// What "phone" means: the CSS breakpoints, which these must match (dashboard.css @media
// max-width 700px for the layout, 560px for the narrowest tweaks). PHONE_MQ is exposed for the
// places that redraw when the screen crosses the breakpoint.
const PHONE_BP = 700;
const SMALL_PHONE_BP = 560;
const PHONE_MQ = window.matchMedia(`(max-width: ${PHONE_BP}px)`);
const SMALL_PHONE_MQ = window.matchMedia(`(max-width: ${SMALL_PHONE_BP}px)`);
const isPhone = () => PHONE_MQ.matches;
const isSmallPhone = () => SMALL_PHONE_MQ.matches;

Chart.defaults.color = "#d2cdea";
Chart.defaults.scale.ticks.color = "#d2cdea";
Chart.defaults.scales.category.ticks.color = "#d2cdea";

