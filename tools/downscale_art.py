"""
Downscales relic and potion art and copies the floor-node icons out of the PCK
extraction into committed repo directories.

Why this exists
---------------
relic_data.json used to store imagePath pointing into `pck_recover_full/`, which
is gitignored (2.8 GB). That meant relic art and node icons were broken for
anyone who cloned the repo — only the machine that had run the GDRE recovery
could render them. Card art already had this solved (downscale_portraits.py ->
card_portraits/); this does the same for the other two asset families.

Output (all committed):
    relic_images/   relic art, downscaled to RELIC_W
    potion_images/  potion art, downscaled to POTION_W
    node_icons/     the handful of floor-node icons run.py actually uses

Run after a PCK recovery, before extract_card_data.py (which records the
relative imagePath and checks the file exists):
    python tools/downscale_art.py

Requires: pip install Pillow
"""
import shutil
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
ROOT = HERE.parent
PCK  = ROOT / "pck_recover_full"

RELIC_SRC  = PCK / "images" / "relics"
# The game keeps a small and a large potion sprite; "large" is the one used on
# the potion bar and in rewards, and is the only size worth carrying.
POTION_SRC = PCK / "images" / "potions" / "large"
ICON_SRC  = PCK / "images" / "ui" / "run_history"
RELIC_DST  = ROOT / "relic_images"
POTION_DST = ROOT / "potion_images"
ICON_DST  = ROOT / "node_icons"

# Relics render at 88x68 in the tile grid and 72px tall in tooltips, so 176px
# wide is 2x for retina. Source art is 256x256; full-res was ~18 MB for 380
# files, which is dead weight in a repo and on a page.
RELIC_W = 176

# Potions render at roughly relic size in tooltips and reward lists; same 2x
# reasoning as relics.
POTION_W = 176

# run.py only maps these node types, plus the thirteen per-boss portraits
# (<name>_boss.png) it uses for boss timeline nodes, the eight per-Ancient
# portraits (darv/neow/nonupeipe/orobas/pael/tanx/tezcatara/vakuu.png) it
# uses for Ancient timeline nodes, and the unknown_elite/shop/treasure.png
# variants for a "?" room by what it turned out to be — the outline variants
# aren't used anywhere and are skipped. Kept at source resolution: they're
# 128x128 and the whole set totals well under 200 KB.
NODE_ICON_FILES = [
    "monster.png", "elite.png", "rest_site.png", "shop.png",
    "treasure.png", "unknown_monster.png", "unknown_elite.png",
    "unknown_shop.png", "unknown_treasure.png",
    "ancient.png", "event.png",
    "aeonglass_boss.png", "ceremonial_beast_boss.png", "doormaker_boss.png",
    "kaiser_crab_boss.png", "knowledge_demon_boss.png",
    "lagavulin_matriarch_boss.png", "queen_boss.png", "soul_fysh_boss.png",
    "test_subject_boss.png", "the_insatiable_boss.png", "the_kin_boss.png",
    "vantom_boss.png", "waterfall_giant_boss.png",
    "darv.png", "neow.png", "nonupeipe.png", "orobas.png", "pael.png",
    "tanx.png", "tezcatara.png", "vakuu.png",
]


def downscale_relics():
    srcs = sorted(p for p in RELIC_SRC.rglob("*.png") if not p.name.endswith(".import"))
    shutil.rmtree(RELIC_DST, ignore_errors=True)
    RELIC_DST.mkdir()
    total = 0
    for src in srcs:
        dst = RELIC_DST / src.relative_to(RELIC_SRC)
        dst.parent.mkdir(parents=True, exist_ok=True)
        img = Image.open(src).convert("RGBA")
        if img.width > RELIC_W:
            h = max(1, round(img.height * RELIC_W / img.width))
            img = img.resize((RELIC_W, h), Image.LANCZOS)
        img.save(dst, optimize=True, compress_level=9)
        total += dst.stat().st_size
    return len(srcs), total


def downscale_potions():
    if not POTION_SRC.exists():
        return 0, 0
    srcs = sorted(p for p in POTION_SRC.glob("*.png"))
    shutil.rmtree(POTION_DST, ignore_errors=True)
    POTION_DST.mkdir()
    total = 0
    for src in srcs:
        img = Image.open(src).convert("RGBA")
        if img.width > POTION_W:
            h = max(1, round(img.height * POTION_W / img.width))
            img = img.resize((POTION_W, h), Image.LANCZOS)
        dst = POTION_DST / src.name
        img.save(dst, optimize=True, compress_level=9)
        total += dst.stat().st_size
    return len(srcs), total


def copy_node_icons():
    shutil.rmtree(ICON_DST, ignore_errors=True)
    ICON_DST.mkdir()
    copied, missing, total = 0, [], 0
    for name in NODE_ICON_FILES:
        src = ICON_SRC / name
        if not src.exists():
            missing.append(name)
            continue
        shutil.copy2(src, ICON_DST / name)
        total += (ICON_DST / name).stat().st_size
        copied += 1
    return copied, missing, total


def main():
    if not RELIC_SRC.exists():
        raise SystemExit(f"Source not found: {RELIC_SRC}\n"
                         "Run the GDRE recovery first (see CLAUDE.md).")
    n, size = downscale_relics()
    print(f"Relics : {n} images -> {RELIC_DST}  ({size/1024/1024:.2f} MB at {RELIC_W}px)")
    pn, psize = downscale_potions()
    print(f"Potions: {pn} images -> {POTION_DST}  ({psize/1024/1024:.2f} MB at {POTION_W}px)")
    copied, missing, isize = copy_node_icons()
    print(f"Icons  : {copied} icons -> {ICON_DST}  ({isize/1024:.0f} KB)")
    if missing:
        # A missing file means the extraction is stale or the game renamed
        # an asset; run.py falls back to an emoji for any node type (or
        # boss encounter) whose icon didn't make it into node_icons/.
        print(f"  ! missing: {', '.join(missing)}")


if __name__ == "__main__":
    main()
