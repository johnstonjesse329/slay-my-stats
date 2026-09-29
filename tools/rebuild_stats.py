"""
tools/rebuild_stats.py — Recount the site-wide stats from every profile.

Uploads keep users/_stats.json.gz up to date by adding each upload's new
runs onto it (see the ingest handler's tally/merge_stats). That never
rereads anyone's history, so this full recount is only needed when a new
figure is added to the stats, a profile is removed, or a best-effort update
was missed. Run it by hand; nothing schedules it.

Usage:
    python tools/rebuild_stats.py
        Recount local_data/ (the dev server's store).

    python tools/rebuild_stats.py --bucket slay-my-stats-data
        Recount the live data bucket (needs AWS credentials).
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))  # the handler imports run.py
sys.path.insert(0, str(_REPO_ROOT / "infra" / "lambda" / "ingest"))
import handler

_DATA_DIR = _REPO_ROOT / "local_data"


def main():
    args = sys.argv[1:]
    bucket = args[args.index("--bucket") + 1] if "--bucket" in args else None
    store = handler.S3Store(bucket) if bucket else handler.DirStore(_DATA_DIR)

    players, _ = handler._read_index(store)
    total = handler.empty_stats()
    for p in players:
        got = store.get(handler.blob_key(p["slug"]))
        if got is None:
            print(f"  {p['slug']}: listed but missing, skipped")
            continue
        runs = handler._unpack(got[0]).get("runs", [])
        handler.merge_stats(total, handler.tally(runs, p["slug"]))
        print(f"  {p['slug']}: {len(runs)} runs")

    # Overwrites whatever is there. An upload landing mid-recount makes this
    # write fail rather than lose its tally; run it again.
    current = store.get(handler.STATS_KEY)
    store.put(handler.STATS_KEY, handler._pack(total), {}, current[2] if current else None)
    print(f"{len(players)} players, {total['allRuns']} runs ({total['runs']} solo) -> {handler.STATS_KEY}")


if __name__ == "__main__":
    main()
