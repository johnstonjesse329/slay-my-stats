// =========================================================================
// Events page: a visit counts once. Dialogue choices are grouped by the
// prompt they were recorded on, with separate stages for repeat prompts.
// =========================================================================

const EVENT_GRANT_MIN_SHARE = 0.5;   // a grant shows when it came with at least this share of an option's visits

function emptyEventTally() {
  return { v: 0, o: Object.create(null), h: 0, s: Object.create(null) };
}

function eventStageOptions(tally, stage) {
  return tally.s[stage] || (tally.s[stage] = Object.create(null));
}

function addEventCounts(options, choice, n, w, grants) {
  const counts = options[choice] || (options[choice] = [0, 0, Object.create(null)]);
  counts[0] += n;
  counts[1] += w;
  Object.entries(grants).forEach(([g, count]) => { counts[2][g] = (counts[2][g] || 0) + count; });
}

function mergeEventTally(tallies, id, ev) {
  const into = tallies[id] || (tallies[id] = emptyEventTally());
  into.v += ev.v;
  into.h += ev.h || 0;
  Object.entries(ev.o).forEach(([choice, [n, w, grants]]) => {
    addEventCounts(into.o, choice, n, w, grants);
  });
  Object.entries(ev.s || {}).forEach(([stage, choices]) => {
    const options = eventStageOptions(into, stage);
    Object.entries(choices).forEach(([choice, [n, w, grants]]) => addEventCounts(options, choice, n, w, grants));
  });
}

function eventTalliesYou() {
  const out = Object.create(null);
  filterRuns().forEach(run => (run.events || []).forEach(([id, opt, grants, history]) => {
    const ev = out[id] || (out[id] = emptyEventTally());
    ev.v++;
    const grantCounts = Object.fromEntries(grants.map(g => [g, 1]));
    const won = Number(!!run.won);
    addEventCounts(ev.o, opt, 1, won, grantCounts);
    if (history) {
      ev.h++;
      let first = true;
      history.forEach(([, stage, choice]) => {
        if (!stage) return;
        addEventCounts(eventStageOptions(ev, stage), choice, 1, won, first ? grantCounts : {});
        first = false;
      });
    }
  }));
  return out;
}

// What the site totals hold for the characters in view, or null when they have
// no complete event count (a total recounted before events were kept).
function eventTalliesAll() {
  const all = favTalliesAll();
  if (!all || siteStatsForFavs.eventsVersion !== 1) return null;
  const out = Object.create(null);
  const chars = sharedActiveChar === "ALL" ? Object.keys(all.picks) : [sharedActiveChar];
  chars.forEach(char => Object.entries(all.picks[char]?.events || {}).forEach(([id, ev]) => {
    mergeEventTally(out, id, ev);
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

const EVENT_FORCED_INTRO = new Set([
  "EVENT.WATERFALL_OF_OBVIOUS_SECRETS", "EVENT.MUSEUM_OF_TORTURE", "EVENT.TINKER_TIME",
]);

function eventStageName(id, stage) {
  const [page, occurrence] = stage.split(".");
  const names = {
    INITIAL: "First decision", ALL: "Choice", ENTER: "Gremlin", DISPLAY: "Display",
    CHOOSE_CARD_TYPE: "Card type", CHOOSE_RIDER: "Card effect", DOLL: "Doll",
    REJECT: "After rejecting the trial", MERCHANT: "Merchant verdict", NOBLE: "Noble verdict",
    NONDESCRIPT: "Nondescript verdict", RECORDED: "Other recorded choice",
    REACH_DEEPER_1: "After reaching deeper", REACH_DEEPER_2: "At the center",
    HOLD_ON_LOOP: "Keep holding on",
  };
  let name = names[page] || titleCaseId(page);
  if (page === "ALL") {
    if (id === "EVENT.ENDLESS_CONVEYOR") return `Belt choice ${occurrence || 1}`;
    if (id === "EVENT.ABYSSAL_BATHS") return `Bath choice ${occurrence || 1}`;
  }
  if (/^HOLD_ON_\d+$/.test(page)) name = `After holding on (${Number(page.split("_").pop()) + 1})`;
  if (/^DECIPHER_\d+$/.test(page)) name = `Deciphering step ${page.split("_").pop()}`;
  return occurrence ? `${name} (${occurrence})` : name;
}

function eventChoices(tally) {
  const catalog = DATA.eventCatalog || {};
  const out = Object.create(null);
  Object.entries(tally).forEach(([id, ev]) => {
    const cat = catalog[id] || {};
    const label = key => Object.hasOwn(cat.labels || {}, key) ? cat.labels[key]
      : titleCaseId(key.replace(/\.title$/, "").split(".").pop());
    const sortedOptions = (choices, visitOutcome = false) => Object.entries(choices)
      .sort((a, b) => b[1][0] - a[1][0] || a[0].localeCompare(b[0]))
      .map(([key, counts]) => {
        const grant = eventGrantText(counts);
        return { key, label: label(key), taken: counts[0], wins: counts[1],
          grant: visitOutcome ? (grant === "not recorded" ? "" : `Visit outcome · ${grant}`) : grant };
      });
    const options = sortedOptions(ev.o);
    const stages = Object.entries(ev.s).map(([stage, choices]) => ({
      stage, label: eventStageName(id, stage), options: sortedOptions(choices, true),
      visits: Object.values(choices).reduce((sum, [n]) => sum + n, 0),
    })).sort((a, b) => Number(b.stage === "INITIAL") - Number(a.stage === "INITIAL")
      || Number(b.stage === "REJECT") - Number(a.stage === "REJECT")
      || b.visits - a.visits || a.stage.localeCompare(b.stage, undefined, { numeric: true }));
    const fixed = !!cat.initial && !cat.conditional && !cat.random_offer;
    out[id] = {
      visits: ev.v,
      historyVisits: ev.h,
      options,
      stages,
      staged: EVENT_FORCED_INTRO.has(id) || stages.some(s => s.stage !== "INITIAL"),
      not_taken: fixed ? cat.initial.filter(k => !(k in ev.o)).map(label) : [],
      flags: { conditional: !!cat.conditional, random_offer: !!cat.random_offer },
    };
  });
  return out;
}

function eventName(id) {
  return (DATA.eventCatalog?.[id]?.title) || titleCaseId(id.replace(/^EVENT\./, ""));
}

// One colour per option, shared by its slice of the pie and its row, in the order of the rows.
const EVENT_SLICE_COLORS = ["#e0c468", "#6fd6c6", "#9db8f0", "#d97a3a", "#c58be0", "#8fd16b", "#e0788c", "#8fa0b8"];

// Each option has its own arc, so hovering its stroke hits only that slice.
function eventPieHtml(ch) {
  const total = ch.options.reduce((n, o) => n + o.taken, 0);
  if (!total) return "";
  const radius = 15.9;
  const point = angle => `${21 + radius * Math.cos(angle)} ${21 + radius * Math.sin(angle)}`;
  let at = -Math.PI / 2;
  const slices = ch.options.map((o, i) => {
    if (!o.taken) return "";
    const share = o.taken / total * 100;
    const end = at + (2 * Math.PI * o.taken) / total;
    const shape = share === 100 ? `circle cx="21" cy="21" r="${radius}"` :
      `path d="M ${point(at)} A ${radius} ${radius} 0 ${share > 50 ? 1 : 0} 1 ${point(end)}"`;
    at = end;
    const pct = share < 0.1 ? "<0.1" : Math.round(share * 10) / 10;
    const label = escapeHtml(`${o.label}: ${o.taken} of ${total} choices (${pct}%)`);
    // data-tip takes HTML, so encode the already escaped text for its attribute.
    return `<${shape} class="event-pie-slice" fill="none" stroke="${EVENT_SLICE_COLORS[i % EVENT_SLICE_COLORS.length]}" stroke-width="9"
      role="img" aria-label="${label}" data-tip="${escapeHtml(label)}" tabindex="0"/>`;
  }).join("");
  return `<svg class="event-pie" viewBox="0 0 42 42" role="group" aria-label="Share of recorded choices by option">${slices}</svg>`;
}

function eventOptionsHtml(ch) {
  const color = i => EVENT_SLICE_COLORS[i % EVENT_SLICE_COLORS.length];
  const rows = ch.options.map((o, i) => {
    const win = Math.round(o.wins / o.taken * 100);
    return `<div class="event-opt">
      <span class="event-opt-name"><i class="event-dot" style="background:${color(i)}"></i>${escapeHtml(o.label)}</span>
      <span class="event-opt-n">${o.taken}</span>
      <span class="event-opt-win${win >= 50 ? " event-opt-hi" : ""}">${win}%</span>
      <span class="event-opt-wl">${o.wins}W / ${o.taken - o.wins}L</span>
      <span class="event-opt-grant${o.grant === "not recorded" ? " event-opt-none" : ""}">${escapeHtml(o.grant)}</span>
    </div>`;
  }).join("")
    + (ch.not_taken || []).map(l => `<div class="event-opt event-opt-never"><span class="event-opt-name"><i class="event-dot event-dot-none"></i>${escapeHtml(l)}</span><span class="event-opt-n">0</span><span class="event-opt-win"></span><span class="event-opt-wl"></span><span class="event-opt-grant"></span></div>`).join("");
  return `<div class="event-body">${eventPieHtml(ch)}<div class="event-opts">${rows}</div></div>`;
}

function eventColumnHtml(who, ch, staged, forcedIntro, query) {
  const head = who === "you" ? "Your runs" : "All players";
  if (!ch) return `<div class="event-col event-col-${who}"><h4>${head}</h4><p class="event-none">—</p></div>`;
  const notes = [ch.flags.conditional && "Some options are only offered at times", ch.flags.random_offer && "The options on offer vary"]
    .filter(Boolean);
  let body = "";
  if (staged && ch.historyVisits < ch.visits) {
    notes.unshift(`Dialogue history recorded for ${ch.historyVisits} of ${ch.visits} visits`);
  }
  if (staged && ch.stages.length) {
    body = ch.stages.map((stage, i) => {
      const title = `${escapeHtml(stage.label)} <span class="event-visits">${stage.visits} recorded</span>`;
      const matches = query && stage.options.some(o => o.label.toLowerCase().includes(query));
      return `<details class="event-stage"${i === 0 || matches ? " open" : ""}><summary>${title}</summary>${eventOptionsHtml(stage)}</details>`;
    }).join("");
  } else if (!staged || (!forcedIntro && !ch.historyVisits)) {
    body = eventOptionsHtml(ch);
  } else {
    body = '<p class="event-none">No decisions recorded.</p>';
  }
  return `<div class="event-col event-col-${who}"><h4>${head} <span class="event-visits">${ch.visits} visit${ch.visits !== 1 ? "s" : ""}</span></h4>
    ${body}${notes.length ? `<p class="event-note">${notes.join(". ")}</p>` : ""}</div>`;
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
  const hay = [eventName(id), ...[you, all].flatMap(ch => ch
    ? [...ch.options, ...ch.stages.flatMap(stage => stage.options)].map(o => o.label) : [])];
  return hay.some(s => s.toLowerCase().includes(q));
}

function renderEventActChips(ids) {
  const count = act => ids.filter(id => act === "all" || eventActsOf(id).includes(act)).length;
  const chips = [["all", "All"], ...EVENT_ACTS.map(a => [a, a]), ["shared", "Any act"]]
    .filter(([a]) => a === "all" || count(a) || a === eventsAct);
  document.getElementById("events-act-chips").innerHTML = chips.map(([a, label]) =>
    `<button type="button" class="run-tag run-tag-btn" data-act="${a}" aria-pressed="${a === eventsAct}">${label} <span class="run-tag-n">${count(a)}</span></button>`).join("");
}

// The event's own illustration (event_images/, from tools/downscale_art.py), as a
// tall crop down the left of the card: which event this is, read at a glance. The
// source is a wide banner, so hover (or focus) opens the whole uncropped image.
function eventArtHtml(id) {
  const src = DATA.eventCatalog?.[id]?.imagePath;
  if (!src) return "";
  return `<div class="event-art">
    <img class="event-art-thumbnail" loading="lazy" src="${src}" alt="" tabindex="0">
    <img class="event-art-preview" loading="lazy" src="${src}" alt="">
  </div>`;
}

function placeEventArtPreview(thumbnail) {
  const preview = thumbnail?.nextElementSibling;
  if (!preview || !preview.offsetWidth) return;
  const { vw, vh } = viewportSize();
  const { left, right, top, bottom, width, height } = thumbnail.getBoundingClientRect();
  const w = preview.offsetWidth, h = preview.offsetHeight, gap = 8;
  let x = left + (width - w) / 2;
  let y = top + (height - h) / 2;
  if (right + w + gap * 2 <= vw) x = right + gap;
  else if (left >= w + gap * 2) x = left - w - gap;
  else y = vh - bottom >= top ? bottom + gap : top - h - gap;
  preview.style.left = `${clampAxis(x, w, vw, gap)}px`;
  preview.style.top = `${clampAxis(y, h, vh, gap)}px`;
  preview.style.visibility = "visible";
}

function eventCardHtml(id, you, all) {
  const art = eventArtHtml(id);
  const staged = you[id]?.staged || all?.[id]?.staged;
  const forcedIntro = EVENT_FORCED_INTRO.has(id);
  const query = eventsQuery.trim().toLowerCase();
  return `<section class="event-card${art ? " event-card-art" : ""}">${art}
        <div class="event-main">
        <h3>${eventName(id)}</h3>
        <div class="event-cols">${eventColumnHtml("you", you[id], staged, forcedIntro, query)}${all ? eventColumnHtml("all", all[id], staged, forcedIntro, query) : ""}</div>
        </div>
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
const eventsList = document.getElementById("events-list");
eventsList.addEventListener("pointerover", e => {
  if (e.pointerType === "mouse" && e.target.matches(".event-art-thumbnail")) {
    requestAnimationFrame(() => placeEventArtPreview(e.target));
  }
});
eventsList.addEventListener("focusin", e => {
  if (e.target.matches(".event-art-thumbnail")) placeEventArtPreview(e.target);
});
eventsList.addEventListener("load", e => {
  if (e.target.matches(".event-art-preview")) placeEventArtPreview(e.target.previousElementSibling);
}, true);
window.addEventListener("scroll", () => placeEventArtPreview(eventsList.querySelector(".event-art-thumbnail:focus")), { passive: true });
window.addEventListener("resize", () => placeEventArtPreview(eventsList.querySelector(".event-art-thumbnail:focus, .event-art-thumbnail:hover")), { passive: true });
document.getElementById("events-act-chips").addEventListener("click", e => {
  const b = e.target.closest("[data-act]");
  if (!b) return;
  eventsAct = b.dataset.act === eventsAct ? "all" : b.dataset.act;
  renderEventsPage();
});
