"""
tools/build_user_blob.py — Build a per-user data blob for the static site.

Parses a local STS2 history folder the same way run.py does, then saves it
into local_data/ exactly as an upload would (the ingest Lambda's storage
code, so the layout can't drift): the profile's summary at
users/<slug>.json.gz and its runs by month at users/<slug>/<YYYY-MM>.json.gz,
the private ids/<steamid>.json.gz record, and the users/_index.json.gz list.
boot.js fetches the summary, then the month files; see build_site.py's
docstring for how the whole static site fits together. Rebuilding replaces
the profile's runs but keeps its slug.

Usage:
    python tools/build_user_blob.py
        Auto-detects the history folder (same as run.py). If more than one
        Steam account has save data, pass --steam-id to pick one.

    python tools/build_user_blob.py --history "C:\\path\\to\\history"
        Skip auto-detection and use the folder you specify.

    python tools/build_user_blob.py --steam-id 76561198000000001
        Pick a Steam account when auto-detection finds more than one.

    python tools/build_user_blob.py --name "Mr. Bean"
        Use this display name instead of asking Steam for it.
"""

import sys
import time
from pathlib import Path

# Make run.py and the ingest handler importable regardless of cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "infra" / "lambda" / "ingest"))
import run
import handler

_DATA_DIR = _REPO_ROOT / "local_data"


def parse_args():
    args = sys.argv[1:]
    history_dir = Path(args[args.index("--history") + 1]) if "--history" in args else None
    steam_id_arg = args[args.index("--steam-id") + 1] if "--steam-id" in args else None
    name_arg = args[args.index("--name") + 1] if "--name" in args else None
    return history_dir, steam_id_arg, name_arg


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
    history_dir_arg, steam_id_arg, name_arg = parse_args()
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

    store = handler.DirStore(_DATA_DIR)
    record = store.get(handler.id_key(steam_id))
    slug = handler._unpack(record[0])["slug"] if record else None
    existing = store.get(handler.blob_key(slug)) if slug else None
    old_name = handler._unpack(existing[0]).get("name") if existing else None

    name = handler.clean_name(name_arg or handler.lookup_steam_name(steam_id)) or old_name
    if name is None:
        print("Couldn't get your Steam name from Steam. Pass --name.")
        sys.exit(1)

    slug = handler.save_profile(store, steam_id, slug, existing[2] if existing else None,
                                name, runs, {}, time.time())
    out_path = _DATA_DIR / handler.blob_key(slug)
    month_dir = _DATA_DIR / "users" / slug
    month_files = sorted(month_dir.glob("*.json.gz"))

    print(f"Name:          {name}")
    print(f"Runs:          {len(runs)} in {len(month_files)} month(s)")
    print(f"Gzipped size:  {out_path.stat().st_size:,} bytes summary + "
          f"{sum(p.stat().st_size for p in month_files):,} bytes of months")
    print(f"Wrote {out_path} and {month_dir}/  (site URL /u/{slug})")


if __name__ == "__main__":
    main()
