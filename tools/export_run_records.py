"""PREVIEW: run_records.json for the owner's own runs (FB-44, FB-51, FB-64).

Reads two things the owner has on this machine and puts them side by side by run start time:

  * the mod's event log, telemetry/<steamid>/<start time>.json.gz (local_data/owner_telemetry/,
    synced from the data bucket), for the "largest" records of a run: cards played in a turn,
    damage in a turn, the largest single hit, Block gained, energy gained in a turn;
  * the game's own .run file (steam/<id>/modded/profile1/saves/history), for the win badges the
    game posts on its end screen (players[].badges: id + rarity). Badges are never worked out
    from stats here; a run whose file has none shows none.

Nothing is guessed: a number the log cannot give stays None and the page says "not recorded".

    python tools/export_run_records.py --steam <your Steam ID> [--history <dir>] [--telemetry <dir>]

Writes local_data/run_records.json (ignored by git); build_site.py puts it in DATA.runRecords
when it exists. The badge art is the game's own (images/ui/game_over_screen/badge_*.png over its
bronze/silver/gold plate), inlined so no new art folder is needed.
"""
import argparse
import base64
import gzip
import io
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAVES = Path.home() / "AppData/Roaming/SlayTheSpire2/steam"
PCK = Path(r"E:/GitHub repos/sts2-history-dashboard/pck_recover_full")
OUT = ROOT / "local_data" / "run_records.json"


def _slot(a):
    """The player a logged event belongs to. Older logs carry no slot: one player."""
    for key in ("sourceSlot", "targetSlot"):
        if a.get(key) is not None:
            return a[key]
    return 0


def records(log, slot):
    """Largest-of-the-run numbers for one player's slot, from one run's event log."""
    ev = log.get("log") or []
    kinds = {e["k"] for e in ev}
    # What this log can say. `action0` and `damageCalc` arrived with the card-attributed hits,
    # `energy+` events and sourceSlot; a log without them cannot name the card or count gained energy.
    new_mod = "action0" in kinds
    has_card_hits = any(e["k"] == "hit" and "card" in e["a"] for e in ev)
    encounters = {}
    for e in ev:
        if e["k"] == "fight0":
            encounters[e["f"]] = (e["a"].get("enc") or "").replace("ENCOUNTER.", "")

    plays = defaultdict(set)      # (fight, turn) -> card instances played by hand
    dmg = defaultdict(int)
    blk = defaultdict(int)
    start = {}                    # (fight, turn) -> energy the turn opened with
    cards = defaultdict(int)      # (fight, turn) -> energy gained by cards and relics
    best_hit = None
    blk_total = 0
    for e in ev:
        a, k = e["a"], e["k"]
        key = (e["f"], e["t"])
        if k == "play1" and a.get("auto") is False and _slot(a) == slot:
            plays[key].add(a.get("instance") if a.get("instance") is not None else e["q"])
        elif k == "hit" and a.get("by") == "P" and a.get("t") != "P" and a.get("enemy", True) \
                and _slot(a) == slot and a.get("t") not in ("Osty", "Byrdpip"):
            n = a.get("total") or 0
            dmg[key] += n
            # A card's hit only: what a power, orb or Osty hits for is not a card.
            if a.get("card") and (best_hit is None or n > best_hit["n"]):
                best_hit = {"n": n, "card": a.get("card") or None, "enemy": a.get("t"), "fight": e["f"],
                            "turn": e["t"], "enc": encounters.get(e["f"])}
        elif k == "blk" and a.get("c") == "P" and _slot(a) == slot:
            blk[key] += a.get("n") or 0
            blk_total += a.get("n") or 0
        elif k == "turn0" and a.get("targetSlot", 0) == slot:
            start[key] = a.get("energy")
        elif k == "energy+" and a.get("targetSlot", 0) == slot:
            cards[key] += a.get("n") or 0

    def top(table, extra=None):
        if not table:
            return None
        key = max(table, key=lambda x: table[x])
        row = {"n": table[key], "fight": key[0], "turn": key[1], "enc": encounters.get(key[0])}
        if extra:
            row.update(extra(key))
        return row

    energy = None
    if new_mod and (start or cards):
        keys = set(start) | set(cards)
        best = max(keys, key=lambda x: (start.get(x) or 0) + cards.get(x, 0))
        energy = {"n": (start.get(best) or 0) + cards.get(best, 0), "start": start.get(best) or 0,
                  "fromCards": cards.get(best, 0), "fight": best[0], "turn": best[1], "enc": encounters.get(best[0])}
        by_cards = max(keys, key=lambda x: cards.get(x, 0))
        energy["mostFromCards"] = {"n": cards.get(by_cards, 0), "fight": by_cards[0], "turn": by_cards[1],
                                   "enc": encounters.get(by_cards[0])}
    return {
        "cardsInTurn": top({k: len(v) for k, v in plays.items()}),
        "damageInTurn": top(dmg),
        "blockInTurn": top(blk),
        "blockTotal": blk_total if blk else None,
        "largestHit": best_hit if has_card_hits else None,
        "energyInTurn": energy,
        "events": len(ev), "truncated": bool(log.get("truncated")),
        "attributed": bool(new_mod and has_card_hits),
    }


def badge_names():
    loc = json.loads((PCK / "localization/eng/badges.json").read_text(encoding="utf-8"))

    def name(bid, rarity):
        t = loc.get(f"{bid}.{rarity}Title") or loc.get(f"{bid}.title")
        d = loc.get(f"{bid}.{rarity}Description") or loc.get(f"{bid}.description")
        return t, d
    return name


def badge_art(bid, rarity, cache):
    from PIL import Image
    key = f"{bid.lower()}_{rarity}"
    if key in cache:
        return key
    base = PCK / "images/ui/game_over_screen"
    plate, glyph = base / f"badge_{rarity}.png", base / f"badge_{bid.lower()}.png"
    if not plate.exists() or not glyph.exists():
        return None
    img = Image.open(plate).convert("RGBA")
    img.alpha_composite(Image.open(glyph).convert("RGBA"))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    cache[key] = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    return key


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steam", required=True)
    ap.add_argument("--history")
    ap.add_argument("--telemetry", default=str(ROOT / "local_data" / "owner_telemetry"))
    args = ap.parse_args()
    name = badge_names()
    art, runs = {}, {}
    history = Path(args.history) if args.history else SAVES / args.steam / "modded/profile1/saves/history"
    for f in sorted(history.glob("*.run")):
        run = json.loads(f.read_text(encoding="utf-8"))
        ts = str(run.get("start_time") or f.stem)
        players = run.get("players") or []
        slot = next((i for i, p in enumerate(players) if str(p.get("id")) == args.steam), 0)
        entry = {"slot": slot, "badges": None, "records": None}
        if "badges" in players[slot]:
            entry["badges"] = []
            for b in players[slot]["badges"]:
                title, desc = name(b["id"], b["rarity"])
                entry["badges"].append({"id": b["id"], "rarity": b["rarity"], "title": title, "desc": desc,
                                        "art": badge_art(b["id"], b["rarity"], art)})
        tel = Path(args.telemetry) / f"{ts}.json.gz"
        if tel.exists():
            entry["records"] = records(json.load(gzip.open(tel, "rt", encoding="utf-8")), slot)
        runs[ts] = entry
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"runs": runs, "badgeArt": art}, separators=(",", ":")), encoding="utf-8")
    withrec = sum(1 for r in runs.values() if r["records"])
    print(f"{len(runs)} runs, {withrec} with an event log, {len(art)} badge images -> {OUT}")


if __name__ == "__main__":
    main()
