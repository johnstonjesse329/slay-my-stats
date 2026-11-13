"""
Copies each character's portraits out of the recovered game into ui_icons/char/:

  icon_<char>.png    the 88x88 head from the game's top panel
                     (images/ui/top_panel/character_icon_<char>.png). Shown before a
                     character's name everywhere the site names one.
  select_<char>.png  the 132x196 character-select portrait
                     (images/packed/character_select/char_select_<char>.png). Heads
                     each character's Ascension Tracker card on the Overview.

The characters are whichever have both files, so a new one arrives with the
patch that adds it (run.build_char_icons reads this folder, not a list).

    python tools/bake_char_icons.py
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pck_root import find_pck_root

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "ui_icons" / "char"


def main() -> int:
    pck = find_pck_root()
    icons = pck / "images" / "ui" / "top_panel"
    selects = pck / "images" / "packed" / "character_select"
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        old.unlink()
    chars = []
    for icon in sorted(icons.glob("character_icon_*.png")):
        char = icon.stem.removeprefix("character_icon_")
        select = selects / f"char_select_{char}.png"
        # Skips the _outline variants and the placeholder "deprecated_character".
        if char.endswith("_outline") or not select.exists():
            continue
        shutil.copy2(icon, OUT / f"icon_{char}.png")
        shutil.copy2(select, OUT / f"select_{char}.png")
        chars.append(char)
    if not chars:
        print(f"no character portraits found under {pck}", file=sys.stderr)
        return 1
    print(f"{len(chars)} characters -> {OUT}: {', '.join(chars)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
