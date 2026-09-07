// =========================================================================
// Seeds page
// =========================================================================

// ---- Node type color + label helpers (used by legend and results) ----

const NODE_COLORS = {
  monster:   "#5cba7d",
  elite:     "#e8a930",
  boss:      "#e05c5c",
  shop:      "#bcbcd0",
  rest_site: "#5b9bd5",
  treasure:  "#c49fe8",
  unknown:   "#555",
  ancient:   "#e0c468",
};

function nodeColor(type) { return NODE_COLORS[type] || "#555"; }

function nodeTypeLabel(type) {
  const map = { monster: "Monster", elite: "Elite", boss: "Boss", shop: "Shop",
                rest_site: "Rest", treasure: "Treasure", unknown: "Event", ancient: "Ancient" };
  return map[type] || type;
}

function encLabel(l) {
  if (!l.enc) return nodeTypeLabel(l.type);
  if (DATA.encLabels[l.enc]) return DATA.encLabels[l.enc];
  return l.enc.replace(/^(ENCOUNTER|EVENT)\./, "")
              .replace(/_(WEAK|NORMAL|ELITE|BOSS)$/, "")
              .replace(/_/g, " ")
              .replace(/\b\w/g, c => c.toUpperCase());
}

function locBadge(l) {
  const color   = nodeColor(l.type);
  const tip     = (l.picked ? "✓ Picked — " : "Not picked — ") + encLabel(l).replace(/"/g, "&quot;");
  const label   = nodeTypeLabel(l.type);
  const flColor = l.picked ? "#e0e0e0" : "#555";
  const picked  = l.picked ? `<span style="color:#5cba7d;font-size:0.7rem;margin-left:1px">✓</span>` : "";
  return `<span class="seed-loc-badge" style="border-color:${color};opacity:${l.picked ? 1 : 0.5}" data-tip="${tip}"><span style="color:${color};font-size:0.72rem">${label}</span><span style="color:${flColor}">${l.floor}</span>${picked}</span>`;
}

// Deduplicate runs to one entry per seed+character (most recent play wins),
// applied after filtering so date/build/ascension filters see the right runs.
function dedupSeedRuns(runs) {
  const map = new Map();
  runs.forEach(run => {
    if (!run.seed) return;
    const key = run.seed + "|" + run.char;
    const existing = map.get(key);
    if (!existing || run.ts > existing.ts) map.set(key, run);
  });
  return [...map.values()].sort((a, b) => b.ts - a.ts);
}

let seedCardFilters  = [];  // [{id, label, min}]
let seedRelicFilters = [];  // [{id, label}]
let seedSortCol      = "date";
let seedSortAsc      = false;
const SEED_PAGE_SIZE = 100; // rows rendered before the "show more" control
let seedRowLimit     = SEED_PAGE_SIZE;

// ---- Typeahead helpers ----

function buildTypeahead(inputId, dropdownId, labelMap, getActive, onPick) {
  const input    = document.getElementById(inputId);
  const dropdown = document.getElementById(dropdownId);

  const allEntries = Object.entries(labelMap).map(([id, label]) => ({ id, label }))
    .sort((a, b) => a.label.localeCompare(b.label));

  function showDropdown(query) {
    const q = query.trim().toLowerCase();
    if (!q) { dropdown.style.display = "none"; return; }
    const active = getActive();
    const matches = allEntries.filter(e =>
      !active.some(f => f.id === e.id) &&
      e.label.toLowerCase().includes(q)
    ).slice(0, 12);

    if (!matches.length) { dropdown.style.display = "none"; return; }

    dropdown.innerHTML = matches.map(e =>
      `<div class="seeds-dropdown-item" data-id="${e.id}">${e.label}</div>`
    ).join("");
    dropdown.style.display = "";

    dropdown.querySelectorAll(".seeds-dropdown-item").forEach(item => {
      item.addEventListener("mousedown", e => {
        e.preventDefault();
        onPick(item.dataset.id, labelMap[item.dataset.id]);
        input.value = "";
        dropdown.style.display = "none";
      });
    });
  }

  input.addEventListener("input", () => showDropdown(input.value));
  input.addEventListener("focus", () => showDropdown(input.value));
  input.addEventListener("blur",  () => setTimeout(() => { dropdown.style.display = "none"; }, 150));
}

// ---- Card filter chips ----

function renderCardChips() {
  const container = document.getElementById("seeds-card-filters");
  container.innerHTML = seedCardFilters.map((f, i) =>
    `<div class="seeds-chip">
      <span class="seeds-chip-label">${f.label}</span>
      <span class="seeds-chip-qty">
        <span class="seeds-chip-qty-label">offered</span>
        <button class="seeds-chip-adj" data-idx="${i}" data-field="minOffered" data-delta="-1" ${f.minOffered <= 1 ? "disabled" : ""}>−</button>
        <span class="seeds-chip-min">≥${f.minOffered}</span>
        <button class="seeds-chip-adj" data-idx="${i}" data-field="minOffered" data-delta="1">+</button>
      </span>
      <span class="seeds-chip-qty">
        <span class="seeds-chip-qty-label">took</span>
        <button class="seeds-chip-adj" data-idx="${i}" data-field="minTook" data-delta="-1" ${f.minTook <= 0 ? "disabled" : ""}>−</button>
        <span class="seeds-chip-min">${f.minTook > 0 ? "≥" + f.minTook : "any"}</span>
        <button class="seeds-chip-adj" data-idx="${i}" data-field="minTook" data-delta="1">+</button>
      </span>
      <button class="seeds-chip-remove" data-idx="${i}">×</button>
    </div>`
  ).join("");

  container.querySelectorAll(".seeds-chip-adj").forEach(btn => {
    btn.addEventListener("click", e => {
      const idx   = +e.target.dataset.idx;
      const field = e.target.dataset.field;
      const floor = field === "minOffered" ? 1 : 0;
      seedCardFilters[idx][field] = Math.max(floor, seedCardFilters[idx][field] + +e.target.dataset.delta);
      renderCardChips();
      renderSeeds();
    });
  });
  container.querySelectorAll(".seeds-chip-remove").forEach(btn => {
    btn.addEventListener("click", e => {
      seedCardFilters.splice(+e.target.dataset.idx, 1);
      renderCardChips();
      renderSeeds();
    });
  });
}

function renderRelicChips() {
  const container = document.getElementById("seeds-relic-filters");
  container.innerHTML = seedRelicFilters.map((f, i) =>
    `<div class="seeds-chip">
      <span class="seeds-chip-label">${f.label}</span>
      <button class="seeds-chip-remove" data-idx="${i}">×</button>
    </div>`
  ).join("");

  container.querySelectorAll(".seeds-chip-remove").forEach(btn => {
    btn.addEventListener("click", e => {
      seedRelicFilters.splice(+e.target.dataset.idx, 1);
      renderRelicChips();
      renderSeeds();
    });
  });
}

// ---- Wire up typeaheads ----

buildTypeahead(
  "seeds-card-input", "seeds-card-dropdown",
  DATA.cardLabels,
  () => seedCardFilters,
  (id, label) => {
    seedCardFilters.push({ id, label, minOffered: 1, minTook: 0 });
    renderCardChips();
    renderSeeds();
  }
);

buildTypeahead(
  "seeds-relic-input", "seeds-relic-dropdown",
  DATA.relicLabels,
  () => seedRelicFilters,
  (id, label) => {
    seedRelicFilters.push({ id, label });
    renderRelicChips();
    renderSeeds();
  }
);

document.getElementById("seeds-clear-btn").addEventListener("click", () => {
  seedCardFilters  = [];
  seedRelicFilters = [];
  renderCardChips();
  renderRelicChips();
  renderSeeds();
});

// ---- Results table ----

function renderSeeds() {
  // Deduplicate after filtering so date/build/ascension filters are respected
  // before picking the representative run for each seed+character pair.
  const seedRuns = dedupSeedRuns(filterRuns().filter(r => r.seed));
  const filtered = seedRuns.filter(run => {
    const offered = run.cardsOffered  || {};
    const relics  = run.relicsOffered || {};
    if (!seedCardFilters.every(f => {
      const locs = offered[f.id] || [];
      if (locs.length < f.minOffered) return false;
      if (f.minTook > 0 && locs.filter(l => l.picked).length < f.minTook) return false;
      return true;
    })) return false;
    if (!seedRelicFilters.every(f => (relics[f.id]  || []).length >= 1))     return false;
    return true;
  });

  // Sort
  const sortFns = {
    seed:  (a, b) => a.seed.localeCompare(b.seed),
    char:  (a, b) => a.char.localeCompare(b.char),
    won:   (a, b) => (a.won === b.won ? 0 : a.won ? -1 : 1),
    date:  (a, b) => a.ts - b.ts,
  };
  const sortFn = sortFns[seedSortCol] || sortFns.date;
  filtered.sort((a, b) => seedSortAsc ? sortFn(a, b) : sortFn(b, a));

  // Live count moves off the heading into its hover tooltip so the h2 reads
  // as a clean noun phrase like every other page heading.
  const seedsTitle = document.getElementById("seeds-title");
  if (seedsTitle) {
    const n = filtered.length;
    seedsTitle.dataset.tip = `${n} seed${n === 1 ? "" : "s"} match the current search`;
  }

  const hasFilters = seedCardFilters.length > 0 || seedRelicFilters.length > 0;

  // Render sortable headers
  const arrow = col => col === seedSortCol ? (seedSortAsc ? " ▲" : " ▼") : "";
  const thStyle = col => `cursor:pointer;user-select:none;white-space:nowrap${col === seedSortCol ? ";color:#e0c468" : ""}`;
  document.getElementById("seeds-thead-row").innerHTML = `
    <th style="text-align:left;${thStyle("seed")}"    data-col="seed" tabindex="0">Seed${arrow("seed")}</th>
    <th style="text-align:left;${thStyle("char")}"    data-col="char" tabindex="0">Character${arrow("char")}</th>
    <th style="text-align:center;${thStyle("won")}"   data-col="won" tabindex="0">Win${arrow("won")}</th>
    <th style="text-align:left;${thStyle("date")}"    data-col="date" tabindex="0">Date${arrow("date")}</th>
    <th style="text-align:left">Matched Cards / Relics Offered</th>
  `;
  document.getElementById("seeds-thead-row").querySelectorAll("th[data-col]").forEach(th => {
    th.addEventListener("click", () => {
      if (seedSortCol === th.dataset.col) seedSortAsc = !seedSortAsc;
      else { seedSortCol = th.dataset.col; seedSortAsc = false; }
      renderSeeds();
    });
    bindEnterSpace(th);
  });

  const tbody = document.getElementById("seeds-tbody");
  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:#8a8aa0;padding:1.5rem">No matching seeds</td></tr>`;
    return;
  }

  const charColor = run => CHAR_COLOR_MAP[run.char] || "#a0a0b8";
  const fmt = ts => new Date(ts * 1000).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });

  _seedDetailRuns = filtered;

  tbody.onclick = e => {
    const seedEl = e.target.closest(".seed-id");
    if (seedEl) { copySeed(seedEl.dataset.seed, seedEl); return; }
    const row = e.target.closest("tr.seed-row");
    if (row) toggleSeedDetail(row);
  };
  // Keyboard parity: the expandable rows and copyable seed ids are click-only;
  // make Enter/Space on the focused row/seed activate the same action.
  tbody.onkeydown = e => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const seedEl = e.target.closest(".seed-id");
    const row = e.target.closest("tr.seed-row");
    if (!seedEl && !row) return;
    e.preventDefault();
    if (seedEl) { copySeed(seedEl.dataset.seed, seedEl); return; }
    toggleSeedDetail(row);
  };

  const visibleRows = filtered.slice(0, seedRowLimit);
  const moreRow = filtered.length > seedRowLimit
    ? `<tr><td colspan="5" style="text-align:center;padding:0.6rem">
        <button class="seed-show-more" id="seeds-show-more">Show ${Math.min(SEED_PAGE_SIZE, filtered.length - seedRowLimit)} more</button>
        <button class="seed-show-more" id="seeds-show-all">Show all ${filtered.length}</button>
       </td></tr>`
    : "";

  tbody.innerHTML = visibleRows.map((run, i) => {
    const color = charColor(run);
    const wonDot = `<span style="color:${run.won ? "#e0e0e0" : "#8a8aa0"}">${run.won ? "Win" : "Loss"}</span>`;

    let matchSummary = "";
    if (hasFilters) {
      const cardParts = seedCardFilters.map(f => {
        const locs    = (run.cardsOffered || {})[f.id] || [];
        const badges  = locs.map(locBadge).join("");
        return `<div class="seed-match-row"><span style="color:#9ecfff;font-weight:600">${f.label}</span><span class="seed-loc-badges">${badges}</span></div>`;
      });
      const relicParts = seedRelicFilters.map(f => {
        const locs    = (run.relicsOffered || {})[f.id] || [];
        const badges  = locs.map(locBadge).join("");
        return `<div class="seed-match-row"><span style="color:#c49fe8;font-weight:600">${f.label}</span><span class="seed-loc-badges">${badges}</span></div>`;
      });
      matchSummary = [...cardParts, ...relicParts].join("");
    }

    return `<tr class="seed-row" data-idx="${i}" style="cursor:pointer" tabindex="0">
      <td style="padding:0.4rem 0.75rem;font-family:monospace;white-space:nowrap">
        <span class="seed-expand-arrow" style="color:#8a8aa0;font-size:0.7rem;margin-right:0.4rem">▶</span><span class="seed-id" role="button" tabindex="0" aria-label="Copy seed ${run.seed}" style="cursor:pointer;color:#e0c468" data-tip="Click to copy" data-seed="${run.seed}">${run.seed}</span>
      </td>
      <td style="padding:0.4rem 0.75rem;white-space:nowrap">
        <span style="color:${color}">${fmtCharName(run.char)}</span>
      </td>
      <td style="padding:0.4rem 0.75rem;text-align:center">${wonDot}</td>
      <td style="padding:0.4rem 0.75rem;white-space:nowrap;color:#bcbcd0;font-size:0.82rem">${fmt(run.ts)}</td>
      <td style="padding:0.4rem 0.75rem;font-size:0.82rem">${matchSummary}</td>
    </tr>`;
  }).join("") + moreRow;

  const moreBtn = document.getElementById("seeds-show-more");
  if (moreBtn) moreBtn.addEventListener("click", () => { seedRowLimit += SEED_PAGE_SIZE; renderSeeds(); });
  const allBtn = document.getElementById("seeds-show-all");
  if (allBtn) allBtn.addEventListener("click", () => { seedRowLimit = Infinity; renderSeeds(); });
}

let _seedDetailRuns = [];

function toggleSeedDetail(row) {
  const next = row.nextElementSibling;
  if (next && next.classList.contains("seed-detail-row")) {
    next.remove();
    row.querySelector(".seed-expand-arrow").textContent = "▶";
    return;
  }
  // Close any other open detail rows
  document.querySelectorAll(".seed-detail-row").forEach(r => r.remove());
  document.querySelectorAll(".seed-expand-arrow").forEach(a => a.textContent = "▶");

  const idx  = +row.dataset.idx;
  const run  = _seedDetailRuns[idx];
  if (!run) return;

  row.querySelector(".seed-expand-arrow").textContent = "▼";

  const detail = document.createElement("tr");
  detail.className = "seed-detail-row";
  detail.innerHTML = `<td colspan="5" style="padding:0;background:#1b1c1f;border-bottom:2px solid #3f4147">${renderSeedDetail(run)}</td>`;
  row.after(detail);
}

function renderSeedDetail(run) {
  const cards  = dedupeCardCounts(run.finalDeck || []);
  const relics = run.finalRelics || [];

  const groupsHtml = renderCardGroupsHtml(cards);
  const relicHtml  = renderRelicTiles(relics);

  return `<div class="seed-detail-panel">
    <div class="seed-detail-section">
      <div class="seed-detail-label">Final Deck — ${cards.length} unique, ${(run.finalDeck||[]).length} total</div>
      <div class="seed-detail-cards">${groupsHtml || "<span style='color:#8a8aa0'>—</span>"}</div>
    </div>
    <div class="seed-detail-section">
      <div class="seed-detail-label">Relics — ${relics.length}</div>
      <div class="deck-relic-list">${relicHtml || "<span style='color:#8a8aa0'>—</span>"}</div>
    </div>
  </div>`;
}

function copySeed(seed, el) {
  navigator.clipboard.writeText(seed).then(() => {
    const orig = el.textContent;
    el.textContent = "Copied!";
    el.style.color = "#5cba7d";
    setTimeout(() => { el.textContent = orig; el.style.color = "#e0c468"; }, 1200);
  });
}


