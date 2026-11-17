// =========================================================================
// Upload — "Sign in with Steam" and the run-history upload, live site only.
//
// Flow:
//   1. The call to action asks /auth/me who is signed in. Signed out, it goes
//      to /auth/login, which sends the browser through Steam's sign-in and
//      back to /upload with the site's session cookie set (infra session.py).
//   2. On /upload (or with #upload), a signed-in visitor gets the upload
//      panel in place of the page.
//   3. The player picks their history folder. Each .run file is re-serialized
//      onto one line (NDJSON). A POST to /auth/upload, which trusts only the
//      session cookie, hands back a one-time upload URL (a presigned S3 POST)
//      plus the player's profile slug, if any.
//   4. Runs the profile already has are dropped, the rest are gzip'd with
//      CompressionStream and POSTed straight to S3 as one file. Its arrival
//      there triggers the processing, which merges the runs into the profile
//      and writes a small result file the page polls for.
//
// Profiles live at /u/<slug>, a slug the server picks from the Steam name on
// the first upload. Each upload's answer ({slug, name}) is also remembered in
// localStorage, so a later visit can check for new runs before signing in.
//
// /auth/* is on the site's own origin: CloudFront sends it to the ingest
// Lambda, and tools/serve_site.py answers it locally.
//
// Classic script in an IIFE, like boot.js. Every piece of text shown comes
// from textContent, never from interpolated HTML.
// =========================================================================
(function () {

  const PROFILE_KEY = "sms-profile-";  // + steamId -> {slug, name}
  // How often and how long to wait for an upload's result. Processing a big
  // first upload takes a while; past this the page stops waiting, but the
  // upload still lands.
  const POLL_MS = 2000;
  const POLL_GIVE_UP_MS = 6 * 60 * 1000;  // the process Lambda's timeout, plus a minute
  // An upload URL is good for 10 minutes; reuse one after a failed send
  // only while it has a bit of that left.
  const UPLOAD_URL_MAX_AGE_MS = 8 * 60 * 1000;
  // Paths where the panel may take over #main-content: the root page and the
  // Upload page. On a profile app.js owns #main-content, and the other
  // hand-written pages have nothing to upload from. Trailing slashes normalize
  // away, so /upload/ counts as /upload.
  const PANEL_PATHS = new Set(["/", "/index.html", "/upload"]);
  const HERE_PATH = location.pathname.replace(/\/+$/, "") || "/";
  const onPanelPage = PANEL_PATHS.has(HERE_PATH);

  function el(tag, props, children) {
    const node = document.createElement(tag);
    Object.assign(node, props || {});
    for (const c of children || []) node.append(c);
    return node;
  }

  const runCount = n => `${n} run${n === 1 ? "" : "s"}`;
  const alreadyThere = n => n === 1 ? "That run is already on your profile."
    : `All ${n} runs are already on your profile.`;

  // ---- Steam sign-in ------------------------------------------------------

  // Through Steam and back to the Upload page, where the panel lives.
  function startSignIn() {
    location.assign("/auth/login?next=%2Fupload");
  }

  // The signed-in Steam ID, or null (signed out, or the server can't be reached).
  async function whoAmI() {
    try {
      const resp = await fetch("/auth/me", { cache: "no-store" });
      return resp.ok ? (await resp.json()).steamId || null : null;
    } catch (e) {
      return null;
    }
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

  // ---- UI -------------------------------------------------------------------

  // The site bar's "Upload runs" entry is a link to the Upload page, taken from
  // the `nav:` label on site/pages/upload.html. What this wires up is the call
  // to action on that page.
  function wireUploadLinks(canHostPanel) {
    const upload = async () => {
      const steamId = await whoAmI();
      if (!steamId) startSignIn();
      else if (canHostPanel) showUploadPanel(steamId);
      else location.assign("/upload#upload");
    };
    // <a data-upload> in page text. Delegated, since boot.js fetches page bodies
    // in after this script has run.
    document.addEventListener("click", e => {
      if (!e.target.closest("a[data-upload]")) return;
      e.preventDefault();
      upload();
    });
  }

  // Replaces the page (like boot.js's fallbacks do) with the upload panel.
  function showUploadPanel(steamId) {
    const main = document.getElementById("main-content");
    if (!main) return;
    // boot.js's page renderer is mid-fetch for /upload and would paint the page
    // body over this panel when it resolves, so claim #main-content first.
    window.uploadPanelActive = true;
    const filterBar = document.getElementById("shared-filter-bar");
    if (filterBar) filterBar.style.display = "none";
    document.querySelectorAll(".page-tabs").forEach(n => { n.style.display = "none"; });

    const profile = knownProfile(steamId);
    const status = el("div", { className: "upload-status", role: "status" });
    const folderInput = el("input", { type: "file", multiple: true, className: "upload-input", id: "upload-folder" });
    folderInput.setAttribute("webkitdirectory", "");

    // A page can't open the picker at a path of its choosing (browsers only
    // offer Documents, Downloads and the like as starting points), so the
    // next best thing: copy the path, ready to paste into the picker.
    //
    // Only Windows and macOS are written for -- navigator.platform is "Mac..."
    // there and "Win..." there, and something else on a phone, tablet or Linux
    // box. Those get no path line, no Copy button and no "go to the folder"
    // step: the fallback path is Windows, so showing it anywhere else would just
    // be a wrong answer, and this is the one part of the panel that differs per
    // platform.
    const isMac = navigator.platform.startsWith("Mac");
    const hasPath = isMac || navigator.platform.startsWith("Win");
    const historyPath = isMac
      ? "~/Library/Application Support/SlayTheSpire2/steam/" + steamId + "/profile1/saves/history"
      : "%APPDATA%\\SlayTheSpire2\\steam\\" + steamId + "\\profile1\\saves\\history";
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
    folderBtn.addEventListener("click", () => { if (hasPath) copyPath(); folderInput.click(); });

    const step = (title, ...body) => el("li", {}, [title, ...body]);
    const panel = el("section", { className: "upload-panel" }, [
      el("h2", { textContent: "Upload your runs" }),
      el("p", {}, profile
        ? ["Signed in with Steam as ", el("a", { href: `/u/${profile.slug}`, textContent: profile.name }), "."]
        : ["Signed in with Steam."]),
      el("ol", { className: "upload-steps" }, [
        // The path, and getting the picker to it, are the only platform-specific
        // steps; everything else applies wherever runs can be picked at all.
        ...(hasPath ? [
          step("Copy the folder path.",
            el("div", { className: "upload-path" }, [pathCode, copyBtn])),
        ] : []),
        step("Click Choose history folder.",
          el("div", { className: "upload-actions" }, [folderBtn, folderInput])),
        ...(hasPath ? [isMac
          ? step("Go to the folder:", " press ⌘⇧G, paste, and then press Return.")
          : step("Go to the folder:", " click the address bar, paste, and then press Enter.")] : []),
        step("Select the folder", " and confirm. It looks empty because the picker only shows folders."),
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
        await upload(steamId, [...input.files], status);
      } finally {
        busy = false;
        input.value = "";
      }
    };
    folderInput.addEventListener("change", () => onPick(folderInput));
  }

  // The stages of an upload, each keeping its own line so nothing is rewritten
  // under the reader: finished ones stay with a tick and a figure, the current
  // one spins, the rest wait. [key, while doing it, once done]
  const STEPS = [
    ["read", "Reading files", "Read files"],
    ["check", "Checking which are new", "Checked which are new"],
    ["pack", "Compressing", "Compressed"],
    ["send", "Uploading", "Uploaded"],
    ["add", "Adding to your profile", "Added to your profile"],
  ];

  // The note under the steps: what to do next, or what went wrong.
  function noteOf(status) {
    if (!status.note) {
      status.note = el("p", { className: "upload-progress-note" });
      status.append(status.note);
    }
    return status.note;
  }

  // Move to a stage: the stages before it are done, it is under way. `detail`
  // is a figure for the line ("31 new"); one given to a stage stays on it.
  function step(status, key, detail) {
    status.stage = { key, halted: false, details: { ...(status.stage && status.stage.details) } };
    if (detail) status.stage.details[key] = detail;
    renderSteps(status);
  }

  // Every stage done; the last gets its figure.
  function stepsDone(status, detail) {
    if (!status.stage) return;
    status.stage = { key: "done", halted: false, details: { ...status.stage.details, add: detail } };
    renderSteps(status);
  }

  function renderSteps(status) {
    if (!status.stage) return;
    const at = status.stage.key === "done" ? STEPS.length : STEPS.findIndex(s => s[0] === status.stage.key);
    let list = status.querySelector(".upload-progress");
    if (!list) {
      list = el("ol", { className: "upload-progress" });
      status.prepend(list);
    }
    list.replaceChildren(...STEPS.map(([key, doing, did], i) => {
      const state = i < at ? "done" : i > at ? "wait" : status.stage.halted ? "halt" : "now";
      const mark = { done: "✓", now: "◐", halt: "•", wait: "○" }[state];
      const item = el("li", { className: state }, [el("i", { textContent: mark, ariaHidden: "true" }),
                      document.createTextNode(state === "done" ? did : doing)]);
      const detail = status.stage.details[key];
      if (detail && state !== "wait") item.append(el("small", { textContent: detail }));
      return item;
    }));
  }

  // A message below the steps. Once something has been said the current stage
  // stops spinning: it either failed or there is nothing left for it to do.
  function setStatus(status, text, link) {
    if (status.stage) {
      status.stage.halted = true;
      renderSteps(status);
    }
    const note = noteOf(status);
    note.textContent = text;
    if (link) note.append(" ", el("a", { href: link.href, textContent: link.text }));
  }

  // An upload URL handed out for this sign-in and not yet used: a send that
  // failed on the way to S3 can try again with it, without a new sign-in.
  let pending = null;  // {auth, at}

  function signInAgain(status, text) {
    setStatus(status, text);
    noteOf(status).append(" ", el("button", { type: "button", className: "upload-link", textContent: "Sign in again",
                                      onclick: startSignIn }));
  }

  // The session cookie goes with the POST; the answer is a one-time upload
  // URL. Resolves to that answer, or null (status says why).
  async function authorize(status) {
    let resp, result;
    try {
      resp = await fetch("/auth/upload", { method: "POST" });
      result = await resp.json();
    } catch (e) {
      setStatus(status, "Upload failed — couldn't reach the server. Try again in a moment.");
      return null;
    }
    if (!resp.ok) {
      // Signed out (the session expired, or signed out elsewhere) needs a new
      // sign-in; a cooldown or conflict can just be retried.
      if (resp.status === 401) {
        signInAgain(status, result.message || "Sign in through Steam to upload.");
      } else {
        setStatus(status, result.message || `Upload failed (${resp.status}).`);
      }
      return null;
    }
    return result;
  }

  // Every state where there is nothing left to do here ends on the profile page,
  // so the runs just added -- or the ones that turned out to be there already --
  // are what you see next. A beat first, so the line above can be read rather
  // than flashing past, and it says so, so the pause doesn't look like a hang.
  function finishAtProfile(status, text, slug) {
    if (!slug) {
      setStatus(status, text);
      return;
    }
    setStatus(status, `${text} Taking you to your profile…`);
    setTimeout(() => location.assign(`/u/${slug}`), 1800);
  }

  async function upload(steamId, files, status) {
    if (pending && Date.now() - pending.at >= UPLOAD_URL_MAX_AGE_MS) pending = null;

    step(status, "read");
    const { runs, unreadable } = await readRuns(files);
    if (!runs.length) {
      setStatus(status, "No .run files found there. Pick the history folder itself (the one full of numbered .run files).");
      return;
    }

    // With a remembered profile, check for new runs before asking for an
    // upload URL: if there are none, there is nothing to send.
    step(status, "check");
    status.stage.details.read = `${runCount(runs.length)} found`;
    renderSteps(status);
    const known = knownProfile(steamId);
    let slug = known && known.slug;
    let have = await existingTimestamps(slug);
    const allThere = () => runs.every(r => have.has(r.start));
    if (allThere()) {
      finishAtProfile(status, alreadyThere(runs.length), slug);
      return;
    }

    if (!pending) {
      const auth = await authorize(status);
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
        finishAtProfile(status, alreadyThere(runs.length), slug);
        return;
      }
    }
    const fresh = runs.filter(r => !have.has(r.start)).map(r => r.line);

    status.stage.details.check = `${fresh.length} new`;
    step(status, "pack");
    const body = await gzip(fresh.join("\n"));
    if (body.length > auth.maxBytes) {
      pending = null;
      setStatus(status, `That's ${(body.length / 1048576).toFixed(0)} MB compressed, over the `
        + `${(auth.maxBytes / 1048576).toFixed(0)} MB upload limit.`);
      return;
    }

    step(status, "send", body.length < 1048576 ? `${Math.max(1, Math.round(body.length / 1024))} KB` : `${(body.length / 1048576).toFixed(1)} MB`);
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

    step(status, "add");
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
    if (result.slug) rememberProfile(steamId, result.slug, result.name);
    // Runs naming a character, card or relic the site doesn't know yet: kept, added later.
    const held = result.held
      ? `${result.held} run(s) use content from a mod or a newer patch. We kept them and will add them if the site supports it.`
      : "";
    if (!result.added) {
      if (result.duplicates) {
        finishAtProfile(status, [alreadyThere(result.duplicates), held].filter(Boolean).join(" "), result.slug || slug);
      } else if (held) {
        setStatus(status, held, profileLink);
      } else {
        setStatus(status, "None of those files could be read as runs.", profileLink);
      }
      return;
    }
    stepsDone(status, runCount(result.added));
    const parts = [`Your profile now has ${result.total}.`];
    if (held) parts.push(held);
    if (result.rejected + unreadable) parts.push(`${result.rejected + unreadable} file(s) couldn't be read as runs and were skipped.`);
    finishAtProfile(status, parts.join(" "), result.slug || slug);
  }

  // ---- Entry point -----------------------------------------------------------

  // The Upload page (where a sign-in returns) and #upload links open the panel
  // straight away when signed in. Elsewhere it waits for the call to action, so
  // ordinary page views don't ask the server who is signed in.
  wireUploadLinks(onPanelPage);
  if (onPanelPage && (HERE_PATH === "/upload" || location.hash === "#upload")) {
    whoAmI().then(steamId => { if (steamId) showUploadPanel(steamId); });
  }

})();
