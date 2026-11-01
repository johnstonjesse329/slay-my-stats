"""Power curves for every run on gamma, for review in power_curve.html.

Reads the raw uploads pulled from gamma's data bucket into gamma_raw/ (one
gzip NDJSON per upload under raw/<steamid>/, one .run per line), keeps the
newest copy of each run, and writes pcs/<steamid>-<start_time>.json plus
pcs/index.json for the viewer's run picker. Wins first, then newest first,
so the interesting ones are ready soonest; the index is rewritten as runs
finish, so the page can be used while the rest are still going.

    aws s3 sync s3://slay-my-stats-gamma-data/raw/ gamma_raw/
    python gamma_curves.py            # every run
    python gamma_curves.py --errors   # just the ones the last pass failed on or didn't reach
    python archetypes.py              # then: label each run's archetype for the picker
"""
import gzip
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import power_curve as pc

HERE = Path(__file__).parent
RAW, OUT = HERE / "gamma_raw", HERE / "pcs"
# Steam id -> player name, and approaches.py's sample runs: kept out of git in local.json.
LOCAL = json.loads((HERE / "local.json").read_text(encoding="utf-8")) if (HERE / "local.json").exists() else {}
NAMES = LOCAL.get("names", {})
pc.SAMPLES = 20  # review batch: unchanged floors reuse their games (power_curve.curve)


def load():
    runs = {}
    for f in sorted(RAW.rglob("*.ndjson.gz")):  # upload stamps sort oldest first: later copies win
        sid = f.parent.name
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    d = json.loads(line)
                    if isinstance(d, dict) and d.get("map_point_history") and d.get("players"):
                        runs[(sid, d.get("start_time"))] = d
    return runs


def one(job):
    (sid, ts), d = job
    rid = f"{sid}-{ts}"
    idx = pc.run.local_player_index(d, sid)
    p = d["players"][idx]
    entry = {"id": rid, "player": NAMES.get(sid, sid), "ts": ts,
             "character": (p.get("character") or "").replace("CHARACTER.", ""),
             "ascension": d.get("ascension", 0), "win": bool(d.get("win")),
             "coop": len(d["players"]) > 1, "abandoned": bool(d.get("was_abandoned")),
             "floors": sum(len(a) for a in d["map_point_history"]), "build": d.get("build_id")}
    pc.DEADLINE = time.time() + 60  # one bad deck can't hold up the batch
    try:
        out = {"run": rid, **pc.curve(d, sid)}
    except Exception as e:  # a prototype: note the run and move on
        return {**entry, "error": f"{type(e).__name__}: {e}"}
    (OUT / f"{rid}.json").write_text(json.dumps(out), encoding="utf-8")
    return entry


def write_index(entries):
    rows = sorted(entries, key=lambda e: -(e["ts"] or 0))
    (OUT / "index.json").write_text(json.dumps(rows), encoding="utf-8")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    runs = load()
    jobs = sorted(runs.items(), key=lambda kv: (not kv[1].get("win"), -(kv[0][1] or 0)))
    done = []
    if "--errors" in sys.argv:
        done = json.loads((OUT / "index.json").read_text(encoding="utf-8"))
        done = [e for e in done if "error" not in e]
        ok = {e["id"] for e in done}  # anything else failed, or finished after the last index write
        jobs = [j for j in jobs if f"{j[0][0]}-{j[0][1]}" not in ok]
    print(f"{len(jobs)} runs", flush=True)
    start, total = time.time(), len(done) + len(jobs)
    with Pool(11) as pool:
        for entry in pool.imap_unordered(one, jobs):
            done.append(entry)
            if len(done) % 20 == 0 or len(done) == total:
                write_index(done)
                errs = sum(1 for e in done if "error" in e)
                print(f"{len(done)}/{total} done, {errs} errors, {time.time() - start:.0f}s", flush=True)
    for e in done:
        if "error" in e:
            print("error", e["id"], e["error"])
