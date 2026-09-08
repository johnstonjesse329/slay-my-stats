"""
Bakes a fully finished card image — art AND text — for every card, in both its
base and upgraded form, out of card_chrome/ + card_data.json + the full-res
portraits.

Why this exists
----------------
js/card-face.js used to composite a card at render time out of six chrome
<img> layers plus four live text overlays sized in cqw units. That's the
right shape for a single desktop user's machine, but wrong for a public,
multi-user site: every viewer re-does the same deterministic layout work, and
CloudFront ends up serving a pile of small chrome/portrait pieces instead of
one cacheable finished image. A card's full appearance — every layer AND
every piece of text, including substituted stat values — is 100% determined
by (card_id, upgrade_state) via card_data.json, never by any user's run data,
so it can be baked once, offline, exactly like card_chrome/ already is.

Card upgrade levels beyond 1 don't need their own variant: card_data.json has
no per-level scaling data, and the live JS doesn't compute one either —
varsUpgraded is a single fixed value applied whenever upgrade > 0. So exactly
two baked variants per card (base, upgraded) matches current behavior.

Output: card_final/ (committed to the repo, like card_chrome/)
    <CARD.ID>.webp        base
    <CARD.ID>_UP.webp     upgraded (title in green, varsUpgraded/energyUpgraded applied)

Run after both tools/extract_card_data.py and tools/bake_card_chrome.py (it
needs card_data.json for text and card_chrome/ for the pre-shaded pieces):
    python tools/bake_finished_cards.py [--width 400]

Requires: pip install Pillow
"""
import argparse
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
ROOT = HERE.parent

CHROME_DIR   = ROOT / "card_chrome"
CARD_DATA    = ROOT / "card_data.json"
PORTRAIT_SRC = ROOT / "pck_recover_full" / "images" / "packed" / "card_portraits"
FONT_BOLD    = ROOT / "pck_recover_full" / "fonts" / "kreon_bold.ttf"
FONT_REGULAR = ROOT / "pck_recover_full" / "fonts" / "kreon_regular.ttf"
OUT          = ROOT / "card_final"

# Kreon has no glyphs for the ⚡/✦ tokens the game's own description text uses
# (:energy / :stars runs below) — Pillow has no font-fallback chain like a
# browser does, so without this every one renders as a tofu box. Segoe UI
# Symbol (a plain outline font, unlike the COLR emoji font) covers both. This
# tool only ever runs on the dev's own Windows box, same as the rest of the
# asset pipeline, so a hardcoded system path is fine.
SYMBOL_FONT = Path("C:/Windows/Fonts/seguisym.ttf")

# Mirrors _PORTRAIT_OVERRIDES in run.py / cardImgSrc() in run-detail.js —
# a few cards' art is filed under a different stem than the card id implies.
PORTRAIT_OVERRIDES = {
    "stack": "smokestack",
    "mad_science": "mad_science_attack",
}

TITLE_COLOR = (255, 255, 255, 255)
TITLE_UPGRADED_COLOR = (121, 224, 122, 255)
TYPE_COLOR = (0, 0, 0, 191)  # rgba(0,0,0,0.75)
DESC_COLOR = (255, 255, 255, 255)
DESC_BOLD_COLOR = (255, 214, 102, 255)  # #ffd666
STARS_BOLD_COLOR = (91, 155, 213, 255)  # #5b9bd5, used only for the :stars token
SHADOW_COLOR = (0, 0, 0, 200)


# ---------------------------------------------------------------------------
# substituteDescVars() port (js/run-detail.js:764-807)
# ---------------------------------------------------------------------------
def substitute_desc_vars_runs(desc, variables):
    """Port of substituteDescVars(desc, vars, {html:true}) that returns a list
    of (text, bold, color, symbol) runs instead of an HTML string, so the
    baker can draw mixed-style text without a browser.
    """
    runs = []

    def emit(text, bold=False, color=None, symbol=False):
        if text:
            runs.append((text, bold, color, symbol))

    pos = 0
    pattern = re.compile(r"\{\{(\w+)(?::(\w+)(?::([^}]*))?)?\}\}")
    for m in pattern.finditer(desc):
        emit(desc[pos:m.start()])
        pos = m.end()
        name, kind, arg = m.group(1), m.group(2), m.group(3)
        value = variables.get(name)
        # Matches JS's `v[name] ?? 1`: repeat count defaults to 1 when the var
        # is absent (relic placeholders lean on this), but an explicit 0 means 0.
        count = 1 if value is None else int(value)
        if kind == "energy":
            emit("⚡" * count, symbol=True)
        elif kind == "stars":
            emit("✦" * count, color=STARS_BOLD_COLOR, symbol=True)
        elif kind == "plural":
            one, many = (arg.split("|", 1) + [""])[:2]
            emit(one if value == 1 else many)
        elif kind == "show":
            yes, no = (arg.split("|", 1) + [""])[:2]
            emit(yes if value else no)
        else:
            emit(str(value if value is not None else ""), bold=True)
    emit(desc[pos:])
    return runs


# ---------------------------------------------------------------------------
# Portrait lookup — mirrors build_card_images() in run.py, but against the
# full-res extraction rather than the pre-downscaled 144px card_portraits/,
# so a single downscale (straight to bake resolution) is the only one that
# ever happens.
# ---------------------------------------------------------------------------
def index_portraits():
    index = {}
    for p in sorted(PORTRAIT_SRC.rglob("*.png")):
        index.setdefault(p.stem, []).append(p)
    return index


def resolve_portrait(index, card_id):
    stem = card_id.split(".", 1)[1].lower()
    stem = PORTRAIT_OVERRIDES.get(stem, stem)
    candidates = index.get(stem, [])
    if not candidates:
        return None
    non_beta = [c for c in candidates if "beta" not in c.parts]
    return non_beta[0] if non_beta else candidates[0]


# ---------------------------------------------------------------------------
def load_chrome():
    """Loads chrome pieces on demand, keyed the same way card-face.js indexes
    them; paste_layer() below resizes each to its target rect regardless of
    whatever width tools/bake_card_chrome.py produced them at.
    """
    cache = {}

    def get(name):
        if name in cache:
            return cache[name]
        path = CHROME_DIR / f"{name}.png"
        img = Image.open(path).convert("RGBA") if path.exists() else None
        cache[name] = img
        return img
    return get


def rect_px(rect, bounds, scale):
    l, t, r, b = rect
    x0, y0 = bounds
    return (round((l - x0) * scale), round((t - y0) * scale),
            round((r - x0) * scale), round((b - y0) * scale))


def paste_layer(canvas, img, box):
    if img is None:
        return
    w, h = box[2] - box[0], box[3] - box[1]
    if w <= 0 or h <= 0:
        return
    if img.size != (w, h):
        img = img.resize((w, h), Image.LANCZOS)
    canvas.alpha_composite(img, (box[0], box[1]))


# ---------------------------------------------------------------------------
# Text drawing — center-aligned, word-wrapped, mixed regular/bold runs, with a
# small dark halo standing in for the live CSS's text-shadow (exact blur isn't
# load-bearing here; the live version isn't pixel-audited either).
# ---------------------------------------------------------------------------
def draw_shadowed(draw, xy, text, font, fill):
    x, y = xy
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (1, 1)):
        draw.text((x + dx, y + dy), text, font=font, fill=SHADOW_COLOR)
    draw.text((x, y), text, font=font, fill=fill)


def draw_centered_line(draw, text, box, font, fill):
    x0, y0, x1, y1 = box
    w = draw.textlength(text, font=font)
    asc, desc = font.getmetrics()
    x = x0 + (x1 - x0 - w) / 2
    y = y0 + (y1 - y0 - (asc + desc)) / 2
    draw_shadowed(draw, (x, y), text, font, fill)


def wrap_runs(draw, runs, font_regular, font_bold, font_symbol, max_width):
    """Greedy word-wrap a list of (text, bold, color, symbol) runs into lines.

    A "word" here is a list of (fragment, bold, color, symbol) pieces, not
    necessarily from a single run: a value substitution glues directly onto
    following punctuation with no space in the source text (e.g. the literal
    template is "{{Energy:energy}}." with no space before the period), so a
    run boundary must NOT always become a word boundary — only an actual " "
    or "\n" in the underlying text does.
    """
    def font_for(bold, symbol):
        return font_symbol if symbol else (font_bold if bold else font_regular)

    words, cur_word = [], []

    def flush_word():
        nonlocal cur_word
        if cur_word:
            words.append(cur_word)
            cur_word = []

    for text, bold, color, symbol in runs:
        for para_i, para in enumerate(text.split("\n")):
            if para_i > 0:
                flush_word()
                words.append(None)  # hard break marker
            for si, sw in enumerate(para.split(" ")):
                if si > 0:
                    flush_word()
                if sw:
                    cur_word.append((sw, bold, color, symbol))
    flush_word()

    def word_width(word):
        return sum(draw.textlength(t, font=font_for(b, s)) for t, b, _, s in word)

    space_w = draw.textlength(" ", font=font_regular)
    lines, cur, cur_w = [], [], 0.0
    for w in words:
        if w is None:
            lines.append(cur)
            cur, cur_w = [], 0.0
            continue
        ww = word_width(w)
        extra = (space_w if cur else 0) + ww
        if cur and cur_w + extra > max_width:
            lines.append(cur)
            cur, cur_w = [], 0.0
            extra = ww
        cur.append((w, ww))
        cur_w += extra
    lines.append(cur)
    return lines


def draw_wrapped_desc(draw, runs, box, font_regular, font_bold, font_symbol, line_height=1.12):
    x0, y0, x1, y1 = box
    lines = wrap_runs(draw, runs, font_regular, font_bold, font_symbol, x1 - x0)
    asc, desc_m = font_regular.getmetrics()
    line_h = (asc + desc_m) * line_height
    total_h = line_h * len(lines)
    y = y0 + (y1 - y0 - total_h) / 2
    space_w = draw.textlength(" ", font=font_regular)

    for line in lines:
        line_w = sum(ww for _, ww in line) + space_w * max(0, len(line) - 1)
        x = x0 + (x1 - x0 - line_w) / 2
        for word, _ in line:
            for frag, bold, color, symbol in word:
                font = font_symbol if symbol else (font_bold if bold else font_regular)
                fill = color or (DESC_BOLD_COLOR if bold else DESC_COLOR)
                fw = draw.textlength(frag, font=font)
                draw_shadowed(draw, (x, y), frag, font, fill)
                x += fw
            x += space_w
        y += line_h


# ---------------------------------------------------------------------------
def crop_portrait_to_box(portrait_path, box):
    """Decodes + object-fit:cover-crops a portrait once; the result is reused
    for both the base and upgraded bake of a card since both use the same box.
    """
    w, h = box[2] - box[0], box[3] - box[1]
    img = Image.open(portrait_path).convert("RGBA")
    src_ratio, dst_ratio = img.width / img.height, w / h
    if src_ratio > dst_ratio:
        new_w = round(img.height * dst_ratio)
        x0 = (img.width - new_w) // 2
        img = img.crop((x0, 0, x0 + new_w, img.height))
    else:
        new_h = round(img.width / dst_ratio)
        y0 = (img.height - new_h) // 2
        img = img.crop((0, y0, img.width, y0 + new_h))
    return img


def bake_one(card_id, upgraded, info, chrome, portrait, layout, bounds, scale,
             fonts, canvas_size):
    pool = str(info.get("pool", "colorless")).lower()
    ctype = str(info.get("type", "")).lower()
    rarity = str(info.get("rarity", "")).lower()

    color = layout["poolToColor"].get(pool, "colorless")
    sprite = layout["typeToSprite"].get(ctype, layout["defaultTypeSprite"])
    mat = layout["rarityToMaterial"].get(rarity, layout["defaultMaterial"])
    rects = layout["rects"]

    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))

    if portrait is not None:
        paste_layer(canvas, portrait, rect_px(rects["Portrait"], bounds, scale))

    paste_layer(canvas, chrome(f"frame_{sprite}_{color}"), rect_px(rects["Frame"], bounds, scale))
    paste_layer(canvas, chrome(f"portrait_border_{sprite}_{mat}"), rect_px(rects["PortraitBorder"], bounds, scale))
    paste_layer(canvas, chrome(f"banner_{mat}"), rect_px(rects["TitleBanner"], bounds, scale))
    paste_layer(canvas, chrome(f"plaque_{mat}"), rect_px(rects["TypePlaque"], bounds, scale))

    energy = info.get("energyUpgraded") if (upgraded and info.get("energyUpgraded") is not None) else info.get("energy", -1)
    has_cost = bool(info.get("costsX")) or (energy is not None and energy >= 0)
    if has_cost:
        orb_name = f"energy_{pool}" if chrome(f"energy_{pool}") is not None else "energy_colorless"
        paste_layer(canvas, chrome(orb_name), rect_px(rects["EnergyIcon"], bounds, scale))

    draw = ImageDraw.Draw(canvas)
    title_font, type_font, cost_font, desc_font, desc_bold_font, desc_symbol_font = fonts

    name = info.get("title") or card_id
    if upgraded:
        name += "+"
    draw_centered_line(draw, name, rect_px(rects["TitleLabel"], bounds, scale),
                        title_font, TITLE_UPGRADED_COLOR if upgraded else TITLE_COLOR)

    if info.get("type"):
        draw_centered_line(draw, info["type"], rect_px(rects["TypePlaque"], bounds, scale),
                            type_font, TYPE_COLOR)

    if has_cost:
        cost_text = "X" if info.get("costsX") else str(energy)
        draw_centered_line(draw, cost_text, rect_px(rects["EnergyIcon"], bounds, scale),
                            cost_font, TITLE_COLOR)

    base_vars = info.get("varsUpgraded") if (upgraded and info.get("varsUpgraded")) else info.get("vars")
    variables = {**(base_vars or {}), "IfUpgraded": 1 if upgraded else 0}
    if info.get("desc"):
        runs = substitute_desc_vars_runs(info["desc"], variables)
        draw_wrapped_desc(draw, runs, rect_px(rects["DescriptionLabel"], bounds, scale),
                           desc_font, desc_bold_font, desc_symbol_font)

    return canvas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=int, default=400,
                    help="frame width in px, same convention as bake_card_chrome.py "
                         "(default 400 -> ~440x533 canvas including chrome overhang)")
    args = ap.parse_args()

    for path, what in ((CHROME_DIR, "card_chrome/ (run tools/bake_card_chrome.py first)"),
                       (CARD_DATA, "card_data.json (run tools/extract_card_data.py first)"),
                       (PORTRAIT_SRC, "the full PCK extraction (see CLAUDE.md)")):
        if not path.exists():
            raise SystemExit(f"Source not found: {path}\nNeed: {what}")

    layout = json.loads((CHROME_DIR / "layout.json").read_text(encoding="utf-8"))
    rects = layout["rects"]
    x0 = min(r[0] for r in rects.values())
    y0 = min(r[1] for r in rects.values())
    x1 = max(r[2] for r in rects.values())
    y1 = max(r[3] for r in rects.values())
    bounds = (x0, y0)
    logical_w, logical_h = x1 - x0, y1 - y0

    scale = args.width / 300  # 300 = the frame's own logical width (layout.json's frameWidth)
    canvas_size = (round(logical_w * scale), round(logical_h * scale))

    font_scale = scale
    desc_size = round(layout["fontSizes"]["description"] * font_scale)
    if SYMBOL_FONT.exists():
        symbol_font = ImageFont.truetype(str(SYMBOL_FONT), desc_size)
    else:
        print(f"WARNING: {SYMBOL_FONT} not found — ⚡/✦ tokens will render as tofu boxes")
        symbol_font = ImageFont.truetype(str(FONT_BOLD), desc_size)
    fonts = (
        ImageFont.truetype(str(FONT_BOLD), round(layout["fontSizes"]["title"] * font_scale)),
        ImageFont.truetype(str(FONT_BOLD), round(layout["fontSizes"]["type"] * font_scale)),
        ImageFont.truetype(str(FONT_BOLD), round(layout["fontSizes"]["cost"] * font_scale)),
        ImageFont.truetype(str(FONT_REGULAR), desc_size),
        ImageFont.truetype(str(FONT_BOLD), desc_size),
        symbol_font,
    )

    cards = json.loads(CARD_DATA.read_text(encoding="utf-8"))
    portrait_index = index_portraits()
    chrome = load_chrome()
    portrait_box = rect_px(layout["rects"]["Portrait"], bounds, scale)

    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*.webp"):
        old.unlink()

    manifest = []
    for card_id, info in sorted(cards.items()):
        # Base and upgraded share the same portrait — decode+crop it once.
        portrait_path = resolve_portrait(portrait_index, card_id)
        portrait = crop_portrait_to_box(portrait_path, portrait_box) if portrait_path else None
        for upgraded, suffix in ((False, ""), (True, "_UP")):
            img = bake_one(card_id, upgraded, info, chrome, portrait, layout,
                           bounds, scale, fonts, canvas_size)
            path = OUT / f"{card_id}{suffix}.webp"
            # method=6 (max compression effort) measured ~50x slower than
            # method=4 for only ~5% smaller files here — a few cents/month of
            # S3 storage isn't worth turning a ~1min bake into over an hour.
            img.save(path, "WEBP", quality=85, method=4)
            manifest.append((path.name, path.stat().st_size))

    total = sum(sz for _, sz in manifest)
    print(f"Baked {len(manifest)} images ({len(cards)} cards x 2) -> {OUT}")
    print(f"Total: {total/1024/1024:.2f} MB  (canvas {canvas_size[0]}x{canvas_size[1]}px)")


if __name__ == "__main__":
    main()
