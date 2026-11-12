"""Archetype of every reviewed run, from its final deck, for power_curve.html.

Each character's archetypes are counted off the signature cards in the deck
the run ended with (the card fields power_curve builds, plus what the powers a
card applies consume or produce). The biggest count names the run when it's 3
or more; a close second (within 70%) makes it a pair; otherwise "Mixed".
Writes the archetype into pcs/index.json and prints a baseline per character
and archetype: runs, wins and the median curve at act ends and the finish.

The site uses SIGS and PAYOFFS too (build_site.py build_archetypes()), with its
own rule: every archetype the deck has 3+ non-starter cards of is a tag.

    python archetypes.py
"""
import json
import re
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


_TEXT = None


def text(c):
    """The card's rules text (card_data.json). Souls and losing your own HP aren't in
    power_data, but the text names them plainly: "Add a Soul", "Lose 2 HP"."""
    global _TEXT
    if _TEXT is None:
        _TEXT = json.loads((HERE.parents[1] / "card_data.json").read_text(encoding="utf-8"))
    return (_TEXT.get(c["id"]) or {}).get("desc", "")


# "Lose 2 HP", "lose 1 HP", "you lose HP", "you lost HP"; not "Enemy loses", "Osty loses",
# or Buffer's "would lose". Curses that cost HP (Regret, Bad Luck) aren't a build.
SELF_HP = re.compile(r"(?<!would )\blos[et]\b(?: \d+)? HP", re.I)


def self_damage(c):
    return c["type"] not in ("Curse", "Status") and bool(SELF_HP.search(text(c)))


def says(pattern, flags=0):
    """A test on the card's text, for what power_data misses: payoff cards that read a
    count (Ashen Strike, Bully, Time's Up), and powers it doesn't trace (Furnace's Forge)."""
    rx = re.compile(pattern, flags)
    return lambda c: c["type"] not in ("Curse", "Status") and bool(rx.search(text(c)))


# An archetype named here needs one of these cards as well as the count. Paying HP or
# applying Vulnerable is common (Bloodletting, Bash's Vulnerable are in nearly every
# Ironclad deck); a build pays off on it.
PAYOFFS = {
    "IRONCLAD": {
        "Self-damage": says(r"lost HP|whenever you lose HP", re.I),
        "Vulnerable": says(r"each Vulnerable|is Vulnerable|Vulnerable enem|apply Vulnerable|enemy's Vulnerable"),
    },
    "DEFECT": {
        "Status": says(r"create a Status|draw a Status|Status cards"),
    },
    "NECROBINDER": {
        "Ethereal": says(r"Ethereal card"),
    },
    "REGENT": {
        "Creation": says(r"\bcreated?\b"),
    },
}


_strength = says(r"Gain \d+ Strength(?! this turn)|for each Strength you have")
_shiv, _poison, _osty, _doom = says(r"\bShivs?\b"), says(r"\bPoison\b"), says(r"\bOsty\b|\bSummon\b"), says(r"\bDoom\b")
_discard = says(r"(?<!no longer )\b[Dd]iscard (\d+ cards?|your Hand)|discarded|\bSly\b")
_zero = says(r"0 ?⚡")

# Each character's builds: a card counts toward one when it makes the thing or pays
# off on it. The site tags a deck with every build it has 3+ of (see build_site.py).
SIGS = {
    "IRONCLAD": {
        "Strength": lambda c: applies(c, "Strength", "self") or any(e.get("power") == "Strength" for pw in c["applies"] for e in pc.turn_power(pw))
                              or _strength(c),
        # Exhausting other cards, or paying off on it (Ashen Strike, Evil Eye).
        "Exhaust": lambda c: bool(c["exhausts"]) or "uses:exhaust" in pw_tags(c) or "makes:exhaust" in pw_tags(c)
                             or (c["calc"] or ("",))[1:2] == ("exhaustPile",) or (c["twice"] or ("",))[0] == "exhaustedThisTurn",
        "Block": lambda c: block_scaling(c),
        "Self-damage": self_damage,
        "Vulnerable": says(r"\bVulnerable\b"),
    },
    "SILENT": {
        "Shiv": lambda c: bool(c["shivs"]) or "uses:shiv" in pw_tags(c) or _shiv(c),
        "Poison": lambda c: applies(c, "Poison", "enemy") or "uses:power:Poison" in pw_tags(c) or _poison(c),
        "Discard": lambda c: bool(c["discard"] or c["sly"] or c["discards_hand"]) or "uses:discard" in pw_tags(c) or _discard(c),
    },
    "DEFECT": {
        "Lightning": lambda c: channels(c, "Lightning") or says(r"\bLightning\b")(c),
        "Frost": lambda c: channels(c, "Frost") or says(r"\bFrost\b")(c),
        "Dark": lambda c: channels(c, "Dark") or says(r"\bDark\b")(c),
        "Zero-cost": lambda c: (c["type"] == "Attack" and c["cost"] == 0 and not c["x"]) or _zero(c),
        # Cards that put junk in the deck (Dazed, Burn, Void...) for the cards that feed on it.
        "Status": says(r"\bStatus\b|\b(Dazed|Wounds?|Burn|Void|Slimed)\b"),
    },
    "NECROBINDER": {
        "Doom": lambda c: applies(c, "Doom", "enemy") or bool(c["doom_kill"] or c["doom_from_dmg"]) or _doom(c),
        "Osty": lambda c: bool(c["osty"] or c["summon"]) or "uses:osty" in pw_tags(c) or _osty(c),
        "Souls": says(r"\bSouls?\b"),
        "Ethereal": says(r"\bEthereal\b"),
    },
    "REGENT": {
        "Stars": lambda c: bool(c["gain_stars"] or c["star_x"]) or c["stars"] > 0 or says("✦")(c),
        "Forge": lambda c: bool(c["forge"] or c["blade"]) or says(r"\bForge\b|Sovereign Blade")(c),
        # Cards that make cards (Colorless, Debris, Minions) and the ones that count them.
        "Creation": says(r"Colorless|\bcreated?\b|Debris|Minion"),
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
