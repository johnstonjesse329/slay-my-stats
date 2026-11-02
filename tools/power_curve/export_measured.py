"""measured_runs.json for the site: what the runs that carry an event log actually did,
floor by floor.

A run file says how long a fight took and what got through. For a run the mod has been
in, the log says what happened inside it: what arrived, what was blocked, what came off
the enemies, and the cards and energy played. The Keeping Up charts on the Runs page read
these; no estimate goes into them.

Keys are the run's start time, which is what the page already uses to identify a run, and
whose value is the telemetry file's name.

    python export_measured.py
"""
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import telemetry_report as tr  # noqa: E402

OUT = HERE.parents[1] / "measured_runs.json"


def floor_numbers(fight, costs):
    """What one fight actually did, for the page's three charts."""
    turns = fight["turns"]
    # Cards drawn, not cards seen: a Shiv, a retained card or a Cascade off the draw pile
    # is played without being drawn, so more can be played than this says.
    drawn = [len(t["hand"]) + len(t["drawn"]) for t in turns]
    # They act after you, so a fight you win on your own turn gives them one turn less.
    swung = [t for t in turns if t["enemy_side"]]
    # The indirect side of energy: plays at list price over what they really spent.
    # An X card lists at 3, as it does in the formula.
    plays = tr.throughput(fight, {c: 3 if v == "X" else v or 0 for c, v in costs.items()})
    return {
        "draw": statistics.mean(drawn) if drawn else 0.0,
        "taken": fight["taken"],
        "arrived": (fight["blocked"] + fight["taken"]) / len(swung) if swung else 0.0,
        "enemyTurns": len(swung),
        "junk": fight["junk"],
        # Everything that came off the enemies, respawns and heals included, by
        # anything at all: the size of the job done.
        "removed": fight["enemy_lost"],
        "played": plays["played"] if plays else 0.0,
        "listPrice": plays["equiv"] if plays else 0.0,
        "spent": plays["spent"] if plays else 0.0,
    }


def main():
    runs = tr.load_runs()
    logs, _ = tr.load_logs(runs)
    costs = tr.card_costs()
    out = {}
    for (sid, ts), derived in logs.items():
        raw = runs.get((sid, ts))
        if raw is None:
            continue
        try:
            import run as runmod
            parsed = runmod.parse_run_data(raw, steam_id=sid, fallback_ts=ts)
        except Exception:
            continue
        per_floor = []
        for fight, node in tr.align(derived["fights"], parsed.get("timeline") or []):
            if not fight["turns"]:
                continue
            row = {"floor": node["floor"] + 1}
            row.update({k: round(v, 2) if isinstance(v, float) else v
                        for k, v in floor_numbers(fight, costs).items()})
            per_floor.append(row)
        if per_floor:
            out[str(ts)] = per_floor
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"{OUT.name}: {len(out)} run(s), "
          f"{sum(len(v) for v in out.values())} floors, {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
