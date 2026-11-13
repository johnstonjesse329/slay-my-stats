// -------------------------------------------------------------------------
// Main update function — called whenever a filter changes
// -------------------------------------------------------------------------

function updateAll() {
  const filteredRuns = filterRuns();

  const { pivot, grand, charStats } = aggregateRuns(filteredRuns);

  renderCards(grand, charStats, avgRestOnWins(filteredRuns));
  renderTimeLanes(pivot);
  renderRunEndLanes(pivot);
  renderFightTables();
  renderFinalBossWinPivot(filteredRuns);
  updateRestActCharts(filteredRuns);
  updateEliteActCharts(filteredRuns);
  updateMonthlyWinChart(filteredRuns);
  updateAscWinChart(filteredRuns);
  renderPersonalBests();
  renderAscTracker();
}


// -------------------------------------------------------------------------
// Shared filter state — used identically by all 4 pages.
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
// while Overview is active (it always shows every character);
// lastUnlockedChar is what showPage() restores sharedActiveChar to the
// moment you land back on an unlocked page, so a real character selection
// survives a visit to Overview instead of being silently replaced by "ALL".
let lastUnlockedChar   = "ALL";
// The ascension ranges the tables group their columns by (next to an "All"
// column) unless granular view is on: the run page's tuning tiers (keepTier in
// run-detail.js), so a table and a run's grading split at the same place. A bucket the player has no runs in is
// dropped, since DATA.ascensions only lists levels that appear in runs.
const ASC_BUCKETS = [
  { key: "A0-7", label: "A0–7", min: 0, max: 7 },
  { key: "A8+",  label: "A8+",  min: 8, max: Infinity },
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
// "all" | "solo" | "multi", and the ticked game modes (see modeShowsRun).
let sharedActivePlayers = "all";
let sharedActiveModes   = new Set(["standard", "daily", "dread"]);
// "all" | "vanilla" | "modded": whether runs the game mod reported loaded mods
// for are shown (see modsShowRun).
let sharedActiveMods   = "all";
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
// setSharedPlayers("all") below runs during the filter bar's own initial
// setup and triggers rerenderCurrentPage() -> updateUnsavedIndicator(),
// which reads both of these — they must exist before any control's
// default wiring can possibly call that chain, not just before the
// buttons that visibly use them render.
const SHARED_FILTER_STORAGE_KEY = "sts2_filter_prefs";
const SHARED_FILTER_HARDCODED_DEFAULTS = {
  char: "ALL", ascGranular: false, builds: [...DATA.builds],
  players: "all", modes: ["standard", "daily", "dread"], mods: "all", tsFrom: 0, tsTo: TS_NO_UPPER_BOUND,
};

// Game modes with their own rules and stats (no map in Blitz, a separate ascension
// track, a custom run's modifiers). A run with no run.mode is a standard run.
const OWN_MODES = ["daily", "blitz", "dread", "custom"];
const ALL_MODES = ["standard", ...OWN_MODES];
const MODE_LABELS = { standard: "Standard", daily: "Daily", blitz: "Blitz", dread: "Dread", custom: "Custom" };
function runModeOf(run) { return run.mode || "standard"; }

// Whether the Players (all / solo / multi) and Modes filters let a run through.
function modeShowsRun(players, modes, run) {
  if (players === "solo"  &&  run.mp) return false;
  if (players === "multi" && !run.mp) return false;
  return modes.has(runModeOf(run));
}

// Saves from before the Players/Modes split carry one `mode` value.
function savedModeState(state) {
  if (state.players) {
    return { players: state.players, modes: (state.modes || []).filter(m => ALL_MODES.includes(m)) };
  }
  const old = state.mode || "all";
  if (old === "solo" || old === "multi") return { players: old, modes: ["standard"] };
  if (OWN_MODES.includes(old)) return { players: "all", modes: [old] };
  return { players: "all", modes: [...SHARED_FILTER_HARDCODED_DEFAULTS.modes] };
}

// Whether the Mods filter lets a run through. A run uploaded from files says
// nothing about mods (no run.mods), so "unmodded" means "not known to be modded".
function runIsModded(run) { return (run.mods || []).length > 0; }
function modsShowRun(mods, run) {
  if (mods === "modded")  return runIsModded(run);
  if (mods === "vanilla") return !runIsModded(run);
  return true;
}

function filterRuns() {
  return DATA.runsData.filter(run => {
    if (sharedActiveChar !== "ALL" && run.char !== sharedActiveChar) return false;
    if (!sharedActiveAscs.has(run.asc))     return false;
    if (!sharedActiveBuilds.has(run.build)) return false;
    if (run.ts < sharedTsFrom || run.ts > sharedTsTo) return false;
    return modeShowsRun(sharedActivePlayers, sharedActiveModes, run) && modsShowRun(sharedActiveMods, run);
  });
}

function filteredRunTsSet() {
  return new Set(filterRuns().map(r => r.ts));
}
