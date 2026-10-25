// =========================================================================
// Card and relic tooltips -- what both the dashboard and the front page show
// =========================================================================
// The lookups and markup behind a card face or a relic's tooltip, moved here
// from card-face.js and run-detail.js so the front page's site-wide stats
// can show the same popouts. Its own file, like map-bg.js, so that page can
// load it without app.js (build_site.py serves it on its own); run.py's local
// file inlines it with the rest. Everything reads the global DATA, which
// boot.js builds from /catalog.json on both pages.

function cardFaceAvailable() {
  return !!(DATA.cardFinal && Object.keys(DATA.cardFinal).length);
}

// A card's image is keyed by id and upgrade state, plus any per-instance variant.
//
// Most cards have exactly one form, but Mad Science cannot be drawn at all without
// TinkerTimeType and TinkerTimeRider: the Tinker Time event is the only thing that
// ever assigns them, so the unrolled card is type None with a ?????? description.
// tools/ExportCards.cs emits one image per combination, named by the two saved
// integers, and a variant is used only when that image exists -- so a card that
// carries state without a variant bake still falls back to its single canonical
// face rather than rendering a broken image.
function cardVariantSuffix(props) {
  if (!props) return "";
  const { TinkerTimeType: t, TinkerTimeRider: r } = props;
  if (t == null || r == null) return "";
  return `.${t}.${r}`;
}

function cardFaceKey(id, upgrade, props) {
  const upgradeSuffix = upgrade > 0 ? "_UP" : "";
  const variant = cardVariantSuffix(props);
  if (variant) {
    const key = `${id}${variant}${upgradeSuffix}`;
    if (DATA.cardFinal && DATA.cardFinal[key]) return key;
  }
  return `${id}${upgradeSuffix}`;
}

// A card face renders in three different contexts (deck tile, node-tooltip
// card, hover preview), each with its own size (the deck tile and the hover
// preview share one). Picking each one's clamp()
// independently -- as the first pass at this did -- gives each context its
// own vw-breakpoint, so resizing the window shrinks them at different rates
// and points: exactly the "inconsistent sizing" this produces. Deriving every
// clamp from the same breakpoint keeps them shrinking in lockstep (down to
// wherever a given context hits its own min and clamps flat).
// card_final/ ships each card with a transparent margin around it, because the
// game draws the energy cost orb and the frame's own bevel outside the card's
// 300x422 rect (the orb is half outside it; see tools/ExportCards.cs's Pad()).
// A width asked for here is the *card body*, so it is scaled up to the image's
// width -- otherwise every face would render ~10% smaller than before, and the
// margin would eat into the space callers laid out for the card.
//
// The numbers are local to the function on purpose: files earlier in the bundle
// call this while app.js is still executing, and reading a module-level `const`
// that early is a temporal-dead-zone ReferenceError.
function cardOuterWidth(px) {
  const BODY_W = 300;
  const MARGIN = 16;
  return Math.round(px * (BODY_W + 2 * MARGIN) / BODY_W);
}

function cardFaceWidth(minPx, maxPx) {
  const BREAKPOINT = 600;
  const vw = (cardOuterWidth(maxPx) / BREAKPOINT * 100).toFixed(3);
  return `clamp(${cardOuterWidth(minPx)}px, ${vw}vw, ${cardOuterWidth(maxPx)}px)`;
}

// ---- Download size: thumbnails and deferred tooltip art -----------------
//
// Icon-size art (22-26px) uses tools/bake_thumbs.py's small WebP copies
// instead of the full-size file, which can be 20x the bytes. Maps a full-size
// art URL onto its thumbnail; anything without one (no bake, or a folder
// that isn't thumbnailed) comes back unchanged.
function thumbSrc(src) {
  const t = DATA.thumbRoots;
  if (!src || !t || !t.dirs) return src;
  const prefix = t.art + "/";
  if (!src.startsWith(prefix)) return src;
  const rel = src.slice(prefix.length);
  if (!t.dirs.includes(rel.split("/")[0])) return src;
  return `${t.thumbs}/${rel.replace(/\.(png|webp)$/i, ".webp")}`;
}

// Hover tooltips are built into the page up front, hidden with
// visibility:hidden, and a hidden image still downloads. Tooltip art is
// written as data-src instead and only given its real src when its tooltip
// is first opened (hover, focus or tap below; showFloatingHtmlTooltip for
// the floating ones), so a page only downloads the art someone looks at.
function imgSrcAttr(src, deferred) {
  return deferred ? `data-src="${src}"` : `src="${src}"`;
}

function loadDeferredImages(root) {
  for (const img of root.querySelectorAll("img[data-src]")) {
    img.src = img.dataset.src;
    img.removeAttribute("data-src");
  }
}

// A tooltip's .card-tooltip-wrap / .relic-tooltip-wrap sits right inside
// the element that opens it, so walk up a few levels from whatever the
// pointer or focus landed on and load the art of any tooltip found there.
function loadTooltipArtNear(target) {
  for (let el = target, depth = 0; el && el.children && depth < 6; el = el.parentElement, depth++) {
    for (const child of el.children) {
      if (child.classList.contains("card-tooltip-wrap") || child.classList.contains("relic-tooltip-wrap")) {
        loadDeferredImages(child);
      }
    }
  }
}
document.addEventListener("pointerover", e => loadTooltipArtNear(e.target), { passive: true });
document.addEventListener("focusin", e => loadTooltipArtNear(e.target));

// opts.thumb: icon-size, use the thumbnail. opts.deferred: tooltip art, see
// imgSrcAttr().
function renderCardFace(id, upgrade = 0, width = 200, opts = {}) {
  let src = DATA.cardFinal && DATA.cardFinal[cardFaceKey(id, upgrade, opts.props)];
  if (!src) return "";
  if (opts.thumb) src = thumbSrc(src);
  const w = typeof width === "number" ? `${width}px` : width;
  const name = (cardInfo(id) || {}).title || fmtCardLabel(id);
  return `<img loading="lazy" class="cardface" style="width:${w}" ${imgSrcAttr(src, opts.deferred)} alt="${name}">`;
}

function fmtCardLabel(id) {
  if (!id) return id;
  if (DATA.cardLabels && DATA.cardLabels[id]) return DATA.cardLabels[id];
  return id.replace(/^CARD\./, "").replace(/_/g, " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}

function fmtRelicLabel(id) {
  if (!id) return id;
  if (DATA.relicLabels && DATA.relicLabels[id]) return DATA.relicLabels[id];
  return id.replace(/^RELIC\./, "").replace(/_/g, " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}

function cardInfo(id) {
  return (DATA.cardData && DATA.cardData[id]) || null;
}

function relicInfo(id) {
  return (DATA.relicData && DATA.relicData[id]) || null;
}

// A known item with no art (DEPRECATED_RELIC, DEPRECATED_POTION, MOCK_*
// test potions — the game ships none for them) gets the "?" event icon, so
// it still renders as an icon with its tooltip instead of a bare text label.
// Unknown ids stay null: with no tooltip to name them, the text label is better.
function artOrPlaceholder(info) {
  if (!info) return null;
  return info.imagePath || (DATA.nodeIcons && DATA.nodeIcons.event) || null;
}

function relicImgSrc(id) {
  return artOrPlaceholder(relicInfo(id));
}

// Name, rarity label and description of a relic, as HTML — shared by the hover
// tooltip and the deck's relic tiles (card-face.js).
function relicTextParts(id) {
  const info = relicInfo(id);
  if (!info) return null;
  const rarColor = { Common: "#ccc", Uncommon: "#aad4ff", Rare: "#ffd700", Boss: "#e88", Starter: "#bcbcd0" }[info.rarity] || "#bcbcd0";
  return {
    name: info.title || fmtRelicLabel(id),
    rarHtml: info.rarity ? `<div class="rt-rarity" style="color:${rarColor}">${info.rarity}</div>` : "",
    desc: substituteDescVars(info.desc || "", info.vars).replace(/\n/g, "<br>"),
  };
}

function buildRelicTooltip(id) {
  const parts = relicTextParts(id);
  if (!parts) return "";
  const { name, rarHtml, desc } = parts;
  const src  = relicImgSrc(id);
  const artHtml = src ? `<img loading="lazy" class="rt-art" ${imgSrcAttr(src, true)} alt="${name}">` : "";
  const descHtml = desc ? `<div class="rt-desc">${desc}</div>` : "";
  return `<div class="relic-tooltip">
    ${artHtml}
    <div class="rt-header">${name}${rarHtml}</div>
    ${descHtml}
  </div>`;
}

// Resolves {{Placeholder}} tokens in a card or relic description.
//
// Shared by cards, relics and potions: each ships a `vars` map read from the
// game's DynamicVars. `vars` is still optional here — glyph tokens default to
// one glyph, and a bare token with no value falls back to "?".
//
// `html: false` emits bare glyphs with no markup, for callers embedding
// the result in an attribute (e.g. data-tip) rather than element content.
// `pool`: the card's color/character (info.pool), so the inline energy glyph
// matches that card's own cost-badge color. Relics/potions aren't tied to a
// pool, so they default to colorless -- the same default DATA.energyIcons
// (run.py's build_energy_icons()) uses for any pool without its own sprite.
function substituteDescVars(desc, vars, { html = true, pool = "colorless" } = {}) {
  if (!desc) return desc;
  const v = vars || {};
  const energyIcons = DATA.energyIcons || {};
  const energyIconUrl = energyIcons[pool?.toLowerCase()] || energyIcons.colorless;
  const b = (inner, style) => html
    ? `<b${style ? ` style="${style}"` : ""}>${inner}</b>`
    : inner;
  // Token grammar, as emitted by tools/desc_tokens.py:
  //   {{Var}}                      the value
  //   {{Var:energy}} {{Var:stars}} that many glyphs
  //   {{Var:plural:one|many}}      word form chosen by the value
  //   {{Var:show:yes|no}}          branch chosen by a flag (e.g. IfUpgraded)
  //
  // plural/show can't be resolved at extract time: a card's base and upgraded
  // forms share one desc string with different vars, so "{{Combats:plural:
  // combat|combats}}" is "combat" at 1 and "combats" at 5. A branch can hold
  // tokens of its own ("{{Combats:plural:combat|{{Combats}} combats}}"), so
  // tokens are matched by depth and the chosen branch is rendered in turn.
  const tokenEnd = (text, start) => {
    for (let i = start, depth = 0; i < text.length - 1;) {
      const pair = text.substr(i, 2);
      if (pair === "{{") { depth++; i += 2; }
      else if (pair === "}}") { depth--; i += 2; if (depth === 0) return i; }
      else i++;
    }
    return -1;
  };
  // "one|many", split at the first | outside a nested token.
  const branches = arg => {
    for (let i = 0, depth = 0; i < arg.length; i++) {
      const pair = arg.substr(i, 2);
      if (pair === "{{") depth++;
      else if (pair === "}}") depth--;
      else if (arg[i] === "|" && depth === 0) return [arg.slice(0, i), arg.slice(i + 1)];
    }
    return [arg];
  };
  // The comparison in a cond: token (">1", ">=2"), or "" for a bare truthiness
  // test. Mirrors _passes_test in tools/bake_finished_cards.py.
  const passesCond = (value, test) => {
    const m = /^(>=|<=|==|!=|>|<)(-?\d+(?:\.\d+)?)$/.exec(test);
    if (!m) return !!value;
    const lhs = Number(value), rhs = Number(m[2]);
    switch (m[1]) {
      case ">=": return lhs >= rhs;
      case "<=": return lhs <= rhs;
      case "==": return lhs === rhs;
      case "!=": return lhs !== rhs;
      case ">":  return lhs > rhs;
      default:   return lhs < rhs;
    }
  };
  const token = raw => {
    // Branch text may itself contain ':', so peel off only the first two
    // segments and keep the remainder of the payload intact.
    const c1 = raw.indexOf(":");
    if (c1 < 0) {
      const val = v[raw];
      return b(val !== undefined ? String(val) : "?");
    }
    const name  = raw.slice(0, c1);
    const after = raw.slice(c1 + 1);
    const c2    = after.indexOf(":");
    const kind  = c2 < 0 ? after : after.slice(0, c2);
    const arg   = c2 < 0 ? "" : after.slice(c2 + 1);

    // The actual in-game energy orb image, colored for this pool -- not a
    // lightning bolt. See .desc-energy-icon in dashboard.css.
    if (kind === "energy") return html
      ? (energyIconUrl ? `<span class="desc-energy-icon" aria-hidden="true" style="background-image:url(${energyIconUrl})"></span>` : "⚡").repeat(v[name] ?? 1)
      : "⚡".repeat(v[name] ?? 1);
    if (kind === "stars")  return b("✦".repeat(v[name] ?? 1), "color:#5b9bd5");
    // Word forms and conditional branches are prose, not values — no <b>.
    if (kind === "plural") {
      const [one, many] = branches(arg);
      return render(v[name] === 1 ? one : (many ?? one));
    }
    if (kind === "show") {
      const [yes, no] = branches(arg);
      return render(v[name] ? yes : (no ?? ""));
    }
    if (kind === "cond") {
      // {Var:cond:>1?one|many} / {Var:cond:one|many}. The variable's value picks
      // the branch, so it survives to here like plural/show. When the variable
      // isn't known at all the branch can't be determined -- show nothing rather
      // than guess, which would put invented text on the card. Mirrors the cond
      // case in tools/bake_finished_cards.py's expand_desc.
      const q = arg.indexOf("?");
      const test = q < 0 ? "" : arg.slice(0, q);
      const [yes, no] = branches(q < 0 ? arg : arg.slice(q + 1));
      if (v[name] === undefined) return "";
      return render(passesCond(v[name], test) ? yes : (no ?? ""));
    }
    if (kind === "percentMore" || kind === "percentLess") {
      // The game's Percent{More,Less}Formatter takes a MULTIPLIER and writes the
      // delta as a whole percent: percentMore is (value - 1) * 100, percentLess is
      // (1 - value) * 100. See src/Core/Localization/Formatters/. The '%' lives in
      // the template, outside this placeholder.
      const n = Number(v[name]);
      if (!Number.isFinite(n)) return "";
      const pct = Math.round((kind === "percentMore" ? n - 1 : 1 - n) * 100);
      return b(String(pct));
    }
    const val = v[name];
    return b(val !== undefined ? String(val) : "?");
  };
  const render = text => {
    let out = "";
    for (let pos = 0;;) {
      const start = text.indexOf("{{", pos);
      const end = start < 0 ? -1 : tokenEnd(text, start);
      if (end < 0) return out + text.slice(pos);
      out += text.slice(pos, start) + token(text.slice(start + 2, end - 2));
      pos = end;
    }
  };
  return render(desc);
}

