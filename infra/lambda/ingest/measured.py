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
import math
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
_WEAK = "POWER.WEAK_POWER"
_DEBILITATE = "POWER.DEBILITATE_POWER"
# Core PowerModel types. Negative applications of Strength, Dexterity and Focus
# are also debuffs under the game's GetTypeForAmount rules.
_DEBUFFS = frozenset(f"POWER.{name}_POWER" for name in """
    AEONGLASS_DOMINION AMNESIA BIASED_COGNITION BORROWED_TIME CHAINS_OF_BINDING
    CONFUSED CONQUEROR CONSTRICT DAMPEN DEBILITATE DEMISE DISINTEGRATION DISLIKE_YOU
    DOOM ENCORE FLANKING FRAIL HANG HEX IMBALANCED INSATIABLE_DOMINION KNOCKDOWN
    LAGAVULIN_MATRIARCH_DOMINION MAGIC_BOMB MIND_ROT NEUROSURGE NO_BLOCK NO_DRAW
    NO_ENERGY_GAIN OBLIVION PLOW POISON RINGING SHRIEK SHRINK SIC_EM SLOTH SLOW
    SMOGGY STRANGLE SURROUNDED TAG_TEAM TAINTED TANGLED TENDER THE_GAMBIT
    VULNERABLE WASTE_AWAY WEAK WRAITH_FORM YOU_ARE_MINE
""".split())
_SIGNED_DEBUFFS = frozenset(f"POWER.{name}_POWER" for name in
                            ("DEXTERITY", "FOCUS", "SHRIEK", "SHRINK", "STRENGTH"))
_OTHER_DAMAGE_REDUCERS = {"POWER.SHRINK_POWER", "POWER.STRENGTH_POWER"}


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


align = dt.align_fights


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
        **({"damageBySlot": fight["damageBySlot"]}
           if fight.get("closed") and fight.get("damageBySlot") is not None else {}),
        **({"incomingBySlot": fight["incomingBySlot"]}
           if fight.get("incomingBySlot") is not None else {}),
        # A fun number: what hits carried past an enemy's last HP. Not damage, in no rate.
        **({"overkillDealt": fight["ovk_dealt"], "overkillBest": fight["ovk_best"]}
           if fight.get("ovk_dealt") else {}),
        "played": plays["played"] if plays else 0.0,
        "listPrice": plays["equiv"] if plays else 0.0,
        "spent": plays["spent"] if plays else 0.0,
    }


def party_fights(events):
    """Yield the same attempts, in the same order, as derive()."""
    fight = None
    for event in sorted(events, key=lambda event: event.get("q", 0)):
        if event.get("k") == "fight0":
            if fight is not None:
                yield fight
            fight = [event]
        elif fight is not None and fight[-1].get("k") != "fight1":
            fight.append(event)
    if fight is not None:
        yield fight


def damage_reduction(calculation, debilitated, debilitate_source):
    """Yield (source slot, damage reduced) for a calculation with an isolated modifier."""
    modifiers = calculation.get("modifiers")
    if not isinstance(modifiers, list) or len(modifiers) != 1 or not isinstance(modifiers[0], dict):
        return
    modifier, = modifiers
    model = modifier.get("model")
    source = modifier.get("sourceSlot")
    before, after = calculation["before"], calculation["after"]
    if isinstance(model, str) and model in _OTHER_DAMAGE_REDUCERS:
        yield source, int(before) - int(after)
    elif model == _WEAK:
        # Debilitate and the target's Paper Krane are folded into Weak's multiplier
        # by the game. Verify the multiplier before attributing their effects.
        for weak_factor in (0.75, 0.60):
            final_factor = 2 * weak_factor - 1 if debilitated else weak_factor
            if math.isclose(after, before * final_factor, rel_tol=0, abs_tol=1e-8):
                yield source, int(before) - int(before * 0.75)
                if debilitated:
                    yield debilitate_source, int(before * weak_factor) - int(after)
                break


def party_numbers(events, costs):
    """Read support and throughput without relying on the recorder's player identity."""
    start = events[0].get("a") or {}
    size = start.get("damageSlots")
    if start.get("support") != 1 or type(size) is not int or not 2 <= size <= 8:
        return {}
    if events[-1].get("k") != "fight1":
        return {}

    def seat(value):
        return value if type(value) is int and 0 <= value < size else None

    def count(value):
        return value if type(value) is int and value >= 0 else 0

    def delta(a):
        before, after = a.get("before"), a.get("after")
        if (type(before) in (int, float) and type(after) in (int, float)
                and math.isfinite(before) and math.isfinite(after)):
            return int(after) - int(before)
        return 0

    def add(source, target, key, amount):
        if source is not None and target is not None and source != target and amount > 0:
            row = support.setdefault((source, target), {})
            row[key] = row.get(key, 0) + amount

    def contributor(a):
        modifiers = a.get("modifiers") or []
        sources = {seat(m.get("sourceSlot")) for m in modifiers if isinstance(m, dict)}
        return next(iter(sources)) if len(sources) == 1 else None

    def hit_key(a):
        return tuple(a.get(k) for k in ("action", "sourceSlot", "targetId", "card"))

    turns = [set() for _ in range(size)]
    plays = [dict(draw=0, played=0, listPrice=0, spent=0, junk=0) for _ in range(size)]
    debuffs = [0] * size
    enemies = set()
    for event in events:
        a = event.get("a") or {}
        if event.get("k") == "snap":
            creatures = a.get("creatures")
            if isinstance(creatures, list):
                enemies.update(c["combatId"] for c in creatures
                               if isinstance(c, dict) and "move" in c and type(c.get("combatId")) is int)
        elif event.get("k") == "hit" and a.get("enemy") is True and type(a.get("targetId")) is int:
            enemies.add(a["targetId"])
    enemy_attacks, debilitate, reduced_hits = [], {}, set()
    support, actions, parents, discounts, extra_plays, resolved = {}, {}, {}, {}, {}, {}
    previous_kind, previous = None, {}
    for event in events:
        kind, a = event.get("k"), event.get("a") or {}
        source, target = seat(a.get("sourceSlot")), seat(a.get("targetSlot"))
        action, instance = count(a.get("action")), count(a.get("instance"))
        actor = actions.get(action)
        if kind == "action0" and count(a.get("id")):
            actions[a["id"]] = source
            parents[a["id"]] = count(a.get("parent"))
        elif kind == "atk" and a.get("side") == "Player" and isinstance(a.get("by"), str):
            if a.get("done") is False:
                enemy_attacks.append(a["by"])
            elif enemy_attacks and enemy_attacks[-1] == a["by"]:
                enemy_attacks.pop()
        elif kind == "pow" and target is None and type(a.get("targetId")) is int and a["targetId"] in enemies:
            power, amount = a.get("p"), a.get("d")
            if isinstance(power, str) and type(amount) is int:
                if source is not None and ((amount > 0 and power in _DEBUFFS)
                                           or (amount < 0 and power in _SIGNED_DEBUFFS)):
                    debuffs[source] += 1
                if power == _DEBILITATE and isinstance(a.get("c"), str):
                    name = a["c"]
                    if not count(a.get("n")):
                        debilitate.pop(name, None)
                    elif amount > 0:
                        debilitate[name] = source if debilitate.get(name, source) == source else None
        elif kind == "turn0" and target is not None and count(a.get("turn")):
            turns[target].add(a["turn"])
        elif kind == "draw1" and target is not None:
            plays[target]["draw"] += 1
            plays[target]["junk"] += a.get("card") in dt.JUNK
            if a.get("hand") is False:
                add(actor, target, "draw", 1)
        elif kind == "eps" and source is not None:
            plays[source]["spent"] += count(a.get("n"))
        elif kind == "play1" and source is not None:
            cost = costs.get(a.get("card"), 0)
            plays[source]["played"] += 1
            plays[source]["listPrice"] += 3 if cost == "X" else (cost or 0)
            if instance and a.get("playIndex") == 0 and a.get("auto") is False:
                discount = discounts.pop((source, instance), None)
                if discount and a.get("energySpent") == discount.get("after"):
                    helper = seat(discount.get("sourceSlot"))
                    add(helper, source, "energySaved", -delta(discount))
                    if discount["after"] == 0 and not a.get("starsSpent"):
                        add(helper, source, "freePlays", 1)
            if (a.get("auto") is True and a.get("playIndex") == 0 and a.get("energySpent") == 0
                    and not a.get("starsSpent") and a.get("card") not in dt.JUNK):
                add(actions.get(parents.get(action)), source, "freePlays", 1)
            extra = extra_plays.get(action)
            if (extra and extra.get("targetSlot") == source and extra.get("card") == a.get("card")
                    and extra["before"] <= count(a.get("playIndex")) < extra["after"]):
                add(contributor(extra), source, "extraPlays", 1)
        elif kind == "costReduction" and target is not None and instance and delta(a) < 0:
            discounts[target, instance] = a
        elif kind == "playCount" and action and type(a.get("before")) is int and delta(a) > 0:
            extra_plays[action] = a
        elif kind == "energy+":
            add(actor, target, "energy", count(a.get("n")))
        elif kind == "blk":
            add(source if source is not None else actor, target, "block", count(a.get("n")))
        elif kind == "gen" and a.get("card") not in dt.JUNK:
            add(source, target, "generated", 1)
        elif (kind == "damageResolved" and previous_kind == "damageCalc" and source is None
              and seat(a.get("petOwnerSlot")) is None and target is not None):
            # Enemy attacks need not have an action id. The immediately preceding
            # calculation must match the resolved hit and its pre-block damage.
            damage_id = count(a.get("damageId"))
            if (damage_id and damage_id not in reduced_hits and hit_key(previous) == hit_key(a)
                    and previous.get("targetSlot") == target
                    and a.get("targetId") is not None and a["targetId"] == a.get("originalTargetId")
                    and delta(previous) < 0 and previous["after"] >= 0
                    and int(previous["after"]) == count(a.get("blocked")) + count(a.get("intendedHpLoss"))):
                reduced_hits.add(damage_id)
                attacker = enemy_attacks[-1] if enemy_attacks else None
                if attacker is not None or not debilitate:
                    for helper, amount in damage_reduction(previous, attacker in debilitate, debilitate.get(attacker)):
                        add(seat(helper), target, "damageReduced", amount)
        elif (kind == "damageResolved" and previous_kind == "damageCalc" and action
              and (source is not None or seat(a.get("petOwnerSlot")) is not None)):
            # In one action, the calculation immediately preceding resolution must match
            # the exact unredirected hit. Mixed or unknown modifiers cannot be split.
            blocked, intended = count(a.get("blocked")), count(a.get("intendedHpLoss"))
            if (count(a.get("damageId")) and hit_key(previous) == hit_key(a)
                    and a.get("targetId") is not None and a["targetId"] == a.get("originalTargetId")
                    and delta(previous) > 0
                    and int(previous["after"]) == blocked + intended):
                hp = count(a.get("hpLost"))
                base_hp = max(0, intended - delta(previous))
                dealer = source if source is not None else seat(a.get("petOwnerSlot"))
                resolved[a["damageId"]] = (contributor(previous), dealer, max(0, hp - base_hp))
        elif kind == "hit" and a.get("enemy") is True:
            credit = resolved.pop(count(a.get("damageId")), None)
            if credit:
                helper, dealer, hp = credit
                add(helper, dealer, "damage", hp)
        previous_kind, previous = kind, a

    by_slot = [{key: round(value / len(played_turns), 2) for key, value in totals.items()}
               if played_turns else None for totals, played_turns in zip(plays, turns)]
    return {
        "playBySlot": by_slot,
        "debuffsBySlot": debuffs,
        "supportBySlot": [{"from": source, "to": target, **row}
                          for (source, target), row in sorted(support.items())],
    }


def measured(log, timeline) -> list[dict]:
    """One row per fight the log and the run's timeline both have, with a turn to read.
    Empty for a log in an older shape, or one nothing could be read from."""
    if not isinstance(log, dict) or log.get("v") != 3 or not log.get("log"):
        return []
    costs = card_table()["costs"]
    derived = dt.derive(log, {})  # the move table only feeds what an enemy was about to do
    if any(e.get("k") == "fight0" and (e.get("a") or {}).get("support") == 1
           for e in log["log"] if isinstance(e, dict)):
        for fight, events in zip(derived["fights"], party_fights(log["log"])):
            fight["partyNumbers"] = party_numbers(events, costs)
    rows = []
    for fight, node in align(derived["fights"], timeline or []):
        if not fight["turns"]:
            continue
        row = {"floor": node["floor"] + 1}
        row.update({k: round(v, 2) if isinstance(v, float) else v
                    for k, v in floor_numbers(fight, costs).items()})
        row.update(fight.get("partyNumbers", {}))
        rows.append(row)
    return rows
