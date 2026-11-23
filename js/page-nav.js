// =========================================================================
// Page navigation
// =========================================================================

const PAGES = ["overview", "detail", "cards", "relics", "seeds"];
let currentPage = "overview";

// The URL hash names the tab, and on Run Detail the run as well:
// #detail/<run ts>, so the address opens the same run for anyone. A multiplayer
// run's party tab follows it: #detail/<ts>/<partner's slug, or "all">.
function parsePageHash() {
  const [page, ts, view] = location.hash.replace("#", "").split("/");
  const runTs = page === "detail" && /^\d+$/.test(ts || "") ? +ts : null;
  return { page, runTs, view: runTs != null && /^[a-z0-9_-]+$/i.test(view || "") ? view : "" };
}

function pageHash(page) {
  if (page !== "detail" || detailSelectedTs == null) return page;
  return runDetailHash(detailSelectedTs);
}

const PAGE_RENDERERS = {
  overview:  updateAll,
  detail:    renderDetailRunList,
  cards:     renderCardsPage,
  relics:    renderRelicsPage,
  seeds:     renderSeeds,
};

// Whether each page's DOM already reflects the current shared filter state.
// showPage() used to re-render unconditionally on every tab switch — fine
// for cheap pages, but Card Stats rebuilds ~500 rows (each with a portrait
// image) from scratch, which is a visible stutter switching back to a tab
// where nothing actually changed. rerenderCurrentPage() is the single
// chokepoint for filter controls, Reset, and presets, so it's the one place
// that needs to mark every *other* page dirty after rendering.
const pageDirty = Object.fromEntries(PAGES.map(p => [p, true]));

function rerenderCurrentPage() {
  (PAGE_RENDERERS[currentPage] || updateAll)();
  pageDirty[currentPage] = false;
  PAGES.forEach(p => { if (p !== currentPage) pageDirty[p] = true; });
  // Defined further down (near the Save/Reset buttons); by the time any
  // filter control can actually trigger a rerender, the whole script has
  // already finished its initial top-to-bottom run, so this is safe.
  if (typeof updateUnsavedIndicator === "function") updateUnsavedIndicator();
  updateFilterSummary();
  // Keep an opened/copied filter link accurate as its controls change.
  if (sharedFiltersLoaded && new URL(location.href).searchParams.has("filters")) {
    const url = new URL(location.href);
    url.searchParams.set("filters", JSON.stringify(currentSharedFilterState()));
    history.replaceState(null, "", url);
  }
}

// The one-line summary the filter rows collapse behind (.filter-summary in
// dashboard.css; the bar starts collapsed at every width now, not just phone).
// Looks its elements
// up on each call because the filter bar's own setup rerenders before the
// rest of this file has run.
function updateFilterSummary() {
  const playersLabels = { all: "All players", solo: "Solo", multi: "Multi" };
  // Only modes the player has a checkbox for (see the Modes checkboxes below).
  const modes = ALL_MODES.filter(m => sharedActiveModes.has(m)
      && (!["blitz", "dread", "custom"].includes(m) || DATA.runsData.some(r => r.mode === m)))
    .map(m => MODE_LABELS[m]);
  const nAscs = sharedActiveAscs.size;
  const asc = nAscs === DATA.ascensions.length ? "All ascensions"
            : nAscs === 0 ? "No ascensions"
            : [...sharedActiveAscs].sort((a, b) => a - b).map(ascLabel).join(", ");
  const date = sharedTsFrom === 0 && sharedTsTo === TS_NO_UPPER_BOUND ? "All time"
             : `${sharedTsFrom > 0 ? tsToDateStr(sharedTsFrom) : "…"} → ${sharedTsTo !== TS_NO_UPPER_BOUND ? tsToDateStr(sharedTsTo - 86400) : "…"}`;
  const parts = [
    sharedActiveChar === "ALL" ? "All characters" : fmtCharName(sharedActiveChar),
    playersLabels[sharedActivePlayers],
    modes.length ? modes.join(", ") : "No modes",
    ...(sharedActiveMods !== "all" ? [sharedActiveMods === "modded" ? "Modded" : "Unmodded"] : []),
    asc,
    sharedActiveBuilds.size === 1 ? [...sharedActiveBuilds][0] : sharedBuildSummary(),
    date,
  ];
  const locked = currentPage === "overview";
  const visible = DATA.runsData.filter(run => runPassesFilters(run)).length;
  const isDefault = sharedFilterStateEquals(currentSharedFilterState(), SHARED_FILTER_HARDCODED_DEFAULTS);
  const active = !locked && !isDefault;
  const bar = document.getElementById("shared-filter-bar");
  if (sharedFiltersLoaded) syncFilterPresetSelection();
  bar.classList.toggle("filters-locked", locked);
  bar.classList.toggle("filters-active", active);
  bar.querySelectorAll(".filter-row button, .filter-row input, .filter-row select").forEach(control => {
    control.disabled = locked || (control.id === "shared-filter-preset-delete"
      && !document.getElementById("shared-filter-presets").value.startsWith("preset:"));
  });
  document.querySelector("#shared-filter-summary .filter-label").textContent =
    locked ? "Filters locked" : active ? "Filters applied" : "Default filters applied";
  const summary = locked
    ? `Overview · ${overviewMode.selectedOptions[0].text} · ${overviewBuild.selectedOptions[0].text}`
    : `${visible} of ${DATA.runsData.length} runs · ${parts.join(" · ")}`;
  const summaryText = document.querySelector("#shared-filter-summary .filter-summary-text");
  summaryText.textContent = summary;
  summaryText.title = summary;

}

document.getElementById("shared-filter-summary").addEventListener("click", e => {
  const open = document.getElementById("shared-filter-bar").classList.toggle("expanded");
  e.currentTarget.setAttribute("aria-expanded", String(open));
});

function showPage(page) {
  if (!PAGES.includes(page)) page = "overview";
  currentPage = page;
  PAGES.forEach(p => {
    document.getElementById("page-" + p).style.display = p === page ? "" : "none";
    document.getElementById("tab-"  + p).classList.toggle("active", p === page);
  });
  // Overview's charts and tables compare characters side by side, so a
  // single-character selection is disabled there. Landing on it with one
  // selected (e.g. arriving from Card Stats) snaps back to "All" rather than
  // leaving the filter bar and page disagreeing. setSharedActiveChar() (not
  // a direct assignment) so this goes through the same rerenderCurrentPage()
  // chokepoint every other filter change does. isUserPick=false on both
  // branches below: neither is the user choosing a character, so neither
  // should overwrite lastUnlockedChar.
  if (page === "overview" && sharedActiveChar !== "ALL") {
    setSharedActiveChar("ALL", false);
  }
  // Landing on an unlocked page restores whatever character was last
  // actually chosen — without this, a real "Defect" selection would turn
  // into "All" just by passing through Overview on the way somewhere else.
  if (!charIsLocked(page) && sharedActiveChar !== lastUnlockedChar) {
    setSharedActiveChar(lastUnlockedChar, false);
  }
  sharedCharSel.querySelectorAll(".char-btn[data-char]").forEach(btn => {
    btn.disabled = page === "overview";
    btn.title = page === "overview"
      ? "Overview compares every character"
      : "";
  });
  if (pageDirty[page]) {
    (PAGE_RENDERERS[page] || updateAll)();
    pageDirty[page] = false;
  }
  location.hash = pageHash(page);
  updateFilterSummary();
  // Counted by the morning digest (site/boot.js); run.py's local file has no noteView.
  if (window.noteView) noteView(page, page === "detail" ? detailSelectedTs : null);
}

// Jump to a specific run in Run Detail from anywhere else in the app
// (Personal Bests stat links). Setting
// detailSelectedTs alone isn't enough: showPage() only re-renders a page
// when pageDirty[page] is true, and Run Detail won't be dirty if it was
// already rendered earlier in the session, so the jump would silently keep
// showing whatever run was already selected instead of the new one. Force
// it dirty here so a jump always actually lands, regardless of prior state.
function jumpToRun(ts) {
  detailSelectedTs = ts;
  pageDirty.detail = true;
  showPage("detail");
}

// Open the run a #detail/<ts> link names. A link has to work for whoever
// opens it, so any filter that would hide the run is widened first; the
// viewer's other filters stay as they were. A ts this profile has no run
// for lands on Run Detail's usual first run. `view` is the party tab to open on.
function openRunLink(ts, view = "") {
  const run = DATA.runsData.find(r => r.ts === ts);
  const changed = [];
  if (run) {
    const state = currentSharedFilterState();
    const widen = {};
    if (state.char !== "ALL" && state.char !== run.char) widen.char = "ALL";
    if (!sharedActiveAscs.has(runAsc(run))) { widen.ascGranular = false; widen.ascs = undefined; }
    if (!sharedActiveBuilds.has(run.build)) widen.builds = [...DATA.builds];
    if (run.ts < state.tsFrom || run.ts > state.tsTo) { widen.tsFrom = 0; widen.tsTo = TS_NO_UPPER_BOUND; }
    if (state.players !== "all" && (state.players === "multi") !== !!run.mp) widen.players = "all";
    if (!state.modes.includes(runModeOf(run))) widen.modes = [...state.modes, runModeOf(run)];
    if (!modsShowRun(state.mods, run)) widen.mods = "all";
    if (![...detailTags].every(t => runTags(run).includes(t))) { detailTags.clear(); changed.push("tags"); }
    if (!playedWithAll(run)) { detailPartners.clear(); changed.push("played with"); }
    if (!matchesDetailAct(run)) { detailActReached.value = "0"; changed.push("act reached"); }
    const names = { char: "character", ascGranular: "ascension", builds: "build", tsFrom: "date", players: "players", modes: "mode", mods: "mods" };
    Object.keys(names).forEach(key => { if (key in widen) changed.push(names[key]); });
    if (Object.keys(widen).length > 0) {
      applySharedFilterState({ ...state, ...widen }, "detail");
      // Other tabs need to reflect the widened filters when they're opened.
      PAGES.forEach(p => { pageDirty[p] = true; });
      updateUnsavedIndicator();
      updateFilterSummary();
    }
  }
  detailView = { ts, who: view === "self" ? "" : view || defaultPartyView(run) };
  jumpToRun(ts);
  const notice = document.getElementById("detail-jump-notice");
  notice.textContent = changed.length ? `Filters adjusted to show this run: ${changed.join(", ")}.` : "";
  notice.hidden = !changed.length;
}

// A link pasted into the address bar of a page that is already open only
// changes the hash, so nothing reloads. Follow it. The hash this page sets
// itself (showPage) arrives here too, already matching, and does nothing.
window.addEventListener("hashchange", () => {
  const { page, runTs, view } = parsePageHash();
  if (!PAGES.includes(page)) return;
  if (runTs != null && (runTs !== detailSelectedTs || location.hash !== "#" + runDetailHash(runTs))) openRunLink(runTs, view);
  else if (page !== currentPage) showPage(page);
});

// ---- Shared character selector ----
const sharedCharSel = document.getElementById("shared-char-selector");

const sharedAllBtn = document.createElement("button");
sharedAllBtn.className = "char-btn active";
sharedAllBtn.textContent = "All";
sharedAllBtn.style.setProperty("--char-color", COLORS.gold);
sharedAllBtn.addEventListener("click", () => {
  setSharedActiveChar("ALL");
});
sharedCharSel.appendChild(sharedAllBtn);

DATA.characters.forEach(char => {
  const btn = document.createElement("button");
  btn.className = "char-btn";
  btn.style.setProperty("--char-color", charColor(char));
  btn.innerHTML = charIconHtml(char) + fmtCharName(char);
  btn.dataset.char = char;
  // currentPage defaults to "overview" and showPage() doesn't run on a bare
  // load with no URL hash, so the disabled state showPage() would otherwise
  // set needs a matching starting value here too.
  btn.disabled = currentPage === "overview";
  btn.title = btn.disabled
    ? "Overview compares every character"
    : "";
  btn.addEventListener("click", () => setSharedActiveChar(char));
  sharedCharSel.appendChild(btn);
});

// Single setter for sharedActiveChar, mirroring setSharedPlayers() below —
// every caller (these two click handlers, and showPage()'s Overview
// character-filter lock) goes through here instead of
// mutating sharedActiveChar directly, so rerenderCurrentPage()'s dirty
// tracking (see pageDirty) always sees the change without each call site
// needing to remember to flag it by hand.
// `isUserPick` is false only when showPage() calls this to force a
// char-locked page's own required value, or to restore lastUnlockedChar
// when landing on an unlocked page — neither represents the user actually
// choosing a character, so neither should overwrite what they last chose.
function setSharedActiveChar(char, isUserPick = true) {
  sharedActiveChar = char;
  if (isUserPick) lastUnlockedChar = char;
  updateSharedCharBtns();
  rerenderCurrentPage();
}

function updateSharedCharBtns() {
  sharedCharSel.querySelectorAll(".char-btn").forEach(btn => {
    const match = btn.dataset.char ? btn.dataset.char === sharedActiveChar : sharedActiveChar === "ALL";
    btn.classList.toggle("active", match);
  });
}

// ---- Shared ascension filter ----
// Off by default: every level is included and the tables group columns by
// ASC_BUCKETS. "Show granular" reveals the per-level checkboxes.
const sharedAscBox     = document.getElementById("shared-asc-checkboxes");
const sharedAscGranularBtn = document.getElementById("shared-asc-granular");
const sharedAscAll     = document.getElementById("shared-asc-all");
const sharedAscNone    = document.getElementById("shared-asc-none");

function setActive(btn, on) {
  btn.classList.toggle("active", on);
}

function syncAscControls() {
  sharedAscBox.querySelectorAll("input").forEach(cb => {
    cb.checked = sharedActiveAscs.has(+cb.value);
    cb.closest("label").classList.toggle("checked", cb.checked);
  });
  setActive(sharedAscAll,  sharedActiveAscs.size === DATA.ascensions.length);
  setActive(sharedAscNone, sharedActiveAscs.size === 0);
  setActive(sharedAscGranularBtn, sharedAscGranular);
  sharedAscGranularBtn.setAttribute("aria-pressed", String(sharedAscGranular));
  sharedAscBox.style.display = sharedAscGranular ? "flex" : "none";
  sharedAscAll.style.display = sharedAscNone.style.display = sharedAscGranular ? "" : "none";
}

function setSharedAscs(ascs) {
  sharedActiveAscs = new Set(ascs);
  syncAscControls();
  rerenderCurrentPage();
}

DATA.ascensions.forEach(asc => {
  const label = document.createElement("label");
  label.innerHTML = `<input type="checkbox" value="${asc}"> ${ascHtml(asc)}`;
  label.querySelector("input").addEventListener("change", e => {
    const next = new Set(sharedActiveAscs);
    if (e.target.checked) next.add(asc); else next.delete(asc);
    setSharedAscs(next);
  });
  sharedAscBox.appendChild(label);
});

sharedAscAll.addEventListener("click",  () => setSharedAscs(DATA.ascensions));
sharedAscNone.addEventListener("click", () => setSharedAscs([]));

sharedAscGranularBtn.addEventListener("click", () => {
  sharedAscGranular = !sharedAscGranular;
  // Outside granular view every level is included; the picks don't carry over.
  if (!sharedAscGranular) sharedActiveAscs = new Set(DATA.ascensions);
  syncAscControls();
  rerenderCurrentPage();
});

syncAscControls();

// ---- Shared build dropdown ----
const sharedBuildBox   = document.getElementById("shared-build-checkboxes");
const sharedBuildToggle = document.getElementById("shared-build-toggle");
const sharedBuildPanel  = document.getElementById("shared-build-panel");

function sharedBuildSummary() {
  const n = sharedActiveBuilds.size;
  return n === 0 ? "No builds"
       : n === DATA.builds.length ? "All builds"
       : `${n} build${n !== 1 ? "s" : ""}`;
}

function updateSharedBuildLabel() {
  sharedBuildToggle.textContent = `${sharedBuildSummary()} ▾`;
}

sharedBuildToggle.addEventListener("click", e => {
  e.stopPropagation();
  const willOpen = sharedBuildPanel.style.display === "none";
  sharedBuildPanel.style.display = willOpen ? "" : "none";
  sharedBuildToggle.setAttribute("aria-expanded", String(willOpen));
});
document.addEventListener("click", e => {
  if (!sharedBuildPanel.contains(e.target) && e.target !== sharedBuildToggle) {
    sharedBuildPanel.style.display = "none";
    sharedBuildToggle.setAttribute("aria-expanded", "false");
  }
});
// Disclosure-panel convention: Escape closes the dropdown and returns focus.
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && sharedBuildPanel.style.display !== "none") {
    sharedBuildPanel.style.display = "none";
    sharedBuildToggle.setAttribute("aria-expanded", "false");
    sharedBuildToggle.focus();
  }
});

DATA.builds.forEach(build => {
  const label = document.createElement("label");
  label.className = "checked";
  label.innerHTML = `<input type="checkbox" value="${build}" checked> ${build}`;
  label.querySelector("input").addEventListener("change", e => {
    if (e.target.checked) sharedActiveBuilds.add(build); else sharedActiveBuilds.delete(build);
    label.classList.toggle("checked", e.target.checked);
    updateSharedBuildLabel();
    rerenderCurrentPage();
  });
  sharedBuildBox.appendChild(label);
});

document.getElementById("shared-build-all").addEventListener("click", () => {
  sharedActiveBuilds = new Set(DATA.builds);
  sharedBuildBox.querySelectorAll("input").forEach(cb => { cb.checked = true; cb.closest("label").classList.add("checked"); });
  updateSharedBuildLabel();
  rerenderCurrentPage();
});
document.getElementById("shared-build-none").addEventListener("click", () => {
  sharedActiveBuilds = new Set();
  sharedBuildBox.querySelectorAll("input").forEach(cb => { cb.checked = false; cb.closest("label").classList.remove("checked"); });
  updateSharedBuildLabel();
  rerenderCurrentPage();
});

updateSharedBuildLabel();

// ---- Shared players buttons + modes checkboxes ----
const sharedPlayersButtons = {
  "all":   document.getElementById("shared-players-all"),
  "solo":  document.getElementById("shared-players-solo"),
  "multi": document.getElementById("shared-players-multi"),
};

function setSharedPlayers(players) {
  sharedActivePlayers = players;
  Object.entries(sharedPlayersButtons).forEach(([key, btn]) => setActive(btn, key === players));
}

Object.entries(sharedPlayersButtons).forEach(([players, btn]) => {
  btn.addEventListener("click", () => {
    setSharedPlayers(players);
    rerenderCurrentPage();
  });
});

const sharedModesBox = document.getElementById("shared-modes-checkboxes");
// Blitz, Dread and Custom only get a checkbox once the player has a run in them.
ALL_MODES.forEach(mode => {
  const label = document.createElement("label");
  label.innerHTML = `<input type="checkbox" value="${mode}"> ${MODE_LABELS[mode]}`;
  if (["blitz", "dread", "custom"].includes(mode) && !DATA.runsData.some(r => r.mode === mode)) label.style.display = "none";
  label.querySelector("input").addEventListener("change", e => {
    const next = new Set(sharedActiveModes);
    if (e.target.checked) next.add(mode); else next.delete(mode);
    setSharedModes(next);
    rerenderCurrentPage();
  });
  sharedModesBox.appendChild(label);
});

function setSharedModes(modes) {
  sharedActiveModes = new Set(modes);
  sharedModesBox.querySelectorAll("input").forEach(cb => {
    cb.checked = sharedActiveModes.has(cb.value);
    cb.closest("label").classList.toggle("checked", cb.checked);
  });
}

setSharedModes(SHARED_FILTER_HARDCODED_DEFAULTS.modes);
setSharedPlayers("all");

// ---- Shared mods buttons ----
// The group only shows when some run has loaded mods; with none, it would be
// a filter that can't do anything.
const sharedModsButtons = {
  "all":     document.getElementById("shared-mods-all"),
  "vanilla": document.getElementById("shared-mods-vanilla"),
  "modded":  document.getElementById("shared-mods-modded"),
};
document.getElementById("shared-mods-group").style.display = DATA.runsData.some(runIsModded) ? "" : "none";

function setSharedMods(mods) {
  sharedActiveMods = mods;
  Object.entries(sharedModsButtons).forEach(([key, btn]) => setActive(btn, key === mods));
}

Object.entries(sharedModsButtons).forEach(([mods, btn]) => {
  btn.addEventListener("click", () => {
    setSharedMods(mods);
    rerenderCurrentPage();
  });
});

setSharedMods("all");

// ---- Shared date range ----
document.getElementById("shared-date-from").value = tsToDateStr(minTs);
document.getElementById("shared-date-to").value   = tsToDateStr(maxTs);

const SHARED_DATE_BTN_IDS = ["shared-date-7d", "shared-date-30d", "shared-date-90d", "shared-date-today", "shared-date-alltime"];
function setActiveSharedDateBtn(activeId) {
  SHARED_DATE_BTN_IDS.forEach(id => setActive(document.getElementById(id), id === activeId));
}

document.getElementById("shared-date-from").addEventListener("change", e => {
  setActiveSharedDateBtn(null);
  sharedTsFrom = e.target.value ? dateStrToLocalTs(e.target.value) : 0;
  rerenderCurrentPage();
});
document.getElementById("shared-date-to").addEventListener("change", e => {
  setActiveSharedDateBtn(null);
  sharedTsTo = e.target.value ? dateStrToLocalTs(e.target.value) + 86400 : TS_NO_UPPER_BOUND;
  rerenderCurrentPage();
});

function setSharedLastDays(n) {
  const to   = new Date();
  const from = new Date();
  from.setDate(from.getDate() - n);
  document.getElementById("shared-date-to").value   = tsToDateStr(to.getTime() / 1000);
  document.getElementById("shared-date-from").value = tsToDateStr(from.getTime() / 1000);
  sharedTsFrom = dateStrToLocalTs(document.getElementById("shared-date-from").value);
  sharedTsTo   = dateStrToLocalTs(document.getElementById("shared-date-to").value)   + 86400;
  rerenderCurrentPage();
}

document.getElementById("shared-date-7d").addEventListener("click",  () => { setActiveSharedDateBtn("shared-date-7d");      setSharedLastDays(7); });
document.getElementById("shared-date-30d").addEventListener("click", () => { setActiveSharedDateBtn("shared-date-30d");     setSharedLastDays(30); });
document.getElementById("shared-date-90d").addEventListener("click", () => { setActiveSharedDateBtn("shared-date-90d");     setSharedLastDays(90); });
document.getElementById("shared-date-today").addEventListener("click", () => {
  setActiveSharedDateBtn("shared-date-today");
  const today = tsToDateStr(Date.now() / 1000);
  document.getElementById("shared-date-from").value = today;
  document.getElementById("shared-date-to").value   = today;
  sharedTsFrom = dateStrToLocalTs(today);
  sharedTsTo   = sharedTsFrom + 86400;
  rerenderCurrentPage();
});
document.getElementById("shared-date-alltime").addEventListener("click", () => {
  setActiveSharedDateBtn("shared-date-alltime");
  // Blank, not minTs/maxTs — "All time" means no bound, not "today's data
  // range," so it stays correct after future regenerations add new runs
  // (see sharedTsFrom/sharedTsTo declaration above).
  document.getElementById("shared-date-from").value = "";
  document.getElementById("shared-date-to").value   = "";
  sharedTsFrom = 0;
  sharedTsTo   = TS_NO_UPPER_BOUND;
  rerenderCurrentPage();
});

// ---- Save/Reset filter defaults ----
//
// run.py regenerates this HTML file fresh every time (no server, no
// per-user backend), so the browser's localStorage is the only thing
// that can survive a reload/regeneration — keyed to the browser, not the
// file content. "Save as default" snapshots the 5 shared filter values;
// "Reset filters" reverts the live filters to the hardcoded defaults,
// and clears the saved snapshot so the reset survives reloads and profile changes.

function currentSharedFilterState() {
  return {
    // lastUnlockedChar, not sharedActiveChar — the latter can currently be
    // a page-forced value (see charIsLocked()) that doesn't reflect what
    // the user actually chose.
    char:   lastUnlockedChar,
    // Ascension picks only exist in granular view (see savedAscState()).
    ascGranular: sharedAscGranular,
    ...(sharedAscGranular && { ascs: [...sharedActiveAscs] }),
    builds: [...sharedActiveBuilds],
    allBuilds: sharedActiveBuilds.size === DATA.builds.length,
    players: sharedActivePlayers,
    modes:  [...sharedActiveModes],
    mods:   sharedActiveMods,
    tsFrom: sharedTsFrom,
    tsTo:   sharedTsTo,
  };
}

function showFilterStatus(text) {
  const el = document.getElementById("shared-filters-status");
  el.textContent = text;
  clearTimeout(showFilterStatus._t);
  showFilterStatus._t = setTimeout(() => { el.textContent = ""; }, 2500);
}

// Overview always needs "ALL" (see showPage()), regardless of anything
// saved or currently active. A saved/current character value only means
// anything on the three pages that don't constrain it (Card Stats, Run
// Detail, Seed Data). Used by
// applySharedFilterState (skip applying a saved char here), the Save
// button (preserve rather than overwrite the saved char here), and the
// unsaved-changes indicator (don't compare char here).
function charIsLocked(page) {
  return page === "overview";
}

// Applies a saved (or default) filter state to both the in-memory shared
// filter variables AND every control's on-screen state, reusing each
// control's own update function rather than duplicating that UI logic.
//
// The character field is the one exception — see charIsLocked() above.
// lastUnlockedChar (the "real" preference) always gets set to the loaded
// value, but sharedActiveChar (the live/rendered value) only follows it
// on the three pages that don't constrain it — on the other two, applying
// it would just get immediately overwritten by that page's own forcing
// logic, so it's skipped outright instead; showPage()'s restoration logic
// picks lastUnlockedChar back up the moment an unlocked page is reached.
// `targetPage` defaults to `currentPage` (correct for the live
// Reset-button call site) but must be passed explicitly during initial
// load, where `currentPage` is still stuck at its "overview" default —
// the URL hash isn't resolved into the real landing page until the very
// end of the script, after this runs.
function applySharedFilterState(state, targetPage = currentPage) {
  state = normalizeSharedFilterState(state);
  lastUnlockedChar = state.char;
  if (!charIsLocked(targetPage)) {
    sharedActiveChar = state.char;
    updateSharedCharBtns();
  }

  const validBuilds = savedBuilds(state);
  const asc = savedAscState(state);
  sharedAscGranular = asc.granular;
  sharedActiveAscs  = new Set(asc.ascs);
  syncAscControls();

  sharedActiveBuilds = new Set(validBuilds);
  sharedBuildBox.querySelectorAll("input").forEach(cb => {
    const on = sharedActiveBuilds.has(cb.value);
    cb.checked = on;
    cb.closest("label").classList.toggle("checked", on);
  });
  updateSharedBuildLabel();

  setSharedMods(state.mods ?? "all");
  const modeState = savedModeState(state);
  setSharedModes(modeState.modes);
  setSharedPlayers(modeState.players);

  sharedTsFrom = state.tsFrom;
  sharedTsTo   = state.tsTo;
  document.getElementById("shared-date-from").value = sharedTsFrom > 0 ? tsToDateStr(sharedTsFrom) : "";
  document.getElementById("shared-date-to").value   = sharedTsTo !== TS_NO_UPPER_BOUND ? tsToDateStr(sharedTsTo - 86400) : "";
  setActiveSharedDateBtn(sharedTsFrom === 0 && sharedTsTo === TS_NO_UPPER_BOUND ? "shared-date-alltime" : null);
}

document.getElementById("shared-filters-save").addEventListener("click", e => {
  // currentSharedFilterState().char is lastUnlockedChar, not
  // sharedActiveChar — already the right value to save regardless of
  // whether the current page happens to be char-locked.
  localStorage.setItem(SHARED_FILTER_STORAGE_KEY, JSON.stringify(currentSharedFilterState()));
  showFilterStatus("Saved");
  updateUnsavedIndicator();
  // Restart the pop animation even on rapid repeat clicks.
  const btn = e.currentTarget;
  btn.classList.remove("pop");
  void btn.offsetWidth;
  btn.classList.add("pop");
});

document.getElementById("shared-filters-reset").addEventListener("click", () => {
  localStorage.removeItem(SHARED_FILTER_STORAGE_KEY);
  document.getElementById("shared-filter-presets").value = "default";
  document.getElementById("shared-filter-preset-name").value = "";
  const url = new URL(location.href);
  url.searchParams.delete("filters");
  history.replaceState(null, "", url);
  applySharedFilterState(SHARED_FILTER_HARDCODED_DEFAULTS);
  rerenderCurrentPage();
  showFilterStatus("Filters reset — saved default cleared");
  updateUnsavedIndicator();
});

// "All builds" stays all when a new patch appears. A selection from another
// profile with no matching builds falls back to all; an intentional empty
// selection stays empty. Legacy saves still carry an explicit builds array.
function savedBuilds(state) {
  if (state.allBuilds || !Array.isArray(state.builds)) return [...DATA.builds];
  const valid = state.builds.filter(b => DATA.builds.includes(b));
  return state.builds.length && !valid.length ? [...DATA.builds] : valid;
}

// Links and browser storage are untrusted input. Keep valid selections, and
// fill missing/invalid fields with defaults before they reach the controls.
function normalizeSharedFilterState(state) {
  if (!state || typeof state !== "object" || Array.isArray(state)) throw new Error("Invalid filters");
  const base = SHARED_FILTER_HARDCODED_DEFAULTS;
  const mode = savedModeState(state);
  const result = { ...base, ...state,
    char: state.char === "ALL" || DATA.characters.includes(state.char) ? state.char : "ALL",
    builds: Array.isArray(state.builds) ? state.builds.filter(b => typeof b === "string").slice(0, 240) : [...DATA.builds],
    allBuilds: state.allBuilds === true || !Array.isArray(state.builds),
    players: ["all", "solo", "multi"].includes(mode.players) ? mode.players : "all",
    modes: Array.isArray(mode.modes) ? mode.modes.filter(m => ALL_MODES.includes(m)) : [...base.modes],
    mods: ["all", "vanilla", "modded"].includes(state.mods) ? state.mods : "all",
    tsFrom: Number.isSafeInteger(state.tsFrom) && state.tsFrom >= 0 ? state.tsFrom : base.tsFrom,
    tsTo: Number.isSafeInteger(state.tsTo) && state.tsTo >= 0 ? state.tsTo : base.tsTo,
  };
  // Preserve legacy granular saves while preventing malformed flags/lists.
  if (typeof state.ascGranular !== "boolean") delete result.ascGranular;
  if (!Array.isArray(state.ascs)) delete result.ascs;
  return result;
}

const FILTER_PRESETS_KEY = "sts2_filter_presets";
function readFilterPresets() {
  try {
    const saved = JSON.parse(localStorage.getItem(FILTER_PRESETS_KEY) || "[]");
    return Array.isArray(saved) ? saved.filter(p => p && typeof p.name === "string" && p.state).slice(0, 50) : [];
  } catch { return []; }
}
function refreshFilterPresets(selected = "") {
  const select = document.getElementById("shared-filter-presets");
  select.replaceChildren(new Option("Default", "default"), new Option("Choose a preset", ""));
  select.options[1].disabled = true;
  select.options[1].hidden = true;
  readFilterPresets().forEach(p => select.add(new Option(p.name, `preset:${p.name}`)));
  if (selected) select.value = `preset:${selected}`;
  syncFilterPresetSelection();
}
function syncFilterPresetSelection() {
  const select = document.getElementById("shared-filter-presets");
  const state = currentSharedFilterState();
  const matches = readFilterPresets().filter(p => {
    try { return sharedFilterStateEquals(state, normalizeSharedFilterState(p.state)); }
    catch { return false; }
  });
  select.value = matches.find(p => select.value === `preset:${p.name}`) ? select.value
    : sharedFilterStateEquals(state, SHARED_FILTER_HARDCODED_DEFAULTS) ? "default"
    : matches.length ? `preset:${matches[0].name}` : "";
  document.getElementById("shared-filter-preset-delete").disabled = currentPage === "overview" || !select.value.startsWith("preset:");
}
document.getElementById("shared-filter-preset-save").addEventListener("click", () => {
  const input = document.getElementById("shared-filter-preset-name");
  const name = input.value.trim().slice(0, 60);
  if (!name) { input.focus(); showFilterStatus("Enter a name for these filters"); return; }
  const presets = readFilterPresets().filter(p => p.name !== name);
  if (presets.length >= 50) { showFilterStatus("Delete a preset before saving another"); return; }
  presets.push({ name, state: currentSharedFilterState() });
  try { localStorage.setItem(FILTER_PRESETS_KEY, JSON.stringify(presets)); }
  catch { showFilterStatus("Browser storage is unavailable"); return; }
  refreshFilterPresets(name);
  input.value = "";
  showFilterStatus("Filter preset saved in this browser");
});
document.getElementById("shared-filter-presets").addEventListener("change", e => {
  if (e.target.value === "default") { document.getElementById("shared-filters-reset").click(); return; }
  const preset = readFilterPresets().find(p => `preset:${p.name}` === e.target.value);
  if (!preset) return;
  try {
    applySharedFilterState(preset.state);
    rerenderCurrentPage();
    refreshFilterPresets(preset.name);
    document.getElementById("shared-filter-preset-name").value = preset.name;
    showFilterStatus("Preset applied");
  } catch { showFilterStatus("This preset could not be loaded"); }
});
document.getElementById("shared-filter-preset-delete").addEventListener("click", () => {
  const selected = document.getElementById("shared-filter-presets").value;
  if (!selected.startsWith("preset:")) return;
  const name = selected.slice("preset:".length);
  try { localStorage.setItem(FILTER_PRESETS_KEY, JSON.stringify(readFilterPresets().filter(p => p.name !== name))); }
  catch { showFilterStatus("Could not delete preset — browser storage is unavailable"); return; }
  document.getElementById("shared-filter-preset-name").value = "";
  refreshFilterPresets();
  showFilterStatus("Preset deleted");
});
window.addEventListener("storage", e => {
  if (e.key === FILTER_PRESETS_KEY || e.key === null) refreshFilterPresets();
});
document.getElementById("shared-filter-copy-link").addEventListener("click", async () => {
  const url = new URL(location.href);
  url.searchParams.set("filters", JSON.stringify(currentSharedFilterState()));
  try {
    await navigator.clipboard.writeText(url.href);
    history.replaceState(null, "", url);
    showFilterStatus("Link with filters copied");
  } catch { showFilterStatus("Could not copy the link — clipboard access was blocked"); }
});
refreshFilterPresets();

// A save only carries ascension picks when granular view was on; otherwise every
// level is included. Saves from before granular view existed have no ascGranular and
// always carry ascs: they open in granular view if they left any level unchecked,
// so the checkboxes showing that selection aren't hidden.
function savedAscState(state) {
  const all  = [...DATA.ascensions];
  const ascs = Array.isArray(state.ascs) ? state.ascs.filter(a => DATA.ascensions.includes(a)) : all;
  const granular = state.ascGranular ?? ascs.length !== all.length;
  return { granular, ascs: granular ? ascs : all };
}

function sameAscState(a, b) {
  return a.granular === b.granular && a.ascs.length === b.ascs.length && a.ascs.every(x => b.ascs.includes(x));
}

// Advisory badge next to Save/Reset, shown whenever the live filter state
// has drifted from whatever baseline the session actually started from —
// the saved preference if one exists, otherwise the hardcoded defaults.
// One signal either way: "you've changed something since your last save
// (or since opening the dashboard, if you've never saved)." Not shown as
// a warning color — this is a "you might want to save this" nudge, not
// an error state; plenty of filter changes are just browsing and don't
// need saving.
function sameModeState(a, b) {
  return a.players === b.players && a.modes.length === b.modes.length && a.modes.every(m => b.modes.includes(m));
}

function sharedFilterStateEquals(a, b) {
  const aBuilds = savedBuilds(a), bBuilds = savedBuilds(b);
  return a.char === b.char
    && sameModeState(savedModeState(a), savedModeState(b))
    && (a.mods ?? "all") === (b.mods ?? "all")
    && sameAscState(savedAscState(a), savedAscState(b))
    && a.tsFrom === b.tsFrom
    && a.tsTo === b.tsTo
    && aBuilds.length === bBuilds.length && aBuilds.sort().join(",") === bBuilds.sort().join(",");
}

function sharedFilterBaseline() {
  const raw = localStorage.getItem(SHARED_FILTER_STORAGE_KEY);
  if (raw) {
    try { return JSON.parse(raw); } catch { /* fall through to defaults */ }
  }
  return SHARED_FILTER_HARDCODED_DEFAULTS;
}

function updateUnsavedIndicator() {
  const badge = document.getElementById("shared-filters-unsaved");
  const isBaseline = sharedFilterStateEquals(currentSharedFilterState(), sharedFilterBaseline());
  badge.style.display = isBaseline ? "none" : "flex";
  // "Save as default" only needs to stand out when there's actually
  // something unsaved to catch — once saved (or already at baseline) it
  // goes back to a plain toggle-btn like Reset, same as the badge above.
  document.getElementById("shared-filters-save").classList.toggle("toggle-btn-primary", !isBaseline);
}

// Apply any saved preference on load, after every control above has
// finished wiring up its default state and event listeners.
(function loadSavedSharedFilters() {
  const { page } = parsePageHash();
  const targetPage = PAGES.includes(page) ? page : "overview";
  const linked = new URL(location.href).searchParams.get("filters");
  if (linked) {
    try {
      if (linked.length > 16000) throw new Error("Filter link too long");
      applySharedFilterState(JSON.parse(linked), targetPage);
      updateUnsavedIndicator();
      showFilterStatus("Filters loaded from link");
      return;
    } catch { showFilterStatus("Invalid filter link — using your defaults"); }
  }
  const raw = localStorage.getItem(SHARED_FILTER_STORAGE_KEY);
  if (raw) {
    try {
      // currentPage is still stuck at its "overview" default here — the
      // URL hash isn't resolved into the real landing page until the
      // very end of this file, in the IIFE after this one. Peek at it
      // directly so applySharedFilterState() knows the TRUE destination
      // (e.g. a direct #cards link) instead of assuming "overview" and
      // wrongly skipping a perfectly valid saved character for an
      // unlocked page.
      const { page } = parsePageHash();
      const targetPage = PAGES.includes(page) ? page : "overview";
      applySharedFilterState(JSON.parse(raw), targetPage);
    } catch (error) {
      console.warn("Could not restore saved filters:", error.message);
      localStorage.removeItem(SHARED_FILTER_STORAGE_KEY);
    }
  }
  updateUnsavedIndicator();
})();
sharedFiltersLoaded = true;
syncFilterPresetSelection();
