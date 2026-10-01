"""
Bakes small WebP thumbnails of the repo's art folders into thumbs/.

Why this exists
---------------
The dashboard draws a lot of art at icon size: the Overview's most-picked
cards and relics (22-26px), Card Stats' row portraits (22px), Run Detail's
boon icons (16px). Those used to load the full-size files -- a 260x345 card
face (~19 KB) or a 176x176 relic (~9 KB) for a 26px box -- so a single
Overview or Card Stats view downloaded close to a megabyte of images it showed
as specks. A thumbnail at twice the largest icon size covers high-DPI screens
at a few KB each.

Output (gitignored, uploaded by tools/deploy.py), mirroring each source folder:
    thumbs/card_final/...      thumbs/card_portraits/...
    thumbs/relic_images/...    thumbs/potion_images/...
Every file becomes <same relative path>.webp, fitted inside THUMB_BOX.
js/card-face.js's thumbSrc() maps a full-size URL onto its thumbnail.

Run after anything that changes those folders (tools/refresh_game_data.py
runs it last):
    python tools/bake_thumbs.py

Requires: pip install Pillow
"""
import shutil
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DST  = ROOT / "thumbs"

SOURCES = ["card_final", "card_portraits", "relic_images", "potion_images"]
# 2x the largest icon-size use (a 26px-wide card face), with a little room.
# Tall enough that a card face (3:4) is limited by width, not height.
THUMB_BOX = (56, 80)
QUALITY = 85


def bake(src: Path, dst: Path) -> None:
    with Image.open(src) as im:
        im.load()
        im.thumbnail(THUMB_BOX, Image.LANCZOS)
        dst.parent.mkdir(parents=True, exist_ok=True)
        im.save(dst, "WEBP", quality=QUALITY, method=6)


def main() -> None:
    if DST.exists():
        shutil.rmtree(DST)  # drop thumbnails whose source is gone
    total_src = total_dst = count = 0
    for name in SOURCES:
        root = ROOT / name
        if not root.exists():
            print(f"skip {name}/ (missing)")
            continue
        for src in sorted(root.rglob("*")):
            if src.suffix.lower() not in (".png", ".webp"):
                continue
            dst = DST / name / src.relative_to(root).with_suffix(".webp")
            bake(src, dst)
            total_src += src.stat().st_size
            total_dst += dst.stat().st_size
            count += 1
    print(f"{count} thumbnails: {total_src / 1e6:.1f} MB of art -> {total_dst / 1e6:.1f} MB in thumbs/")


if __name__ == "__main__":
    main()
