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

Output: card_final/ (gitignored, like card_chrome/; uploaded by tools/deploy.py)
    <CARD.ID>.webp        base
    <CARD.ID>_UP.webp     upgraded (title in green, varsUpgraded/energyUpgraded applied)

Run after both tools/extract_card_data.py and tools/bake_card_chrome.py (it
needs card_data.json for text and card_chrome/ for the pre-shaded pieces):
    python tools/bake_finished_cards.py [--width 300]

Requires: pip install Pillow
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from desc_tokens import clean_desc, unwrap_choices
from pck_root import find_pck_root

HERE = Path(__file__).parent
ROOT = HERE.parent


PCK_ROOT     = find_pck_root()
CHROME_DIR   = ROOT / "card_chrome"
CARD_DATA    = ROOT / "card_data.json"
PORTRAIT_SRC = PCK_ROOT / "images" / "packed" / "card_portraits"
FONT_BOLD    = PCK_ROOT / "fonts" / "kreon_bold.ttf"
FONT_REGULAR = PCK_ROOT / "fonts" / "kreon_regular.ttf"
LOC_CARDS    = PCK_ROOT / "localization" / "eng" / "cards.json"
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

# A portrait is cropped to the Portrait rect's aspect (card_chrome/layout.json:
# 250x190 logical = 1.316). Most sources are already that shape (1000x760 and
# friends), so the crop is a no-op for them. Some are not: the Ancient set ships
# 606x852 art, which is the *frame's* aspect (300x422), about 1.85x the window's
# height. Those get an arbitrary band out of the middle and the rest is dropped,
# so where the band lands decides whether the subject survives.
#
# Rather than a per-card table, the landing point is derived from the art: slide
# the window down over the artwork's own empty top margin and no further. That
# never cuts subject and never wastes margin, per card, with nothing to update
# when a new style of oversized art turns up. See crop_portrait_to_box.
#
# Cards that need to be pinned somewhere else anyway can be listed here (0.0 is
# the top of the art, 0.5 centred, 1.0 the bottom); anything listed wins over the
# derived value. Empty by design -- prefer fixing the rule.
PORTRAIT_ANCHOR: dict[str, float] = {}

# A row counts as subject once this share of its pixels differs from that row's
# own modal colour. The arts are gradient fields with faint petals, so a row is
# judged against itself rather than one global background colour.
CONTENT_ROW_THRESHOLD = 0.08
CONTENT_SAMPLE_STEP = 3
CONTENT_CHANNEL_DELTA = 60

# card.tscn TitleLabel: font_color Color(1,0.964706,0.886275,1)
TITLE_COLOR = (255, 246, 226, 255)
TITLE_UPGRADED_COLOR = (121, 224, 122, 255)
TYPE_COLOR = (0, 0, 0, 191)  # card.tscn TypeLabel: font_color Color(0,0,0,0.752941)
DESC_COLOR = (255, 255, 255, 255)
STARS_BOLD_COLOR = (91, 155, 213, 255)  # #5b9bd5, used only for the :stars token
SHADOW_COLOR = (0, 0, 0, 200)

# StsColors.cs — the fixed colors the game's [gold]/[blue]/[purple] BBCode tags
# (RichTextGold/Blue/Purple.cs) apply to keyword spans in card descriptions.
GOLD_COLOR   = (239, 200, 81, 255)   # StsColors.gold   Color("EFC851")
BLUE_COLOR   = (135, 206, 235, 255)  # StsColors.blue   Color("87CEEB")
PURPLE_COLOR = (238, 130, 238, 255)  # StsColors.purple Color("EE82EE")

# card.tscn TitleLabel: no bold_font override (base_font is kreon_regular_shared),
# font_outline_color Color(0.301961,0.294118,0.25098,1), outline_size 12,
# font_shadow_color Color(0,0,0,0.188235), shadow_offset_x/y 2. These are all in
# the same logical (300-wide-frame) units as everything in layout.json, so they
# get scaled by the same `scale` factor as the rest of the render.
TITLE_OUTLINE_COLOR = (77, 75, 64, 255)
TITLE_OUTLINE_SIZE = 12
TITLE_SHADOW_COLOR = (0, 0, 0, 48)
TITLE_SHADOW_OFFSET = 2
TITLE_GLYPH_SPACING = 1  # FontVariation_2eadq: spacing_glyph = 1

# card.tscn EnergyLabel: kreon_bold_shared at font_size 32, outline_size 16,
# in a 46x56 box offset (-23,-26)..(23,30) from the EnergyIcon's center. NCard.cs
# colors it at runtime: StsColors.cream fill, outline = the card pool's
# EnergyOutlineColor (CardPools/*.cs; CardPoolModel's default for the rest).
COST_FONT_SIZE = 32
COST_OUTLINE_SIZE = 16
COST_BOX = (-23, -26, 23, 30)
COST_OUTLINE_DEFAULT = (0x5C, 0x54, 0x40, 255)
COST_OUTLINE_BY_POOL = {
    "ironclad":    (0x80, 0x20, 0x20, 255),
    "silent":      (0x1A, 0x66, 0x25, 255),
    "defect":      (0x1D, 0x56, 0x73, 255),
    "necrobinder": (0x80, 0x33, 0x67, 255),
    "regent":      (0x80, 0x3D, 0x0E, 255),
    "quest":       (0x43, 0x1E, 0x14, 255),
}

# Sentinel control characters standing in for [gold]/[blue]/[purple] BBCode
# while the desc string passes through the brace-substitution pipeline below
# (see clean_desc_with_color) — chosen from the C0 control range, which never
# appears in real card text, so they survive unharmed through str operations
# that would otherwise treat "[gold]"/"[/gold]" as ordinary stray brackets.
_COLOR_OPEN = {"\x01": GOLD_COLOR, "\x02": BLUE_COLOR, "\x03": PURPLE_COLOR}
_COLOR_CLOSE = "\x04"
_COLOR_TAG_TO_SENTINEL = {"gold": "\x01", "blue": "\x02", "purple": "\x03"}


# ---------------------------------------------------------------------------
# substituteDescVars() port (js/run-detail.js:764-807)
# ---------------------------------------------------------------------------
def _split_by_color(desc):
    """Splits a desc string containing the sentinel chars _COLOR_OPEN/_COLOR_CLOSE
    (injected by clean_desc_with_color, standing in for the game's [gold]/[blue]/
    [purple] BBCode) into (segment, color) pairs, color=None outside any tag.
    Tags don't nest in the source data, so this doesn't need to either.
    """
    out = []
    color = None
    buf = []

    def flush():
        if buf:
            out.append(("".join(buf), color))
            buf.clear()

    for ch in desc:
        if ch in _COLOR_OPEN:
            flush()
            color = _COLOR_OPEN[ch]
        elif ch == _COLOR_CLOSE:
            flush()
            color = None
        else:
            buf.append(ch)
    flush()
    return out


def _token_end(text, start):
    """Index just past the }} closing the {{ at `start` (tokens nest)."""
    depth = 0
    i = start
    while i < len(text) - 1:
        pair = text[i:i + 2]
        if pair == "{{":
            depth += 1
            i += 2
        elif pair == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                return i
        else:
            i += 1
    return -1


def _split_branches(arg):
    """Splits "one|many" at the first | outside a nested {{token}}."""
    depth = 0
    for i, ch in enumerate(arg):
        pair = arg[i:i + 2]
        if pair == "{{":
            depth += 1
        elif pair == "}}":
            depth -= 1
        elif ch == "|" and depth == 0:
            return arg[:i], arg[i + 1:]
    return arg, ""


ORB_CHAR = "\x05"   # one per energy pip; draw_wrapped_desc pastes an orb sprite
STAR_CHAR = "✦"


def expand_desc(desc, variables):
    """Port of substituteDescVars (js/run-detail.js): resolves every {{token}}
    to plain text, recursing into the branch a plural/show token picks. Energy
    and star tokens come out as runs of ORB_CHAR / STAR_CHAR.
    """
    out = []
    pos = 0
    while True:
        start = desc.find("{{", pos)
        end = _token_end(desc, start) if start >= 0 else -1
        if end < 0:
            out.append(desc[pos:])
            return "".join(out)
        out.append(desc[pos:start])
        pos = end
        name, _, rest = desc[start + 2:end - 2].partition(":")
        kind, _, arg = rest.partition(":")
        value = variables.get(name)
        # Matches JS's `v[name] ?? 1`: repeat count defaults to 1 when the
        # var is absent (relic placeholders lean on this), an explicit 0
        # means 0.
        count = 1 if value is None else int(value)
        if kind == "energy":
            out.append(ORB_CHAR * count)
        elif kind == "stars":
            out.append(STAR_CHAR * count)
        elif kind == "plural":
            one, many = _split_branches(arg)
            out.append(expand_desc(one if value == 1 else many, variables))
        elif kind == "show":
            yes, no = _split_branches(arg)
            out.append(expand_desc(yes if value else no, variables))
        else:
            # HighlightDifferencesFormatter (Var:diff()) only wraps this in
            # [green]/[red] BBCode when it differs from a combat baseline;
            # in the static base/upgraded views baseComparison is always 0,
            # so the game renders these numbers in the plain description
            # color, never bold/gold — confirmed via StsTextUtilities.
            # HighlightChangeText in the decompiled source, not guessed.
            out.append(str(value if value is not None else ""))


def substitute_desc_vars_runs(desc, variables):
    """`desc` as a list of (text, color, kind) runs, so the baker can draw
    mixed-style text without a browser. `kind` is None for plain text,
    "symbol" for the Segoe UI Symbol :stars glyph, or "orb" for a run of
    energy-icon placeholder chars (one per pip) that draw_wrapped_desc pastes
    as the real per-pool orb image instead of a font glyph. `desc` may contain
    the color sentinel chars from clean_desc_with_color; text inside a
    [gold]/[blue]/[purple] span gets that color, except the :stars glyphs,
    which keep their own.

    Tokens are expanded before the text is split by color: a branch can open
    or close a color span of its own (Charge's "[gold]{Cards:plural:...[/gold]|
    ...[/gold]}"), so the spans only pair up once the branch is chosen.
    """
    runs = []
    for segment, color in _split_by_color(expand_desc(desc, variables)):
        for part in re.split(f"({ORB_CHAR}+|{STAR_CHAR}+)", segment):
            if not part:
                continue
            if part[0] == ORB_CHAR:
                runs.append((part, color, "orb"))
            elif part[0] == STAR_CHAR:
                runs.append((part, STARS_BOLD_COLOR, "symbol"))
            else:
                runs.append((part, color, None))
    return runs


# Keyword color — the raw localization strings in cards.json wrap keywords
# like [gold]Vulnerable[/gold] in BBCode that clean_desc() strips out entirely
# (card_data.json's desc field has no color info left). Re-derive color-aware
# desc text straight from the same raw cards.json card_data.json was extracted
# from.
# ---------------------------------------------------------------------------
def clean_desc_with_color(text):
    """clean_desc() (tools/desc_tokens.py), but instead of discarding
    [gold]/[blue]/[purple] BBCode it first swaps each open/close tag for one
    of the sentinel control chars in _COLOR_OPEN/_COLOR_CLOSE, so they ride
    through untouched (clean_desc only ever looks at '{'/'}'/'['/']') and
    _split_by_color can recover them afterward. Any other (non-color) [tag]
    is stripped as usual.
    """
    if not text:
        return ""
    for name, sentinel in _COLOR_TAG_TO_SENTINEL.items():
        text = text.replace(f"[{name}]", sentinel).replace(f"[/{name}]", _COLOR_CLOSE)
    return clean_desc(text)


# CardKeywordOrder.cs: keywords printed below the description; every other
# keyword goes above it. card_data.json lists a card's keywords already in
# print order (tools/extract_card_data.py).
KEYWORDS_AFTER = {"Exhaust", "Eternal"}


def with_keyword_lines(desc, info, upgraded):
    """The card text as the game prints it: CardModel wraps the localized
    description in one "[gold]Keyword[/gold]." line per keyword, and a card
    like Ascender's Bane has no description at all beyond those lines.
    """
    keywords = info.get("keywordsUpgraded") if (upgraded and "keywordsUpgraded" in info) else info.get("keywords")
    if not keywords:
        return desc
    line = lambda k: f"{_COLOR_TAG_TO_SENTINEL['gold']}{k}{_COLOR_CLOSE}."
    before = [line(k) for k in keywords if k not in KEYWORDS_AFTER]
    after = [line(k) for k in keywords if k in KEYWORDS_AFTER]
    return "\n".join(before + ([desc] if desc else []) + after)


def dynamic_desc_text(raw_desc):
    """Face text for a card whose localization is entirely dropped constructs.

    Only Mad Science matches today: its string is a choose() over the rolled card
    type plus a HasRider block of eight named riders, and every token in it is one
    the grammar drops, so the card baked with no description at all.

    Composed only from the template's own branch text — nothing is worded here
    beyond the "Riders:" label. Measured against the DescriptionLabel box, which
    holds five lines: the eight rider names fit in both forms (the upgraded card
    spends one line on its Innate. keyword), while naming the type branches too
    needs a sixth line and spills onto the art, and the riders' full effect text
    needs thirteen. So the names are what fits, and the effects are not shown.
    """
    _types, named = unwrap_choices(raw_desc)
    if not named:
        return ""
    return "Riders: " + ", ".join(name for name, _ in named) + "."


def load_raw_card_descriptions():
    """{stem: raw description string} for every CARD.<stem> in cards.json's
    localization, keyed the same way card_data.json's "CARD.<stem>" ids split
    (card_id.split(".", 1)[1]) so bake_one can look one up per card_id.
    """
    if not LOC_CARDS.exists():
        print(f"WARNING: {LOC_CARDS} not found — keyword colors and the exact "
              f"in-combat description variant won't be available; falling back "
              f"to card_data.json's already-cleaned (uncolored) desc for every card.")
        return {}
    raw = json.loads(LOC_CARDS.read_text(encoding="utf-8"))
    out = {}
    for key, value in raw.items():
        stem, sep, field = key.partition(".")
        if sep and field == "description" and isinstance(value, str):
            out[stem] = value
    return out


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


def portrait_key(card_id):
    """The portrait stem a card id resolves to, after PORTRAIT_OVERRIDES."""
    stem = card_id.split(".", 1)[1].lower()
    return PORTRAIT_OVERRIDES.get(stem, stem)


def resolve_portrait(index, card_id):
    stem = portrait_key(card_id)
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


# card_banner.tres is an AtlasTexture with region 653x145 and margin
# Rect2(1, 23, 2, 25): the texture Godot sizes is 655x170, with the ribbon
# drawn 23px down from its top. card_chrome/banner_*.png is just the ribbon
# (margins dropped), so stretching it over the whole TitleBanner rect draws
# it ~14% too tall and ~10 logical px too high.
BANNER_FULL = (655, 170)
BANNER_REGION = (1, 23, 653, 145)  # x, y, w, h within BANNER_FULL


def banner_ribbon_rect(rect):
    """Where the ribbon itself lands inside the TitleBanner rect, per
    card.tscn's stretch_mode=6 (keep aspect, cover, centered)."""
    l, t, r, b = rect
    s = max((r - l) / BANNER_FULL[0], (b - t) / BANNER_FULL[1])
    ox = l + ((r - l) - BANNER_FULL[0] * s) / 2
    oy = t + ((b - t) - BANNER_FULL[1] * s) / 2
    rx, ry, rw, rh = BANNER_REGION
    return (ox + rx * s, oy + ry * s, ox + (rx + rw) * s, oy + (ry + rh) * s)


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
# Text drawing — center-aligned, word-wrapped, mixed regular/symbol runs, with
# a small dark halo standing in for the live CSS's text-shadow on the
# description/cost labels (exact blur isn't load-bearing there; the live
# version isn't pixel-audited either). The TitleLabel and TypeLabel each copy
# their own card.tscn shadow/outline properties exactly instead, since those
# were the ones a screenshot comparison flagged as visibly off.
# ---------------------------------------------------------------------------
def draw_shadowed(draw, xy, text, font, fill):
    x, y = xy
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (1, 1)):
        draw.text((x + dx, y + dy), text, font=font, fill=SHADOW_COLOR)
    draw.text((x, y), text, font=font, fill=fill)


def draw_plain_centered_line(draw, text, box, font, fill):
    """card.tscn's TypeLabel has no outline_size/shadow_color at all — just a
    flat font_color — unlike every other label on the card, so no halo.
    """
    x0, y0, x1, y1 = box
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    w, h = r - l, b - t
    x = x0 + (x1 - x0 - w) / 2 - l
    y = y0 + (y1 - y0 - h) / 2 - t
    draw.text((x, y), text, font=font, fill=fill)


def draw_title_line(draw, text, box, font, fill, scale):
    draw_outlined_line(draw, text, box, font, fill, TITLE_OUTLINE_COLOR,
                       TITLE_OUTLINE_SIZE, TITLE_GLYPH_SPACING, scale)


def draw_outlined_line(draw, text, box, font, fill, outline_color, outline_size,
                       glyph_spacing, scale):
    """A card.tscn Label with an outline + the 19% 2px drop shadow every
    outlined card label shares (TitleLabel, EnergyLabel), laid out the way
    Godot's Label does it:
      - vertical_alignment=1 centers the font's line box (ascent+descent),
        not the glyphs' ink, so capitals sit a little above box-center.
      - glyph_spacing is added after every glyph (TitleLabel's
        FontVariation_2eadq has spacing_glyph=1).
      - outline_size is a stroke *radius* of outline_size/4, measured off an
        in-game capture (~3 logical px), not outline_size/2.
    Glyphs are placed one at a time for the spacing (advancing by the
    kerned prefix length, so kerning survives), and every glyph's stroke is
    drawn before any fill so one letter's outline never covers the next.
    """
    x0, y0, x1, y1 = box
    stroke_w = max(1, round(outline_size * scale / 4))
    spacing = glyph_spacing * scale
    xs = [font.getlength(text[:i]) + i * spacing for i in range(len(text))]
    w = font.getlength(text) + len(text) * spacing
    asc, desc = font.getmetrics()
    x = x0 + (x1 - x0 - w) / 2
    baseline = y0 + (y1 - y0 - (asc + desc)) / 2 + asc
    shadow_off = round(TITLE_SHADOW_OFFSET * scale)
    passes = (
        (shadow_off, TITLE_SHADOW_COLOR, stroke_w, TITLE_SHADOW_COLOR),
        (0, outline_color, stroke_w, outline_color),
        (0, fill, 0, None),
    )
    for off, color, sw, sf in passes:
        for ch, cx in zip(text, xs):
            draw.text((x + cx + off, baseline + off), ch, font=font, fill=color,
                      anchor="ls", stroke_width=sw, stroke_fill=sf)


def wrap_runs(draw, runs, font_regular, font_symbol, max_width, orb_size):
    """Greedy word-wrap a list of (text, color, kind) runs into lines.

    A "word" here is a list of (fragment, color, kind) pieces, not
    necessarily from a single run: a value substitution glues directly onto
    following punctuation with no space in the source text (e.g. the literal
    template is "{{Energy:energy}}." with no space before the period), so a
    run boundary must NOT always become a word boundary — only an actual " "
    or "\n" in the underlying text does.
    """
    def font_for(kind):
        return font_symbol if kind == "symbol" else font_regular

    words, cur_word = [], []

    def flush_word():
        nonlocal cur_word
        if cur_word:
            words.append(cur_word)
            cur_word = []

    for text, color, kind in runs:
        for para_i, para in enumerate(text.split("\n")):
            if para_i > 0:
                flush_word()
                words.append(None)  # hard break marker
            for si, sw in enumerate(para.split(" ")):
                if si > 0:
                    flush_word()
                if sw:
                    cur_word.append((sw, color, kind))
    flush_word()

    def word_width(word):
        return sum(orb_size * len(t) if k == "orb" else draw.textlength(t, font=font_for(k))
                   for t, _, k in word)

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


def draw_wrapped_desc(draw, image, runs, box, font_regular, font_symbol, line_pitch,
                      single_line_height, orb_img, orb_size):
    """line_pitch is the y-distance from one line's top to the next one's
    (see main()). single_line_height sizes the block's first line for
    vertical centering only, never as a between-lines increment.

    `image` is the RGBA layer `draw` was created from — needed alongside
    `draw` because an "orb" run pastes `orb_img` (the real per-pool energy
    sprite) rather than drawing a font glyph, which ImageDraw can't do.
    """
    x0, y0, x1, y1 = box
    lines = wrap_runs(draw, runs, font_regular, font_symbol, x1 - x0, orb_size)
    total_h = single_line_height + line_pitch * max(0, len(lines) - 1)
    y = y0 + (y1 - y0 - total_h) / 2
    space_w = draw.textlength(" ", font=font_regular)
    asc, desc_m = font_regular.getmetrics()
    orb_y_offset = (asc + desc_m - orb_size) / 2

    for line in lines:
        line_w = sum(ww for _, ww in line) + space_w * max(0, len(line) - 1)
        x = x0 + (x1 - x0 - line_w) / 2
        for word, _ in line:
            for frag, color, kind in word:
                if kind == "orb" and orb_img is not None:
                    for i in range(len(frag)):
                        image.alpha_composite(orb_img, (round(x + i * orb_size), round(y + orb_y_offset)))
                    fw = orb_size * len(frag)
                else:
                    font = font_symbol if kind == "symbol" else font_regular
                    fill = color or DESC_COLOR
                    fw = draw.textlength(frag, font=font)
                    draw_shadowed(draw, (x, y), frag, font, fill)
                x += fw
            x += space_w
        y += line_pitch


# ---------------------------------------------------------------------------
def content_top_row(img):
    """The first row of a portrait that carries subject rather than field.

    Each row is compared against its own modal colour and the pixels departing
    from it are counted, which holds up on the gradient backgrounds and faint
    particles these arts are built from -- a single sampled background colour
    does not. Returns a row index in the source image's own coordinates.

    Only ever runs for art taller than the window, so the per-pixel cost is paid
    by the handful of oversized cards rather than every card in the bake.
    """
    rgb = img if img.mode == "RGB" else img.convert("RGB")
    px = rgb.load()
    for y in range(rgb.height):
        row = [px[x, y] for x in range(0, rgb.width, CONTENT_SAMPLE_STEP)]
        modal = Counter(row).most_common(1)[0][0]
        busy = sum(1 for c in row
                   if abs(c[0] - modal[0]) + abs(c[1] - modal[1]) + abs(c[2] - modal[2])
                   > CONTENT_CHANNEL_DELTA)
        if busy / len(row) > CONTENT_ROW_THRESHOLD:
            return y
    return 0


def auto_anchor(img, band):
    """Where the crop window should sit in art that is taller than the window.

    Places it as far down as the artwork's own empty top margin allows: no
    subject is cut, and no margin is wasted, for any style of oversized art.
    Returns a fraction of the slack, so 0.0 is the top of the art.
    """
    slack = img.height - band
    if slack <= 0:
        return 0.5
    return min(1.0, max(0.0, content_top_row(img) / slack))


def crop_portrait_to_box(portrait_path, box, anchor=None):
    """Decodes + object-fit:cover-crops a portrait once; the result is reused
    for both the base and upgraded bake of a card since both use the same box.

    When the source is taller than the box, the kept band's position comes from
    auto_anchor unless an explicit fraction is passed. Art that is wider than the
    box is cropped from the centre, which is what every card in the catalogue
    needs today (their art is already the window's shape).
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
        if anchor is None:
            anchor = auto_anchor(img.convert("RGB"), new_h)
        y0 = round((img.height - new_h) * anchor)
        img = img.crop((0, y0, img.width, y0 + new_h))
    return img


def bake_one(card_id, upgraded, info, chrome, portrait, layout, bounds, scale,
             fonts, canvas_size, raw_descs, line_pitch, single_line_height):
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
    paste_layer(canvas, chrome(f"banner_{mat}"), rect_px(banner_ribbon_rect(rects["TitleBanner"]), bounds, scale))
    paste_layer(canvas, chrome(f"plaque_{mat}"), rect_px(rects["TypePlaque"], bounds, scale))

    # Same sprite for the cost badge (pasted below, if this card has one) and
    # any inline {{Energy:energy}} pips in its description (drawn further
    # down) — a card's pool determines both, so this is resolved once.
    orb_name = f"energy_{pool}" if chrome(f"energy_{pool}") is not None else "energy_colorless"

    energy = info.get("energyUpgraded") if (upgraded and info.get("energyUpgraded") is not None) else info.get("energy", -1)
    has_cost = bool(info.get("costsX")) or (energy is not None and energy >= 0)
    if has_cost:
        paste_layer(canvas, chrome(orb_name), rect_px(rects["EnergyIcon"], bounds, scale))

    # Text goes on its own layer, composited at the end: ImageDraw writes
    # RGBA values straight into the image rather than blending, so drawing a
    # translucent color (the title's 19% shadow, TypeLabel's 75% black) on
    # the canvas itself punches see-through holes in the chrome under it.
    text_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(text_layer)
    title_font, type_font, cost_font, desc_font, desc_symbol_font = fonts

    name = info.get("title") or card_id
    if upgraded:
        name += "+"
    draw_title_line(draw, name, rect_px(rects["TitleLabel"], bounds, scale),
                     title_font, TITLE_UPGRADED_COLOR if upgraded else TITLE_COLOR, scale)

    if info.get("type"):
        draw_plain_centered_line(draw, info["type"], rect_px(rects["TypePlaque"], bounds, scale),
                                  type_font, TYPE_COLOR)

    if has_cost:
        cost_text = "X" if info.get("costsX") else str(energy)
        l, t, r, b = rects["EnergyIcon"]
        cx, cy = (l + r) / 2, (t + b) / 2
        cost_box = (cx + COST_BOX[0], cy + COST_BOX[1], cx + COST_BOX[2], cy + COST_BOX[3])
        draw_outlined_line(draw, cost_text, rect_px(cost_box, bounds, scale), cost_font,
                           TITLE_COLOR, COST_OUTLINE_BY_POOL.get(pool, COST_OUTLINE_DEFAULT),
                           COST_OUTLINE_SIZE, 0, scale)

    base_vars = info.get("varsUpgraded") if (upgraded and info.get("varsUpgraded")) else info.get("vars")
    variables = {**(base_vars or {}), "IfUpgraded": 1 if upgraded else 0}
    # Prefer a freshly-recolored desc straight from the raw locale (keeps
    # [gold]/[blue]/[purple] keyword spans, which card_data.json's own desc
    # field has stripped) — fall back to that already-cleaned, colorless desc
    # for any card_id with no raw-locale match (e.g. a data quirk), so nothing
    # silently loses its description text.
    stem = card_id.split(".", 1)[1]
    raw_desc = raw_descs.get(stem)
    desc = clean_desc_with_color(raw_desc) if raw_desc else info.get("desc")
    # Some cards have text that the grammar can't express at all (see
    # dynamic_desc_text): the raw string is there but converts to nothing, so
    # recover its branches rather than baking a card with no description.
    if not (desc or "").strip() and raw_desc:
        desc = dynamic_desc_text(raw_desc)
    desc = with_keyword_lines(desc, info, upgraded)
    if desc:
        runs = substitute_desc_vars_runs(desc, variables)
        orb_size = round(desc_font.size * 0.9)  # matches dashboard.css's .desc-energy-icon (0.9em)
        orb_sprite = chrome(orb_name)
        orb_img = orb_sprite.resize((orb_size, orb_size), Image.LANCZOS) if orb_sprite is not None else None
        draw_wrapped_desc(draw, text_layer, runs, rect_px(rects["DescriptionLabel"], bounds, scale),
                           desc_font, desc_symbol_font, line_pitch, single_line_height,
                           orb_img, orb_size)

    canvas.alpha_composite(text_layer)
    return canvas


def main():
    ap = argparse.ArgumentParser()
    # --width is the FRAME width; the canvas is the bounds of every rect, so it
    # comes out wider than the frame (300 -> 330x438, 236 -> 260x345).
    #
    # A card face is drawn at 210px at most -- the hover tooltip and the deck
    # tiles (node tiles are 128px). At 1x that made 236 plenty (1.24x the
    # largest use), which is why it was cut from 400 on 2026-10-01 to halve the
    # bytes. On a 2x display though the browser needs 420 device px for that
    # 210px draw, so the 260px canvas was upscaled 1.6x and card text looked
    # soft. 300 gives a 330px canvas: native at 2x up to 165 CSS px, covering
    # the deck tiles outright and most tooltip widths, for ~30 KB a face and
    # ~32 MB in card_final/ (against ~22 KB / ~23 MB at 236, ~39 KB / ~46 MB at
    # 400). 381 is the exact "native at 2x everywhere" value if that is ever
    # worth the bytes. A single Run Detail session pulls hundreds of these, so
    # it is the site's heaviest download either way.
    ap.add_argument("--width", type=int, default=300,
                    help="frame width in px, same convention as bake_card_chrome.py "
                         "(default 300 -> ~330x438 canvas including chrome overhang)")
    ap.add_argument("--only", nargs="+", metavar="CARD_ID",
                    help="re-bake just these cards (e.g. CARD.HEADBUTT), leaving the rest of "
                         "card_final/ untouched — for quick layout iteration")
    args = ap.parse_args()

    for path, what in ((CHROME_DIR, "card_chrome/ (run tools/bake_card_chrome.py first)"),
                       (CARD_DATA, "card_data.json (run tools/extract_card_data.py first)"),
                       (PORTRAIT_SRC, f"the full PCK extraction — set STS2_PCK_ROOT or check out "
                                      f"sts2-history-dashboard next to this repo")):
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
    desc_font = ImageFont.truetype(str(FONT_REGULAR), desc_size)
    fonts = (
        # card.tscn's TitleLabel base_font is kreon_regular_shared, not bold —
        # its outline (drawn by draw_title_line) is what gives the title its
        # visual weight in-game, not a bold glyph.
        ImageFont.truetype(str(FONT_REGULAR), round(layout["fontSizes"]["title"] * font_scale)),
        ImageFont.truetype(str(FONT_BOLD), round(layout["fontSizes"]["type"] * font_scale)),
        ImageFont.truetype(str(FONT_BOLD), round(COST_FONT_SIZE * font_scale)),
        desc_font,
        symbol_font,
    )

    # card.tscn's DescriptionLabel: line_separation = -3 (a gap between
    # lines, in logical units) on top of the font's ascent+descent.
    # single_line_height sizes a lone line for centering; it matches in-game
    # one-line cards like Strike to ~1px.
    asc, desc_m = desc_font.getmetrics()
    line_separation = -3 * font_scale
    line_pitch = (asc + desc_m) + line_separation
    single_line_height = (asc + desc_m) * 1.12

    cards = json.loads(CARD_DATA.read_text(encoding="utf-8"))
    raw_descs = load_raw_card_descriptions()
    portrait_index = index_portraits()
    chrome = load_chrome()
    portrait_box = rect_px(layout["rects"]["Portrait"], bounds, scale)

    OUT.mkdir(exist_ok=True)
    if args.only:
        cards = {cid: cards[cid] for cid in args.only}
    else:
        for old in OUT.glob("*.webp"):
            old.unlink()

    manifest = []
    for card_id, info in sorted(cards.items()):
        # Base and upgraded share the same portrait — decode+crop it once.
        portrait_path = resolve_portrait(portrait_index, card_id)
        if portrait_path:
            # None when unlisted, which lets crop_portrait_to_box derive the
            # landing point from the art itself (see PORTRAIT_ANCHOR).
            anchor = PORTRAIT_ANCHOR.get(portrait_key(card_id))
            portrait = crop_portrait_to_box(portrait_path, portrait_box, anchor)
        else:
            portrait = None
        for upgraded, suffix in ((False, ""), (True, "_UP")):
            img = bake_one(card_id, upgraded, info, chrome, portrait, layout,
                           bounds, scale, fonts, canvas_size,
                           raw_descs, line_pitch, single_line_height)
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
