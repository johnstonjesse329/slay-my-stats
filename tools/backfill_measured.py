"""
tools/backfill_measured.py — Give runs already on the site their per-floor energy and card numbers.

A run uploaded now has them worked out from its event log and stored on the run
(infra/lambda/ingest/measured.py). Runs uploaded before that have the log in
telemetry/<steamid>/<start time>.json.gz and nothing on the run, so their Keeping Up page
has no Energy and cards chart. This reads each log, works the numbers out the same way and
writes them onto the run in its month file. Nothing else in a run changes, and a run that
already has them is left alone.

Usage:
    python tools/backfill_measured.py --bucket slay-my-stats-gamma-data --dry-run
    python tools/backfill_measured.py --bucket slay-my-stats-gamma-data
    python tools/backfill_measured.py --bucket <name> --slug splitswigs
    python tools/backfill_measured.py --bucket <name> --redo
        --redo also re-reads runs that have them, after the reading itself changed.

    --dry-run            Report what would change without writing.
    --bucket <name>      The data bucket (needs AWS credentials); otherwise local_data/.
    --slug <slug>        One profile only.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))  # the handler imports run.py
sys.path.insert(0, str(_REPO_ROOT / "infra" / "lambda" / "ingest"))
import handler
import measured

_DATA_DIR = _REPO_ROOT / "local_data"


def backfill_profile(store, steam_id: str, slug: str, redo: bool = False, dry_run: bool = False) -> dict:
    """Write `measured` onto every run of this profile that has a log and doesn't have it.
    Returns {"runs": with a log, "added": runs given numbers, "unreadable": logs with
    nothing to read}."""
    summary = {"runs": 0, "added": 0, "unreadable": 0}
    got = store.get(handler.blob_key(slug))
    doc = handler._unpack(got[0]) if got else None
    if not doc or doc.get("v", 1) < 2:
        return summary
    for month in sorted(doc.get("months", {})):
        key = handler.month_key(slug, month)
        for _ in range(handler.MERGE_RETRIES):
            held = store.get(key)
            if held is None:
                break
            runs = handler._unpack(held[0])["runs"]
            changed = False
            for r in runs:
                if r.get("measured") and not redo:
                    continue
                log = store.get(handler.telemetry_key(steam_id, r["ts"]))
                if log is None:
                    continue
                summary["runs"] += 1
                rows = handler._measured_rows(handler._unpack(log[0]), r)
                if not rows:
                    summary["unreadable"] += 1
                    continue
                r["measured"] = rows
                summary["added"] += 1
                changed = True
            if not changed or dry_run:
                break
            try:
                store.put(key, handler._pack({"v": 2, "runs": runs}), {}, held[2])
                break
            except handler.StoreConflict:  # an upload wrote this month first: read it again
                summary["runs"] = summary["added"] = summary["unreadable"] = 0
                continue
    return summary


def main():
    args = sys.argv[1:]

    def arg(name):
        return args[args.index(name) + 1] if name in args else None

    if "--help" in args or "-h" in args:
        sys.exit(__doc__)
    bucket = arg("--bucket")
    store = handler.S3Store(bucket) if bucket else handler.DirStore(_DATA_DIR)
    dry_run = "--dry-run" in args
    only = arg("--slug")

    total = 0
    for key in sorted(store.list("ids/")):
        got = store.get(key)
        if not got:
            continue
        steam_id = key[len("ids/"):-len(".json.gz")]
        slug = handler._unpack(got[0])["slug"]
        if only and slug != only:
            continue
        s = backfill_profile(store, steam_id, slug, redo="--redo" in args, dry_run=dry_run)
        if s["runs"]:
            line = f"  {slug}: {s['runs']} run(s) with a log, {s['added']} {'would get' if dry_run else 'given'} numbers"
            if s["unreadable"]:
                line += f", {s['unreadable']} with nothing to read"
            print(line)
        total += s["added"]
    print(f"{total} run(s) {'would be ' if dry_run else ''}updated.")


if __name__ == "__main__":
    main()
