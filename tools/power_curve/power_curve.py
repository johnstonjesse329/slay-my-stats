"""Prototype: a projected power curve for one run, floor by floor.

Rebuilds the deck and relics after every floor, then plays them in a small
Monte Carlo sim (shuffle, draw, spend energy greedily) to read off what the
deck does per turn: energy, cards seen, damage, block, and how much each
turn outgrows the last (scaling). Damage and block each get their own
all-in turns, so each shows what the hand can put out when that's the
plan, not what's left over from the other. Those four (damage, block,
energy, draw) are the deck's power; fights aren't replayed, since what a
fight costs depends on how it's played. Each fight is listed with the
encounter's HP and attack pattern (power_data.json) beside what happened
in the run (turns_taken, damage_taken).

Cards change mid-fight the way the game code says: Rampage and Thrash grow
(each fight on its own copy), Claw grows every copy, Armaments upgrades and
Primal Force transforms what's actually in hand, Stoke deals random cards
from the pool, and Howl from Beyond plays itself out of the exhaust pile.
HP you take on your own turn (Bloodletting, Inferno's burn) feeds Rupture
and Inferno, and counts toward a fight's damage taken.

Calculated cards count what they count at play (Body Slam's block,
Perfected Strike's Strikes, Finisher's Attacks this turn, Tear Asunder's
times hurt), conditional ones check their condition (Dismantle on a
Vulnerable foe, Pact's End's exhaust pile, Clash's all-Attack hand), and
powers change play the way their rules say: Strength for a turn (Setup
Strike) or off a foe for a turn (Piercing Wail, Mangle), Cruelty's bigger
Vulnerable, replays (One-Two Punch, Echo Form), free cards and Corruption's
exhausting Skills, Rage's and Juggernaut's hooks, Hellraiser, Aggression,
Stampede and Juggling. Anger, Infernal Blade and Headbutt add or move the
cards they say.

The Silent's mechanics play out too: Poison ticks (twice under Accelerant)
and lands from Envenom's hits, Corrosive Wave's draws and Bouncing Flask's
repeats; Serpent Form, Caltrops (Thorns), Speedster, Strangle and Panache
hit on their events (Serpent Form at its amount as each card starts, so
the card that applied it doesn't set it off). Shivs come from Blade Dance,
Infinite Blades and Storm of Steel's discards, Phantom Blades and Fan of
Knives change them, and Knife Trap plays the exhausted ones again. Sly
cards play when discarded (Master Planner makes Skills Sly), Well-Laid
Plans keeps the hand, Nightmare copies a card into next turn, Shadow Step
and Tracking multiply damage, Shadowmeld doubles block, Blur keeps it, and
Wraith Form's Intangible caps each hit at 1 while its Dexterity drains.

The Defect's orbs sit in a row of slots: channeling into a full row evokes
the oldest, passives go off at turn end (Plasma's at the start), Focus
adds to both, Dark stores what it evokes for and Glass wears down. Orb
damage is unpowered (no Strength or Vulnerable), and relics and powers
that channel, add slots or fire on evokes hook into the same row.

The Necrobinder's Osty soaks hits like block, grows with Summon, attacks
with the Osty cards and comes back when summoned again; Doom counts as
dealt and kills at the end of the foe's turn once its HP is down to it;
Souls are cards to draw later.

The Regent's stars are a second cost (pick() counts each as STAR_ENERGY),
and what fires on gaining or spending them plays out. Forge builds the
Sovereign Blade (one into the hand if none is about); Minions, copies and
cards made trigger Arsenal and Pillar of Creation.

Colorless cards: random cards from the run's own character, another
character or the colorless pool (Jackpot's 0-cost ones, Splash's free
Attack, Calamity's on each Attack), cards fetched from the draw pile
(Secret Weapon, Anointed, Seeker Strike, Stratagem on a shuffle), Mayhem's
and Nostalgia's top of the draw pile, Hidden Gem's Replay, Bolas back
next turn, Fasten's Defends, No Block after Panic Button, Rolling
Boulder's growing hit and The Bomb's countdown. The Gambit's lethal clause
is only a penalty on playing it; nobody dies in the sim.

Picking a card weighs its worth against its cost: draw at about 3 a card
(draw_worth: what the energy left can pay for), energy at about 5, stars
at STAR_ENERGY each, and a free draw card always goes first so the hand
is bigger before choosing.

    python power_curve.py <run file> <out.json>
"""
import json
import random
import sys
import time
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

WT = Path(__file__).resolve().parents[2]  # repo root: run.py, card/relic data, power_data.json
sys.path.insert(0, str(WT))
import run  # noqa: E402

CD = json.loads((WT / "card_data.json").read_text(encoding="utf-8"))
RD = json.loads((WT / "relic_data.json").read_text(encoding="utf-8"))
PD = json.loads((WT / "power_data.json").read_text(encoding="utf-8"))
SAMPLES, TURNS, SCALE_TURNS, MAX_PLAYS, MAX_TURN_PLAYS = 300, 5, 8, 40, 200
DEADLINE = None  # time.time() past which a run gives up (gamma_curves sets it)
BASE_ENERGY, BASE_DRAW, HAND_MAX = 3, 5, 10
CHAR_POOLS = ("IRONCLAD", "SILENT", "DEFECT", "NECROBINDER", "REGENT", "FOOL")
INF = float("inf")
SHIV = "CARD.SHIV"
EFFECT_VARS = {"Damage", "Block", "Cards", "Energy", "Shivs", "Repeat"}
# Powers the sim knows how to play out. Self: a running stat. Enemy: a
# per-foe counter. Anything else a card applies is listed as unmodelled.
SELF_POWERS = {"Strength": "str", "Dexterity": "dex", "Accuracy": "acc", "Vigor": "vigor",
               "Afterimage": "afterimage", "NoxiousFumes": "fumes", "Barricade": "barricade",
               "Unmovable": "unmovable",
               # HP loss on your turn -> Strength / a hit on every foe
               "Rupture": "rupture", "Inferno": "inferno",
               # Vulnerable foes' attacks halved; each hit taken hits back
               "Colossus": "colossus", "FlameBarrier": "flame",
               # Caltrops' hit back on every attack taken (Flame Barrier's,
               # but for the fight); Wraith Form's hits capped at 1
               "Thorns": "thorns", "Intangible": "intangible",
               # Orbs' passives and evokes
               "Focus": "focus",
               # The Regent's Sovereign Blade reads these: Parry's block after
               # each swing, Seeking Edge's swing at every foe
               "Parry": "parry", "SeekingEdge": "seeking"}
# Piercing Wail's and Mangle's Strength down come in as temp rules (see rules).
ENEMY_POWERS = {"Poison": "poison", "Weak": "weak", "Vulnerable": "vuln",
                # The Necrobinder's: Doom kills a foe at the end of its turn once
                # its HP is down to it; Debilitate doubles Vulnerable and Weak;
                # Sic 'Em summons on each Osty hit; Hang multiplies Hang's hits;
                # Oblivion dooms it for each card played after
                "Doom": "doom", "Debilitate": "debil", "SicEm": "sicem", "Hang": "hang", "Oblivion": "oblivion",
                # The Regent's Conqueror: the Sovereign Blade hits it for double
                "Conqueror": "conq"}
# Powers that do nothing in a fight (Royalties: gold after it).
NO_COMBAT = {"Royalties"}
BLADE = "CARD.SOVEREIGN_BLADE"
STAR_ENERGY = 0.5  # a star's cost next to energy's when picking a card (a star ~2.5 of value, an energy ~5)
# The debuffs Sleight of Flesh fires on (temporary ones like Enfeebling
# Touch's don't count).
DEBUFFS = {"Poison", "Weak", "Vulnerable", "Debilitate"}
SOUL, HANG = "CARD.SOUL", "CARD.HANG"
# Inferno and Crimson Mantle burn you at the start of every turn, 1 HP more
# for each copy played.
TURN_BURNS = ("Inferno", "CrimsonMantle")
POOL_FACE = {}  # (pool, upgraded, focus) -> a random card's average worth
# What a power feeds, so an all-in turn only sets up what it's going for.
DMG_POWERS = {"Strength", "Accuracy", "Vigor", "NoxiousFumes", "Poison", "Vulnerable", "Rupture", "Inferno", "Thorns",
              "Focus", "Doom", "Hang", "Debilitate", "Oblivion", "SeekingEdge", "Conqueror"}
BLOCK_POWERS = {"Dexterity", "Afterimage", "Barricade", "Unmovable", "Intangible", "Focus", "SicEm", "Parry"}


ECONOMY = ("handDraw", "triggers", "maxEnergy", "noOtherDraws", "atStart", "atStartGate")
# How a power changes play (see extract_power_data.power_rules).
RULES = ("temp", "vulnBonus", "replays", "free", "exhaustsType", "fromDiscard", "playsDrawn", "endPlays", "copiesNth",
         # The Silent's: Tracking, Shadow Step's Double Damage, Shadowmeld, Blur,
         # Well-Laid Plans, Infinite Blades, Nightmare, Phantom Blades, Strangle,
         # Master Planner, Accelerant, Fan of Knives
         "weakBonus", "dmgMult", "blockDoubles", "keepsBlock", "keepsHand", "turnMakes", "clonesNextTurn",
         "firstTagBonus", "retainsTag", "hurtsOnPlay", "keywordOnPlay", "poisonTicks", "aoeTag",
         # The Defect's: Buffer, One for All, Feral, Creative AI
         "buffer", "zeroCostBonus", "returnsZeroCost", "turnMakesRandom",
         # The Necrobinder's: Borrowed Time, Call of the Void, Calcify, Lethality,
         # Necro Mastery, Reaper Form
         "costUp", "turnMakesEthereal", "ostyBonus", "firstAttackBonus", "ostyLossHits", "doomPerDamage",
         # The Regent's: Monologue, Orbit, Pale Blue Dot, Reflect, Monarch's Gaze,
         # Foregone Conclusion, Sword Sage
         "strPerPlay", "energyPer", "drawAfterAttacks", "reflect", "hitStrDown", "handDrawOnce", "bladeReplays",
         # Colorless: Fasten, No Block, Mayhem, Nostalgia, Rolling Boulder, The
         # Bomb, Stratagem, Calamity, Entropy, The Gambit
         "tagBlock", "noCardBlock", "turnPlaysTop", "topsFirst", "turnAoeGrows", "bomb", "shuffleFetch",
         "attackMakesRandom", "turnTransforms", "gambit")
DMG_RULES = {"vulnBonus", "fromDiscard", "playsDrawn", "endPlays", "copiesNth", "weakBonus", "dmgMult", "turnMakes",
             "firstTagBonus", "hurtsOnPlay", "poisonTicks", "aoeTag", "zeroCostBonus", "returnsZeroCost",
             "ostyBonus", "firstAttackBonus", "ostyLossHits", "doomPerDamage", "strPerPlay", "reflect", "bladeReplays",
             "turnAoeGrows", "bomb", "attackMakesRandom"}
TEMP_STATS = {"Strength": "str", "Dexterity": "dex", "Focus": "focus"}
# Orbs (OrbModel and the Orbs folder): what a passive and an evoke are worth
# before Focus. Dark's evoke grows by its passive; Glass's passive loses 1
# each time it goes off and its evoke is twice the passive; Plasma (energy)
# takes no Focus.
ORB_TYPES = ("Lightning", "Frost", "Dark", "Plasma", "Glass")
ORB_PASSIVE = {"Lightning": 3, "Frost": 2, "Dark": 6, "Plasma": 1, "Glass": 4}
ORB_EVOKE = {"Lightning": 8, "Frost": 5, "Dark": 6, "Plasma": 2}
MAX_SLOTS = 10
DEFECT_SLOTS = 3
STATUS_COST = {"BURN": 4, "VOID": 4}  # a made status's dilution; the rest are 2
BURN, VOID = "CARD.BURN", "CARD.VOID"
ORB_TICKS = 2  # passives a channeled orb is valued at: this turn's end and the next


@lru_cache(None)
def economy(pw):
    """A self power's draw and energy side: extra hand draw (Tools of the
    Trade, Draw Cards Next Turn), hooks (Vicious, Dark Embrace, Feel No
    Pain), max energy (Demesne), No Draw, a card given up each turn."""
    p = PD["powers"].get(pw, {})
    return {k: p[k] for k in ECONOMY if k in p}


@lru_cache(None)
def rules(pw):
    """How a power changes play: Strength or Dexterity for the turn (Setup
    Strike, Piercing Wail), Cruelty's Vulnerable bonus, replays (One-Two
    Punch, Echo Form), free cards (Corruption, Void Form), Corruption's
    exhausting Skills, Aggression, Hellraiser, Stampede, Juggling."""
    p = PD["powers"].get(pw, {})
    return {k: p[k] for k in RULES if k in p}


@lru_cache(None)
def turn_power(pw):
    """A self power that acts every turn while it's up (Demon Form, Plating):
    its effects that give the power's own stack, or summon (Invoke's Summon
    Next Turn). Reverts and the like (Temporary Strength, Wraith Form) are
    left out."""
    if pw in SELF_POWERS:
        return ()
    return tuple(e for e in PD["powers"].get(pw, {}).get("turnEffects", []) if e.get("stack") or "summon" in e)


@lru_cache(None)
def power_var(pw, name):
    """A power's own number, off the card that applies it (Danse Macabre's
    Energy: the cost a card needs to set it off)."""
    k = next((k for k, p in PD["cards"].items() if pw in p.get("applies", {})), None)
    return CD.get(k, {}).get("vars", {}).get(name, 1)


@lru_cache(None)
def axes(pw):
    out = {a for a, group in (("dmg", DMG_POWERS), ("block", BLOCK_POWERS)) if pw in group}
    for e in turn_power(pw):
        if e.get("sign", 1) < 0 or (e.get("power") == "Doom" and e.get("side") == "self"):
            continue  # Wraith Form's Dexterity lost, Neurosurge's Doom on you
        if "block" in e or "summon" in e or e.get("power") in BLOCK_POWERS:
            out.add("block")
        if "damage" in e or e.get("power") in DMG_POWERS:
            out.add("dmg")
        if "power" in e:  # Shadow Step's Double Damage next turn
            out |= axes(e["power"])
        if "energy" in e or "stars" in e:  # Outmaneuver, Invoke, Genesis: energy or stars next turn feeds either
            out |= {"dmg", "block"}
        if "forge" in e:  # Furnace: the Sovereign Blade hits harder
            out.add("dmg")
    # More cards or energy feed whatever the turn is going for.
    eco = economy(pw)
    hd = eco.get("handDraw")
    if (hd is not None and not hd.get("less")) or eco.get("maxEnergy", 0) > 0 \
            or any("draw" in e or "energy" in e or "stars" in e for e in eco.get("triggers", [])):
        out |= {"dmg", "block"}
    if any("block" in e or "summon" in e for e in eco.get("triggers", [])):  # Osty's HP soaks hits like block
        out.add("block")
    if any("damage" in e or "poison" in e or "strength" in e for e in eco.get("triggers", [])):
        out.add("dmg")  # Arsenal: Strength for each card made
    r = rules(pw)
    temp = r.get("temp", {})
    if temp.get("stat") in TEMP_STATS:
        # Strength down on a foe is block: it hits for less.
        out.add("block" if temp["sign"] < 0 or temp["stat"] == "Dexterity" else "dmg")
    if r.keys() & DMG_RULES:
        out.add("dmg")
    if r.keys() & {"blockDoubles", "keepsBlock", "buffer", "hitStrDown", "tagBlock"}:  # Monarch's Gaze: foes hit for less
        out.add("block")
    if r.keys() & {"replays", "free", "keepsHand", "clonesNextTurn", "keywordOnPlay", "turnMakesRandom",
                   "energyPer", "drawAfterAttacks", "handDrawOnce",  # Orbit, Pale Blue Dot, Foregone Conclusion
                   "turnPlaysTop", "topsFirst", "shuffleFetch", "turnTransforms"}:  # Mayhem, Nostalgia, Stratagem, Entropy
        out |= {"dmg", "block"}
    for e in orb_hooks(pw):
        # Coolant blocks; Hailstorm, Thunder and Consuming Shadow's evokes hit
        # (its Dark orbs); the orbs Storm, Spinner and Lightning Rod channel
        # and Loop's passives do both.
        out |= {"block"} if "blockPerUnique" in e else {"dmg"} if e.keys() & {"aoe", "damage", "evokeLast"} \
            else {"dmg", "block"}
    return frozenset(out)


@lru_cache(None)
def orb_hooks(pw):
    """What a power does with orbs (see extract_power_data.orb_hooks)."""
    return tuple(PD["powers"].get(pw, {}).get("orbHooks", []))


@lru_cache(None)
def power_pool(pw):
    """The character pool of the card that applies pw (Creative AI's: the Defect's)."""
    return next((CD.get(k, {}).get("pool") for k, p in PD["cards"].items() if pw in p.get("applies", {})), None)


def modelled(pw):
    r = rules(pw)
    return pw in SELF_POWERS or pw in ENEMY_POWERS or pw in NO_COMBAT or bool(turn_power(pw)) or bool(economy(pw)) \
        or bool(orb_hooks(pw)) \
        or bool(r.keys() - {"temp"}) or r.get("temp", {}).get("stat") in TEMP_STATS


def bound(x, v):
    """A turn bound that's a literal or a relic var (Ring of the Drake's Turns)."""
    return int(v.get(x, 1)) if isinstance(x, str) else x


def orb_ops(ops, v, up):
    """A card's orb ops (see extract_power_data.orb_ops) with their numbers
    read off its vars: n orbs channeled, evokes of the next orb (Dualcast's
    2, Multi-Cast's X), passives of every orb of a type (Darkness, Tesla
    Coil) or slots; times is how often the op runs (Chaos' Repeat, Chill's
    one per foe, Shatter's one per orb, Tempest's X). Upgrades add upPlus
    to whichever of them is X, or swap n for upN; an up op is upgrade-only."""
    out = []
    for o in ops:
        if o.get("up") and not up:
            continue
        n, times = o["n"], o.get("times", 1)
        if isinstance(n, str) and n != "X":
            n = -int(v.get(n[1:], 1)) if n.startswith("-") else int(v.get(n, 1))
        if isinstance(times, str) and times not in ("X", "enemies", "orbs", "calc"):
            times = int(v.get(times, 1))
        if up:
            n = o.get("upN", n)
            plus = o.get("upPlus", 0)
        else:
            plus = 0
        out.append({"op": o["op"], "orb": o.get("orb"), "n": n, "times": times, "plus": plus,
                    "on_target": bool(o.get("onTarget"))})
    return out


_cards = {}


def fresh(c):
    """A card that changes as it's played (Rampage, Thrash) or drawn
    (Kingly Kick, Kingly Punch) gets its own copy per fight, so one copy's
    growth stays on that copy."""
    return dict(c) if c["grows"] or c["on_draw"] else c


@lru_cache(None)
def pool(name, kind=None, zero=False):
    """The cards a random card of a character's pool comes from (Stoke), or
    of one type in it (Infernal Blade's Attack), or the 0-cost ones
    (Jackpot). "others" is every character's pool but name's own after a
    colon (Splash: "others:IRONCLAD")."""
    names = set(CHAR_POOLS) - {name[7:]} if name.startswith("others:") else {name}
    return tuple(k for k, d in CD.items() if d.get("pool") in names and d.get("rarity") in ("Common", "Uncommon", "Rare")
                 and kind in (None, d.get("type")) and (not zero or (d.get("energy") == 0 and not d.get("costsX"))))


def card(cid, up=False):
    key = (cid, up)
    if key in _cards:
        return _cards[key]
    d, p = CD.get(cid, {}), PD["cards"].get(cid, {})
    v = dict(d.get("vars", {}))
    if up:
        v.update(d.get("varsUpgraded", {}))
    kw = set((d.get("keywordsUpgraded") if up else d.get("keywords")) or [])
    cost = d.get("energyUpgraded", d.get("energy", 1)) if up else d.get("energy", 1)
    does = set(p.get("does", []))
    hits = p.get("hits", 1)
    per_exhausted = hits == "exhausted"  # Fiend Fire: once per card it exhausted
    if isinstance(hits, str):
        hits = 1 if per_exhausted else int(v.get(hits, 1))
    # A power's amount is what the card passes (a var or a literal: Relax's
    # Cards for Draw Cards Next Turn), else its `XPower` var, else the card's
    # one other number (Noxious Fumes' PoisonPerTurn, Piercing Wail's StrengthLoss).
    leftover = [k for k, x in v.items() if k not in EFFECT_VARS and isinstance(x, (int, float))]
    applies = {}
    for pw, side in p.get("applies", {}).items():
        a = p.get("amounts", {}).get(pw)
        if a == "block":  # Prolong: your block as it's played
            applies[pw] = (side, "block")
            continue
        amt = v.get(a, v.get(f"{a}Power")) if isinstance(a, str) else a
        if amt is None:
            amt = v.get(f"{pw}Power")
        if amt is None and len(leftover) == 1:
            amt = v[leftover[0]]
        if amt is None and d.get("costsX"):  # Malaise: X Weak
            applies[pw] = (side, "X")
            continue
        applies[pw] = (side, (amt or 1) * int(v.get(p.get("applyRepeat"), 1)))  # Bouncing Flask: Repeat times
    # Strength lost rather than gained (see extract_power_data's lowers): off
    # you (Friendship, Shared Fate), the target (Shared Fate, Malaise) or
    # every foe (Resonance, which still gives you its Strength). A number is
    # a literal, a var or X.
    lowers = {s: n if isinstance(n, int) or n == "X" else int(v.get(n, 1))
              for s, n in p.get("lowers", {}).get("Strength", {}).items()}
    side = applies.get("Strength", (None,))[0]
    if lowers and (side in lowers or (side == "both" and "self" in lowers)
                   or (side == "enemy" and "enemies" in lowers)):
        applies.pop("Strength")
    # Cards drawn: the Cards var, or a literal / other var, or up to a full hand (Scrawl).
    dn = p.get("drawN", "Cards")
    draw = 0
    if "draw" in does:
        draw = dn if dn == "fullHand" else int(v.get(dn, 0) if isinstance(dn, str) else dn)
    # Dominate's Strength is the target's Vulnerable, not a flat amount.
    str_per_vuln = v.get("StrengthPerVulnerable", 0)
    if str_per_vuln:
        applies.pop("Strength", None)
    # A calculated card's bonus per stack of a power the sim tracks (Bully:
    # per Vulnerable on the target; Expect a Fight: per Strength).
    ps = p.get("perStack")
    per = None
    if ps and ps["power"] in (ENEMY_POWERS if ps["on"] == "target" else SELF_POWERS):
        per = (ps["power"], ps["on"], v.get("ExtraDamage") or v.get("CalculationExtra") or 1)
    attack = d.get("type") == "Attack"
    shiv = cid == SHIV
    # A calculated number (see extract_power_data.calculated): damage, block
    # or hits plus Extra for each of something counted at play (Body Slam's
    # block, Perfected Strike's Strikes, Finisher's Attacks this turn).
    calc = p.get("calc")
    if calc:
        extra = v.get("ExtraDamage", v.get("CalculationExtra", 1))
        # Precise Cut loses Extra for each other card in hand.
        calc = (calc["to"], calc["of"], -extra if calc.get("neg") else extra, calc.get("plus", 0), v.get("CalculationBase", 0))
    # More hits or block when a condition holds (Dismantle on a Vulnerable
    # foe, Spite after losing HP, Evil Eye after an exhaust).
    twice = p.get("twiceIf")
    # Cards moved between piles (see extract_power_data.pile_moves): counts
    # are a literal, "all" or a var.
    num = lambda n: n if isinstance(n, int) or n == "all" else int(v.get(n, 1))  # noqa: E731
    fd, pf = p.get("fromDiscard"), p.get("playsFrom")
    if twice:
        n = twice["times"]
        # Death's Door: Repeat + 1 times
        twice = (twice["if"], (int(v.get(n, 2)) if isinstance(n, str) else n) + twice.get("plus", 0), twice["to"])
    # Cards made into piles that aren't statuses (Capture Spirit's Souls):
    # n is a literal, a var or X.
    makes = [(x["id"], x["pile"], x["n"] if isinstance(x["n"], int) or x["n"] == "X" else int(v.get(x["n"], 1)))
             for x in p.get("puts", []) if CD.get("CARD." + x["id"], {}).get("type") != "Status"]
    c = {"orb_ops": orb_ops(p.get("orbOps", []), v, up)}
    c.update({
        "id": cid, "title": d.get("title", cid), "type": d.get("type"), "cost": cost,
        "x": d.get("costsX", False),
        # Multiplayer-only cards (Tank, Constellation) do nothing in a solo
        # fight, nor a power that only pays out after it (Royalties' gold).
        "dead": "Unplayable" in kw or d.get("type") in ("Status", "Curse") or bool(p.get("multiplayerOnly"))
        or (d.get("type") == "Power" and bool(p.get("applies")) and set(p["applies"]) <= NO_COMBAT),
        "sly": "Sly" in kw, "exhaust": "Exhaust" in kw or shiv,
        # Every attack hits for its Damage (Osty's for his), or a calculated
        # one's base (Bully's 4), so Strength lands on all of them.
        "dmg": (v.get("Damage") or v.get("OstyDamage") or v.get("CalculationBase", 0)) if attack else 0,
        # The Necrobinder's: Osty's attacks (no Strength, nothing if he's
        # dead), HP summoned to him, Sacrifice and Bone Shards killing him,
        # End of Days' Doom kill, Blight Strike's Doom off its damage, Flatten
        # free after an Osty attack, Banshee's Cry cheaper per Ethereal card
        # played, Souls made.
        "osty": "OstyAttack" in p.get("tags", []), "summon": int(v.get("Summon", 0)) if "summon" in does else 0,
        "kills_osty": bool(p.get("killsOsty")), "doom_kill": bool(p.get("doomKill")),
        "doom_from_dmg": bool(p.get("doomFromDamage")), "free_after_osty": bool(p.get("freeAfterOsty")),
        "cost_down_eth": int(v.get(p["costDownEthereal"], 0)) if p.get("costDownEthereal") else 0,
        "lowers": lowers, "makes_cards": makes,
        "hits": max(1, int(hits)), "aoe": bool(p.get("aoe")) and not shiv, "random": bool(p.get("random")),
        "splash": bool(p.get("splash")), "per": per, "str_per_vuln": str_per_vuln,
        "autoplay": "autoplay" in does, "autoplay_exhausts": bool(p.get("autoplayExhausts")),
        "block": (v.get("Block") or v.get("CalculationBase", 0)) if "block" in does else 0,
        "draw": draw,
        # Scrape's discard is of what it drew, not a pick from the hand.
        "discard": int(v.get("Cards", 1)) if "discard" in does and not p.get("drawnDiscard") and not p.get("discardsHand") else 0,
        # Shadow Step and Storm of Steel discard the whole hand; Storm of Steel
        # makes a Shiv for each card discarded.
        "discards_hand": bool(p.get("discardsHand")), "per_discarded": p.get("makesPerDiscarded"),
        # Echoing Slash goes again on a kill; Knife Trap plays every Shiv in the
        # exhaust pile at the target.
        "repeat_on_kill": bool(p.get("repeatOnKill")), "plays_exhausted": p.get("playsExhausted"),
        # Drum of Battle's energy comes when it's exhausted, not when it's played.
        "energy": v.get("Energy", 0) if "energy" in does and "When this card is Exhausted" not in d.get("desc", "") else 0,
        "exhaust_energy": v.get("Energy", 0) if "When this card is Exhausted" in d.get("desc", "") else 0,
        "shivs": int(v.get("Shivs") or v.get("Cards", 1)) if "SHIV" in p.get("makes", []) and not shiv
            and not p.get("makesPerDiscarded") else 0,
        "applies": applies, "shiv": shiv, "attack": attack,
        "retain": "Retain" in kw, "ethereal": "Ethereal" in kw, "innate": "Innate" in kw,
        # How it draws past a flat count: Pillage keeps going while it draws
        # Attacks; FTL, Impatience, Restlessness and Fetch only on a condition
        # (see Combat.holds); Expertise retains what it drew, Scrape discards
        # the drawn cards that cost energy, Escape Plan blocks if it drew a Skill.
        "draw_while": p.get("drawWhile"), "draw_if": p.get("drawIf"), "energy_if": p.get("energyIf"),
        "play_max": v.get("PlayMax", 0), "drawn_retain": bool(p.get("drawnRetain")),
        "drawn_discard": p.get("drawnDiscard"), "block_if_drawn": p.get("blockIfDrawn"),
        # Other cards it exhausts (True Grit picks once upgraded), and Second
        # Wind's block / Fiend Fire's hits per card exhausted.
        "exhausts": "pick" if up and p.get("exhaustsUp") else p.get("exhausts"),
        "exhaust_n": int(v.get("Cards", 1)),
        "block_per": p.get("blockPer"), "hits_per": "exhausted" if per_exhausted else None,
        "up": up, "upable": not up and d.get("maxUpgradeLevel", 0) > 0, "pool": d.get("pool"),
        "hp_loss": v.get("HpLoss", 0) if p.get("losesHp") else 0,  # Bloodletting, Hemokinesis: HP lost on your own turn
        # What it changes for the rest of the fight (see extract_power_data's
        # in_combat_changes): Rampage's and Thrash's own damage, every Claw's,
        # Molten Fist doubling Vulnerable, Armaments' upgrades, Primal Force's
        # Giant Rocks, Stoke's random cards, Howl from Beyond out of the
        # exhaust pile.
        "grows": v.get(p["grows"], 0) if p.get("grows") not in (None, "exhausted") else p.get("grows"),
        "grows_all": v.get(p["growsAll"], 0) if p.get("growsAll") else 0,
        "doubles": p.get("doubles"),
        "upgrades": p.get("upgradesUp", p.get("upgrades")) if up else p.get("upgrades"),
        "transforms": p.get("transforms"), "generates": p.get("generates"), "from_exhaust": bool(p.get("fromExhaust")),
        "calc": calc, "twice": twice, "only_if": p.get("onlyIf"), "applies_if": p.get("appliesIf", {}),
        "playable_if": p.get("playableIf"), "tags": set(p.get("tags", [])),
        # Anger's copy, Infernal Blade's free random Attack, Headbutt's card
        # back on top, Stomp's cost down per Attack played this turn.
        "copy_to": p.get("copyTo"), "random_free": p.get("randomFree"), "discard_top": bool(p.get("discardToTop")),
        # Adaptive Strike's copy costs 0; the statuses it makes and where
        # (Fight Through: 2 Wounds into the discard pile).
        "copy_free": bool(p.get("copyFree")),
        "puts": [(x["id"], x["pile"], x["n"]) for x in p.get("puts", []) if CD.get("CARD." + x["id"], {}).get("type") == "Status"],
        "cost_down": p.get("costDown"),
        # Hologram's / Dredge's picks out of the discard pile (All for One:
        # every 0-cost card there), Uproar's random Attack autoplayed from the
        # draw pile (Beat Down: Cards of them from the discard pile), Drain
        # Power's upgrades there, Double Energy, Reboot's hand shuffled back.
        "from_discard": fd and dict(fd, n=num(fd["n"])), "plays_from": pf and dict(pf, n=num(pf["n"])),
        "ups_discard": num(p["upgradesDiscard"]) if p.get("upgradesDiscard") else 0,
        "doubles_energy": bool(p.get("doublesEnergy")), "hand_to_draw": bool(p.get("handToDraw")),
        # Whether it hits / blocks at all: Body Slam's and Stack's base is 0.
        "hitter": attack and ("attack" in does or bool(v.get("Damage"))),
        "blocker": "block" in does,
        # The Regent's: the stars it costs (-1: none; Stardust's X: all of
        # them) and gives (Knockout Blow's only on a kill), Forge, the Sovereign
        # Blade itself and Summon Forth fetching it.
        "stars": d.get("stars", -1), "star_x": bool(d.get("starsX")),
        "gain_stars": int(v.get("Stars", 0)) if "stars" in does else 0,
        "stars_if_kill": bool(p.get("starsIfKill")),
        "forge": int(v.get(p["forge"], 0)) if p.get("forge") else 0,
        "blade": cid == BLADE, "blade_to_hand": bool(p.get("bladeToHand")),
        # Cards it turns into Minions (Begone, Guards, Charge) or makes from
        # the colorless pool (Bundle of Joy, Quasar), Heirloom Hammer's copies
        # of colorless cards in hand, Glimmer's cards put back on top, Decisions
        # Decisions' Skill played again, where it goes after play (Particle
        # Wall: back to hand; Shining Strike: on top of the draw pile).
        "turns_into": p.get("turnsInto") and dict(p["turnsInto"], n=num(p["turnsInto"]["n"])
                                                 if p["turnsInto"]["n"] != "any" else "all"),
        "makes_random": p.get("makesRandom") and dict(p["makesRandom"], n=num(p["makesRandom"]["n"])),
        "clones": p.get("clones") and dict(p["clones"], n=num(p["clones"]["n"])),
        "put_back": num(p["putBack"]) if p.get("putBack") else 0,
        "plays_skill": num(p["playsSkill"]) if p.get("playsSkill") else 0,
        "result_pile": p.get("resultPile"),
        # Make It So back to hand every few Skills, Bombardment out of the
        # exhaust pile each turn, I Am Invincible played off the top at turn
        # end, Void Form ending the turn, Kingly Kick / Punch growing as drawn,
        # Heavenly Drill's double hits from X Energy up.
        "returns_on_skills": p.get("returnsOnSkills") and dict(p["returnsOnSkills"],
                                                               every=num(p["returnsOnSkills"]["every"])),
        "from_exhaust_start": bool(p.get("fromExhaustStart")), "autoplays_top": bool(p.get("autoplaysTop")),
        "ends_turn": bool(p.get("endsTurn")),
        "on_draw": p.get("onDraw") and {k: x if isinstance(x, int) else int(v.get(x, 1)) for k, x in p["onDraw"].items()},
        "x_double": int(v.get(p["xDoubleAt"], 0)) if p.get("xDoubleAt") else 0,
        # Colorless: Fisticuffs blocks the HP its hits took, Bolas comes back
        # the turn after, Wish / Secret Technique / Seeker Strike / Anointed
        # pick cards out of the draw pile, Hidden Gem gives a draw-pile card
        # replays, The Bomb's blast.
        "block_from_dmg": bool(p.get("blockFromDamage")), "returns_next_turn": bool(p.get("returnsNextTurn")),
        "fetches": p.get("fetches") and dict(p["fetches"], n=p["fetches"]["n"] if p["fetches"]["n"] == "fullHand"
                                             else num(p["fetches"]["n"]),
                                             choose=p["fetches"].get("choose") and num(p["fetches"]["choose"])),
        "replays_draw": int(v.get(p["replaysDrawCard"], 1)) if p.get("replaysDrawCard") else 0,
        "bomb_dmg": int(v.get(p["bombDamage"], 0)) if p.get("bombDamage") else 0,
    })
    if c["makes_random"] and c["makes_random"].get("choose"):
        c["makes_random"]["choose"] = num(c["makes_random"]["choose"])
    c["helps"] = set().union(*(axes(pw) for pw in applies))
    c["unmodelled"] = [pw for pw in applies if not modelled(pw)]
    c["modelled"] = c["dead"] or any(c[k] for k in ("hitter", "blocker", "draw", "discard", "energy", "shivs", "autoplay",
                                                    "exhausts", "upgrades", "transforms", "copy_to", "random_free",
                                                    "discard_top", "discards_hand", "plays_exhausted", "orb_ops", "puts",
                                                    "from_discard", "plays_from", "ups_discard", "doubles_energy",
                                                    "hand_to_draw", "summon", "kills_osty", "lowers",
                                                    "makes_cards", "gain_stars", "forge", "blade_to_hand",
                                                    "turns_into", "makes_random", "clones", "plays_skill",
                                                    "block_from_dmg", "returns_next_turn", "fetches", "replays_draw",
                                                    "bomb_dmg")) \
        or any(modelled(pw) for pw in applies)
    _cards[key] = c
    return c


def fires(e, n, v, phase=0):
    """Whether a relic effect fires on turn n: its turn gate (on / until /
    from), then a Turns var for every-Nth-turn relics (Happy Flower,
    Pendulum), counted from phase (where the relic's counter stood)."""
    if "on" in e:
        return n == bound(e["on"], v)
    if "until" in e:
        return n <= bound(e["until"], v)
    return n >= e.get("from", 1) and (n + phase) % int(v.get(e.get("every", "Turns"), 1)) == 0


def burst(e, v):
    """A one-off or periodic relic kick (Horn Cleat turn 2, Candelabra, Happy
    Flower) rather than a steady per-turn effect."""
    return "on" in e or "until" in e or int(v.get(e.get("every", "Turns"), 1)) > 1


def relic_effects(rids, elite=False):
    """What a relic set does in a fight; elite: the fight is an elite one
    (Booming Conch)."""
    r = {"max_energy": [], "hand": [], "trig": [], "start": [], "no_other_draws": False, "elite": elite,
         "turn": [], "per_attacks": [], "discard_dmg": 0, "discard_block": 0, "hp_red": 0,
         # Orbs: Cracked Core's first Lightning, Emotion Chip, Metronome;
         # Gold-Plated Cables' extra passive; Infused Core's Lightning bonus
         "orb": [], "cables": 0, "orb_bonus": Counter(),
         # The Regent's: Brilliant Scarf's free Nth card a turn, Vitruvian
         # Minion's doubled Minions, Orange Dough's colorless cards to open with
         "nth_free": 0, "tag_mult": None, "open_makes": []}
    for rid in rids:
        p, v = PD["relics"].get(rid, {}), RD.get(rid, {}).get("vars", {})
        if "nthFree" in p:
            r["nth_free"] = int(v.get(p["nthFree"], 5))
        if "tagMult" in p:
            r["tag_mult"] = (p["tagMult"]["tag"], p["tagMult"]["by"])
        if "openMakes" in p:
            r["open_makes"].append((p["openMakes"]["pool"], int(v.get(p["openMakes"]["n"], 1))))
        r["orb"] += [(e, v) for e in p.get("orbHooks", [])]
        r["cables"] += p.get("firstPassiveExtra", 0)
        if "orbBonus" in p:
            r["orb_bonus"][p["orbBonus"]["orb"]] += int(v.get(p["orbBonus"]["by"], 1))
        if "maxEnergy" in p:
            r["max_energy"].append((p["maxEnergy"], v.get("Energy", 1)))
        if "handDraw" in p:
            r["hand"].append((p["handDraw"], v))
        r["trig"] += [(e, v) for e in p.get("triggers", [])]
        if "atStart" in p:
            r["start"].append((p["atStart"], p.get("atStartGate", {}), 1))
        r["no_other_draws"] |= bool(p.get("noOtherDraws"))
        r["turn"] += [(e, v) for e in p.get("turnEffects", []) if elite or not e.get("elite")]
        cons = p.get("consumes", [])
        if "attacks" in cons:
            r["per_attacks"].append((int(v.get("Cards", 3)), p.get("produces", []), v))
        if "discard" in cons:
            r["discard_dmg"] += v.get("Damage", 0)
            r["discard_block"] += v.get("Block", 0)
        for m in p.get("mods", []):
            if m["stat"] == "hpLost" and m["op"] == "add":
                r["hp_red"] += v.get("HpLossReduction", 1)
    return r


class Combat:
    _cc = None  # costs while pick() weighs the hand: nothing changes them meanwhile

    def __init__(self, deck, rel, foes, rng, steady=False, focus=None, slots=0):
        # steady: leave out one-off relic kicks, so turn-by-turn growth is the deck's own.
        # focus: "dmg" or "block" plays all-in on that and nothing else; None plays
        # a real fight, blocking what's coming and hitting with the rest.
        # slots: the character's orb slots (the Defect's 3; others start with none).
        self.rng, self.rel, self.steady, self.focus = rng, rel, steady, focus
        self.base_slots = self.slots = slots
        self.orbs = []          # oldest first: {"t": type, "ev": Dark's evoke, "g": Glass's passive}
        self.channeled = Counter()  # orbs channeled this fight, all and by type (Metronome, Voltaic)
        self.orbp = Counter()   # powers that act on orbs, by stack (see orb_hooks)
        self.lost_last = False  # HP lost last turn (Emotion Chip)
        self.orb_used = [0] * len(rel["orb"])  # relic orb hooks' uses this fight (Metronome)
        self.pile = [fresh(c) for c in deck]
        rng.shuffle(self.pile)
        self.pile.sort(key=lambda c: c["innate"])  # Innate cards on top: the opening hand
        self.hand, self.used, self.gone = [], [], []  # gone: the exhaust pile
        self.grown = Counter()  # every Claw's extra damage, by card id
        self.foes = [{"hp": f["hp"], "moves": f["moves"], "i": 0,
                      "poison": 0, "weak": 0, "vuln": 0, "strdown": 0, "strangle": 0,
                      # str: Strength lost for the fight (Shared Fate, Malaise)
                      "doom": 0, "debil": 0, "sicem": 0, "hang": 0, "oblivion": 0, "str": 0,
                      # conq: Conqueror (the Sovereign Blade hits it double); hits_t: times hit this turn
                      "conq": 0, "hits_t": 0} for f in foes]
        # The Regent's stars (they keep from turn to turn), Forge put on the
        # Sovereign Blade, cards made this fight (Supermassive) and energy
        # spent toward Orbit's next energy. Stars matter only with something
        # to spend them on: a star gained is worth what the deck's sinks pay
        # per star (The Smith's 30 Forge for 4, Falling Star's 8 for 2), up to
        # the dearest sink's price banked.
        self.stars = self.forged = self.generated = self.orbit = 0
        sinks = [c for c in deck if (c["stars"] > c["gain_stars"]) or c["star_x"]]  # not Royal Gamble's 5 for 9
        self.star_sinks = bool(sinks)
        per = [max(0, c["dmg"] * c["hits"] + c["block"] + c["forge"] * 1.5 + 4 * bool(c["applies"])
                   - 5 * max(0, c["cost"])) / (c["stars"] if c["stars"] > 0 else 1) for c in sinks]
        self.star_val = min(5, max(0.5, sum(per) / len(per))) if per else 0.5
        self.star_cap = max((c["stars"] if c["stars"] > 0 else 5 for c in sinks), default=0)
        self.osty = {"hp": 0, "max": 0}  # the Necrobinder's Osty: dead (0 max) until summoned
        self.eth_played = 0    # Ethereal cards played this fight (Banshee's Cry, Pull From Below)
        self.st = Counter()
        self.held = Counter()  # per-turn powers that are up: Demon Form, Plating
        self.dp = Counter()    # draw and energy powers that are up (see economy)
        self.rule = Counter()  # powers that change play, by stack (see rules)
        self.temp = Counter()  # Strength / Dexterity that goes at the end of the turn
        self.u = Counter()     # this turn's counts the cards read: plays by type, draws
        self.turn_n = self.hurt = self.drawn_total = 0  # hurt: times HP was lost (Tear Asunder)
        self.block = 0
        self.incoming = None
        self.plays_t = 0
        self.nested = False
        self.t = Counter()
        self.keep = []         # cards held to next turn (Expertise's draws)
        self.last_plays = 0    # cards played last turn (Pocketwatch)
        self.no_draw = False   # Battle Trance's No Draw, this turn
        self.clones = []       # Nightmare's copies, into next turn's hand
        self.last_dealt = 0    # damage dealt last turn (what Shadow Step doubles)
        # The character's own pool (Discovery, Jackpot, Calamity and Entropy
        # make cards from it): the deck's commonest character pool.
        own = Counter(c["pool"] for c in deck if c["pool"] in CHAR_POOLS)
        self.char_pool = own.most_common(1)[0][0] if own else "IRONCLAD"
        self.played_total = 0  # cards played this fight (Gold Axe)
        self.boulders = []     # Rolling Boulder: each one's hit, which grows every turn
        self.bombs = []        # The Bomb: [turns left, damage] each
        self.returning = []    # Bolas: back in hand next turn
        # Relic hooks and their counters. Pendulum, Iron Club and Joss Paper
        # keep counting from fight to fight, so each fight starts somewhere
        # random in the count.
        self.trig = [self.hook(e, v, None) for e, v in rel["trig"]]
        self.snap = {}
        self.phase = [rng.randrange(int(v.get(e["every"], 1))) if "every" in e else 0 for e, v in rel["hand"]]

    def hook(self, e, v, pw):
        every = int(v.get(e["every"], 1)) if isinstance(e.get("every"), str) else e.get("every", 1)
        return {"e": e, "v": v, "pw": pw, "n": self.rng.randrange(every) if pw is None else 0, "used": 0, "turn": 0}

    def live(self):
        return [f for f in self.foes if f["hp"] > 0]

    def hit(self, f, amount, relic=False):
        """amount to f. Dealt is what wasn't already counted as Doom it
        carries, so a doomed foe's HP counts once."""
        dealt = min(amount, max(0, f["hp"] - f["doom"]))
        self.t["dealt"] += dealt
        if relic:
            self.t["relicDealt"] += dealt
        alive = f["hp"] > 0
        f["hp"] -= amount
        if alive and f["hp"] <= 0:
            self.trigger("kill")

    def doom(self, f, amt):
        """Doom on f: it counts as dealt now, up to the HP it has left past
        the Doom already on it, and dies to it at the end of its turn (see
        doom_kill). Shroud blocks and Sleight of Flesh hits on each one."""
        if amt <= 0 or f["hp"] <= 0:
            return
        got = min(amt, max(0, f["hp"] - f["doom"]))
        self.t["dealt"] += got
        self.t["doomDealt"] += got
        f["doom"] += amt
        self.u["doomApplied"] += 1
        self.trigger("doomApplied")
        self.trigger("debuffApplied", foe=f)

    def doom_kill(self):
        """Every foe whose HP is down to its Doom dies (its turn's end, End of Days)."""
        for f in self.live():
            if f["hp"] <= f["doom"]:
                f["hp"] = 0
                self.trigger("kill")

    def summon(self, n):
        """Summon n: a living Osty gains n max HP and heals n; a dead one comes
        back at n."""
        if n <= 0:
            return
        if self.osty["hp"] > 0:
            self.osty["max"] += n
            self.osty["hp"] += n
        else:
            self.osty["max"] = self.osty["hp"] = n
        self.t["summoned"] += n

    def osty_lose(self, n):
        """Osty loses up to n HP (a hit he soaks, Sacrifice); Necro Mastery
        hits every foe for each. At 0 he's dead."""
        lost = min(n, self.osty["hp"])
        if lost <= 0:
            return
        self.osty["hp"] -= lost
        if self.osty["hp"] <= 0:
            self.osty = {"hp": 0, "max": 0}
        per = self.ruled("ostyLossHits")
        for f in self.live() if per else []:
            self.hit(f, lost * per)

    def reshuffle(self):
        if not self.pile:
            self.pile, self.used = self.used, []
            self.rng.shuffle(self.pile)
            # Stratagem: the best of the new draw pile into the hand
            for _ in range(int(self.ruled("shuffleFetch")) if self.pile else 0):
                if not self.pile or len(self.hand) >= HAND_MAX:
                    break
                h = max(self.pile, key=self.face)
                self.pile.remove(h)
                self.hand.append(h)

    def random_card(self, mr, up):
        """A random card for makes_random mr (see extract_power_data.colorless):
        from the colorless pool, the character's own or the other
        characters', of its type, 0-cost (Jackpot), upgraded (up), free this
        turn (Discovery) or for the fight (Metamorphosis); the best face of
        mr's choose (Quasar's 3)."""
        src = {"own": self.char_pool, "others": "others:" + self.char_pool}.get(mr.get("pool"), "colorless")
        cards = pool(src, mr.get("type"), bool(mr.get("zeroCost")))
        if not cards:
            return None
        h = max((card(self.rng.choice(cards), up) for _ in range(mr.get("choose") or 1)), key=self.face)
        h = dict(h)
        if mr.get("free") == "turn":
            h["free_turn"] = self.turn_n
        elif mr.get("free") == "combat":
            h["cost"] = 0
        return h

    def random_worth(self, mr, up):
        """What one card made by makes_random mr is worth: its pool's average
        face (made free, the energy it saves), better for a pick of several."""
        src = {"own": self.char_pool, "others": "others:" + self.char_pool}.get(mr.get("pool"), "colorless")
        v = self.pool_face(src, up, mr.get("type"), bool(mr.get("zeroCost")))
        if mr.get("free"):
            cards = pool(src, mr.get("type"), bool(mr.get("zeroCost")))
            v += 5 * sum(max(0, CD[k].get("energy") or 0) for k in cards) / max(1, len(cards))
        return v * (1.3 if (mr.get("choose") or 1) > 1 else 1)

    def draw(self, n, hand=False):
        """Draw up to n cards, stopping at a full hand of 10; returns them.
        Fiddle and No Draw stop every draw but the turn's hand draw."""
        got = []
        if not hand and (self.no_draw or self.rel["no_other_draws"]):
            return got
        for _ in range(int(n)):
            self.reshuffle()
            if not self.pile or len(self.hand) >= HAND_MAX:
                break
            c = self.pile.pop()
            self.hand.append(c)
            self.t["seen"] += 1
            self.u["drawn"] += 1
            self.u["drawnExtra"] += not hand
            self.drawn_total += 1
            if "Strike" in c["tags"] and self.ruled("playsDrawn") and self.u["hellraiser"] < 9:
                # Hellraiser: a Strike plays itself as it's drawn, 9 a turn at most.
                self.u["hellraiser"] += 1
                self.hand.remove(c)
                self.play(c, free=True)
                continue
            got.append(c)
            if c["id"] == VOID:  # Void: 1 energy less as it's drawn
                self.energy = max(0, self.energy - 1)
            if c["on_draw"]:  # Kingly Kick costs 1 less, Kingly Punch hits harder, for the fight
                c["cost"] = max(0, c["cost"] + c["on_draw"].get("cost", 0))
                c["dmg"] += c["on_draw"].get("dmg", 0)
            self.trigger("draw")  # Corrosive Wave
            if not hand:
                self.trigger("drawExtra")  # Speedster
            if c["type"] == "Status":
                self.trigger("drawStatus")
            if c["ethereal"]:
                self.trigger("drawEthereal")
        return got

    def amount(self, a, tr):
        """A hook's number: a literal, its power's stack, or a relic var."""
        if not isinstance(a, str):
            return a
        if a == "Amount":
            return self.dp[tr["pw"]]
        return tr["v"].get(a, tr["v"].get(f"{a}Power", 1))

    def fires_on(self, tr, on, kind=None, cid=None, c=None, spent=False):
        """Whether hook tr is up and set off by this event: its card type
        (Game Piece: Powers), its one card (Haunt: Soul), the card c being
        Ethereal (Spirit of Ash) or costing enough (Danse Macabre). Black
        Hole's play hook wants a play that spent stars (spent), and only that."""
        e = tr["e"]
        return e["on"] == on and e.get("type", kind) == kind and (not tr["pw"] or self.dp[tr["pw"]] > 0) \
            and ("cardIs" not in e or cid == "CARD." + e["cardIs"]) and bool(e.get("starsSpent")) == spent \
            and ("keyword" not in e or bool(c and e["keyword"] == "Ethereal" and c["ethereal"])) \
            and ("minCost" not in e or bool(c and not c["x"] and self.cost(c) >= power_var(tr["pw"], e["minCost"])))

    def trigger(self, on, times=1, kind=None, foe=None, cid=None, c=None, stars=0, spent=False):
        """Fire the relic and power hooks on an event, times over: Dark
        Embrace, Feel No Pain and Joss Paper on an exhaust, Vicious on
        Vulnerable, Gremlin Horn on a kill, Centennial Puzzle on losing HP,
        Game Piece on playing a Power (kind), Unceasing Top on an empty hand,
        Corrosive Wave and Speedster on a draw, Envenom on an attack's hit
        (foe: the one it hit), Serpent Form on any play, Shroud on Doom,
        Sleight of Flesh on a debuff (foe: the one it's on), Devour Life on
        a Soul played. The Regent's: Child of the Stars per star spent
        (stars), Galactic Dust every so many, Mini Regent's Strength, Black
        Hole on stars gained or a play that spent them (spent), Arsenal and
        Pillar of Creation on a card made, The Sealed Throne on any play."""
        for tr in self.trig:
            e = tr["e"]
            if not self.fires_on(tr, on, kind, cid, c, spent):
                continue
            stack = self.dp[tr["pw"]] if tr["pw"] else 0
            if e.get("snapshot"):
                if not self.snap.get(id(tr)):
                    continue
                self.dp[tr["pw"]] = self.snap[id(tr)]  # read at the amount it had
            reps, counted = times * (stars if e.get("perStar") else 1), False
            if "every" in e and stars:  # Galactic Dust: once per Stars stars spent, carried over
                tr["n"] += stars * times
                reps, tr["n"] = divmod(tr["n"], int(self.amount(e["every"], tr)))
                counted = True
            for _ in range(reps):
                if tr["used"] >= e.get("perCombat", INF) or tr["turn"] >= e.get("perTurn", INF):
                    break
                if "every" in e and not counted:  # Iron Club: every 4th card played
                    tr["n"] += 1
                    if tr["n"] % int(self.amount(e["every"], tr)):
                        continue
                tr["used"] += 1
                tr["turn"] += 1
                if "block" in e:
                    self.gain_block(self.amount(e["block"], tr))
                for key in ("damage", "poison"):  # Juggernaut, Charon's Ashes; Envenom
                    if key not in e or not self.live():
                        continue
                    on_foe = foe if e.get("onTarget") and foe and foe["hp"] > 0 else None
                    for f in self.live() if e.get("aoe") else [on_foe or self.rng.choice(self.live())]:
                        if key == "damage":
                            self.hit(f, self.amount(e["damage"], tr))
                        else:
                            f["poison"] += self.amount(e["poison"], tr)
                if "energy" in e:
                    self.energy += self.amount(e["energy"], tr)
                    self.t["energy"] += self.amount(e["energy"], tr)
                if "draw" in e:
                    self.draw(self.amount(e["draw"], tr))
                if "summon" in e:
                    self.summon(self.amount(e["summon"], tr))
                if "strength" in e:  # Arsenal, Mini Regent
                    self.st["str"] += self.amount(e["strength"], tr)
                if "stars" in e:  # The Sealed Throne
                    self.gain_stars(self.amount(e["stars"], tr))
            if e.get("snapshot"):
                self.dp[tr["pw"]] = stack

    def orb_value(self, t, kind, o=None):
        """What one passive or evoke of an orb of type t (or orb o) is worth:
        its base plus Focus (and Infused Core on Lightning), never below 0.
        Dark's evoke is what its passives have stored; Glass's passive is its
        own shrinking base and its evoke twice that; Plasma takes no Focus."""
        if t == "Plasma":
            return ORB_PASSIVE[t] if kind == "passive" else ORB_EVOKE[t]
        if t == "Dark" and kind == "evoke":
            return o["ev"] if o else ORB_EVOKE[t]
        if t == "Glass":
            v = max(0, (o["g"] if o else ORB_PASSIVE[t]) + self.st["focus"])
            return v if kind == "passive" else 2 * v
        base = (ORB_PASSIVE if kind == "passive" else ORB_EVOKE)[t]
        return max(0, base + self.st["focus"] + self.rel["orb_bonus"][t])

    def orb_hit(self, f, amt):
        """Orb damage: unpowered, so no Strength or Vulnerable on it."""
        if f["hp"] > 0 and amt > 0:
            self.hit(f, amt)
            self.t["orbDealt"] += amt

    def passive(self, o, target=None, hooked=True):
        """o's passive once, or twice for the first orb under Gold-Plated
        Cables (hooked: a passive the relic counts, not Loop's or a card's).
        Lightning hits a random foe (Tesla Coil's target), Frost blocks,
        Dark stores more evoke, Plasma gives energy, Glass hits every foe and
        shrinks."""
        times = 1 + (self.rel["cables"] if hooked and self.orbs and o is self.orbs[0] else 0)
        for _ in range(times):
            t, v = o["t"], self.orb_value(o["t"], "passive", o)
            if t == "Lightning" and self.live():
                self.orb_hit(target if target and target["hp"] > 0 else self.rng.choice(self.live()), v)
            elif t == "Frost":
                self.gain_block(v)
            elif t == "Dark":
                o["ev"] += v
            elif t == "Plasma":
                self.energy += v
                self.t["energy"] += v
            elif t == "Glass":
                for f in self.live():
                    self.orb_hit(f, v)
                o["g"] = max(0, o["g"] - 1)

    def evoke(self, o):
        """o's evoke: Lightning hits a random foe (and Thunder hits it again),
        Frost blocks, Dark hits the weakest foe, Plasma gives energy, Glass
        hits every foe."""
        t, v = o["t"], self.orb_value(o["t"], "evoke", o)
        live = self.live()
        if t == "Lightning" and live:
            f = self.rng.choice(live)
            self.orb_hit(f, v)
            for pw in self.orbp:
                for e in orb_hooks(pw):
                    if e["at"] == "evoked" and self.orbp[pw] > 0:
                        self.orb_hit(f, self.orbp[pw])
        elif t == "Frost":
            self.gain_block(v)
        elif t == "Dark" and live:
            self.orb_hit(min(live, key=lambda f: f["hp"]), v)
        elif t == "Plasma":
            self.energy += v
            self.t["energy"] += v
        elif t == "Glass":
            for f in live:
                self.orb_hit(f, v)
        self.t["evokes"] += 1

    def evoke_next(self, n=1, last=False):
        """Evoke the next orb (the oldest; the newest for Consuming Shadow) n
        times, out of its slot on the last (Dualcast, Multi-Cast)."""
        if not self.orbs or n <= 0:
            return
        o = self.orbs[-1] if last else self.orbs[0]
        for _ in range(int(n)):
            self.evoke(o)
        self.orbs.remove(o)

    def channel(self, t):
        """Channel an orb (Random: any of the five): a character with no slots
        gets one, a full row evokes its oldest first. Metronome goes off once
        enough have been channeled this fight."""
        if t == "Random":
            t = self.rng.choice(ORB_TYPES)
        if not self.base_slots and not self.slots:
            self.slots = 1
        if not self.slots:
            return
        if len(self.orbs) >= self.slots:
            self.evoke_next()
        self.orbs.append({"t": t, "ev": ORB_EVOKE.get(t, 0), "g": ORB_PASSIVE["Glass"]})
        self.channeled["all"] += 1
        self.channeled[t] += 1
        for i, (e, v) in enumerate(self.rel["orb"]):
            if e["at"] == "channeled" and self.orb_used[i] < e.get("perCombat", INF) \
                    and self.channeled["all"] >= int(v.get(e["every"], 1)):
                self.orb_used[i] += 1
                for f in self.live():
                    self.hit(f, v.get(e["aoe"], 0), relic=True)

    def add_slots(self, n):
        """Orb slots up (Capacitor) or down (Bulk Up, which loses the newest
        orbs past the new count, unevoked); 10 at most."""
        self.slots = max(0, min(MAX_SLOTS, self.slots + n))
        del self.orbs[self.slots:]

    def run_orb_ops(self, c, times, target):
        """c's orb ops in order (see orb_ops); times is X for an X card."""
        for op in c["orb_ops"]:
            x = int(times) + op["plus"]
            n = x if op["n"] == "X" else op["n"] + (op["plus"] if op["times"] != "X" else 0)
            reps = op["times"]
            reps = x if reps == "X" else len(self.live()) if reps == "enemies" else len(self.orbs) if reps == "orbs" \
                else int(self.calc(c, target, "count")) if reps == "calc" else reps
            n, reps = int(n), int(reps)
            for _ in range(reps):
                if op["op"] == "channel":
                    for _ in range(n):
                        self.channel(op["orb"])
                elif op["op"] == "evoke":
                    self.evoke_next(n)
                elif op["op"] == "passive":  # Darkness' Dark orbs, Tesla Coil's Lightning at its target
                    for o in [o for o in self.orbs if o["t"] == op["orb"]]:
                        for _ in range(n):
                            self.passive(o, target if op["on_target"] else None, hooked=False)
                elif op["op"] == "slots":
                    self.add_slots(n)

    def orb_turn(self, at, n):
        """The orbs at the start or end of turn n. At the start: Plasma's
        energy, Cracked Core's first Lightning and Runic Capacitor's slots,
        Emotion Chip's passives after losing HP, Loop's, Lightning Rod's and
        Spinner's channels, Coolant's block. At the end: every other orb's
        passive and Hailstorm, then Consuming Shadow's evokes."""
        def hook(e, amt):
            if "slots" in e:
                self.add_slots(amt)
            elif "channel" in e:
                for _ in range(int(amt)):
                    self.channel(e["channel"])
            elif "passiveAll" in e:
                if not e.get("ifLostHp") or self.lost_last:
                    for o in list(self.orbs):
                        self.passive(o)
            elif "passiveFirst" in e:
                for _ in range(int(amt)):
                    if self.orbs:
                        self.passive(self.orbs[0], hooked=False)
            elif "blockPerUnique" in e:
                self.gain_block(amt * len({o["t"] for o in self.orbs}))
            elif "aoe" in e:  # Hailstorm, with a Frost orb out (its FrostOrbs is 1)
                if any(o["t"] == "Frost" for o in self.orbs):
                    for f in self.live():
                        self.orb_hit(f, amt)
            elif "evokeLast" in e:
                for _ in range(int(amt)):
                    self.evoke_next(last=True)
        if at == "start":
            for o in [o for o in self.orbs if o["t"] == "Plasma"]:
                self.passive(o)
        else:
            for o in [o for o in self.orbs if o["t"] != "Plasma"]:
                self.passive(o)
        for e, v in self.rel["orb"]:
            if e["at"] == at and (not e.get("first") or n == 1):
                hook(e, next((int(v.get(e[k], 1)) for k in ("n", "slots", "passiveAll") if isinstance(e.get(k), str)),
                             e.get("n", e.get("passiveAll", 1))))
        for pw in [pw for pw in self.orbp if self.orbp[pw] > 0]:
            for e in orb_hooks(pw):
                if e["at"] != at:
                    continue
                stack = self.orbp[pw]
                amt = stack if e.get("n", "Amount") == "Amount" else e["n"]
                hook(e, amt)
                if e.get("decrements"):
                    self.orbp[pw] -= 1

    def gain_block(self, n):
        """Block gained: Juggernaut hits a random foe each time."""
        if n > 0:
            self.block += n
            self.trigger("blockGained")

    def gain_stars(self, n):
        """Stars gained (they keep from turn to turn): Black Hole hits every foe."""
        if n > 0:
            self.stars += n
            self.u["starsGained"] += n  # Radiate
            self.t["stars"] += n
            self.trigger("starsGained")

    def spend_stars(self, n):
        """Stars paid for a card: Child of the Stars, Galactic Dust, Mini Regent."""
        if n > 0:
            self.stars -= n
            self.trigger("starsSpent", stars=n)

    def star_cost(self, c):
        """Stars c costs now: none if it's free (Void Form, Brilliant Scarf's
        Nth card), all of them for Stardust's X."""
        if c["stars"] <= 0 and not c["star_x"]:
            return 0
        if c.get("free_turn") == self.turn_n or self.free_by(c) or self.scarf_free():
            return 0
        return self.stars if c["star_x"] else c["stars"]

    def scarf_free(self):
        """Brilliant Scarf: the Nth card played this turn is free, energy and stars."""
        return bool(self.rel["nth_free"]) and self.u["scarf"] == self.rel["nth_free"] - 1

    def made(self, n=1):
        """n cards made in the fight (transforms too): Arsenal, Pillar of
        Creation and Regalite fire, Supermassive counts them."""
        if n > 0:
            self.generated += n
            self.trigger("generated", n)

    def add_made(self, h, where="Hand"):
        """A made card into a pile (the hand if there's room, else the discard pile)."""
        if where == "Hand" and len(self.hand) < HAND_MAX:
            self.hand.append(h)
        elif where == "Draw":
            self.pile.insert(self.rng.randrange(len(self.pile) + 1), h)
        else:
            self.used.append(h)
        self.made()

    def make_it_so(self):
        """A Skill played: Make It So back to the hand from the draw or discard
        pile on every Nth Skill this turn."""
        for h in [h for h in self.pile + self.used if h["returns_on_skills"]]:
            if self.u["Skill"] % h["returns_on_skills"]["every"] == 0 and len(self.hand) < HAND_MAX:
                (self.pile if h in self.pile else self.used).remove(h)
                self.hand.append(h)

    def blades(self):
        """Every Sovereign Blade not exhausted."""
        return [h for h in self.hand + self.pile + self.used if h["blade"]]

    def forge(self, n):
        """Forge n: a Sovereign Blade into the hand if there's none about (a
        made card), then n more damage on every blade."""
        if n <= 0:
            return
        if not self.blades():
            self.add_made(dict(card(BLADE)))
        for h in self.blades():
            h["dmg"] += n
        self.forged += n
        self.t["forged"] += n

    def ruled(self, key):
        """The stacks up of powers with a given rule (Hellraiser's playsDrawn)."""
        return int(sum(n for pw, n in self.rule.items() if n > 0 and key in rules(pw)))

    def make_status(self, sid, where):
        """A status made into a pile (Fight Through's Wounds), then what fires
        on making one: Smokestack's hit on every foe, Trash to Treasure's
        random orbs."""
        h = card("CARD." + sid)
        if where == "Hand":
            if len(self.hand) >= HAND_MAX:
                return
            self.hand.append(h)
        elif where == "Draw":
            self.pile.insert(self.rng.randrange(len(self.pile) + 1), h)
        else:
            self.used.append(h)
        self.t["statuses"] += 1
        self.made()
        self.trigger("statusMade")
        for pw in [pw for pw in self.orbp if self.orbp[pw] > 0]:
            for e in orb_hooks(pw):
                if e["at"] == "statusMade":
                    for _ in range(int(self.orbp[pw])):
                        self.channel(e["channel"])

    def buffered(self):
        """Buffer: HP about to be lost isn't, for a stack of it."""
        pw = next((pw for pw, n in self.rule.items() if n > 0 and rules(pw).get("buffer")), None)
        if pw:
            self.rule[pw] -= 1
        return bool(pw)

    def lose_hp(self, n):
        """HP lost on your own turn (Bloodletting, Inferno's burn), past
        block: Rupture turns it into Strength, Inferno hits every foe."""
        n = max(0, n - self.rel["hp_red"])
        if not n or self.buffered():
            return
        self.t["selfLost"] += n
        self.hurt += 1
        self.st["str"] += self.st["rupture"]
        if self.st["inferno"]:
            for f in self.live():
                self.hit(f, self.st["inferno"])
        self.trigger("hpLoss")

    def apply(self, pw, side, amt, aoe):
        r = rules(pw)
        if side != "enemy" and orb_hooks(pw):  # Storm, Loop, Coolant, ...
            self.orbp[pw] += amt
        temp = r.get("temp", {})
        if temp.get("stat") in TEMP_STATS:
            # Strength or Dexterity for this turn (Setup Strike), or a foe's
            # Strength down until its turn ends (Piercing Wail, Mangle).
            key = TEMP_STATS[temp["stat"]]
            if side != "enemy":
                self.st[key] += temp["sign"] * amt
                self.temp[key] += temp["sign"] * amt
            elif temp["sign"] < 0 and key == "str":
                live = self.live()
                for f in live if aoe else live and [min(live, key=lambda f: f["hp"])]:
                    f["strdown"] += amt
            return
        if side == "enemy" and "hurtsOnPlay" in r:  # Strangle: each card played hurts it
            live = self.live()
            for f in live if aoe else live and [min(live, key=lambda f: f["hp"])]:
                f["strangle"] += amt
            return
        if side != "enemy" and "clonesNextTurn" in r:  # Nightmare: copies of the best card in hand
            pick = [h for h in self.hand if not h["dead"]]
            if pick:
                self.clones.append((max(pick, key=self.face), int(amt)))
            return
        if side != "enemy" and "turnAoeGrows" in r:  # Rolling Boulder: each one grows on its own
            self.boulders.append(amt)
            return
        if side != "enemy" and "vulnBonus" in r:  # Cruelty: Vulnerable takes Amount % more
            self.st["cruelty"] += amt
            return
        if side != "enemy" and r:
            self.rule[pw] += amt
        if side != "enemy" and pw in TURN_BURNS:
            self.st["burn" + pw] += 1
        if side != "enemy" and pw in SELF_POWERS:
            self.st[SELF_POWERS[pw]] += amt
        elif side == "enemy" and pw in ENEMY_POWERS:
            live = self.live()
            targets = live if aoe else live and [min(live, key=lambda f: f["hp"])]
            for f in targets:
                if pw == "Doom":
                    self.doom(f, amt)
                elif pw == "Hang":  # Hang: max(2, its stack) more, so it doubles
                    f["hang"] += max(2, f["hang"])
                else:
                    f[ENEMY_POWERS[pw]] += amt
                if pw in DEBUFFS:
                    self.trigger("debuffApplied", foe=f)  # Sleight of Flesh
            if pw == "Vulnerable":
                self.trigger("vulnerable", len(targets))
        elif side != "enemy" and economy(pw):
            if not any(t["pw"] == pw for t in self.trig):
                self.trig += [self.hook(e, {}, pw) for e in economy(pw).get("triggers", [])]
            self.dp[pw] += amt
            if economy(pw).get("noOtherDraws"):
                self.no_draw = True
        elif side != "enemy" and turn_power(pw):
            self.held[pw] += amt

    def per_stack(self, c, f):
        """A calculated card's bonus (Bully's per Vulnerable on f)."""
        if not c["per"]:
            return 0
        pw, on, extra = c["per"]
        if on == "target":
            return extra * f[ENEMY_POWERS[pw]] if f else 0
        return extra * self.st[SELF_POWERS[pw]]

    def count(self, of, c, f):
        """What a calculated card counts now (see card's calc)."""
        hand = self.others(c, True)
        if of == "strikes":  # itself too, wherever it is
            return sum("Strike" in h["tags"] for h in hand + self.pile + self.used + self.gone) + ("Strike" in c["tags"])
        if of == "handOthers":  # Precise Cut
            return len(hand)
        if of == "skillsInHand":
            return sum(h["type"] == "Skill" for h in hand)
        if of == "poisonAll":
            return sum(o["poison"] for o in self.live())
        if of == "targetPowers":
            return sum(bool(f[k]) for k in ("poison", "weak", "vuln", "strdown", "doom", "debil")) if f else 0
        if of == "ostyAttackCards":  # Squeeze: the other Osty attacks, wherever they are
            return sum(h["osty"] for h in hand + self.pile + self.used + self.gone)
        if of == "targetDoomTens":  # No Escape: Extra more Doom per 10 on the target
            return int(f["doom"] // 10) if f else 0
        if of == "starCards":  # Crescent Spear: the cards that cost stars, itself too
            return sum(h["stars"] >= 0 or h["star_x"] for h in hand + self.pile + self.used + self.gone) + 1
        if of == "targetHitsThisTurn":  # Beat Into Shape
            return f["hits_t"] if f else 0
        return {"exhaustPile": len(self.gone), "block": self.block, "drawPile": len(self.pile),
                "discardPile": len(self.used), "timesHurt": self.hurt, "drawnThisCombat": self.drawn_total,
                "discardedThisTurn": self.t["discards"], "attacksThisTurn": self.u["Attack"],
                "skillsThisTurn": self.u["Skill"], "drawnThisTurn": self.u["drawn"],
                "drawnThisTurnExtra": self.u["drawnExtra"], "orbs": len(self.orbs),
                "uniqueOrbs": len({o["t"] for o in self.orbs}), "lightningChanneled": self.channeled["Lightning"],
                "energySpentThisTurn": self.u["energySpent"],
                "ostyHp": self.osty["hp"], "ostyMax": self.osty["max"], "ostyMax3": 3 * self.osty["max"],
                "ostyAttacksThisTurn": self.u["ostyAttacks"], "etherealPlayed": self.eth_played,
                "exhaustedSouls": sum(h["id"] == SOUL for h in self.gone),
                "generatedThisCombat": self.generated, "starsGainedThisTurn": self.u["starsGained"],
                "cardsPlayed": self.played_total}.get(of, 0)

    def calc(self, c, f, to):
        """c's calculated bonus to dmg / block / hits now (0 if it has none);
        hits, forge and a power's amount (No Escape's Doom) include the base."""
        if not c["calc"] or c["calc"][0] != to:
            return 0
        _, of, extra, plus, base = c["calc"]
        return (base if to in ("hits", "forge") or to.startswith("power:") else 0) + extra * (plus + self.count(of, c, f))

    def met(self, cond, c, f):
        """Whether a card's condition holds now, on target f (see
        extract_power_data.conditions)."""
        if cond == "targetVulnerable":
            return bool(f and f["vuln"])
        if cond == "targetPoisoned":
            return bool(f and f["poison"])
        if cond == "targetAttacks":
            return bool(f and self.foe_attacks(f))
        if cond == "lostHpThisTurn":
            return self.t["selfLost"] > 0
        if cond == "exhaustedThisTurn":
            return self.t["exhausted"] > 0
        if cond == "exhaustPileAtLeast":
            return len(self.gone) >= c["exhaust_n"]
        if cond == "drawPileEmpty":
            return not self.pile
        if cond == "onlyAttacksInHand":
            return all(h["attack"] for h in self.others(c, True))
        if cond == "doomAppliedThisTurn":
            return self.u["doomApplied"] > 0
        return True

    def n_hits(self, c, f):
        """How many times c hits f: Finisher's Attacks this turn, Dismantle
        twice on a Vulnerable foe, none for Pact's End short of 3 exhausted."""
        if c["only_if"] and not self.met(c["only_if"], c, f):
            return 0
        n = self.calc(c, f, "hits") if c["calc"] and c["calc"][0] == "hits" else c["hits"]
        if c["twice"] and c["twice"][2] == "hits" and self.met(c["twice"][0], c, f):
            n = c["twice"][1]
        return n

    def tagged(self, key, c):
        """The stacks up of powers whose rule key names one of c's tags
        (Fan of Knives' and Phantom Blades' Shivs)."""
        return sum(n for pw, n in self.rule.items() if n > 0 and rules(pw).get(key) in c["tags"])

    def per_hit(self, c, f):
        """One hit of c on f: its damage plus Strength (Accuracy on Shivs,
        Vigor on the first attack, Phantom Blades on the turn's first Shiv),
        half again if f is Vulnerable (more under Cruelty), more again if
        it's Weak under Tracking, doubled under Double Damage. Osty hits
        for his own damage (plus Calcify), none of your Strength, and not
        at all while he's dead. Debilitate makes Vulnerable count twice,
        Lethality adds to the turn's first Attack, Hang multiplies Hang."""
        if c["osty"]:
            if self.osty["hp"] <= 0:
                return 0
            per = c["dmg"] + self.ruled("ostyBonus") + self.per_stack(c, f) + self.calc(c, f, "dmg")
        else:
            first = sum(n for pw, n in self.rule.items() if n > 0 and rules(pw).get("firstTagBonus") in c["tags"]
                        and not self.u["tag:" + rules(pw)["firstTagBonus"]])
            per = c["dmg"] + self.st["str"] + (self.st["acc"] if c["shiv"] else 0) + self.st["vigor"] \
                + self.per_stack(c, f) + self.grown[c["id"]] + self.calc(c, f, "dmg") + first \
                + (self.ruled("zeroCostBonus") if not c["x"] and self.cost(c) == 0 else 0)  # One for All
        vuln = 1.5 + self.st["cruelty"] / 100
        per = max(0, per) * ((2 * vuln - 1 if f["debil"] else vuln) if f["vuln"] else 1)
        if c["attack"] and not self.u["Attack"]:
            per *= 1 + self.ruled("firstAttackBonus") / 100
        if c["id"] == HANG and f["hang"]:
            per *= f["hang"]
        if c["osty"]:
            return per
        if f["weak"]:
            per *= 1 + self.ruled("weakBonus") / 100
        for pw, n in self.rule.items():
            if n > 0 and rules(pw).get("dmgMult"):
                per *= rules(pw)["dmgMult"]
        if c["blade"] and f["conq"]:  # Conqueror: the Sovereign Blade hits it double
            per *= 2
        return per * self.tag_mult(c)

    def tag_mult(self, c):
        """Vitruvian Minion: Minion cards' damage and block doubled."""
        tm = self.rel["tag_mult"]
        return tm[1] if tm and tm[0] in c["tags"] else 1

    def aoe(self, c):
        """Whether c hits every foe: its own, a Shiv under Fan of Knives, the
        Sovereign Blade under Seeking Edge."""
        return c["aoe"] or bool(self.tagged("aoeTag", c)) or (c["blade"] and self.st["seeking"] > 0)

    def attack(self, c, times, hits=None):
        self.landed = []
        if not c["hitter"] or not self.live() or (c["osty"] and self.osty["hp"] <= 0):  # Osty's: not while he's dead
            return
        live = self.live()
        aoe = self.aoe(c)
        first = live[0] if aoe else min(live, key=lambda f: f["hp"])
        left = (self.n_hits(c, first) if hits is None else hits) * times
        reap = self.ruled("doomPerDamage")
        gaze = self.ruled("hitStrDown")  # Monarch's Gaze: Strength down this turn on each foe hit
        while left > 0:  # landed: (foe, HP it lost) per hit, for Blight Strike's Doom
            left -= 1
            live = self.live()
            if not live:
                break
            targets = live if aoe else [self.rng.choice(live)] if c["random"] \
                else [min(live, key=lambda f: f["hp"])]
            for f in targets:
                amt = self.per_hit(c, f)
                took = min(amt, f["hp"])
                self.hit(f, amt)
                self.landed.append((f, took))
                f["hits_t"] += 1  # Beat Into Shape
                f["strdown"] += gaze
                if c["osty"] and f["sicem"] and amt > 0:  # Sic 'Em: Osty's hit summons
                    self.summon(f["sicem"])
                if reap and took > 0:  # Reaper Form: Doom for the damage, yours or Osty's
                    self.doom(f, took * reap)
                if amt > 0 and not c["osty"]:
                    self.trigger("attackHit", foe=f)  # Envenom
                if c["splash"]:  # Omnislice: the same again to every other foe
                    for o in self.live():
                        if o is not f:
                            self.hit(o, amt)
            if c["repeat_on_kill"]:  # Echoing Slash: again for each foe it killed
                left += len(live) - len(self.live())
        if c["osty"]:
            self.u["ostyAttacks"] += 1  # Rattle, Flatten
        else:
            self.st["vigor"] = 0
        for t in c["tags"]:  # Phantom Blades' bonus is for the turn's first Shiv
            self.u["tag:" + t] += 1

    def card_block(self, c):
        blk = c["block"] + self.st["dex"] + self.per_stack(c, None) + self.calc(c, None, "block")
        if c["twice"] and c["twice"][2] == "block" and self.met(c["twice"][0], c, None):
            blk *= c["twice"][1]
        blk += self.tagged("tagBlock", c)  # Fasten: more on Defends
        blk *= 2 ** self.ruled("blockDoubles") * self.tag_mult(c)  # Shadowmeld, Vitruvian Minion
        if self.ruled("noCardBlock"):  # Panic Button's No Block
            return 0
        return blk * 2 if self.blocked < self.st["unmovable"] else blk

    def free_by(self, c):
        """The power that makes c free now, if any: Corruption's Skills, Free
        Attack's next Attack, Veilpiercer's next Ethereal card, Void Form's
        first cards each turn."""
        for pw, n in self.rule.items():
            f = rules(pw).get("free")
            if not f or n <= 0 or (f.get("type") and c["type"] != f["type"]) \
                    or (f.get("keyword") == "Ethereal" and not c["ethereal"]) \
                    or (f.get("perTurn") and self.t["played"] >= n):
                continue
            return pw
        return None

    def cost(self, c):
        """Energy c costs now: 0 if a power or the card that made it (Infernal
        Blade) says so, less for each card of a type played this turn (Stomp).
        Kept per card while pick() weighs a hand, since nothing it costs moves then."""
        if self._cc is not None:
            k = id(c)
            if k not in self._cc:
                self._cc[k] = self._cost(c)
            return self._cc[k]
        return self._cost(c)

    def _cost(self, c):
        if c["x"]:
            return c["cost"]
        if c.get("free_turn") == self.turn_n or self.free_by(c) or (c["free_after_osty"] and self.u["ostyAttacks"]) \
                or self.scarf_free():
            return 0  # Flatten: free once Osty has attacked this turn
        # Banshee's Cry: less per Ethereal card played this fight; Borrowed
        # Time: every card costs more this turn.
        down = (self.u[c["cost_down"]] if c["cost_down"] else 0) + c["cost_down_eth"] * self.eth_played
        return max(0, c["cost"] - down) + self.ruled("costUp")

    def replays(self, c, consume=False):
        """Extra times c plays now: One-Two Punch's next Attack, Burst's next
        Skill, Duplication, Echo Form's first cards each turn, Sword Sage's
        Sovereign Blade."""
        n = (self.ruled("bladeReplays") if c["blade"] else 0) + c.get("gem", 0)  # Hidden Gem's Replay
        for pw, amt in self.rule.items():
            r = rules(pw).get("replays")
            if not r or amt <= 0 or (r["type"] and c["type"] != r["type"]):
                continue
            if r.get("perTurn"):
                n += self.t["played"] < amt
            else:
                n += 1
                if consume and r["decrements"]:
                    self.rule[pw] -= 1
        return n

    def hook_pay(self, on, kind=None, cid=None, c=None, stars=0, spent=False, times=1):
        """(damage, block) the hooks that are up pay out on an event, times
        over: Rage's block on an Attack, Juggernaut's hit on gaining block.
        A summon counts as block (Devour Life), Strength (Arsenal, Mini
        Regent) as damage to come; Child of the Stars pays per star spent,
        Galactic Dust per so many. Panache's count starts over each turn, so
        a play only pays toward it if the hand and energy left can finish it."""
        d = b = 0
        for tr in self.trig:
            e = tr["e"]
            if not self.fires_on(tr, on, kind, cid, c, spent) or tr["turn"] >= e.get("perTurn", INF) \
                    or tr["used"] >= e.get("perCombat", INF):
                continue
            k = times * (stars if e.get("perStar") or ("every" in e and stars) else 1)
            if e.get("perTurn"):
                k = min(k, e["perTurn"] - tr["turn"])
            if e.get("turnReset"):
                need = int(self.amount(e["every"], tr)) - tr["n"] % int(self.amount(e["every"], tr))
                left, can = self.energy - (self.cost(c) if c else 0), 1
                for x in sorted(self.cost(h) for h in self.hand if h is not c and not h["dead"]):
                    if x <= left:
                        left, can = left - x, can + 1
                k = k / need if can >= need else 0
            else:
                k /= self.amount(e["every"], tr) if "every" in e else 1
            d += (self.amount(e.get("damage", 0), tr) * (max(1, len(self.live())) if e.get("aoe") else 1)
                  + self.amount(e.get("strength", 0), tr) * 2) * k
            b += (self.amount(e.get("block", 0), tr) + self.amount(e.get("summon", 0), tr)) * k
        return d, b

    def pool_value(self, pool):
        """The average worth of a pile's cards, one level deep: a Havoc in the
        pile an Uproar plays from doesn't value the pile again."""
        if not pool:
            return 0
        self.nested = True
        try:
            return sum(self.value(h) for h in pool) / len(pool)
        finally:
            self.nested = False

    def value(self, c):
        """What playing c is worth this turn. All-in turns count only their
        own axis (plus draw and energy to find more of it), so a Defend is
        worth nothing to a damage turn and a power only if it feeds the
        plan; a card worth nothing isn't played. Damage counts Strength and
        Vulnerable, so a multi-hit card climbs the order as Strength builds."""
        live = self.live()
        n = max(1, len(live))
        f = min(live, key=lambda f: f["hp"]) if live else None
        ex = self.to_exhaust(c) if c["exhausts"] else []
        hit = self.per_hit(c, f) if c["hitter"] and f else 0
        hits = len(ex) if c["hits_per"] else self.n_hits(c, f)
        if c["star_x"]:  # Stardust: a hit per star
            hits *= self.star_cost(c)
        if c["x_double"] and self.energy >= c["x_double"]:  # Heavenly Drill
            hits *= 2
        shiv = self.per_hit(card(SHIV), f) * (n if self.aoe(card(SHIV)) else 1) if f else 0
        dmg = hit * hits * (n if self.aoe(c) or c["splash"] else 1) + c["shivs"] * shiv
        if c["plays_exhausted"] and f:  # Knife Trap: every Shiv in the exhaust pile again
            dmg += sum(self.per_hit(card(h["id"], c["up"] or h["up"]), f) for h in self.gone
                       if c["plays_exhausted"] in h["tags"])
        blk = self.card_block(c) * (len(ex) if c["block_per"] else 1) if c["blocker"] else 0
        if c["block_from_dmg"] and f:  # Fisticuffs: the HP its hits take
            blk += min(hit * hits, f["hp"])
        orb_d, orb_b, orb_e = self.orb_worth(c, f) if c["orb_ops"] else (0, 0, 0)
        dmg += orb_d
        blk += orb_b
        pay_d, pay_b = self.hook_pay("play", c["type"], c["id"], c)  # Rage, Serpent Form
        blk += pay_b
        dmg += pay_d + (self.hook_pay("blockGained")[0] if blk > 0 else 0)  # Juggernaut
        if self.focus == "dmg" and blk > 0:  # a Body Slam in hand turns this block into damage
            dmg += blk * max((h["calc"][2] for h in self.others(c, True) if h["calc"] and h["calc"][:2] == ("dmg", "block")),
                             default=0)
        if c["block_if_drawn"]:  # Escape Plan: only if the card it draws is a Skill
            pool = self.pile or self.used
            blk *= sum(h["type"] == c["block_if_drawn"] for h in pool) / len(pool) if pool and self.draws(c) else 0
        if self.focus == "dmg":
            v = dmg
        elif self.focus == "block":
            v = blk + self.st["afterimage"]
        else:
            # Block is worth what it stops this turn (all of it under
            # Barricade); against foes with no known attacks, its face value.
            # Osty soaks what gets past block.
            need = INF if self.st["barricade"] or self.incoming is None \
                else max(0, self.incoming - self.block - self.osty["hp"])
            v = dmg + min(blk, need) * (1.2 if self.incoming is not None else 0.9)
        gain = c["energy"] if self.holds(c["energy_if"], c) else 0
        v += self.draw_worth(self.draws(c), self.energy - (0 if c["x"] else self.cost(c)) + gain + orb_e, c) \
            + gain * 5 + orb_e * 5
        if c["calc"] and c["calc"][0] == "draw" and not (self.no_draw or self.rel["no_other_draws"]):
            v += self.calc(c, f, "draw") * 3  # Compile Driver
        if c["calc"] and c["calc"][0].startswith("power:") and c["calc"][0] != "power:Doom" and self.focus != "block":
            v += self.calc(c, f, c["calc"][0]) * len(self.orbs) * 2  # Synchronize: Focus on each orb out
        v += (len(ex) + c["exhaust"]) * self.exhaust_pay()
        v += self.changes_worth(c, f, n, ex)
        sly = sum(1 for h in self.hand if h["sly"] and h is not c)
        v += c["discard"] * (self.rel["discard_dmg"] + 1) + min(c["discard"], sly) * 8
        if c["discards_hand"]:
            # Shadow Step, Storm of Steel: the rest of the hand goes, its Sly cards
            # play themselves; Storm of Steel's Shivs stand in for what went.
            rest = [h for h in self.others(c, True) if not h["retain"]]
            v += len(rest) * self.rel["discard_dmg"] + sum(h["sly"] for h in rest) * 8 \
                - sum(max(0, self.face(h)) for h in rest if not h["sly"]) * 0.5
            if c["per_discarded"] and f and self.focus != "block":
                v += len(rest) * self.per_hit(card(SHIV, c["up"]), f) * (n if self.aoe(card(SHIV)) else 1)
        feeds = (lambda pw: self.focus in axes(pw)) if self.focus else modelled
        for pw, (side, amt) in c["applies"].items():
            if pw in c["applies_if"] and not self.met(c["applies_if"][pw], c, f):
                continue
            amt = self.calc(c, f, "power:" + pw) if c["calc"] and c["calc"][0] == "power:" + pw \
                else self.energy if amt == "X" else self.block if amt == "block" else amt  # No Escape's Doom; Malaise's X Weak
            r = rules(pw)
            if r.get("bomb"):  # The Bomb: its blast at every foe, a few turns off
                v += c["bomb_dmg"] * n * 0.6 if self.focus != "block" else 0
            elif r.get("noCardBlock"):  # Panic Button: the hand's other block lost, and next turn's
                if self.focus != "dmg":
                    v -= sum(self.card_block(h) for h in self.others(c, True) if h["blocker"]) * 0.5 + (amt - 1) * 8
            elif r.get("gambit"):  # The Gambit: any hit you don't block kills you, so only to finish a fight
                v -= 30 if self.focus is None and sum(o["hp"] for o in live) > 20 else 0
            elif pw == "Doom":
                # Doom is damage to come, up to the HP past the Doom already
                # there (Blight Strike's is the damage it deals).
                if self.focus != "block" and f:
                    a = hit * hits if c["doom_from_dmg"] else amt
                    on = live if c["aoe"] or PD["cards"].get(c["id"], {}).get("target") == "AllEnemies" else [f]
                    v += sum(min(a, max(0, o["hp"] - o["doom"])) for o in on)
            elif feeds(pw):
                # Energy next turn is nearly energy now (Outmaneuver, Invoke).
                v += amt * (4 if any("energy" in e for e in turn_power(pw)) else 2)
        v += self.necro_worth(c, f, live, n) + self.regent_worth(c, f)
        if c["str_per_vuln"] and f and self.focus != "block":
            v += (f["vuln"] + c["applies"].get("Vulnerable", (0, 0))[1]) * c["str_per_vuln"] * 2
        if c["autoplay"] and not self.nested:
            # Havoc: whatever's on top of the draw pile, so the pile's average.
            pool = [h for h in (self.pile or self.used) if not h["autoplay"]]
            v += self.pool_value(pool)
        if c["type"] == "Power" and (self.focus in c["helps"] if self.focus else c["helps"]):
            v += 40
        if c["random_free"]:  # Infernal Blade: a random one of its type, free this turn
            v += self.pool_face(c["pool"], False, c["random_free"])
        if c["copy_to"]:  # Anger: another copy to play later
            v += 2 + 4 * c["copy_free"]  # Adaptive Strike's is free
        for sid, _, k in c["puts"]:
            v += self.status_worth(sid) * (1 if k in ("varies", "fullHand") else k)
        if c["discard_top"] and self.used:  # Headbutt: the best of the discard pile drawn next
            v += 3
        if c["from_discard"]:  # a chosen card back is a draw and a bit
            v += len(self.from_discard(c)) * 4
        if c["plays_from"] and not self.nested:  # Uproar, Beat Down: the pile's average card of that type, free
            pool = self.plays_pool(c, True)
            v += self.pool_value(pool) * min(c["plays_from"]["n"], len(pool))
        v += min(c["ups_discard"], sum(h["upable"] for h in self.used)) * 2
        if c["fetches"]:  # Wish, Secret Technique: a chosen card out of the draw pile is a draw and a bit
            v += len(self.fetched(c, True)) * (3.5 if c["fetches"].get("choose") else 4)
        if c["replays_draw"]:  # Hidden Gem: a draw-pile card plays more times from now on
            pool = [h for h in self.pile if not h["dead"]]
            v += c["replays_draw"] * sum(max(0, self.face(h)) for h in pool) / len(pool) * 0.5 if pool else 0
        if c["returns_next_turn"]:  # Bolas: back in hand next turn, a free draw
            v += 2
        if c["doubles_energy"]:  # weighted double: each card played before it shrinks the gain, so it goes first
            v += max(0, self.energy - self.cost(c)) * 10
        if c["hand_to_draw"]:  # Reboot: what's left in hand goes back unplayed
            v -= sum(max(0, self.face(h)) for h in self.others(c, True)) * 0.3
        if c["sly"] and any(h["discard"] for h in self.hand if h is not c):
            v *= 0.3  # better discarded for free than paid for
        v *= 1 + self.replays(c)
        return v if self.focus else v or 1

    def necro_worth(self, c, f, live, n):
        """What c's Necrobinder effects are worth this turn: HP summoned to
        Osty soaks hits like block (on a damage turn, what it adds to the
        Osty attacks in hand, or brings them back to life); killing Osty
        loses that soak but sets off Necro Mastery; Strength off a foe is
        block against its hits, off you is damage lost; Souls are cards to
        come."""
        v = 0
        hand = self.others(c, True)
        s = c["summon"] * (self.energy if c["x"] else 1)  # Dirge: X times
        if s:
            if self.focus == "block":
                v += s
            elif self.focus is None:
                v += s * (1.0 if self.incoming else 0.9)
            if self.focus == "dmg":  # Unleash, Protector: the Osty attacks that read his HP
                v += s * sum(h["calc"][2] for h in hand if h["calc"] and h["calc"][0] == "dmg"
                             and h["calc"][1] in ("ostyHp", "ostyMax"))
            if self.focus != "block" and self.osty["hp"] <= 0:  # brings back the Osty attacks in hand
                v += sum(h["dmg"] * h["hits"] for h in hand if h["osty"]) * 0.8
        hp = self.osty["hp"]
        if c["kills_osty"] and hp > 0:
            if self.focus is None:
                v -= hp * 0.5
            if self.focus != "block":
                v += hp * self.ruled("ostyLossHits") * n
        for side, k in c["lowers"].items():
            k = self.energy if k == "X" else k
            if side == "self":
                v -= k * 3 if self.focus != "block" else 0
            elif self.focus is None and f:
                v += k * sum(self.foe_hits(o)[1] for o in (live if side == "enemies" else [f])) * 2
        v += 4 * sum(self.energy if k == "X" else k for _, _, k in c["makes_cards"])
        return v

    def regent_worth(self, c, f):
        """What c's Regent effects are worth this turn: stars (worth more with
        cards to spend them on) and what fires on gaining or spending them
        (Black Hole, Child of the Stars, Galactic Dust); Forge on the
        Sovereign Blade (half a blade if it makes one); cards made, turned
        into Minions or copied, and what fires on making them (Arsenal,
        Pillar of Creation); Decisions, Decisions' best Skill again; Void
        Form's lost turn."""
        v = d = b = 0
        gs = c["gain_stars"]
        if gs and c["stars_if_kill"]:  # Knockout Blow: only if it kills
            gs *= bool(f and c["hitter"] and self.per_hit(c, f) * self.n_hits(c, f) >= f["hp"])
        if gs:
            want = min(gs, max(0, self.star_cap - self.stars))  # past the dearest sink's price: spare
            v += want * self.star_val + (gs - want) * 0.5
            d, b = self.hook_pay("starsGained")
        sc = self.star_cost(c)
        if sc:
            for pd, pb in (self.hook_pay("play", spent=True), self.hook_pay("starsSpent", stars=sc)):
                d, b = d + pd, b + pb
        fg = c["forge"] or self.calc(c, f, "forge")
        if fg and self.focus != "block":
            v += fg * 1.5 + (0 if self.blades() else max(0, self.face(card(BLADE))) * 0.5)
        hand = self.others(c, True)
        made = 0
        if c["turns_into"]:
            ti = c["turns_into"]
            into = self.face(card("CARD." + ti["into"], ti["up"] and c["up"]))
            gains = sorted((into - self.face(h) for h in (self.pile if ti["from"] == "draw" else hand)), reverse=True)
            gains = [g for g in gains if g > 0][:None if ti["n"] == "all" else ti["n"]]
            v += sum(gains) * (0.5 if ti["from"] == "draw" else 1)  # from the draw pile: later
            made += len(gains)
        if c["makes_random"]:
            mr = c["makes_random"]
            v += mr["n"] * self.random_worth(mr, mr["up"] and c["up"]) * (0.5 if mr.get("pile") == "Draw" else 1)
            made += mr["n"]
        if c["clones"]:
            col = [self.face(h) for h in hand if h["pool"] == "colorless"]
            if col:
                v += c["clones"]["n"] * max(0, max(col))
                made += c["clones"]["n"]
        if c["plays_skill"]:
            sk = [self.value(h) for h in hand if h["type"] == "Skill" and not h["dead"] and not h["plays_skill"]
                  and not h["plays_from"]]
            v += c["plays_skill"] * max(sk, default=0)
        if c["blade_to_hand"] and self.focus != "block":
            v += sum(max(0, self.face(h)) * 0.8 for h in self.pile + self.used + self.gone if h["blade"])
        made += sum(self.energy if k == "X" else k for _, _, k in c["makes_cards"]) + c["shivs"]
        if made:
            pd, pb = self.hook_pay("generated", times=made)
            d, b = d + pd, b + pb
        mono = sum(n for pw, (_, n) in c["applies"].items() if isinstance(n, int) and rules(pw).get("strPerPlay"))
        if mono and f and self.focus != "block":
            # Monologue: Strength after each card played after it, so what the
            # hand can still afford, Attacks last to hit with the most.
            left, after = self.energy - self.cost(c), []
            for h in sorted((h for h in hand if not h["dead"] and not h["x"]), key=lambda h: self.cost(h)):
                if self.cost(h) <= left:
                    left -= self.cost(h)
                    after.append(h)
            after.sort(key=lambda h: h["hitter"])
            d += sum(mono * i * self.n_hits(h, f) for i, h in enumerate(after) if h["hitter"])  # it lands after each
        if c["ends_turn"]:  # Void Form: the energy left this turn goes unspent
            v -= max(0, self.energy - self.cost(c)) * 5
        return v + (d if self.focus == "dmg" else b if self.focus == "block" else d + b)

    def from_discard(self, c):
        """The cards c takes from the discard pile into the hand: every 0-cost
        one (All for One), else its best n, as many as the hand has room for."""
        fd, room = c["from_discard"], HAND_MAX - len(self.others(c, True))
        if fd["n"] == "all":
            got = [h for h in self.used if not h["x"] and not h["dead"] and self.cost(h) == 0
                   and h["type"] in ("Attack", "Skill", "Power")]
        else:
            got = sorted(self.used, key=self.face, reverse=True)[:fd["n"]]
        return got[:max(0, room)]

    def plays_pool(self, c, valuing=False):
        """What Uproar / Beat Down can autoplay: the pile's playable cards of
        the type. Valuing, another Uproar (or a card that plays a Skill from the
        hand) is left out so two of them don't value each other forever."""
        pf = c["plays_from"]
        return [h for h in (self.pile if pf["pile"] == "Draw" else self.used)
                if pf["type"] in (None, h["type"]) and not h["dead"] and not (valuing and (h["plays_from"] or h["plays_skill"]))]

    def fetched(self, c, valuing=False):
        """The cards c picks out of the draw pile into the hand, as many as
        there's room for: the best of its type (Secret Weapon's Attack, Wish's
        any), the best of `choose` random ones (Seeker Strike), every Rare
        (Anointed)."""
        fe, room = c["fetches"], HAND_MAX - len(self.others(c, True))
        cands = [h for h in self.pile if fe["type"] in (None, h["type"])
                 and (not fe.get("rarity") or CD.get(h["id"], {}).get("rarity") == fe["rarity"])]
        if fe["n"] == "fullHand":
            return cands[:max(0, room)]
        if fe.get("choose") and not valuing:  # valuing: only the count matters
            cands = self.rng.sample(cands, min(fe["choose"], len(cands)))
        return sorted(cands, key=self.face, reverse=True)[:max(0, min(fe["n"], room))]

    def status_worth(self, sid):
        """One status made: a dead draw to come (Burn and Void worse), less
        what fires on making it (Smokestack, Trash to Treasure)."""
        v = -STATUS_COST.get(sid, 2)
        for tr in self.trig:
            if self.fires_on(tr, "statusMade") and "damage" in tr["e"]:
                v += self.amount(tr["e"]["damage"], tr) * (len(self.live()) if tr["e"].get("aoe") else 1)
        for pw in [pw for pw in self.orbp if self.orbp[pw] > 0]:
            v += sum(5 * self.orbp[pw] for e in orb_hooks(pw) if e["at"] == "statusMade")
        return v

    def orb_worth(self, c, f):
        """(damage, block, energy) c's orb ops are worth this turn, played out
        on a copy of the orb row: a channeled orb's passive at this turn's end
        and the next (ORB_TICKS) and half its evoke to come, plus the oldest
        orb evoked to make room; an evoke loses those passives; a passive op
        pays now. Glass hits
        every foe. An extra slot is worth a little either way."""
        n_live = max(1, len(self.live()))
        q = [dict(o) for o in self.orbs]
        slots = self.slots or (0 if self.base_slots else 1)
        out = [0, 0, 0]

        def add(o, kind, k=1):
            t, v = o["t"], self.orb_value(o["t"], kind, o) * k
            i = 1 if t == "Frost" else 2 if t == "Plasma" else 0
            out[i] += v * (n_live if t == "Glass" else 1)

        x = self.energy
        for op in c["orb_ops"]:
            n = x + op["plus"] if op["n"] == "X" else op["n"] + (op["plus"] if op["times"] != "X" else 0)
            reps = op["times"]
            reps = x + op["plus"] if reps == "X" else len(self.live()) if reps == "enemies" else len(q) if reps == "orbs" \
                else int(self.calc(c, f, "count")) if reps == "calc" else reps
            n, reps = int(n), int(reps)
            for _ in range(reps):
                if op["op"] == "channel":
                    for _ in range(n):
                        if not slots:
                            break
                        if len(q) >= slots:
                            add(q.pop(0), "evoke")
                        o = {"t": "Lightning" if op["orb"] == "Random" else op["orb"], "ev": ORB_EVOKE.get(op["orb"], 6),
                             "g": ORB_PASSIVE["Glass"]}
                        q.append(o)
                        add(o, "passive", ORB_TICKS)
                        add(o, "evoke", 0.5)
                elif op["op"] == "evoke" and q:
                    add(q[0], "evoke", n)
                    add(q.pop(0), "passive", -ORB_TICKS)
                elif op["op"] == "passive":
                    for o in q:
                        if o["t"] == op["orb"]:
                            add(o, "passive", n)
                elif op["op"] == "slots":
                    slots = max(0, min(MAX_SLOTS, slots + n))
                    out[0] += 2 * n
                    out[1] += 2 * n
        return out

    def changes_worth(self, c, f, n, ex):
        """What c's knock-on effects are worth this turn: HP loss through
        Rupture and Inferno, doubling Vulnerable, upgrades and transforms on
        the cards actually in hand (not the deck's best), Stoke's random
        cards for the hand it burns, and in a real fight Colossus and Flame
        Barrier against what's coming."""
        v = 0
        if self.focus != "block":
            if c["hp_loss"]:
                v += self.st["rupture"] * 2 + self.st["inferno"] * n
            if c["doubles"] and f:
                v += f[ENEMY_POWERS[c["doubles"]]] * 2
        hand = self.others(c, True)
        if c["upgrades"]:
            gains = [self.face(card(h["id"], True)) - self.face(h) for h in hand if h["upable"]]
            v += sum(gains) if c["upgrades"] == "hand" else max(gains, default=0)
        if c["transforms"]:
            into = card("CARD." + c["transforms"]["into"], c["up"])
            v += sum(self.face(into) - self.face(h) for h in hand if h["type"] == c["transforms"]["type"])
        if c["generates"]:
            v += len(ex) * self.pool_face(c["pool"], c["up"]) - sum(self.face(h) for h in ex)
        # A power that plays the next card of a type again (One-Two Punch) is
        # worth the best such card in hand once more; one that makes them free
        # (Free Attack, Corruption), the energy it saves on them.
        for pw, (side, amt) in c["applies"].items():
            r = rules(pw)
            if side == "enemy":
                continue
            if "replays" in r:
                kind = r["replays"]["type"]
                v += max((self.value(h) for h in hand if not h["dead"] and kind in (None, h["type"])
                          and not any("replays" in rules(p) for p in h["applies"])), default=0)
            if "free" in r:
                kind = r["free"].get("type")
                costs = sorted((self.cost(h) for h in hand if not h["x"] and kind in (None, h["type"])), reverse=True)
                v += 5 * sum(costs[:int(amt)] if r["free"]["decrements"] else costs)
        amt = lambda pw: c["applies"].get(pw, (0, 0))[1]
        if self.focus != "block":
            if any(e.get("power") == "DoubleDamage" for pw in c["applies"] for e in turn_power(pw)):
                v += self.last_dealt * 0.8  # Shadow Step: next turn's damage again
            if amt("Strangle"):  # a hit for each card still to play this turn
                v += amt("Strangle") * sum(not h["dead"] and self.cost(h) <= self.energy - self.cost(c) for h in hand)
        affordable = [h for h in hand if not h["dead"] and self.cost(h) <= self.energy - self.cost(c)]
        for pw, (side, a) in c["applies"].items():
            if side == "enemy":
                continue
            if "clonesNextTurn" in rules(pw):  # Nightmare: the best card in hand, a times next turn
                v += a * 0.7 * max((self.face(h) for h in hand if not h["dead"]), default=0)
            if "blockDoubles" in rules(pw) and self.focus != "dmg":  # Shadowmeld: the block still to play
                v += sum(self.card_block(h) for h in affordable if h["blocker"]) * (2 ** a - 1)
            for e in economy(pw).get("triggers", []):
                if e["on"] == "draw" and "poison" in e and self.focus != "block":
                    # Corrosive Wave: Poison on every foe for each card still to draw this turn
                    v += a * sum(self.draws(h) for h in affordable) * n * 2
        if self.focus is None and self.incoming:
            if amt("Colossus") and not self.st["colossus"]:
                v += sum(self.foe_hits(o)[0] for o in self.live() if o["vuln"]) * 0.5
            if amt("FlameBarrier"):
                v += amt("FlameBarrier") * sum(self.foe_hits(o)[1] for o in self.live())
            if amt("Thorns"):  # Caltrops: Flame Barrier for the fight
                v += amt("Thorns") * sum(self.foe_hits(o)[1] for o in self.live()) * 2
            if any(rules(pw).get("buffer") for pw in c["applies"]):  # Buffer: the biggest hit coming
                v += max((t / h for t, h in (self.foe_hits(o) for o in self.live()) if h), default=0)
            if amt("Intangible") and not self.st["intangible"]:  # every hit down to 1
                v += sum(t - h for t, h in (self.foe_hits(o) for o in self.live())) * amt("Intangible") * 0.6
        return v

    def pool_face(self, name, up, kind=None, zero=False):
        """The average worth of a random card from a pool (Stoke), or of one
        type in it (Infernal Blade), or its 0-cost ones (Jackpot)."""
        key = (name, up, self.focus, kind, zero)
        if key not in POOL_FACE:
            cards = pool(name, kind, zero)
            POOL_FACE[key] = sum(self.face(card(k, up)) for k in cards) / len(cards) if cards else 0
        return POOL_FACE[key]

    def swap(self, old, new, pile=None):
        """old, in hand (or pile), becomes new for the rest of the fight
        (Armaments, Primal Force, Charge); an upgraded Rampage keeps what it's
        gained."""
        new, pile = fresh(new), self.hand if pile is None else pile
        if old["grows"] and new["grows"]:
            new["dmg"] += old["dmg"] - card(old["id"], old["up"])["dmg"]
        pile[next(i for i, h in enumerate(pile) if h is old)] = new

    def others(self, c, in_hand):
        """The hand without c (one copy of it, if it's still in the hand)."""
        hand = self.hand[:]
        if in_hand and c in hand:
            hand.remove(c)
        return hand

    def holds(self, cond, c, in_hand=True):
        """Whether c's draw or energy condition is met now: no Attack in hand
        (Impatience), c the only card in hand (Restlessness), under PlayMax
        cards played this turn (FTL), c's first play this turn (Fetch)."""
        hand = self.others(c, in_hand)
        if cond == "noAttackInHand":
            return not any(h["attack"] for h in hand)
        if cond == "onlyCardInHand":
            return not hand
        if cond == "fewPlays":
            return self.t["played"] < c["play_max"]
        if cond == "firstPlay":
            return c["id"] not in self.played_ids
        return True

    def draws(self, c, in_hand=True):
        """Cards c would draw if played now: up to a full hand, Pillage's run
        of Attacks (one more for each in a row), only Scrape's free ones."""
        if not c["draw"] or not self.holds(c["draw_if"], c, in_hand) or self.no_draw or self.rel["no_other_draws"]:
            return 0
        room = HAND_MAX - len(self.others(c, in_hand))
        pool = self.pile or self.used
        n = room if c["draw"] == "fullHand" else c["draw"]
        if c["draw_while"] and pool:
            p = sum(h["type"] == c["draw_while"] for h in pool) / len(pool)
            n = 1 / (1 - p) if p < 1 else room
        if c["drawn_discard"]:
            n *= sum(self.cost(h) == 0 and not h["x"] for h in pool) / len(pool) if pool else 0
        return min(n, room)

    def draw_worth(self, n, left, c=None):
        """What drawing n now is worth with left energy to play them: 3 a
        card the energy can pay for at the pile's going cost (0-cost cards
        always), 1 a card past that for the pick it adds. Prophesize's 6
        with 1 energy left is mostly the latter. Energy the rest of the hand
        (besides c) will spend on cards worth playing isn't left for them:
        Scrawl with two Strikes in hand and 2 energy draws mostly picks."""
        if n <= 0:
            return 0
        for x in sorted(self.cost(h) for h in self.hand
                        if h is not c and not h["dead"] and not h["x"] and self.face(h) > 0):
            if x > left:
                break
            left -= x
        pool = [h for h in (self.pile or self.used) if not h["dead"]]
        if not pool:
            return n
        free = sum(h["x"] or self.cost(h) == 0 for h in pool) / len(pool)
        paid = [self.cost(h) for h in pool if not h["x"] and self.cost(h) > 0]
        use = min(n, n * free + max(0, left) / (sum(paid) / len(paid)) if paid else n)
        return 3 * use + (n - use)

    def face(self, h):
        """A card's rough worth to the turn's plan without playing it out:
        what to give up first (Burning Pact, Tyranny)."""
        if h["dead"]:
            return -1
        d, b = h["dmg"] * h["hits"], h["block"]
        worth = d if self.focus == "dmg" else b if self.focus == "block" else d + b
        # An orb card: about one evoke's worth per orb it channels or evokes.
        worth += sum(6 * (op["n"] if isinstance(op["n"], int) else 2) * (op["times"] if isinstance(op["times"], int) else 2)
                     for op in h["orb_ops"] if op["op"] in ("channel", "evoke"))
        return worth + 3 * (h["draw"] if isinstance(h["draw"], int) else 5) + 5 * h["energy"] \
            + 20 * (h["type"] == "Power")

    def worst(self, cards):
        """The card to give up first. Howl from Beyond goes before anything:
        from the exhaust pile it plays itself for free and comes back."""
        return min(cards, key=lambda h: -2 if h["from_exhaust"] else self.face(h))

    def to_exhaust(self, c, in_hand=True, sample=False):
        """The other cards c exhausts if played now. A random pick (Cinder,
        Thrash) is the worst card when only valuing c, a real draw (sample)
        when playing it."""
        how, hand = c["exhausts"], self.others(c, in_hand)
        pick = (lambda cards: self.rng.choice(cards)) if sample else self.worst
        if how == "hand":
            return hand
        if how == "nonAttacks":
            return [h for h in hand if not h["attack"]]
        if how == "statuses":
            return [h for h in hand + self.pile + self.used if h["type"] == "Status"]
        if how == "upTo":  # Purity: as many as you like, so the dead ones
            return [h for h in hand if h["dead"]][:c["exhaust_n"]]
        if how == "randomAttack":
            hand = [h for h in hand if h["attack"]]
        elif how == "drawPile":
            return [self.worst(self.pile)] if self.pile else []
        elif how == "pick":
            return [self.worst(hand)] if hand else []
        return [pick(hand)] if hand else []

    def exhaust_pay(self):
        """What one exhausted card is worth through the hooks now: Dark
        Embrace's and Joss Paper's draws, Feel No Pain's block, Charon's
        Ashes' hits."""
        v = 0
        for tr in self.trig:
            e = tr["e"]
            if e["on"] != "exhaust" or (tr["pw"] and self.dp[tr["pw"]] <= 0):
                continue
            per = self.amount(e["every"], tr) if "every" in e else 1
            v += 3 * self.amount(e.get("draw", 0), tr) / per
        d, b = self.hook_pay("exhaust")  # Feel No Pain's block, Charon's Ashes' hits
        return v + (d if self.focus != "block" else 0) + (b if self.focus != "dmg" else 0)

    def exhausted(self, cards):
        """cards just went to the exhaust pile: the exhaust hooks fire for each."""
        self.gone += cards
        self.t["exhausted"] += len(cards)
        gain = sum(h["exhaust_energy"] for h in cards)  # Drum of Battle
        self.energy += gain
        self.t["energy"] += gain
        if cards:
            self.trigger("exhaust", len(cards))

    def exhaust_from(self, c):
        """Exhaust the other cards c takes; returns them."""
        out = self.to_exhaust(c, in_hand=False, sample=True)
        for h in out:
            src = self.pile if c["exhausts"] == "drawPile" else next(p for p in (self.hand, self.pile, self.used) if h in p)
            src.remove(h)
        self.exhausted(out)
        return out

    def pick(self):
        self._cc = {}
        try:
            return self._pick()
        finally:
            self._cc = None

    def _pick(self):
        best, score = None, 0
        for c in self.hand:
            if c["dead"] or (c["x"] and self.energy < 1) or (not c["x"] and self.cost(c) > self.energy) \
                    or (c["playable_if"] and not self.met(c["playable_if"], c, None)):
                continue
            sc = self.star_cost(c)
            if sc > self.stars or (c["star_x"] and sc < 1):  # not enough stars (Stardust needs one)
                continue
            s = self.value(c) / max(self.cost(c) + sc * STAR_ENERGY, 0.5)
            # A free draw worth playing goes first, while there's energy left
            # for what it draws (Overclock before the Strike; a paid one would
            # take the Strike's energy); Scrawl's draw to a full hand waits
            # for the hand to empty.
            if s > 0 and not c["x"] and self.cost(c) == 0 and c["draw"] != "fullHand" and self.draws(c) > 0:
                s += 1000
            if s > score:
                best, score = c, s
        return best

    def discard(self, n):
        for _ in range(n):
            if not self.hand:
                return
            c = max(self.hand, key=lambda h: (h["sly"], h["dead"], -self.value(h)))
            self.hand.remove(c)
            self.discarded(c)

    def discarded(self, c):
        """c, out of the hand, goes to the discard pile: discard relics fire
        and a Sly card plays itself for free."""
        self.t["discards"] += 1
        if self.rel["discard_dmg"] and self.live():
            self.hit(self.rng.choice(self.live()), self.rel["discard_dmg"])
        self.gain_block(self.rel["discard_block"])
        if c["sly"]:
            self.play(c, free=True)
        else:
            self.used.append(c)

    def play(self, c, free=False, gone=False):
        """Play c: pay for it, play it once more for each replay (One-Two
        Punch, Echo Form), then put it where it goes."""
        times, paid, spent = 1, 0, 0
        self.plays_t += 1
        if self.plays_t > MAX_TURN_PLAYS:  # cards playing cards (Cascade, Havoc) can't loop a turn forever
            self.used.append(c)
            return
        if not free:
            spent = self.star_cost(c)  # before Void Form's free card is used up
            times = int(self.energy) if c["x"] else spent if c["star_x"] else 1
            cost = self.energy if c["x"] else self.cost(c)
            pw = not c["x"] and self.free_by(c)
            if pw and rules(pw)["free"]["decrements"]:
                self.rule[pw] -= 1
            self.energy -= cost
            paid = cost
            self.u["energySpent"] += cost  # Helix Drill
            self.u["scarf"] += 1  # Brilliant Scarf counts the cards you play (not autoplays)
            self.spend_stars(spent)
            if paid and self.ruled("energyPer"):  # Orbit: energy back for every 4 spent
                self.orbit += paid
                k, self.orbit = divmod(self.orbit, 4)
                self.energy += k * self.ruled("energyPer")
                self.t["energy"] += k * self.ruled("energyPer")
        if c["x_double"] and times >= c["x_double"]:  # Heavenly Drill: twice the hits at X of 4 or more
            times *= 2
        mono = self.ruled("strPerPlay")  # Monologue: Strength this turn for each card played after it
        strangle = [(f, f["strangle"]) for f in self.live() if f["strangle"]]  # as it was before this card
        oblivion = [(f, f["oblivion"]) for f in self.live() if f["oblivion"]]  # likewise: not the Oblivion card itself
        if c["ethereal"]:  # Banshee's Cry's discount, Spirit of Ash's block
            self.eth_played += 1
        # Serpent Form, Afterimage: the amount as this card starts, so not the card that applied it
        self.snap = {id(tr): self.dp[tr["pw"]] for tr in self.trig if tr["e"].get("snapshot")}
        storm = [(e, self.orbp[pw]) for pw in self.orbp if self.orbp[pw] > 0 for e in orb_hooks(pw) if e["at"] == "play"]
        # Nostalgia: the turn's first Attacks / Skills go back on top of the draw pile
        tops = c["type"] in ("Attack", "Skill") and self.u["Attack"] + self.u["Skill"] < self.ruled("topsFirst")
        for _ in range(1 + self.replays(c, consume=True)):
            self.resolve(c, times)
        if mono:
            self.st["str"] += mono
            self.temp["str"] += mono
        if spent:  # Black Hole: hits every foe once a card spends stars
            self.trigger("play", spent=True)
        if self.t["played"] >= 5 and not self.u["paleDot"] and self.ruled("drawAfterAttacks"):
            self.u["paleDot"] = 1  # Pale Blue Dot: 5 cards played this turn draws more next turn
            self.apply("DrawCardsNextTurn", "self", self.ruled("drawAfterAttacks"), False)
        for e, n in storm:  # Storm: Lightning for a Power played, at its stack before this card
            if e.get("type", c["type"]) == c["type"]:
                for _ in range(n):
                    self.channel(e["channel"])
        for f, n in strangle:
            if f["hp"] > 0:
                self.hit(f, n)
        for f, n in oblivion:
            if f["hp"] > 0:
                self.doom(f, n)
        for pw, n in self.rule.items():  # Master Planner: a played Skill is Sly from now on
            k = rules(pw).get("keywordOnPlay")
            if n > 0 and k and k["type"] == c["type"] and k["keyword"] == "Sly" and not c["sly"]:
                c = dict(c, sly=True)
        # Corruption: Skills exhaust once played.
        if c["exhaust"] or gone or any(n > 0 and rules(pw).get("exhaustsType") == c["type"] for pw, n in self.rule.items()):
            self.exhausted([c])
        elif paid == 0 and not c["x"] and self.u["feral"] < sum(
                n for pw, n in self.rule.items() if n > 0 and rules(pw).get("returnsZeroCost") == c["type"]):
            self.u["feral"] += 1  # Feral: a 0-cost Attack back to the hand, Amount a turn
            self.hand.append(c)
        elif c["result_pile"] == "Hand" and len(self.hand) < HAND_MAX:  # Particle Wall
            self.hand.append(c)
        elif c["result_pile"] == "Draw" or tops:  # Shining Strike, Nostalgia: back on top of the draw pile
            self.pile.append(c)
        elif c["type"] != "Power":
            self.used.append(c)
        self.played_total += 1  # Gold Axe
        if not self.hand:
            self.trigger("handEmpty")

    def resolve(self, c, times):
        """One play of c's effects."""
        # Conditions read as the card is played, before it draws (FTL counts
        # the plays finished before it).
        draws = c["draw"] and self.holds(c["draw_if"], c, in_hand=False)
        gains = self.holds(c["energy_if"], c, in_hand=False)
        self.t["played"] += 1
        self.played_ids.add(c["id"])
        out = self.exhaust_from(c) if c["exhausts"] else []
        ex = len(out)
        aim = min(self.live(), key=lambda f: f["hp"]) if self.live() else None
        forge = c["forge"] or self.calc(c, aim, "forge")  # Beat Into Shape: the hits before its own
        self.attack(c, times, ex if c["hits_per"] else None)
        landed = self.landed  # before a card played on the way (Hellraiser) replaces it
        if c["block_from_dmg"]:  # Fisticuffs: block for the HP its hits took
            self.gain_block(sum(took for _, took in landed))
        if c["blade"] and self.st["parry"]:  # Parry: block for each Sovereign Blade swing
            self.gain_block(self.st["parry"] + self.st["dex"])
        if c["gain_stars"] and (not c["stars_if_kill"] or any(f["hp"] <= 0 for f, _ in landed)):
            self.gain_stars(c["gain_stars"])  # Knockout Blow: only for a kill
        self.forge(forge)
        if c["blade_to_hand"]:  # Summon Forth: every blade to the hand, the exhaust pile's too
            for p in (self.pile, self.used, self.gone):
                for h in [h for h in p if h["blade"]]:
                    if len(self.hand) < HAND_MAX:
                        p.remove(h)
                        self.hand.append(h)
        if c["grows"] == "exhausted":  # Thrash: the exhausted attack's damage, Strength and all
            c["dmg"] += sum(max(0, h["dmg"] + self.st["str"]) for h in out if h["attack"])
        elif c["grows"]:  # Rampage: this copy, from its next play on
            c["dmg"] += c["grows"]
        self.grown[c["id"]] += c["grows_all"]  # Claw: every copy
        if c["doubles"] and self.live():  # Molten Fist: the target's Vulnerable again
            f, key = min(self.live(), key=lambda f: f["hp"]), ENEMY_POWERS[c["doubles"]]
            if f[key] > 0:
                f[key] *= 2
                if key == "vuln":
                    self.trigger("vulnerable")
        if c["blocker"] and not c["block_if_drawn"]:
            self.gain_block(self.card_block(c) * (ex if c["block_per"] else times))
            self.blocked += 1
        self.gain_block(self.st["afterimage"])
        if gains:
            self.energy += c["energy"]
            self.t["energy"] += c["energy"]
        if c["doubles_energy"]:  # Double Energy
            self.t["energy"] += self.energy
            self.energy *= 2
        if c["hand_to_draw"]:  # Reboot: the hand shuffled into the draw pile, then it draws
            self.pile += self.hand
            self.hand = []
            self.rng.shuffle(self.pile)
        target = min(self.live(), key=lambda f: f["hp"]) if self.live() else None
        if c["calc"] and c["calc"][0] == "draw":  # Compile Driver: a card per orb type out
            self.draw(self.calc(c, target, "draw"))
        # Synchronize: Focus for each orb type, counted before it channels anything
        sync = {c["calc"][0][6:]: self.calc(c, target, c["calc"][0])} if c["calc"] and c["calc"][0].startswith("power:") \
            else {}
        self.run_orb_ops(c, times, target)
        for pw, (side, amt) in c["applies"].items():
            amt = sync.get(pw, times if amt == "X" else self.block if amt == "block" else amt)  # Malaise: X Weak
            if rules(pw).get("bomb"):  # The Bomb: each one counts down on its own
                self.bombs.append([amt, c["bomb_dmg"]])
                continue
            if pw in c["applies_if"] and not self.met(c["applies_if"][pw], c, target):
                continue  # Go for the Eyes: Weak only if the foe means to attack
            if pw == "Doom" and c["doom_from_dmg"]:  # Blight Strike: Doom for the HP its hits took
                for f, took in landed:
                    self.doom(f, took)
            elif pw != "NoDraw":  # Battle Trance draws first, then stops drawing
                self.apply(pw, side, amt, c["aoe"] or PD["cards"].get(c["id"], {}).get("target") == "AllEnemies")
        if c["doom_kill"]:  # End of Days: the Doom kills now
            self.doom_kill()
        for side, n in c["lowers"].items():  # Strength lost: yours (Friendship), the target's, every foe's
            n = times if n == "X" else n
            if side == "self":
                self.st["str"] -= n
                continue
            live = self.live()
            for f in live if side == "enemies" else live and [min(live, key=lambda f: f["hp"])]:
                f["str"] -= n
                self.trigger("debuffApplied", foe=f)  # Sleight of Flesh
        self.summon(c["summon"] * times)  # Dirge: X times
        if c["kills_osty"]:  # Sacrifice, Bone Shards: after their block and hits
            self.osty_lose(self.osty["hp"])
        for mid, where, k in c["makes_cards"]:  # Souls
            for _ in range(times if k == "X" else k):
                if where != "Hand" or len(self.hand) < HAND_MAX:
                    self.add_made(card("CARD." + mid), where)
        if c["str_per_vuln"] and self.live():
            self.st["str"] += min(self.live(), key=lambda f: f["hp"])["vuln"] * c["str_per_vuln"]
        if c["autoplay"]:
            # Havoc / Cascade: play the top card of the draw pile for free.
            for _ in range(times):
                self.reshuffle()
                if not self.pile:
                    break
                top = self.pile.pop()
                if not top["dead"]:
                    self.play(top, free=True, gone=c["autoplay_exhausts"])
                elif not c["autoplay_exhausts"]:
                    self.used.append(top)
        if draws:
            got = self.draw(HAND_MAX - len(self.hand) if c["draw"] == "fullHand" else c["draw"])
            drawn = got[:]
            while c["draw_while"] and got and got[-1]["type"] == c["draw_while"]:
                got = self.draw(1)  # Pillage: again while it draws Attacks
                drawn += got
            if c["drawn_retain"]:
                self.keep += drawn
            if c["drawn_discard"]:  # Scrape: the drawn cards that cost energy
                for h in drawn:
                    if (self.cost(h) or h["x"]) and h in self.hand:
                        self.hand.remove(h)
                        self.discarded(h)
            if c["block_if_drawn"] and drawn and drawn[0]["type"] == c["block_if_drawn"]:
                self.gain_block(self.card_block(c))
                self.blocked += 1
        for _ in range(min(c["put_back"], len(self.hand))):  # Glimmer: the worst of the hand back on top
            h = self.worst(self.hand)
            self.hand.remove(h)
            self.pile.append(h)
        for _ in range(c["plays_skill"] and 1):  # Decisions, Decisions: the best Skill in hand, played again and again
            sk = [h for h in self.hand if h["type"] == "Skill" and not h["dead"]]
            if not sk:
                break
            h = max(sk, key=self.value)
            self.hand.remove(h)
            for _ in range(c["plays_skill"] - 1):
                self.resolve(h, 1)
            self.play(h, free=True)
        if "NoDraw" in c["applies"]:
            self.apply("NoDraw", "self", 1, False)
        if c["upgrades"]:  # Armaments: the best upgrade in this hand, or all of it
            ups = [h for h in self.hand if h["upable"]]
            if c["upgrades"] == "pick" and ups:
                ups = [max(ups, key=lambda h: self.face(card(h["id"], True)) - self.face(h))]
            for h in ups:
                self.swap(h, card(h["id"], True))
        if c["transforms"]:  # Primal Force: every Attack in hand a Giant Rock
            into = card("CARD." + c["transforms"]["into"], c["up"])
            for h in [h for h in self.hand if h["type"] == c["transforms"]["type"]]:
                self.swap(h, into)
                self.made()
        if c["turns_into"]:  # Begone, Guards from the hand, Charge from the draw pile: into Minions
            ti = c["turns_into"]
            into = card("CARD." + ti["into"], ti["up"] and c["up"])
            src = self.pile if ti["from"] == "draw" else self.hand
            worse = sorted([h for h in src if self.face(h) < self.face(into)], key=self.face)
            for h in worse if ti["n"] == "all" else worse[:ti["n"]]:
                self.swap(h, into, src)
                self.made()
        if c["makes_random"]:  # Bundle of Joy, Quasar, Discovery, Jackpot, Metamorphosis into the draw pile
            mr = c["makes_random"]
            for _ in range(mr["n"] if mr.get("pile") == "Draw" else min(mr["n"], HAND_MAX - len(self.hand))):
                h = self.random_card(mr, mr["up"] and c["up"])
                if h:
                    self.add_made(fresh(h), mr.get("pile", "Hand"))
        if c["clones"]:  # Heirloom Hammer: copies of the best colorless card in hand
            col = [h for h in self.hand if h["pool"] == "colorless"]
            if col:
                best = max(col, key=self.face)
                for _ in range(min(c["clones"]["n"], HAND_MAX - len(self.hand))):
                    self.add_made(fresh(dict(best)))
        if c["generates"] and pool(c["pool"]):  # Stoke: a random card for each exhausted
            for _ in range(min(ex, HAND_MAX - len(self.hand))):
                self.add_made(fresh(card(self.rng.choice(pool(c["pool"])), c["up"])))
        if c["discard"]:
            self.discard(c["discard"])
        if c["discards_hand"]:  # Shadow Step, Storm of Steel
            rest = [h for h in self.hand if not h["retain"]]
            self.hand = [h for h in self.hand if h["retain"]]
            for h in rest:  # all leave first: a Sly one played on the way can change the hand
                self.discarded(h)
            if c["per_discarded"]:  # Storm of Steel: a Shiv for each
                m = min(len(rest), HAND_MAX - len(self.hand))
                self.hand += [card("CARD." + c["per_discarded"], c["up"])] * m
                self.made(m)
        if c["plays_exhausted"] and self.live():  # Knife Trap: each Shiv in the exhaust pile plays again
            for h in [h for h in self.gone if c["plays_exhausted"] in h["tags"]]:
                self.gone.remove(h)
                self.play(card(h["id"], True) if c["up"] else h, free=True)
        if c["shivs"]:
            m = min(c["shivs"], HAND_MAX - len(self.hand))
            self.hand += [card(SHIV)] * m
            self.made(m)
        if c["copy_to"]:  # Anger: a copy into the discard pile
            h = fresh(card(c["id"], c["up"]))
            self.add_made(dict(h, cost=0) if c["copy_free"] else h, "Discard")  # Adaptive Strike's costs 0
        for sid, where, k in c["puts"]:
            for _ in range(HAND_MAX - len(self.hand) if k == "fullHand" else int(k) if k != "varies" else 1):
                self.make_status(sid, where)
        if c["random_free"] and pool(c["pool"], c["random_free"]) and len(self.hand) < HAND_MAX:
            # Infernal Blade: a random Attack of the pool, free this turn
            h = dict(card(self.rng.choice(pool(c["pool"], c["random_free"]))))
            h["free_turn"] = self.turn_n
            self.add_made(h)
        if c["discard_top"] and self.used:  # Headbutt: the discard pile's best card on top
            h = max(self.used, key=self.face)
            self.used.remove(h)
            self.pile.append(h)
        if c["from_discard"]:
            for h in self.from_discard(c):
                self.used.remove(h)
                self.hand.append(h)
        if c["fetches"]:  # Wish, Secret Technique, Seeker Strike, Anointed
            for h in self.fetched(c):
                self.pile.remove(h)
                self.hand.append(h)
        if c["replays_draw"]:  # Hidden Gem: a random draw-pile card without Replay plays more times
            gems = [i for i, h in enumerate(self.pile) if not h["dead"] and not h.get("gem")]
            if gems:
                i = self.rng.choice(gems)
                self.pile[i] = dict(self.pile[i], gem=c["replays_draw"])
        if c["returns_next_turn"]:  # Bolas: back in hand at the start of next turn
            self.returning.append(c)
        for _ in range(c["ups_discard"]):  # Drain Power: random ones in the discard pile upgraded
            ups = [i for i, h in enumerate(self.used) if h["upable"]]
            if not ups:
                break
            i = self.rng.choice(ups)
            self.used[i] = fresh(card(self.used[i]["id"], True))
        if c["plays_from"]:  # Uproar, Beat Down: random ones of the type, played free
            for _ in range(c["plays_from"]["n"]):
                cands = self.plays_pool(c)
                if not cands or not self.live():
                    break
                h = self.rng.choice(cands)
                (self.pile if c["plays_from"]["pile"] == "Draw" else self.used).remove(h)
                self.play(h, free=True)
        self.u[c["type"]] += 1
        if c["attack"]:
            self.attacks += 1
            for n, produces, v in self.rel["per_attacks"]:
                if self.attacks % n == 0:
                    for k in produces:
                        if k == "block":
                            self.gain_block(v.get("Block", 0))
                        elif k.startswith("power:"):
                            self.apply(k[6:], "self", v.get(f"{k[6:]}Power", 1), False)
            for pw, k in list(self.rule.items()):  # Calamity: a random Attack of yours for each
                if k > 0 and rules(pw).get("attackMakesRandom"):
                    for _ in range(int(k)):
                        h = self.random_card({"pool": "own", "type": rules(pw)["attackMakesRandom"]}, False)
                        if h:
                            self.add_made(fresh(h))
            # Juggling: the turn's 3rd Attack is copied into the hand.
            if self.u["Attack"] == 3:
                for _ in range(min(self.ruled("copiesNth"), HAND_MAX - len(self.hand))):
                    self.add_made(fresh(card(c["id"], c["up"])))
        if c["hp_loss"]:  # Rupture's Strength lands once the card is done
            self.lose_hp(c["hp_loss"])
        if c["type"] == "Skill":
            self.make_it_so()
        self.ended |= c["ends_turn"]  # Void Form
        self.trigger("play", kind=c["type"], cid=c["id"], c=c)

    def relic_turn(self, n, at):
        """Fire the relic effects due at the start or end of turn n; returns
        extra cards to draw. Relic block, energy and damage are also tallied
        on their own, so the charts can show the relics' share."""
        draw = 0
        for e, v in self.rel["turn"]:
            # Bound Phylactery's combat-start summon is its every-turn one, not a
            # kick (Phylactery Unbound's 5 at the start is).
            every = "summon" in e and any(o.get("summon") == e["summon"] and "on" not in o
                                          for o, _ in self.rel["turn"])
            # Divine Right's stars and Fencing Manual's forge are turn-1 kicks
            # kept in steady mode: they build up for the fight, like a power.
            if e["at"] != at or not fires(e, n, v) or (self.steady and burst(e, v) and "power" not in e
                                                       and "stars" not in e and "forge" not in e and not every):
                continue
            if "power" in e:
                self.apply(e["power"], e["side"], v.get(f"{e['power']}Power", 1), True)
            elif "damage" in e:
                for f in (self.live() if e["damage"] == "aoe" else self.live()[:1]):
                    self.hit(f, v.get("Damage", 0), relic=True)
            elif "block" in e:
                if (e.get("if") == "noBlock" and self.block) or (e.get("if") == "noAttack" and self.attacks):
                    continue
                amt = v.get("Block", 0) * (len(self.hand) if e.get("per") == "cardInHand" else 1)
                self.gain_block(amt)
                self.t["relicBlock"] += amt
            elif "energy" in e:
                self.energy += v.get("Energy", 1)
                self.t["relicEnergy"] += v.get("Energy", 1)
            elif "draw" in e:
                draw += v.get("Cards", 1)
            elif "summon" in e:  # Bound Phylactery, Phylactery Unbound
                self.summon(int(v.get(e["summon"], 1)))
            elif "stars" in e:  # Divine Right, Divine Destiny, Lunar Pastry
                self.gain_stars(int(v.get("Stars", 1)))
            elif "forge" in e:  # Fencing Manual
                self.forge(int(v.get("Forge", 1)))
        return draw

    def held_turn(self, at):
        """Fire the per-turn powers that are up (Demon Form's Strength,
        Plating's block, Energy Next Turn) due at the start or end of the
        turn; returns extra cards to draw. Plating loses a stack each turn."""
        draw = 0
        for pw in list(self.held):
            if at == "start" and PD["powers"][pw].get("decays"):
                self.held[pw] -= 1
            n = self.held[pw]
            if n <= 0:
                del self.held[pw]
                continue
            for e in turn_power(pw):
                if e["at"] != at:
                    continue
                if "power" in e:  # Wraith Form takes Dexterity away
                    self.apply(e["power"], e.get("side", "self"), n * e.get("sign", 1), False)
                elif "block" in e:
                    self.gain_block(n)
                elif "damage" in e:
                    for f in (self.live() if e["damage"] == "aoe" else self.live()[:1]):
                        self.hit(f, n)
                elif "energy" in e and at == "start":
                    self.energy += n
                elif "draw" in e and at == "start":
                    draw += n
                elif "summon" in e:  # Necro's per-turn summons
                    self.summon(n)
                elif "stars" in e and at == "start":  # Genesis, Star Next Turn
                    self.gain_stars(n)
                elif "forge" in e:  # Furnace
                    self.forge(n)
                if e.get("once"):
                    del self.held[pw]
                    break
        return draw

    def hand_draw(self, n):
        """Cards drawn at the start of turn n: 5, give or take relics (Ring of
        the Snake on turn 1, Big Mushroom's 2 fewer, Pocketwatch after a turn
        of few plays, Pendulum every third turn) and powers (Tools of the
        Trade, Draw Cards Next Turn once, Clarity's 1 while it lasts)."""
        d = BASE_DRAW
        for (e, v), phase in zip(self.rel["hand"], self.phase):
            if (self.steady and burst(e, v)) or (e.get("elite") and not self.rel["elite"]) \
                    or not fires(e, n, v, phase) or self.last_plays > v.get(e.get("ifPlayedAtMost"), INF):
                continue
            d += -v.get("Cards", 1) if e.get("less") else v.get("Cards", 1)
        for pw in list(self.dp):
            hd = economy(pw).get("handDraw")
            if hd is None or self.dp[pw] <= 0:
                continue
            amt = hd.get("flat", self.dp[pw])
            d += -amt if hd.get("less") else amt
            if hd.get("once"):
                del self.dp[pw]
        return d

    def start_choices(self, n):
        """Cards given up after the hand draw: Tools of the Trade discards,
        Tyranny and Toasty Mittens exhaust, Gambling Chip swaps out the dead
        weight on turn 1 (with a plan, whatever does nothing for it)."""
        due = list(self.rel["start"]) + [(economy(pw)["atStart"], economy(pw).get("atStartGate", {}), self.dp[pw])
                                         for pw in self.dp if "atStart" in economy(pw) and self.dp[pw] > 0]
        for how, gate, k in due:
            if gate and not fires(gate, n, {}):
                continue
            if how == "discard":
                self.discard(int(k))
            elif how == "exhaust":
                out = []
                for _ in range(min(int(k), len(self.hand))):  # one at a time: the worst can't go twice
                    out.append(self.worst(self.hand))
                    self.hand.remove(out[-1])
                self.exhausted(out)
            elif how == "mulligan":
                out = [h for h in self.hand if h["dead"] or (self.focus and not self.value(h))]
                for h in out:
                    self.hand.remove(h)
                    self.used.append(h)
                self.draw(len(out), hand=True)

    def turn(self, n):
        if DEADLINE and time.time() > DEADLINE:
            raise TimeoutError("run took too long")
        self.t, self.u = Counter(), Counter()
        self.turn_n = n
        self.attacks = self.blocked = self.plays_t = 0
        self.played_ids = set()
        self.no_draw = self.ended = False
        for tr in self.trig:
            tr["turn"] = 0
            if tr["e"].get("turnReset"):  # Panache counts each turn from scratch
                tr["n"] = 0
        for f in self.foes:
            f["hits_t"] = 0
        if not self.st["barricade"] and not self.ruled("keepsBlock"):  # Barricade, Blur
            self.block = 0
        for pw in [pw for pw in self.rule if (PD["powers"][pw].get("decays") or rules(pw).get("noCardBlock"))
                   and self.rule[pw] > 0]:
            self.rule[pw] -= 1  # Blur wears off a turn at a time; No Block at the end of the foes' turn
        # Infinite Blades' Shivs and Nightmare's copies, before the draw.
        for pw, k in list(self.rule.items()):
            if k > 0 and rules(pw).get("turnMakes"):
                m = int(min(k, HAND_MAX - len(self.hand)))
                self.hand += [card("CARD." + rules(pw)["turnMakes"])] * m
                self.made(m)
            r = rules(pw).get("turnMakesRandom") if k > 0 else None
            kind = None if r in ("Any", "Colorless") else r  # None: any type
            src = "colorless" if r == "Colorless" else power_pool(pw)  # Spectrum Shift: colorless cards
            if r and pool(src, kind):
                # Creative AI: random Powers of the pool; Call of the Void: any, Ethereal
                for _ in range(min(int(k), HAND_MAX - len(self.hand))):
                    h = fresh(card(self.rng.choice(pool(src, kind))))
                    self.hand.append(dict(h, ethereal=True) if rules(pw).get("turnMakesEthereal") else h)
                    self.made()
        for h, k in self.clones:
            m = min(k, HAND_MAX - len(self.hand))
            self.hand += [fresh(card(h["id"], h["up"])) for _ in range(m)]
            self.made(m)
        self.clones = []
        if n == 1:  # Orange Dough: colorless cards in the opening hand
            for src, k in self.rel["open_makes"]:
                for _ in range(min(k, HAND_MAX - len(self.hand))):
                    self.add_made(fresh(card(self.rng.choice(pool(src.lower())))))
        extra = sum(amt for gate, amt in self.rel["max_energy"]
                    if fires(gate, n, {}) and not (self.steady and burst(gate, {})))
        powers = sum(economy(pw)["maxEnergy"] * self.dp[pw] for pw in self.dp if "maxEnergy" in economy(pw))
        self.energy = BASE_ENERGY + extra + powers
        self.t["relicEnergy"] += extra
        draw = self.hand_draw(n) + self.relic_turn(n, "start") + self.held_turn("start")
        for pw in list(self.dp):  # Clarity wears off a turn at a time, after the draw
            if PD["powers"][pw].get("decays"):
                self.dp[pw] -= 1
        for f in self.live():
            f["poison"] += self.st["fumes"]
        self.t["energy"] += self.energy
        self.orb_turn("start", n)
        self.incoming = self.intents()
        # Aggression: Attacks from the discard pile back to the hand, upgraded,
        # before the draw.
        for _ in range(self.ruled("fromDiscard")):
            atk = [h for h in self.used if h["attack"]]
            if not atk or len(self.hand) >= HAND_MAX:
                break
            h = self.rng.choice(atk)
            self.used.remove(h)
            self.hand.append(h)
            if h["upable"]:
                self.swap(h, card(h["id"], True))
        fc = self.ruled("handDrawOnce")  # Foregone Conclusion: the best of the draw pile first
        if fc:
            if len(self.pile) < fc:
                self.rng.shuffle(self.used)
                self.pile, self.used = self.used + self.pile, []
            for h in sorted(self.pile, key=self.face, reverse=True)[:min(fc, HAND_MAX - len(self.hand))]:
                self.pile.remove(h)
                self.hand.append(h)
            del self.rule["ForegoneConclusion"]
        for h in self.returning:  # Bolas: back in hand from wherever it went
            for p in (self.used, self.pile, self.gone):
                if h in p and len(self.hand) < HAND_MAX:
                    p.remove(h)
                    self.hand.append(h)
                    break
        self.returning = []
        self.draw(draw, hand=True)
        for i, k in enumerate(self.boulders):  # Rolling Boulder: every foe, then it grows
            for f in self.live():
                self.hit(f, k)
            self.boulders[i] += PD["powers"]["RollingBoulder"]["turnAoeGrows"]
        for pw, k in list(self.rule.items()):  # Entropy: the worst of the hand transformed
            if k > 0 and rules(pw).get("turnTransforms"):
                avg = self.pool_face(self.char_pool, False)
                for _ in range(int(k)):
                    worst = self.worst(self.hand) if self.hand else None
                    if worst is None or self.face(worst) >= avg:
                        break
                    h = fresh(card(self.rng.choice(pool(self.char_pool))))
                    self.hand[self.hand.index(worst)] = h
        for pw in TURN_BURNS:  # Inferno, Crimson Mantle: HP first thing each turn
            if self.st["burn" + pw]:
                self.lose_hp(self.st["burn" + pw])
        self.start_choices(n)
        for h in [h for h in self.gone if h["from_exhaust_start"]]:  # Bombardment plays from the exhaust pile
            if self.live():
                self.gone.remove(h)
                self.play(h, free=True)
        for _ in range(int(self.ruled("turnPlaysTop"))):  # Mayhem: the top of the draw pile, played
            self.reshuffle()
            if not self.pile or not self.live():
                break
            top = self.pile.pop()
            if top["dead"]:
                self.used.append(top)
            else:
                self.play(top, free=True)
        plays = 0
        while self.live() and plays < MAX_PLAYS and not self.ended:  # a 0-cost draw loop in a thin deck can go forever
            plays += 1
            c = self.pick()
            if not c:
                break
            self.hand.remove(c)
            self.play(c)
        if self.pile and self.pile[-1]["autoplays_top"] and self.live():  # I Am Invincible on top of the draw pile
            self.play(self.pile.pop(), free=True)
        for h in [h for h in self.gone if h["from_exhaust"]]:  # Howl from Beyond plays itself and comes back
            self.gone.remove(h)
            self.play(h, free=True)
        for _ in range(self.ruled("endPlays")):  # Stampede: a random Attack in hand plays itself
            atk = [h for h in self.hand if h["attack"] and not h["dead"]]
            if not atk or not self.live():
                break
            h = self.rng.choice(atk)
            self.hand.remove(h)
            self.play(h, free=True)
        self.orb_turn("end", n)  # before this turn's Focus goes
        for h in [h for h in self.hand if h["id"] == BURN]:  # Burn: 2 to you at the turn's end, past block
            soak = min(self.block, 2)
            self.block -= soak
            self.lose_hp(2 - soak)
        for b in self.bombs:  # The Bomb: a turn closer, or its blast at every foe
            if b[0] > 1:
                b[0] -= 1
            else:
                for f in self.live():
                    self.hit(f, b[1])
                b[0] = 0
        self.bombs = [b for b in self.bombs if b[0] > 0]
        self.relic_turn(n, "end")
        self.held_turn("end")
        # This turn's Strength / Dexterity goes, and so do the powers that
        # last a turn (Rage, One-Two Punch).
        for k, amt in self.temp.items():
            self.st[k] -= amt
        self.temp.clear()
        for d in (self.dp, self.rule):
            for pw in [pw for pw in d if PD["powers"].get(pw, {}).get("lasts") == "turn"]:
                del d[pw]
        for pw in [pw for pw in self.rule if PD["powers"][pw].get("endDecays") and self.rule[pw] > 0]:
            self.rule[pw] -= 1  # Double Damage
        keep_all = self.ruled("keepsHand")  # Well-Laid Plans: the hand isn't discarded
        # The hand goes to the discard pile, but for Retain cards and what
        # Expertise drew; Ethereal cards exhaust, and what that draws (Dark
        # Embrace, Joss Paper) waits until after, so it opens next turn.
        keep, ethereal = [], []
        for h in self.hand:
            if h["retain"] or h in self.keep or (keep_all and not h["ethereal"]) or self.tagged("retainsTag", h):
                if h in self.keep:
                    self.keep.remove(h)
                keep.append(h)
            elif h["ethereal"]:
                ethereal.append(h)
            else:
                self.used.append(h)
        self.hand, self.keep = keep, []
        self.last_plays = self.t["played"]
        self.last_dealt = self.t["dealt"]
        self.t["block"] = self.block + self.t["summoned"]  # HP summoned to Osty soaks hits like block
        for f in self.foes:  # Sic 'Em and Oblivion last your turn
            f["sicem"] = f["oblivion"] = 0
        self.exhausted(ethereal)
        lost = self.enemy_turn() + self.t["selfLost"]
        self.lost_last = lost > 0
        return lost

    def intents(self):
        """Damage the living foes mean to deal this turn, or None for dummies."""
        if not any(f["moves"] for f in self.foes):
            return None
        return sum(self.foe_hits(f)[0] for f in self.live())

    def foe_attacks(self, f):
        """f's attacks this turn as (damage per hit, hits), after Weak (half
        under Debilitate), Strength lost or down and Colossus (half from a
        Vulnerable foe)."""
        out = []
        for dmg, hits in f["moves"][f["i"] % len(f["moves"])] if f["moves"] else []:
            per = max(0, dmg + f["str"] - f["strdown"])
            per = int(per * (0.5 if f["debil"] else 0.75)) if f["weak"] else per
            per = int(per * 0.5) if self.st["colossus"] and f["vuln"] else per
            out.append((min(per, 1) if self.st["intangible"] else per, hits))
        return out

    def foe_hits(self, f):
        """(total damage, hit count) f means to deal this turn."""
        atk = self.foe_attacks(f)
        return sum(p * h for p, h in atk), sum(h for _, h in atk)

    def enemy_turn(self):
        ticks = 1 + self.ruled("poisonTicks")  # Accelerant: Poison goes off more than once
        for f in self.live():
            for _ in range(ticks):
                if f["poison"] <= 0 or f["hp"] <= 0:
                    break
                self.hit(f, f["poison"])
                f["poison"] -= 1
        taken = 0
        for f in self.live():
            if f["moves"]:
                for per, hits in self.foe_attacks(f):
                    for _ in range(hits):
                        if f["hp"] <= 0:  # Flame Barrier killed it mid-attack
                            break
                        soak = min(self.block, per)
                        self.block -= soak
                        if soak and self.ruled("reflect"):  # Reflect: what block stops goes back at the attacker
                            self.hit(f, soak)
                        osty = min(per - soak, self.osty["hp"])  # Osty takes the rest of the hit first
                        self.osty_lose(osty)
                        soak += osty
                        lost = max(0, per - soak - self.rel["hp_red"]) if per > soak else 0
                        if lost and self.buffered():
                            lost = 0
                        taken += lost
                        if lost:
                            self.hurt += 1
                            self.trigger("hpLoss")  # Centennial Puzzle: draws into next turn's hand
                        if self.st["flame"] + self.st["thorns"]:  # flat, no Strength
                            self.hit(f, self.st["flame"] + self.st["thorns"])
                f["i"] += 1
        self.doom_kill()  # Doom kills at the end of the enemy turn, after its attacks
        for f in self.live():
            f["weak"], f["vuln"], f["strdown"] = max(0, f["weak"] - 1), max(0, f["vuln"] - 1), 0
            f["strangle"], f["debil"], f["conq"] = 0, max(0, f["debil"] - 1), max(0, f["conq"] - 1)
        self.st["flame"] = 0  # Flame Barrier lasts the enemy turn
        self.st["colossus"] = max(0, self.st["colossus"] - 1)
        self.st["intangible"] = max(0, self.st["intangible"] - 1)
        return taken


def foe(mid):
    m = PD["monsters"].get(mid)
    if not m or not m.get("hpMin"):
        return {"hp": 40, "moves": []}
    hp = (m["hpMin"][0] + (m.get("hpMax") or m["hpMin"])[0]) / 2
    moves = [[(i["dmg"], i["hits"] or 1) for i in mv["intents"] if i.get("dmg")] for mv in m["moves"]]
    return {"hp": hp, "moves": moves or []}


def profile(deck, rel, n_foes, rng, focus, steady=False, turns=TURNS, slots=0):
    per_turn = [Counter() for _ in range(turns)]
    for _ in range(SAMPLES):
        cb = Combat(deck, rel, [{"hp": INF, "moves": []}] * n_foes, rng, steady, focus, slots)
        for t in range(turns):
            cb.turn(t + 1)
            per_turn[t].update(cb.t)
    return [{k: v / SAMPLES for k, v in c.items()} for c in per_turn]


def growth(rows, k):
    """Per-turn growth of k from turn 2 on: the slope of a straight line
    through it (turn 1 has its own opening draw)."""
    ys = [r.get(k, 0) for r in rows[1:]]
    mx, my = (len(ys) - 1) / 2, sum(ys) / len(ys)
    return sum((x - mx) * (y - my) for x, y in enumerate(ys)) / sum((x - mx) ** 2 for x in range(len(ys)))


def encounter_shape(mids):
    """How the fight hits you: hits per enemy turn, average and biggest hit."""
    hits = dmg = biggest = 0
    for mid in mids:
        moves = foe(mid)["moves"]
        if not moves:
            continue
        for mv in moves:
            for d, h in mv:
                hits += h / len(moves)
                dmg += d * h / len(moves)
                biggest = max(biggest, d)
    return {"hitsPerTurn": round(hits, 1), "dmgPerTurn": round(dmg, 1),
            "avgHit": round(dmg / hits, 1) if hits else 0, "maxHit": biggest,
            "hp": round(sum(foe(m)["hp"] for m in mids))}


def links(deck_ids, relic_ids):
    prod, cons = defaultdict(set), defaultdict(set)
    for cid in set(deck_ids):
        p, name = PD["cards"].get(cid, {}), CD.get(cid, {}).get("title", cid)
        for k in p.get("produces", []):
            prod[k].add(name)
        for k in p.get("consumes", []):
            cons[k].add(name)
        t = CD.get(cid, {}).get("type")
        if t in ("Attack", "Skill", "Power"):
            prod[t.lower() + "s"].add(name)
        if "SHIV" in p.get("makes", []):
            prod["attacks"].add(name)
    for rid in set(relic_ids):
        p, name = PD["relics"].get(rid, {}), RD.get(rid, {}).get("title", rid)
        for k in p.get("produces", []):
            prod[k].add(name)
        for k in p.get("consumes", []):
            cons[k].add(name)
    out = {}
    for k, users in cons.items():
        # A link needs someone else to feed it: Outbreak reading its own
        # Poison isn't one.
        feeders = {p for p in prod[k] if users - {p}}
        if feeders and k != "strike":
            out[k] = (sorted(feeders), sorted(users))
    return out


def curve(data, steam_id=None):
    """The power curve of one parsed .run, for the uploader's seat in co-op.
    Floors whose deck and relics haven't changed reuse the games already played."""
    idx = run.local_player_index(data, steam_id)
    player = data["players"][idx]
    hist = run.extract_deck_history(data, player, idx)
    cards = [(c["id"], a, INF) for c, a in zip([c for c in player["deck"] if c.get("id")], hist["deckAdded"])]
    cards += [tuple(x) for x in hist["cardsLost"]]
    cards.sort(key=lambda c: c[1])
    relics = [(r["id"], a, INF) for r, a in zip([r for r in player["relics"] if r.get("id")], hist["relicsAdded"])]
    relics += [tuple(x) for x in hist["relicsLost"]]
    nodes = [n for act in data["map_point_history"] for n in act]
    acts = [len(a) for a in data["map_point_history"]]
    upgrades_at = [Counter(run.player_stats_at(n, idx).get("upgraded_cards", [])) for n in nodes]

    def deck_at(f):
        ups = sum(upgrades_at[:f], Counter())
        deck, ids = [], []
        for cid, added, removed in cards:
            if added <= f < removed:
                up = ups[cid] > 0
                ups[cid] -= 1
                deck.append(card(cid, up))
                ids.append(cid)
        return deck, ids

    def relics_at(f):
        return [rid for rid, added, removed in relics if added <= f < removed]

    rng = random.Random(1)
    slots = DEFECT_SLOTS if "DEFECT" in player["character"] else 0  # orb slots (BaseOrbSlotCount)
    floors, fights, first_seen, games = [], [], {}, {}
    for f in range(1, len(nodes) + 1):
        deck, ids = deck_at(f)
        rids = relics_at(f)
        rel = relic_effects(rids)
        # Most floors add nothing: the games of an unchanged deck and relics
        # are played once and reused.
        key = (tuple(sorted((c["id"], c["up"]) for c in deck)), tuple(sorted(rids)))
        if key not in games:
            # One all-in damage game and one all-in block game, so each reads
            # what a hand can put out when that's the plan.
            one, guard = profile(deck, rel, 1, rng, "dmg", slots=slots), profile(deck, rel, 1, rng, "block", slots=slots)
            three = profile(deck, rel, 3, rng, "dmg", slots=slots)
            # Scaling is the growth per turn over a longer game, with Horn Cleat,
            # Candelabra and co. left out: their kick on one turn isn't the deck growing.
            grow_d = profile(deck, rel, 1, rng, "dmg", steady=True, turns=SCALE_TURNS, slots=slots)
            grow_b = profile(deck, rel, 1, rng, "block", steady=True, turns=SCALE_TURNS, slots=slots)
            games[key] = one, guard, three, grow_d, grow_b
        one, guard, three, grow_d, grow_b = games[key]
        lk = links(ids, rids)
        for k, (feeders, users) in lk.items():
            for name in feeders + users:
                first_seen.setdefault((k, name), f)
        avg = lambda rows, k: round(sum(r.get(k, 0) for r in rows) / len(rows), 1)  # noqa: E731
        unmod = sorted({c["title"] for c in deck if not c["modelled"]})
        floors.append({
            "floor": f, "type": nodes[f - 1]["map_point_type"], "deck": len(deck),
            "energy": avg(one, "energy"), "seen": avg(one, "seen"), "played": avg(one, "played"),
            "dmg": avg(one, "dealt"), "dmgT1": round(one[0].get("dealt", 0), 1),
            "dmgGrowth": round(growth(grow_d, "dealt"), 2), "blockGrowth": round(growth(grow_b, "block"), 2),
            "dmgByTurn": [round(t.get("dealt", 0), 1) for t in grow_d],
            "blockByTurn": [round(t.get("block", 0), 1) for t in grow_b],
            "dmg3": avg(three, "dealt"),
            "block": avg(guard, "block"), "relicBlock": avg(guard, "relicBlock"),
            "relicEnergy": avg(one, "relicEnergy"), "relicDealt": avg(one, "relicDealt"),
            "energyByTurn": [round(t.get("energy", 0), 1) for t in one],
            "links": len(lk), "unmodelled": unmod,
        })
        room = (nodes[f - 1].get("rooms") or [{}])[0]
        if room.get("monster_ids"):
            ps = run.player_stats_at(nodes[f - 1], idx)
            fights.append({
                "floor": f, "encounter": room["model_id"].replace("ENCOUNTER.", ""),
                "monsters": [m.replace("MONSTER.", "") for m in room["monster_ids"]],
                **encounter_shape(room["monster_ids"]),
                "turns": room.get("turns_taken"), "taken": ps.get("damage_taken"),
                "potions": [x.replace("POTION.", "") for x in ps.get("potion_used", [])],
            })
    final = links(*[x for x in (deck_at(len(nodes))[1], relics_at(len(nodes)))])
    synergies = [{"key": k, "feeders": [(n, first_seen[(k, n)]) for n in fe],
                  "users": [(n, first_seen[(k, n)]) for n in us],
                  "active": max(min(first_seen[(k, n)] for n in fe), min(first_seen[(k, n)] for n in us))}
                 for k, (fe, us) in final.items()]
    synergies.sort(key=lambda s: s["active"])
    return {"character": player["character"], "acts": acts,
            "floors": floors, "fights": fights, "synergies": synergies}


def main(path, out_path):
    out = {"run": Path(path).name, **curve(json.loads(Path(path).read_text(encoding="utf-8")))}
    Path(out_path).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"{len(out['floors'])} floors, {len(out['fights'])} fights, {len(out['synergies'])} synergy links")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
