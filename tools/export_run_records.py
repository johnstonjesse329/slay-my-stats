"""run_records.json for runs on this machine that the site has no records for yet (FB-44, FB-51, FB-64).

Uploads carry their own records now (infra/lambda/ingest/records.py); this is the local preview's
fallback for a profile built before that.

Reads two things the owner has on this machine and puts them side by side by run start time:

  * the mod's event log, telemetry/<steamid>/<start time>.json.gz (local_data/owner_telemetry/,
    synced from the data bucket), for the "largest" records of a run: cards played in a turn,
    damage in a turn, the largest single hit, Block gained, energy gained in a turn;
  * the game's own .run file (steam/<id>/modded/profile1/saves/history), for the win badges the
    game posts on its end screen (players[].badges: id + rarity). Badges are never worked out
    from stats here; a run whose file has none shows none.

Nothing is guessed: a number the log cannot give stays None and the page says "not recorded".

    python tools/export_run_records.py --steam <your Steam ID> [--history <dir>] [--telemetry <dir>]

Writes local_data/run_records.json (ignored by git); build_site.py puts it in DATA.runRecords
when it exists. The badge art and text are baked once by tools/bake_badge_art.py.
"""
import argparse
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAVES = Path.home() / "AppData/Roaming/SlayTheSpire2/steam"
OUT = ROOT / "local_data" / "run_records.json"


import sys
sys.path.insert(0, str(ROOT / "infra" / "lambda" / "ingest"))
from records import badges, records  # noqa: E402  the same reading the upload runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steam", required=True)
    ap.add_argument("--history")
    ap.add_argument("--telemetry", default=str(ROOT / "local_data" / "owner_telemetry"))
    args = ap.parse_args()
    runs = {}
    history = Path(args.history) if args.history else SAVES / args.steam / "modded/profile1/saves/history"
    for f in sorted(history.glob("*.run")):
        run = json.loads(f.read_text(encoding="utf-8"))
        ts = str(run.get("start_time") or f.stem)
        players = run.get("players") or []
        slot = next((i for i, p in enumerate(players) if str(p.get("id")) == args.steam), 0)
        entry = {"slot": slot, "badges": badges(players[slot]), "records": None}
        tel = Path(args.telemetry) / f"{ts}.json.gz"
        if tel.exists():
            entry["records"] = records(json.load(gzip.open(tel, "rt", encoding="utf-8")), slot)
        runs[ts] = entry
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"runs": runs}, separators=(",", ":")), encoding="utf-8")
    withrec = sum(1 for r in runs.values() if r["records"])
    print(f"{len(runs)} runs, {withrec} with an event log -> {OUT}")


if __name__ == "__main__":
    main()
