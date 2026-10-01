"""
tools/remove_profile.py — Take a profile off the site.

Deletes the profile (summary and month files), drops it from the player
list, and removes the private record tying it to a Steam account, so the
player's next upload starts a fresh profile, under the same slug if it's
still free. Their kept raw uploads stay unless --raw is given.

Site-wide stats aren't touched: run tools/rebuild_stats.py afterwards.

Usage:
    python tools/remove_profile.py --slug mrbean [--slug other ...]

    --raw                Delete the player's raw uploads too.
    --dry-run            List what would be deleted without deleting it.
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
    slugs = [args[i + 1] for i, a in enumerate(args) if a == "--slug" and i + 1 < len(args)]
    if not slugs:
        sys.exit(__doc__)
    bucket = args[args.index("--bucket") + 1] if "--bucket" in args else None
    store = handler.S3Store(bucket) if bucket else handler.DirStore(_DATA_DIR)
    dry_run = "--dry-run" in args

    for slug in slugs:
        s = handler.remove_profile(store, slug, raw="--raw" in args, dry_run=dry_run)
        if not s["deleted"]:
            print(f"  {slug}: no such profile")
            continue
        print(f"  {slug}: {'would delete' if dry_run else 'deleted'} {len(s['deleted'])} object(s)")
        for k in s["deleted"]:
            print(f"    {k}")
    if not dry_run:
        print("Now run tools/rebuild_stats.py" + (f" --bucket {bucket}" if bucket else "") + " to recount the site stats.")


if __name__ == "__main__":
    main()
