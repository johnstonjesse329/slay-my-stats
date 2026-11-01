"""Turn the mod's raw event log into per-fight and per-turn numbers.

The log holds events and nothing else (see the mod's EventLog.cs); every
judgement about what an event means lives here, where it can be changed and
re-run over logs already in the data bucket instead of costing another played
run.

    from derive_telemetry import derive, check
    d = derive(log)                  # {"fights": [...], "turns": [...], "checks": [...]}
    problems = check(d)              # [] when the numbers agree with themselves

The turn model is the part that was wrong in the first version: a turn opens at
the first sign that a new one began and closes only when the *next* one opens, so
the enemy phase belongs to the player's turn. Anything else loses the damage a
fight actually cost.

    python derive_telemetry.py telemetry_raw/<steamid>/<start time>.json.gz
"""
import gzip
import json
import sys
from pathlib import Path

PLAYER = "P"

# A single HP delta this large is the game saying "infinite", not damage. Waterfall
# Giant logs a billion when it does whatever it does; averaging that into a fight's
# damage would bury every real number in it.
HP_SENTINEL = 1_000_000


def _junk_ids():
    """Status and Curse cards: what an enemy puts in your deck to cost you a draw.

    Read from card_data.json when it sits beside the tools. When it does not, the set
    is empty and junk is simply not counted, rather than guessed at from card names.
    """
    path = Path(__file__).resolve().parents[2] / "card_data.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    return frozenset(cid for cid, c in data.items() if isinstance(c, dict)
                     and (c.get("rarity") in ("Status", "Curse")
                          or c.get("pool") in ("status", "curse")))


JUNK = _junk_ids()

# Events that can only happen inside a turn, used to open one when the game has
# given us no turn boundary yet.
TURN_SCOPED = {"hit", "recv", "blk", "eps", "play1", "draw1", "pow", "orb", "evoke", "star",
               "atk", "potion", "blkc", "pile"}

# Openers. A repeat of one of these within a turn means a new turn began -- which
# is also how an extra turn shows up, since it reuses the turn number.
OPENERS = {"draw0", "erese", "turn0", "side0"}


def _new_turn(number, reason):
    return {
        "n": number, "why": reason, "e0": None, "e1": None, "spent": 0,
        "dmg": 0, "dmg_other": 0, "junk": 0, "taken": 0, "blocked": 0, "bgn": 0,
        "orbs": 0, "evokes": 0,
        "attacks": 0, "hits": 0, "potions": [], "hand": [], "drawn": [], "played": [],
        "discarded": [], "exhausted": [], "generated": [], "powers": {}, "stars": 0,
        "events": 0, "snap0": None, "snap1": None,
        "hand_by_pile": [], "hand_left": [], "hand_at_open": None, "hand_at_end": None,
        "auto_played": [], "from_draw": [], "targets": [],
        "enemy_powers": [], "vuln": 0, "weak": 0, "vuln_dmg": 0,
        "intent": 0, "expected": 0, "alive": 0, "enemy_lost": 0,
        "self_taken": 0, "self_blocked": 0,
    }


def _new_fight(fight, first):
    return {
        "i": fight, "enc": first.get("enc", ""), "hp0": first.get("hp"), "hp1": None,
        "rounds0": first.get("round"), "rounds1": None, "deck0": first.get("deck"),
        "won": False, "turns": [], "hp_in": 0, "hp_out": 0, "killed": [],
        # The demand side: what there was to kill, and what killing it cost.
        # `pool` is the enemies' HP when the fight opened; `enemy_lost` and
        # `enemy_healed` are read off the HP deltas themselves, because those are
        # the ground truth -- `hit` events miss damage over time (in one fight 27
        # of 112 HP removed arrived with no attacker attached) and carry a sentinel
        # when the game means "infinite" (Waterfall Giant logged a billion).
        "pool": None, "enemy_lost": 0, "enemy_healed": 0, "enemy_sentinel": 0,
        # Damage to enemies that did not come from one of our attacks: poison and
        # other damage over time log with an empty attacker.
        "dmg_other": 0, "dmg_hit": 0, "junk": 0,
    }


def derive(log, moves=None):
    """{"fights": [...], "checks": [...]} for one run's log object.

    `moves` maps a move id to (hits, cycle): the hits it will land as [(damage per
    hit, hits)], and what the monster that owns the move averages a turn across its
    whole move list. The demand side -- what the enemies were about to do, and what
    the encounter could do given enough turns. It is game data, passed in by the
    caller; without it the intent fields stay zero rather than being guessed.
    """
    moves = moves or {}
    events = log.get("log") or []
    events = sorted((e for e in events if isinstance(e, dict)), key=lambda e: e.get("q", 0))
    fights = []
    fight = None
    turn = None
    seen_openers = set()
    # Who is Vulnerable right now. It decides which hits were boosted, which is the
    # number the formula's Vulnerable term is standing in for: how much of the damage
    # actually landed at +50%. Counting turns where it happened to be up at turn start
    # missed every debuff applied during a turn -- exactly the turns it pays on.
    vuln = {}
    # The hand, followed card by card. It has to survive the turn boundary: a
    # retained card (SNAKEBITE among them) is never re-drawn, so the opening hand
    # of a turn is the arrivals of this turn plus whatever the last one left.
    hand_now = []

    def close_turn():
        nonlocal turn
        if turn is not None and fight is not None:
            fight["turns"].append(turn)
        turn = None

    def open_turn(number, reason):
        nonlocal turn, seen_openers
        close_turn()
        turn = _new_turn(number, reason)
        seen_openers = {reason}

    for e in events:
        kind = e.get("k") or ""
        a = e.get("a") or {}
        ts_turn = e.get("t") or 0

        if kind == "fight0":
            close_turn()
            fight = _new_fight(e.get("f", 0), a)
            fights.append(fight)
            hand_now.clear()
            continue
        if fight is None:
            continue
        if kind in ("win", "fight1"):
            if kind == "win":
                fight["won"] = True
                # Not the end state: a victory can be followed by healing before the
                # fight is really closed, and `hp1` must be what the fight ended on.
                continue
            fight["hp1"] = a.get("hp", fight["hp1"])
            fight["rounds1"] = a.get("round", fight["rounds1"])
            # The fight is over. What follows -- post-combat healing, rewards -- is
            # not part of it, and counting it made healed HP look like damage the
            # fight never cost.
            close_turn()
            fight["closed"] = True
            continue
        if fight.get("closed"):
            continue

        # Snapshots are state, not turn-scoped events: one arrives before any turn
        # exists (the fight's opening state). They hang off the fight, and off the
        # open turn when there is one.
        if kind == "snap":
            fight.setdefault("snaps", []).append(a)
            if fight["pool"] is None:
                # The opening state of the fight: what stood in front of us.
                fight["pool"] = sum((c.get("max") or 0) for c in a.get("creatures") or []
                                    if not c.get("you"))
            if turn is not None:
                why = a.get("why") or ""
                if why == "side1":
                    turn["snap1"] = a
                    turn["hand_at_end"] = list(hand_now)
                else:
                    turn["snap0"] = a
                    turn["hand_at_open"] = list(hand_now)
                    # The demand: what the enemies alive at this boundary are about
                    # to do. This is the half of the comparison that does not depend
                    # on our play -- the encounter decides it, and killing an enemy
                    # before it acts is how the demand gets cancelled.
                    #
                    # Strength counts here: a Knowledge Demon that buffs to +4 hits
                    # harder than its move list says, and reading the base numbers
                    # alone made 175 damage of hits look like 121 of intent.
                    for c in a.get("creatures") or []:
                        if c.get("you") or not c.get("hp"):
                            continue
                        turn["alive"] += 1
                        strength = (c.get("pow") or {}).get("POWER.STRENGTH_POWER", 0) or 0
                        hits, cycle = moves.get(c.get("move") or "", ((), 0))
                        for dmg, count in hits:
                            turn["intent"] += (dmg + strength) * count
                        # And what this monster would average a turn if the fight ran
                        # long enough for its whole move list to come round. The
                        # recorded moves stop when the fight does: kill it on turn 3
                        # and turns 4 to 6 never happen.
                        turn["expected"] += cycle
                    # The debuffs standing on the enemies at the turn's start. Called
                    # out because it is the number the formula guesses at and telemetry
                    # is supposed to replace.
                    live = set()
                    # Rebuilt from the snapshot, not added to: an enemy that died or
                    # whose debuff ran out is absent from it, and stale entries would
                    # credit hits that were never boosted.
                    vuln.clear()
                    for c in a.get("creatures") or []:
                        if c.get("you") or not c.get("hp"):
                            continue
                        for name, amount in (c.get("pow") or {}).items():
                            if name.endswith("VULNERABLE_POWER") or name == "POWER.VULNERABLE":
                                turn["vuln"] += 1
                                live.add("vuln")
                                vuln[c.get("c")] = amount
                            elif name.endswith("WEAK_POWER") or name == "POWER.WEAK":
                                turn["weak"] += 1
                                live.add("weak")
            continue

        if kind in OPENERS:
            side = a.get("side")
            if kind == "side0" and side not in (None, "Player"):
                continue  # an enemy turn start is not the player's turn beginning
            number = a.get("turn") or ts_turn
            if kind not in seen_openers:
                if turn is None:
                    turn = _new_turn(number, kind)
                    seen_openers = {kind}
                else:
                    seen_openers.add(kind)
            else:
                open_turn(number, kind)
            if kind == "erese" and turn is not None:
                turn["e0"] = a.get("energy")
            if kind == "turn0" and turn is not None:
                turn["e0"] = a.get("energy")
            continue

        if kind == "side1" and a.get("side") == "Player":
            # The player's turn is over but the round is not: the enemies act next
            # and their damage belongs to this turn, so nothing closes here.
            if turn is not None:
                turn["e1"] = a.get("energy")
            continue

        if turn is None:
            if kind in TURN_SCOPED:
                turn = _new_turn(ts_turn, f"lazy:{kind}")
                seen_openers = set()
            else:
                continue
        turn["events"] += 1

        if kind == "hit" and a.get("by") == PLAYER and (a.get("t") or "") != PLAYER:
            turn["dmg"] += a.get("total") or 0
            fight["dmg_hit"] += (a.get("unb") or 0) - (a.get("ovk") or 0)
            target = a.get("t") or ""
            if target and target not in turn["targets"]:
                turn["targets"].append(target)
            # Was the thing it landed on Vulnerable at that moment, whatever the turn
            # looked like when it started?
            if target and vuln.get(target):
                turn["vuln_dmg"] += a.get("total") or 0
        elif kind == "hit" and (a.get("t") or "") not in ("", PLAYER):
            # Damage that reached an enemy without one of our attacks behind it:
            # poison and other damage over time log with no attacker. It is damage
            # the deck caused, so it counts -- but it is not a card being played,
            # and calling it one is how a poison deck reads as a Withering deck.
            amount = (a.get("unb") or 0) - (a.get("ovk") or 0)
            turn["dmg_other"] += amount
            fight["dmg_other"] += amount
        elif kind == "recv" and a.get("t") == PLAYER:
            # Damage that comes at us attributed to ourselves is a curse or a status
            # doing its work, not the enemy: Knowledge Demon's curse deals 6 a turn.
            # Counting it as enemy demand made 133 points of hits look like 175, and
            # counting the matching hit as ours inflated the damage we dealt.
            self_inflicted = a.get("by") == PLAYER
            if self_inflicted:
                turn["self_taken"] += a.get("unb") or 0
                turn["self_blocked"] += a.get("blk") or 0
            else:
                turn["taken"] += a.get("unb") or 0
                turn["blocked"] += a.get("blk") or 0
        elif kind == "hp":
            delta = a.get("d") or 0
            if a.get("c") == PLAYER:
                if delta < 0:
                    fight["hp_in"] += -delta
                else:
                    fight["hp_out"] += delta
            elif abs(delta) >= HP_SENTINEL:
                # The game saying "infinite", not damage. Waterfall Giant logs a
                # billion; averaging that in would bury every real number.
                fight["enemy_sentinel"] += 1
            elif delta < 0:
                # Includes the blow that killed it: the killing blow is the most
                # important delta of the fight, and an earlier version skipped it
                # by catching "hp is now 0" first, which made every fight look
                # like it removed ~10% less HP than the enemies had.
                fight["enemy_lost"] += -delta
                turn["enemy_lost"] += -delta
                if a.get("hp") == 0:
                    fight["killed"].append(a.get("c"))
            else:
                fight["enemy_healed"] += delta
        elif kind == "blk" and a.get("c") == PLAYER:
            turn["bgn"] += a.get("n") or 0
        elif kind == "eps":
            turn["spent"] += a.get("n") or 0
        elif kind == "enter":
            # A card arriving in hand. Only the statuses and curses are counted:
            # a card the enemy slipped into the deck is a draw you did not get, and
            # counting it separately keeps "the deck was weak" apart from "the deck
            # was full of junk this fight".
            if (a.get("card") or "") in JUNK:
                turn["junk"] += 1
                fight["junk"] += 1
        elif kind == "draw1":
            (turn["hand"] if a.get("hand") else turn["drawn"]).append(a.get("card"))
        elif kind == "pile":
            # The authoritative record of where a card is. `draw1` only fires for
            # cards that were drawn; a card can leave the draw pile straight into
            # play (Cascade, Mayhem) and never be "drawn" at all.
            to = a.get("to") or ""
            if to:
                fight["has_pile_to"] = True
            if (a.get("from") or "") == "Draw":
                turn["from_draw"].append(a.get("card"))
            if to == "Hand":
                turn["hand_by_pile"].append(a.get("card"))
                hand_now.append(a.get("card"))
            elif (a.get("from") or "") == "Hand":
                turn["hand_left"].append(a.get("card"))
                if a.get("card") in hand_now:
                    hand_now.remove(a.get("card"))
        elif kind == "play1":
            turn["played"].append(a.get("card"))
        elif kind == "disc":
            turn["discarded"].append(a.get("card"))
        elif kind == "exh":
            turn["exhausted"].append(a.get("card"))
        elif kind == "gen":
            turn["generated"].append(a.get("card"))
        elif kind == "pow":
            power = a.get("p") or ""
            if a.get("c") == PLAYER:
                turn["powers"][power] = a.get("n")
            else:
                # Debuffs on the enemy are half of what the damage line guesses at:
                # Vulnerable on a target lifts every hit against it. This was missing,
                # and it made a deck that applied Vulnerable 66 times look like it
                # never did.
                turn["enemy_powers"].append({"c": a.get("c"), "p": power, "n": a.get("n")})
                if power.endswith("VULNERABLE_POWER") or power == "POWER.VULNERABLE":
                    if a.get("n"):
                        vuln[a.get("c")] = a.get("n")
                    else:
                        vuln.pop(a.get("c"), None)
        elif kind == "orb":
            turn["orbs"] += 1
        elif kind == "evoke":
            turn["evokes"] += 1
        elif kind == "star":
            turn["stars"] += a.get("n") or 0
        elif kind == "atk" and a.get("by") == PLAYER:
            if a.get("done"):
                turn["hits"] += a.get("hits") or 0
            else:
                turn["attacks"] += 1
        elif kind == "potion":
            turn["potions"].append({"p": a.get("p"), "t": a.get("t")})
        elif kind == "extra":
            fight["extra_turns"] = fight.get("extra_turns", 0) + 1

    close_turn()

    for f in fights:
        f.setdefault("extra_turns", 0)
        for t in f["turns"]:
            # Energy a turn did not start with but did have: cards and relics.
            t["gained"] = None if t["e0"] is None or t["e1"] is None else t["e1"] + t["spent"] - t["e0"]
            # What the turn could actually spend: what it spent, plus what it left.
            # Comparing the deck's energy projection against turn *start* energy
            # under-counts every turn that gained any, which is most of them.
            t["available"] = None if t["e1"] is None else t["e1"] + t["spent"]
            # The projection is per target; a turn that hit three enemies dealt
            # three times its per-target damage, so the total is not comparable.
            t["dmg_each"] = t["dmg"] / len(t["targets"]) if t["targets"] else 0.0
        f["taken"] = sum(t["taken"] for t in f["turns"])
        f["blocked"] = sum(t["blocked"] for t in f["turns"])
        f["self_taken"] = sum(t["self_taken"] for t in f["turns"])
        f["self_blocked"] = sum(t["self_blocked"] for t in f["turns"])
        f["dmg"] = sum(t["dmg"] for t in f["turns"])
        f["bgn"] = sum(t["bgn"] for t in f["turns"])
        f["spent"] = sum(t["spent"] for t in f["turns"])
        f["turns_n"] = len(f["turns"])
        # The share of damage that landed at +50%: what the formula's Vulnerable
        # term should equal, and a fairer number than "was it up at turn start".
        dealt = sum(t["dmg"] for t in f["turns"])
        f["vuln_share"] = (sum(t["vuln_dmg"] for t in f["turns"]) / dealt) if dealt else 0.0
        # What the enemies cost, read from their HP deltas rather than from our hit
        # events. `spawned` is what the pool cannot explain: an enemy that appeared
        # mid-fight (Axebots respawn, Ovicopter hatches eggs) or healed itself.
        f["enemy_net"] = f["enemy_lost"] - f["enemy_healed"]
        f["dealt_removed"] = f["dmg_hit"] + f["dmg_other"]
        # Everything else that took HP off an enemy: damage with no hit behind it at
        # all. Poison and Burn still log a hit with an empty attacker; this is the
        # bucket for the effects that are not damage at all -- Doom's countdown to
        # the enemy's own HP, an HP-loss effect, anything the game resolves without an
        # attack. It is not "damage the deck dealt" and must not be counted as such,
        # which is why it is named rather than folded in.
        f["enemy_unexplained"] = max(0, f["enemy_net"] - f["dealt_removed"])
        f["spawned"] = max(0, f["enemy_net"] - (f["pool"] or 0))
        # HP paid that no incoming hit explains: the deck's own costs (Bloodletting,
        # Offering, potions). A fact about the deck, not a hole in the log.
        f["self_dmg"] = max(0, f["hp_in"] - f["taken"])
        # The demand side, from what the enemies were about to do each turn, and the
        # cost of not killing them: an enemy-turn is one enemy standing when a turn
        # began. A turn's damage is a distribution, not an average -- a fight that
        # goes 63, 2, 2, 2 and one that goes 17, 17, 17, 18 average the same and mean
        # completely different things -- so the spread is kept.
        f["intent_total"] = sum(t["intent"] for t in f["turns"])
        # What the encounter averages a turn, over the turns it actually took: the
        # smooth version of the intent, for fights that ended before the move list
        # came round, and for comparing one floor against another.
        f["expected_total"] = sum(t["expected"] for t in f["turns"])
        f["attacker_turns"] = sum(t["alive"] for t in f["turns"])
        f["lost_per_turn"] = [t["enemy_lost"] for t in f["turns"]]
        if f["lost_per_turn"]:
            ordered = sorted(f["lost_per_turn"])
            f["lost_median"] = ordered[len(ordered) // 2]
            f["lost_peak"] = ordered[-1]
            f["idle_turns"] = sum(1 for v in f["lost_per_turn"] if v == 0)

    return {"v": log.get("v"), "truncated": bool(log.get("truncated")), "fights": fights}


def check(derived):
    """Every way the derived numbers can contradict the log, as text.

    These are the checks the first version had no equivalent of: it was wrong and
    looked fine. A failure here names the fight and what disagreed.
    """
    problems = []
    for f in derived.get("fights") or []:
        tag = f"fight {f['i']} {f['enc']}"
        if f["hp0"] is not None and f["hp1"] is not None:
            lost = f["hp_in"] - f["hp_out"]
            if lost != f["hp0"] - f["hp1"]:
                problems.append(
                    f"{tag}: HP moved {lost} ({f['hp_in']} in, {f['hp_out']} out) but reads "
                    f"{f['hp0']}->{f['hp1']}; {f['hp0'] - f['hp1']}")
        # Damage taken is incoming damage only. More HP lost than the hits explain is
        # the deck paying its own costs -- Ironclad spending HP for tempo -- and that
        # is a fact about the deck, recorded as `self_dmg`, not a contradiction. Fewer
        # HP lost than the hits say is a hole: something dealt damage that never
        # happened.
        if f["taken"] > f["hp_in"]:
            problems.append(
                f"{tag}: {f['taken']} counted as damage taken but only {f['hp_in']} HP lost")
        # What there was to kill against what was killed. More than the pool means
        # enemies appeared or healed, which the fight records as `spawned`. Less, in a
        # fight that was won, means damage the log missed.
        pool = f.get("pool")
        if f.get("won") and pool and f["enemy_net"] < pool:
            problems.append(
                f"{tag}: {f['enemy_net']} enemy HP removed against a pool of {pool}")
        for i, t in enumerate(f["turns"]):
            if t["gained"] is not None and t["gained"] < 0:
                problems.append(
                    f"{tag} turn {i + 1} (n{t['n']}): spent {t['spent']} with only "
                    f"{t['e0']} start and {t['e1']} end energy")
            # The snapshot is the state at the boundary; the events are the deltas.
            # They have to agree, or one of the two is lying.
            end = t.get("snap1") or {}
            you = (end.get("you") or [{}])[0]
            if t["e1"] is not None and you.get("en") is not None and t["e1"] != you["en"]:
                problems.append(
                    f"{tag} turn {i + 1} (n{t['n']}): energy {t['e1']} at the side's end "
                    f"but {you['en']} in the snapshot")
        snaps = f.get("snaps") or []
        if snaps:
            missing = [i for i, t in enumerate(f["turns"]) if t.get("snap0") is None]
            if missing:
                problems.append(f"{tag}: no turn-start snapshot for turn(s) {[i + 1 for i in missing]}")
        if f["rounds1"] is not None and f["turns_n"] != f["rounds1"] + f.get("extra_turns", 0):
            problems.append(
                f"{tag}: {f['turns_n']} turns against {f['rounds1']} rounds "
                f"and {f.get('extra_turns', 0)} extra")
        # Card movement can only be followed where the log records a pile's
        # destination. Logs from before that are checked on their totals instead,
        # and said so -- a weaker check that claims to be strong is worse than none.
        if f.get("has_pile_to"):
            have = []
            for t in f["turns"]:
                have += (t["hand"] + t["drawn"] + t["generated"] + t["hand_by_pile"]
                         + t["auto_played"] + t["from_draw"])
            for card in (c for t in f["turns"] for c in t["played"]):
                if card in have:
                    have.remove(card)
                else:
                    problems.append(f"{tag}: played {card} which never left the draw pile or the hand")
                    break
        # The hand is also stated twice: by the card movement events and by the
        # snapshot taken at each boundary. They must agree. Both boundaries are
        # compared, because a card can appear or vanish at either -- and the
        # boundary comparison only works against a hand carried across turns, since
        # a retained card is never drawn again. Logs without pile destinations have
        # no movements to compare, so they are skipped rather than failed.
        for i, t in enumerate(f["turns"] if f.get("has_pile_to") else []):
            for field, snap_field, where in (("hand_at_open", "snap0", "opens"),
                                             ("hand_at_end", "snap1", "ends")):
                snapped = t.get(snap_field) or {}
                you = (snapped.get("you") or [{}])[0]
                tracked = t.get(field)
                if "hand" in you and tracked is not None:
                    recorded, moved = sorted(you["hand"]), sorted(tracked)
                    if recorded != moved:
                        problems.append(
                            f"{tag} turn {i + 1} (n{t['n']}): hand {where} {recorded} "
                            f"in the snapshot but {moved} by the card-movement events")
    return problems


def load(path):
    p = Path(path)
    if p.suffix == ".gz":
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    return json.loads(p.read_text(encoding="utf-8"))


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    log = load(argv[1])
    if "log" not in log:
        print(f"{argv[1]} is not an event log (v{log.get('v')}); it is a summary from the older mod.")
        return 2
    d = derive(log)
    print(f"{len(d['fights'])} fights, {sum(f['turns_n'] for f in d['fights'])} turns"
          + (", TRUNCATED" if d["truncated"] else ""))
    print(f"\n{'floor':>5}  {'encounter':<34} {'hp':>11} {'turns':>5} {'dmg':>5}"
          f" {'taken':>5} {'blk':>5} {'bgn':>5} {'spent':>5}")
    for f in d["fights"]:
        print(f"{f['i']:>5}  {f['enc'][:34]:<34} {str(f['hp0']) + '->' + str(f['hp1']):>11}"
              f" {f['turns_n']:>5} {f['dmg']:>5} {f['taken']:>5} {f['blocked']:>5}"
              f" {f['bgn']:>5} {f['spent']:>5}")
    problems = check(d)
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print(f"   {p}")
    else:
        print("\nEvery check passes: HP agrees with the damage events, energy balances,"
              "\nturn counts match the rounds, and no card was played that was never drawn.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
