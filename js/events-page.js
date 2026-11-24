// =========================================================================
// Events page: every option taken at a mystery event, how often, and what the
// node recorded it handing over, yours beside all players'. A save records only
// the option taken (never the ones passed over), so an option nobody took is
// listed only for events whose option set is fixed (DATA.eventCatalog, from
// tools/build_event_catalog.py), and no option is ever called the default.
//
// A tally is { eventId: { v: visits, o: { option: [taken, wins, { grant: n }] } } },
// the shape run.py's "events" take once added up, in the site totals as well.
// =========================================================================

const EVENT_GRANT_MIN_SHARE = 0.5;   // a grant shows when it came with at least this share of an option's visits

function eventTalliesYou() {
  const out = {};
  filterRuns().forEach(run => (run.events || []).forEach(([id, opt, grants]) => {
    const ev = out[id] || (out[id] = { v: 0, o: {} });
    ev.v++;
    const o = ev.o[opt] || (ev.o[opt] = [0, 0, {}]);
    o[0]++; o[1] += run.won ? 1 : 0;
    grants.forEach(g => { o[2][g] = (o[2][g] || 0) + 1; });
  }));
  return out;
}

// What the site totals hold for the characters in view, or null when they have
// no complete event count (a total recounted before events were kept).
function eventTalliesAll() {
  const all = favTalliesAll();
  if (!all || siteStatsForFavs.eventsVersion !== 1) return null;
  const out = {};
  const chars = sharedActiveChar === "ALL" ? Object.keys(all.picks) : [sharedActiveChar];
  chars.forEach(char => Object.entries(all.picks[char]?.events || {}).forEach(([id, ev]) => {
    const into = out[id] || (out[id] = { v: 0, o: {} });
    into.v += ev.v;
    Object.entries(ev.o).forEach(([opt, [n, w, grants]]) => {
      const o = into.o[opt] || (into.o[opt] = [0, 0, {}]);
      o[0] += n; o[1] += w;
      Object.entries(grants).forEach(([g, c]) => { o[2][g] = (o[2][g] || 0) + c; });
    });
  }));
  return out;
}

function eventGrantName(token) {
  const [kind, ...rest] = token.split("-");
  const id = rest.join("-");
  if (kind === "card") return fmtCardLabel(id);
  if (kind === "relic") return fmtRelicLabel(id);
  if (kind === "potion") return (DATA.potionData?.[id]?.title) || titleCaseId(id.replace(/^POTION\./, ""));
  if (kind === "maxhp") return `${Number(id) > 0 ? "+" : ""}${id} max HP`;
  return { gold_up: "gold", gold_down: "gold spent", hurt: "damage", upgrade: "upgrade", remove: "card removed",
           transform: "transform", enchant: "enchant" }[token] || token;
}

// What an option handed over, from the grants that came with at least half its visits.
// Card, relic and potion ids that differ from visit to visit read as "random ...".
function eventGrantText(option) {
  const [taken, , grants] = option;
  const bar = taken * EVENT_GRANT_MIN_SHARE;
  const parts = [];
  ["card", "relic", "potion"].forEach(kind => {
    const own = Object.entries(grants).filter(([g]) => g.startsWith(kind + "-"));
    const top = own.reduce((best, e) => !best || e[1] > best[1] ? e : best, null);
    const total = own.reduce((n, e) => n + e[1], 0);
    if (top && top[1] >= bar) parts.push(eventGrantName(top[0]));
    else if (total >= bar) parts.push(`random ${kind}`);
  });
  Object.entries(grants).filter(([g, n]) => !/^(card|relic|potion)-/.test(g) && n >= bar)
    .sort((a, b) => b[1] - a[1]).forEach(([g]) => parts.push(eventGrantName(g)));
  return parts.length ? parts.join(", ") : "not recorded";
}

// { eventId: { visits, options: [{ key, label, taken, grant }], not_taken: [labels],
//   flags: { conditional, random_offer, random_outcome, outcome_recorded } } }
// from a tally. not_taken lists the catalog's options nobody took, for a fixed set only.
function eventChoices(tally) {
  const catalog = DATA.eventCatalog || {};
  const out = {};
  Object.entries(tally).forEach(([id, ev]) => {
    const cat = catalog[id] || {};
    const label = key => (cat.labels || {})[key] || titleCaseId(key.split(".").pop());
    const options = Object.entries(ev.o).sort((a, b) => b[1][0] - a[1][0] || a[0].localeCompare(b[0]))
      .map(([key, o]) => ({ key, label: label(key), taken: o[0], wins: o[1], grant: eventGrantText(o) }));
    const fixed = !!cat.initial && !cat.conditional && !cat.random_offer;
    out[id] = {
      visits: ev.v,
      options,
      not_taken: fixed ? cat.initial.filter(k => !(k in ev.o)).map(label) : [],
      flags: { conditional: !!cat.conditional, random_offer: !!cat.random_offer, random_outcome: !!cat.random_outcome,
               outcome_recorded: options.some(o => o.grant !== "not recorded") },
    };
  });
  return out;
}

function eventName(id) {
  return (DATA.eventCatalog?.[id]?.title) || titleCaseId(id.replace(/^EVENT\./, ""));
}

// One colour per option, shared by its slice of the pie and its row, in the order of the rows.
const EVENT_SLICE_COLORS = ["#e0c468", "#6fd6c6", "#9db8f0", "#d97a3a", "#c58be0", "#8fd16b", "#e0788c", "#8fa0b8"];

// Each option's share of the visits, as a ring: a slice per option taken.
function eventPieHtml(ch) {
  const total = ch.options.reduce((n, o) => n + o.taken, 0) || 1;
  let at = 0;
  const slices = ch.options.map((o, i) => {
    const share = o.taken / total * 100;
    const out = `<circle class="event-pie-slice" r="15.9155" cx="21" cy="21" fill="none" stroke="${EVENT_SLICE_COLORS[i % EVENT_SLICE_COLORS.length]}" stroke-width="9"
      stroke-dasharray="${share} ${100 - share}" stroke-dashoffset="${25 - at}"><title>${escapeHtml(o.label)}: ${o.taken} of ${total}</title></circle>`;
    at += share;
    return out;
  }).join("");
  return `<svg class="event-pie" viewBox="0 0 42 42" role="img" aria-label="Share of visits by option">${slices}</svg>`;
}

function eventColumnHtml(who, ch) {
  const head = who === "you" ? "Your runs" : "All players";
  if (!ch) return `<div class="event-col event-col-${who}"><h4>${head}</h4><p class="event-none">—</p></div>`;
  const color = i => EVENT_SLICE_COLORS[i % EVENT_SLICE_COLORS.length];
  const rows = ch.options.map((o, i) => {
    const win = Math.round(o.wins / o.taken * 100);
    return `<div class="event-opt">
      <span class="event-opt-name"><i class="event-dot" style="background:${color(i)}"></i>${o.label}</span>
      <span class="event-opt-n">${o.taken}</span>
      <span class="event-opt-win${win >= 50 ? " event-opt-hi" : ""}">${win}%</span>
      <span class="event-opt-wl">${o.wins}W / ${o.taken - o.wins}L</span>
      <span class="event-opt-grant${o.grant === "not recorded" ? " event-opt-none" : ""}">${o.grant}</span>
    </div>`;
  }).join("")
    + ch.not_taken.map(l => `<div class="event-opt event-opt-never"><span class="event-opt-name"><i class="event-dot event-dot-none"></i>${l}</span><span class="event-opt-n">0</span><span class="event-opt-win"></span><span class="event-opt-wl"></span><span class="event-opt-grant"></span></div>`).join("");
  const notes = [ch.flags.conditional && "Some options are only offered at times", ch.flags.random_offer && "The options on offer vary"]
    .filter(Boolean).join(". ");
  return `<div class="event-col event-col-${who}"><h4>${head} <span class="event-visits">${ch.visits} visit${ch.visits !== 1 ? "s" : ""}</span></h4>
    <div class="event-body">${eventPieHtml(ch)}<div class="event-opts">${rows}</div></div>${notes ? `<p class="event-note">${notes}</p>` : ""}</div>`;
}

// Filter bar: a text match on the event or any option, and one act (or "Any act", the shared
// events). With no act picked the list is sectioned by act, in the game's order.
const EVENT_ACTS = ["Overgrowth", "Underdocks", "Hive", "Glory"];
let eventsQuery = "";
let eventsAct = "all";   // "all", an EVENT_ACTS name, or "shared"

function eventActsOf(id) {
  const acts = DATA.eventCatalog?.[id]?.acts || [];
  return acts.length ? acts : ["shared"];
}

function eventMatches(id, you, all) {
  const q = eventsQuery.trim().toLowerCase();
  if (!q) return true;
  const hay = [eventName(id), ...[you, all].flatMap(ch => ch ? ch.options.map(o => o.label) : [])];
  return hay.some(s => s.toLowerCase().includes(q));
}

function renderEventActChips(ids) {
  const count = act => ids.filter(id => act === "all" || eventActsOf(id).includes(act)).length;
  const chips = [["all", "All"], ...EVENT_ACTS.map(a => [a, a]), ["shared", "Any act"]]
    .filter(([a]) => a === "all" || count(a) || a === eventsAct);
  document.getElementById("events-act-chips").innerHTML = chips.map(([a, label]) =>
    `<button type="button" class="run-tag-btn" data-act="${a}" aria-pressed="${a === eventsAct}">${label} <span class="event-visits">${count(a)}</span></button>`).join("");
}

function eventCardHtml(id, you, all) {
  return `<section class="event-card">
        <h3>${eventName(id)}</h3>
        <div class="event-cols">${eventColumnHtml("you", you[id])}${all ? eventColumnHtml("all", all[id]) : ""}</div>
      </section>`;
}

function renderEventsPage() {
  loadSiteStatsForFavs();
  const you = eventChoices(eventTalliesYou());
  const allTally = eventTalliesAll();
  const all = allTally ? eventChoices(allTally) : null;
  const every = [...new Set([...Object.keys(you), ...Object.keys(all || {})])]
    .sort((a, b) => ((you[b]?.visits || 0) - (you[a]?.visits || 0)) || ((all?.[b]?.visits || 0) - (all?.[a]?.visits || 0)) || eventName(a).localeCompare(eventName(b)));
  renderEventActChips(every);
  const ids = every.filter(id => eventMatches(id, you[id], all?.[id]));
  const scope = sharedActiveChar === "ALL" ? "all characters" : fmtCharName(sharedActiveChar);
  const n = Object.keys(you).length;
  document.getElementById("events-caption").textContent =
    `${n} event${n !== 1 ? "s" : ""} recorded under the current filters (${scope}).`;
  const sections = [...EVENT_ACTS, "shared"]
    .filter(a => eventsAct === "all" || eventsAct === a)
    .map(a => [a, ids.filter(id => eventActsOf(id).includes(a))]).filter(([, list]) => list.length);
  document.getElementById("events-list").innerHTML = sections.length
    ? sections.map(([a, list]) => `<h3 class="events-act-head">${a === "shared" ? "Any act" : a}</h3>`
        + list.map(id => eventCardHtml(id, you, all)).join("")).join("")
    : `<p class="event-none">${every.length ? "No events match." : "No events recorded under the current filters."}</p>`;
}

document.getElementById("events-search").addEventListener("input", e => { eventsQuery = e.target.value; renderEventsPage(); });
document.getElementById("events-act-chips").addEventListener("click", e => {
  const b = e.target.closest("[data-act]");
  if (!b) return;
  eventsAct = b.dataset.act === eventsAct ? "all" : b.dataset.act;
  renderEventsPage();
});
