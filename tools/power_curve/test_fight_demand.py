"""What winning took on an encounter, and how each fight reads against it.

The monsters and their moves are made up here, so nothing depends on the numbers in
the game data. Each case is something the real data does: pets listed beside the
enemies, a boss with no HP in the data, an encounter the data does not have.
"""
import gzip
import json
import statistics
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import fight_demand as fd  # noqa: E402

MONSTERS = {
    "MONSTER.A": {"hpMin": [40, 44], "hpMax": [44, 48]},
    "MONSTER.B": {"hpMin": [100, 110], "hpMax": [100, 110]},
}


def fight(enc="ENCOUNTER.X", ids=("MONSTER.A",), t=3, taken=0, asc=0, died=False, share=None, act=0, build=fd.SPAWNS_LISTED):
    return {"enc": enc, "ids": list(ids), "t": t, "taken": taken, "each": [taken], "asc": asc, "kind": "monster",
            "act": act, "died": died, "coop": share is not None, "share": share or 1, "build": build}


def demand_of(runs, logged=None):
    with mock.patch.object(fd.pc, "PD", {"monsters": MONSTERS}):
        return fd.table(runs, logged)


def line_of(runs, level=0):
    return demand_of(runs)["ENCOUNTER.X"]["tiers"][level]


def every_tier(line):
    return [line] * fd.TIERS


def room(ids, turns=3):
    return {"model_id": "ENCOUNTER.X", "monster_ids": ids, "turns_taken": turns}


def run(rooms, players=1, abandoned=False, win=True, taken=(5,), healed=None):
    stats = [{"damage_taken": d, "hp_healed": h} for d, h in zip(taken, healed or [0] * len(taken))]
    return {"players": [{"character": "CHARACTER.X"}] * players, "was_abandoned": abandoned, "win": win,
            "ascension": 0, "map_point_history": [[{
                "map_point_type": "monster", "player_stats": stats, "rooms": [r],
            } for r in rooms]]}


class BodyPool(unittest.TestCase):
    def pool(self, monster):
        with mock.patch.object(fd.pc, "PD", {"monsters": MONSTERS}):
            return fd.body_pool(monster)

    def test_takes_the_middle_of_the_range_at_each_difficulty(self):
        self.assertEqual(self.pool("MONSTER.A"), (42, 46))

    def test_a_boss_with_no_hp_in_the_data_uses_its_phases(self):
        self.assertEqual(self.pool("MONSTER.TEST_SUBJECT"), (600, 636))

    def test_a_monster_the_data_does_not_have_is_zero_not_an_error(self):
        self.assertEqual(self.pool("MONSTER.DOORMAKER"), (0, 0))


class HpShare(unittest.TestCase):
    def test_follows_the_games_steps(self):
        self.assertEqual(fd.hp_share(0, "boss"), 1.1)
        self.assertEqual(fd.hp_share(1, "boss"), 1.2)
        self.assertEqual(fd.hp_share(2, "elite"), 1.2)
        self.assertEqual(fd.hp_share(2, "boss"), 1.3)


class RunFights(unittest.TestCase):
    def test_pets_are_not_enemies(self):
        fights = fd.run_fights({"a": run([room(["MONSTER.OSTY", "MONSTER.A", "MONSTER.BYRDPIP"])])})
        self.assertEqual(fights[0][0]["ids"], ["MONSTER.A"])

    def test_abandoned_runs_are_left_out(self):
        self.assertEqual(fd.run_fights({"a": run([room(["MONSTER.A"])], abandoned=True)}), [])

    def test_solo_is_the_whole_enemy(self):
        got = fd.run_fights({"a": run([room(["MONSTER.A"])])})[0][0]
        self.assertFalse(got["coop"])
        self.assertEqual(got["share"], 1)

    def test_co_op_takes_a_players_share_and_the_partys_mean(self):
        got = fd.run_fights({"a": run([room(["MONSTER.A"])], players=2, taken=(4, 10))})[0][0]
        self.assertTrue(got["coop"])
        self.assertEqual(got["share"], 1.1)
        self.assertEqual(got["taken"], 7)

    def test_what_the_floor_healed_comes_off_its_damage_taken(self):
        got = fd.run_fights({"a": run([room(["MONSTER.A"])], taken=(10,), healed=(4,))})[0][0]
        self.assertEqual((got["taken"], got["each"]), (6, [6]))

    def test_spare_healing_stops_at_zero(self):
        got = fd.run_fights({"a": run([room(["MONSTER.A"])], taken=(3,), healed=(6,))})[0][0]
        self.assertEqual(got["taken"], 0)

    def test_each_player_of_a_party_heals_their_own_damage(self):
        # Together they took 14 and healed 7, but one player's spare healing can't cover
        # the other's damage.
        got = fd.run_fights({"a": run([room(["MONSTER.A"])], players=2, taken=(4, 10), healed=(6, 1))})[0][0]
        self.assertEqual((got["taken"], got["each"]), (4.5, [0, 9]))

    def test_a_floor_with_no_healing_recorded_is_its_damage_taken(self):
        self.assertEqual(fd.net_taken({"damage_taken": 7}), 7)
        self.assertEqual(fd.net_taken({}), 0)

    def test_a_loss_marks_only_the_last_fight(self):
        fights = fd.run_fights({"a": run([room(["MONSTER.A"]), room(["MONSTER.B"])], win=False)})[0]
        self.assertEqual([f["died"] for f in fights], [False, True])

    def test_a_win_marks_nothing(self):
        fights = fd.run_fights({"a": run([room(["MONSTER.A"])])})[0]
        self.assertFalse(fights[0]["died"])


class Table(unittest.TestCase):
    def test_pool_sums_every_body_at_each_difficulty(self):
        d = demand_of([[fight(ids=("MONSTER.A", "MONSTER.B"))]])["ENCOUNTER.X"]
        self.assertEqual(d["pool"], [142, 156])

    def test_a_random_line_up_is_weighed_by_what_the_rooms_held(self):
        runs = [[fight(ids=("MONSTER.A",))], [fight(ids=("MONSTER.A",))], [fight(ids=("MONSTER.B",))]]
        self.assertEqual(demand_of(runs)["ENCOUNTER.X"]["pool"][0], round((42 + 42 + 100) / 3))

    def test_turns_is_the_winners_average(self):
        runs = [[fight(t=2)], [fight(t=3)], [fight(t=7)]]
        self.assertEqual(line_of(runs)["turns"], 4)

    def test_lost_runs_are_not_in_the_line(self):
        won = [[fight(t=3, taken=10)] for _ in range(fd.WON_MIN)]
        lost = [[fight(t=30, taken=90), fight(enc="ENCOUNTER.Y", died=True)] for _ in range(5)]
        d = line_of([*won, *lost])
        self.assertEqual((d["turns"], d["taken"], d["n"]), (3, 10, fd.WON_MIN))

    def test_every_fight_of_a_won_run_is_in_the_line(self):
        runs = [[fight(t=4), fight(enc="ENCOUNTER.Y", t=2)] for _ in range(fd.WON_MIN)]
        self.assertEqual(demand_of(runs)["ENCOUNTER.Y"]["tiers"][0]["turns"], 2)

    def test_lost_runs_still_count_towards_the_pool(self):
        won = [[fight(ids=("MONSTER.A",))] for _ in range(fd.WON_MIN)]
        lost = [[fight(ids=("MONSTER.B",)), fight(enc="ENCOUNTER.Y", died=True)] for _ in range(fd.WON_MIN)]
        self.assertEqual(demand_of([*won, *lost])["ENCOUNTER.X"]["pool"][0], 71)

    def test_too_few_wins_is_a_pool_and_no_line(self):
        d = demand_of([[fight()] for _ in range(fd.WON_MIN - 1)])["ENCOUNTER.X"]
        self.assertEqual(d["pool"][0], 42)
        self.assertNotIn("turns", d["tiers"][0])

    def test_a_party_gets_its_own_line_once_it_has_enough_wins(self):
        solo = [[fight(t=3)] for _ in range(3)]
        party = [[fight(t=5, share=1.1)] for _ in range(fd.COOP_MIN)]
        d = line_of([*solo, *party])
        self.assertEqual((d["turns"], d["n"]), (3, 3))
        self.assertEqual(d["coop"]["turns"], 5)

    def test_a_few_co_op_wins_are_not_a_line(self):
        party = [[fight(t=5, share=1.1)] for _ in range(fd.COOP_MIN - 1)]
        self.assertNotIn("coop", line_of([[fight(t=3)], *party]))

    def test_an_encounter_only_parties_have_won_still_has_a_line(self):
        party = [[fight(t=5, share=1.1)] for _ in range(fd.WON_MIN)]
        self.assertEqual(line_of(party)["turns"], 5)

    def test_a_log_fills_in_an_encounter_the_data_has_no_hp_for(self):
        d = demand_of([[fight(ids=("MONSTER.DOORMAKER",))]], {"ENCOUNTER.X": 300})["ENCOUNTER.X"]
        self.assertEqual(d["pool"], [300, 300])

    def test_a_log_well_over_the_pool_scales_both_difficulties(self):
        d = demand_of([[fight(ids=("MONSTER.B",))]], {"ENCOUNTER.X": 200})["ENCOUNTER.X"]
        self.assertEqual(d["pool"], [200, 220])

    def test_a_log_near_the_pool_changes_nothing(self):
        d = demand_of([[fight(ids=("MONSTER.B",))]], {"ENCOUNTER.X": 120})["ENCOUNTER.X"]
        self.assertEqual(d["pool"], [100, 110])


class ManyTargets(unittest.TestCase):
    OLD = (0, 103, 2)

    def test_one_enemy_is_one_target(self):
        self.assertFalse(fd.many_targets([fight()]))

    def test_an_opening_line_up_of_two_is_many(self):
        self.assertTrue(fd.many_targets([fight(ids=("MONSTER.A", "MONSTER.A"))]))

    def test_one_run_seeing_a_spawn_speaks_for_a_run_that_killed_it_first(self):
        self.assertTrue(fd.many_targets([fight(), fight(ids=("MONSTER.A", "MONSTER.B"))]))

    def test_an_older_version_does_not_speak_for_a_newer_one(self):
        self.assertFalse(fd.many_targets([fight(ids=("MONSTER.A", "MONSTER.A"), build=self.OLD), fight()]))

    def test_an_older_version_speaks_when_nothing_newer_fought_it(self):
        self.assertTrue(fd.many_targets([fight(ids=("MONSTER.A", "MONSTER.A"), build=self.OLD)]))

    def test_an_unknown_version_is_older(self):
        self.assertFalse(fd.many_targets([fight(ids=("MONSTER.A", "MONSTER.A"), build=()), fight()]))

    def test_the_table_carries_it(self):
        self.assertIs(demand_of([[fight()]])["ENCOUNTER.X"]["many"], False)

    def test_a_run_files_version_reaches_the_fight(self):
        raw = {**run([room(["MONSTER.A"])]), "build_id": "v0.106.1"}
        self.assertEqual(fd.run_fights({"x": raw})[0][0]["build"], (0, 106, 1))
        self.assertTrue(fd.run_fights({"x": raw})[0][0]["build"] >= fd.SPAWNS_LISTED)


class Tiers(unittest.TestCase):
    def wins(self, asc, t, n=fd.WON_MIN):
        return [[fight(asc=asc, t=t)] for _ in range(n)]

    def test_each_is_how_the_monsters_are_tuned(self):
        self.assertEqual([fd.tier(a) for a in (0, 1, 7, 8, 9, 10)], [0, 0, 0, 1, 1, 1])

    def test_under_8_shares_a_line(self):
        self.assertEqual(line_of([[fight(asc=0, t=2)], [fight(asc=1, t=3)], [fight(asc=7, t=7)]])["turns"], 4)

    def test_8_9_and_10_share_a_line(self):
        self.assertEqual(line_of([[fight(asc=8, t=2)], [fight(asc=10, t=3)], [fight(asc=9, t=7)]], 1)["turns"], 4)

    def test_a_line_holds_only_its_own_tiers_wins(self):
        tiers = demand_of([*self.wins(1, 3), *self.wins(10, 9)])["ENCOUNTER.X"]["tiers"]
        self.assertEqual([t["turns"] for t in tiers], [3, 9])
        self.assertEqual([t["n"] for t in tiers], [fd.WON_MIN] * 2)

    def test_too_few_wins_in_a_tier_borrows_from_no_other(self):
        d = demand_of([*self.wins(1, 3, 20), *self.wins(9, 9, fd.WON_MIN - 1)])["ENCOUNTER.X"]
        self.assertIsNone(fd.winners_of(fight(asc=8), d))
        self.assertEqual(fd.winners_of(fight(asc=1), d)["turns"], 3)

    def test_an_act_leaves_out_fights_its_tier_has_no_line_for(self):
        demand = demand_of(self.wins(1, 3, 20))
        self.assertEqual(fd.act_readings([fight(asc=8)] * 3, demand, CUTS), [])

    def test_the_hp_a_fight_reads_at_is_the_runs_own(self):
        demand = demand_of(self.wins(8, 3))
        self.assertAlmostEqual(fd.readings([fight(asc=8)], demand)[0]["doing"], 46 / 3)


class SharedMoves(unittest.TestCase):
    PD = {"encounters": {"ENCOUNTER.X": {"monsters": ["MONSTER.A", "MONSTER.B"]}},
          "monsters": {"MONSTER.A": {"hpMin": [100, 105], "hpMax": [101, 106], "moves": [
                           {"id": "RAM", "intents": [{"dmg": 15}]},
                           {"id": "SAME", "intents": [{"dmg": 3}]}]},
                       "MONSTER.B": {"hpMin": [80, 85], "hpMax": [100, 100], "moves": [
                           {"id": "RAM", "intents": [{"dmg": 10}]},
                           {"id": "SAME", "intents": [{"dmg": 3}]}]}}}

    def setUp(self):
        patcher = mock.patch.object(fd.pc, "PD", self.PD)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_max_hp_says_whose_move_it_was(self):
        table = fd.tr.move_table()
        self.assertEqual(table[("ENCOUNTER.X", "RAM", 106)][0], [(15, 1)])
        self.assertEqual(table[("ENCOUNTER.X", "RAM", 80)][0], [(10, 1)])

    def test_where_the_bands_touch_the_first_monster_listed_wins(self):
        self.assertEqual(fd.tr.move_table()[("ENCOUNTER.X", "RAM", 100)][0], [(15, 1)])

    def test_an_hp_outside_both_bands_falls_back_to_the_encounter(self):
        table = fd.tr.move_table()
        self.assertNotIn(("ENCOUNTER.X", "RAM", 500), table)
        self.assertEqual(table[("ENCOUNTER.X", "RAM")][0], [(15, 1)])

    def test_a_move_that_means_the_same_on_both_needs_no_hp(self):
        self.assertFalse([k for k in fd.tr.move_table() if k[:2] == ("ENCOUNTER.X", "SAME") and len(k) == 3])


class Deadly(unittest.TestCase):
    PD = {"encounters": {}, "monsters": {"MONSTER.A": {"moves": [
        {"id": "HIT", "intents": [{"dmg": 6, "dmgAsc": 7, "hits": 2}]},
        {"id": "SAME", "intents": [{"dmg": 3}]},
    ]}}}

    def setUp(self):
        patcher = mock.patch.object(fd.pc, "PD", self.PD)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_each_move_table_reads_its_own_column(self):
        self.assertEqual(fd.tr.move_table()["HIT"][0], [(6, 2)])
        self.assertEqual(fd.tr.move_table("dmgAsc")["HIT"][0], [(7, 2)])

    def test_a_move_ascension_leaves_alone_keeps_its_damage(self):
        self.assertEqual(fd.tr.move_table("dmgAsc")["SAME"][0], [(3, 1)])

    def test_a_log_reads_moves_at_its_runs_ascension(self):
        with tempfile.TemporaryDirectory() as folder:
            for start in (1, 2, 3):
                path = Path(folder) / "sid" / f"{start}.json.gz"
                path.parent.mkdir(exist_ok=True)
                with gzip.open(path, "wt", encoding="utf-8") as fh:
                    json.dump({"log": []}, fh)
            runs = {("sid", 1): {"ascension": fd.tr.DEADLY - 1}, ("sid", 2): {"ascension": fd.tr.DEADLY}}
            with mock.patch.object(fd.tr, "TELEMETRY", Path(folder)), \
                    mock.patch.object(fd.tr.dt, "derive", lambda log, moves: moves["HIT"][0]):
                logs, _ = fd.tr.load_logs(runs)
        self.assertEqual(logs[("sid", 1)], [(6, 2)])
        self.assertEqual(logs[("sid", 2)], [(7, 2)])
        # No run file to say otherwise: base.
        self.assertEqual(logs[("sid", 3)], [(6, 2)])


DEMAND = {
    "ENCOUNTER.X": {"pool": [100, 120], "tiers": every_tier({"turns": 3, "n": 9})},
    "ENCOUNTER.NEW": {"pool": [0, 0], "tiers": every_tier({"turns": 3, "n": 9})},
    "ENCOUNTER.UNWON": {"pool": [100, 120], "tiers": every_tier({})},
}


class Readings(unittest.TestCase):
    def test_every_fight_reads_on_its_own(self):
        rows = fd.readings([fight(t=1), fight(t=5)], DEMAND)
        self.assertEqual([r["t"] for r in rows], [1, 5])
        self.assertAlmostEqual(rows[1]["doing"], 100 / 5)

    def test_a_fight_with_no_pool_is_skipped(self):
        self.assertEqual(fd.readings([fight(enc="ENCOUNTER.NEW")], DEMAND), [])

    def test_an_encounter_with_no_data_is_skipped(self):
        self.assertEqual(fd.readings([fight(enc="ENCOUNTER.GONE")], DEMAND), [])

    def test_an_encounter_too_few_have_won_is_skipped(self):
        self.assertEqual(fd.readings([fight(enc="ENCOUNTER.UNWON")], DEMAND), [])

    def test_reads_against_winners_on_that_fight(self):
        row = fd.readings([fight(t=6)], DEMAND)[0]
        self.assertAlmostEqual(row["ask"], 100 / 3)
        self.assertAlmostEqual(row["damage"], 1 / 2)

    def test_co_op_reads_a_players_share_against_winning_parties(self):
        line = {"turns": 3, "n": 9, "coop": {"turns": 4, "n": 9}}
        demand = {"ENCOUNTER.X": {"pool": [100, 120], "tiers": every_tier(line)}}
        row = fd.readings([fight(t=3, share=1.2)], demand)[0]
        self.assertAlmostEqual(row["doing"], 120 / 3)
        self.assertAlmostEqual(row["ask"], 120 / 4)

    def test_a_party_with_no_line_of_its_own_borrows_solo(self):
        row = fd.readings([fight(t=3, share=1.2)], DEMAND)[0]
        self.assertAlmostEqual(row["ask"], 120 / 3)

    def test_a_one_turn_kill_reads_as_what_it_did(self):
        row = fd.readings([fight(t=1)], DEMAND)[0]
        self.assertAlmostEqual(row["doing"], 100)
        self.assertAlmostEqual(row["damage"], 3)

    def test_tough_enemies_raise_the_pool(self):
        row = fd.readings([fight(asc=fd.TOUGH)], DEMAND)[0]
        self.assertAlmostEqual(row["ask"], 120 / 3)


class Winners(unittest.TestCase):
    def test_turns_and_damage_taken_are_per_fight(self):
        got = fd.winners([fight(t=3, taken=10), fight(t=1, taken=4)])
        self.assertEqual((got["turns"], got["taken"], got["n"]), (2, 7, 2))

    def test_the_rate_is_over_the_turns_the_enemies_got(self):
        # They act after you, so 3 won turns gave them 2.
        self.assertEqual(fd.winners([fight(t=3, taken=10)])["rate"], 5)

    def test_a_lost_fight_gave_them_every_turn(self):
        self.assertEqual(fd.swung(fight(t=3, died=True)), 3)

    def test_a_one_turn_kill_has_no_turn_to_divide_by(self):
        self.assertEqual(fd.winners([fight(t=1, taken=4)])["rate"], 0)

    def test_the_rate_is_a_sum_over_a_sum(self):
        self.assertEqual(fd.winners([fight(t=1, taken=4), fight(t=3, taken=8)])["rate"], 6)

    def test_the_table_keeps_the_rate(self):
        d = line_of([[fight(taken=6)] for _ in range(fd.WON_MIN)])
        self.assertEqual(d["rate"], 3)


ACT_X = {"turns": 4, "taken": 15, "n": 9}
ACTS = {"ENCOUNTER.X": {"tiers": every_tier(ACT_X)},
        "ENCOUNTER.Y": {"tiers": every_tier({"turns": 2, "taken": 2, "n": 9})},
        "ENCOUNTER.UNWON": {"pool": [100, 120], "tiers": every_tier({})}}
# Quarters of winning acts, fixed here so a case reads the same whatever the history holds.
CUT = {"guard": [0.67, 1.5], "pace": [0.8, 1.25]}
CUTS = {"acts": [CUT] * 3, "run": CUT}


class ActReadings(unittest.TestCase):
    def test_each_fight_is_held_to_its_own_winners_and_the_act_sums_them(self):
        fights = [fight(t=4, taken=9), fight(enc="ENCOUNTER.Y", t=2, taken=3), fight(t=6, taken=0)]
        row = fd.act_readings(fights, ACTS, CUTS)[0]
        self.assertEqual((row["turns"], row["winTurns"]), (12, 10))
        self.assertEqual((row["taken"], row["winTaken"]), (12, 32))
        self.assertAlmostEqual(row["pace"], 10 / 12)
        self.assertAlmostEqual(row["guard"], 33 / 13)
        self.assertAlmostEqual(row["each"], (33 / 13) / (10 / 12))

    def test_a_hard_act_that_matches_winners_reads_level(self):
        row = fd.act_readings([fight(t=4, taken=15)] * 3, ACTS, CUTS)[0]
        self.assertEqual(row["pace"], 1)
        self.assertEqual(row["guard"], 1)
        self.assertEqual(row["verdict"], "meeting")

    def test_slow_is_fine_so_long_as_damage_taken_holds(self):
        row = fd.act_readings([fight(t=8, taken=15)] * 3, ACTS, CUTS)[0]
        self.assertEqual(row["pace"], 0.5)
        self.assertEqual(row["verdict"], "meeting")
        self.assertIsNone(row["lacking"])

    def test_being_slow_earns_no_allowance_of_damage(self):
        row = fd.act_readings([fight(t=8, taken=30)] * 3, ACTS, CUTS)[0]
        self.assertEqual(row["verdict"], "behind")

    def test_fights_that_ran_long_lack_damage(self):
        row = fd.act_readings([fight(t=8, taken=30)] * 3, ACTS, CUTS)[0]
        self.assertEqual(row["lacking"], "damage")

    def test_too_much_each_turn_lacks_block(self):
        row = fd.act_readings([fight(t=4, taken=60)] * 3, ACTS, CUTS)[0]
        self.assertEqual(row["verdict"], "behind")
        self.assertEqual(row["lacking"], "block")

    def test_ahead_lacks_nothing(self):
        row = fd.act_readings([fight(t=8, taken=1)] * 3, ACTS, CUTS)[0]
        self.assertEqual(row["verdict"], "ahead")
        self.assertIsNone(row["lacking"])

    def test_killing_much_faster_without_taking_more_is_ahead(self):
        row = fd.act_readings([fight(t=3, taken=15)] * 3, ACTS, CUTS)[0]
        self.assertEqual((row["held"], row["speed"]), ("meeting", "ahead"))
        self.assertEqual(row["verdict"], "ahead")

    def test_killing_much_faster_and_taking_more_is_meeting(self):
        row = fd.act_readings([fight(t=3, taken=20)] * 3, ACTS, CUTS)[0]
        self.assertEqual((row["held"], row["speed"]), ("meeting", "ahead"))
        self.assertEqual(row["verdict"], "meeting")

    def test_speed_lifts_nothing_out_of_behind(self):
        row = fd.act_readings([fight(t=2, taken=60)] * 3, ACTS, CUTS)[0]
        self.assertEqual((row["held"], row["speed"]), ("behind", "ahead"))
        self.assertEqual(row["verdict"], "behind")

    def test_a_slow_act_keeps_its_reading_and_its_own_mark(self):
        row = fd.act_readings([fight(t=8, taken=1)] * 3, ACTS, CUTS)[0]
        self.assertEqual((row["held"], row["speed"]), ("ahead", "behind"))
        self.assertEqual(row["verdict"], "ahead")

    def test_an_act_with_no_damage_still_divides(self):
        row = fd.act_readings([fight(t=4)] * 3, ACTS, CUTS)[0]
        self.assertEqual(row["guard"], 46)

    def test_the_fight_that_ended_the_run_is_left_out(self):
        fights = [fight()] * 3 + [fight(t=50, taken=999, died=True)]
        self.assertEqual(fd.act_readings(fights, ACTS, CUTS)[0]["fights"], 3)

    def test_too_few_fights_is_no_reading(self):
        self.assertEqual(fd.act_readings([fight()] * (fd.ACT_MIN - 1), ACTS, CUTS), [])

    def test_an_encounter_with_no_data_does_not_count(self):
        fights = [fight()] * 3 + [fight(enc="ENCOUNTER.GONE")]
        self.assertEqual(fd.act_readings(fights, ACTS, CUTS)[0]["fights"], 3)

    def test_an_encounter_too_few_have_won_does_not_count(self):
        fights = [fight()] * 3 + [fight(enc="ENCOUNTER.UNWON")]
        self.assertEqual(fd.act_readings(fights, ACTS, CUTS)[0]["fights"], 3)

    def test_acts_read_apart(self):
        rows = fd.act_readings([fight(act=a) for a in (0, 0, 0, 1, 1, 1)], ACTS, CUTS)
        self.assertEqual([r["act"] for r in rows], [0, 1])

    def test_a_party_reads_against_winning_parties(self):
        demand = {"ENCOUNTER.X": {"tiers": every_tier({**ACT_X, "coop": {"turns": 8, "taken": 1, "n": 9}})}}
        row = fd.act_readings([fight(t=4, share=1.2)] * 3, demand, CUTS)[0]
        self.assertEqual(row["winTurns"], 24)
        self.assertEqual(row["winTaken"], 3)


class RunReading(unittest.TestCase):
    def read(self, *acts):
        """A run of three fights an act, each given as (turns, damage taken)."""
        fights = [fight(t=t, taken=taken, act=a) for a, (t, taken) in enumerate(acts) for _ in range(3)]
        return fd.run_reading(fd.act_readings(fights, ACTS, CUTS), CUTS)

    def test_a_run_is_its_acts_added_up(self):
        got = self.read((4, 15), (6, 3))
        self.assertEqual((got["turns"], got["winTurns"]), (30, 24))
        self.assertEqual((got["taken"], got["winTaken"]), (54, 90))
        self.assertAlmostEqual(got["pace"], 24 / 30)
        self.assertAlmostEqual(got["guard"], 91 / 55)

    def test_it_reads_on_the_totals_not_a_count_of_acts(self):
        # Two acts just under the line and one far over: most acts read behind, the run doesn't.
        got = self.read((4, 25), (4, 25), (4, 0))
        self.assertEqual(got["verdict"], "meeting")

    def test_the_same_rule_as_an_act(self):
        for acts, want in (([(4, 15)], "meeting"), ([(4, 60)], "behind"), ([(8, 1)], "ahead"), ([(3, 15)], "ahead"),
                           ([(3, 20)], "meeting"), ([(8, 15)], "meeting")):
            with self.subTest(acts=acts):
                self.assertEqual(self.read(*acts)["verdict"], want)

    def test_no_act_to_read_is_no_reading(self):
        self.assertIsNone(fd.run_reading([], CUTS))

    def test_op_is_ahead_in_both_late_acts(self):
        behind = (4, 60)
        ahead = (8, 1)
        self.assertTrue(self.read(behind, ahead, ahead)["op"])
        self.assertFalse(self.read(ahead, behind, ahead)["op"])
        self.assertFalse(self.read(ahead, ahead, behind)["op"])

    def test_op_counts_killing_much_faster_as_ahead(self):
        self.assertTrue(self.read((4, 15), (3, 15), (3, 15))["op"])

    def test_a_run_that_stopped_short_of_act_three_is_not_op(self):
        self.assertFalse(self.read((8, 1), (8, 1))["op"])

    def test_op_takes_no_win(self):
        fights = [fight(t=8, taken=1, act=a) for a in (1, 2) for _ in range(3)] + [fight(act=2, died=True)]
        self.assertTrue(fd.run_reading(fd.act_readings(fights, ACTS, CUTS), CUTS)["op"])


class HeldOut(unittest.TestCase):
    def test_a_whole_run_reads_against_the_other_half_only(self):
        # Against its own half each run would meet its own line.
        cells = fd.held_out([self.steady, self.strong] * 2, CUTS)
        self.assertEqual(len(cells["solo", 0, "run", "behind"]), 2)
        self.assertEqual(len(cells["solo", 0, "run", "ahead"]), 2)
        self.assertNotIn(("solo", 0, "run", "meeting"), cells)

    def test_an_op_run_counts_as_ahead_too(self):
        cells = fd.held_out([self.steady, self.strong] * 2, CUTS)
        self.assertEqual(cells["solo", 0, "run", "op"], cells["solo", 0, "run", "ahead"])

    steady = [fight(t=4, taken=30, act=a) for a in range(3) for _ in range(3)]
    strong = [fight(t=4, taken=0, act=a) for a in range(3) for _ in range(3)]


class ActRows(unittest.TestCase):
    def test_each_player_of_a_party_is_read(self):
        party = [{**fight(t=4, share=1.2), "each": [3, 30]} for _ in range(3)]
        rows = list(fd.act_rows([party], ACTS, CUTS))
        self.assertEqual([r[0] for r in rows], ["coop", "coop"])
        self.assertEqual([r[3]["taken"] for r in rows], [9, 90])

    def test_a_lost_run_is_marked(self):
        fights = [fight()] * 3 + [fight(died=True)]
        self.assertFalse(next(fd.act_rows([fights], ACTS, CUTS))[2])

    def test_a_run_is_marked_with_its_tier(self):
        self.assertEqual(next(fd.act_rows([[fight(asc=10)] * 3], ACTS, CUTS))[1], 1)


class Verdict(unittest.TestCase):
    def test_on_the_edge_is_meeting(self):
        low, high = CUT["guard"]
        self.assertEqual([fd.verdict(1, v, CUT) for v in (low - 0.01, low, high, high + 0.01)],
                         ["behind", "meeting", "meeting", "ahead"])

    def test_level_with_winners_is_meeting(self):
        self.assertEqual(fd.verdict(1, 1, CUT), "meeting")

    def test_on_the_speed_edge_is_meeting(self):
        fast = CUT["pace"][1]
        self.assertEqual([fd.verdict(p, 1, CUT) for p in (fast, fast + 0.01)], ["meeting", "ahead"])

    def test_just_over_on_damage_taken_gets_no_lift(self):
        self.assertEqual(fd.verdict(2, 0.99, CUT), "meeting")

    def test_the_edges_are_the_ones_given(self):
        tight = {"guard": [0.9, 1.1], "pace": [0.95, 1.05]}
        self.assertEqual([fd.verdict(1, g, tight) for g in (0.85, 1.2)], ["behind", "ahead"])
        self.assertEqual([fd.verdict(1, g, CUT) for g in (0.85, 1.2)], ["meeting", "meeting"])


class Cuts(unittest.TestCase):
    """The quarters an act is read against: winning acts only, every tier together."""

    @staticmethod
    def played(taken, t=4, asc=0, died=False):
        fights = [fight(t=t, taken=taken, asc=asc, act=a) for a in range(3) for _ in range(3)]
        return fights + [fight(act=2, died=True)] if died else fights

    def cuts(self, runs):
        return fd.cuts_of(runs, fd.table(runs))

    def test_the_quarters_are_of_winning_acts(self):
        runs = [self.played(taken) for taken in (0, 10, 20, 30, 40)]
        got = self.cuts(runs)["acts"][0]["guard"]
        guards = sorted(r["guard"] for fights in runs for r in fd.act_totals(fights, fd.table(runs)) if r["act"] == 0)
        self.assertEqual(got, [round(q, 3) for q in statistics.quantiles(guards, n=4)[::2]])
        self.assertLess(got[0], 1)
        self.assertGreater(got[1], 1)

    def test_a_lost_run_moves_nothing(self):
        wins = [self.played(taken) for taken in (0, 10, 20, 30, 40)]
        self.assertEqual(self.cuts(wins), self.cuts(wins + [self.played(500, died=True)] * 5))

    def test_every_tier_goes_in(self):
        low = [self.played(taken) for taken in (0, 10, 20)]
        high = [self.played(taken, asc=10) for taken in (0, 60, 120)]
        self.assertNotEqual(self.cuts(low + high), self.cuts(low + [self.played(10, asc=10)] * 3))

    def test_one_set_per_act_and_one_for_runs(self):
        got = self.cuts([self.played(taken) for taken in (0, 10, 20, 30, 40)])
        self.assertEqual(len(got["acts"]), 3)
        self.assertEqual(set(got["run"]), {"guard", "pace"})

    def test_an_act_past_the_last_has_the_runs_quarters(self):
        self.assertIs(fd.act_cut({"acts": [CUT], "run": "run"}, 1), "run")


if __name__ == "__main__":
    unittest.main()
