// PREVIEW: the owner's own runs only (FB-44, FB-51, FB-64). Reads DATA.runRecords, which
// tools/export_run_records.py builds on the owner's machine from the mod's event log and the
// game's .run file; the live site has none, so there the section never draws.
//
// Nothing here is worked out from other stats: a number the log cannot give, or a badge list the
// run file does not carry, says "Not recorded".

const RECORDS_STYLE = `
.run-records { margin: 1.25rem 0; }
.run-records-head { display: flex; align-items: baseline; gap: 0.75rem; flex-wrap: wrap; margin-bottom: 0.75rem; }
.run-records-head h2 { margin: 0; }
.run-records-preview { font-size: var(--fs-sm); color: var(--gold); border: 1px solid var(--gold); border-radius: 999px; padding: 0.05rem 0.6rem; }
.run-records-grid { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr); gap: 1rem; align-items: start; }
.run-records-peaks { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; margin-bottom: 1rem; }
.run-records-peak { background: var(--panel-2); border: 1px solid var(--hairline); border-radius: 8px; padding: 0.7rem 0.9rem; }
.run-records-peak b { display: block; font-size: 1.9rem; line-height: 1.1; color: var(--gold); font-family: var(--font-head); }
.run-records-peak span, .run-records-where { font-size: var(--fs-sm); color: var(--text-dim); }
.run-records-table { width: 100%; border-collapse: collapse; }
.run-records-table td { padding: 0.45rem 0.4rem; border-top: 1px solid var(--hairline); vertical-align: top; }
.run-records-table td:first-child { color: var(--text-dim); width: 46%; }
.run-records-table td b { color: var(--text); font-size: 1.05rem; }
.run-records-none { color: var(--text-faint); font-style: italic; }
.run-records-badges { display: grid; grid-template-columns: repeat(auto-fill, minmax(11rem, 1fr)); gap: 0.6rem; }
.run-records-badge { display: flex; gap: 0.55rem; align-items: center; background: var(--panel-2); border: 1px solid var(--hairline); border-radius: 8px; padding: 0.4rem 0.6rem; }
.run-records-badge img { width: 44px; height: 44px; flex: none; }
.run-records-badge strong { display: block; font-size: var(--fs-sm); }
.run-records-badge small { display: block; color: var(--text-dim); font-size: 0.72rem; line-height: 1.25; }
.run-records h3 { font-size: var(--fs-sm); color: var(--text-dim); margin: 0 0 0.5rem; font-weight: 600; }
@media (max-width: 900px) { .run-records-grid { grid-template-columns: 1fr; } }
`;

function recordsPlace(row) {
  if (!row) return "";
  const enc = row.enc ? encLabel({ enc: `ENCOUNTER.${row.enc}` }) : "";
  return `${enc ? escapeHtml(enc) + ", " : ""}turn ${row.turn}`;
}

const recordsNone = text => `<span class="run-records-none">${text || "Not recorded"}</span>`;

function recordsBadgeText(text) {
  return escapeHtml(text || "").replace(/\[(?:blue|gold|red|green)\](.*?)\[\/(?:blue|gold|red|green)\]/g, "<b>$1</b>");
}

function recordsPanelHtml(entry, art) {
  const r = entry.records;
  const peaks = !r ? "" : `
    <div class="run-records-peaks">
      <div class="run-records-peak"><span>Peak damage in a turn</span><b>${r.damageInTurn ? r.damageInTurn.n : "-"}</b>
        <div class="run-records-where">${r.damageInTurn ? recordsPlace(r.damageInTurn) : recordsNone()}</div></div>
      <div class="run-records-peak"><span>Peak Block in a turn</span><b>${r.blockInTurn ? r.blockInTurn.n : "-"}</b>
        <div class="run-records-where">${r.blockInTurn ? recordsPlace(r.blockInTurn) : recordsNone()}</div></div>
    </div>`;
  const row = (label, value, where) =>
    `<tr><td>${label}</td><td>${value}${where ? `<div class="run-records-where">${where}</div>` : ""}</td></tr>`;
  let table;
  if (!r) {
    table = `<p>${recordsNone("Not recorded: this run has no event log")}</p>`;
  } else {
    const hit = r.largestHit;
    const en = r.energyInTurn;
    const over = r.mostOverkill;
    table = `<table class="run-records-table"><tbody>
      ${row("Most cards played in a turn", r.cardsInTurn ? `<b>${r.cardsInTurn.n}</b>` : recordsNone(), recordsPlace(r.cardsInTurn))}
      ${row("Most damage in a single turn", r.damageInTurn ? `<b>${r.damageInTurn.n}</b>` : recordsNone(), recordsPlace(r.damageInTurn))}
      ${row("Largest single card hit, overkill included", hit ? `<b>${hit.n}</b> ${escapeHtml(fmtCardLabel(hit.card))}` : recordsNone(),
            hit ? `${hit.overkill ? `${hit.dealt} dealt + ${hit.overkill} overkill, ` : ""}on ${escapeHtml(hit.enemy)}, ${recordsPlace(hit)}` : "")}
      ${row("Most overkill on a single hit", over ? `<b>${over.n}</b> ${escapeHtml(fmtCardLabel(over.card))}`
              : r.overkillTotal != null ? `<b>0</b>` : recordsNone(),
            over ? `on ${escapeHtml(over.enemy)}, ${recordsPlace(over)}` : "")}
      ${row("Overkill, whole run", r.overkillTotal != null ? `<b>${r.overkillTotal}</b>` : recordsNone())}
      ${row("Most Block gained in a turn", r.blockInTurn ? `<b>${r.blockInTurn.n}</b>` : recordsNone(), recordsPlace(r.blockInTurn))}
      ${row("Block gained, whole run", r.blockTotal != null ? `<b>${r.blockTotal}</b>` : recordsNone())}
      ${row("Highest energy in a single turn", en ? `<b>${en.n}</b>` : recordsNone(),
            en ? `${en.start} opened the turn + ${en.fromCards} gained from cards, ${recordsPlace(en)}` : "")}
    </tbody></table>`;
  }
  let badges;
  if (entry.badges == null) badges = `<p>${recordsNone()}</p>`;
  else if (!entry.badges.length) badges = `<p>${recordsNone("No badges earned this run")}</p>`;
  else badges = `<div class="run-records-badges">${entry.badges.map(b => `
      <div class="run-records-badge" title="${escapeHtml(b.desc || "")}">
        ${art[b.art] ? `<img src="${art[b.art]}" alt="" width="44" height="44">` : ""}
        <div><strong>${escapeHtml(b.title || b.id)}</strong><small>${recordsBadgeText(b.desc)}</small></div>
      </div>`).join("")}</div>`;
  return `<section class="run-records chart-box" aria-label="Run records (preview)">
    <div class="run-records-head"><h2>Run records</h2><span class="run-records-preview">Preview, your runs only</span></div>
    <div class="run-records-grid">
      <div>${peaks}<h3>Largest of the run</h3>${table}</div>
      <div><h3>Win badges, as the game awarded them</h3>${badges}</div>
    </div></section>`;
}

function renderRunRecords(run) {
  const host = document.getElementById("detail-records");
  if (!host) return;
  const entry = DATA.runRecords?.runs?.[run.ts];
  if (!entry) { host.innerHTML = ""; return; }
  if (!document.getElementById("run-records-style")) {
    const style = document.createElement("style");
    style.id = "run-records-style";
    style.textContent = RECORDS_STYLE;
    document.head.appendChild(style);
  }
  host.innerHTML = recordsPanelHtml(entry, DATA.runRecords.badgeArt || {});
}
