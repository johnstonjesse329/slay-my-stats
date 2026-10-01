"""
tools/rebuild_profiles.py — Re-parse players' raw uploads into their profiles.

Every upload is kept as sent under raw/<steamid>/, so after a fix to run.py's
parser (with run.PARSER_VERSION bumped) the profiles it built can be rebuilt
from them. A profile's runs with no raw copy (listed in its noRaw: ones
uploaded before raw copies were kept) are left as they are; they get a raw
copy, and the fresh parse, the next time the player uploads.

Site-wide stats aren't touched: run tools/rebuild_stats.py afterwards.

Usage:
    python tools/rebuild_profiles.py --stale
        Rebuild the profiles an older parser built.
    python tools/rebuild_profiles.py --all
        Rebuild every profile.
    python tools/rebuild_profiles.py --slug mrbean
    python tools/rebuild_profiles.py --steam-id 76561198000000001
        Rebuild one profile.
    python tools/rebuild_profiles.py --migrate
        Split profiles from before month files (every run in
        users/<slug>.json.gz) into month files, as they are: nothing is
        re-parsed. An upload does this for its own profile anyway.

    --dry-run            Report what would change without writing.
    --bucket <name>      The live data bucket (needs AWS credentials);
                         otherwise local_data/ (the dev server's store).
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))  # the handler imports run.py
sys.path.insert(0, str(_REPO_ROOT / "infra" / "lambda" / "ingest"))
import handler
import run

_DATA_DIR = _REPO_ROOT / "local_data"


def _players(store) -> dict[str, str]:
    """steam_id -> slug for every player with a profile."""
    players = {}
    for key in store.list("ids/"):
        got = store.get(key)
        if got:
            players[key[len("ids/"):-len(".json.gz")]] = handler._unpack(got[0])["slug"]
    return players


def main():
    args = sys.argv[1:]

    def arg(name):
        return args[args.index(name) + 1] if name in args else None

    bucket = arg("--bucket")
    store = handler.S3Store(bucket) if bucket else handler.DirStore(_DATA_DIR)
    dry_run = "--dry-run" in args

    players = _players(store)
    if "--migrate" in args:
        migrated = 0
        for slug in sorted(players.values()):
            if dry_run:
                got = store.get(handler.blob_key(slug))
                todo = bool(got) and handler._unpack(got[0]).get("v", 1) < 2
            else:
                try:
                    todo = handler.migrate_profile(store, slug)
                except handler.IngestError as e:
                    print(f"  {slug}: {e.message}")
                    continue
            if todo:
                migrated += 1
                print(f"  {slug}")
        print(f"{migrated} profile(s) {'would be ' if dry_run else ''}split into month files.")
        return
    if arg("--steam-id"):
        targets = [arg("--steam-id")]
    elif arg("--slug"):
        targets = [sid for sid, slug in players.items() if slug == arg("--slug")]
        if not targets:
            sys.exit(f"No profile has the slug {arg('--slug')!r}.")
    elif "--all" in args or "--stale" in args:
        targets = sorted(players)
    else:
        sys.exit(__doc__)

    rebuilt = 0
    for steam_id in targets:
        slug = players.get(steam_id)
        if "--stale" in args:
            got = store.get(handler.blob_key(slug)) if slug else None
            version = handler._unpack(got[0]).get("parser", 0) if got else None
            if version is None or version >= run.PARSER_VERSION:
                continue
        try:
            s = handler.rebuild_profile(store, steam_id, dry_run=dry_run)
        except handler.IngestError as e:
            print(f"  {slug or steam_id}: {e.message}")
            continue
        rebuilt += 1
        line = f"  {s['slug']}: {s['runs']} runs ({s['fromRaw']} re-parsed, {s['noRaw']} without a raw copy)"
        if s["dropped"]:
            line += f", {s['dropped']} no longer parse and are dropped"
        if s["unreadableUploads"]:
            line += f", {s['unreadableUploads']} unreadable uploads"
        print(line)

    print(f"{rebuilt} profile(s) {'would be ' if dry_run else ''}rebuilt with parser v{run.PARSER_VERSION}.")
    if rebuilt and not dry_run:
        print("Now run tools/rebuild_stats.py" + (f" --bucket {bucket}" if bucket else "") + " to recount the site stats.")


if __name__ == "__main__":
    main()
