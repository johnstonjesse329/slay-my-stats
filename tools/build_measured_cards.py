"""
tools/build_measured_cards.py — What a card costs, and which cards are junk, for the ingest Lambda.

The Lambda works out each run's energy and card-draw numbers from its event log
(infra/lambda/ingest/measured.py), and for that it needs card costs. The game's card
data is Mega Crit's and stays out of the repo, so this table is cut from the local
card_data.json when the Lambda bundle is made (infra/slay_my_stats/slay_my_stats_stack.py)
and lands beside the handler as measured_cards.json, never committed.

    python tools/build_measured_cards.py
"""
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
SOURCE = _ROOT / "card_data.json"
OUT = _ROOT / "infra" / "lambda" / "ingest" / "measured_cards.json"


def build(cards: dict) -> dict:
    """{"costs": {id: cost, "X", or None}, "junk": [id, ...]}.

    Junk is what an enemy puts in your deck to cost you a draw (Status and Curse). The
    same rule as tools/power_curve/derive_telemetry.py's, and costs the same as
    telemetry_report.card_costs(): infra/tests/test_measured.py checks both."""
    junk = sorted(cid for cid, c in cards.items() if isinstance(c, dict)
                  and (c.get("rarity") in ("Status", "Curse") or c.get("pool") in ("status", "curse")))
    dead = set(junk)
    costs = {}
    for cid, card in cards.items():
        unplayable = (cid in dead or card.get("type") in ("Status", "Curse")
                      or "Unplayable" in (card.get("keywords") or []))
        costs[cid] = None if unplayable else "X" if card.get("costsX") else max(card.get("energy") or 0, 0)
    return {"costs": costs, "junk": junk}


def write(path: Path = OUT, source: Path = SOURCE) -> Path:
    table = build(json.loads(source.read_text(encoding="utf-8")))
    path.write_text(json.dumps(table, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    return path


if __name__ == "__main__":
    out = write()
    print(f"{out.name}: {out.stat().st_size // 1024} KB")
