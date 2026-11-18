"""
tools/seed_gamma.py — Copy prod's run data into gamma's bucket, then rebuild
gamma's profiles and stats from it, so gamma shows real players' data.

Copies users/, ids/, raw/ and telemetry/ from slay-my-stats-data to
slay-my-stats-gamma-data (not _uploads/, the in-flight upload area). It only
adds and overwrites, never deletes: gamma's own test data stays. Prod's player
list replaces gamma's, though, so players with only a gamma profile are put
back on it afterwards.

The rebuild uses this checkout's parser and ingest handler, so run it from the
worktree holding the code you want to check on gamma. Profiles are rebuilt
twice: co-op links work out each pair of players' clock gap from the games
already linked, so the second pass links what the first couldn't.

Usage:
    python tools/seed_gamma.py
        Copy, rebuild every profile (two passes), recount the stats.
    python tools/seed_gamma.py --no-copy
        Rebuild and recount only (after a parser or handler change).
    python tools/seed_gamma.py --no-rebuild
        Copy only.
    python tools/seed_gamma.py --dry-run
        List what the copy would do; nothing is written.

Needs AWS credentials (`aws login`); a session that expires mid-run stops it,
and running it again carries on safely.
"""

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))  # the handler imports run.py
sys.path.insert(0, str(_REPO_ROOT / "infra" / "lambda" / "ingest"))
import handler

PROD = "slay-my-stats-data"
GAMMA = "slay-my-stats-gamma-data"
PREFIXES = ("users", "ids", "raw", "telemetry")


def _run(cmd: list[str]) -> None:
    print("$", " ".join(cmd), flush=True)
    if subprocess.run(cmd, cwd=_REPO_ROOT).returncode:
        sys.exit(f"Failed: {' '.join(cmd)}")


def _keep_gamma_players(store, before: list[dict]) -> None:
    """The copy replaces gamma's player list with prod's, which drops players
    who only have a gamma profile. Put them back, as they were listed."""
    players, etag = handler._read_index(store)
    listed = {p["slug"] for p in players}
    kept = [p for p in before if p["slug"] not in listed and store.get(handler.blob_key(p["slug"]))]
    if not kept:
        return
    players = sorted(players + kept, key=lambda p: p["slug"])
    store.put(handler.INDEX_KEY, handler._pack({"v": 1, "players": players}), {}, etag)
    print("Kept gamma-only players on the list:", ", ".join(p["slug"] for p in kept))


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args

    # Fail now rather than halfway through, if the session has lapsed.
    if subprocess.run(["aws", "sts", "get-caller-identity"], capture_output=True).returncode:
        sys.exit("No working AWS credentials: run `aws login` and try again.")

    if "--no-copy" not in args:
        store = handler.S3Store(GAMMA)
        before, _ = handler._read_index(store)
        for prefix in PREFIXES:
            cmd = ["aws", "s3", "sync", f"s3://{PROD}/{prefix}/", f"s3://{GAMMA}/{prefix}/",
                   "--exclude", "_uploads/*", "--only-show-errors"]
            _run(cmd + (["--dryrun"] if dry_run else []))
        if not dry_run:
            _keep_gamma_players(store, before)

    if dry_run or "--no-rebuild" in args:
        return
    profiles = [sys.executable, "tools/rebuild_profiles.py", "--all", "--bucket", GAMMA]
    _run(profiles)
    _run(profiles)
    _run([sys.executable, "tools/rebuild_stats.py", "--bucket", GAMMA])
    print(f"Done: {GAMMA} seeded from {PROD} and rebuilt.")


if __name__ == "__main__":
    main()
