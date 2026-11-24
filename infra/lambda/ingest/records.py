"""The largest-of-the-run numbers and win badges a run page shows (FB-44, FB-51, FB-64).

Worked out once, when a run is ingested, from the mod's event log and the game's own
.run file, and stored on the run record (run.records, run.badges) so the page needs no
second file. tools/export_run_records.py reads the owner's local files with the same
functions for the local preview.

Nothing is guessed: a number the log cannot give stays None and the page says "not recorded".
Badges are never worked out from stats; a run whose file carries none has none.
"""
from collections import defaultdict


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
    has_ovk = any(e["k"] == "hit" and "ovk" in e["a"] for e in ev)
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
    best_over = None              # the most overkill one hit carried past an enemy's last HP
    over_total = 0
    blk_total = 0
    for e in ev:
        a, k = e["a"], e["k"]
        key = (e["f"], e["t"])
        if k == "play1" and a.get("auto") is False and _slot(a) == slot:
            plays[key].add(a.get("instance") if a.get("instance") is not None else e["q"])
        elif k == "hit" and a.get("by") == "P" and a.get("t") != "P" and a.get("enemy", True) \
                and _slot(a) == slot and a.get("t") not in ("Osty", "Byrdpip"):
            n = a.get("total") or 0
            over = a.get("ovk") or 0
            dmg[key] += n          # damage dealt: overkill is never in it
            # A card's hit only: what a power, orb or Osty hits for is not a card. The hit is
            # what the card swung for, overkill included; `dealt` is what it actually took off.
            if a.get("card") and (best_hit is None or n + over > best_hit["n"]):
                best_hit = {"n": n + over, "dealt": n, "overkill": over, "card": a.get("card") or None,
                            "enemy": a.get("t"), "fight": e["f"], "turn": e["t"], "enc": encounters.get(e["f"])}
            over_total += over     # every hit of ours counts toward the run total, card or not
            if a.get("card") and over > (best_over["n"] if best_over else 0):
                best_over = {"n": over, "dealt": n, "card": a.get("card") or None, "enemy": a.get("t"),
                             "fight": e["f"], "turn": e["t"], "enc": encounters.get(e["f"])}
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
        # Only logs from a mod that records `ovk` can say; an older one has no overkill to show.
        "mostOverkill": best_over,
        "overkillTotal": over_total if has_ovk else None,
        "energyInTurn": energy,
        "events": len(ev), "truncated": bool(log.get("truncated")),
        "attributed": bool(new_mod and has_card_hits),
    }


def badges(player: dict) -> list | None:
    """The badges the game posted for this player: id and rarity only (the names, text
    and art are the game's, held in the site's catalog). None when the .run file has no
    badge list at all, which is different from an empty one."""
    if not isinstance(player, dict) or not isinstance(player.get("badges"), list):
        return None
    return [{"id": b["id"], "rarity": b["rarity"]} for b in player["badges"]
            if isinstance(b, dict) and isinstance(b.get("id"), str) and isinstance(b.get("rarity"), str)]
