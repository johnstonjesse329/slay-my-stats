"""
Bakes the card "chrome" (frames, portrait borders, title banners, energy orbs)
out of the game's UI atlas into flat PNGs the dashboard can use directly.

Why this exists
---------------
There is no finished card-frame image anywhere in the extraction. In-game a
frame is an *atlas region* (`images/atlases/ui_atlas.sprites/card/*.tres`,
each a Rect2 into `ui_atlas_0.png`) that is recolored at draw time by
`shaders/hsv.gdshader` — a hue/saturation/value shift performed in YIQ space
— with per-variant parameters supplied by a material:

  * frames          -> materials/cards/frames/card_frame_<color>_mat.tres
                       (chosen by the card's character/pool)
  * banners+borders -> materials/cards/banners/card_banner_<rarity>_mat.tres
                       (chosen by the card's rarity)

Slicing the atlas without applying the material gives one neutral frame that
matches no character, which is why a naive extraction never looked right.
This script reproduces that shader exactly on the CPU and bakes the result,
so the dashboard needs no runtime shader — just <img>s.

Output: card_chrome/ (committed to the repo)
    frame_<type>_<color>.png          e.g. frame_attack_red.png
    portrait_border_<type>_<rarity>.png
    banner_<rarity>.png
    energy_<pool>.png
    layout.json                       logical rects from scenes/cards/card.tscn

Run after a full PCK extraction (see CLAUDE.md):
    python tools/bake_card_chrome.py [--width 300]

Requires: pip install Pillow numpy
"""
import argparse
import json
import re
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).parent
ROOT = HERE.parent
PCK  = ROOT / "pck_recover_full"

SPRITE_DIR   = PCK / "images/atlases/ui_atlas.sprites/card"
FRAME_MAT_D  = PCK / "materials/cards/frames"
BANNER_MAT_D = PCK / "materials/cards/banners"
CARD_TSCN    = PCK / "scenes/cards/card.tscn"
# The type plaque ("Attack"/"Skill"/"Power") is a plain PNG, not an atlas
# region — card.tscn points TypePlaque straight at this file.
PLAQUE_PNG   = PCK / "images/ui/cards/card_portrait_border_plaque2.png"
OUT          = ROOT / "card_chrome"

FRAME_TYPES  = ["attack", "skill", "power", "ancient", "quest"]
BORDER_TYPES = ["attack", "skill", "power"]
POOLS        = ["ironclad", "silent", "defect", "necrobinder", "regent", "colorless", "quest"]

# card_data.json's `pool` -> frame material. The character pools mirror
# CHAR_COLORS in run.py; the rest are pseudo-pools the extractor emits for
# non-character cards ("curse", "status", "token", "event", "quest", "other"),
# which is why a plain character lookup isn't enough — a Curse falling back to
# "colorless" renders a grey frame instead of the dark one the game uses.
# Keys are compared case-insensitively; `pool` is upper-case for characters
# and lower-case for the pseudo-pools.
POOL_TO_COLOR = {
    "ironclad": "red", "silent": "green", "defect": "blue",
    "necrobinder": "pink", "regent": "orange", "colorless": "colorless",
    "curse": "curse", "status": "colorless", "token": "colorless",
    "event": "colorless", "quest": "quest", "other": "colorless",
}

# card_data.json's `type` -> frame/border sprite variant. Only Attack/Skill/
# Power have their own art; everything else (Curse, Status, Quest, None)
# reuses the skill silhouette, which is what the game shows for them.
TYPE_TO_SPRITE = {"attack": "attack", "skill": "skill", "power": "power"}

# card_data.json's `rarity` -> banner/border/plaque material. Basic cards use
# the same desaturated look as Common (verified against the in-game Strike),
# and Token has no material of its own.
RARITY_TO_MATERIAL = {
    "basic": "common", "common": "common", "uncommon": "uncommon",
    "rare": "rare", "ancient": "ancient", "curse": "curse",
    "event": "event", "status": "status", "quest": "quest", "token": "status",
}

# ---------------------------------------------------------------------------
# CPU port of shaders/hsv.gdshader
# ---------------------------------------------------------------------------
# GLSL mat3(a, b, c) takes COLUMN vectors, so this is the standard RGB->YIQ
# matrix written column-wise in the shader source.
RGB_TO_YIQ = np.array([
    [0.2989,  0.5870,  0.1140],
    [0.5959, -0.2774, -0.3216],
    [0.2115, -0.5229,  0.3114],
], dtype=np.float64)
YIQ_TO_RGB = np.linalg.inv(RGB_TO_YIQ)


def hsv_shift(rgb, h, s, v):
    """Apply the game's HSV material shift to a float RGB array in 0..1."""
    flat = rgb.reshape(-1, 3)
    yiq = flat @ RGB_TO_YIQ.T                      # M * v

    hue = (1.0 - h) * 6.283185
    c, sn = np.cos(hue), np.sin(hue)
    # NOTE: the shader does `col.rgb *= hue_shift`, which in GLSL is
    # VECTOR * MATRIX (v @ M), not M @ v. Using M @ v here rotates the hue
    # the wrong way and turns the red material cyan.
    hue_m = np.array([[1, 0, 0],
                      [0,  c, sn],
                      [0, -sn, c]], dtype=np.float64)
    yiq = yiq @ hue_m

    yiq = yiq * np.array([1.0, s, s])              # saturation
    yiq = yiq * v                                  # value
    return (yiq @ YIQ_TO_RGB.T).reshape(rgb.shape)


def apply_material(img, params):
    """HSV-shift an RGBA image's colour channels, leaving alpha untouched."""
    a = np.asarray(img, dtype=np.float64) / 255.0
    rgb, alpha = a[..., :3], a[..., 3:]
    out = np.clip(hsv_shift(rgb, *params), 0.0, 1.0)
    merged = np.concatenate([out, alpha], axis=-1)
    return Image.fromarray((merged * 255).round().astype(np.uint8), "RGBA")


# ---------------------------------------------------------------------------
# Godot resource parsing
# ---------------------------------------------------------------------------
def material_params(path):
    txt = path.read_text(encoding="utf-8", errors="ignore")
    def val(k):
        m = re.search(rf"shader_parameter/{k}\s*=\s*(-?[\d.]+)", txt)
        return float(m.group(1))
    return val("h"), val("s"), val("v")


def load_materials(directory, prefix):
    return {
        p.stem.replace(prefix, "").replace("_mat", ""): material_params(p)
        for p in sorted(directory.glob("*.tres"))
    }


_atlas_cache = {}


def slice_sprite(name):
    """Crop one named sprite out of its backing atlas PNG."""
    tres = SPRITE_DIR / f"{name}.tres"
    txt = tres.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"^region\s*=\s*Rect2\(([-\d.,\s]+)\)", txt, re.M)
    if not m:
        raise ValueError(f"no region in {tres.name}")
    x, y, w, h = (int(float(v)) for v in m.group(1).split(","))
    am = re.search(r'path="res://(images/atlases/[^"]+\.png)"', txt)
    atlas_path = PCK / am.group(1)
    atlas = _atlas_cache.get(atlas_path)
    if atlas is None:
        atlas = _atlas_cache[atlas_path] = Image.open(atlas_path).convert("RGBA")
    return atlas.crop((x, y, x + w, y + h))


def card_layout():
    """Logical (center-origin) rects for each card element, from card.tscn.

    The card is laid out in a 300x422 space centred on the origin; the frame's
    native 598x844 atlas region is therefore almost exactly 2x. Emitting these
    lets the dashboard position everything without re-parsing the scene.
    """
    txt = CARD_TSCN.read_text(encoding="utf-8", errors="ignore")
    want = {"Portrait", "Frame", "PortraitBorder", "TitleBanner",
            "EnergyIcon", "TitleLabel", "DescriptionLabel", "TypePlaque"}
    out = {}
    for block in re.split(r"^\[node ", txt, flags=re.M)[1:]:
        nm = re.match(r'name="([^"]+)"', block)
        if not nm or nm.group(1) not in want:
            continue
        rect = {}
        for side in ("left", "top", "right", "bottom"):
            m = re.search(rf"^offset_{side}\s*=\s*(-?[\d.]+)", block, re.M)
            if m:
                rect[side] = float(m.group(1))
        if len(rect) == 4:
            out[nm.group(1)] = [rect["left"], rect["top"], rect["right"], rect["bottom"]]
    return out


# ---------------------------------------------------------------------------
def save(img, name, target_w, manifest):
    if img.width != target_w:
        h = max(1, round(img.height * target_w / img.width))
        img = img.resize((target_w, h), Image.LANCZOS)
    path = OUT / name
    img.save(path, optimize=True, compress_level=9)
    manifest.append((name, path.stat().st_size))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=int, default=300,
                    help="output width of a full card frame in px (default 300)")
    args = ap.parse_args()

    if not SPRITE_DIR.exists():
        raise SystemExit(f"Source not found: {SPRITE_DIR}\n"
                         "Run the full PCK extraction first (see CLAUDE.md).")

    frame_mats  = load_materials(FRAME_MAT_D, "card_frame_")
    banner_mats = load_materials(BANNER_MAT_D, "card_banner_")

    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir()
    manifest = []

    fw = args.width
    for t in FRAME_TYPES:
        base = slice_sprite(f"card_frame_{t}_s")
        for color, params in frame_mats.items():
            save(apply_material(base, params), f"frame_{t}_{color}.png", fw, manifest)

    # Portrait borders and banners scale relative to the frame: their logical
    # widths are 275 and 327 against the frame's 300 (see card.tscn).
    for t in BORDER_TYPES:
        base = slice_sprite(f"card_portrait_border_{t}_s")
        for rarity, params in banner_mats.items():
            save(apply_material(base, params),
                 f"portrait_border_{t}_{rarity}.png", round(fw * 275 / 300), manifest)

    banner = slice_sprite("card_banner")
    for rarity, params in banner_mats.items():
        save(apply_material(banner, params),
             f"banner_{rarity}.png", round(fw * 327 / 300), manifest)

    # Type plaque ("Attack"/"Skill"/"Power"). card.tscn assigns it no material,
    # but it is rarity-tinted at runtime like the banner: the source art is
    # cyan, which is exactly the `uncommon` look (that material is identity,
    # h=1/s=1/v=1), and a Basic card in-game shows a grey plaque — i.e. the
    # `common` material desaturating that same source. So bake per rarity.
    plaque = Image.open(PLAQUE_PNG).convert("RGBA")
    for rarity, params in banner_mats.items():
        save(apply_material(plaque, params),
             f"plaque_{rarity}.png", round(fw * 61 / 300), manifest)

    # Energy orbs are already coloured per character - no material applied.
    for pool in POOLS:
        try:
            save(slice_sprite(f"energy_{pool}"), f"energy_{pool}.png",
                 round(fw * 64 / 300), manifest)
        except FileNotFoundError:
            print(f"  (no energy sprite for {pool})")

    (OUT / "layout.json").write_text(json.dumps({
        "frameWidth": fw,
        "logicalSize": [300, 422],
        "poolToColor": POOL_TO_COLOR,
        "typeToSprite": TYPE_TO_SPRITE,
        "defaultTypeSprite": "skill",
        "rarityToMaterial": RARITY_TO_MATERIAL,
        "defaultMaterial": "common",
        # Font sizes are in the same logical units as `rects` (card.tscn's
        # theme_override_font_sizes), so a consumer scales them by the same
        # factor it scales the rects.
        "fontSizes": {"title": 26, "description": 21, "type": 16, "cost": 34},
        # Cards with energy < 0 (146 of them: curses, statuses, tokens) have no
        # cost at all - the game draws no orb for them, so consumers must skip
        # the EnergyIcon element entirely rather than draw an empty orb.
        "noEnergyWhenBelowZero": True,
        "rects": card_layout(),
    }, indent=2), encoding="utf-8")

    total = sum(sz for _, sz in manifest)
    print(f"Baked {len(manifest)} images -> {OUT}")
    print(f"Total: {total/1024/1024:.2f} MB  (frame width {fw}px)")


if __name__ == "__main__":
    main()
