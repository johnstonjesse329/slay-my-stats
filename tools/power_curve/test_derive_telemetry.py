"""The deriver's tests: every case is a log the mod could produce.

These run in a second and need neither the game nor a network. The first one is
the v1 failure itself, kept as a regression: an enemy-phase hit must land in the
player's turn, or the run under-reports what it cost.
"""
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import derive_telemetry as dt  # noqa: E402


def ev(q, kind, **a):
    return {"q": q, "f": 0, "t": 1, "k": kind, "a": a}


def fight(hp0=80, hp1=71, dealt=9):
    """One fight, laid out in the order the game actually fires these.

    The order is copied from a real transcript (run 1793316666), not guessed: the
    hand is dealt after the energy reset and before AfterPlayerTurnStart, cards
    move between piles around every play, and the enemy acts after the player's
    side has ended.

    `dealt` is what the player did to the enemy (which does not touch the player's
    HP); the damage the player *took* is `hp0 - hp1`, so the HP events and the
    damage events agree by construction.
    """
    taken = hp0 - hp1
    return [
        ev(1, "fight0", enc="ENCOUNTER.X", hp=hp0, round=1, deck=12),
        ev(2, "side0", side="Player", round=1, turn=1),
        ev(3, "erese", turn=1, energy=3, max=3),
        ev(4, "draw0", turn=1, energy=3, hand=0, max=10),
        ev(5, "pile", card="A", **{"from": "Draw", "to": "Hand"}),
        ev(6, "draw1", card="A", hand=True),
        ev(7, "pile", card="B", **{"from": "Draw", "to": "Hand"}),
        ev(8, "draw1", card="B", hand=True),
        ev(9, "turn0", turn=1, energy=3, stars=0, round=1),
        ev(10, "side2", side="Player", round=1, turn=1),
        ev(11, "eps", n=1, card="A"),
        ev(12, "pile", card="A", **{"from": "Hand", "to": "Play"}),
        ev(13, "atk", by="P", src="A", side="Enemy", done=False, hits=0),
        ev(14, "hit", by="P", t="E0", total=dealt, blk=0, unb=dealt, ovk=0),
        ev(15, "atk", by="P", src="A", side="Enemy", done=True, hits=1),
        ev(16, "play1", card="A", up=0, auto=False),
        ev(17, "pile", card="A", **{"from": "Play", "to": "Discard"}),
        ev(18, "side1", side="Player", energy=2, round=1),
        ev(19, "side0", side="Enemy", round=1, turn=1),
        ev(20, "side2", side="Enemy", round=1, turn=1),
        ev(21, "atk", by="E0", src="MONSTER.X", side="Player", done=False, hits=0),
        ev(22, "hit", by="E0", t="P", total=taken, blk=0, unb=taken, ovk=0),
        ev(23, "recv", t="P", by="E0", total=taken, blk=0, unb=taken, ovk=0,
           broke=False, full=False, kill=False),
        ev(24, "hp", c="P", d=-taken, hp=hp1),
        ev(25, "atk", by="E0", src="MONSTER.X", side="Player", done=True, hits=1),
        ev(26, "side1", side="Enemy", energy=2, round=1),
        ev(27, "fight1", hp=hp1, round=1),
    ]


class TurnModel(unittest.TestCase):
    def test_enemy_phase_damage_belongs_to_the_players_turn(self):
        # The v1 bug: the turn was closed at the player's side end, so this hit
        # vanished. It must be in turn 1.
        d = dt.derive({"v": 3, "log": fight()})
        f = d["fights"][0]
        self.assertEqual(len(f["turns"]), 1)
        self.assertEqual(f["turns"][0]["taken"], 9)
        self.assertEqual(f["taken"], 9)

    def test_the_killing_blow_counts_in_full_overkill_included(self):
        # The hit that kills logs `hit`, `hp` to 0 and `die` with no `recv` behind it
        # (run 1793674597: 6 HP left, 9 blocked, 14 through). Damage taken is what the
        # blow carried, not the HP there was left to lose.
        log = fight()
        log[-1]["q"] = 40  # events are read in q order; the fight closes after the blow
        log += [
            ev(30, "hp", c="P", d=-6, hp=0),
            ev(31, "hit", by="E0", t="P", total=15, blk=9, unb=6, ovk=8),
            ev(32, "die", c="P", stop=False),
        ]
        f = dt.derive({"v": 3, "log": log})["fights"][0]
        self.assertEqual(f["taken"], 9 + 14)
        self.assertEqual(f["blocked"], 9)
        self.assertEqual(f["overkill"], 8)
        self.assertEqual(f["self_dmg"], 0)

    def test_a_hit_with_its_recv_is_not_counted_again_when_the_player_dies(self):
        log = fight()
        log[-1]["q"] = 40
        log.append(ev(32, "die", c="P", stop=False))
        f = dt.derive({"v": 3, "log": log})["fights"][0]
        self.assertEqual(f["taken"], 9)
        self.assertEqual(f["overkill"], 0)

    def test_extra_turn_opens_another_turn(self):
        log = fight()
        cut = len(log) - 1  # everything before fight1
        log[cut:cut] = [
            ev(30, "side1", side="Enemy", energy=2, round=1),
            ev(31, "extra", turn=1, energy=3),
            ev(32, "side0", side="Player", round=1, turn=1),
            ev(33, "erese", turn=1, energy=3, max=3),
            ev(34, "draw0", turn=1, energy=3, hand=0, max=10),
            ev(35, "turn0", turn=1, energy=3, stars=0, round=1),
        ]
        for i, e in enumerate(log, start=1):
            e["q"] = i
        f = dt.derive({"v": 3, "log": log})["fights"][0]
        self.assertEqual(len(f["turns"]), 2, "the extra turn is a second turn")
        self.assertEqual(f.get("extra_turns"), 1)

    def test_hand_and_draws_are_told_apart(self):
        # The v1 bug's other half: the hand is dealt as drawn cards, and every one
        # of them has to end up in `hand`, not silently dropped.
        d = dt.derive({"v": 3, "log": fight()})
        t = d["fights"][0]["turns"][0]
        self.assertEqual(t["hand"], ["A", "B"])
        self.assertEqual(t["drawn"], [])
        self.assertEqual(t["played"], ["A"])

    def test_draw_after_the_turn_start_is_a_draw(self):
        log = fight()[:8] + [ev(9, "draw1", card="C", hand=False)] + fight()[8:]
        for i, e in enumerate(log, start=1):
            e["q"] = i
        t = dt.derive({"v": 3, "log": log})["fights"][0]["turns"][0]
        self.assertEqual(t["hand"], ["A", "B"])
        self.assertEqual(t["drawn"], ["C"])

    def test_energy_gained_mid_turn_is_derived(self):
        log = fight()
        for e in log:
            if e["k"] == "side1" and e["a"].get("side") == "Player":
                e["a"]["energy"] = 5
        t = dt.derive({"v": 3, "log": log})["fights"][0]["turns"][0]
        self.assertEqual(t["e0"], 3)
        self.assertEqual(t["e1"], 5)
        self.assertEqual(t["spent"], 1)
        self.assertEqual(t["gained"], 3, "5 end + 1 spent - 3 start")


class Facts(unittest.TestCase):
    """Attacks, potions and snapshots: the facts that exist only during the fight."""

    def setUp(self):
        self.log = fight()

    def _with(self, *events):
        log = list(self.log)
        for e in events:
            log.insert(len(log) - 1, e)
        for i, e in enumerate(log, start=1):
            e["q"] = i
        return log

    def test_attacks_and_hits_are_counted_apart(self):
        # Kunai counts attacks, a per-hit relic counts hits. Damage events cannot
        # tell them apart, so the attack events must. The fixture has one attack
        # that landed one hit; add a three-hit attack on top.
        log = self._with(ev(20, "atk", by="P", src="CARD.X", side="Enemy", done=False, hits=0),
                         ev(21, "atk", by="P", src="CARD.X", side="Enemy", done=True, hits=3))
        t = dt.derive({"v": 3, "log": log})["fights"][0]["turns"][0]
        self.assertEqual(t["attacks"], 2)
        self.assertEqual(t["hits"], 4)

    def test_a_pet_is_not_an_enemy_and_its_damage_is_nobodys(self):
        # Osty soaking a hit, then dying to the same blow's overflow: the enemy's blow on
        # it is neither damage to the player nor damage the deck dealt, and its HP is
        # not enemy HP. Byrdpip is caught by the placeholder HP, not by name.
        snap = ev(3, "snap", why="fight0", round=1, creatures=[
            {"c": "P", "you": True, "hp": 80, "max": 80, "blk": 0, "pow": {}},
            {"c": "Osty", "you": False, "hp": 1, "max": 1, "blk": 0, "pow": {}},
            {"c": "Newpet", "you": False, "hp": 9999, "max": 9999, "blk": 0, "pow": {}},
            {"c": "E0", "you": False, "hp": 40, "max": 40, "blk": 0, "pow": {}}])
        log = self._with(
            snap,
            ev(20, "hp", c="Osty", d=-5, hp=0),
            ev(21, "hit", by="E0", t="Osty", total=5, blk=0, unb=5, ovk=3),
            ev(22, "hp", c="Newpet", d=-5, hp=9994),
            ev(23, "hit", by="E0", t="Newpet", total=5, blk=0, unb=5, ovk=0))
        f = dt.derive({"v": 3, "log": log})["fights"][0]
        base = dt.derive({"v": 3, "log": self.log})["fights"][0]
        self.assertEqual(f["pool"], 40)
        self.assertEqual(f["enemy_lost"], base["enemy_lost"])
        self.assertEqual(f["dmg_other"], base["dmg_other"])
        self.assertEqual(f["taken"], base["taken"])

    def test_enemy_attacks_are_not_the_players(self):
        log = self._with(ev(20, "atk", by="E0", src="MONSTER.X", side="Player", done=False, hits=0))
        t = dt.derive({"v": 3, "log": log})["fights"][0]["turns"][0]
        self.assertEqual(t["attacks"], 1, "only the fixture's own player attack")

    def test_a_potion_keeps_what_it_hit(self):
        log = self._with(ev(20, "potion", p="POTION.FIRE", t="E0"))
        t = dt.derive({"v": 3, "log": log})["fights"][0]["turns"][0]
        self.assertEqual(t["potions"], [{"p": "POTION.FIRE", "t": "E0"}])

    def test_snapshots_attach_to_the_turn_and_the_fight(self):
        snap_start = {"why": "turn0", "round": 1, "you": [{"en": 3}],
                      "creatures": [{"c": "P", "you": True, "hp": 80, "blk": 0, "pow": {}}]}
        snap_end = {"why": "side1", "round": 1, "you": [{"en": 2}], "creatures": []}
        log = self._with(ev(20, "snap", **snap_start), ev(21, "snap", **snap_end))
        f = dt.derive({"v": 3, "log": log})["fights"][0]
        self.assertEqual(len(f["snaps"]), 2)
        self.assertEqual(f["turns"][0]["snap0"]["why"], "turn0")
        self.assertEqual(f["turns"][0]["snap1"]["why"], "side1")

    def test_a_snapshot_that_disagrees_with_the_energy_event_is_caught(self):
        log = self._with(ev(20, "snap", why="side1", round=1, you=[{"en": 9}], creatures=[]))
        problems = dt.check(dt.derive({"v": 3, "log": log}))
        self.assertTrue(any("in the snapshot" in p for p in problems), problems)

    def test_a_turn_without_its_start_snapshot_is_caught(self):
        log = self._with(ev(20, "snap", why="side1", round=1, you=[{"en": 2}], creatures=[]))
        problems = dt.check(dt.derive({"v": 3, "log": log}))
        self.assertTrue(any("no turn-start snapshot" in p for p in problems), problems)


class Units(unittest.TestCase):
    """The units the projection and the measurement have to share."""

    def test_multi_target_damage_is_split_per_target(self):
        # The projection is per target. A Whirlwind turn that hits three enemies
        # dealt three times its per-target damage, and comparing the total against
        # a per-target projection over-reads the deck by 78% on a real run.
        log = fight()
        log.insert(15, ev(14.5, "hit", by="P", t="E1", total=9, blk=0, unb=9, ovk=0))
        log.insert(16, ev(14.6, "hit", by="P", t="E2", total=9, blk=0, unb=9, ovk=0))
        for i, e in enumerate(log, start=1):
            e["q"] = i
        t = dt.derive({"v": 3, "log": log})["fights"][0]["turns"][0]
        self.assertEqual(t["dmg"], 27, "9 to each of three targets")
        self.assertEqual(len(t["targets"]), 3)
        self.assertEqual(t["dmg_each"], 9)

    def test_energy_available_is_what_the_turn_had_to_spend(self):
        log = fight()
        for e in log:
            if e["k"] == "side1" and e["a"].get("side") == "Player":
                e["a"]["energy"] = 2
        t = dt.derive({"v": 3, "log": log})["fights"][0]["turns"][0]
        self.assertEqual(t["available"], 3, "2 left over + 1 spent")
        self.assertEqual(t["e0"], 3, "started with 3, so nothing was gained")

    def test_energy_available_is_absent_rather_than_zero_when_unknown(self):
        # A fight's last turn can end without the player's side-end event, and a
        # zero there drags the mean down: it read 2.7 against a true 4.1.
        log = [e for e in fight() if not (e["k"] == "side1" and e["a"].get("side") == "Player")]
        t = dt.derive({"v": 3, "log": log})["fights"][0]["turns"][0]
        self.assertIsNone(t["available"])
        self.assertIsNone(t["e1"])


class Debuffs(unittest.TestCase):
    """Debuffs on the enemy: half of what the damage line guesses at, and absent
    from the first version of the deriver entirely."""

    def test_enemy_power_changes_are_kept(self):
        log = fight()
        log.insert(15, ev(14.5, "pow", c="E0", p="POWER.VULNERABLE_POWER", n=2, d=2, by="P"))
        for i, e in enumerate(log, start=1):
            e["q"] = i
        t = dt.derive({"v": 3, "log": log})["fights"][0]["turns"][0]
        self.assertEqual(t["enemy_powers"], [{"c": "E0", "p": "POWER.VULNERABLE_POWER", "n": 2}])

    def test_uptime_comes_from_the_snapshot(self):
        # The id is POWER.VULNERABLE_POWER; looking for "POWER.VULNERABLE" found
        # nothing and made a deck that applied it 66 times look like it never did.
        snap = {"why": "turn0", "round": 1, "you": [{"en": 3}],
                "creatures": [{"c": "P", "you": True, "hp": 70, "blk": 0, "pow": {}},
                              {"c": "E0", "you": False, "hp": 40, "blk": 0,
                               "pow": {"POWER.VULNERABLE_POWER": 2}}]}
        log = fight()
        log.insert(9, ev(8.5, "snap", **snap))
        for i, e in enumerate(log, start=1):
            e["q"] = i
        t = dt.derive({"v": 3, "log": log})["fights"][0]["turns"][0]
        self.assertEqual(t["vuln"], 1, "one enemy carried it")

    def test_a_dead_enemy_does_not_count_towards_uptime(self):
        snap = {"why": "turn0", "round": 1, "you": [{"en": 3}],
                "creatures": [{"c": "E0", "you": False, "hp": 0, "blk": 0,
                               "pow": {"POWER.VULNERABLE_POWER": 2}}]}
        log = fight()
        log.insert(9, ev(8.5, "snap", **snap))
        for i, e in enumerate(log, start=1):
            e["q"] = i
        t = dt.derive({"v": 3, "log": log})["fights"][0]["turns"][0]
        self.assertEqual(t["vuln"], 0)


class Throughput(unittest.TestCase):
    """Cards played is the unit a deck is judged by, because a free play is energy
    the deck did not have to spend."""

    def test_list_price_counts_what_the_plays_would_have_cost(self):
        import telemetry_report as tr
        f = dt.derive({"v": 3, "log": fight()})["fights"][0]
        t = tr.throughput(f, {"A": 3, "B": 1})
        self.assertEqual(t["played"], 1)
        self.assertEqual(t["equiv"], 3, "one A at list price")

    def test_a_card_played_for_free_still_costs_at_list_price(self):
        # Cascade pulls a card off the draw pile straight into play: no energy
        # spent, but the deck got a card's worth of value.
        import telemetry_report as tr
        log = fight()
        log.insert(9, ev(8.5, "play1", card="Z"))
        for i, e in enumerate(log, start=1):
            e["q"] = i
        f = dt.derive({"v": 3, "log": log})["fights"][0]
        t = tr.throughput(f, {"A": 3, "Z": 2})
        self.assertEqual(t["played"], 2)
        self.assertEqual(t["spent"], 1, "the free card spent nothing")
        self.assertEqual(t["equiv"], 5, "but was worth 2 at list price")
        self.assertEqual(t["equiv"] - t["spent"], 4, "free plays are net energy")


    def test_uptime_is_measured_on_the_damage_not_the_turn_boundary(self):
        # Vulnerable applied during a turn boosts that turn's hits, so "was it up at
        # turn start" under-counts it badly. What matters is how much damage landed
        # at +50%.
        snap = {"why": "turn0", "round": 1, "you": [{"en": 3}],
                "creatures": [{"c": "P", "you": True, "hp": 70, "blk": 0, "pow": {}},
                              {"c": "E0", "you": False, "hp": 40, "blk": 0, "pow": {}}]}
        log = fight()
        hit = next(e for e in log if e["k"] == "hit" and e["a"].get("by") == "P")
        hit["a"]["t"] = "E0"
        log.insert(9, ev(8.5, "snap", **snap))
        log.insert(12, ev(11.5, "pow", c="E0", p="POWER.VULNERABLE_POWER", n=2, d=2, by="P"))
        for i, e in enumerate(log, start=1):
            e["q"] = i
        f = dt.derive({"v": 3, "log": log})["fights"][0]
        self.assertGreater(f["turns"][0]["vuln_dmg"], 0, "the hit landed while it was up")
        self.assertEqual(f["turns"][0]["vuln"], 0, "but it was not up at the turn's start")
        self.assertGreater(f["vuln_share"], 0)

    def test_damage_on_an_unvulnerable_target_does_not_count(self):
        log = fight()
        hit = next(e for e in log if e["k"] == "hit" and e["a"].get("by") == "P")
        hit["a"]["t"] = "E1"          # hit a target with no debuff
        log.insert(12, ev(11.5, "pow", c="E0", p="POWER.VULNERABLE_POWER", n=2, d=2, by="P"))
        for i, e in enumerate(log, start=1):
            e["q"] = i
        f = dt.derive({"v": 3, "log": log})["fights"][0]
        self.assertEqual(f["turns"][0]["vuln_dmg"], 0)
        self.assertEqual(f["vuln_share"], 0)


class Checks(unittest.TestCase):
    def test_a_clean_fight_passes(self):
        self.assertEqual(dt.check(dt.derive({"v": 3, "log": fight()})), [])

    def test_healing_after_the_fight_is_not_the_fights_damage(self):
        # Real case: a fight ended at 76 HP, then post-combat healing took it to 80.
        # Counting that heal made the fight look like it cost 0 instead of 4.
        log = fight(hp1=76)
        log.append(ev(60, "hp", c="P", d=4, hp=80))
        d = dt.derive({"v": 3, "log": log})
        self.assertEqual(d["fights"][0]["hp_out"], 0)
        self.assertEqual(dt.check(d), [])

    def test_a_victory_does_not_set_the_end_hp(self):
        # AfterCombatVictory fires before the fight is closed and before any
        # post-combat healing, so its HP is not what the fight ended on.
        log = fight(hp1=76)
        log.insert(-1, ev(50, "win", hp=76, round=1))
        log.append(ev(60, "win", hp=80, round=1))
        self.assertEqual(dt.derive({"v": 3, "log": log})["fights"][0]["hp1"], 76)

    def test_a_card_played_straight_from_the_draw_pile_is_not_a_gap(self):
        # Real case: Cascade plays the top card of the draw pile. It never enters
        # the hand and AfterCardDrawn never fires, so availability cannot be proven
        # from draws alone.
        log = fight()
        log.insert(8, ev(8.5, "pile", card="Z", **{"from": "Draw", "to": "Play"}))
        log.insert(9, ev(8.6, "play1", card="Z"))
        for i, e in enumerate(log, start=1):
            e["q"] = i
        problems = dt.check(dt.derive({"v": 3, "log": log}))
        self.assertFalse(any("never left the draw pile" in p for p in problems), problems)

    def test_a_stricter_hand_check_runs_once_pile_destinations_are_logged(self):
        log = fight()
        for e in log:
            if e["k"] == "pile":
                e["a"]["to"] = "Hand"
        log.insert(8, ev(8.5, "play1", card="Z"))
        for i, e in enumerate(log, start=1):
            e["q"] = i
        problems = dt.check(dt.derive({"v": 3, "log": log}))
        self.assertTrue(any("never left the draw pile" in p for p in problems), problems)

    def test_hp_that_disagrees_with_the_damage_events_is_caught(self):
        log = fight()
        for e in log:
            if e["k"] == "fight1":
                e["a"]["hp"] = 60  # claims 20 lost, the events say 9
        problems = dt.check(dt.derive({"v": 3, "log": log}))
        self.assertTrue(any("HP moved" in p for p in problems), problems)

    def test_damage_events_that_disagree_with_the_hp_drops_are_caught(self):
        log = fight()
        log.insert(-1, ev(25.5, "recv", t="P", by="E0", total=4, blk=0, unb=4, ovk=0,
                          broke=False, full=False, kill=False))
        for i, e in enumerate(log, start=1):
            e["q"] = i
        problems = dt.check(dt.derive({"v": 3, "log": log}))
        self.assertTrue(any("counted as damage taken" in p for p in problems), problems)

    def test_a_card_played_that_was_never_available_is_caught(self):
        log = fight()
        log.insert(16, ev(15.5, "play1", card="Z", up=0, auto=False))
        for i, e in enumerate(log, start=1):
            e["q"] = i
        problems = dt.check(dt.derive({"v": 3, "log": log}))
        self.assertTrue(any("never left the draw pile" in p for p in problems), problems)

    def test_turn_count_must_match_the_rounds(self):
        log = [e for e in fight() if e["k"] != "fight1"]
        log.append(ev(50, "fight1", hp=71, round=3))  # claims 3 rounds, saw 1
        problems = dt.check(dt.derive({"v": 3, "log": log}))
        self.assertTrue(any("against 3 rounds" in p for p in problems))

    def test_an_empty_log_is_not_an_error(self):
        d = dt.derive({"v": 3, "log": []})
        self.assertEqual(d["fights"], [])
        self.assertEqual(dt.check(d), [])


def snap(why, hand, energy=3, enemies=()):
    """A boundary snapshot, in the shape the mod writes it. Only the hand, the
    energy and the enemies are read here; the rest of the state is in the real ones.

    `enemies` is what stands in front of us: (id, hp, max) each.
    """
    creatures = [{"c": "P", "you": True, "hp": 70, "max": 70, "blk": 0, "pow": {}}]
    creatures += [{"c": cid, "you": False, "hp": hp, "max": mx, "blk": 0, "pow": {}}
                  for cid, hp, mx in enemies]
    return {"why": why, "round": 1, "creatures": creatures,
            "you": [{"en": energy, "st": 0, "gold": 0, "hand": list(hand), "draw": 5,
                     "disc": 0, "exh": 0, "orbs": [], "relics": [], "potions": []}]}


def killing_fight(enemies=(("E0", 10, 10),), blow=10, extra=(), hp1=70):
    """The smallest fight with an enemy in it: one card played, one enemy killed.

    `blow` is the HP the enemy loses to the killing hit, `extra` is any (kind, args)
    to insert before the fight closes -- self-damage, a sentinel HP delta, junk --
    and `hp1` is the player's HP when the fight ends.
    """
    log = [
        ev(1, "fight0", enc="ENCOUNTER.X", hp=70, round=1, deck=5),
        ev(2, "side0", side="Player", round=1, turn=1),
        ev(3, "erese", turn=1, energy=3, max=3),
        ev(4, "draw0", turn=1, energy=3, hand=0, max=10),
        ev(5, "pile", card="A", **{"from": "Draw", "to": "Hand"}),
        ev(6, "turn0", turn=1, energy=3, stars=0, round=1),
        ev(7, "snap", **snap("turn0", ["A"], enemies=enemies)),
        ev(8, "eps", n=1, card="A"),
        ev(9, "pile", card="A", **{"from": "Hand", "to": "Play"}),
        ev(10, "play1", card="A", up=0, auto=False),
        ev(11, "atk", by="P", src="A", side="Enemy", done=False, hits=0),
        ev(12, "hit", by="P", t="E0", total=blow, blk=0, unb=blow, ovk=0),
        ev(13, "hp", c="E0", d=-blow, hp=0),
    ]
    q = 13
    for kind, args in extra:
        q += 1
        log.append(ev(q, kind, **args))
    log += [
        ev(q + 1, "pile", card="A", **{"from": "Play", "to": "Discard"}),
        ev(q + 2, "side1", side="Player", energy=2, round=1),
        ev(q + 3, "snap", **snap("side1", [], energy=2, enemies=())),
        ev(q + 4, "win", hp=hp1, round=1),
        ev(q + 5, "fight1", hp=hp1, round=1),
    ]
    return log


class EnemyAccounting(unittest.TestCase):
    """What the enemies cost, read from their HP rather than from our hit events.

    This is the demand side of the whole measurement: if the damage the deck did
    cannot be tied to the HP the enemies actually had, nothing built on top of it
    is worth reading.
    """

    def test_the_killing_blow_counts_as_damage(self):
        # Regression: the killing blow was caught by an earlier "hp is now 0"
        # branch, so its delta never reached the total. Every won fight then looked
        # like it had removed about 10% less HP than the enemies had.
        f = dt.derive({"v": 3, "log": killing_fight()})["fights"][0]
        self.assertEqual(f["pool"], 10)
        self.assertEqual(f["enemy_lost"], 10)
        self.assertEqual(dt.check(dt.derive({"v": 3, "log": killing_fight()})), [])

    def test_a_won_fight_that_removed_less_than_the_pool_is_caught(self):
        log = killing_fight(blow=6)  # 10 HP enemy, 6 damage, then it dies anyway
        problems = dt.check(dt.derive({"v": 3, "log": log}))
        self.assertTrue(any("against a pool of 10" in p for p in problems), problems)

    def test_a_sentinel_hp_delta_is_not_damage(self):
        # Waterfall Giant logs a billion for its own reasons; it must not become a
        # fight's damage or its average.
        log = killing_fight(enemies=(("E0", 10, 10),), extra=[("hp", {"c": "E0", "d": -1_000_002_59, "hp": 0})])
        f = dt.derive({"v": 3, "log": log})["fights"][0]
        self.assertEqual(f["enemy_sentinel"], 1)
        self.assertEqual(f["enemy_lost"], 10)

    def test_enemies_that_appear_mid_fight_are_reported_as_spawned(self):
        # Axebots respawn and Ovicopter hatches: more HP removed than stood there.
        log = killing_fight(blow=10, extra=[("hp", {"c": "E0", "d": -15, "hp": 0})])
        d = dt.derive({"v": 3, "log": log})
        self.assertEqual(d["fights"][0]["spawned"], 15)
        self.assertEqual(dt.check(d), [])

    def test_a_boss_that_revives_is_reported_as_more_than_stood_there(self):
        # Test Subject: 100 HP on the first snapshot, then it heals back up to 200 and
        # 300. Net of the healing that reads as 100 removed in a 600 HP fight.
        log = killing_fight(blow=10, extra=[("hp", {"c": "E0", "d": 20, "hp": 20}),
                                            ("hp", {"c": "E0", "d": -20, "hp": 0})])
        f = dt.derive({"v": 3, "log": log})["fights"][0]
        self.assertEqual((f["enemy_lost"], f["enemy_net"]), (30, 10))
        self.assertEqual(f["spawned"], 20)

    def test_a_move_id_two_monsters_share_reads_as_the_one_in_this_fight(self):
        # BITE_MOVE is 5 on a Phantasmal Gardener and 13 on a Tunneler. Keyed on the id
        # alone, a Gardener fight read at Tunneler damage.
        moves = {"BITE_MOVE": (((13, 1),), 9.0),
                 ("ENCOUNTER.GARDENERS", "BITE_MOVE"): (((5, 1),), 3.8)}
        state = snap("turn0", [], enemies=(("first", 10, 10),))
        state["creatures"][1]["move"] = "BITE_MOVE"
        log = [ev(1, "fight0", enc="ENCOUNTER.GARDENERS", hp=70, round=1, deck=10),
               ev(2, "side0", side="Player", round=1, turn=1),
               ev(3, "snap", **state),
               ev(4, "fight1", hp=70, round=1)]
        t = dt.derive({"v": 3, "log": log}, moves)["fights"][0]["turns"][0]
        self.assertEqual((t["intent"], t["expected"]), (5, 3.8))

    def test_two_monsters_sharing_a_move_in_one_fight_read_by_their_max_hp(self):
        # Flail Knight's Ram is 15 and Magi Knight's 10, and the log calls them "first"
        # and "third".
        moves = {("ENCOUNTER.KNIGHTS", "RAM_MOVE"): (((15, 1),), 11.0),
                 ("ENCOUNTER.KNIGHTS", "RAM_MOVE", 101): (((15, 1),), 11.0),
                 ("ENCOUNTER.KNIGHTS", "RAM_MOVE", 82): (((10, 1),), 10.0)}
        state = snap("turn0", [], enemies=(("first", 90, 101), ("third", 70, 82)))
        state["creatures"][1]["move"] = state["creatures"][2]["move"] = "RAM_MOVE"
        log = [ev(1, "fight0", enc="ENCOUNTER.KNIGHTS", hp=70, round=1, deck=10),
               ev(2, "side0", side="Player", round=1, turn=1),
               ev(3, "snap", **state),
               ev(4, "fight1", hp=70, round=1)]
        t = dt.derive({"v": 3, "log": log}, moves)["fights"][0]["turns"][0]
        self.assertEqual((t["intent"], t["expected"]), (25, 21.0))

    def test_a_move_outside_the_encounters_list_still_reads(self):
        # A summoned monster is not in the encounter's list, and its move is still a
        # move: the plain id is the fallback, not silence.
        moves = {"BITE_MOVE": (((13, 1),), 9.0)}
        state = snap("turn0", [], enemies=(("egg3", 10, 10),))
        state["creatures"][1]["move"] = "BITE_MOVE"
        log = [ev(1, "fight0", enc="ENCOUNTER.GARDENERS", hp=70, round=1, deck=10),
               ev(2, "side0", side="Player", round=1, turn=1),
               ev(3, "snap", **state),
               ev(4, "fight1", hp=70, round=1)]
        t = dt.derive({"v": 3, "log": log}, moves)["fights"][0]["turns"][0]
        self.assertEqual(t["intent"], 13)

    def test_self_damage_is_a_fact_not_a_contradiction(self):
        # Bloodletting and Offering pay HP. The deck taking its own HP is not the
        # log disagreeing with itself, and an Ironclad run must not read as broken.
        log = killing_fight(extra=[("hp", {"c": "P", "d": -3, "hp": 67})], hp1=67)
        d = dt.derive({"v": 3, "log": log})
        self.assertEqual(d["fights"][0]["self_dmg"], 3)
        self.assertEqual(dt.check(d), [])

    def test_damage_that_had_no_attacker_is_counted_but_apart(self):
        # Poison and other damage over time log with an empty attacker. It is damage
        # the deck caused; it is not one of our attacks.
        log = killing_fight(extra=[("hit", {"by": "", "t": "E0", "total": 4, "blk": 0, "unb": 4, "ovk": 0})])
        f = dt.derive({"v": 3, "log": log})["fights"][0]
        self.assertEqual(f["dmg_other"], 4)
        self.assertEqual(f["dmg_hit"], 10)

    def test_junk_is_counted_apart_from_the_deck(self):
        # A status the enemy slips into the hand is a draw you did not get. Only
        # read when card_data.json is available; then a real status counts and a
        # real card does not.
        if not dt.JUNK:
            self.skipTest("card_data.json not present, junk cannot be classified")
        status = sorted(dt.JUNK)[0]
        log = killing_fight(extra=[("enter", {"card": status}), ("enter", {"card": "CARD.STRIKE"})])
        f = dt.derive({"v": 3, "log": log})["fights"][0]
        self.assertEqual(f["junk"], 1)

    def test_hp_taken_off_with_no_hit_behind_it_is_its_own_bucket(self):
        # Living Fog's bomb dies with the Fog: it loses its last HP with nothing
        # attacking it. Measuring that as damage the deck dealt would credit a deck
        # for something it never hit with.
        log = killing_fight(extra=[("hp", {"c": "E0", "d": -4, "hp": 0})])
        f = dt.derive({"v": 3, "log": log})["fights"][0]
        self.assertEqual(f["enemy_lost"], 14)
        self.assertEqual(f["dealt_removed"], 10)
        self.assertEqual(f["enemy_unexplained"], 4)

    def test_overkill_is_already_out_of_the_hp_a_hit_took(self):
        # A 15 on an enemy with 10 HP left: `unb` is the 10 it lost, with 5 overkill.
        # Taking the overkill off again read as 5 HP gone with no hit behind it.
        log = killing_fight(extra=[("hp", {"c": "E0", "d": -6, "hp": 0}),
                                   ("hit", {"by": "P", "t": "E0", "total": 11, "blk": 0,
                                            "unb": 6, "ovk": 5})])
        f = dt.derive({"v": 3, "log": log})["fights"][0]
        self.assertEqual(f["dmg_hit"], 16)
        self.assertEqual(f["enemy_unexplained"], 0)

    def test_overkill_is_left_in_for_damage_with_no_attacker_too(self):
        log = killing_fight(extra=[("hp", {"c": "E0", "d": -2, "hp": 0}),
                                   ("hit", {"by": "", "t": "E0", "total": 5, "blk": 0,
                                            "unb": 2, "ovk": 3})])
        f = dt.derive({"v": 3, "log": log})["fights"][0]
        self.assertEqual(f["dmg_other"], 2)
        self.assertEqual(f["enemy_unexplained"], 0)

    def test_a_heal_cannot_hide_hp_gone_with_no_hit(self):
        # Knowledge Demon heals: read off the net, the heal would cancel the gap.
        log = killing_fight(extra=[("hp", {"c": "E0", "d": 4, "hp": 4}),
                                   ("hp", {"c": "E0", "d": -4, "hp": 0})])
        f = dt.derive({"v": 3, "log": log})["fights"][0]
        self.assertEqual(f["enemy_unexplained"], 4)

    def test_vulnerable_on_you_lifts_what_was_aimed_but_weak_on_them_does_not(self):
        moves = {"BITE_MOVE": (((7, 2),), 3.0)}
        def aimed(you, them):
            state = snap("turn0", [], enemies=(("first", 10, 10),))
            state["creatures"][0]["pow"] = you
            state["creatures"][1].update(move="BITE_MOVE", pow=them)
            log = [ev(1, "fight0", enc="ENCOUNTER.X", hp=70, round=1, deck=10),
                   ev(2, "side0", side="Player", round=1, turn=1),
                   ev(3, "snap", **state),
                   ev(4, "fight1", hp=70, round=1)]
            return dt.derive({"v": 3, "log": log}, moves)["fights"][0]["turns"][0]["intent"]
        self.assertEqual(aimed({}, {}), 14)
        self.assertEqual(aimed({"POWER.VULNERABLE_POWER": 2}, {}), 20)  # 7 lands as 10, twice
        self.assertEqual(aimed({}, {"POWER.WEAK_POWER": 1}), 14)

    def test_the_giants_explosion_is_what_it_had_built_the_turn_before(self):
        # It builds a number every turn and deals it the turn after it dies. The move
        # list has no number for that, and the power is gone by the turn it lands.
        def turn(q, n, move, built):
            state = snap("turn0", [], enemies=(("giant", 10, 10),))
            state["creatures"][1].update(move=move, pow={dt.ERUPTION: built} if built else {})
            return [ev(q, "side0", side="Player", round=n, turn=n), ev(q + 1, "snap", **state)]
        log = [ev(1, "fight0", enc="ENCOUNTER.GIANT", hp=70, round=1, deck=10),
               *turn(2, 1, "STOMP_MOVE", 15), *turn(4, 2, "STOMP_MOVE", 18),
               *turn(6, 3, dt.EXPLODE, 0), ev(8, "fight1", hp=70, round=3)]
        moves = {"STOMP_MOVE": (((5, 1),), 5.0)}
        turns = dt.derive({"v": 3, "log": log}, moves)["fights"][0]["turns"]
        self.assertEqual([t["intent"] for t in turns], [5, 5, 18])

    def test_a_monster_that_never_built_anything_keeps_its_listed_explosion(self):
        # Living Fog's bomb has the same move id, and its number in the move list.
        state = snap("turn0", [], enemies=(("bomb1", 4, 4),))
        state["creatures"][1]["move"] = dt.EXPLODE
        log = [ev(1, "fight0", enc="ENCOUNTER.LIVING_FOG_NORMAL", hp=70, round=1, deck=10),
               ev(2, "side0", side="Player", round=1, turn=1),
               ev(3, "snap", **state),
               ev(4, "fight1", hp=70, round=1)]
        moves = {("ENCOUNTER.LIVING_FOG_NORMAL", dt.EXPLODE): (((8, 1),), 8.0)}
        self.assertEqual(dt.derive({"v": 3, "log": log}, moves)["fights"][0]["turns"][0]["intent"], 8)

    def test_one_fights_explosion_does_not_carry_into_the_next(self):
        state = snap("turn0", [], enemies=(("giant", 10, 10),))
        state["creatures"][1]["move"] = dt.EXPLODE
        built = snap("turn0", [], enemies=(("giant", 10, 10),))
        built["creatures"][1].update(move="STOMP_MOVE", pow={dt.ERUPTION: 30})
        log = [ev(1, "fight0", enc="ENCOUNTER.GIANT", hp=70, round=1, deck=10),
               ev(2, "side0", side="Player", round=1, turn=1), ev(3, "snap", **built),
               ev(4, "fight1", hp=70, round=1),
               ev(5, "fight0", enc="ENCOUNTER.GIANT", hp=70, round=1, deck=10),
               ev(6, "side0", side="Player", round=1, turn=1), ev(7, "snap", **state),
               ev(8, "fight1", hp=70, round=1)]
        fights = dt.derive({"v": 3, "log": log}, {})["fights"]
        self.assertEqual(fights[1]["turns"][0]["intent"], 0)

    def aimed_after(self, *during, move="BITE_MOVE", hits=((10, 2),), strength=None):
        """What one turn aims, with `during` happening between its opening state and
        the enemies' side. Two hits of 10 on one enemy unless told otherwise."""
        state = snap("turn0", [], enemies=(("first", 10, 10),))
        state["creatures"][1].update(move=move, pow=strength or {})
        log = [ev(1, "fight0", enc="ENCOUNTER.X", hp=70, round=1, deck=10),
               ev(2, "side0", side="Player", round=1, turn=1),
               ev(3, "snap", **state),
               *[ev(4 + i, *e[:1], **e[1]) for i, e in enumerate(during)],
               ev(50, "side0", side="Enemy", round=1, turn=1),
               ev(51, "fight1", hp=70, round=1)]
        return dt.derive({"v": 3, "log": log}, {move: (hits, 3.0)})["fights"][0]["turns"][0]["intent"]

    def test_strength_gained_on_your_turn_lifts_what_was_aimed(self):
        # Brimstone gives every enemy 1 as your turn starts, just after the opening
        # state; Enrage gives Test Subject 2 for each Skill. Both land before it swings.
        gained = ("pow", dict(c="first", p=dt.STRENGTH, d=1, n=1))
        self.assertEqual(self.aimed_after(gained), 22)

    def test_strength_your_deck_took_off_does_not_lower_what_was_aimed(self):
        # Like Weak, that's damage the deck stopped, and the gap should show it.
        cut = ("pow", dict(c="first", p=dt.STRENGTH, d=-15, n=-15, by="P"))
        self.assertEqual(self.aimed_after(cut), 20)

    def test_strength_given_back_after_they_swing_lifts_nothing(self):
        state = snap("turn0", [], enemies=(("first", 10, 10),))
        state["creatures"][1]["move"] = "BITE_MOVE"
        log = [ev(1, "fight0", enc="ENCOUNTER.X", hp=70, round=1, deck=10),
               ev(2, "side0", side="Player", round=1, turn=1),
               ev(3, "snap", **state),
               ev(4, "side0", side="Enemy", round=1, turn=1),
               ev(5, "pow", c="first", p=dt.STRENGTH, d=15, n=0),
               ev(6, "fight1", hp=70, round=1)]
        moves = {"BITE_MOVE": (((10, 2),), 3.0)}
        self.assertEqual(dt.derive({"v": 3, "log": log}, moves)["fights"][0]["turns"][0]["intent"], 20)

    def test_strength_on_one_enemy_lifts_only_that_enemy(self):
        gained = ("pow", dict(c="someone else", p=dt.STRENGTH, d=5, n=5))
        self.assertEqual(self.aimed_after(gained), 20)

    def test_tainted_adds_to_every_hit(self):
        # Two Skills at 2 each: 4 on each of the two hits.
        played = [("pow", dict(c="P", p=dt.TAINTED, d=2, n=2)), ("pow", dict(c="P", p=dt.TAINTED, d=2, n=4))]
        self.assertEqual(self.aimed_after(*played), 28)

    def test_tainted_comes_before_vulnerable(self):
        # (5 + 2) x 1.5 is 10, where 5 x 1.5 + 2 would be 9.
        state = snap("turn0", [], enemies=(("first", 10, 10),))
        state["creatures"][0]["pow"] = {"POWER.VULNERABLE_POWER": 1}
        state["creatures"][1]["move"] = "BITE_MOVE"
        log = [ev(1, "fight0", enc="ENCOUNTER.X", hp=70, round=1, deck=10),
               ev(2, "side0", side="Player", round=1, turn=1),
               ev(3, "snap", **state),
               ev(4, "pow", c="P", p=dt.TAINTED, d=2, n=2),
               ev(5, "fight1", hp=70, round=1)]
        moves = {"BITE_MOVE": (((5, 1),), 3.0)}
        self.assertEqual(dt.derive({"v": 3, "log": log}, moves)["fights"][0]["turns"][0]["intent"], 10)

    def test_tainted_does_not_last_into_the_next_turn(self):
        state = snap("turn0", [], enemies=(("first", 10, 10),))
        state["creatures"][1]["move"] = "BITE_MOVE"
        log = [ev(1, "fight0", enc="ENCOUNTER.X", hp=70, round=1, deck=10),
               ev(2, "side0", side="Player", round=1, turn=1), ev(3, "snap", **state),
               ev(4, "pow", c="P", p=dt.TAINTED, d=2, n=2),
               ev(5, "side0", side="Player", round=2, turn=2), ev(6, "snap", **state),
               ev(7, "fight1", hp=70, round=2)]
        moves = {"BITE_MOVE": (((10, 1),), 3.0)}
        turns = dt.derive({"v": 3, "log": log}, moves)["fights"][0]["turns"]
        self.assertEqual([t["intent"] for t in turns], [12, 10])

    def growing(self, first, second, stopped=False):
        """Two turns of move `first` then `second`, the first of them landing a hit
        unless a stun or a kill stopped it."""
        def state(move):
            s = snap("turn0", [], enemies=(("first", 10, 10),))
            s["creatures"][1]["move"] = move
            return s
        hit = [] if stopped else [ev(6, "hit", by="first", t="P", total=10, blk=0, unb=10, ovk=0)]
        log = [ev(1, "fight0", enc="ENCOUNTER.X", hp=70, round=1, deck=10),
               ev(2, "side0", side="Player", round=1, turn=1), ev(3, "snap", **state(first)),
               ev(5, "side0", side="Enemy", round=1, turn=1), *hit,
               ev(7, "side0", side="Player", round=2, turn=2), ev(8, "snap", **state(second)),
               ev(9, "fight1", hp=70, round=2)]
        moves = {"PRESSURE_GUN_MOVE": (((20, 1),), 3.0), "MULTI_CLAW_MOVE": (((10, 3),), 3.0),
                 "BITE_MOVE": (((10, 3),), 3.0)}
        return [t["intent"] for t in dt.derive({"v": 3, "log": log}, moves)["fights"][0]["turns"]]

    def test_pressure_gun_adds_five_each_time_it_fires(self):
        self.assertEqual(self.growing("PRESSURE_GUN_MOVE", "PRESSURE_GUN_MOVE"), [20, 25])

    def test_multi_claw_adds_a_hit_each_time_it_lands(self):
        self.assertEqual(self.growing("MULTI_CLAW_MOVE", "MULTI_CLAW_MOVE"), [30, 40])

    def test_a_move_that_never_landed_has_not_grown(self):
        self.assertEqual(self.growing("MULTI_CLAW_MOVE", "MULTI_CLAW_MOVE", stopped=True), [30, 30])

    def test_a_move_outside_the_list_does_not_grow(self):
        self.assertEqual(self.growing("BITE_MOVE", "BITE_MOVE"), [30, 30])

    def test_one_fights_growth_does_not_carry_into_the_next(self):
        def state():
            s = snap("turn0", [], enemies=(("first", 10, 10),))
            s["creatures"][1]["move"] = "PRESSURE_GUN_MOVE"
            return s
        log = [ev(1, "fight0", enc="ENCOUNTER.X", hp=70, round=1, deck=10),
               ev(2, "side0", side="Player", round=1, turn=1), ev(3, "snap", **state()),
               ev(4, "side0", side="Enemy", round=1, turn=1),
               ev(5, "hit", by="first", t="P", total=20, blk=0, unb=20, ovk=0),
               ev(6, "fight1", hp=50, round=1),
               ev(7, "fight0", enc="ENCOUNTER.X", hp=70, round=1, deck=10),
               ev(8, "side0", side="Player", round=1, turn=1), ev(9, "snap", **state()),
               ev(10, "fight1", hp=70, round=1)]
        fights = dt.derive({"v": 3, "log": log}, {"PRESSURE_GUN_MOVE": (((20, 1),), 3.0)})["fights"]
        self.assertEqual(fights[1]["turns"][0]["intent"], 20)

    def test_the_enemies_side_opening_is_recorded_on_the_turn(self):
        f = dt.derive({"v": 3, "log": fight()})["fights"][0]
        self.assertTrue(f["turns"][0]["enemy_side"])
        won_on_your_turn = [e for e in fight() if e["q"] < 18] + [ev(19, "fight1", hp=71, round=1)]
        f = dt.derive({"v": 3, "log": won_on_your_turn})["fights"][0]
        self.assertFalse(f["turns"][0]["enemy_side"])


def two_turns(held_in_hand=(), generated=(), retained_in_snapshot=()):
    """Two turns of a Silent fight, with the hand stated at both boundaries.

    Turn 1 draws and plays one card; `held_in_hand` cards are drawn and kept.
    `generated` arrive mid-turn, after the opening snapshot, as a Shiv does.
    `retained_in_snapshot` is what the game says is still in hand at the turn's
    end -- a Retain card is never re-drawn, so turn 2 opens with it.
    """
    log = [
        ev(1, "fight0", enc="ENCOUNTER.X", hp=70, round=1, deck=12),
        ev(2, "side0", side="Player", round=1, turn=1),
        ev(3, "erese", turn=1, energy=3, max=3),
        ev(4, "draw0", turn=1, energy=3, hand=0, max=10),
        ev(5, "pile", card="A", **{"from": "Draw", "to": "Hand"}),
        ev(6, "draw1", card="A", hand=True),
    ]
    q = 6
    for card in held_in_hand:
        q += 1
        log.append(ev(q, "pile", card=card, **{"from": "Draw", "to": "Hand"}))
        q += 1
        log.append(ev(q, "draw1", card=card, hand=True))
    q += 1
    log.append(ev(q, "turn0", turn=1, energy=3, stars=0, round=1))
    q += 1
    log.append(ev(q, "snap", **snap("turn0", ["A", *held_in_hand])))
    q += 1
    log.append(ev(q, "eps", n=1, card="A"))
    q += 1
    log.append(ev(q, "pile", card="A", **{"from": "Hand", "to": "Play"}))
    q += 1
    log.append(ev(q, "play1", card="A", up=0, auto=False))
    q += 1
    log.append(ev(q, "pile", card="A", **{"from": "Play", "to": "Discard"}))
    for card in generated:
        q += 1
        log.append(ev(q, "pile", card=card, **{"from": "None", "to": "Hand"}))
        q += 1
        log.append(ev(q, "gen", card=card))
        q += 1
        log.append(ev(q, "pile", card=card, **{"from": "Hand", "to": "Play"}))
        q += 1
        log.append(ev(q, "play1", card=card, up=0, auto=True))
        q += 1
        log.append(ev(q, "pile", card=card, **{"from": "Play", "to": "Exhaust"}))
    hand_at_end = list(retained_in_snapshot) or list(held_in_hand)
    q += 1
    log.append(ev(q, "side1", side="Player", energy=2, round=1))
    q += 1
    log.append(ev(q, "snap", **snap("side1", hand_at_end, energy=2)))
    q += 1
    log.append(ev(q, "side0", side="Enemy", round=1, turn=1))
    q += 1
    log.append(ev(q, "side1", side="Enemy", energy=2, round=1))
    q += 1
    log.append(ev(q, "side0", side="Player", round=2, turn=2))
    q += 1
    log.append(ev(q, "erese", turn=2, energy=3, max=3))
    q += 1
    log.append(ev(q, "draw0", turn=2, energy=3, hand=len(hand_at_end), max=10))
    q += 1
    log.append(ev(q, "pile", card="B", **{"from": "Draw", "to": "Hand"}))
    q += 1
    log.append(ev(q, "draw1", card="B", hand=True))
    q += 1
    log.append(ev(q, "turn0", turn=2, energy=3, stars=0, round=2))
    q += 1
    log.append(ev(q, "snap", **snap("turn0", ["B", *hand_at_end])))
    q += 1
    log.append(ev(q, "eps", n=1, card="B"))
    q += 1
    log.append(ev(q, "pile", card="B", **{"from": "Hand", "to": "Play"}))
    q += 1
    log.append(ev(q, "play1", card="B", up=0, auto=True))
    q += 1
    log.append(ev(q, "pile", card="B", **{"from": "Play", "to": "Discard"}))
    q += 1
    log.append(ev(q, "side1", side="Player", energy=2, round=2))
    q += 1
    log.append(ev(q, "snap", **snap("side1", hand_at_end, energy=2)))
    q += 1
    log.append(ev(q, "fight1", hp=70, round=2))
    return log


class HandAcrossTurns(unittest.TestCase):
    """The hand check has to survive a turn boundary, and it did not.

    Real case, run 1793569704 (Silent): 92 of 220 turns were reported as
    contradictions. None of them were. Two things the check had wrong: a card
    generated mid-turn (a Shiv from Up My Sleeve) was compared against a snapshot
    taken before it existed, and a Retain card carried into the next turn was
    never drawn again, so it looked like it had arrived from nowhere.
    """

    def test_a_retained_card_is_in_hand_without_being_drawn_again(self):
        log = two_turns(held_in_hand=["R"], retained_in_snapshot=["R"])
        d = dt.derive({"v": 3, "log": log})
        self.assertEqual(dt.check(d), [])
        self.assertEqual(d["fights"][0]["turns"][1]["hand_at_open"], ["R", "B"])

    def test_a_card_generated_mid_turn_is_not_part_of_the_opening_hand(self):
        log = two_turns(held_in_hand=["R"], generated=["SHIV"], retained_in_snapshot=["R"])
        d = dt.derive({"v": 3, "log": log})
        self.assertEqual(dt.check(d), [])
        turns = d["fights"][0]["turns"]
        self.assertEqual(turns[0]["hand_at_open"], ["A", "R"])
        self.assertEqual(turns[0]["hand_at_end"], ["R"])
        self.assertEqual(turns[0]["hand_by_pile"], ["A", "R", "SHIV"])

    def test_a_hand_that_disagrees_at_the_turn_end_is_caught(self):
        # The check still bites: claim a card at the end that never came back.
        log = two_turns(held_in_hand=["R"], retained_in_snapshot=["R", "GHOST"])
        problems = dt.check(dt.derive({"v": 3, "log": log}))
        self.assertTrue(any("hand ends" in p and "GHOST" in p for p in problems), problems)

    def test_a_hand_that_disagrees_at_the_turn_start_is_caught(self):
        log = two_turns(held_in_hand=["R"], retained_in_snapshot=["R"])
        for e in log:
            if e["k"] == "snap" and e["a"]["why"] == "turn0" and "B" in e["a"]["you"][0]["hand"]:
                e["a"]["you"][0]["hand"].remove("R")  # the game says R is not there
        problems = dt.check(dt.derive({"v": 3, "log": log}))
        self.assertTrue(any("hand opens" in p for p in problems), problems)


class RoundTrip(unittest.TestCase):
    def test_a_summary_from_the_old_mod_is_refused_by_the_cli(self):
        old = {"v": 2, "fights": [{"enc": "E", "hp0": 1, "hp1": 1, "turns": []}]}
        self.assertNotIn("log", old)

    def test_json_shape_matches_what_the_mod_writes(self):
        # EventLog.Take() emits {"v":3,"log":[{"q","f","t","k","a"}],"truncated":bool}
        log = json.loads(json.dumps({"v": 3, "log": fight(), "truncated": False}))
        d = dt.derive(log)
        self.assertFalse(d["truncated"])
        self.assertEqual(d["v"], 3)


class Joining(unittest.TestCase):
    """Pairing the log's fights with the run file's combat nodes."""

    def test_fights_are_paired_by_encounter_not_by_position(self):
        import telemetry_report as tr
        fights = [{"enc": "ENCOUNTER.A"}, {"enc": "ENCOUNTER.B"}]
        timeline = [{"enc": "EVENT.X", "turns": 0}, {"enc": "ENCOUNTER.A", "turns": 3},
                    {"enc": "EVENT.Y", "turns": 0}, {"enc": "ENCOUNTER.B", "turns": 2}]
        self.assertEqual([n["enc"] for _, n in tr.align(fights, timeline)],
                         ["ENCOUNTER.A", "ENCOUNTER.B"])

    def test_an_event_fight_pairs_by_the_fight_not_the_event(self):
        # Real case: ENCOUNTER.MYSTERIOUS_KNIGHT_EVENT_ENCOUNTER sits in a second room
        # behind EVENT.THE_LANTERN_KEY, and the node's enc is the event.
        import telemetry_report as tr
        fights = [{"enc": "ENCOUNTER.A"}, {"enc": "ENCOUNTER.EVENTY"}]
        timeline = [{"enc": "ENCOUNTER.A", "turns": 3},
                    {"enc": "EVENT.Y", "fight": "ENCOUNTER.EVENTY", "turns": 2}]
        self.assertEqual([n["enc"] for _, n in tr.align(fights, timeline)],
                         ["ENCOUNTER.A", "EVENT.Y"])

    def test_a_fight_only_one_side_has_is_skipped_not_fatal(self):
        # A positional join would lose every fight after the gap.
        import telemetry_report as tr
        fights = [{"enc": "ENCOUNTER.A"}, {"enc": "ENCOUNTER.EVENTY"}, {"enc": "ENCOUNTER.B"}]
        timeline = [{"enc": "ENCOUNTER.A", "turns": 3}, {"enc": "ENCOUNTER.B", "turns": 2}]
        self.assertEqual([n["enc"] for _, n in tr.align(fights, timeline)],
                         ["ENCOUNTER.A", "ENCOUNTER.B"])

    def test_a_combat_the_log_missed_is_skipped_too(self):
        import telemetry_report as tr
        fights = [{"enc": "ENCOUNTER.A"}, {"enc": "ENCOUNTER.C"}]
        timeline = [{"enc": "ENCOUNTER.A", "turns": 3}, {"enc": "ENCOUNTER.B", "turns": 1},
                    {"enc": "ENCOUNTER.C", "turns": 2}]
        self.assertEqual([n["enc"] for _, n in tr.align(fights, timeline)],
                         ["ENCOUNTER.A", "ENCOUNTER.C"])


if __name__ == "__main__":
    unittest.main()
