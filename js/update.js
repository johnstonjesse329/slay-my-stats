// -------------------------------------------------------------------------
// Main update function — called whenever a filter changes
// -------------------------------------------------------------------------

function updateAll() {
  const filteredRuns = filterRuns();
  // "ALL" columns mean "every ascension the player has run", not "whichever
  // ascensions are currently checked" -- see filterRuns()'s ignoreAsc option.
  const allAscRuns = filterRuns({ ignoreAsc: true });

  const { pivot, grand, charStats } = aggregateRuns(filteredRuns, allAscRuns);

  winChart.data.datasets[0].data       = charStats.map(s => s.win_pct    ?? 0);
  floorChart.data.datasets[0].data     = charStats.map(s => s.median_floor ?? 0);
  timeChart.data.datasets[0].data      = charStats.map(s => s.median_min   ?? 0);
  totalTimeChart.data.datasets[0].data = charStats.map(s => s.total_hrs  ?? 0);
  [winChart, floorChart, timeChart, totalTimeChart].forEach(chart => chart.data.datasets[0].meta = charStats);
  const totalHrs = charStats.reduce((sum, s) => sum + (s.total_hrs ?? 0), 0);
  timeShareChart.data.datasets[0].data = charStats.map(s => totalHrs > 0 ? +((s.total_hrs ?? 0) / totalHrs * 100).toFixed(1) : 0);
  timeShareChart.data.datasets[0].meta  = charStats;
  [winChart, floorChart, timeChart, totalTimeChart, timeShareChart].forEach(chart => chart.update());

  renderCards(grand, charStats, avgRestOnWins(filteredRuns));
  renderWinPivot(pivot);
  renderDeckPivot("cards-table",  pivot, "median_win_cards",  "median_win_cards",  "median_loss_cards",  "min_win_cards",  "max_win_cards",  "#9ecfff");
  renderDeckPivot("relics-table", pivot, "median_win_relics", "median_win_relics", "median_loss_relics", "min_win_relics", "max_win_relics", "#c49fe8");
  renderDeckPivot("elites-table", pivot, "median_win_elites", "median_win_elites", "median_loss_elites", "min_win_elites", "max_win_elites", "#e0c468");
  renderStarterCardsTable(aggregateStarterCards(filteredRuns));
  renderFinalBossWinPivot(filteredRuns, allAscRuns);
  renderRestChoicesTable(aggregateRestChoices(filteredRuns, allAscRuns), filteredRuns);
  updateRestWinCharts(filteredRuns);
  updateEliteActCharts(filteredRuns);
  updateMonthlyWinChart(filteredRuns);
  updateAscWinChart(filteredRuns);
  renderPersonalBests();
}


// -------------------------------------------------------------------------
// Shared filter state — used identically by all 5 pages.
// See "Filter architecture" in CLAUDE.md for the full design.
// -------------------------------------------------------------------------

const allTimestamps = DATA.runsData.map(run => run.ts);
const minTs = allTimestamps.length ? Math.min(...allTimestamps) : 0;
const maxTs = allTimestamps.length ? Math.max(...allTimestamps) : 0;

function tsToDateStr(ts) {
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
}

// Parses a "YYYY-MM-DD" date input value as local midnight, returning unix seconds.
function dateStrToLocalTs(dateStr) {
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(y, m - 1, d).getTime() / 1000;
}

let sharedActiveChar   = "ALL";
// The character preference that applies to the three pages that don't
// constrain it (Card Stats, Run Detail, Seed Data) — see charIsLocked()
// below. sharedActiveChar itself gets temporarily forced away from this
// while Overview or Character Detail is active (each computes its own
// required value independently); lastUnlockedChar is what showPage()
// restores sharedActiveChar to the moment you land back on an unlocked
// page, so a real character selection survives cycling through any
// number of locked pages in between instead of getting silently replaced
// by whatever the last-visited locked page happened to force it to.
let lastUnlockedChar   = "ALL";
// The ascension ranges the tables group their columns by (next to an "All"
// column) unless granular view is on. A bucket the player has no runs in is
// dropped, since DATA.ascensions only lists levels that appear in runs.
const ASC_BUCKETS = [
  { key: "A0-9", label: "A0–9", min: 0,  max: 9 },
  { key: "A10",  label: "A10",  min: 10, max: 10 },
].map(b => ({ ...b, ascs: DATA.ascensions.filter(a => a >= b.min && a <= b.max) }))
 .filter(b => b.ascs.length);
let sharedActiveAscs   = new Set(DATA.ascensions);
// "Show granular" reveals the per-level ascension checkboxes and splits the tables
// into one column per level instead of per ASC_BUCKETS range. With it off,
// every level is included.
let sharedAscGranular  = false;

// The ascension columns every per-ascension table renders before its ALL
// column: the ASC_BUCKETS ranges by default, or each checked level when
// granular. Tables key their buckets by ascColumnKey(run.asc) to match.
function ascColumns() {
  if (!sharedAscGranular) return ASC_BUCKETS;
  return [...sharedActiveAscs].sort((a, b) => a - b).map(a => ({ key: a, label: `A${a}`, ascs: [a] }));
}

function ascColumnKey(asc) {
  return sharedAscGranular ? asc : ASC_BUCKETS.find(b => b.ascs.includes(asc))?.key;
}
let sharedActiveBuilds = new Set(DATA.builds);
let sharedActiveMode   = "solo";
// 0 / TS_NO_UPPER_BOUND mean "no bound" rather than a snapshot of the
// current file's actual min/max run timestamp — this matters because a
// saved preference (see Save/Reset below) has to survive future
// regenerations that add runs past whatever the newest run happened to be
// on save day. Storing a concrete timestamp for "all time" would silently
// exclude every run added after that save, which is exactly the bug this
// sentinel avoids. A large finite number, not Infinity: Infinity doesn't
// survive JSON.stringify (it serializes to null), which would silently
// turn "no upper bound" into "exclude every run" the moment this value is
// saved to and reloaded from localStorage.
const TS_NO_UPPER_BOUND = Number.MAX_SAFE_INTEGER;
let sharedTsFrom       = 0;
let sharedTsTo         = TS_NO_UPPER_BOUND;

// Declared here (not near the Save/Reset buttons that use them) because
// setSharedMode("solo") below runs during the filter bar's own initial
// setup and triggers rerenderCurrentPage() -> updateUnsavedIndicator(),
// which reads both of these — they must exist before any control's
// default wiring can possibly call that chain, not just before the
// buttons that visibly use them render.
const SHARED_FILTER_STORAGE_KEY = "sts2_filter_prefs";
const SHARED_FILTER_HARDCODED_DEFAULTS = {
  char: "ALL", ascGranular: false, builds: [...DATA.builds],
  mode: "solo", tsFrom: 0, tsTo: TS_NO_UPPER_BOUND,
};

// opts.ignoreAsc skips the ascension checkbox filter, for building the
// "ALL" column of per-ascension tables -- it should mean "every ascension
// this player has run" (subject to every other active filter), not
// "whichever ascensions happen to be checked right now".
function filterRuns(opts = {}) {
  return DATA.runsData.filter(run => {
    if (sharedActiveChar !== "ALL" && run.char !== sharedActiveChar) return false;
    if (!opts.ignoreAsc && !sharedActiveAscs.has(run.asc)) return false;
    if (!sharedActiveBuilds.has(run.build)) return false;
    if (run.ts < sharedTsFrom || run.ts > sharedTsTo) return false;
    if (sharedActiveMode === "solo"  && (run.mp || run.mode === "daily")) return false;
    if (sharedActiveMode === "multi" && !run.mp)                          return false;
    if (sharedActiveMode === "daily" && run.mode !== "daily")             return false;
    return true;
  });
}

function filteredRunTsSet(opts = {}) {
  return new Set(filterRuns(opts).map(r => r.ts));
}

// Character Detail is inherently single-character (its tables only make
// sense for one character's kit at a time) and can't render for "All
// Characters" — it falls back to the most-played character in the
// current filtered view, so the default drill-down opens on dense data
// rather than a sparsely-played character full of "—" cells. (Card Stats
// does NOT use this — it genuinely aggregates across every character's
// card pool when "All" is selected; see Filter architecture in
// CLAUDE.md.) showPage() also pushes this fallback into the SHARED
// character filter itself when landing on this tab with "All" active, so
// the filter bar and the page can never show conflicting state.
function singleCharFallback() {
  if (sharedActiveChar !== "ALL") return sharedActiveChar;
  const counts = {};
  filterRuns().forEach(r => { counts[r.char] = (counts[r.char] || 0) + 1; });
  let best = "", bestN = 0;
  Object.entries(counts).forEach(([char, n]) => { if (n > bestN) { best = char; bestN = n; } });
  return best || DATA.characters[0] || "";
}

