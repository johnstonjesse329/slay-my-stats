"""
tools/rebuild_stats.py — Recount the site-wide stats from every profile, and
rewrite each player's seed index (users/<slug>/_seeds.json.gz, what the Seeds
page's "all players" toggle searches).

Uploads keep users/_stats.json.gz up to date by adding each upload's new
runs onto it (see the ingest handler's tally/merge_stats). That never
rereads anyone's history, so this full recount is only needed when a new
figure is added to the stats, a profile is removed, or a best-effort update
was missed (the card and relic picks behind the Cards page's All players
favorites were such a new figure). Run it by hand; nothing schedules it.

Usage:
    python tools/rebuild_stats.py
        Recount local_data/ (the dev server's store).

    python tools/rebuild_stats.py --bucket slay-my-stats-data
        Recount the live data bucket (needs AWS credentials).

    --workers <n>        Players read at once (default 8); the totals are the same.
"""

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))  # the handler imports run.py
sys.path.insert(0, str(_REPO_ROOT / "infra" / "lambda" / "ingest"))
import handler

_DATA_DIR = _REPO_ROOT / "local_data"
DEFAULT_WORKERS = 8


def main():
    args = sys.argv[1:]
    bucket = args[args.index("--bucket") + 1] if "--bucket" in args else None
    store = handler.S3Store(bucket) if bucket else handler.DirStore(_DATA_DIR)

    current = store.get(handler.STATS_KEY)
    players, _ = handler._read_index(store)
    total = handler.empty_stats()
    workers = max(1, int(args[args.index("--workers") + 1]) if "--workers" in args else DEFAULT_WORKERS)

    def read(p):
        """Everything one player adds to the total, read and tallied off the main thread
        and merged in player order below, so the result matches a one-at-a-time recount."""
        got = store.get(handler.blob_key(p["slug"]))
        if got is None:
            return None
        tallies, seeded, count = [], [], 0
        for _, runs in handler.stored_months(store, p["slug"], handler._unpack(got[0])):
            tallies.append(handler.tally(runs, p["slug"]))
            seeded += handler.seed_entries(runs)
            count += len(runs)
        old = store.get(handler.seeds_key(p["slug"]))
        store.put(handler.seeds_key(p["slug"]), handler._pack({"v": 1, "runs": seeded}), {}, old[2] if old else None)
        return tallies, count, len(seeded)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for done, (p, result) in enumerate(zip(players, pool.map(read, players)), 1):
            if result is None:
                print(f"  [{done}/{len(players)}] {p['slug']}: listed but missing, skipped", flush=True)
                continue
            tallies, count, seeded = result
            for t in tallies:
                handler.merge_stats(total, t)
            print(f"  [{done}/{len(players)}] {p['slug']}: {count} runs, {seeded} seeded", flush=True)

    # Overwrites whatever is there. An upload landing mid-recount makes this
    # write fail rather than lose its tally; run it again.
    store.put(handler.STATS_KEY, handler._pack(total), {}, current[2] if current else None)
    print(f"{len(players)} players, {total['allRuns']} runs ({total['solo']['runs']} solo, "
          f"{total['multi']['runs']} multiplayer) -> {handler.STATS_KEY}")


if __name__ == "__main__":
    main()
