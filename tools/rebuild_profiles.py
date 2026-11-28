"""
tools/rebuild_profiles.py — Re-parse players' raw uploads into their profiles.

Every upload is kept as sent under raw/<steamid>/, so after a fix to run.py's
parser (with run.PARSER_VERSION bumped) the profiles it built can be rebuilt
from them. A profile's runs with no raw copy (listed in its noRaw: ones
uploaded before raw copies were kept) are left as they are; they get a raw
copy, and the fresh parse, the next time the player uploads. Runs ending
before floor 3 are omitted from the rebuilt profiles, including legacy runs.

Site-wide stats aren't touched: run tools/rebuild_stats.py afterwards.

Usage:
    python tools/rebuild_profiles.py --stale
        Rebuild the profiles an older parser built.
    python tools/rebuild_profiles.py --all
        Rebuild every profile, and make one for anyone whose runs were all
        held (they named content the game data didn't have yet).
    python tools/rebuild_profiles.py --slug mrbean
    python tools/rebuild_profiles.py --steam-id 76561198000000001
        Rebuild one profile.
    python tools/rebuild_profiles.py --migrate
        Split profiles from before month files (every run in
        users/<slug>.json.gz) into month files, as they are: nothing is
        re-parsed. An upload does this for its own profile anyway.
    python tools/rebuild_profiles.py --measured --all
        Re-read every stored log into its run's per-floor numbers (energy and
        cards for the Keeping Up charts), without re-parsing any run. The one
        way to give runs uploaded before those numbers their charts, and to
        re-derive them after the reading changes.

    --dry-run            Report what would change without writing.
    --strict             Fail if a profile could not be rebuilt.
    --workers <n>        Players rebuilt at once (default 8).
    --bucket <name>      The live data bucket (needs AWS credentials);
                         otherwise local_data/ (the dev server's store).
"""

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))  # the handler imports run.py
sys.path.insert(0, str(_REPO_ROOT / "infra" / "lambda" / "ingest"))
import handler
import run

_DATA_DIR = _REPO_ROOT / "local_data"
DEFAULT_WORKERS = 8


def _players(store) -> dict[str, str]:
    """steam_id -> slug for every player with a profile."""
    players = {}
    for key in store.list("ids/"):
        got = store.get(key)
        if got:
            players[key[len("ids/"):-len(".json.gz")]] = handler._unpack(got[0])["slug"]
    return players


def rederive_measured(store, steam_id: str, slug: str, dry_run: bool = False, redo: bool = False) -> dict:
    """Re-read this profile's stored logs into its runs' per-floor numbers.

    Nothing is re-parsed: the fix was in how a log is turned into numbers, and a run
    whose raw copy was never kept still has its log. `redo` re-reads runs that already
    have numbers, which is what a change to the reading needs. Returns {"runs": with a
    log, "added": runs given numbers, "unreadable": logs with nothing to read}."""
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

    bucket = arg("--bucket")
    store = handler.S3Store(bucket) if bucket else handler.DirStore(_DATA_DIR)
    dry_run = "--dry-run" in args
    strict = "--strict" in args

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
    elif "--stale" in args:
        targets = sorted(players)
    elif "--all" in args:
        raw = {k.split("/")[1] for k in store.list("raw/") if handler.RAW_KEY_RE.match(k)}
        targets = sorted(set(players) | raw)
    else:
        sys.exit(__doc__)

    workers = max(1, int(arg("--workers") or DEFAULT_WORKERS))

    if "--measured" in args:
        # Only the logs are re-read. A run's numbers are stored on the run, so a fix to
        # how a log is read needs a re-derive, not a re-parse; and a run with no raw
        # copy still has its log.
        plan = [(sid, players[sid]) for sid in targets if sid in players]

        def one(item):
            steam_id, slug = item
            return slug, rederive_measured(store, steam_id, slug, dry_run, redo=True)

        total = 0
        print(f"{len(plan)} profile(s) with a log, {workers} at a time.", flush=True)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for slug, s in pool.map(one, plan):
                if s["runs"]:
                    line = (f"  {slug}: {s['runs']} run(s) with a log, "
                            f"{s['added']} {'would get' if dry_run else 'given'} numbers")
                    if s["unreadable"]:
                        line += f", {s['unreadable']} with nothing to read"
                    print(line, flush=True)
                total += s["added"]
        print(f"{total} run(s) {'would be ' if dry_run else ''}updated.")
        return

    def rebuild(steam_id):
        """(steam_id, summary | None, error | None); a worker never raises IngestError."""
        slug = players.get(steam_id)
        if "--stale" in args:
            got = store.get(handler.blob_key(slug)) if slug else None
            version = handler._unpack(got[0]).get("parser", 0) if got else None
            if version is None or version >= run.PARSER_VERSION:
                return steam_id, None, None
        try:
            return steam_id, handler.rebuild_profile(store, steam_id, dry_run=dry_run, strict=strict), None
        except handler.IngestError as e:
            return steam_id, None, e

    rebuilt = failed = 0
    print(f"{len(targets)} candidate(s), {workers} at a time.", flush=True)
    # Players are independent and the work is mostly waiting on S3, so a few at once;
    # map keeps the report in order.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for done, (steam_id, s, err) in enumerate(pool.map(rebuild, targets), 1):
            slug = players.get(steam_id)
            if err:
                print(f"  [{done}/{len(targets)}] {slug or steam_id}: {err.message}", flush=True)
                if err.code != "no_profile":
                    failed += 1
                continue
            if s is None:
                continue
            rebuilt += 1
            line = f"  [{done}/{len(targets)}] {s['slug']}: {s['runs']} runs ({s['fromRaw']} re-parsed, {s['noRaw']} without a raw copy)"
            if s["dropped"]:
                line += f", {s['dropped']} dropped (no longer parse, or now held)"
            if s.get("new"):
                line += ", a new profile"
            if s["held"]:
                line += f", {s['held']} still held (content the game data doesn't have)"
            if s["unreadableUploads"]:
                line += f", {s['unreadableUploads']} unreadable uploads"
            print(line, flush=True)

    print(f"{rebuilt} profile(s) {'would be ' if dry_run else ''}rebuilt with parser v{run.PARSER_VERSION}.")
    if rebuilt and not dry_run:
        print("Now run tools/rebuild_stats.py" + (f" --bucket {bucket}" if bucket else "") + " to recount the site stats.")
    if strict and failed:
        sys.exit(f"{failed} profile(s) could not be rebuilt.")


if __name__ == "__main__":
    main()
