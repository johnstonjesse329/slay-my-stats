"""
Bakes the page background: the game's act-map parchment scroll with a map
(nodes + dashed paths) drawn on it, darkened so the dashboard's panels stay
readable on top.

The scroll is the three stacked map_{top,middle,bottom} pieces the map screen
uses (images/packed/map/map_bgs/<act>/, 2036x1440 each). The map drawn on it
is decorative, not a real run: seeded random rows of 2-4 nodes using the
committed node_icons/, recolored to the sepia ink the game draws unvisited
nodes in, joined by dashed ink paths that stop short of each icon.

Output: ui_icons/map_scroll.webp (committed; dashboard.css draws it behind
the page via .map-bg, panned by js/map-bg.js).

Run after a full PCK extraction (see README "Refreshing game data"):
    python tools/bake_map_background.py [--pck PATH] [--act overgrowth]

Requires: pip install Pillow
"""
import argparse
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance

HERE = Path(__file__).parent
ROOT = HERE.parent
# The extraction lives in-repo on some machines and in the sibling
# sts2-history-dashboard checkout on others.
PCK_CANDIDATES = [ROOT / "pck_recover_full", ROOT.parent / "sts2-history-dashboard" / "pck_recover_full"]
ICONS = ROOT / "node_icons"
OUT = ROOT / "ui_icons" / "map_scroll.webp"

SLATE = (25, 29, 32)       # the map screen's surround, also the page colour around the scroll
INK = (70, 52, 34)         # unvisited-node sepia
KINDS = ["monster"] * 6 + ["elite"] * 2 + ["rest_site"] * 2 + ["event"] * 3 + ["shop", "treasure"]
WIDTH = 1400               # dashboard.css caps the drawn scroll at this width
BRIGHTNESS = 0.30
SATURATION = 0.85


def ink_icon(name: str, size: int) -> Image.Image:
    im = Image.open(ICONS / f"{name}.png").convert("RGBA").resize((size, size), Image.LANCZOS)
    ink = Image.new("RGBA", im.size, INK + (0,))
    ink.putalpha(im.getchannel("A").point(lambda v: int(v * 0.7)))
    return ink


def draw_map(img: Image.Image, x0, x1, y0, y1, seed, cols=6, row_h=150, icon=64):
    rnd = random.Random(seed)
    d = ImageDraw.Draw(img)
    step = (x1 - x0) / cols
    grid = []
    for r in range(int((y1 - y0) / row_h)):
        xs = sorted(rnd.sample(range(cols), rnd.randint(2, 4)))
        grid.append([(int(x0 + step * (c + 0.5) + rnd.randint(-18, 18)),
                      int(y1 - r * row_h + rnd.randint(-14, 14))) for c in xs])
    for row, nxt_row in zip(grid, grid[1:]):
        for (x, y) in row:
            for (nx, ny) in sorted(nxt_row, key=lambda p: abs(p[0] - x))[: rnd.choice((1, 1, 2))]:
                n = int(((nx - x) ** 2 + (ny - y) ** 2) ** 0.5 / 14)
                for k in range(0, n, 2):
                    t0, t1 = k / n, (k + 0.55) / n
                    if t0 < 0.22 or t1 > 0.78:   # leave a gap around each icon
                        continue
                    d.line([(x + (nx - x) * t0, y + (ny - y) * t0),
                            (x + (nx - x) * t1, y + (ny - y) * t1)], fill=INK + (120,), width=3)
    for row in grid:
        for (x, y) in row:
            img.alpha_composite(ink_icon(rnd.choice(KINDS), icon), (x - icon // 2, y - icon // 2))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pck", type=Path, help="pck_recover_full root (default: auto-detect)")
    ap.add_argument("--act", default="overgrowth", help="map_bgs subfolder (glory, hive, overgrowth, underdocks)")
    args = ap.parse_args()

    pck = args.pck or next((p for p in PCK_CANDIDATES if p.exists()), None)
    if pck is None:
        raise SystemExit("pck_recover_full not found; pass --pck")
    src = pck / "images" / "packed" / "map" / "map_bgs" / args.act

    pieces = [Image.open(src / f"map_{p}_{args.act}.png").convert("RGBA") for p in ("top", "middle", "bottom")]
    w, h = pieces[0].size
    scroll = Image.new("RGBA", (w, h * 3), SLATE + (255,))
    for i, p in enumerate(pieces):
        scroll.alpha_composite(p, (0, h * i))
    draw_map(scroll, 330, 1720, 700, h * 3 - 500, seed=7)

    out = ImageEnhance.Color(scroll.convert("RGB")).enhance(SATURATION)
    out = ImageEnhance.Brightness(out).enhance(BRIGHTNESS)
    out = out.resize((WIDTH, round(out.height * WIDTH / out.width)), Image.LANCZOS)
    OUT.parent.mkdir(exist_ok=True)
    out.save(OUT, "WEBP", quality=80, method=6)
    print(f"wrote {OUT.relative_to(ROOT)} {out.size[0]}x{out.size[1]} {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
