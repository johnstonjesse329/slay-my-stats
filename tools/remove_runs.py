"""
tools/remove_runs.py — Take individual runs off a profile.

For runs that never belonged there, such as mod test runs. Removes each run
(by its ts, the number in its .run file name) from the profile's month files,
from the kept raw uploads (a rebuild re-parses those, so without this it would
bring the run back) and from the telemetry store, then fixes the profile
summary and the player list's run count.

Site-wide stats aren't touched: run tools/rebuild_stats.py afterwards.
Delete the run's .run file from the game's history folder too, or the next
upload sends it again.

Usage:
    python tools/remove_runs.py --slug splitswigs --ts 1794578529 [--ts ...]

    --dry-run            List what would be removed without removing it.
    --bucket <name>      The live data bucket (needs AWS credentials);
                         otherwise local_data/ (the dev server's store).
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
    arg = lambda name: args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None
    slug = arg("--slug")
    ts = [args[i + 1] for i, a in enumerate(args) if a == "--ts" and i + 1 < len(args)]
    if not slug or not ts or not all(t.isdigit() for t in ts):
        sys.exit(__doc__)
    bucket = arg("--bucket")
    store = handler.S3Store(bucket) if bucket else handler.DirStore(_DATA_DIR)
    dry_run = "--dry-run" in args

    try:
        out = handler.remove_runs(store, slug, ts, dry_run=dry_run)
    except handler.IngestError as e:
        sys.exit(f"{slug}: {e}")
    verb = "would remove" if dry_run else "removed"
    for month, tss in out["months"].items():
        print(f"  {verb} from users/{slug}/{month}.json.gz: {', '.join(map(str, tss))}")
    for key, n in out["raw"].items():
        print(f"  {verb} {n} run(s) from {key}")
    for key in out["telemetry"]:
        print(f"  {verb} {key}")
    for t in out["missing"]:
        print(f"  {t}: not on the profile")
    if not dry_run:
        print("Now run tools/rebuild_stats.py" + (f" --bucket {bucket}" if bucket else "") + " to recount the site stats.")


if __name__ == "__main__":
    main()
