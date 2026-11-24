"""Bake the game's win-badge art and text for the run page's Run records panel (FB-64).

The game posts badges at the end of a win (players[].badges: id + rarity). Each is a glyph over
a bronze/silver/gold plate; this composites them into ui_icons/badges/<id>_<rarity>.png and
writes badge_catalog.json (id -> rarity -> title and text, the game's own localization), which
build_site.py publishes in the catalog. Needs the extracted game files (pck_recover_full).

    python tools/bake_badge_art.py
"""
import json
from pathlib import Path

from PIL import Image

import art_manifest

ROOT = Path(__file__).resolve().parents[1]
PCK_CANDIDATES = [ROOT / "pck_recover_full", ROOT.parent / "sts2-history-dashboard" / "pck_recover_full",
                  Path(r"E:/GitHub repos/sts2-history-dashboard/pck_recover_full")]
OUT = ROOT / "ui_icons" / "badges"
CATALOG = ROOT / "badge_catalog.json"
RARITIES = ("bronze", "silver", "gold")


def main():
    art_manifest.require_up_to_date()
    pck = next((p for p in PCK_CANDIDATES if p.is_dir()), None)
    if pck is None:
        raise SystemExit("pck_recover_full not found")
    base = pck / "images/ui/game_over_screen"
    loc = json.loads((pck / "localization/eng/badges.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    catalog = {}
    for glyph in sorted(base.glob("badge_*.png")):
        bid = glyph.stem[len("badge_"):]
        if bid in RARITIES:
            continue
        for rarity in RARITIES:
            title = loc.get(f"{bid.upper()}.{rarity}Title") or loc.get(f"{bid.upper()}.title")
            desc = loc.get(f"{bid.upper()}.{rarity}Description") or loc.get(f"{bid.upper()}.description")
            if not title:
                continue
            img = Image.open(base / f"badge_{rarity}.png").convert("RGBA")
            img.alpha_composite(Image.open(glyph).convert("RGBA"))
            img.save(OUT / f"{bid}_{rarity}.png", optimize=True)
            catalog.setdefault(bid.upper(), {})[rarity] = {"title": title, "desc": desc or ""}
    CATALOG.write_text(json.dumps(catalog, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    art_manifest.update(["ui_icons/badges"])
    print(f"{sum(len(v) for v in catalog.values())} badges -> {OUT}, {CATALOG.name}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    main()
