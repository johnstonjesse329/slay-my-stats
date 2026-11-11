"""
Bakes the art the run page's "Map by Act" draws with, from the game's own map
screen (MegaCrit.Sts2.Core.Nodes.Screens.Map): per act, the scroll behind the
map, the path dots, the circle drawn round visited nodes, and each node type's
icon on its outline.

What the game does, and so what this bakes:
  * Scroll: the act's map_top / map_middle / map_bottom pieces stacked
    (images/packed/map/map_bgs/<act>/, 2036x1440 each).
  * Node: the atlas icon (ui_atlas map/icons/map_*) over its outline
    (compressed map/map_*_outline). The outline is tinted with the act's
    MapBgColor; the icon's tan pixels (within 0.5 of initial_color in
    normal_map_point.gdshader) are replaced with MapBgColor lerped halfway to
    gray.
  * Path dot: compressed map/map_dot, tinted MapUntraveledColor, or
    MapTraveledColor once walked.
  * Circle: compressed map/map_circle_4 (the finished frame), tinted 241F1A.

Output: ui_icons/map/ (scroll_<act>.webp, dot_<act>_{todo,walked}.png,
node_<act>_<type>.png incl. node_<act>_unknown_<room>.png, circle.png).

Run after a full PCK extraction (see README "Refreshing game data"):
    python tools/bake_act_map_art.py [--pck PATH]

Requires: pip install Pillow
"""
import argparse
import re
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
ROOT = HERE.parent
PCK_CANDIDATES = [ROOT / "pck_recover_full", ROOT.parent / "sts2-history-dashboard" / "pck_recover_full"]
OUT = ROOT / "ui_icons" / "map"

# Models/Acts/*.cs: MapBgColor, MapUntraveledColor, MapTraveledColor.
ACTS = {
    "overgrowth":  {"bg": "A78A67", "todo": "877256", "walked": "28231D"},
    "underdocks":  {"bg": "9F95A5", "todo": "534A62", "walked": "180F24"},
    "hive":        {"bg": "9B9562", "todo": "6E7750", "walked": "27221C"},
    "glory":       {"bg": "819A97", "todo": "60717C", "walked": "1D1E2F"},
}
CIRCLE_TINT = "241F1A"  # scenes/vfx/map_circle_vfx.tscn
# normal_map_point.gdshader's initial_color, from normal_map_point.tscn.
INITIAL = (0.705882, 0.615686, 0.537255)
# NNormalMapPoint.IconName: our node type -> the game's icon file.
NODE_ICONS = {"monster": "map_monster", "elite": "map_elite", "rest_site": "map_rest",
              "shop": "map_shop", "unknown": "map_unknown", "treasure": "map_chest"}
# NNormalMapPoint.UnknownIconPath / UnknownOutlinePath: a visited "?" shows the room it turned
# out to be, on that room's outline.
UNKNOWN_ICONS = {"unknown_monster": ("map_unknown_monster", "map_monster"),
                 "unknown_elite": ("map_unknown_elite", "map_elite"),
                 "unknown_shop": ("map_unknown_shop", "map_shop"),
                 "unknown_treasure": ("map_unknown_chest", "map_chest")}
SCROLL_CROP = (398, 1638)   # the 1240px of the 2036 wide scroll round the 1050px the nodes span
SCROLL_W = 500


def rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def atlas(pck: Path, tres: Path) -> Image.Image:
    """An AtlasTexture .tres as Godot shows it: the region placed at margin.xy in a
    canvas region.size + margin.size big."""
    t = tres.read_text()
    src = re.search(r'path="res://images/atlases/([^"]+)"', t).group(1)
    x, y, w, h = map(float, re.search(r"region = Rect2\(([^)]+)\)", t).group(1).split(","))
    mx, my, mw, mh = map(float, re.search(r"margin = Rect2\(([^)]+)\)", t).group(1).split(","))
    crop = Image.open(pck / "images" / "atlases" / src).convert("RGBA").crop((int(x), int(y), int(x + w), int(y + h)))
    full = Image.new("RGBA", (int(w + mw), int(h + mh)), (0, 0, 0, 0))
    full.paste(crop, (int(mx), int(my)))
    return full


def tint(im: Image.Image, color) -> Image.Image:
    """Godot's modulate: multiply the colour channels."""
    px = im.load()
    for yy in range(im.height):
        for xx in range(im.width):
            r, g, b, a = px[xx, yy]
            px[xx, yy] = (int(r * color[0]), int(g * color[1]), int(b * color[2]), a)
    return im


def recolor(im: Image.Image, map_color) -> Image.Image:
    """normal_map_point.gdshader: pixels near initial_color become map_color."""
    px = im.load()
    out = tuple(int(c * 255) for c in map_color)
    for yy in range(im.height):
        for xx in range(im.width):
            r, g, b, a = px[xx, yy]
            d = (((r / 255 - INITIAL[0]) ** 2 + (g / 255 - INITIAL[1]) ** 2 + (b / 255 - INITIAL[2]) ** 2) ** 0.5)
            if d < 0.5:
                px[xx, yy] = out + (a,)
    return im


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pck", type=Path, help="pck_recover_full root (default: auto-detect)")
    args = ap.parse_args()
    pck = args.pck or next((p for p in PCK_CANDIDATES if p.exists()), None)
    if pck is None:
        raise SystemExit("pck_recover_full not found; pass --pck")
    OUT.mkdir(parents=True, exist_ok=True)
    sprites = pck / "images" / "atlases"
    icons, outlines = sprites / "ui_atlas.sprites" / "map" / "icons", sprites / "compressed.sprites" / "map"

    tint(atlas(pck, outlines / "map_circle_4.tres"), rgb(CIRCLE_TINT)).save(OUT / "circle.png")
    dot = atlas(pck, outlines / "map_dot.tres")
    for act, c in ACTS.items():
        scroll = Image.new("RGBA", (2036, 1440 * 3))
        for i, part in enumerate(("top", "middle", "bottom")):
            piece = Image.open(pck / "images" / "packed" / "map" / "map_bgs" / act / f"map_{part}_{act}.png").convert("RGBA")
            scroll.paste(piece, (0, 1440 * i))
        scroll = scroll.crop((SCROLL_CROP[0], 0, SCROLL_CROP[1], scroll.height))
        scroll.resize((SCROLL_W, round(scroll.height * SCROLL_W / scroll.width)), Image.LANCZOS).save(
            OUT / f"scroll_{act}.webp", quality=78, method=6)
        for state in ("todo", "walked"):
            tint(dot.copy(), rgb(c[state])).save(OUT / f"dot_{act}_{state}.png")
        bg = rgb(c["bg"])
        map_color = tuple(b * 0.5 + 0.5 * 0.5 for b in bg)   # lerp(bg, gray, 0.5)
        pairs = {k: (n, n) for k, n in NODE_ICONS.items()} | UNKNOWN_ICONS
        for key, (icon, outline) in pairs.items():
            node = tint(atlas(pck, outlines / f"{outline}_outline.tres"), bg)
            node.alpha_composite(recolor(atlas(pck, icons / f"{icon}.tres"), map_color))
            node.save(OUT / f"node_{act}_{key}.png")
    print(f"baked {len(list(OUT.iterdir()))} files into {OUT}")


if __name__ == "__main__":
    main()
