"""Do decks with more setup cards take more damage in real fights?

Setup cards are Powers: they do nothing on the turn they're played. For every
fight in gamma's runs, the deck going in (the floor before) is counted, and the
real damage taken and turns are set against the same encounter's average, so
a hard fight doesn't read as a bad deck. Then per act: the gap from the
encounter average by how many Powers the deck had, and a least-squares fit
that holds deck size, the sim's damage and block, ascension and player fixed.

    python fights_vs_setup.py [pcs dir]   # default: pcs/ next to this file
"""
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import approaches as ap
import gamma_curves as g

PCS = Path(sys.argv[1]) if len(sys.argv) > 1 else g.OUT
MIN_SEEN = 8  # an encounter needs this many fights to have an average worth comparing to


def rows():
    runs = g.load()
    index = json.loads((PCS / "index.json").read_text(encoding="utf-8"))
    out = []
    for e in index:
        if e.get("error"):
            continue
        sid, ts = e["id"].split("-")
        d, pcs = runs[(sid, int(ts))], json.loads((PCS / f"{e['id']}.json").read_text(encoding="utf-8"))
        st, floors = ap.states(d, sid), pcs["floors"]
        ends = [sum(len(a) for a in d["map_point_history"][:i + 1]) for i in range(len(d["map_point_history"]))]
        for fi in pcs["fights"]:
            f = fi["floor"]
            if f < 2 or fi["taken"] is None or fi["turns"] is None:
                continue
            _, deck, rids, slots = st[f - 2]  # the deck that walked into the fight
            before = floors[f - 2]
            out.append({
                "enc": fi["encounter"], "act": next(i + 1 for i, end in enumerate(ends) if f <= end),
                "room": floors[f - 1]["type"], "taken": fi["taken"], "turns": fi["turns"],
                "powers": sum(c["type"] == "Power" for c in deck), "size": len(deck),
                "dmg": before["dmg"], "block": before["block"],
                "asc": e["ascension"], "player": sid, "id": e["id"],
                "deck": deck, "rids": rids, "slots": slots, "sim": before,
            })
    return out


def solve(X, y):
    """Least squares by the normal equations (few columns, so plain Gauss-Jordan is fine)."""
    k = len(X[0])
    A = [[sum(r[i] * r[j] for r in X) for j in range(k)] + [sum(r[i] * t for r, t in zip(X, y))] for i in range(k)]
    for c in range(k):
        p = max(range(c, k), key=lambda r: abs(A[r][c]))
        A[c], A[p] = A[p], A[c]
        for r in range(k):
            if r != c and A[c][c]:
                m = A[r][c] / A[c][c]
                A[r] = [a - m * b for a, b in zip(A[r], A[c])]
    return [A[i][k] / A[i][i] if A[i][i] else 0 for i in range(k)]


def main():
    data = rows()
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
    print(f"{len(data)} fights, {len(kept)} in encounters seen {MIN_SEEN}+ times ({sum(len(v) >= MIN_SEEN for v in by_enc.values())} encounters)\n")

    bucket = lambda n: min(n, 6)  # noqa: E731
    players = sorted({r["player"] for r in kept})
    for act in (1, 2, 3):
        rs = [r for r in kept if r["act"] == act]
        if not rs:
            continue
        print(f"Act {act}: {len(rs)} fights.  Gap from the encounter's average by Powers in the deck")
        print(f"  {'powers':>6} {'fights':>7} {'taken':>7} {'turns':>7} {'deck':>5} {'sim dmg':>8}")
        for b in range(7):
            sub = [r for r in rs if bucket(r["powers"]) == b]
            if len(sub) < 20:
                continue
            m = lambda k: statistics.mean(r[k] for r in sub)  # noqa: E731
            print(f"  {str(b) + ('+' if b == 6 else ''):>6} {len(sub):>7} {m('d_taken'):>+7.1f} {m('d_turns'):>+7.2f} {m('size'):>5.0f} {m('dmg'):>8.1f}")
        names = ["powers", "deck size", "sim dmg", "sim block", "ascension"] + [f"player {p[-4:]}" for p in players[1:]]
        X = [[1, r["powers"], r["size"], r["dmg"], r["block"], r["asc"]] + [r["player"] == p for p in players[1:]] for r in rs]
        for y_key in ("d_taken", "d_turns"):
            b = solve(X, [r[y_key] for r in rs])
            print(f"  fit {y_key[2:]:>5}: " + ", ".join(f"{n} {v:+.2f}" for n, v in zip(names, b[1:])))
        print()


if __name__ == "__main__":
    main()
