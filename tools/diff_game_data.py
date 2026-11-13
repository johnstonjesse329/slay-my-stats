"""
What a game patch changed: cards, relics and potions added, removed or edited.

The data files are regenerated in place on every refresh, so without a copy of the
previous ones there is nothing to compare against (v0.113 was diffed against a stale
dist/catalog.json by luck). tools/refresh_game_data.py therefore snapshots the data
under local_data/game_data/<version>/ before and after it runs, then prints this
report. Faces are rendered by the game, so a card whose text or numbers changed has a
new face too; art-only changes are not caught here.

    python tools/diff_game_data.py                 # the two newest snapshots
    python tools/diff_game_data.py v0.111.0 v0.113.0
    python tools/diff_game_data.py --snapshot v0.113.0   # save the current data
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS = ROOT / "local_data" / "game_data"
FILES = {"cards": "card_data.json", "relics": "relic_data.json", "potions": "potion_data.json"}
# Where an item lives on disk, not what it is; the site adds the leading slash.
IGNORED = {"imagePath"}
# The fields worth a line each in the report, so a reader sees the actual change.
SHOWN = ("title", "rarity", "type", "energy", "stars", "keywords", "desc", "descUpgraded")


def snapshot(version: str, root: Path = ROOT) -> Path:
    out = SNAPSHOTS / version
    out.mkdir(parents=True, exist_ok=True)
    for name in FILES.values():
        if (root / name).exists():
            shutil.copy2(root / name, out / name)
    return out


def versions() -> list[str]:
    def key(v: str):
        return [int(p) if p.isdigit() else p for p in v.lstrip("v").replace("-", ".").split(".")]
    return sorted((p.name for p in SNAPSHOTS.iterdir() if p.is_dir()), key=key) if SNAPSHOTS.exists() else []


def load(folder: Path, name: str) -> dict:
    path = folder / name
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def diff(old: dict, new: dict) -> dict:
    changed = {}
    for k in sorted(set(old) & set(new)):
        fields = [f for f in sorted(set(old[k]) | set(new[k]))
                  if f not in IGNORED and old[k].get(f) != new[k].get(f)]
        if fields:
            changed[k] = fields
    return {"added": sorted(set(new) - set(old)), "removed": sorted(set(old) - set(new)),
            "changed": changed}


def report(old_v: str, new_v: str) -> str:
    lines = [f"Game data changes {old_v} -> {new_v}"]
    for what, name in FILES.items():
        old, new = load(SNAPSHOTS / old_v, name), load(SNAPSHOTS / new_v, name)
        d = diff(old, new)
        lines.append(f"\n== {what}: {len(old)} -> {len(new)}  "
                     f"(+{len(d['added'])} added, -{len(d['removed'])} removed, "
                     f"{len(d['changed'])} changed)")
        if d["added"]:
            by_pool: dict[str, list[str]] = {}
            for k in d["added"]:
                by_pool.setdefault(str(new[k].get("pool") or new[k].get("rarity") or ""), []).append(k)
            for pool, keys in sorted(by_pool.items()):
                lines.append(f"  added [{pool}] ({len(keys)}): " + ", ".join(k.split(".", 1)[-1] for k in keys))
        if d["removed"]:
            lines.append("  removed: " + ", ".join(d["removed"]))
        for k, fields in d["changed"].items():
            lines.append(f"  {k}  [{', '.join(fields)}]")
            for f in fields:
                if f in SHOWN:
                    a, b = old[k].get(f), new[k].get(f)
                    lines.append(f"      {f}: {json.dumps(a, ensure_ascii=False)}")
                    lines.append(f"      {' ' * len(f)}  -> {json.dumps(b, ensure_ascii=False)}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("old", nargs="?")
    ap.add_argument("new", nargs="?")
    ap.add_argument("--snapshot", metavar="VERSION", help="save the current data files as VERSION")
    args = ap.parse_args()
    if args.snapshot:
        print(f"snapshot -> {snapshot(args.snapshot)}")
        return 0
    have = versions()
    old_v, new_v = (args.old, args.new) if args.old and args.new else (have[-2:] if len(have) >= 2 else (None, None))
    if not old_v:
        print(f"Need two snapshots in {SNAPSHOTS} (have: {have or 'none'}).", file=sys.stderr)
        return 1
    text = report(old_v, new_v)
    out = SNAPSHOTS / f"changes_{old_v}_to_{new_v}.txt"
    out.write_text(text + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(text)
    print(f"\n(written to {out})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
