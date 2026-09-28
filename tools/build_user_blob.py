"""
tools/build_user_blob.py — Build a per-user data blob for the static site.

Parses a local STS2 history folder the same way run.py does, then writes a
gzip-compressed, compact-JSON blob to local_data/users/steam-<steamid64>.json.gz.
That's the file boot.js fetches at /users/steam-<steamid64>.json.gz on the
live site (see build_site.py's docstring for how the whole static site fits
together).

Usage:
    python tools/build_user_blob.py
        Auto-detects the history folder (same as run.py). If more than one
        Steam account has save data, pass --steam-id to pick one.

    python tools/build_user_blob.py --history "C:\\path\\to\\history"
        Skip auto-detection and use the folder you specify.

    python tools/build_user_blob.py --steam-id 76561198000000001
        Pick a Steam account when auto-detection finds more than one.
"""

import gzip
import json
import sys
from pathlib import Path

# Make run.py importable regardless of cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
import run

_OUT_DIR = _REPO_ROOT / "local_data" / "users"


def parse_args():
    args = sys.argv[1:]
    history_dir = Path(args[args.index("--history") + 1]) if "--history" in args else None
    steam_id_arg = args[args.index("--steam-id") + 1] if "--steam-id" in args else None
    return history_dir, steam_id_arg


def resolve_history_dir(history_dir: Path | None, steam_id_arg: str | None) -> Path:
    """
    Mirrors run.py's resolve_history_dir(), but non-interactive: with several
    Steam accounts found, this script takes --steam-id instead of prompting,
    since it's meant to be run unattended (e.g. from a future upload script).
    """
    if history_dir is not None:
        return history_dir

    candidates = run.find_history_dirs()
    if not candidates:
        print("Could not find STS2 save data. Use --history to specify the path manually.")
        sys.exit(1)

    if len(candidates) == 1:
        return candidates[0]

    if steam_id_arg:
        for c in candidates:
            if c.parts[-4] == steam_id_arg:
                return c
        print(f"No history folder found for Steam ID {steam_id_arg!r}.")
        sys.exit(1)

    print("Multiple Steam accounts found. Pass --steam-id to pick one:\n")
    for c in candidates:
        run_count = len(list(c.glob("*.run")))
        print(f"  {c.parts[-4]}  ({run_count} runs)  {c}")
    sys.exit(1)


def main():
    history_dir_arg, steam_id_arg = parse_args()
    history_dir = resolve_history_dir(history_dir_arg, steam_id_arg)

    if not history_dir.exists():
        print(f"History directory not found:\n  {history_dir}")
        sys.exit(1)

    # Steam ID is 4 levels up from history/ (.../steam/<steamID>/profile1/saves/history).
    steam_id = history_dir.parts[-4]
    if not (steam_id.isdigit() and len(steam_id) == 17):
        print(f"Expected a 17-digit Steam ID at parts[-4] of {history_dir}, got {steam_id!r}.")
        sys.exit(1)

    run_files = sorted(history_dir.glob("*.run"), key=lambda p: int(p.stem))
    if not run_files:
        print(f"No .run files found in:\n  {history_dir}")
        sys.exit(1)

    runs = []
    errors = []
    for path in run_files:
        try:
            runs.append(run.parse_run(path))
        except Exception as e:
            errors.append((path.name, str(e)))

    skipped = f" ({len(errors)} skipped)" if errors else ""
    print(f"Parsed {len(runs)} runs{skipped}.")
    if errors:
        print("Skipped files:")
        for name, err in errors:
            print(f"  {name}: {err}")

    runs.sort(key=lambda r: r["ts"])

    payload = json.dumps({"v": 1, "runs": runs}, separators=(",", ":")).encode("utf-8")
    gzipped = gzip.compress(payload)

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _OUT_DIR / f"steam-{steam_id}.json.gz"
    out_path.write_bytes(gzipped)

    print(f"Steam ID:      {steam_id}")
    print(f"Runs:          {len(runs)}")
    print(f"Raw JSON size: {len(payload):,} bytes")
    print(f"Gzipped size:  {len(gzipped):,} bytes")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
