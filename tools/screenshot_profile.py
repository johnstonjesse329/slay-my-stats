"""
tools/screenshot_profile.py -- a stand-in profile for the README screenshots.

The README screenshots show a player called RightNeow. This copies the real
profile in local_data/users/ under that name (slug "rightneow"), so a preview
at /u/rightneow shows it without touching, renaming or re-uploading the real
runs. Everything lands in local_data/, which is gitignored, and nothing is
ever written to the real profile's files or to AWS.

    python tools/screenshot_profile.py make [--source splitswigs]
    python tools/screenshot_profile.py remove

`make` can be rerun to refresh the copy after local_data has been synced from
prod. `remove` deletes the copy and its line in the local player index.
"""
import argparse
import gzip
import json
import shutil
import sys
from pathlib import Path

USERS = Path(__file__).resolve().parent.parent / "local_data" / "users"
SLUG = "rightneow"
NAME = "RightNeow"


def _read(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def _write(path, doc):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"))


def _update_index(entry):
    """Set (entry dict) or drop (None) the SLUG row in the local player index."""
    path = USERS / "_index.json.gz"
    index = _read(path)
    index["players"] = [p for p in index["players"] if p["slug"] != SLUG]
    if entry:
        index["players"].append(entry)
        index["players"].sort(key=lambda p: p["slug"])
    _write(path, index)


def make(source):
    src_doc = USERS / f"{source}.json.gz"
    src_dir = USERS / source
    if not src_doc.exists() or not src_dir.is_dir():
        sys.exit(f"No local profile '{source}' in {USERS}; sync local_data first.")
    shutil.rmtree(USERS / SLUG, ignore_errors=True)
    shutil.copytree(src_dir, USERS / SLUG)
    doc = _read(src_doc)
    doc["name"] = NAME
    _write(USERS / f"{SLUG}.json.gz", doc)
    entry = next(p for p in _read(USERS / "_index.json.gz")["players"] if p["slug"] == source)
    _update_index({**entry, "slug": SLUG, "name": NAME})
    print(f"Copied '{source}' to /u/{SLUG} as {NAME} ({entry['runs']} runs).")


def remove():
    shutil.rmtree(USERS / SLUG, ignore_errors=True)
    (USERS / f"{SLUG}.json.gz").unlink(missing_ok=True)
    _update_index(None)
    print(f"Removed /u/{SLUG}.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=["make", "remove"])
    ap.add_argument("--source", default="splitswigs")
    args = ap.parse_args()
    make(args.source) if args.action == "make" else remove()
