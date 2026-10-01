"""
Downscales card portrait images from the full-res PCK extraction to 144px-wide PNGs
suitable for the dashboard thumbnails (displayed at 72px, 2x for retina).

Run this after a full PCK extraction to regenerate card_portraits/:
    python downscale_portraits.py

Requires: pip install Pillow
Source:   pck_recover_full/images/packed/card_portraits/
Output:   card_portraits/  (preserves subfolder structure, e.g. ironclad/, beta/)
"""
import shutil
from pathlib import Path
from PIL import Image

from pck_root import find_pck_root

HERE    = Path(__file__).parent
ROOT    = HERE.parent          # this script lives in tools/; assets live at the repo root
SRC     = find_pck_root() / "images" / "packed" / "card_portraits"
DST     = ROOT / "card_portraits"
TARGET_W = 144

if not SRC.exists():
    print(f"Source not found: {SRC}")
    print('Run the full PCK extraction first (see README "Refreshing game data").')
    raise SystemExit(1)

shutil.rmtree(DST, ignore_errors=True)
DST.mkdir()

portraits = list(SRC.rglob("*.png"))
print(f"Downscaling {len(portraits)} portraits to {TARGET_W}px wide...")

for src in portraits:
    dst = DST / src.relative_to(SRC)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(src).convert("RGBA")
    w, h = img.size
    new_h = int(h * TARGET_W / w)
    img.resize((TARGET_W, new_h), Image.LANCZOS).save(dst, optimize=True, compress_level=9)

print(f"Done → {DST}")
