"""Three ways to project a run's power per floor, on one median-deck win per
character, scored against the full sim at high samples (the reference):

A  analytic: deck averages, no simulation. Expected hand size from draw
   cards, energy from relics/cards, a fractional knapsack of the average hand
   by damage (or block) per energy, Strength/Dexterity/Focus/Poison ramp from
   the chance each scaling card has been drawn by turn t.
B  lookup: each card's and relic's worth measured offline by the sim (the
   character's starter deck plus that one card), added up per floor.
C  small sim: the current sim at SAMPLES_C per game, as it would run when a
   run is opened.

Usage: python approaches.py [ref|c|b|a|report]  (each stage caches to approaches/)."""
import json
import pickle
import random
import sys
import time
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

import gamma_curves as g
import power_curve as pc

OUT = Path(__file__).parent / "approaches"  # local caches this script writes itself (pickle is safe here)
PICKS = {ch: tuple(v) for ch, v in g.LOCAL.get("picks", {}).items()}  # character: (steam id, start time), from the median-deck solo wins
SAMPLES_REF, SAMPLES_C, SAMPLES_B = 200, 20, 100
AXES = ("energy", "dmg", "dmgT1", "dmg3", "block", "dmgGrowth", "blockGrowth")


def seeded(seed):
    """pc.curve makes its own random.Random(1); give it another seed."""
    orig = random.Random
    pc.random.Random = lambda _=None: orig(seed)
    return orig


def run_data():
    runs = g.load()
    return {ch: (sid, runs[(sid, ts)]) for ch, (sid, ts) in PICKS.items()}


def states(d, sid):
    """Each floor's deck (card dicts), card ids, relic ids, relic effects and
    orb slots, as power_curve.curve builds them."""
    idx = pc.run.local_player_index(d, sid)
    player = d["players"][idx]
    hist = pc.run.extract_deck_history(d, player, idx)
    cards = [(c["id"], a, pc.INF) for c, a in zip([c for c in player["deck"] if c.get("id")], hist["deckAdded"])]
    cards += [tuple(x) for x in hist["cardsLost"]]
    cards.sort(key=lambda c: c[1])
    relics = [(r["id"], a, pc.INF) for r, a in zip([r for r in player["relics"] if r.get("id")], hist["relicsAdded"])]
    relics += [tuple(x) for x in hist["relicsLost"]]
    nodes = [n for act in d["map_point_history"] for n in act]
    ups_at = [Counter(pc.run.player_stats_at(n, idx).get("upgraded_cards", [])) for n in nodes]
    slots = pc.DEFECT_SLOTS if "DEFECT" in player["character"] else 0
    out = []
    for f in range(1, len(nodes) + 1):
        ups = sum(ups_at[:f], Counter())
        deck = []
        for cid, added, removed in cards:
            if added <= f < removed:
                deck.append(pc.card(cid, ups[cid] > 0))
                ups[cid] -= 1
        rids = [rid for rid, added, removed in relics if added <= f < removed]
        out.append((f, deck, rids, slots))
    return out


# ---------------------------------------------------------------- A: analytic
def num(v, default=0):
    return v if isinstance(v, (int, float)) else default


def relic_bits(rel, turns, steady=False):
    """Per-turn energy, extra draw, flat block and starting Strength/Dex/Focus
    out of relic_effects' entries; anything else is left out. steady leaves
    out one-off kicks (Anchor, Bag of Preparation), as the sim's growth games do."""
    energy, draw, block = [0.0] * turns, [0.0] * turns, [0.0] * turns
    stats = Counter()
    energy = [e + len(rel["max_energy"]) for e in energy]
    for e, v in rel["turn"]:
        # The amount a buff grants: a relic that hits both sides carries a var for
        # each (Brimstone: SelfStrength 2, EnemyStrength 1), and the one that counts
        # for us is ours.
        def amount():
            nums = [(k, float(x)) for k, x in v.items()
                    if isinstance(x, (int, float)) and k not in ("Turns", "EnergyGlyph")]
            if not nums:
                return 0.0
            if e.get("side") == "both":
                ours = [(k, x) for k, x in nums if "self" in k.lower()]
                if ours:
                    return ours[0][1]
            return nums[0][1]
        amt = amount()
        if steady and (e.get("until") or (e.get("on") and not e.get("power"))):
            continue
        on = [t for t in range(turns) if (not e.get("on") or t + 1 == pc.bound(e["on"], v)) and (not e.get("until") or t < pc.bound(e["until"], v))
              and (not v.get("Turns") or (t + 1) % int(v["Turns"]) == 0)]
        if e.get("energy"):
            for t in on:
                energy[t] += amt
        elif e.get("block"):
            for t in on:
                block[t] += amt
        elif e.get("power") in ("Strength", "Dexterity", "Focus"):
            if e.get("on") == 1:
                stats[e["power"]] += amt
            elif not e.get("on") and not e.get("until"):
                # Every turn, so it accumulates: +2 a turn is +2, then +4, then +6.
                # What the damage line wants is the average bonus over a fight, which
                # is amt x (turns + 1) / 2 -- not amt, and not nothing.
                stats[e["power"]] += amt * (turns + 1) / 2
    for e, v in rel["hand"]:
        if steady and e.get("until"):
            continue
        amt = float(v.get("Cards", 0))
        for t in range(turns):
            if not e.get("until") or t < pc.bound(e["until"], v):  # "until" can name a var (Turns)
                draw[t] += amt
    return energy, draw, block, stats


def analytic(deck, rids, slots, turns, steady=False):
    """Per-turn damage (1 and 3 foes), block and energy from deck averages."""
    rel = pc.relic_effects(rids)
    r_energy, r_draw, r_block, r_stats = relic_bits(rel, turns, steady)
    n = max(len(deck), 1)
    live = [c for c in deck if not c["dead"]]
    cost = lambda c: 3 if c["x"] else c["cost"]  # noqa: E731
    draws = lambda c: 5 if c["draw"] == "fullHand" else num(c["draw"])  # noqa: E731
    # Scaling cards: what each gives once drawn (Inflame) or every turn after (Demon Form).
    ramp = []  # (card, stat, once, per_turn)
    for c in live:
        for pw, (side, amt) in c["applies"].items():
            amt = num(amt, 1)
            if side == "self" and pw in ("Strength", "Dexterity", "Focus"):
                ramp.append((c, pw, amt, 0))
            elif side == "self":
                for e in pc.turn_power(pw):
                    if e.get("power") in ("Strength", "Dexterity", "Focus"):
                        ramp.append((c, e["power"], 0, amt))
    # Powers that act every turn once played: (card, axis, amount per turn, builds up)
    # Plating's block, Noxious Fumes' poison (it piles up), Lightning Rod's and
    # Spinner's orbs, Hailstorm's hit with Frost about, Countdown's Doom.
    per_turn = []
    frost = any(op["orb"] == "Frost" for c in live for op in c["orb_ops"])
    for c in live:
        for pw, (side, amt) in c["applies"].items():
            amt = num(amt, 1)
            if side != "self":
                continue
            for e in pc.PD["powers"].get(pw, {}).get("turnEffects", []):
                if e.get("block"):
                    per_turn.append((c, "block", amt, False))
                elif e.get("power") == "Poison":
                    per_turn.append((c, "dmg", amt, True))
                elif e.get("power") == "Doom" and e.get("side") == "enemy":  # Countdown
                    per_turn.append((c, "dmg", amt, False))
            for h in pc.PD["powers"].get(pw, {}).get("orbHooks", []):
                n = num(h.get("n"), amt) if h.get("n") != "Amount" else amt
                if h.get("channel") == "Lightning":
                    per_turn.append((c, "dmg", 3 * n, True))
                elif h.get("channel") == "Glass":
                    per_turn.append((c, "dmg", 4 * n, True))
                elif h.get("aoe") and frost:
                    per_turn.append((c, "aoe", amt, False))
                elif h.get("passiveFirst"):
                    per_turn.append((c, "dmg", 3 * amt, False))
    rows = []
    for t in range(turns):
        hand = 5 + r_draw[t]
        for _ in range(4):  # draw cards draw more: settle the hand size
            share = min(hand, n) / n
            hand = min(10, n, 5 + r_draw[t] + sum(draws(c) * share for c in live if cost(c) <= 1))
        share = min(hand, n) / n
        drawn_by = lambda k: min(1.0, (k + 1) * share)  # noqa: E731  # P(a card was drawn by turn k)
        energy = 3 + r_energy[t] + sum(num(c["energy"]) * share for c in live)
        st = Counter(r_stats)
        spent = 0.0
        for c, stat, once, per in ramp:
            st[stat] += once * drawn_by(t) + per * sum(drawn_by(k) for k in range(t))
            spent += cost(c) * (drawn_by(t) - (drawn_by(t - 1) if t else 0))  # played the turn it's drawn
        res = {"energy": energy}
        extra = Counter()
        for c, ax, amt, builds in per_turn:  # in play from the turn after it's drawn
            on = sum(drawn_by(k) for k in range(t)) if builds else drawn_by(t - 1) if t else 0
            if ax == "aoe":
                extra["dmg"] += amt * on
                extra["dmg3"] += 3 * amt * on
            else:
                extra[ax] += amt * on
                if ax == "dmg":
                    extra["dmg3"] += amt * on
        for focus, foes in (("dmg", 1), ("dmg3", 3), ("block", 1)):
            items = []
            for c in live:
                if c["type"] == "Power" or (focus != "block" and c["applies"].get("Strength")):
                    continue  # the ramp above has these
                if focus == "block":
                    v = (c["block"] + st["Dexterity"]) * (c["hits"] if c["block_per"] else 1) if c["blocker"] else 0
                    v += num(c["summon"]) * (energy if c["x"] else 1)  # Osty soaks hits, as the sim counts it
                    v += sum((2 + st["Focus"]) * pc.ORB_TICKS * num(op["n"], 1) for op in c["orb_ops"]
                             if op["op"] == "channel" and op["orb"] == "Frost")
                else:
                    hits = num(c["hits"], 1) * (foes if c["aoe"] else 1)
                    v = (c["dmg"] + st["Strength"]) * hits if c["hitter"] else 0
                    v += num(c["shivs"]) * (4 + st["Strength"])
                    pois = c["applies"].get("Poison")
                    v += num(pois[1], 0) * 2.5 if pois else 0
                    doom = c["applies"].get("Doom")  # damage to come, as the sim counts it
                    v += num(doom[1], 0) * (foes if c["aoe"] else 1) if doom and doom[0] != "self" else 0
                    for op in c["orb_ops"]:
                        k = num(op["n"], 1) * num(op["times"], 1)
                        if op["op"] == "channel" and op["orb"] == "Lightning":
                            v += k * (3 + st["Focus"]) * pc.ORB_TICKS
                        elif op["op"] == "channel" and op["orb"] == "Dark":
                            v += k * 6
                        elif op["op"] == "evoke":
                            v += k * (8 + st["Focus"])
                    if c["x"]:
                        v *= energy
                if v > 0:
                    items.append((v, cost(c), share))
            budget = max(0.0, energy - spent)
            total = 0.0
            for v, k, amt in sorted(items, key=lambda i: -i[0] / max(i[1], 0.25)):
                if k == 0:
                    total += v * amt
                    continue
                take = min(amt, budget / k)
                total += v * take
                budget -= take * k
                if budget <= 0:
                    break
            res[focus] = total + extra[focus] + (r_block[t] if focus == "block" else 0)
        rows.append(res)
    return rows


def floor_a(deck, rids, slots):
    one = analytic(deck, rids, slots, pc.TURNS)
    grow = analytic(deck, rids, slots, pc.SCALE_TURNS, steady=True)
    avg = lambda k: sum(r[k] for r in one) / len(one)  # noqa: E731
    return {"energy": avg("energy"), "dmg": avg("dmg"), "dmgT1": one[0]["dmg"], "dmg3": avg("dmg3"),
            "block": avg("block"), "dmgGrowth": pc.growth([{"d": r["dmg"]} for r in grow], "d"),
            "blockGrowth": pc.growth([{"b": r["block"]} for r in grow], "b")}


# ---------------------------------------------------------------- B: lookup
def measure(deck, rids, slots):
    """The five profile games of power_curve.curve, as one floor's numbers."""
    rel = pc.relic_effects(rids)
    rng = random.Random(1)
    one, guard = pc.profile(deck, rel, 1, rng, "dmg", slots=slots), pc.profile(deck, rel, 1, rng, "block", slots=slots)
    three = pc.profile(deck, rel, 3, rng, "dmg", slots=slots)
    gd = pc.profile(deck, rel, 1, rng, "dmg", steady=True, turns=pc.SCALE_TURNS, slots=slots)
    gb = pc.profile(deck, rel, 1, rng, "block", steady=True, turns=pc.SCALE_TURNS, slots=slots)
    avg = lambda rows, k: sum(r.get(k, 0) for r in rows) / len(rows)  # noqa: E731
    return {"energy": avg(one, "energy"), "dmg": avg(one, "dealt"), "dmgT1": one[0].get("dealt", 0),
            "dmg3": avg(three, "dealt"), "block": avg(guard, "block"),
            "dmgGrowth": pc.growth(gd, "dealt"), "blockGrowth": pc.growth(gb, "block")}


def b_job(job):
    kind, key, base_deck, base_rids, slots = job
    pc.SAMPLES = SAMPLES_B
    t = time.time()
    if kind == "base":
        m = measure(base_deck, base_rids, slots)
    elif kind == "card":
        m = measure(base_deck + [pc.card(*key)], base_rids, slots)
    else:
        m = measure(base_deck, base_rids + [key], slots)
    return kind, key, m, time.time() - t


def floor_b(deck, rids, table):
    """Cards: a per-copy worth w = ((N0+1)·V(starter+card) - N0·V(starter)) / 5,
    and a deck of N gives 5/N of the worths it holds. Relics add their
    measured difference."""
    base, n0 = table["base"], table["n0"]
    out = {}
    for k in AXES:
        w = sum(((n0 + 1) * table["card"][(c["id"], c["up"])][k] - n0 * base[k]) / 5 for c in deck)
        v = 5 * w / max(len(deck), 1)
        v += sum(table["relic"][r][k] - base[k] for r in rids if r not in table["base_rids"])
        out[k] = v
    return out


# ---------------------------------------------------------------- stages
def ref_job(ch_seed_samples):
    ch, seed, samples = ch_seed_samples
    sid, d = run_data()[ch]
    pc.SAMPLES = samples
    orig = seeded(seed)
    t = time.time()
    res = pc.curve(d, sid)
    pc.random.Random = orig
    return ch, res["floors"], time.time() - t


def stage_sim(name, seed, samples):
    with Pool(5) as p:
        res = p.map(ref_job, [(ch, seed, samples) for ch in PICKS])
    (OUT / f"{name}.pkl").write_bytes(pickle.dumps({ch: (fl, el) for ch, fl, el in res}))
    for ch, _, el in res:
        print(name, ch, f"{el:.1f}s", flush=True)


def stage_b():
    data = run_data()
    jobs, meta = [], {}
    for ch, (sid, d) in data.items():
        st = states(d, sid)
        _, base_deck, base_rids, slots = st[0]
        meta[ch] = (len(base_deck), base_rids)
        cards = sorted({(c["id"], c["up"]) for _, deck, _, _ in st for c in deck})
        rels = sorted({r for _, _, rids, _ in st for r in rids} - set(base_rids))
        jobs += [(ch, ("base", None, base_deck, base_rids, slots))]
        jobs += [(ch, ("card", k, base_deck, base_rids, slots)) for k in cards]
        jobs += [(ch, ("relic", r, base_deck, base_rids, slots)) for r in rels]
    t = time.time()
    with Pool(11) as p:
        res = p.map(b_job, [j for _, j in jobs])
    wall = time.time() - t
    tables = {ch: {"card": {}, "relic": {}, "n0": meta[ch][0], "base_rids": meta[ch][1], "cpu": 0.0, "n": 0}
              for ch in PICKS}
    for (ch, _), (kind, key, m, el) in zip(jobs, res):
        tb = tables[ch]
        tb["cpu"] += el
        tb["n"] += 1
        if kind == "base":
            tb["base"] = m
        else:
            tb[kind][key] = m
    (OUT / "b.pkl").write_bytes(pickle.dumps(tables))
    for ch, tb in tables.items():
        print("B", ch, f"{tb['n']} measurements, {tb['cpu']:.0f} CPU-s", flush=True)
    print(f"B wall {wall:.0f}s on 11 workers")


def corr(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy) if sx and sy else float("nan")


def score(pred, ref, k):
    xs, ys = [p[k] for p in pred], [r[k] for r in ref]
    err = sum(abs(x - y) for x, y in zip(xs, ys)) / max(sum(abs(y) for y in ys), 1e-9)
    dx = [b - a for a, b in zip(xs, xs[1:])]
    dy = [b - a for a, b in zip(ys, ys[1:])]
    return corr(xs, ys), corr(dx, dy), err


def stage_report():
    ref = pickle.loads((OUT / "ref.pkl").read_bytes())
    ref2 = pickle.loads((OUT / "ref2.pkl").read_bytes()) if (OUT / "ref2.pkl").exists() else None
    c = pickle.loads((OUT / "c.pkl").read_bytes())
    tables = pickle.loads((OUT / "b.pkl").read_bytes())
    data = run_data()
    report = {}
    for ch, (sid, d) in data.items():
        st = states(d, sid)
        t = time.time()
        a = [floor_a(deck, rids, slots) for _, deck, rids, slots in st]
        ta = time.time() - t
        t = time.time()
        b = [floor_b(deck, rids, tables[ch]) for _, deck, rids, _ in st]
        tb = time.time() - t
        r = ref[ch][0]
        rows = {"A": (a, ta), "B": (b, tb), "C": (c[ch][0], c[ch][1])}
        if ref2:
            rows["ref noise"] = (ref2[ch][0], ref2[ch][1])
        report[ch] = {"ref_s": ref[ch][1], "b_cpu": tables[ch]["cpu"], "b_n": tables[ch]["n"],
                      "floors": {"ref": r, **{k: v[0] for k, v in rows.items()}}, "scores": {}}
        print(f"\n== {ch}  ({len(st)} floors; ref {ref[ch][1]:.0f}s at {SAMPLES_REF} samples; "
              f"B offline {tables[ch]['n']} measurements = {tables[ch]['cpu']:.0f} CPU-s)")
        print(f"{'':10}{'time/run':>10} " + " ".join(f"{k:>18}" for k in AXES))
        for name, (pred, el) in rows.items():
            sc = {k: score(pred, r, k) for k in AXES}
            report[ch]["scores"][name] = {"time": el, **{k: v for k, v in sc.items()}}
            print(f"{name:10}{el:>9.3f}s " + " ".join(f"r{v[0]:+.2f} d{v[1]:+.2f} e{v[2]:.2f}".rjust(18) for v in sc.values()))
    (OUT / "report.json").write_text(json.dumps(report, default=list), encoding="utf-8")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    stage = sys.argv[1] if len(sys.argv) > 1 else "report"
    if stage == "ref":
        stage_sim("ref", 1, SAMPLES_REF)
    elif stage == "ref2":
        stage_sim("ref2", 3, SAMPLES_REF)
    elif stage == "c":
        stage_sim("c", 2, SAMPLES_C)
    elif stage == "b":
        stage_b()
    else:
        stage_report()
