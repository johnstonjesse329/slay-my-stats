"""What a run's event log says each fight did, one row per floor, for the Keeping Up charts.

The Runs page draws card draw, energy and the damage split from these. They are worked
out once, when a run is ingested, and stored on the run record, so the page needs no
second file and no new route: a run opened on the site already carries them.

The reading itself is tools/power_curve/derive_telemetry.py, copied into the bundle next
to this file. This module adds what the page needs on top: pairing the log's fights with
the run's combat floors, and the per-floor numbers. tools/power_curve/export_measured.py
does the same for the owner's local logs; infra/tests/test_measured.py holds the two
together on real logs, so a change to one that the other doesn't follow fails there.

    measured(log, timeline) -> [{"floor": 3, "draw": 5.0, "taken": 7, ...}, ...]
"""
import json
import statistics
import sys
from pathlib import Path

# The repo root when this runs from the repo; None in the Lambda, where the file sits at
# /var/task/measured.py with nothing above it (indexing parents there raised at import).
_parents = Path(__file__).resolve().parents
_REPO = _parents[3] if len(_parents) > 3 else None
try:
    import derive_telemetry as dt  # bundled beside this file in the Lambda
except ImportError:  # the dev server and tests run from the repo
    sys.path.append(str(_REPO / "tools" / "power_curve"))
    import derive_telemetry as dt

_CARDS = Path(__file__).with_name("measured_cards.json")
_cards = None


def card_table() -> dict:
    """{"costs": {card id: cost, "X", or None for one that can't be played}, "junk": [ids]},
    built from the game's card data when the bundle is made (tools/build_measured_cards.py).
    In the repo it is cut from card_data.json on the spot. With neither it is empty:
    every card then costs nothing and no junk is counted, which shows up as flat Card
    cost lines rather than as a wrong number."""
    global _cards
    if _cards is None:
        try:
            _cards = json.loads(_CARDS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            try:
                sys.path.append(str(_REPO / "tools"))
                import build_measured_cards
                _cards = build_measured_cards.build(
                    json.loads(build_measured_cards.SOURCE.read_text(encoding="utf-8")))
            except (OSError, ValueError, ImportError, TypeError):
                _cards = {"costs": {}, "junk": []}
        dt.JUNK = frozenset(_cards.get("junk") or ())
    return _cards


def align(fights, timeline):
    """Pairs the log's fights with the run's combat nodes by encounter id, in order.

    A fight can exist in one list and not the other -- a run written by an older
    parser may lack a fight the log has -- so this aligns on content rather than
    assuming the two lists line up. Sequence alignment keeps the order and skips
    whichever side is missing an entry.
    """
    combats = [n for n in timeline if n.get("turns") or str(n.get("enc") or "").startswith("ENCOUNTER.")]
    a = [f.get("enc") or "" for f in fights]
    b = [n.get("fight") or n.get("enc") or "" for n in combats]

    # Longest common subsequence on the encounter ids: O(len(a)*len(b)), and both
    # lists are under a few hundred.
    n, m = len(a), len(b)
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            table[i][j] = (table[i + 1][j + 1] + 1 if a[i] and a[i] == b[j]
                           else max(table[i + 1][j], table[i][j + 1]))
    pairs, i, j = [], 0, 0
    while i < n and j < m:
        if a[i] and a[i] == b[j]:
            pairs.append((fights[i], combats[j]))
            i += 1
            j += 1
        elif table[i + 1][j] >= table[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


def throughput(fight, costs):
    """What a fight's turns put out: cards played, what those plays would have cost at
    list price (`equiv`), and the energy actually spent. A card played for free is energy
    the deck did not have to spend, so raw energy under-reads a deck that cheats cards in."""
    turns = fight["turns"]
    if not turns:
        return None
    return {
        "played": statistics.mean(len(t["played"]) for t in turns),
        "equiv": statistics.mean(sum(costs.get(c, 0) for c in t["played"]) for t in turns),
        "spent": statistics.mean(t["spent"] for t in turns),
    }


def floor_numbers(fight, costs):
    """What one fight actually did, for the page's three charts."""
    turns = fight["turns"]
    # Cards drawn, not cards seen: a Shiv, a retained card or a Cascade off the draw pile
    # is played without being drawn, so more can be played than this says.
    drawn = [len(t["hand"]) + len(t["drawn"]) for t in turns]
    # They act after you, so a fight you win on your own turn gives them one turn less.
    swung = [t for t in turns if t["enemy_side"]]
    # An X card lists at 3, as it does in the formula.
    plays = throughput(fight, {c: 3 if v == "X" else v or 0 for c, v in costs.items()})
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


def measured(log, timeline) -> list[dict]:
    """One row per fight the log and the run's timeline both have, with a turn to read.
    Empty for a log in an older shape, or one nothing could be read from."""
    if not isinstance(log, dict) or log.get("v") != 3 or not log.get("log"):
        return []
    costs = card_table()["costs"]
    derived = dt.derive(log, {})  # the move table only feeds what an enemy was about to do
    rows = []
    for fight, node in align(derived["fights"], timeline or []):
        if not fight["turns"]:
            continue
        row = {"floor": node["floor"] + 1}
        row.update({k: round(v, 2) if isinstance(v, float) else v
                    for k, v in floor_numbers(fight, costs).items()})
        rows.append(row)
    return rows
