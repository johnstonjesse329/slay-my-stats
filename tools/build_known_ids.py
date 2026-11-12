"""
tools/build_known_ids.py — Which characters, cards and relics are core game content, for the ingest Lambda.

A run that names anything else came from a mod, or from a patch newer than our game data. The
process Lambda holds such a run back: it stays in raw/ and joins the profile when a rebuild
(tools/rebuild_profiles.py) runs after the game data catches up. The game data is Mega Crit's and
stays out of the repo, so this table is cut from the local card_data.json and relic_data.json
when the Lambda bundle is made (infra/slay_my_stats/slay_my_stats_stack.py) and lands beside the
handler as known_ids.json, never committed. Content the game has since removed is listed by hand
in tools/retired_ids.json.

    python tools/build_known_ids.py
"""
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
CARDS = _ROOT / "card_data.json"
RELICS = _ROOT / "relic_data.json"
RETIRED = Path(__file__).resolve().with_name("retired_ids.json")
OUT = _ROOT / "infra" / "lambda" / "ingest" / "known_ids.json"


def build(cards: dict, relics: dict, retired: dict) -> list[str]:
    """Every known ID, sorted: cards and relics as the game names them ("CARD.X", "RELIC.X"),
    characters as "CHARACTER.X" (a character is a card pool written in capitals: IRONCLAD, not
    colorless), and the retired IDs."""
    chars = {f"CHARACTER.{c['pool']}" for c in cards.values()
             if isinstance(c, dict) and isinstance(c.get("pool"), str) and c["pool"].isupper()}
    return sorted(set(cards) | set(relics) | chars | {k for k in retired if not k.startswith("_")})


def load() -> list[str]:
    read = lambda p: json.loads(p.read_text(encoding="utf-8"))
    return build(read(CARDS), read(RELICS), read(RETIRED))


def write(path: Path = OUT) -> Path:
    path.write_text(json.dumps(load(), separators=(",", ":")), encoding="utf-8")
    return path


if __name__ == "__main__":
    out = write()
    print(f"{out.name}: {len(json.loads(out.read_text(encoding='utf-8')))} IDs")
