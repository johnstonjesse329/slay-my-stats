"""Do the Runs page's deck-strength lines track what actually happened?

Walks gamma's runs fight by fight. For every fight, the deck that walked in (the
floor before) is scored with predict_fights.formula, and the four numbers the
Runs page charts -- damage, block, energy and cards a turn -- are set against
that fight's real damage taken and turns. Each encounter's own average is taken
out first, so a boss doesn't read as a bad deck.

Walk-forward on purpose: the deck is the one the player actually had, not the
finished deck read backwards, which is the claim the chart makes.

    aws s3 sync s3://slay-my-stats-gamma-data/raw/ gamma_raw/
    python validate_floors.py

No sim and no pcs/ needed: the run files carry each fight's encounter, damage
taken and turns.

Reports, in order:
  1. each bucket against its counterpart, within encounter (Spearman)
  2. the fitted composite, held out by run: fit on half, score the other half
  3. the floor-to-floor claim -- did a stronger floor mean a better next fight?
  4. calibration: deciles of the composite against real damage taken
  5. the same, split by how much of the deck the model can't see
"""
import json
import statistics
import sys
import time
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

import approaches as ap  # noqa: E402
import fights_vs_setup as fv  # noqa: E402
import gamma_curves as g  # noqa: E402
import power_curve as pc  # noqa: E402
import predict_fights as pf  # noqa: E402
import run  # noqa: E402

MIN_SEEN = 8  # an encounter needs this many fights before its average means anything
FROST = pc.ORB_PASSIVE["Frost"]
EFFECTS = ("h", "b", "e", "d", "dx", "st", "tb", "fu", "po", "fr", "su")


@lru_cache(maxsize=None)
def card_blind(cid, up):
    """True when the model had to guess this card: nothing in the game data says
    what it does, so its row is a prior from cards of the same shape (marked
    "u"). Junk isn't a guess."""
    return bool(pf.card_row(pc.card(cid, up)).get("u"))


@lru_cache(maxsize=None)
def relic_blind(rid):
    """True when a relic gives neither block nor energy a turn, which is all the
    model has room for."""
    return not pf.relic_block(rid) and not pf.relic_energy(rid)


def buckets(feat, size):
    """What js/deck-strength.js draws, in Python: the four per-turn numbers.
    Vulnerable lifts the damage line and Weak the block line, since neither is
    throughput of its own."""
    damage = ((feat["f_dmg"] + feat["f_str"] + feat["f_dot"])
              * (1 + feat["f_vuln_bonus"] * feat["f_vuln"] * (1 + feat["f_vuln_double"]))
              * (1 + feat["f_weak_bonus"] * feat["f_weak"]))
    block = (feat["f_block"] + feat["f_dex"] + feat["f_turnblock"] + feat["f_frost"] * FROST
             + feat["f_summon"]) * (1 + pf.WEAK_MULT * feat["f_weak"])
    return {
        "damage": damage,
        "block": block,
        "energy": feat["f_energy"],
        "draw": feat["f_seen"] * (size - feat["f_junk"]) / max(size, 1),
    }


def fights():
    runs = g.load()
    print(f"{len(runs)} runs in gamma_raw/", flush=True)
    out, cache = [], {}
    t = time.time()
    for i, ((sid, ts), d) in enumerate(runs.items(), 1):
        try:
            parsed = run.parse_run_data(d, steam_id=sid, fallback_ts=ts)
            st = ap.states(d, sid)
        except Exception as e:  # a prototype: skip what doesn't parse, say so at the end
            print(f"  skipped {sid}-{ts}: {type(e).__name__}: {e}")
            continue
        for node in parsed.get("timeline") or []:
            floor = node["floor"] + 1
            if not node.get("enc") or not node.get("turns") or floor < 2 or floor - 2 >= len(st):
                continue
            _, deck, rids, _ = st[floor - 2]  # the deck that walked into the fight
            key = (tuple(sorted((c["id"], c["up"]) for c in deck)), tuple(sorted(rids)))
            if key not in cache:
                cache[key] = pf.formula(deck, rids)
            feat = cache[key]
            blind_cards = sum(card_blind(c["id"], c["up"]) for c in deck)
            blind_relics = sum(relic_blind(r) for r in rids)
            synergy = (sum(1 for r in rids if pf.relic_triggers(r))
                       + sum(1 for c in deck if any(k in pf.card_row(c) for k in pf.TRIGGERS.values())))
            out.append({
                "enc": node["enc"], "act": node.get("act", 0), "player": sid, "run": f"{sid}-{ts}",
                "floor": floor, "taken": node["dmg"], "turns": node["turns"],
                "asc": parsed.get("ascension", 0), "size": len(deck), "synergy": synergy,
                "blind_cards": blind_cards, "blind_relics": blind_relics,
                "feat": {**feat, **buckets(feat, len(deck))},
            })
        if i % 200 == 0:
            print(f"  {i} runs, {len(out)} fights, {time.time() - t:.0f}s", flush=True)
    return out


def rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    for r, i in enumerate(order):
        out[i] = float(r)
    return out


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if not sx or not sy:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def spearman(xs, ys):
    return pearson(rank(xs), rank(ys))


def r2(pred, actual):
    m = sum(actual) / len(actual)
    ss = sum((a - m) ** 2 for a in actual)
    return 1 - sum((a - p) ** 2 for p, a in zip(pred, actual)) / ss if ss else 0.0


def main():
    data = fights()
    by_enc = defaultdict(list)
    for r in data:
        by_enc[r["enc"]].append(r)
    kept = []
    for enc, rs in by_enc.items():
        if len(rs) < MIN_SEEN:
            continue
        mt, mn = statistics.mean(r["taken"] for r in rs), statistics.mean(r["turns"] for r in rs)
        for r in rs:
            kept.append({**r, "d_taken": r["taken"] - mt, "d_turns": r["turns"] - mn})
    encs = sum(len(v) >= MIN_SEEN for v in by_enc.values())
    print(f"\n{len(data)} fights, {len(kept)} in the {encs} encounters fought {MIN_SEEN}+ times\n")

    # 1. Each bucket against its counterpart.
    print("1. Bucket against outcome, within encounter (Spearman, -1..1)")
    pairs = [
        ("block/turn", "block", "damage taken", "d_taken", -1),
        ("damage/turn", "damage", "turns", "d_turns", -1),
        ("energy/turn", "energy", "turns", "d_turns", -1),
        ("cards/turn", "draw", "damage taken", "d_taken", -1),
        ("block/turn", "block", "turns", "d_turns", -1),
        ("damage/turn", "damage", "damage taken", "d_taken", -1),
    ]
    for label, feat_key, label_y, y, _ in pairs:
        rho = spearman([r["feat"][feat_key] for r in kept], [r[y] for r in kept])
        print(f"   {label:>12} vs {label_y:<13} rho {rho:+.3f}")

    # 2. The composite, held out by run.
    print("\n2. Fitted composite, held out by run (fit on half, score the other half)")
    runs_sorted = sorted({r["run"] for r in kept})
    halves = [set(runs_sorted[0::2]), set(runs_sorted[1::2])]
    players = sorted({r["player"] for r in kept})
    base = lambda r: [1, r["asc"], r["act"]] + [r["player"] == p for p in players[1:]]  # noqa: E731
    nb = len(base(kept[0]))
    for y in ("taken", "turns"):
        pred_all, act_all = [], []
        for train, test in ((halves[0], halves[1]), (halves[1], halves[0])):
            tr = [r for r in kept if r["run"] in train]
            te = [r for r in kept if r["run"] in test]
            if not tr or not te:
                continue
            w = fv.solve([base(r) + [r["feat"][c] for c in pf.FORMULA] for r in tr],
                         [r["d_" + y] for r in tr])
            for r in te:
                pred_all.append(sum(wi * xi for wi, xi in zip(w, base(r) + [r["feat"][c] for c in pf.FORMULA])))
                act_all.append(r["d_" + y])
        print(f"   {y:<6} R^2 {100 * r2(pred_all, act_all):>5.1f}%  on {len(act_all)} held-out fights")

    # 3. The floor-to-floor claim: a stronger floor should mean a better next fight.
    # Weights for display below are fitted on everything; the honest numbers are in 2.
    w = fv.solve([base(r) + [r["feat"][c] for c in pf.FORMULA] for r in kept],
                 [r["d_taken"] for r in kept])
    w_turns = fv.solve([base(r) + [r["feat"][c] for c in pf.FORMULA] for r in kept],
                       [r["d_turns"] for r in kept])
    print("\n3. Floor to floor: did a stronger deck mean a better next fight?")
    by_run = defaultdict(list)
    for r in kept:
        by_run[r["run"]].append(r)
    for y, label in (("taken", "damage taken"), ("turns", "turns")):
        wy = w if y == "taken" else w_turns
        ups, downs = [], []
        for rs in by_run.values():
            rs.sort(key=lambda r: r["floor"])
            for a, b in zip(rs, rs[1:]):
                # the fitted score says lower is stronger, so a fall is an improvement
                s_a = score_of(a["feat"], wy)
                s_b = score_of(b["feat"], wy)
                if abs(s_b - s_a) < 0.05:
                    continue
                (ups if s_b < s_a else downs).append(b["d_" + y])
        if ups and downs:
            ok = statistics.mean(ups) < statistics.mean(downs)
            print(f"   {label:<13} stronger floor -> {statistics.mean(ups):+.2f}, weaker -> {statistics.mean(downs):+.2f}  "
                  f"({'as expected' if ok else 'backwards'}; {len(ups)} vs {len(downs)} changes)")

    # 4. Calibration by decile of the fitted score.
    print("\n4. Calibration: real damage taken by decile of the fitted score (should climb)")
    scored = [(score_of(a["feat"], w), a["d_taken"]) for a in kept]
    scored.sort(key=lambda x: x[0])
    step = max(1, len(scored) // 10)
    for i in range(0, len(scored), step)[:10]:
        chunk = scored[i:i + step]
        print(f"   decile {i // step + 1}: score {statistics.mean(s for s, _ in chunk):+6.2f}  "
              f"taken {statistics.mean(t for _, t in chunk):+5.2f}")

    # 5. Split by how much of the deck the model can't see.
    print("\n5. By how many guessed cards the deck held (relics are unmodelled too, so counted apart)")
    blind_cards = [r["blind_cards"] for r in kept]
    print(f"   {statistics.mean(blind_cards):.1f} guessed cards a deck on average; "
          f"{100 * sum(1 for b in blind_cards if b >= 3) / len(blind_cards):.0f}% of fights had 3+; "
          f"{statistics.mean(r['blind_relics'] for r in kept):.1f} unmodelled relics")
    for lo, hi in ((0, 0), (1, 2), (3, 98), (99, 999)):
        sub = [r for r in kept if lo <= r["blind_cards"] <= hi] if hi < 999 else []
        if len(sub) < 100:
            continue
        rho = spearman([r["feat"]["block"] for r in sub], [r["d_taken"] for r in sub])
        by = f"{lo}" if lo == hi else f"{lo}-{hi if hi < 98 else '+'}"
        print(f"   {by:>5} unmodelled cards: {len(sub):>5} fights  block vs taken rho {rho:+.3f}")

    # 6. Decks built around triggers: the ones the per-turn numbers can't see.
    # Held out across the divide: the model is fitted on one group and scored on
    # the other, so what the trigger terms add to those decks shows up.
    print("\n6. Decks carrying a per-event trigger (a per-attack relic, an on-play power)")
    groups = {"with": [r for r in kept if r["synergy"]], "without": [r for r in kept if not r["synergy"]]}
    feat = lambda r: base(r) + [r["feat"][c] for c in pf.FORMULA]  # noqa: E731
    for label, other in (("with", "without"), ("without", "with")):
        sub, tr = groups[label], groups[other]
        if len(sub) < 100 or len(tr) < 100:
            continue
        for y in ("taken", "turns"):
            w = fv.solve([feat(r) for r in tr], [r["d_" + y] for r in tr])
            pred = [sum(wi * xi for wi, xi in zip(w, feat(r))) for r in sub]
            act = [r["d_" + y] for r in sub]
            rb = spearman([r["feat"]["block"] for r in sub], [r["d_taken"] for r in sub])
            print(f"   {label:>7} decks, {len(sub):>5} fights: {y:<5} R^2 {100 * r2(pred, act):>5.1f}%"
                  + (f"   block vs taken {rb:+.3f}" if y == "taken" else ""))


def score_of(feat, w):
    return sum(wi * feat[c] for wi, c in zip(w, pf.FORMULA))


if __name__ == "__main__":
    main()
