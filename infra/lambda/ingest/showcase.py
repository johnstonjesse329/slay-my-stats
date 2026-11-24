"""The home page's showcase: cool winning runs from the last 30 days (FB-53).

Built by the daily benchmark refresh (benchmark.py), which already reads every published
run, and published as users/_showcase.json.gz. The page only draws it. Nothing here ranks
players: each tab is a short handful of runs worth opening, and a run with no turn data
simply isn't a candidate for the turn tabs.

    {"v": 1, "at": <seconds>, "days": 30,
     "op":       [{"slug", "name", "ts", "char", "asc", "syn"}, ...],
     "blocked":  [{..., "n"}], "held": [{..., "n"}], "hit": [{..., "n"}], "deck": [{..., "n"}]}

`syn` is the run's deck synergies, up to SYNERGIES_SHOWN names the Overview's "Win % by
synergy" table also uses (deck_synergies), biggest first; it is left out when the deck has none
or the bundle has no table, and a row without it (an older file) draws without.
"""
import json
from pathlib import Path

import run as run_py
from tools.power_curve.fight_demand import act_readings, run_reading

WINDOW_DAYS = 30
PER_TAB = 6
TABS = ("op", "blocked", "held", "hit", "deck")
SYNERGIES_SHOWN = 3

# The names the Overview's synergy table files keys under (SYNERGY_FAMILIES in js/card-face.js,
# kept in step by test_showcase); a key in no family is named by synergy_label.
SYNERGY_FAMILIES = {
    "IRONCLAD": {"Strength": ["power:Strength"], "Exhaust": ["exhaust", "exhaust skills", "exhaust attacks", "Skill Exhaust"], "Block": ["block scaling", "card Block"], "Self-damage": ["HP loss"], "Vulnerable": ["power:Vulnerable"]},
    "SILENT": {"Shiv": ["shiv"], "Poison": ["power:Poison"], "Discard": ["discard"]},
    "DEFECT": {"Lightning": ["lightning", "lightning focus", "lightning slots", "lightning evoke", "lightning passive"], "Frost": ["frost", "frost focus", "frost slots", "frost evoke", "frost passive"], "Dark": ["dark", "dark focus", "dark slots", "dark evoke", "dark passive"], "Plasma": ["plasma slots", "plasma evoke", "plasma passive"], "Zero-cost": ["zero-cost", "zero-cost attacks"], "Status": ["status"]},
    "NECROBINDER": {"Doom": ["power:Doom", "Doom application"], "Osty": ["Osty health", "Osty attacks", "Osty damage"], "Souls": ["souls"], "Ethereal": ["ethereal"]},
    "REGENT": {"Stars": ["stars", "star spending", "star gain", "star-cost cards"], "Forge": ["forge", "blade upgrades"], "Creation": ["creation", "colorless", "minion"]},
    "FOOL": {"Shots": ["aim", "shots", "arrows"], "Impale": ["impale", "dislodge"], "Melodies": ["melodies", "wah melody", "cho melody", "ki melody", "wah cards", "cho cards", "ki cards"], "Sadness": ["sadness"], "Stretch": ["stretch"]},
}

_SYNERGY_FILE = Path(__file__).with_name("showcase_synergy.json")
_table = None


def synergy_table():
    """{"synergy": build_site.build_synergy(), "basic": [Basic card ids]} from the bundle
    (build_site.write_showcase_synergy), or {} when the bundle has none."""
    global _table
    if _table is None:
        try:
            _table = json.loads(_SYNERGY_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _table = {}
    return _table


def synergy_label(key) -> str:
    key = key[6:] if key.startswith("power:") else key
    return key[:1].upper() + key[1:]


def deck_synergies(char, deck, relics, table=None, limit=SYNERGIES_SHOWN) -> list:
    """The synergy names a final deck has, the way js/card-face.js's deckLinks and runSynergies
    count them: a key is a link when one card or relic makes it and a different one needs it,
    and a link made only of Basic cards is dropped (every deck starts with those). Biggest
    first (feeders plus users), ties in the order the deck met them; [] with no table."""
    table = synergy_table() if table is None else table
    syn = table.get("synergy")
    if not syn:
        return []
    basic = set(table.get("basic") or [])
    makers, users = {}, {}

    def row_of(card):
        upgrade = 1 if (card.get("current_upgrade_level") or 0) > 0 else 0
        rolls = syn.get("cardRolls", {}).get(card["id"])
        if rolls is not None:
            props = run_py._card_props(card)
            t, r = props.get("TinkerTimeType"), props.get("TinkerTimeRider")
            suffix = f".{t}.{r}" if t is not None and r is not None else ""
            rows = rolls.get(card["id"] + suffix)
            return rows[upgrade] if rows and upgrade < len(rows) else None
        variants = syn.get("cardVariants", {}).get(card["id"])
        return (variants[upgrade] if variants and upgrade < len(variants) else None) or syn["cards"].get(card["id"])

    seen = [(c["id"], row_of(c)) for c in deck or [] if isinstance(c, dict) and c.get("id")]
    seen += [(r["id"], syn["relics"].get(r["id"])) for r in relics or [] if isinstance(r, dict) and r.get("id")]
    for item_id, row in seen:
        if not row:
            continue
        for key in row[0]:
            makers.setdefault(key, {})[item_id] = True
        for key in row[1]:
            users.setdefault(key, {})[item_id] = True
    links = []
    for key in makers:
        m, u = list(makers[key]), list(users.get(key, {}))
        feeders = [x for x in m if any(y != x for y in u)]
        payoffs = [y for y in u if any(x != y for x in feeders)]
        if feeders and payoffs and any(x not in basic for x in feeders + payoffs):
            links.append((len(feeders) + len(payoffs), key))
    families = SYNERGY_FAMILIES.get((char or "").removeprefix("CHARACTER."), {})
    names = []
    for _, key in sorted(links, key=lambda link: -link[0]):
        name = next((n for n, keys in families.items() if key in keys), None) or synergy_label(key)
        if name not in names:
            names.append(name)
    return names[:limit]


def turn_peaks(log) -> dict:
    """The most Block gained, the most Block held at once and the most damage dealt (overkill included) in one
    turn of a run's event log
    (the same reading as tools/export_run_records.py, for a solo run's one player). A key
    is left out when the log has none: a hit total only exists in logs from a mod that records
    `ovk`."""
    block, hit, held = {}, {}, 0
    for e in (log or {}).get("log") or []:
        a, key = e.get("a") or {}, (e.get("f"), e.get("t"))
        if e.get("k") == "blk" and a.get("c") == "P":
            block[key] = block.get(key, 0) + (a.get("n") or 0)
        elif e.get("k") == "snap" and a.get("why") in ("turn0", "side1"):
            # The player's Block as the turn opens and as it ends (what the enemies attack into),
            # carry-over included: gains alone miss Block kept from earlier turns.
            held = max([held] + [c.get("blk") or 0 for c in a.get("creatures") or [] if c.get("c") == "P"])
        elif e.get("k") == "hit" and a.get("by") == "P" and a.get("t") != "P" and "ovk" in a:
            # Damage that got past Block plus the overshoot on a kill: the whole hit.
            hit[key] = hit.get(key, 0) + (a.get("unb") or 0) + (a.get("ovk") or 0)
    out = {name: max(table.values()) for name, table in (("blocked", block), ("hit", hit)) if table}
    if held:
        out["held"] = held
    return out


def is_op(fights, encounters, cuts) -> bool:
    reading = run_reading(act_readings(fights, encounters, cuts), cuts) if fights else None
    return bool(reading and reading["op"])


def build(candidates, now, per_tab=PER_TAB) -> dict:
    """candidates: one dict per winning solo run, {slug, name, ts, char, asc, deck, op,
    blocked, held, hit}; blocked, held and hit may be missing."""
    since = now - WINDOW_DAYS * 86400
    recent = [c for c in candidates if c["ts"] >= since]

    def entry(c, n=None):
        out = {k: c.get(k) for k in ("slug", "name", "ts", "char", "asc")}
        if c.get("syn"):
            out["syn"] = c["syn"]
        return {**out, "n": n} if n is not None else out

    out = {"v": 1, "at": int(now), "days": WINDOW_DAYS,
           "op": [entry(c) for c in sorted((c for c in recent if c.get("op")), key=lambda c: -c["ts"])[:per_tab]]}
    for tab, field in (("blocked", "blocked"), ("held", "held"), ("hit", "hit"), ("deck", "deck")):
        best = sorted((c for c in recent if c.get(field)), key=lambda c: (-c[field], -c["ts"]))
        out[tab] = [entry(c, c[field]) for c in best[:per_tab]]
    return out
