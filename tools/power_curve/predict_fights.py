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
import statistics
import sys
import time
import zlib
from collections import Counter, defaultdict

import approaches as ap
import fights_vs_setup as fv
import power_curve as pc

num = ap.num
FORMULA = ["f_dmg", "f_block", "f_dex", "f_turnblock", "f_frost", "f_summon", "f_str", "f_dot", "f_junk", "f_seen", "f_energy"]


def card_row(c):
    """What the formula needs from one card, as plain numbers (zeros left out),
    so the site's js/deck-strength.js can run the same sums on the same rows."""
    if c["dead"]:
        return {"x": 1}  # junk: only counts toward deck size
    r = Counter({
        "p": c["type"] == "Power",
        "c": 3 if c["x"] else max(c["cost"], 0),
        "d": 5 if c["draw"] == "fullHand" else num(c["draw"]),
        "e": num(c["energy"]),
        "b": c["block"] * (num(c["hits"], 1) if c["block_per"] else 1) if c["blocker"] else 0,
        "h": (c["dmg"] * num(c["hits"], 1) if c["hitter"] else 0) + 4 * num(c["shivs"]),
        "n": num(c["hits"], 1) if c["hitter"] else 0,  # hits per play; 0 if not an attack
    })
    for pw, (side, amt) in c["applies"].items():
        if side != "self":
            continue
        amt, p = num(amt, 1), pc.PD["powers"].get(pw, {})
        for m in p.get("mods", []):
            if m.get("op") == "add" and m.get("stat") == "block":
                r["dx"] += amt
            elif m.get("op") == "add" and m.get("stat") == "damage":
                r["st"] += amt
        for e in p.get("turnEffects", []):
            if e.get("block"):
                r["tb"] += amt
            elif e.get("power") == "Poison":
                r["fu"] += amt
    pois = c["applies"].get("Poison")
    if pois and pois[0] == "enemy":
        r["po"] += num(pois[1], 0)
    r["fr"] += sum(num(op["n"], 1) for op in c["orb_ops"] if op["op"] == "channel" and op["orb"] == "Frost")
    r["su"] += num(c["summon"])
    return {k: (int(v) if isinstance(v, bool) else v) for k, v in r.items() if v}


def relic_block(rid, turns=pc.TURNS):
    """A relic's block per turn (Anchor, Horn Cleat, Orichalcum...). Relics add up."""
    return sum(ap.relic_bits(pc.relic_effects([rid]), turns)[2]) / turns


def relic_energy(rid, turns=pc.TURNS):
    """A relic's energy per turn (Blood-Soaked Rose, Sozu, a bigger energy pool).
    Relics add up."""
    return sum(ap.relic_bits(pc.relic_effects([rid]), turns)[0]) / turns


def formula(deck, rids, turns=pc.TURNS):
    bits = [ap.relic_bits(pc.relic_effects([r]), turns) for r in rids]
    return formula_rows([card_row(c) for c in deck],
                        sum(b[2] for b in bits) / turns, sum(b[0] for b in bits) / turns, turns)


def formula_rows(rows, relic_blk, relic_energy, turns=pc.TURNS):
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
    energy = 3 + relic_energy + sum(g(r, "e") for r in live) * share
    on = sum(min(1, k * share) for k in range(turns)) / turns  # a Power's share of turns in play: from the turn after it's drawn

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
    live_share = lambda r: on if g(r, "p") else share  # noqa: E731  # a Skill's buff (Blur) only on the turn it's played
    return {
        "f_dmg": d_played * d_avg, "f_block": b_played * b_avg,
        "f_dex": sum(g(r, "dx") * live_share(r) for r in live) * b_played,
        "f_turnblock": sum(g(r, "tb") for r in live) * on + relic_blk,
        "f_frost": sum(g(r, "fr") for r in live) * share,
        "f_summon": sum(g(r, "su") for r in live) * share,
        "f_str": sum(g(r, "st") * live_share(r) for r in live) * attacks,
        "f_dot": sum(g(r, "fu") for r in live) * on * turns / 2 + sum(g(r, "po") for r in live) * share * 2.5,
        "f_junk": n - len(live), "f_seen": seen, "f_energy": energy,
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
