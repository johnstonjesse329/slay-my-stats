// =========================================================================
// Page navigation
// =========================================================================

const PAGES = ["overview", "character", "detail", "cards", "seeds"];
let currentPage = "overview";

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
}

function showPage(page) {
  if (!PAGES.includes(page)) page = "overview";
  currentPage = page;
  PAGES.forEach(p => {
    document.getElementById("page-" + p).style.display = p === page ? "" : "none";
    document.getElementById("tab-"  + p).classList.toggle("active", p === page);
  });
  // Character Detail's tables are only meaningful for one character at a
  // time (unlike Card Stats, which genuinely aggregates for "All" — see
  // CLAUDE.md's Filter architecture section). Rather than silently
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
  location.hash = page;
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

// ---- Shared ascension checkboxes ----
const sharedAscBox = document.getElementById("shared-asc-checkboxes");

DATA.ascensions.forEach(asc => {
  const label = document.createElement("label");
  label.className = "checked";
  label.innerHTML = `<input type="checkbox" value="${asc}" checked> A${asc}`;
  label.querySelector("input").addEventListener("change", e => {
    if (e.target.checked) sharedActiveAscs.add(asc); else sharedActiveAscs.delete(asc);
    label.classList.toggle("checked", e.target.checked);
    syncAscAllNoneHighlight();
    rerenderCurrentPage();
  });
  sharedAscBox.appendChild(label);
});

const sharedAscAll  = document.getElementById("shared-asc-all");
const sharedAscNone = document.getElementById("shared-asc-none");

// The Ascension group has no single "active value" the way Mode/Character/
// Date do, so its All/None toggles never got the gold active treatment — but
// when every ascension is checked, "All" IS the active state and should read
// as such (same for "None" when nothing is checked), matching how the other
// groups highlight their current selection.
function syncAscAllNoneHighlight() {
  const all  = sharedActiveAscs.size === DATA.ascensions.length;
  const none = sharedActiveAscs.size === 0;
  [[sharedAscAll, all], [sharedAscNone, none]].forEach(([btn, on]) => {
    btn.style.color       = on ? "#e0c468" : "";
    btn.style.borderColor = on ? "#e0c468" : "";
  });
}

document.getElementById("shared-asc-all").addEventListener("click", () => {
  sharedActiveAscs = new Set(DATA.ascensions);
  sharedAscBox.querySelectorAll("input").forEach(cb => { cb.checked = true; cb.closest("label").classList.add("checked"); });
  syncAscAllNoneHighlight();
  rerenderCurrentPage();
});
document.getElementById("shared-asc-none").addEventListener("click", () => {
  sharedActiveAscs = new Set();
  sharedAscBox.querySelectorAll("input").forEach(cb => { cb.checked = false; cb.closest("label").classList.remove("checked"); });
  syncAscAllNoneHighlight();
  rerenderCurrentPage();
});

syncAscAllNoneHighlight();

// ---- Shared build dropdown ----
const sharedBuildBox   = document.getElementById("shared-build-checkboxes");
const sharedBuildToggle = document.getElementById("shared-build-toggle");
const sharedBuildPanel  = document.getElementById("shared-build-panel");

function updateSharedBuildLabel() {
  const n = sharedActiveBuilds.size;
  const label = n === 0 ? "No builds"
              : n === DATA.builds.length ? "All builds"
              : `${n} build${n !== 1 ? "s" : ""}`;
  sharedBuildToggle.textContent = `${label} ▾`;
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
// "Reset filters" clears that snapshot and reverts to the hardcoded
// defaults, never to "whatever was last saved" (a true blank slate is
// kept distinct from the user's saved preference).

function currentSharedFilterState() {
  return {
    // lastUnlockedChar, not sharedActiveChar — the latter can currently be
    // a page-forced value (see charIsLocked()) that doesn't reflect what
    // the user actually chose.
    char:   lastUnlockedChar,
    ascs:   [...sharedActiveAscs],
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
  const validAscs   = state.ascs.filter(a => DATA.ascensions.includes(a));
  const validBuilds = state.builds.filter(b => DATA.builds.includes(b));
  sharedActiveAscs = new Set(validAscs);
  sharedAscBox.querySelectorAll("input").forEach(cb => {
    const on = sharedActiveAscs.has(+cb.value);
    cb.checked = on;
    cb.closest("label").classList.toggle("checked", on);
  });
  syncAscAllNoneHighlight();

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
  // Wipes a saved preference in one shot with no undo — block on an
  // explicit confirmation rather than letting a single stray click fire it.
  if (!confirm("Reset all filters to their defaults? This clears your saved preference.")) return;
  localStorage.removeItem(SHARED_FILTER_STORAGE_KEY);
  applySharedFilterState(SHARED_FILTER_HARDCODED_DEFAULTS);
  rerenderCurrentPage();
  showFilterStatus("Reset to defaults");
  updateUnsavedIndicator();
});

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
    && a.tsFrom === b.tsFrom
    && a.tsTo === b.tsTo
    && a.ascs.length === b.ascs.length && [...a.ascs].sort().join(",") === [...b.ascs].sort().join(",")
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
      const hash = location.hash.replace("#", "");
      const targetPage = PAGES.includes(hash) ? hash : "overview";
      applySharedFilterState(JSON.parse(raw), targetPage);
    } catch {
      localStorage.removeItem(SHARED_FILTER_STORAGE_KEY);
    }
  }
  updateUnsavedIndicator();
})();



