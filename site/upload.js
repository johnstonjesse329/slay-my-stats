// =========================================================================
// Upload — "Sign in with Steam" and the run-history upload, live site only.
//
// Flow:
//   1. The site bar's "Upload runs" button sends the browser to Steam's
//      OpenID login, with this site's root as return_to.
//   2. Steam redirects back to /?openid.mode=id_res&openid.claimed_id=...
//      Those params are the proof of who signed in; they're moved out of the
//      address bar (so they don't linger in history or get shared) into
//      sessionStorage, and the upload panel takes over the page.
//   3. The player picks their history folder. Each .run file is re-serialized
//      onto one line (NDJSON). The OpenID params go to the ingest endpoint,
//      which re-verifies them with Steam and hands back a one-time upload
//      URL (a presigned S3 POST) plus the player's profile slug, if any.
//   4. Runs the profile already has are dropped, the rest are gzip'd with
//      CompressionStream and POSTed straight to S3 as one file. Its arrival
//      there triggers the processing, which merges the runs into the profile
//      and writes a small result file the page polls for.
//
// Profiles live at /u/<slug>, a slug the server picks from the Steam name on
// the first upload. Each upload's answer ({slug, name}) is also remembered in
// localStorage, so a later visit can check for new runs before signing in.
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
  const PROFILE_KEY = "sms-profile-";  // + steamId -> {slug, name}
  // The ingest endpoint refuses sign-ins older than 30 minutes; stop offering
  // an upload a bit before that so it doesn't fail at the last step.
  const SIGNIN_MAX_AGE_MS = 25 * 60 * 1000;
  // How often and how long to wait for an upload's result. Processing a big
  // first upload takes a while; past this the page stops waiting, but the
  // upload still lands.
  const POLL_MS = 2000;
  const POLL_GIVE_UP_MS = 6 * 60 * 1000;  // the process Lambda's timeout, plus a minute
  // An upload URL is good for 10 minutes; reuse one after a failed send
  // only while it has a bit of that left.
  const UPLOAD_URL_MAX_AGE_MS = 8 * 60 * 1000;

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

  function knownProfile(steamId) {
    try {
      const p = JSON.parse(localStorage.getItem(PROFILE_KEY + steamId) || "null");
      if (p && /^[a-z0-9]{1,32}(-[1-9][0-9]{0,5})?$/.test(p.slug)) return p;
    } catch (e) { /* ignore */ }
    return null;
  }

  function rememberProfile(steamId, slug, name) {
    try { localStorage.setItem(PROFILE_KEY + steamId, JSON.stringify({ slug, name })); } catch (e) { /* ignore */ }
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

  // ts values already on the player's profile, so they aren't re-sent; the
  // profile's summary lists them by month. Runs the server has no raw copy
  // of (noRaw; every run, on a profile from before raw copies were kept) are
  // sent again so it gets one.
  async function existingTimestamps(slug) {
    if (!slug) return new Set();
    try {
      const resp = await fetch(`/users/${slug}.json.gz`, { cache: "no-store" });
      if (!resp.ok) return new Set();
      const doc = await resp.json();
      const all = doc.months ? Object.values(doc.months).flat() : (doc.runs || []).map(r => r.ts);
      const noRaw = new Set(doc.noRaw || all);
      return new Set(all.filter(ts => !noRaw.has(ts)));
    } catch (e) {
      return new Set();
    }
  }

  async function gzip(text) {
    const stream = new Blob([text]).stream().pipeThrough(new CompressionStream("gzip"));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }

  // Polls for the result the processing writes once an upload is in.
  // Resolves to the result, or null if it didn't show up in time.
  async function waitForResult(uploadId) {
    const giveUp = Date.now() + POLL_GIVE_UP_MS;
    while (Date.now() < giveUp) {
      await new Promise(r => setTimeout(r, POLL_MS));
      try {
        const resp = await fetch(`/users/_uploads/${uploadId}.json.gz`, { cache: "no-store" });
        if (resp.ok) return await resp.json();
      } catch (e) { /* not there yet, or a blip: keep waiting */ }
    }
    return null;
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
    const links = document.querySelector(".site-links");
    if (!links) return;
    const btn = el("button", { type: "button", className: "upload-btn", textContent: "Upload runs" });
    const upload = () => {
      if (!signIn || Date.now() - signIn.at >= SIGNIN_MAX_AGE_MS) startSignIn();
      else if (onRoot) showUploadPanel(signIn);
      else location.assign("/#upload");
    };
    btn.addEventListener("click", upload);
    links.insertBefore(btn, links.querySelector(".site-github"));  // null: at the end
    // <a data-upload> in page text (e.g. the About page) does the same. Delegated,
    // since boot.js fetches page bodies in after this script has run.
    document.addEventListener("click", e => {
      if (!e.target.closest("a[data-upload]")) return;
      e.preventDefault();
      upload();
    });
  }

  // Replaces the page (like boot.js's fallbacks do) with the upload panel.
  function showUploadPanel(signIn) {
    const main = document.getElementById("main-content");
    if (!main) return;
    const filterBar = document.getElementById("shared-filter-bar");
    if (filterBar) filterBar.style.display = "none";
    document.querySelectorAll(".page-tabs").forEach(n => { n.style.display = "none"; });

    const profile = knownProfile(signIn.steamId);
    const status = el("p", { className: "upload-status", role: "status" });
    const folderInput = el("input", { type: "file", multiple: true, className: "upload-input", id: "upload-folder" });
    folderInput.setAttribute("webkitdirectory", "");

    // A page can't open the picker at a path of its choosing (browsers only
    // offer Documents, Downloads and the like as starting points), so the
    // next best thing: copy the path, ready to paste into the picker.
    const isMac = navigator.platform.startsWith("Mac");
    const historyPath = isMac
      ? "~/Library/Application Support/SlayTheSpire2/steam/" + signIn.steamId + "/profile1/saves/history"
      : "%APPDATA%\\SlayTheSpire2\\steam\\" + signIn.steamId + "\\profile1\\saves\\history";
    const pathCode = el("code", { textContent: historyPath });
    const copyBtn = el("button", { type: "button", className: "upload-copy", textContent: "Copy" });
    let copiedTimer;
    const copyPath = () => {
      const done = () => {
        copyBtn.textContent = "Copied ✓";
        clearTimeout(copiedTimer);
        copiedTimer = setTimeout(() => { copyBtn.textContent = "Copy"; }, 2500);
      };
      // No clipboard access (old browser, not https): select the path so
      // Ctrl+C gets it.
      const fallback = () => { getSelection().selectAllChildren(pathCode); };
      if (navigator.clipboard) navigator.clipboard.writeText(historyPath).then(done, fallback);
      else fallback();
    };
    copyBtn.addEventListener("click", copyPath);
    const folderBtn = el("button", { type: "button", className: "upload-btn", textContent: "Choose history folder" });
    // Copies too, in case step 1 was skipped.
    folderBtn.addEventListener("click", () => { copyPath(); folderInput.click(); });

    const step = (title, ...body) => el("li", {}, [el("strong", { textContent: title }), ...body]);
    const panel = el("section", { className: "upload-panel" }, [
      el("h2", { textContent: "Upload your runs" }),
      el("p", {}, profile
        ? ["Signed in with Steam as ", el("a", { href: `/u/${profile.slug}`, textContent: profile.name }), "."]
        : ["Signed in with Steam. Your profile's address comes from your Steam name."]),
      el("ol", { className: "upload-steps" }, [
        step("Copy your run history folder's location.",
          el("div", { className: "upload-path" }, [pathCode, copyBtn])),
        step("Click Choose history folder below.",
          el("div", { className: "upload-actions" }, [folderBtn, folderInput])),
        isMac
          ? step("Go to the folder:", " press ⌘⇧G, paste (⌘V) and press Return.")
          : step("Go to the folder:", " click the address bar at the top of the window that opens, paste (Ctrl+V) and press Enter."),
        step("Select it", " even though it looks empty (the picker only shows folders, not the run files inside)"
          + " and click Upload (or Select). If your browser asks whether to upload the files, say yes."),
      ]),
      el("p", { className: "upload-note", textContent: "Runs already on your profile are skipped." }),
      status,
    ]);
    main.textContent = "";
    main.append(panel);

    let busy = false;
    const onPick = async (input) => {
      if (busy || !input.files.length) return;
      busy = true;
      try {
        await upload(signIn, [...input.files], status);
      } finally {
        busy = false;
        input.value = "";
      }
    };
    folderInput.addEventListener("change", () => onPick(folderInput));
  }

  function setStatus(status, text, link) {
    status.textContent = text;
    if (link) status.append(" ", el("a", { href: link.href, textContent: link.text }));
  }

  // An upload URL handed out for this sign-in and not yet used: a send that
  // failed on the way to S3 can try again with it, without a new sign-in.
  let pending = null;  // {auth, at}

  function signInAgain(status, text) {
    forgetSignIn();
    setStatus(status, text);
    status.append(" ", el("button", { type: "button", className: "upload-link", textContent: "Sign in again",
                                      onclick: startSignIn }));
  }

  // The sign-in's params go to the ingest endpoint, which answers with a
  // one-time upload URL. Resolves to that answer, or null (status says why).
  async function authorize(signIn, status) {
    let url;
    try {
      url = await ingestUrl();
    } catch (e) {
      setStatus(status, "Uploads aren't available right now.");
      return null;
    }
    let resp, result;
    try {
      resp = await fetch(`${url}?${new URLSearchParams(signIn.params)}`, { method: "POST" });
      result = await resp.json();
    } catch (e) {
      setStatus(status, "Upload failed — couldn't reach the server. Try again in a moment.");
      return null;
    }
    if (!resp.ok) {
      // A rejected or expired sign-in can't be retried; a cooldown or conflict
      // can. Steam may also refuse a sign-in it already confirmed once.
      if (["signin_expired", "bad_openid"].includes(result.error)) {
        signInAgain(status, result.message || "Sign in again to upload.");
      } else {
        setStatus(status, result.message || `Upload failed (${resp.status}).`);
      }
      return null;
    }
    // The sign-in is kept: it works again (after the cooldown) until it expires.
    return result;
  }

  async function upload(signIn, files, status) {
    if (pending && Date.now() - pending.at >= UPLOAD_URL_MAX_AGE_MS) pending = null;
    if (!pending && Date.now() - signIn.at >= SIGNIN_MAX_AGE_MS) {
      signInAgain(status, "Your Steam sign-in has expired.");
      return;
    }

    setStatus(status, "Reading files…");
    const { runs, unreadable } = await readRuns(files);
    if (!runs.length) {
      setStatus(status, "No .run files found there. Pick the history folder itself (the one full of numbered .run files).");
      return;
    }

    // With a remembered profile, check for new runs before asking for an
    // upload URL: if there are none, there is nothing to send.
    setStatus(status, `Found ${runs.length} runs. Checking which are new…`);
    const known = knownProfile(signIn.steamId);
    let slug = known && known.slug;
    let have = await existingTimestamps(slug);
    const allThere = () => runs.every(r => have.has(r.start));
    if (allThere()) {
      setStatus(status, `All ${runs.length} runs are already on your profile.`, { href: `/u/${slug}`, text: "View profile" });
      return;
    }

    if (!pending) {
      const auth = await authorize(signIn, status);
      if (!auth) return;
      pending = { auth, at: Date.now() };
    }
    const auth = pending.auth;
    // The server knows the profile even when this browser doesn't (another
    // device, cleared storage).
    if (auth.slug && auth.slug !== slug) {
      slug = auth.slug;
      have = await existingTimestamps(slug);
      if (allThere()) {
        pending = null;
        setStatus(status, `All ${runs.length} runs are already on your profile.`, { href: `/u/${slug}`, text: "View profile" });
        return;
      }
    }
    const fresh = runs.filter(r => !have.has(r.start)).map(r => r.line);

    setStatus(status, `Compressing ${fresh.length} new runs…`);
    const body = await gzip(fresh.join("\n"));
    if (body.length > auth.maxBytes) {
      pending = null;
      setStatus(status, `That's ${(body.length / 1048576).toFixed(0)} MB compressed, over the `
        + `${(auth.maxBytes / 1048576).toFixed(0)} MB upload limit.`);
      return;
    }

    setStatus(status, `Uploading ${fresh.length} runs (${(body.length / 1048576).toFixed(1)} MB)…`);
    const form = new FormData();
    for (const [k, v] of Object.entries(auth.fields)) form.append(k, v);
    form.append("file", new Blob([body], { type: "application/gzip" }), "runs.ndjson.gz");  // must come last
    let resp;
    try {
      resp = await fetch(auth.url, { method: "POST", body: form });
    } catch (e) {
      resp = null;
    }
    if (!resp || !resp.ok) {
      setStatus(status, "Upload failed — couldn't send the file. Pick the folder again to retry.");
      return;
    }
    pending = null;

    setStatus(status, `Sent. Adding ${fresh.length} runs to your profile…`);
    const result = await waitForResult(auth.uploadId);
    const profileLink = (result && result.slug) || slug
      ? { href: `/u/${(result && result.slug) || slug}`, text: "View profile" } : null;
    if (!result) {
      setStatus(status, "Your runs are uploaded but still being added. Check your profile in a few minutes.", profileLink);
      return;
    }
    if (result.status !== "done") {
      setStatus(status, result.message || "That upload couldn't be added.", profileLink);
      return;
    }
    if (result.slug) rememberProfile(signIn.steamId, result.slug, result.name);
    if (!result.added) {
      setStatus(status, result.duplicates
        ? `All ${result.duplicates} runs are already on your profile.`
        : "None of those files could be read as runs.", profileLink);
      return;
    }
    const parts = [`Added ${result.added} run${result.added === 1 ? "" : "s"}; your profile now has ${result.total}.`];
    if (result.rejected + unreadable) parts.push(`${result.rejected + unreadable} file(s) couldn't be read as runs and were skipped.`);
    setStatus(status, parts.join(" "), profileLink);
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
