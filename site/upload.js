// =========================================================================
// Upload — "Sign in with Steam" and the run-history upload, live site only.
//
// Flow:
//   1. The header's "Upload your runs" button sends the browser to Steam's
//      OpenID login, with this site's root as return_to.
//   2. Steam redirects back to /?openid.mode=id_res&openid.claimed_id=...
//      Those params are the proof of who signed in; they're moved out of the
//      address bar (so they don't linger in history or get shared) into
//      sessionStorage, and the upload panel takes over the page.
//   3. The player picks their history folder. Each .run file is re-serialized
//      onto one line (NDJSON), runs the server already has are dropped, and
//      the rest are gzip'd with CompressionStream and POSTed along with the
//      OpenID params to the ingest endpoint, which re-verifies them with
//      Steam and merges the runs into the player's profile.
//
// The ingest endpoint's URL comes from /site-config.json (the Lambda's
// Function URL, written at deploy time; tools/serve_site.py answers it with
// its own /api/ingest).
//
// Classic script in an IIFE, like boot.js. Every piece of text shown comes
// from textContent, never from interpolated HTML.
// =========================================================================
(function () {

  const STEAM_LOGIN = "https://steamcommunity.com/openid/login";
  const SIGNIN_KEY = "sms-steam-signin";
  // The ingest endpoint refuses sign-ins older than 30 minutes; stop offering
  // an upload a bit before that so it doesn't fail at the last step.
  const SIGNIN_MAX_AGE_MS = 25 * 60 * 1000;
  // Function URL requests cap at 6 MB, and a binary body is base64'd inside
  // that (x4/3). ~1,700 typical runs fit; bigger histories go in parts.
  const MAX_BODY_BYTES = 4 * 1024 * 1024;

  function el(tag, props, children) {
    const node = document.createElement(tag);
    Object.assign(node, props || {});
    for (const c of children || []) node.append(c);
    return node;
  }

  // ---- Steam sign-in ------------------------------------------------------

  function startSignIn() {
    const root = location.origin + "/";
    const q = new URLSearchParams({
      "openid.ns": "http://specs.openid.net/auth/2.0",
      "openid.mode": "checkid_setup",
      "openid.return_to": root,
      "openid.realm": root,
      "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
      "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
    });
    location.assign(`${STEAM_LOGIN}?${q}`);
  }

  // Returns {signIn: {params, steamId, at} | null, fresh}. Picks up a sign-in
  // Steam just returned in the URL first (stripping it from the address
  // bar), else a remembered one that's still young enough to use.
  function takeSignIn() {
    const search = new URLSearchParams(location.search);
    const mode = search.get("openid.mode");
    if (mode) history.replaceState(null, "", location.pathname + location.hash);
    if (mode === "id_res") {
      const params = {};
      for (const [k, v] of search) if (k.startsWith("openid.")) params[k] = v;
      const m = (params["openid.claimed_id"] || "").match(/^https:\/\/steamcommunity\.com\/openid\/id\/(\d{17})$/);
      if (m) {
        const signIn = { params, steamId: m[1], at: Date.now() };
        try { sessionStorage.setItem(SIGNIN_KEY, JSON.stringify(signIn)); } catch (e) { /* private mode */ }
        return { signIn, fresh: true };
      }
    }
    try {
      const saved = JSON.parse(sessionStorage.getItem(SIGNIN_KEY) || "null");
      if (saved && Date.now() - saved.at < SIGNIN_MAX_AGE_MS) return { signIn: saved, fresh: false };
    } catch (e) { /* ignore */ }
    return { signIn: null, fresh: false };
  }

  function forgetSignIn() {
    try { sessionStorage.removeItem(SIGNIN_KEY); } catch (e) { /* ignore */ }
  }

  // ---- Reading the history folder ------------------------------------------

  // Resolves to [{start, line}] for every readable .run file, oldest first.
  // Files that aren't JSON objects are skipped here (and counted) rather than
  // sent -- the server would only reject them.
  async function readRuns(files) {
    const runs = [];
    let unreadable = 0;
    for (const f of files) {
      if (!f.name.endsWith(".run")) continue;
      try {
        const data = JSON.parse(await f.text());
        if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("not a run");
        runs.push({ start: data.start_time, line: JSON.stringify(data) });
      } catch (e) {
        unreadable++;
      }
    }
    runs.sort((a, b) => (a.start || 0) - (b.start || 0));
    return { runs, unreadable };
  }

  // ts values already on the player's profile, so they aren't re-sent.
  async function existingTimestamps(steamId) {
    try {
      const resp = await fetch(`/users/steam-${steamId}.json.gz`, { cache: "no-store" });
      if (!resp.ok) return new Set();
      const doc = await resp.json();
      return new Set((doc.runs || []).map(r => r.ts));
    } catch (e) {
      return new Set();
    }
  }

  async function gzip(text) {
    const stream = new Blob([text]).stream().pipeThrough(new CompressionStream("gzip"));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }

  // The largest oldest-first prefix of `lines` whose gzip fits the limit.
  // Compression ratio is steady across runs, so one estimate then shrinking
  // by the overshoot converges in a pass or two.
  async function fitBatch(lines) {
    let n = lines.length;
    for (;;) {
      const body = await gzip(lines.slice(0, n).join("\n"));
      if (body.length <= MAX_BODY_BYTES || n === 1) return { body, count: n };
      n = Math.max(1, Math.floor(n * (MAX_BODY_BYTES / body.length) * 0.95));
    }
  }

  async function ingestUrl() {
    const resp = await fetch("/site-config.json", { cache: "no-store" });
    if (!resp.ok) throw new Error("no site config");
    const cfg = await resp.json();
    if (!cfg.ingestUrl) throw new Error("no ingest url");
    return cfg.ingestUrl;
  }

  // ---- UI -------------------------------------------------------------------

  function addHeaderButton(signIn, onRoot) {
    const header = document.querySelector("header");
    if (!header) return;
    const btn = el("button", { type: "button", className: "upload-btn", textContent: "Upload your runs" });
    btn.addEventListener("click", () => {
      if (!signIn || Date.now() - signIn.at >= SIGNIN_MAX_AGE_MS) startSignIn();
      else if (onRoot) showUploadPanel(signIn);
      else location.assign("/#upload");
    });
    header.append(btn);
  }

  // Replaces the page (like boot.js's fallbacks do) with the upload panel.
  function showUploadPanel(signIn) {
    const main = document.getElementById("main-content");
    if (!main) return;
    const filterBar = document.getElementById("shared-filter-bar");
    if (filterBar) filterBar.style.display = "none";
    document.querySelectorAll(".page-tabs").forEach(n => { n.style.display = "none"; });

    const profileUrl = `/u/steam-${signIn.steamId}`;
    const status = el("p", { className: "upload-status", role: "status" });
    const folderInput = el("input", { type: "file", multiple: true, className: "upload-input", id: "upload-folder" });
    folderInput.setAttribute("webkitdirectory", "");
    const filesInput = el("input", { type: "file", multiple: true, accept: ".run", className: "upload-input", id: "upload-files" });

    const pathHint = el("code", {
      textContent: navigator.platform.startsWith("Mac")
        ? "~/Library/Application Support/SlayTheSpire2/steam/" + signIn.steamId + "/profile1/saves/history"
        : "%APPDATA%\\SlayTheSpire2\\steam\\" + signIn.steamId + "\\profile1\\saves\\history",
    });

    const panel = el("section", { className: "upload-panel" }, [
      el("h2", { textContent: "Upload your runs" }),
      el("p", {}, [
        "Signed in with Steam as ",
        el("a", { href: profileUrl, textContent: signIn.steamId }),
        ". Choose your Slay the Spire 2 run history folder:",
      ]),
      el("p", {}, [pathHint]),
      el("p", { className: "upload-note", textContent:
        "Only runs this profile doesn't already have are sent. On Windows, paste the path above into the folder picker's address bar." }),
      el("div", { className: "upload-actions" }, [
        el("label", { className: "upload-btn", htmlFor: "upload-folder", textContent: "Choose history folder" }),
        folderInput,
        el("label", { className: "upload-link", htmlFor: "upload-files", textContent: "or pick .run files" }),
        filesInput,
      ]),
      status,
    ]);
    main.textContent = "";
    main.append(panel);

    let busy = false;
    const onPick = async (input) => {
      if (busy || !input.files.length) return;
      busy = true;
      try {
        await upload(signIn, [...input.files], status, profileUrl);
      } finally {
        busy = false;
        input.value = "";
      }
    };
    folderInput.addEventListener("change", () => onPick(folderInput));
    filesInput.addEventListener("change", () => onPick(filesInput));
  }

  function setStatus(status, text, link) {
    status.textContent = text;
    if (link) status.append(" ", el("a", { href: link.href, textContent: link.text }));
  }

  async function upload(signIn, files, status, profileUrl) {
    if (Date.now() - signIn.at >= SIGNIN_MAX_AGE_MS) {
      forgetSignIn();
      setStatus(status, "Your Steam sign-in has expired.");
      status.append(" ", el("button", { type: "button", className: "upload-link", textContent: "Sign in again",
                                        onclick: startSignIn }));
      return;
    }

    setStatus(status, "Reading files…");
    const { runs, unreadable } = await readRuns(files);
    if (!runs.length) {
      setStatus(status, "No .run files found there. Pick the history folder itself (the one full of numbered .run files).");
      return;
    }

    setStatus(status, `Found ${runs.length} runs. Checking which are new…`);
    const have = await existingTimestamps(signIn.steamId);
    const fresh = runs.filter(r => !have.has(r.start)).map(r => r.line);
    if (!fresh.length) {
      setStatus(status, `All ${runs.length} runs are already on your profile.`, { href: profileUrl, text: "View profile" });
      return;
    }

    setStatus(status, `Compressing ${fresh.length} new runs…`);
    const { body, count } = await fitBatch(fresh);

    let url;
    try {
      url = await ingestUrl();
    } catch (e) {
      setStatus(status, "Uploads aren't available right now.");
      return;
    }

    setStatus(status, `Uploading ${count} runs (${(body.length / 1048576).toFixed(1)} MB)…`);
    let resp, result;
    try {
      const q = new URLSearchParams(signIn.params);
      resp = await fetch(`${url}?${q}`, {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body,
      });
      result = await resp.json();
    } catch (e) {
      setStatus(status, "Upload failed — couldn't reach the server. Try again in a moment.");
      return;
    }

    if (!resp.ok) {
      // A used or expired sign-in can't be retried; a cooldown or conflict can.
      if (["signin_used", "signin_expired", "bad_openid"].includes(result.error)) {
        forgetSignIn();
        setStatus(status, result.message || "Sign in again to upload.");
        status.append(" ", el("button", { type: "button", className: "upload-link", textContent: "Sign in again",
                                          onclick: startSignIn }));
      } else {
        setStatus(status, result.message || `Upload failed (${resp.status}).`);
      }
      return;
    }

    // One sign-in, one write: the server refuses the same sign-in twice.
    if (result.added) forgetSignIn();
    const parts = [`Added ${result.added} run${result.added === 1 ? "" : "s"}; your profile now has ${result.total}.`];
    if (result.rejected + unreadable) parts.push(`${result.rejected + unreadable} file(s) couldn't be read as runs and were skipped.`);
    const left = fresh.length - count;
    if (left > 0) parts.push(`${left} more runs didn't fit in one upload — sign in again in a minute to send the rest.`);
    setStatus(status, parts.join(" "), { href: profileUrl, text: "View profile" });
  }

  // ---- Entry point -----------------------------------------------------------

  // The panel only ever takes over the root page: on a profile, app.js owns
  // #main-content. A sign-in that just arrived (Steam returns to the root)
  // opens it straight away; a remembered one waits for the header button.
  const onRoot = location.pathname === "/" || location.pathname === "/index.html";
  const { signIn, fresh } = takeSignIn();
  addHeaderButton(signIn, onRoot);
  if (onRoot && signIn && (fresh || location.hash === "#upload")) showUploadPanel(signIn);

})();
