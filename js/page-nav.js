// =========================================================================
// Page navigation
// =========================================================================

const PAGES = ["overview", "character", "detail", "cards", "seeds"];
let currentPage = "overview";

// The URL hash names the tab, and on Run Detail the run as well:
// #detail/<run ts>, so the address opens the same run for anyone.
function parsePageHash() {
  const [page, ts] = location.hash.replace("#", "").split("/");
  return { page, runTs: page === "detail" && /^\d+$/.test(ts || "") ? +ts : null };
}

function pageHash(page) {
  return page === "detail" && detailSelectedTs != null ? `detail/${detailSelectedTs}` : page;
}

const PAGE_RENDERERS = {
  overview:  updateAll,
  character: updateDetail,
  detail:    renderDetailRunList,
  cards:     renderCardsPage,
  seeds:     renderSeeds,
};

// Whether each page's DOM already reflects the current shared filter state.
// showPage() used to re-render unconditionally on every tab switch — fine
// for cheap pages, but Card Stats rebuilds ~500 rows (each with a portrait
// image) from scratch, which is a visible stutter switching back to a tab
// where nothing actually changed. rerenderCurrentPage() is the single
// chokepoint every filter change already runs through (individual
// controls, Reset, and loading a saved preference all end up calling it —
// the latter two via setSharedMode() inside applySharedFilterState()), so
// it's the one place that needs to mark every *other* page dirty.
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
}

// The one-line summary the filter rows collapse behind (.filter-summary in
// dashboard.css; the bar starts collapsed at every width now, not just phone).
// Looks its elements
// up on each call because the filter bar's own setup rerenders before the
// rest of this file has run.
function updateFilterSummary() {
  const modeLabels = { all: "All modes", solo: "Solo", multi: "Multi", daily: "Daily" };
  const nAscs = sharedActiveAscs.size;
  const asc = nAscs === DATA.ascensions.length ? "All ascensions"
            : nAscs === 0 ? "No ascensions"
            : [...sharedActiveAscs].sort((a, b) => a - b).map(a => `A${a}`).join(", ");
  const date = sharedTsFrom === 0 && sharedTsTo === TS_NO_UPPER_BOUND ? "All time"
             : `${sharedTsFrom > 0 ? tsToDateStr(sharedTsFrom) : "…"} → ${sharedTsTo !== TS_NO_UPPER_BOUND ? tsToDateStr(sharedTsTo - 86400) : "…"}`;
  const parts = [
    sharedActiveChar === "ALL" ? "All characters" : fmtCharName(sharedActiveChar),
    modeLabels[sharedActiveMode],
    asc,
    sharedBuildSummary(),
    date,
  ];
  document.querySelector("#shared-filter-summary .filter-summary-text").textContent = parts.join(" · ");
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
  // Character Detail's tables are only meaningful for one character at a
  // time (unlike Card Stats, which genuinely aggregates for "All").
  // Rather than silently
  // rendering one character's data while the shared filter still reads
  // "All" (previously surfaced via a barely-visible page note, easy to
  // miss), landing on this tab with "All" active now sets the SHARED
  // filter itself to the same fallback character, so the filter bar and
  // the page can never disagree. The "All" button is also disabled while
  // this tab is active, so it's visibly not an option rather than something
  // that looks clickable but silently redirects.
  // setSharedActiveChar() (not a direct assignment) so this goes through
  // the same rerenderCurrentPage() chokepoint every other filter change
  // does — pageDirty tracking then just works, with no manual flagging
  // needed here for this page having been forced dirty. isUserPick=false
  // on all three branches below: none of them represent the user actually
  // choosing a character, so none should overwrite lastUnlockedChar.
  if (page === "character" && sharedActiveChar === "ALL") {
    // Prefer the user's actual last choice over the computed "most
    // played" fallback — singleCharFallback() only sees whatever
    // sharedActiveChar happens to be at this exact moment, which depends
    // on navigation path (e.g. "ALL" fresh from Overview vs. already a
    // specific character if arriving via an unlocked page), not on what
    // the user really wants. Falling back to singleCharFallback() only
    // when lastUnlockedChar is itself still "ALL" (never touched this
    // session) keeps this consistent regardless of path taken to get here.
    setSharedActiveChar(lastUnlockedChar !== "ALL" ? lastUnlockedChar : singleCharFallback(), false);
  }
  sharedAllBtn.disabled = page === "character";
  sharedAllBtn.title = page === "character"
    ? "Character Detail shows one character at a time — pick a character above"
    : "";
  // Overview is the mirror image: its charts/tables exist to compare
  // characters side by side, so a single-character selection there is
  // disabled the same way "All" is disabled on Character Detail. Landing
  // here with one already selected (e.g. arriving from Card Stats) snaps
  // back to "All" rather than leaving the filter bar and page disagreeing.
  if (page === "overview" && sharedActiveChar !== "ALL") {
    setSharedActiveChar("ALL", false);
  }
  // Landing on an unlocked page restores whatever character was last
  // actually chosen, in case it got forced away to something else (e.g.
  // Character Detail's own fallback) while cycling through locked pages
  // in between — without this, a real "Defect" selection could silently
  // turn into whatever Character Detail's singleCharFallback() picks
  // (e.g. "Ironclad", if that's the most-played character) just by
  // passing through it on the way to somewhere else.
  if (!charIsLocked(page) && sharedActiveChar !== lastUnlockedChar) {
    setSharedActiveChar(lastUnlockedChar, false);
  }
  sharedCharSel.querySelectorAll(".char-btn[data-char]").forEach(btn => {
    btn.disabled = page === "overview";
    btn.title = page === "overview"
      ? "Overview compares every character — pick a character in Character Detail or Card Stats instead"
      : "";
  });
  if (pageDirty[page]) {
    (PAGE_RENDERERS[page] || updateAll)();
    pageDirty[page] = false;
  }
  location.hash = pageHash(page);
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
// for lands on Run Detail's usual first run.
function openRunLink(ts) {
  const run = DATA.runsData.find(r => r.ts === ts);
  if (run) {
    const state = currentSharedFilterState();
    const widen = {};
    if (state.char !== "ALL" && state.char !== run.char) widen.char = "ALL";
    if (!sharedActiveAscs.has(run.asc)) { widen.ascGranular = false; widen.ascs = undefined; }
    if (!sharedActiveBuilds.has(run.build)) widen.builds = [...DATA.builds];
    if (run.ts < state.tsFrom || run.ts > state.tsTo) { widen.tsFrom = 0; widen.tsTo = TS_NO_UPPER_BOUND; }
    if (!modeShowsRun(state.mode, run)) widen.mode = run.mode === "daily" ? "daily" : run.mp ? "multi" : "solo";
    if (Object.keys(widen).length > 0) {
      applySharedFilterState({ ...state, ...widen }, "detail");
      // applySharedFilterState() re-rendered the page behind this one partway
      // through (setSharedMode), before the dates were in place.
      PAGES.forEach(p => { pageDirty[p] = true; });
      updateUnsavedIndicator();
      updateFilterSummary();
    }
  }
  jumpToRun(ts);
}

// A link pasted into the address bar of a page that is already open only
// changes the hash, so nothing reloads. Follow it. The hash this page sets
// itself (showPage) arrives here too, already matching, and does nothing.
window.addEventListener("hashchange", () => {
  const { page, runTs } = parsePageHash();
  if (!PAGES.includes(page)) return;
  if (runTs != null && runTs !== detailSelectedTs) openRunLink(runTs);
  else if (page !== currentPage) showPage(page);
});

// ---- Shared character selector ----
const sharedCharSel = document.getElementById("shared-char-selector");

const sharedAllBtn = document.createElement("button");
sharedAllBtn.className = "char-btn active";
sharedAllBtn.textContent = "All";
sharedAllBtn.style.setProperty("--char-color", "#e0c468");
sharedAllBtn.addEventListener("click", () => {
  // Disabled (via showPage()) while Character Detail is active, so this
  // only ever fires on pages where "All" is a valid selection.
  setSharedActiveChar("ALL");
});
sharedCharSel.appendChild(sharedAllBtn);

DATA.characters.forEach((char, i) => {
  const btn = document.createElement("button");
  btn.className = "char-btn";
  btn.style.setProperty("--char-color", DATA.charColors[i]);
  btn.textContent = fmtCharName(char);
  btn.dataset.char = char;
  // currentPage defaults to "overview" and showPage() doesn't run on a bare
  // load with no URL hash, so the disabled state showPage() would otherwise
  // set needs a matching starting value here too.
  btn.disabled = currentPage === "overview";
  btn.title = btn.disabled
    ? "Overview compares every character — pick a character in Character Detail or Card Stats instead"
    : "";
  btn.addEventListener("click", () => setSharedActiveChar(char));
  sharedCharSel.appendChild(btn);
});

// Single setter for sharedActiveChar, mirroring setSharedMode() below —
// every caller (these two click handlers, and showPage()'s Character
// Detail / Overview character-filter lock) goes through here instead of
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

function setGold(btn, on) {
  btn.style.color       = on ? "#e0c468" : "";
  btn.style.borderColor = on ? "#e0c468" : "";
}

function syncAscControls() {
  sharedAscBox.querySelectorAll("input").forEach(cb => {
    cb.checked = sharedActiveAscs.has(+cb.value);
    cb.closest("label").classList.toggle("checked", cb.checked);
  });
  setGold(sharedAscAll,  sharedActiveAscs.size === DATA.ascensions.length);
  setGold(sharedAscNone, sharedActiveAscs.size === 0);
  setGold(sharedAscGranularBtn, sharedAscGranular);
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
  label.innerHTML = `<input type="checkbox" value="${asc}"> A${asc}`;
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

// ---- Shared mode buttons ----
const sharedModeButtons = {
  "all":   document.getElementById("shared-mode-all"),
  "solo":  document.getElementById("shared-mode-solo"),
  "multi": document.getElementById("shared-mode-multi"),
  "daily": document.getElementById("shared-mode-daily"),
};

function setSharedMode(mode) {
  sharedActiveMode = mode;
  Object.entries(sharedModeButtons).forEach(([key, btn]) => {
    const active = key === mode;
    btn.style.color       = active ? "#e0c468" : "";
    btn.style.borderColor = active ? "#e0c468" : "";
  });
  rerenderCurrentPage();
}

Object.entries(sharedModeButtons).forEach(([mode, btn]) => {
  btn.addEventListener("click", () => setSharedMode(mode));
});

setSharedMode("solo");

// ---- Shared date range ----
document.getElementById("shared-date-from").value = tsToDateStr(minTs);
document.getElementById("shared-date-to").value   = tsToDateStr(maxTs);

const SHARED_DATE_BTN_IDS = ["shared-date-7d", "shared-date-30d", "shared-date-90d", "shared-date-today", "shared-date-alltime"];
function setActiveSharedDateBtn(activeId) {
  SHARED_DATE_BTN_IDS.forEach(id => {
    const btn = document.getElementById(id);
    const on  = id === activeId;
    btn.style.color       = on ? "#e0c468" : "";
    btn.style.borderColor = on ? "#e0c468" : "";
  });
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
// never to "whatever was last saved", but leaves the snapshot alone until
// the user saves over it.

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
    mode:   sharedActiveMode,
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

// Overview and Character Detail each compute their own required character
// value independently (see showPage()) — Overview always needs "ALL",
// Character Detail always needs a specific character via
// singleCharFallback(), regardless of anything saved or currently active.
// A saved/current character value only means anything on the three pages
// that don't constrain it (Card Stats, Run Detail, Seed Data). Used by
// applySharedFilterState (skip applying a saved char here), the Save
// button (preserve rather than overwrite the saved char here), and the
// unsaved-changes indicator (don't compare char here).
function charIsLocked(page) {
  return page === "overview" || page === "character";
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
  lastUnlockedChar = state.char;
  if (!charIsLocked(targetPage)) {
    sharedActiveChar = state.char;
    updateSharedCharBtns();
  }

  // Builds are filtered against DATA.builds so a saved preference that
  // references an older export's build strings doesn't silently leave
  // every run excluded if this dashboard was regenerated against a
  // different set of builds since the preference was saved.
  const validBuilds = state.builds.filter(b => DATA.builds.includes(b));
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

  setSharedMode(state.mode);

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
  // Only the live filters reset; the saved default stays until Save is
  // clicked, so a misclick is undone by reloading.
  applySharedFilterState(SHARED_FILTER_HARDCODED_DEFAULTS);
  rerenderCurrentPage();
  showFilterStatus("Reset — Save as default to keep it");
  updateUnsavedIndicator();
});

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
function sharedFilterStateEquals(a, b) {
  return a.char === b.char
    && a.mode === b.mode
    && sameAscState(savedAscState(a), savedAscState(b))
    && a.tsFrom === b.tsFrom
    && a.tsTo === b.tsTo
    && a.builds.length === b.builds.length && [...a.builds].sort().join(",") === [...b.builds].sort().join(",");
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
    } catch {
      localStorage.removeItem(SHARED_FILTER_STORAGE_KEY);
    }
  }
  updateUnsavedIndicator();
})();
