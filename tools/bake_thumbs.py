"""
Bakes small WebP thumbnails of the repo's art folders into thumbs/.

Why this exists
---------------
The dashboard draws a lot of art at icon size: the Overview's most-picked
cards and relics (22-26px), Card Stats' row portraits (22px), Run Detail's
boon icons (16px). Those used to load the full-size files -- a 332x454 card
face (~24 KB) or a 176x176 relic (~9 KB) for a 26px box -- so a single
Overview or Card Stats view downloaded close to a megabyte of images it showed
as specks. A thumbnail at twice the largest icon size covers high-DPI screens
at a few KB each.

The Cards page's table draws a card face 112px wide, too big for the icon-size
copy, so card_final/ also gets a larger set (LARGE_BOX, sharp at 2x) under
thumbs/lg/.

Output (gitignored, uploaded by tools/deploy.py), mirroring each source folder:
    thumbs/card_final/...      thumbs/card_portraits/...
    thumbs/relic_images/...    thumbs/potion_images/...
    thumbs/lg/card_final/...
Every file becomes <same relative path>.webp, fitted inside THUMB_BOX (LARGE_BOX
for thumbs/lg/). js/item-tips.js's thumbSrc() maps a full-size URL onto its
thumbnail.

Run after anything that changes those folders (tools/refresh_game_data.py
runs it last):
    python tools/bake_thumbs.py

Requires: pip install Pillow
"""
import shutil
from pathlib import Path

from PIL import Image

import art_manifest

ROOT = Path(__file__).resolve().parent.parent
DST  = ROOT / "thumbs"

SOURCES = ["card_final", "card_portraits", "relic_images", "potion_images", "enchantment_images"]
# 2x the largest icon-size use (a 26px-wide card face), with a little room.
# Tall enough that a card face (3:4) is limited by width, not height. A face image
# includes a 16px transparent margin around a 300px card, so the box is sized for
# the image (332px) while keeping the card itself at the 56px it was.
THUMB_BOX = (62, 88)
# The Cards table's face (dashboard.css --cards-thumb-w: 112px) at 2x.
LARGE = "lg"
LARGE_SOURCES = ["card_final"]
LARGE_BOX = (224, 320)
QUALITY = 85


def bake(src: Path, dst: Path, box=THUMB_BOX) -> None:
    with Image.open(src) as im:
        im.load()
        im.thumbnail(box, Image.LANCZOS)
        dst.parent.mkdir(parents=True, exist_ok=True)
        im.save(dst, "WEBP", quality=QUALITY, method=6)


def main() -> None:
    art_manifest.require_up_to_date()
    if DST.exists():
        shutil.rmtree(DST)  # drop thumbnails whose source is gone
    total_src = total_dst = count = 0
    jobs = [(name, DST / name, THUMB_BOX) for name in SOURCES]
    jobs += [(name, DST / LARGE / name, LARGE_BOX) for name in LARGE_SOURCES]
    for name, out, box in jobs:
        root = ROOT / name
        if not root.exists():
            print(f"skip {name}/ (missing)")
            continue
        for src in sorted(root.rglob("*")):
            if src.suffix.lower() not in (".png", ".webp"):
                continue
            dst = out / src.relative_to(root).with_suffix(".webp")
            bake(src, dst, box)
            total_src += src.stat().st_size
            total_dst += dst.stat().st_size
            count += 1
    print(f"{count} thumbnails: {total_src / 1e6:.1f} MB of art -> {total_dst / 1e6:.1f} MB in thumbs/")
    art_manifest.update(["thumbs"])


if __name__ == "__main__":
    main()
