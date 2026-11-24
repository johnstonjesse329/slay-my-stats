"""The home page's showcase: cool winning runs from the last 30 days (FB-53).

Built by the daily benchmark refresh (benchmark.py), which already reads every published
run, and published as users/_showcase.json.gz. The page only draws it. Nothing here ranks
players: each tab is a short handful of runs worth opening, and a run with no turn data
simply isn't a candidate for the turn tabs.

    {"v": 1, "at": <seconds>, "days": 30,
     "op":       [{"slug", "name", "ts", "char", "asc"}, ...],
     "blocked":  [{..., "n"}], "overkill": [{..., "n"}], "deck": [{..., "n"}]}
"""
from tools.power_curve.fight_demand import act_readings, run_reading

WINDOW_DAYS = 30
PER_TAB = 6
TABS = ("op", "blocked", "overkill", "deck")


def turn_peaks(log) -> dict:
    """The most Block gained and the most overkill dealt in one turn of a run's event log
    (the same reading as tools/export_run_records.py, for a solo run's one player). A key
    is left out when the log has none: overkill only exists in logs from a mod that records
    `ovk`."""
    block, over = {}, {}
    for e in (log or {}).get("log") or []:
        a, key = e.get("a") or {}, (e.get("f"), e.get("t"))
        if e.get("k") == "blk" and a.get("c") == "P":
            block[key] = block.get(key, 0) + (a.get("n") or 0)
        elif e.get("k") == "hit" and a.get("by") == "P" and a.get("t") != "P" and a.get("ovk"):
            over[key] = over.get(key, 0) + a["ovk"]
    return {name: max(table.values()) for name, table in (("blocked", block), ("overkill", over)) if table}


def is_op(fights, encounters, cuts) -> bool:
    reading = run_reading(act_readings(fights, encounters, cuts), cuts) if fights else None
    return bool(reading and reading["op"])


def build(candidates, now, per_tab=PER_TAB) -> dict:
    """candidates: one dict per winning solo run, {slug, name, ts, char, asc, deck, op,
    blocked, overkill}; blocked and overkill may be missing."""
    since = now - WINDOW_DAYS * 86400
    recent = [c for c in candidates if c["ts"] >= since]

    def entry(c, n=None):
        out = {k: c.get(k) for k in ("slug", "name", "ts", "char", "asc")}
        return {**out, "n": n} if n is not None else out

    out = {"v": 1, "at": int(now), "days": WINDOW_DAYS,
           "op": [entry(c) for c in sorted((c for c in recent if c.get("op")), key=lambda c: -c["ts"])[:per_tab]]}
    for tab, field in (("blocked", "blocked"), ("overkill", "overkill"), ("deck", "deck")):
        best = sorted((c for c in recent if c.get(field)), key=lambda c: (-c[field], -c["ts"]))
        out[tab] = [entry(c, c[field]) for c in best[:per_tab]]
    return out
