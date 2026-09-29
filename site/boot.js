// =========================================================================
// Boot script — builds window.DATA for a /u/steam-<id> profile, then loads
// the dashboard bundle (/app.js).
//
// The dashboard JS (js/*.js in the repo, concatenated to /app.js at deploy
// time) is a classic script whose top-level code reads a global DATA the
// instant it loads — see js/data.js's header comment. run.py used to build
// that object in Python (build_html()) and inline it straight into the
// page; now that the site is static, this file rebuilds the exact same
// shape in the browser from two fetches:
//   - /catalog.json        — the game-data catalog (cards/relics/encounters/
//                             images), the same for every profile.
//   - /users/steam-<id>.json.gz — this profile's parsed runs (parse_run()
//                             output, one entry per run, already sorted by
//                             ts), served gzip-encoded — fetch()/Response
//                             decode that transparently.
//
// Classic script (no type=module) wrapped in an IIFE so the only thing it
// leaves behind on window is DATA itself, exactly like the code it's
// replacing.
// =========================================================================
(function () {

  // ---- Porting run.py's string helpers -----------------------------------
  //
  // strip_prefix/fmt_card/fmt_relic/fmt_encounter and Python's str.title()
  // have to match run.py byte-for-byte, since encLabels/cardLabels/
  // relicLabels are the fallback shown whenever the catalog has no title
  // for an id (see the precedence loop below).

  // value.removeprefix(prefix) if value else "" — only strips the prefix
  // when it's actually there; an empty/falsy value becomes "".
  function stripPrefix(value, prefix) {
    if (!value) return "";
    return value.startsWith(prefix) ? value.slice(prefix.length) : value;
  }

  // Python's str.title(): uppercase the first letter of each run of
  // consecutive letters, lowercase the rest of that run. Anything that
  // isn't an ASCII letter (digits, underscores-turned-spaces, punctuation)
  // passes through untouched and ends the current run. Restricted to
  // A-Z/a-z is fine here — every id this runs on is ASCII.
  function pythonTitle(s) {
    let out = "";
    let prevWasLetter = false;
    for (const ch of s) {
      if (/[A-Za-z]/.test(ch)) {
        out += prevWasLetter ? ch.toLowerCase() : ch.toUpperCase();
        prevWasLetter = true;
      } else {
        out += ch;
        prevWasLetter = false;
      }
    }
    return out;
  }

  function fmtCard(cardId) {
    return pythonTitle(stripPrefix(cardId, "CARD.").replace(/_/g, " "));
  }
  function fmtRelic(relicId) {
    return pythonTitle(stripPrefix(relicId, "RELIC.").replace(/_/g, " "));
  }
  function fmtEncounter(encId) {
    return pythonTitle(stripPrefix(encId, "ENCOUNTER.").replace(/_/g, " "));
  }

  // ---- Porting run.py's build_sort_key ------------------------------------
  //
  // build_sort_key(build) -> (1, nums) if any dot-part is all-digit, else
  // (0,). sorted(..., key=build_sort_key, reverse=True): numeric builds
  // first (highest version first), non-numeric builds (e.g. "UNKNOWN")
  // last, in original relative order — reverse=True in Python sorts
  // stably, it doesn't literally reverse the whole list, so ties keep
  // their original order rather than swapping.

  // "".lstrip("v") strips every leading 'v', not just one.
  function lstripV(s) {
    let i = 0;
    while (i < s.length && s[i] === "v") i++;
    return s.slice(i);
  }

  function buildSortKey(build) {
    const parts = lstripV(build).split(".");
    const nums = [];
    for (const p of parts) {
      if (/^[0-9]+$/.test(p)) nums.push(parseInt(p, 10));
    }
    return nums.length ? { flag: 1, nums } : { flag: 0, nums: [] };
  }

  // Ascending comparison of two build_sort_key() results, matching Python
  // tuple comparison: compare flag first, then the nums list element by
  // element (a shorter list that's a prefix of the other is "less").
  function cmpBuildKeyAsc(ka, kb) {
    if (ka.flag !== kb.flag) return ka.flag - kb.flag;
    if (ka.flag === 0) return 0; // both (0,) — equal, tuple has no 2nd element
    const len = Math.max(ka.nums.length, kb.nums.length);
    for (let i = 0; i < len; i++) {
      const x = ka.nums[i], y = kb.nums[i];
      if (x === undefined || y === undefined) return ka.nums.length - kb.nums.length;
      if (x !== y) return x - y;
    }
    return 0;
  }

  // Descending order (reverse=True), built by swapping the comparator's
  // arguments rather than negating the result — that keeps ties returning
  // exactly 0, so JS's stable sort leaves tied builds in their original
  // relative order, same as Python's reverse=True.
  function cmpBuildDesc(a, b) {
    return cmpBuildKeyAsc(buildSortKey(b), buildSortKey(a));
  }

  function deriveBuilds(runs) {
    const seen = new Set();
    const order = [];
    for (const run of runs) {
      if (!seen.has(run.build)) {
        seen.add(run.build);
        order.push(run.build);
      }
    }
    return order.sort(cmpBuildDesc);
  }

  // ---- Rebuilding the rest of build_html()'s derived fields ---------------

  function deriveCharacters(runs) {
    return [...new Set(runs.map(r => r.char))].sort();
  }

  function deriveAscensions(runs) {
    return [...new Set(runs.map(r => r.asc))].sort((a, b) => a - b);
  }

  // Same precedence as build_html(): per-run encounter/card/relic ids seen
  // in fights/cardsOffered/relicsOffered get labelled first (catalog title
  // if there is one, else the fmt_* fallback); then every catalog entry
  // that has a title gets set as a fallback default too, so tooltips can
  // name cards/relics this player was never offered (e.g. ones skipped or
  // removed, which never show up in cardsOffered).
  function deriveLabels(runs, cardData, relicData) {
    const encLabels = {};
    const cardLabels = {};
    const relicLabels = {};

    for (const run of runs) {
      for (const fight of run.fights || []) {
        const enc = fight.enc;
        if (enc && !(enc in encLabels)) encLabels[enc] = fmtEncounter(enc);
      }
      for (const cid of Object.keys(run.cardsOffered || {})) {
        if (cid && !(cid in cardLabels)) {
          const meta = cardData[cid];
          cardLabels[cid] = (meta && meta.title) || fmtCard(cid);
        }
      }
      for (const rid of Object.keys(run.relicsOffered || {})) {
        if (rid && !(rid in relicLabels)) {
          const meta = relicData[rid];
          relicLabels[rid] = (meta && meta.title) || fmtRelic(rid);
        }
      }
    }

    for (const [cid, meta] of Object.entries(cardData)) {
      if (meta.title && !(cid in cardLabels)) cardLabels[cid] = meta.title;
    }
    for (const [rid, meta] of Object.entries(relicData)) {
      if (meta.title && !(rid in relicLabels)) relicLabels[rid] = meta.title;
    }

    return { encLabels, cardLabels, relicLabels };
  }

  // Builds the exact DATA shape build_html() embeds, key order included
  // (it has no functional effect, but matches the Python dict literal so
  // the two are easy to diff against each other).
  function buildData(catalog, runs) {
    const characters = deriveCharacters(runs);
    const ascensions = deriveAscensions(runs);
    const builds = deriveBuilds(runs);
    const charColors = characters.map(c => catalog.charColorMap[c] || "#888");
    const { encLabels, cardLabels, relicLabels } =
      deriveLabels(runs, catalog.cardData, catalog.relicData);

    return {
      characters,
      charColors,
      ascensions,
      builds,
      encLabels,
      encGroups: catalog.encGroups,
      cardLabels,
      relicLabels,
      cardImages: catalog.cardImages,
      cardImageOverrides: catalog.cardImageOverrides,
      cardData: catalog.cardData,
      cardChar: catalog.cardChar,
      relicData: catalog.relicData,
      potionData: catalog.potionData,
      nodeIcons: catalog.nodeIcons,
      cardFinal: catalog.cardFinal,
      energyIcons: catalog.energyIcons,
      runsData: runs,
    };
  }

  // ---- No-profile / error fallback ----------------------------------------
  //
  // Whenever we're not going to load /app.js (no user in the URL, or a
  // fetch didn't work out), the filter bar and page tabs are dead UI —
  // they're wired up by app.js, which never runs in these cases — so they
  // get hidden along with swapping in a short explanation. textContent
  // only: nothing here is ever built from interpolated HTML.
  function showFallback(message) {
    const main = document.getElementById("main-content");
    if (main) {
      main.textContent = "";
      const p = document.createElement("p");
      p.textContent = message;
      main.appendChild(p);
    }
    const filterBar = document.getElementById("shared-filter-bar");
    if (filterBar) filterBar.style.display = "none";
    document.querySelectorAll(".page-tabs").forEach(el => { el.style.display = "none"; });
  }

  function showNoProfile() {
    showFallback(
      "This is a Slay the Spire 2 run-history site. Profiles live at " +
      "/u/steam-<SteamID64> (upload/sign-in coming soon)."
    );
  }

  function showNoRuns() {
    showFallback("No runs have been uploaded for this profile yet.");
  }

  function showError() {
    showFallback("Something went wrong loading this profile. Please try again later.");
  }

  function loadAppScript() {
    const script = document.createElement("script");
    script.src = "/app.js";
    document.body.appendChild(script);
  }

  // ---- Entry point ---------------------------------------------------------

  async function main() {
    // Strict match: /u/steam-<17 digits>, optional trailing slash.
    const match = location.pathname.match(/^\/u\/steam-(\d{17})\/?$/);
    if (!match) {
      showNoProfile();
      return;
    }
    const steamId = match[1];

    let catalogResp, userResp;
    try {
      [catalogResp, userResp] = await Promise.all([
        fetch("/catalog.json"),
        fetch(`/users/steam-${steamId}.json.gz`),
      ]);
    } catch (e) {
      showError();
      return;
    }

    // Check the blob's own status first — a missing/forbidden profile is a
    // known, expected case with its own message, regardless of how the
    // catalog fetch went.
    if (userResp.status === 403 || userResp.status === 404) {
      showNoRuns();
      return;
    }
    if (!catalogResp.ok || !userResp.ok) {
      showError();
      return;
    }

    let catalog, userDoc;
    try {
      [catalog, userDoc] = await Promise.all([catalogResp.json(), userResp.json()]);
    } catch (e) {
      showError();
      return;
    }

    window.DATA = buildData(catalog, userDoc.runs || []);
    loadAppScript();
  }

  main();

})();
