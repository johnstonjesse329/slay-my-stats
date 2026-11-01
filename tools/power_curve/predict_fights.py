"""Which measure of a deck best predicts how its real fights went?

For every fight in gamma's runs, the deck that walked in is measured several
ways, and each set of measures is fitted (least squares) to the damage taken
and turns, as the gap from that encounter's average. Fits are made on half the
runs and scored on the other half, then the other way round: the share of the
gap each set explains, beside who played, on what ascension, in which act.

  sim       power_curve's dummy games (pcs/): damage, block, 3-foe damage, growth
  averages  approaches.py's A: the same numbers from deck averages, no games
  formula   damage and block from the cards a turn sees, as many as the energy
            pays for, plus what builds on them (Strength, Dexterity, Plating,
            block relics, poison, Frost, Osty), each its own number. 0.06 ms a deck.

Setup count, deck size, Unmovable, Barricade and on-play block (Afterimage,
Feel No Pain) were tried in the formula too: none helped on the held-out half.

    python predict_fights.py [pcs dir]
"""
import os
import statistics
import sys
import time
import zlib
from collections import Counter, defaultdict

import approaches as ap
import fights_vs_setup as fv
import power_curve as pc

num = ap.num
FORMULA = ["f_dmg", "f_block", "f_dex", "f_turnblock", "f_frost", "f_summon", "f_str", "f_dot", "f_vuln", "f_weak",
           "f_junk", "f_seen", "f_energy"]
VULN_MULT = 0.5   # Vulnerable: the enemy takes half again
WEAK_MULT = 0.25  # Weak: the enemy deals a quarter less
SHIV_DMG = 4      # what a Shiv deals before anything lifts it (CARD.SHIV in the game data)
EFFECTS = ("h", "b", "e", "et", "d", "dx", "st", "tb", "sh", "fu", "po", "vu", "wk", "fr", "su",
           "bpc", "bpa", "dpc", "dpa", "epc", "epa", "epp", "xpa", "spa", "tm", "sv", "sb")

# Trigger vocabulary: what a card or relic pays per event, keyed by the event it
# counts. One set of keys for both, so any effect of the shape "per card played",
# "per attack played" or "per power played" is modelled the same way, whatever
# the deck does to make those events frequent.
TRIGGERS = {
    ("block", "card"): "bpc", ("block", "attack"): "bpa",
    ("damage", "card"): "dpc", ("damage", "attack"): "dpa",
    ("energy", "card"): "epc", ("energy", "attack"): "epa", ("energy", "power"): "epp",
    ("DexterityPower", "attack"): "xpa", ("StrengthPower", "attack"): "spa",
}
EVENT_OF_TYPE = {None: "card", "Attack": "attack", "Power": "power", "Skill": "card"}


def numeric_row(c):
    """What can be read off one card, as plain numbers (zeros left out)."""
    if c["dead"]:
        return {"x": 1}  # junk: only counts toward deck size
    r = Counter({
        "p": c["type"] == "Power",
        "c": 3 if c["x"] else max(c["cost"], 0),
        "d": 5 if c["draw"] == "fullHand" else num(c["draw"]),
        "e": num(c["energy"]),
        "b": c["block"] * (num(c["hits"], 1) if c["block_per"] else 1) if c["blocker"] else 0,
        # Damage generated mid-turn is not this card's damage. A card that adds three
        # Shivs used to carry their 12 as its own, which hid the thing that makes a
        # Shiv deck work: the shivs are played with the turn's spare energy, and every
        # Accuracy stack lifts each of them.
        "h": c["dmg"] * num(c["hits"], 1) if c["hitter"] else 0,
        "n": num(c["hits"], 1) if c["hitter"] else 0,  # hits per play; 0 if not an attack
        "sh": num(c["shivs"]),  # Shivs this card puts in hand: extra cards played a turn
    })
    for pw, (side, amt) in c["applies"].items():
        amt, p = num(amt, 1), pc.PD["powers"].get(pw, {})
        # A Power that changes how much Vulnerable or Weak is worth. Checked before the
        # side filter because Debilitate lands on the enemy while Cruelty and Tracking
        # sit on us -- all three change the damage we deal. The game data carried these
        # and the cheap formula ignored them, so a deck with Cruelty read as if its
        # Vulnerable were the plain 50%.
        if p.get("vulnBonus"):
            r["vb"] += amt / 100        # Cruelty: Vulnerable takes Amount% more
        if p.get("weakBonus"):
            r["wb"] += amt / 100        # Tracking: Amount% more on a Weak foe
        if p.get("debuffDouble"):
            r["vd"] += amt              # Debilitate: "twice as effective" for N turns
        if side != "self":
            continue
        for m in p.get("mods", []):
            if m.get("op") == "add" and m.get("stat") == "block":
                r["dx"] += amt
            elif m.get("op") == "add" and m.get("stat") == "damage":
                # Accuracy and Phantom Blades read exactly like Strength in the data
                # -- an additive damage modifier -- but they lift *Shivs*, not every
                # attack, and a Shiv deck's whole output is Shivs. `consumes: [shiv]`
                # is what tells them apart.
                if "shiv" in (p.get("consumes") or []):
                    if p.get("firstTagBonus"):
                        r["sb"] += amt      # Phantom Blades: the first Shiv a turn
                    else:
                        r["sv"] += amt      # Accuracy: every Shiv
                else:
                    r["st"] += amt
        # A Power that hands you a Shiv every turn (Infinite Blades) is a Shiv a turn
        # for as long as it is up, which nothing above was reading.
        if p.get("turnMakes") == "SHIV":
            r["tm"] += 1
        for e in p.get("turnEffects", []):
            if e.get("block"):
                r["tb"] += amt
            elif e.get("power") == "Poison":
                r["fu"] += amt
            elif e.get("energy"):
                r["et"] += amt  # Charge Battery and friends: energy on the next turn
        # A Power that raises your energy ceiling rather than firing an effect
        # (Pyre): worth that much energy every turn it is up. It carries maxEnergy
        # instead of a turnEffect, so nothing above saw it at all.
        if isinstance(p.get("maxEnergy"), int) and p["maxEnergy"] > 0:
            r["et"] += amt
        for t in p.get("triggers") or []:
            # Whatever the card pays per event -- Afterimage's block per card
            # played, Rage's per attack, Panache's damage every fifth card -- goes
            # in under the event it counts, so the deck's own rate of those events
            # is what makes it big.
            if t.get("on") != "play":
                continue
            event = EVENT_OF_TYPE.get(t.get("type"), "card")
            every = num(t.get("every"), 1) or 1
            for stat, key in TRIGGERS.items():
                # The event has to be the one this key counts, or Rage's block per
                # attack is also booked as block per card and every trigger is paid
                # twice over. `event` was computed and never compared, so it was.
                if not t.get(stat[0]) or stat[1] != event:
                    continue
                # A block payment goes into the block line whether or not the fit
                # is using trigger terms, so it has to be paid on every play. A
                # trigger carrying a condition -- DanseMacabre's cost floor, Spirit
                # of Ash's Ethereal keyword -- pays some plays and not others, and a
                # deck's play count cannot say how many. Counting those as
                # unconditional would inflate the line.
                if key in ("bpc", "bpa") and set(t) - {"block", "on", "type", "snapshot", "every"}:
                    continue
                r[key] += amt / every
    pois = c["applies"].get("Poison")
    if pois and pois[0] == "enemy":
        r["po"] += num(pois[1], 0)
    for pw, key in (("Vulnerable", "vu"), ("Weak", "wk")):
        eff = c["applies"].get(pw)
        if eff and eff[0] == "enemy":
            r[key] += num(eff[1], 1)
    r["fr"] += sum(num(op["n"], 1) for op in c["orb_ops"] if op["op"] == "channel" and op["orb"] == "Frost")
    r["su"] += num(c["summon"])
    return {k: (int(v) if isinstance(v, bool) else v) for k, v in r.items() if v}


def readable(row):
    """False when nothing landed in the row: the game data doesn't say what the
    card does, so the formula can't read it. Junk is readable (as junk)."""
    return bool(row.get("x")) or any(k in row for k in EFFECTS)


# --- What a card the parser can't read is worth ---------------------------------
#
# 189 live cards carry no number the formula can use: their effect is a named
# Power the game data leaves empty (Barricade, Buffer, Apparition), a trigger,
# or a wrapped action (Alchemize). Modelling each by hand doesn't scale, so an
# unreadable card is scored as a typical card of the same shape -- same type,
# same cost, helping with the same things -- taken from the cards that can be
# read. It is a guess, and it is marked with "u" so the coverage reports can
# count guesses rather than read numbers.

_priors = {}


def _shape(c):
    helps = tuple(sorted(c.get("helps") or ()))
    return (c["type"], 3 if c["x"] else max(c["cost"], 0), helps)


def _prior_groups():
    """Readable cards grouped by shape, built once over the whole pool."""
    if "_groups" not in _priors:
        _priors["_groups"] = None  # building: a prior can't ask for one yet
        groups = defaultdict(list)
        for cid in pc.CD:
            cc = pc.card(cid, False)
            row = numeric_row(cc)
            if readable(row):
                groups[_shape(cc)].append(row)
        _priors["_groups"] = groups
    return _priors["_groups"]


def _prior(c):
    """What a card the game data can't describe is worth, as a typical readable
    card of the same type, cost and job: an Attack that helps damage borrows the
    median hit of Attacks at its cost, a Skill that helps block the median block
    of Skills, a Power that helps block the median per-turn block of Powers. One
    number, never a row of them: handing a card every stat an average row
    carries invented damage and energy for Barricade, and made the fit worse.
    A card that helps with neither (Alchemize's potion) keeps its shape only."""
    key = _shape(c)
    if key in _priors:
        return _priors[key]
    groups = _prior_groups()
    type_, cost, helps = key
    same_cost = [r for s, rs in groups.items() if s[0] == type_ and s[1] == cost for r in rs]
    same_type = [r for s, rs in groups.items() if s[0] == type_ for r in rs]
    job = "dmg" if "dmg" in helps else "block" if "block" in helps else None
    stats = {("Attack", "dmg"): ["h"], ("Attack", "block"): ["b"],
             ("Skill", "dmg"): ["h"], ("Skill", "block"): ["b"],
             ("Power", "dmg"): ["st", "h"], ("Power", "block"): ["tb", "dx"]}.get((type_, job), [])
    out = {"u": 1, "c": 3 if c["x"] else max(c["cost"], 0)}
    if type_ == "Power":
        out["p"] = 1  # still a Power: it counts from the turn after it's drawn
    if type_ == "Attack":
        out["n"] = 1
    for stat in stats:
        for rows in (same_cost, same_type):
            vals = [r[stat] for r in rows if r.get(stat)]
            if len(vals) >= 5:
                out[stat] = round(statistics.median(vals), 2)
                break
        if stat in out:
            break
    _priors[key] = out
    return out


def card_row(c):
    """What the formula needs from one card, as plain numbers (zeros left out),
    so the site's js/deck-strength.js can run the same sums on the same rows.
    A card the game data can't describe gets its shape's prior, marked "u", when
    PF_PRIORS is set; the prior measured a wash, so it is off by default."""
    row = numeric_row(c)
    if readable(row) or not os.environ.get("PF_PRIORS"):
        return row
    return _prior(c)


def relic_block(rid, turns=pc.TURNS):
    """A relic's block per turn (Anchor, Horn Cleat, Orichalcum...). Relics add up."""
    return sum(ap.relic_bits(pc.relic_effects([rid]), turns)[2]) / turns


def relic_energy(rid, turns=pc.TURNS):
    """A relic's energy per turn (Blood-Soaked Rose, Sozu, a bigger energy pool).
    Relics add up."""
    return sum(ap.relic_bits(pc.relic_effects([rid]), turns)[0]) / turns


def relic_triggers(rid):
    """A relic's per-event payments, in the same vocabulary as a card's: Kunai's
    Dexterity per attack, Shuriken's Strength, Ornamental Fan's block, Kusarigama's
    damage, Art of War's and Nunchaku's energy. These scale with how many attacks
    a turn the deck makes, which is what any attack-heavy deck does and a slow one
    doesn't -- the synergy the per-turn numbers can't see."""
    out = Counter()
    for n, _tags, v in pc.relic_effects([rid]).get("per_attacks") or []:
        every = num(n, 1) or 1
        for stat, key in TRIGGERS.items():
            # The relic's own vars capitalise theirs: Ornamental Fan pays "Block",
            # Kusarigama "Damage". Reading only the lowercase spelling silently
            # dropped both, so a deck with those relics looked like it gained
            # nothing per attack -- and against its measured fights it gained a lot.
            amount = v.get(stat[0], v.get(stat[0].capitalize()))
            if stat[1] == "attack" and amount:
                out[key] += amount / every
    return out


def formula(deck, rids, turns=pc.TURNS):
    bits = [ap.relic_bits(pc.relic_effects([r]), turns) for r in rids]
    trig = Counter()
    for r in rids:
        trig.update(relic_triggers(r))
    # Relics that grant Strength, Dexterity or Focus are worth damage and block a
    # turn. This Counter used to be computed and then dropped: only block and energy
    # were passed, so Vajra's Strength reached nothing and Brimstone's compounding
    # Strength was invisible.
    stats = Counter()
    for b in bits:
        stats.update(b[3])
    return formula_rows([card_row(c) for c in deck],
                        sum(sum(b[2]) for b in bits) / turns, sum(sum(b[0]) for b in bits) / turns, turns, trig,
                        relic_str=stats.get("Strength", 0.0),
                        relic_dex=stats.get("Dexterity", 0.0),
                        relic_focus=stats.get("Focus", 0.0))


def formula_rows(rows, relic_blk, relic_energy, turns=pc.TURNS, relic_trig=None,
                 relic_str=0.0, relic_dex=0.0, relic_focus=0.0):
    """Per-turn damage and block, each played all-in as the sim's games are:
    the hand's cards for that job, as many as the energy pays for. What builds
    on them (Strength, Dexterity, Plating, block relics...) is its own number,
    so the fit to real fights can weigh each one. js/deck-strength.js is a
    line-for-line copy: change both."""
    g = lambda r, k: r.get(k, 0)  # noqa: E731
    n = max(len(rows), 1)
    live = [r for r in rows if not g(r, "x")]
    seen = min(10, n, 5 * (1 + sum(g(r, "d") for r in live) / n))  # cards a turn sees, draw cards drawing more
    share = seen / n
    on = sum(min(1, k * share) for k in range(turns)) / turns  # a Power's share of turns in play: from the turn after it's drawn
    energy = (3 + relic_energy + sum(g(r, "e") for r in live) * share
              + sum(g(r, "et") for r in live) * on)  # energy cards give a turn, while they're up

    def all_in(key):
        """Per turn: the job's cards in hand, as many as the energy pays for, and their average worth."""
        cards = [(g(r, key), g(r, "c")) for r in live if not g(r, "p") and g(r, key) > 0]
        if not cards:
            return 0.0, 0.0
        in_hand = len(cards) * share
        avg_cost = sum(k for _, k in cards) / len(cards)
        played = min(in_hand, energy / avg_cost) if avg_cost else in_hand
        return played, sum(v for v, _ in cards) / len(cards)

    b_played, b_avg = all_in("b")
    d_played, d_avg = all_in("h")
    hitters = [g(r, "n") for r in live if g(r, "n")]
    attacks = sum(hitters) / max(len(hitters), 1) * d_played
    # Cards played a turn, Shivs included, and the other events a deck can be
    # paid per: attacks played, powers played. Every playable card counts here,
    # skills too, since generating cards is how a Shiv deck gets its volume.
    playable_cost = [g(r, "c") for r in live if not g(r, "p")]
    avg_cost_all = sum(playable_cost) / len(playable_cost) if playable_cost else 0
    cards_turn = (min(seen, energy / avg_cost_all) if avg_cost_all else seen) + sum(g(r, "sh") for r in live) * share
    attacks_turn = d_played
    powers_turn = sum(1 for r in live if g(r, "p")) * share
    # Shivs are the one source of damage a deck does not have to draw: a card adds
    # them to the hand, and a Power adds one a turn. They cost no energy, so the
    # all-in damage above cannot see them at all -- which is how a deck that plays
    # 13 cards a turn for 159 damage read as a deck playing 5 for 30.
    shivs_turn = (sum(g(r, "sh") for r in live) * share + sum(g(r, "tm") for r in live) * on)
    shiv_bonus = sum(g(r, "sv") * (on if g(r, "p") else share) for r in live)
    first_shiv = sum(g(r, "sb") * (on if g(r, "p") else share) for r in live)
    # Triggers are encoded but off by default: every linear version of them
    # measured worse on the decks that carry them (see power_curve_decisions.md).
    # PF_ATK=1 turns them on for the next attempt.
    on_trig = os.environ.get("PF_ATK", "0") == "1"
    rt = (relic_trig or Counter()).get if on_trig else (lambda k, d=0: 0)
    trig = on_trig

    def per(key):
        """What a deck is paid per event, from cards and relics together. A card's
        trigger only pays while the Power is up (live_share); a relic's pays from
        the moment it's held."""
        return sum(g(r, key) * (on if g(r, "p") else share) for r in live) + rt(key, 0)

    def per_block(key):
        """The same, for block, which is counted whether or not the fit is using
        trigger terms. Block paid per card played is a block source like any other,
        and leaving it out made a Silent deck read as if it had no Afterimage: on
        run 1793569704 42% of the block it gained came in one-point payments, at
        one a card. The other events stay behind the flag because they were
        measured as fit terms, not because they aren't real."""
        return sum(g(r, key) * (on if g(r, "p") else share) for r in live) + (relic_trig or Counter()).get(key, 0)
    live_share = lambda r: on if g(r, "p") else share  # noqa: E731  # a Skill's buff (Blur) only on the turn it's played
    return {
        "f_dmg": (d_played * d_avg
                  + shivs_turn * (SHIV_DMG + shiv_bonus)
                  + (first_shiv if shivs_turn > 0 else 0)
                  + (per("dpc") * cards_turn + per("dpa") * attacks_turn if trig else 0)),
        "f_shiv": shivs_turn,
        "f_block": b_played * b_avg,
        "f_dex": sum(g(r, "dx") * live_share(r) for r in live) * b_played + relic_dex * b_played
        + (per("xpa") * attacks_turn * b_played if trig else 0),
        "f_turnblock": sum(g(r, "tb") for r in live) * on + relic_blk
        + per_block("bpc") * cards_turn + per_block("bpa") * attacks_turn,
        "f_frost": sum(g(r, "fr") for r in live) * share,
        "f_summon": sum(g(r, "su") for r in live) * share,
        "f_str": sum(g(r, "st") * live_share(r) for r in live) * attacks + relic_str * attacks
        + (per("spa") * attacks_turn * attacks if trig else 0),
        "f_dot": sum(g(r, "fu") for r in live) * on * turns / 2 + sum(g(r, "po") for r in live) * share * 2.5,
        # Uptime, not stacks: a card applying N turns of Vulnerable a turn keeps it
        # up all fight once N x how often it's played reaches 1.
        "f_vuln": min(1.0, sum(g(r, "vu") for r in live) * share),
        "f_weak": min(1.0, sum(g(r, "wk") for r in live) * share),
        # What Vulnerable and Weak are worth to this deck, which is not always the base
        # 50% and 25%: Cruelty adds to Vulnerable's bonus, Debilitate doubles it while
        # it is on the target, Tracking makes our hits hurt Weak enemies more. The game
        # data has carried all three for a while and nothing consumed them, so a deck
        # with Cruelty read as if its Vulnerable were the plain 50%.
        "f_vuln_bonus": VULN_MULT + sum(g(r, "vb") * live_share(r) for r in live),
        "f_vuln_double": min(1.0, sum(g(r, "vd") * share for r in live)),
        "f_weak_bonus": sum(g(r, "wb") * live_share(r) for r in live),
        "f_junk": n - len(live), "f_seen": seen,
        "f_energy": energy + (per("epp") * powers_turn + per("epa") * attacks_turn + per("epc") * cards_turn if trig else 0),
    }


def main():
    t = time.time()
    data = fv.rows()
    print(f"{len(data)} fights loaded in {time.time() - t:.0f}s")
    by_enc = defaultdict(list)
    for r in data:
        by_enc[r["enc"]].append(r)
    for rs in by_enc.values():
        mt, mn = statistics.mean(r["taken"] for r in rs), statistics.mean(r["turns"] for r in rs)
        for r in rs:
            r["d_taken"], r["d_turns"] = r["taken"] - mt, r["turns"] - mn

    t, cache = time.time(), {}
    for r in data:
        key = (tuple(sorted((c["id"], c["up"]) for c in r["deck"])), tuple(sorted(r["rids"])))
        if key not in cache:
            a = ap.floor_a(r["deck"], r["rids"], r["slots"])
            cache[key] = {**{"a_" + k: v for k, v in a.items()}, **formula(r["deck"], r["rids"])}
        r.update(cache[key])
        for k in ("dmg", "block", "dmg3", "dmgGrowth", "blockGrowth", "energy"):
            r["s_" + k] = r["sim"][k]
    print(f"{len(cache)} distinct decks measured by averages + formula in {time.time() - t:.1f}s\n")

    players = sorted({r["player"] for r in data})
    base = lambda r: [1, r["asc"], r["act"]] + [r["player"] == p for p in players[1:]]  # noqa: E731
    sets = {
        "baseline": [],
        "deck size": ["size"],
        "sim": ["s_dmg", "s_block", "s_dmg3", "s_dmgGrowth", "s_blockGrowth", "s_energy", "size"],
        "averages": ["a_dmg", "a_block", "a_dmg3", "a_dmgGrowth", "a_blockGrowth", "a_energy", "size"],
        "formula": FORMULA,
        "sim + formula": ["s_dmg", "s_block", "s_dmg3", "s_dmgGrowth", "s_blockGrowth", "s_energy", "size"] + FORMULA,
    }
    half = lambda r: zlib.crc32(r["id"].encode()) % 2  # noqa: E731  # whole runs go one side or the other

    def r2(cols, y, rows_of=lambda rs: rs):
        """Fit on one half, score on the other, both ways round; the average."""
        out = []
        for h in (0, 1):
            tr, te = [r for r in data if half(r) == h], rows_of([r for r in data if half(r) != h])
            X = lambda rs: [base(r) + [r[c] for c in cols] for r in rs]  # noqa: E731
            b, m = fv.solve(X(tr), [r[y] for r in tr]), statistics.mean(r[y] for r in te)
            out.append(1 - sum((r[y] - sum(w * x for w, x in zip(b, row))) ** 2 for r, row in zip(te, X(te)))
                       / sum((r[y] - m) ** 2 for r in te))
        return sum(out) / 2

    print("Share of the gap from the encounter's average explained, on the half not fitted to")
    print(f"{'measures':16}{'taken':>8}{'turns':>8}   {'taken, by act':>22}")
    for name, cols in sets.items():
        acts = [r2(cols, "d_taken", lambda rs, a=a: [r for r in rs if r["act"] == a]) for a in (1, 2, 3)]
        print(f"{name:16}{r2(cols, 'd_taken'):>8.3f}{r2(cols, 'd_turns'):>8.3f}   " + " ".join(f"{v:>7.3f}" for v in acts))


if __name__ == "__main__":
    main()
