"""Archetype of every reviewed run, from its final deck, for power_curve.html.

Each character's archetypes are counted off the signature cards in the deck
the run ended with (the card fields power_curve builds, plus what the powers a
card applies consume or produce). The biggest count names the run when it's 3
or more; a close second (within 70%) makes it a pair; otherwise "Mixed".
Writes the archetype into pcs/index.json and prints a baseline per character
and archetype: runs, wins and the median curve at act ends and the finish.

    python archetypes.py
"""
import json
import statistics
from collections import defaultdict

import approaches as ap
import gamma_curves as g
import power_curve as pc

HERE = g.HERE


def pw_tags(c):
    """What the powers c applies to you consume and produce (exhaust, shiv, block...)."""
    tags = set()
    for pw, (side, _) in c["applies"].items():
        p = pc.PD["powers"].get(pw, {})
        tags |= {"uses:" + t for t in p.get("consumes", [])} | {"makes:" + t for t in p.get("produces", [])}
        tags |= {"chan:" + h["channel"] for h in p.get("orbHooks", []) if h.get("channel")}
    return tags


def channels(c, orb):
    return any(op["op"] == "channel" and op["orb"] == orb for op in c["orb_ops"]) or "chan:" + orb in pw_tags(c)


def applies(c, pw, side):
    return c["applies"].get(pw, (None,))[0] == side or "makes:power:" + pw in pw_tags(c)


def block_scaling(c):
    """Cards that build on block, not just make some: Body Slam, Entrench,
    Barricade, Juggernaut, Unmovable, Stone Armor (a big Block card alone isn't a build)."""
    if (c["calc"] and "block" in c["calc"][:2]) or (c["blocker"] and not c["block"]):
        return True
    for pw in c["applies"]:
        p = pc.PD["powers"].get(pw, {})
        if p.get("keepsBlock") or "block" in p.get("produces", [])                 or any(t.get("on") == "blockGained" for t in p.get("triggers", []))                 or any(m.get("stat") == "block" for m in p.get("mods", [])):
            return True
    return False


SIGS = {
    "IRONCLAD": {
        "Strength": lambda c: applies(c, "Strength", "self") or any(e.get("power") == "Strength" for pw in c["applies"] for e in pc.turn_power(pw)),
        "Exhaust": lambda c: bool(c["exhausts"]) or "uses:exhaust" in pw_tags(c),
        "Block": lambda c: block_scaling(c),
    },
    "SILENT": {
        "Shiv": lambda c: bool(c["shivs"]) or "uses:shiv" in pw_tags(c),
        "Poison": lambda c: applies(c, "Poison", "enemy") or "uses:power:Poison" in pw_tags(c),
        "Discard": lambda c: bool(c["discard"] or c["sly"] or c["discards_hand"]) or "uses:discard" in pw_tags(c),
    },
    "DEFECT": {
        "Lightning": lambda c: channels(c, "Lightning"),
        "Frost": lambda c: channels(c, "Frost"),
        "Dark": lambda c: channels(c, "Dark"),
        "Zero-cost": lambda c: c["type"] == "Attack" and c["cost"] == 0 and not c["x"],
    },
    "NECROBINDER": {
        "Doom": lambda c: applies(c, "Doom", "enemy") or bool(c["doom_kill"] or c["doom_from_dmg"]),
        "Osty": lambda c: bool(c["osty"] or c["summon"]) or "uses:osty" in pw_tags(c),
    },
    "REGENT": {
        "Stars": lambda c: bool(c["gain_stars"] or c["star_x"]) or c["stars"] > 0,
        "Forge": lambda c: bool(c["forge"] or c["blade"]),
    },
}


def archetype(ch, deck):
    sigs = SIGS.get(ch)
    if not sigs:
        return "Mixed"
    score = sorted(((sum(1 for c in deck if f(c)), name) for name, f in sigs.items()), reverse=True)
    (top, a), (second, b) = score[0], score[1]
    if top < 3:
        return "Mixed"
    return f"{a} + {b}" if second >= 3 and second >= 0.7 * top else a


def main():
    runs = g.load()
    index = json.loads((HERE / "pcs" / "index.json").read_text(encoding="utf-8"))
    groups = defaultdict(list)
    for e in index:
        if e.get("error"):
            continue
        sid, ts = e["id"].split("-")
        st = ap.states(runs[(sid, int(ts))], sid)
        e["archetype"] = archetype(e["character"], st[-1][1]) if st else "Mixed"
        if e["floors"] >= 17 and not e["coop"]:
            curve = json.loads((HERE / "pcs" / f"{e['id']}.json").read_text(encoding="utf-8"))
            groups[(e["character"], e["archetype"])].append((e, curve["floors"]))
    (HERE / "pcs" / "index.json").write_text(json.dumps(index), encoding="utf-8")

    med = lambda xs: statistics.median(xs) if xs else float("nan")  # noqa: E731
    at = lambda fl, f, k: fl[min(f, len(fl)) - 1][k]  # noqa: E731
    print(f"{'character':12}{'archetype':20}{'runs':>5}{'wins':>5}   dmg f1/17/33/end    dmg3 end  block f1/17/33/end   dmgGrowth end  falls")
    for (ch, arch), rows in sorted(groups.items()):
        fl = [r[1] for r in rows]
        dm = [med([at(x, f, "dmg") for x in fl]) for f in (1, 17, 33)] + [med([x[-1]["dmg"] for x in fl])]
        bl = [med([at(x, f, "block") for x in fl]) for f in (1, 17, 33)] + [med([x[-1]["block"] for x in fl])]
        falls = sum(1 for x in fl if x[-1]["dmg"] < x[0]["dmg"])  # ended weaker than it started
        print(f"{ch:12}{arch:20}{len(rows):>5}{sum(r[0]['win'] for r in rows):>5}   "
              + "/".join(f"{v:.0f}" for v in dm).ljust(19) + f"{med([x[-1]['dmg3'] for x in fl]):>8.0f}  "
              + "/".join(f"{v:.0f}" for v in bl).ljust(19) + f"{med([x[-1]['dmgGrowth'] for x in fl]):>14.1f}  {falls:>5}")


if __name__ == "__main__":
    main()
