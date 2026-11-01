"""measured_runs.json for the site: what the runs that carry an event log actually did,
floor by floor.

The Deck Strength chart guesses what a deck can do. For a run the mod has been in, the
log says what it *did* -- damage removed from the enemies, block gained, cards seen,
energy available -- and nothing beats that. Those numbers are exported here so the page
can draw them beside the projection instead of only estimating.

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


def floor_numbers(fight):
    """What one fight actually did per turn, in the four chart buckets."""
    turns = fight["turns"]
    n = len(turns) or 1
    seen = [len(t["hand"]) + len(t["drawn"]) for t in turns]
    energy = [t["available"] for t in turns if t["available"] is not None]
    return {
        # Damage the deck caused: our hits plus the ticks that carry no attacker
        # (poison, burn). HP taken off by something that is not damage at all --
        # Doom's countdown to the enemy's own HP -- is deliberately not here.
        "damage": fight["dealt_removed"] / n,
        "block": fight["bgn"] / n,
        "energy": statistics.mean(energy) if energy else 0.0,
        "draw": statistics.mean(seen) if seen else 0.0,
        "turns": len(turns),
        "pool": fight["pool"] or 0,
        "taken": fight["taken"],
        "intent": fight["intent_total"] / n,
        "junk": fight["junk"],
        "attackerTurns": fight["attacker_turns"],
    }


def main():
    logs, _ = tr.load_logs()
    runs = tr.load_runs()
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
            row = {"floor": node["floor"] + 1, "enc": node.get("enc") or ""}
            row.update({k: round(v, 2) if isinstance(v, float) else v
                        for k, v in floor_numbers(fight).items()})
            per_floor.append(row)
        if per_floor:
            out[str(ts)] = per_floor
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"{OUT.name}: {len(out)} run(s), "
          f"{sum(len(v) for v in out.values())} floors, {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
