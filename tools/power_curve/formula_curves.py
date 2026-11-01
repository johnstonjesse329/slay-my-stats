"""Deck strength per floor from the cheap formula, for power_curve.html.

Fits predict_fights.formula to every real fight in gamma's runs (damage taken
and turns, as the gap from the encounter's average, beside who played,
ascension and act), saves the weights to formula_weights.json, then scores
the deck after every floor of every run: the damage taken and turns a fight
would cost it against an average deck going into the same fight. What each
floor added or removed comes along, so a pick's effect can be read off.
Adds "fTaken", "fTurns" and "changes" to each floor in pcs/<run>.json; no sim.

    python formula_curves.py [pcs dir]
"""
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import approaches as ap
import fights_vs_setup as fv
import gamma_curves as g
import power_curve as pc
import predict_fights as pf

HERE = Path(__file__).parent
WEIGHTS = HERE / "formula_weights.json"


def fit():
    data = fv.rows()
    by_enc = defaultdict(list)
    for r in data:
        by_enc[r["enc"]].append(r)
    for rs in by_enc.values():
        mt, mn = statistics.mean(r["taken"] for r in rs), statistics.mean(r["turns"] for r in rs)
        for r in rs:
            r["d_taken"], r["d_turns"] = r["taken"] - mt, r["turns"] - mn
    cache = {}
    for r in data:
        key = (tuple(sorted((c["id"], c["up"]) for c in r["deck"])), tuple(sorted(r["rids"])))
        if key not in cache:
            cache[key] = pf.formula(r["deck"], r["rids"])
        r.update(cache[key])
    players = sorted({r["player"] for r in data})
    base = lambda r: [1, r["asc"], r["act"]] + [r["player"] == p for p in players[1:]]  # noqa: E731
    nb = len(base(data[0]))
    out = {"fights": len(data), "features": pf.FORMULA}
    for y in ("taken", "turns"):
        b = fv.solve([base(r) + [r[c] for c in pf.FORMULA] for r in data], [r["d_" + y] for r in data])
        w = dict(zip(pf.FORMULA, b[nb:]))
        # Centre on the average deck that walked into a fight, so 0 is "an average deck".
        out[y] = {"weights": w, "centre": statistics.mean(sum(w[c] * r[c] for c in w) for r in data)}
    WEIGHTS.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def score(feat, model, y):
    m = model[y]
    return sum(w * feat[c] for c, w in m["weights"].items()) - m["centre"]


def name(cid):
    return pc.CD.get(cid, {}).get("title") or pc.RD.get(cid, {}).get("title") or cid.split(".", 1)[-1].replace("_", " ").title()


def main():
    pcs_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else g.OUT
    fv.PCS = pcs_dir
    t = time.time()
    model = fit()
    print(f"fitted on {model['fights']} fights in {time.time() - t:.0f}s")
    for y in ("taken", "turns"):
        print(f"  {y}: " + ", ".join(f"{c} {w:+.3f}" for c, w in model[y]["weights"].items()))

    runs = g.load()
    index = json.loads((pcs_dir / "index.json").read_text(encoding="utf-8"))
    t, n = time.time(), 0
    for e in index:
        if e.get("error"):
            continue
        sid, ts = e["id"].split("-")
        path = pcs_dir / f"{e['id']}.json"
        out = json.loads(path.read_text(encoding="utf-8"))
        prev_cards, prev_rel = Counter(), set()
        for fl, (_, deck, rids, _) in zip(out["floors"], ap.states(runs[(sid, int(ts))], sid)):
            feat = pf.formula(deck, rids)
            fl["fTaken"], fl["fTurns"] = round(score(feat, model, "taken"), 2), round(score(feat, model, "turns"), 3)
            cards = Counter(c["title"] + ("+" if c["up"] else "") for c in deck)
            fl["changes"] = (["+ " + k for k in (cards - prev_cards).elements()] + ["− " + k for k in (prev_cards - cards).elements()]
                             + ["+ " + name(r) for r in rids if r not in prev_rel] + ["− " + name(r) for r in prev_rel - set(rids)])
            prev_cards, prev_rel = cards, set(rids)
        path.write_text(json.dumps(out), encoding="utf-8")
        n += 1
    print(f"scored {n} runs in {time.time() - t:.1f}s")


if __name__ == "__main__":
    main()
