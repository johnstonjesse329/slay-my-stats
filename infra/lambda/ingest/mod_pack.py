"""The daily snapshot the mod's in-game stats read (nothing in the game calls an API).

Built by the benchmark refresh (benchmark.py) from the fight lines and act cuts it just
computed and the public totals (users/_stats.json.gz). Two files under mod/v1/:

    pack.json.gz            replaced daily
    synergy.<hash>.json     static game data, named by its content; the pack names it

    {"v": 1, "built": <seconds>, "synergy": "synergy.0a1b2c3d4e.json" or null,
     "ruler": {"encounters": {id: {"pool": [base, tough], "tiers": [line, line]}},
               "cuts": {"acts": [{"guard": [lo, hi], "pace": [lo, hi]}], "run": {...}}},
     "lanes": {"solo" | "multi": {
         "chars" | "cards" | "relics": {id: [runs, wins]},
         "picks": {char: {"cards" | "relics": {id: [picks, wins picked, offers, wins skipped]}}},
         "events": {event: {"v": visits, "o": {option: [taken, wins]}}}}}}

Events count the choice made on an event's first page, summed over characters. "v" is there
only where every visit offers every option (the event catalog flags the others), so that
taken / v is a pick rate.

A pick here is one taken from an offer, so picks / offers is the pick rate; a relic handed
over unasked is left out of it. Wins picked still counts the runs that were handed one.

A line is {"turns", "taken", "n"} of the runs that won, with "coop" the same for a party,
or {} when too few have won. Synergies are suggestions only: no win rate is kept for a
combination. No Steam ID, name or seed goes into either file.

A change an older mod can't read goes in mod/v2/ beside v1.
"""
import gzip
import hashlib
import json
from pathlib import Path

import showcase

PREFIX = "mod/v1/"
PACK_KEY = PREFIX + "pack.json.gz"
SIZE_BUDGET = 400 * 1024  # gzipped pack; over it is logged
LINE_FIELDS = ("turns", "taken", "n")
PICK_FIELDS = (0, 1, 4, 5)  # of handler's pick slots: picks, wins picked, offers, wins skipped
HANDED_OVER = 6  # of the same slots: picks that were never offered

_STATIC_FILE = Path(__file__).with_name("mod_synergy.json")


def static_data() -> dict:
    """{"synergy", "archetypes", "basic", "fixedEvents"} from the bundle (build_site.write_mod_synergy),
    or {} when the bundle has none."""
    try:
        return json.loads(_STATIC_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _line(line: dict) -> dict:
    out = {k: line[k] for k in LINE_FIELDS if k in line}
    if "coop" in line:
        out["coop"] = _line(line["coop"])
    return out


def ruler(benchmark: dict) -> dict:
    return {"encounters": {enc: {"pool": d["pool"], "tiers": [_line(t) for t in d["tiers"]]}
                           for enc, d in benchmark["encounters"].items()},
            "cuts": benchmark["cuts"]}


def _pick(q: list) -> list:
    picks, *rest = (q[s] for s in PICK_FIELDS)
    return [picks - sum(q[HANDED_OVER:HANDED_OVER + 1]), *rest]


def _picks(picks: dict) -> dict:
    return {char: {kind: {i: _pick(q) for i, q in kinds.get(kind, {}).items()
                          if len(q) > max(PICK_FIELDS)}  # shorter totals never counted offers
                   for kind in ("cards", "relics")}
            for char, kinds in picks.items()}


def _events(picks: dict, fixed: set) -> dict:
    out = {}
    for kinds in picks.values():
        for event_id, ev in kinds.get("events", {}).items():
            into = out.setdefault(event_id, {"o": {}})
            if event_id in fixed:
                into["v"] = into.get("v", 0) + ev["v"]
            for option, (taken, wins, *_) in ev["o"].items():
                if "." in option:  # a later page of a multi-step event
                    continue
                have = into["o"].setdefault(option, [0, 0])
                have[0] += taken
                have[1] += wins
    return out


def lanes(stats: dict, fixed_events: set = frozenset()) -> dict:
    out = {}
    for lane in ("solo", "multi"):
        totals = stats.get(lane, {})
        out[lane] = {**{k: totals.get(k, {}) for k in ("chars", "cards", "relics")},
                     "picks": _picks(totals.get("picks", {})),
                     "events": _events(totals.get("picks", {}), fixed_events)}
    return out


def build(benchmark: dict, stats: dict, static: dict, now: float):
    """(pack, synergy file name or None, synergy file bytes or None)."""
    name = body = None
    if static.get("synergy"):
        body = json.dumps({"v": 1, "synergy": static["synergy"], "archetypes": static.get("archetypes"),
                           "families": showcase.SYNERGY_FAMILIES, "basic": static["basic"]},
                          sort_keys=True, separators=(",", ":")).encode("utf-8")
        name = f"synergy.{hashlib.sha256(body).hexdigest()[:10]}.json"
    pack = {"v": 1, "built": int(now), "synergy": name, "ruler": ruler(benchmark),
            "lanes": lanes(stats, set(static.get("fixedEvents") or ()))}
    return pack, name, body


def encode(pack: dict) -> bytes:
    return gzip.compress(json.dumps(pack, separators=(",", ":")).encode("utf-8"), mtime=0)


def publish(store, benchmark: dict, stats: dict, now: float, static: dict | None = None) -> None:
    """static: the game data, when it isn't in the bundle (tools/build_mod_pack.py)."""
    pack, name, body = build(benchmark, stats, static_data() if static is None else static, now)
    # The synergy file first, so the pack never names one that isn't there.
    if name and store.get(PREFIX + name) is None:  # the name is the content: written once
        store.put(PREFIX + name, gzip.compress(body, mtime=0), {}, None)
    data = encode(pack)
    previous = store.get(PACK_KEY)
    store.put(PACK_KEY, data, {}, previous[2] if previous else None)
    print(json.dumps({"mod_pack_bytes": len(data), "over_budget": len(data) > SIZE_BUDGET,
                      "synergy": name}))
