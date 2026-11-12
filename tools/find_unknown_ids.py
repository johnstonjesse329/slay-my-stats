"""
tools/find_unknown_ids.py — The characters, cards and relics in uploaded runs that the game data doesn't have.

The process Lambda holds back a run that names one (see known_ids() in the handler). This lists
them all from raw/, with who sent them and on which builds, to sort them out:

  * A mod's: nothing to do. Those runs stay held.
  * The game's, from a patch newer than our game data: refresh card_data.json and
    relic_data.json, deploy, then tools/rebuild_profiles.py --all.
  * The game's, since removed: older runs still carry it. Check the game's own files
    (sts2.dll at the game data's build) have no such thing, then add it to
    tools/retired_ids.json. Not seeing it in recent runs proves nothing.

Usage:
    python tools/find_unknown_ids.py [--bucket <name>]
        --bucket: the live data bucket (needs AWS credentials); otherwise local_data/.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "infra" / "lambda" / "ingest"))
import handler


def main():
    args = sys.argv[1:]
    bucket = args[args.index("--bucket") + 1] if "--bucket" in args else None
    store = handler.S3Store(bucket) if bucket else handler.DirStore(_REPO_ROOT / "local_data")
    if not handler.known_ids():
        sys.exit("No game data: card_data.json and relic_data.json are needed.")

    seen = defaultdict(lambda: {"runs": set(), "players": set(), "builds": set(), "coop": 0})
    for key in sorted(store.list("raw/")):
        m = handler.RAW_KEY_RE.match(key)
        got = store.get(key) if m else None
        if got is None:
            continue
        try:
            lines = list(handler.iter_upload_lines(got[0]))
        except handler.IngestError:
            continue
        for line in lines:
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            run = (m.group(1), data.get("start_time"))
            for i in handler.unknown_ids(data):
                s = seen[i]
                if run not in s["runs"]:
                    s["runs"].add(run)
                    s["players"].add(m.group(1))
                    s["builds"].add(str(data.get("build_id")))
                    s["coop"] += len(data.get("players") or []) > 1

    if not seen:
        print("Every run names only known characters, cards and relics.")
        return
    print(f"{'ID':48} {'runs':>5} {'players':>7} {'co-op':>5}  builds")
    for i, s in sorted(seen.items(), key=lambda kv: (-len(kv[1]["runs"]), kv[0])):
        builds = sorted(s["builds"])
        span = builds[0] if len(builds) == 1 else f"{builds[0]} .. {builds[-1]}"
        print(f"{i:48} {len(s['runs']):5} {len(s['players']):7} {s['coop']:5}  {span}")


if __name__ == "__main__":
    main()
