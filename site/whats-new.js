// What's new (site/pages/whats-new.html, its posts from site/whats-new/).
//
// On every page: the site bar's dot by What's new, shown until this browser has opened the page
// since the newest post (build_site.py puts that post's date and id on the dot).
//
// On the page itself (boot.js calls placeWhatsNew once the posts are in): each post's reactions,
// and for a post that closes feedback notes, how many players asked for it, with "You asked for
// this" for those who did. Both come from /auth/reactions (infra/lambda/ingest/reactions.py).
// Anyone can see the counts; reacting signs in through Steam first and comes back to the post.
(function () {
  "use strict";
  // reactions.KINDS, in the same order. The art is the game's, already on the site.
  const KINDS = [
    { kind: "flame", label: "Rest Site", src: "/node_icons/rest_site.png" },
    { kind: "elite", label: "Elite", src: "/node_icons/elite.png" },
    { kind: "skull", label: "Red Skull", src: "/thumbs/relic_images/red_skull.webp" },
    { kind: "eye", label: "Glass Eye", src: "/thumbs/relic_images/glass_eye.webp" },
    { kind: "huh", label: "Unknown", src: "/node_icons/event.png" },
    { kind: "flower", label: "Happy Flower", src: "/thumbs/relic_images/happy_flower.webp" },
  ];
  const SEEN_KEY = "smst-whats-new-seen";

  function seen(value) {
    try {
      if (value === undefined) return localStorage.getItem(SEEN_KEY);
      localStorage.setItem(SEEN_KEY, value);
    } catch (e) { /* storage off: the dot just keeps showing */ }
    return null;
  }

  const dot = document.querySelector(".new-dot[data-latest]");
  const latest = dot ? dot.dataset.latest : "";
  if (dot && !/^\/whats-new(\/|$)/.test(location.pathname) && seen() !== latest) dot.hidden = false;

  let signedIn = false;
  const posts = {};  // post id -> {bar, counts: {kind: n}, mine: Set, busy: Set}

  function el(tag, props, children) {
    const node = Object.assign(document.createElement(tag), props || {});
    (children || []).forEach(c => node.append(c));
    return node;
  }

  function plural(n, word) { return `${n} ${word}${n === 1 ? "" : "s"}`; }

  function render(id) {
    const post = posts[id];
    post.bar.querySelectorAll("button.react").forEach(button => {
      const { kind, label } = KINDS.find(k => k.kind === button.dataset.kind);
      const n = post.counts[kind] || 0;
      const on = post.mine.has(kind);
      button.setAttribute("aria-pressed", String(on));
      button.querySelector(".react-count").textContent = n ? String(n) : "";
      button.title = `${label}${n ? ` · ${plural(n, "reaction")}` : ""}${signedIn ? "" : " · sign in to react"}`;
      button.setAttribute("aria-label", `${label}, ${plural(n, "reaction")}${on ? ", including yours" : ""}`);
    });
  }

  function say(id, message) {
    const status = posts[id].bar.querySelector(".react-status");
    status.textContent = message;
    clearTimeout(status.timer);
    if (message) status.timer = setTimeout(() => { status.textContent = ""; }, 6000);
  }

  function buildBar(article) {
    const id = article.dataset.post;
    const bar = article.querySelector(".post-reactions") || article.appendChild(el("div", { className: "post-reactions" }));
    bar.setAttribute("role", "group");
    bar.setAttribute("aria-label", "Reactions");
    bar.hidden = true;  // until the counts load; left hidden if they can't
    bar.replaceChildren(...KINDS.map(({ kind, label, src }) => el("button", {
      type: "button", className: "react",
    }, [
      el("img", { src, alt: "", width: 22, height: 22, loading: "lazy", decoding: "async" }),
      el("span", { className: "react-count" }),
    ])), el("span", { className: "react-status", role: "status" }));
    bar.querySelectorAll("button.react").forEach((button, i) => {
      button.dataset.kind = KINDS[i].kind;
      button.addEventListener("click", () => toggle(id, KINDS[i].kind));
    });
    posts[id] = { bar, counts: {}, mine: new Set(), busy: new Set() };
  }

  function take(data) {
    signedIn = !!data.signedIn;
    Object.entries(data.posts || {}).forEach(([id, view]) => {
      const post = posts[id];
      if (!post) return;
      post.counts = view.counts || {};
      post.mine = new Set(view.mine || []);
      post.bar.hidden = false;
      render(id);
      if (view.asked) showAsked(post.bar.closest("article"), view.asked);
    });
  }

  function showAsked(article, asked) {
    article.querySelector(".post-asked")?.remove();
    if (!asked.count) return;
    const others = asked.count - 1;
    const text = asked.mine
      ? "You asked for this" + (others ? `, with ${plural(others, "other player")}` : "")
      : `Requested by ${plural(asked.count, "player")} through Feedback`;
    const line = el("p", { className: "post-asked" + (asked.mine ? " post-asked-mine" : ""), textContent: text });
    article.querySelector(".post-head").after(line);
  }

  async function call(options, query) {
    const response = await fetch("/auth/reactions" + (query ? "?" + query : ""), options);
    let data = {};
    try { data = await response.json(); } catch (e) { /* not JSON: a 404 from a local server */ }
    if (!response.ok) throw Object.assign(new Error(data.message || "Reactions are unavailable right now."), { status: response.status });
    return data;
  }

  async function toggle(id, kind) {
    const post = posts[id];
    if (!signedIn) {
      location.assign("/auth/login?next=" + encodeURIComponent(`/whats-new/${id}`));
      return;
    }
    if (post.busy.has(kind)) return;
    post.busy.add(kind);
    const on = !post.mine.has(kind);
    const before = { counts: { ...post.counts }, mine: new Set(post.mine) };
    // Show it at once; the answer brings the real counts.
    post.counts[kind] = Math.max(0, (post.counts[kind] || 0) + (on ? 1 : -1));
    if (on) post.mine.add(kind); else post.mine.delete(kind);
    render(id);
    try {
      take(await call({ method: "POST", headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ post: id, kind, on }) }));
    } catch (e) {
      post.counts = before.counts;
      post.mine = before.mine;
      if (e.status === 401) signedIn = false;
      render(id);
      say(id, e.status === 401 ? "Sign in again to react." : e.message);
    } finally {
      post.busy.delete(kind);
    }
  }

  window.placeWhatsNew = function (section, postId) {
    if (latest) {
      seen(latest);
      if (dot) dot.hidden = true;
    }
    const articles = [...section.querySelectorAll("article.post[data-post]")];
    articles.forEach(buildBar);
    if (postId) {
      const target = articles.find(a => a.dataset.post === postId);
      if (target) {
        target.classList.add("post-focus");
        const title = target.querySelector(".post-head h2")?.textContent.trim();
        if (title) document.title = `${title} — What's new — Slay My Stats`;
        target.scrollIntoView({ block: "start" });
      } else {
        section.querySelector("h1")?.after(el("p", { className: "posts-missing",
          textContent: "That post isn't here any more. Here's everything else." }));
      }
    }
    if (!articles.length) return;
    const params = new URLSearchParams({ posts: articles.map(a => a.dataset.post).join(",") });
    const fixes = articles.filter(a => a.dataset.fixes)
      .map(a => `${a.dataset.post}:${a.dataset.fixes.split(",").join(".")}`);
    if (fixes.length) params.set("fixes", fixes.join(","));
    call({ credentials: "same-origin" }, params.toString()).then(take).catch(() => { /* bars stay hidden */ });
  };
})();
