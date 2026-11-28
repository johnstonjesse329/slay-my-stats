import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambda" / "ingest"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import showcase

NOW = 100 * 86400


def run(ts, **kw):
    return {"slug": "a", "name": "A", "ts": ts, "char": "CHARACTER.SILENT", "asc": 5, "deck": 20, **kw}


class TurnPeaks(unittest.TestCase):
    def test_block_and_hit_by_turn(self):
        log = {"log": [
            {"k": "blk", "f": 1, "t": 1, "a": {"c": "P", "n": 7}},
            {"k": "blk", "f": 1, "t": 1, "a": {"c": "P", "n": 5}},
            {"k": "blk", "f": 1, "t": 2, "a": {"c": "E", "n": 99}},
            {"k": "hit", "f": 1, "t": 2, "a": {"by": "P", "t": "Louse", "unb": 10, "ovk": 4}},
            {"k": "hit", "f": 1, "t": 2, "a": {"by": "P", "t": "Louse", "unb": 8, "ovk": 6}},
            {"k": "hit", "f": 1, "t": 3, "a": {"by": "P", "t": "P", "ovk": 50}},
        ]}
        self.assertEqual(showcase.turn_peaks(log), {"blocked": 12, "hit": 28})

    def test_block_held_counts_carry_over(self):
        def snap(f, t, why, blk, enemy=300):
            return {"k": "snap", "f": f, "t": t, "a": {"why": why, "creatures": [
                {"c": "P", "you": True, "blk": blk}, {"c": "Louse", "you": False, "blk": enemy}]}}
        log = {"log": [
            {"k": "blk", "f": 1, "t": 1, "a": {"c": "P", "n": 40}},
            snap(1, 1, "side1", 40),
            snap(1, 2, "turn0", 40),                       # carried over
            {"k": "blk", "f": 1, "t": 2, "a": {"c": "P", "n": 30}},
            snap(1, 2, "side1", 70),
            snap(1, 3, "fight0", 999),                     # not a turn reading
        ]}
        self.assertEqual(showcase.turn_peaks(log), {"blocked": 40, "held": 70})

    def test_missing_figures_are_left_out(self):
        self.assertEqual(showcase.turn_peaks({"log": []}), {})
        self.assertEqual(showcase.turn_peaks(None), {})

    def test_multiplayer_uses_the_uploaders_own_events(self):
        def event(kind, **args):
            return {"k": kind, "f": 1, "t": 1, "a": args}

        log = {"log": [
            event("snap", why="side1", creatures=[
                {"c": "P", "slot": 0, "blk": 100}, {"c": "P", "slot": 1, "blk": 12}]),
            event("blk", c="P", sourceSlot=1, targetSlot=0, n=100),
            event("blk", c="P", sourceSlot=0, targetSlot=1, n=9),
            event("hit", by="P", t="enemy", sourceSlot=1, enemy=True, unb=20, ovk=3),
            event("hit", by="P", t="enemy", sourceSlot=0, enemy=True, unb=100, ovk=0),
            event("hit", by="P", t="enemy", enemy=True, unb=100, ovk=0),
            event("hit", by="P", t="Osty", sourceSlot=1, enemy=False, unb=100, ovk=0),
        ]}
        self.assertEqual(showcase.turn_peaks(log, slot=1), {"blocked": 9, "held": 12, "hit": 23})


class FinalBossNoDamage(unittest.TestCase):
    def test_only_the_second_a10_boss_counts(self):
        first_boss = {"map_point_type": "boss", "player_stats": [{"damage_taken": 0}],
                      "rooms": [{"model_id": "ENCOUNTER.A"}]}
        second_boss = {"map_point_type": "boss", "player_stats": [{"damage_taken": 7, "hp_healed": 7}],
                       "rooms": [{"model_id": "ENCOUNTER.B"}]}
        raw = {"win": True, "players": [{}], "ascension": 10,
               "map_point_history": [[], [], [first_boss, second_boss]]}
        self.assertFalse(showcase.final_boss_no_damage(raw, 0))
        raw["map_point_history"][-1].reverse()
        self.assertTrue(showcase.final_boss_no_damage(raw, 0))
        raw["map_point_history"][-1].pop(0)
        self.assertFalse(showcase.final_boss_no_damage(raw, 0))

    def test_requires_recorded_numeric_damage(self):
        stats = {"hp_healed": 0}
        boss = {"map_point_type": "boss", "rooms": [{"model_id": "ENCOUNTER.A"}], "player_stats": [stats]}
        raw = {"win": True, "players": [{}], "map_point_history": [[], [], [boss]]}
        self.assertFalse(showcase.final_boss_no_damage(raw, 0))
        stats["damage_taken"] = 0
        self.assertTrue(showcase.final_boss_no_damage(raw, 0))
        stats["damage_taken"] = False
        self.assertFalse(showcase.final_boss_no_damage(raw, 0))

    def test_requires_a_win_with_final_act_boss_history(self):
        boss = {"map_point_type": "boss", "player_stats": [{"damage_taken": 0}],
                "rooms": [{"model_id": "ENCOUNTER.A"}]}
        raw = {"win": True, "players": [{}], "map_point_history": [[], [], [boss]]}
        self.assertFalse(showcase.final_boss_no_damage({**raw, "win": False}, 0))
        self.assertFalse(showcase.final_boss_no_damage({**raw, "was_abandoned": True}, 0))
        self.assertFalse(showcase.final_boss_no_damage({**raw, "map_point_history": [[], [boss]]}, 0))


class Build(unittest.TestCase):
    def test_each_modes_top_runs_are_kept_even_when_the_combined_tab_is_full(self):
        solo = run(NOW - 1, deck=40)
        multiplayer = run(NOW - 2, deck=30, multiplayer=True, op=True)
        out = showcase.build([solo, multiplayer], NOW, per_tab=1)
        self.assertEqual([e["n"] for e in out["deck"]], [40])
        self.assertEqual([e["n"] for e in out["modes"]["solo"]["deck"]], [40])
        self.assertEqual([e["n"] for e in out["modes"]["multiplayer"]["deck"]], [30])
        self.assertTrue(out["modes"]["multiplayer"]["op"][0]["multiplayer"])

    def test_window_and_gaps(self):
        old = run(NOW - 31 * 86400, deck=90, op=True)
        out = showcase.build([old, run(NOW - 86400, op=True), run(NOW - 2 * 86400, deck=40, blocked=30, held=55)], NOW)
        self.assertEqual([e["ts"] for e in out["op"]], [NOW - 86400])
        self.assertEqual([e["n"] for e in out["deck"]], [40, 20])
        self.assertNotIn("blocked", out)
        self.assertEqual([e["n"] for e in out["held"]], [55])
        self.assertEqual(out["hit"], [])

    def test_op_runs_are_unlimited_and_figure_tabs_are_capped(self):
        out = showcase.build([run(NOW - i, deck=i, op=True) for i in range(1, 50)], NOW)
        self.assertEqual(len(out["op"]), 49)
        self.assertEqual(len(out["deck"]), 30)

    def test_zero_damage_boss_wins_are_recent_uncapped_and_filtered_by_mode(self):
        solo = run(NOW - 1, boss_no_damage=True)
        damaged = run(NOW - 2, boss_no_damage=False, multiplayer=True)
        coop = run(NOW - 3, boss_no_damage=True, multiplayer=True)
        old = run(NOW - 31 * 86400, boss_no_damage=True)
        out = showcase.build([old, coop, damaged, solo], NOW, per_tab=1)
        self.assertEqual([e["ts"] for e in out["boss_no_damage"]], [solo["ts"], coop["ts"]])
        self.assertEqual([e["ts"] for e in out["modes"]["solo"]["boss_no_damage"]], [solo["ts"]])
        self.assertEqual([e["ts"] for e in out["modes"]["multiplayer"]["boss_no_damage"]], [coop["ts"]])

    def test_handful(self):
        out = showcase.build([run(NOW - i, deck=i + 1) for i in range(1, 20)], NOW, per_tab=3)
        self.assertEqual(len(out["deck"]), 3)
        self.assertEqual(out["deck"][0]["n"], 20)

    def test_synergy_names_ride_along_and_old_rows_do_not_need_them(self):
        out = showcase.build([run(NOW - 5, op=True, syn=["Shiv", "Poison"]), run(NOW - 6, op=True)], NOW)
        self.assertEqual(out["op"][0]["syn"], ["Shiv", "Poison"])
        self.assertNotIn("syn", out["op"][1])


TABLE = {
    "synergy": {
        "cards": {"CARD.A": [["power:Strength"], []], "CARD.B": [[], ["power:Strength"]],
                  "CARD.S1": [["shiv"], []], "CARD.S2": [[], ["shiv"]], "CARD.SOLO": [["lone"], ["lone"]]},
        "relics": {"RELIC.R": [["shiv"], []]},
        "cardVariants": {"CARD.A": [[["power:Strength"], []], [["power:Strength"], ["lone"]]]},
        "cardRolls": {},
    },
    "basic": ["CARD.S1", "CARD.S2"],
}


def cards(*ids, up=0):
    return [{"id": i, "current_upgrade_level": up} for i in ids]


class DeckSynergies(unittest.TestCase):
    def names(self, deck, relics=(), char="CHARACTER.IRONCLAD"):
        return showcase.deck_synergies(char, deck, [{"id": r} for r in relics], TABLE)

    def test_a_maker_and_a_different_user(self):
        self.assertEqual(self.names(cards("CARD.A", "CARD.B")), ["Strength"])
        self.assertEqual(self.names(cards("CARD.A")), [])            # nothing to pay it off
        self.assertEqual(self.names(cards("CARD.SOLO")), [])         # a card never links to itself

    def test_starters_alone_say_nothing_but_a_relic_counts(self):
        self.assertEqual(self.names(cards("CARD.S1", "CARD.S2")), [])
        self.assertEqual(self.names(cards("CARD.S2"), ["RELIC.R"], "CHARACTER.SILENT"), ["Shiv"])

    def test_upgraded_copy_reads_its_own_row(self):
        deck = cards("CARD.A", "CARD.B") + cards("CARD.SOLO", up=1)
        self.assertEqual(self.names(deck), ["Strength"])
        self.assertEqual(showcase.deck_synergies("CHARACTER.IRONCLAD", cards("CARD.A", up=1) + cards("CARD.SOLO"), [], TABLE), ["Lone"])

    def test_unknown_key_is_named_from_the_key_and_no_table_means_none(self):
        self.assertEqual(showcase.synergy_label("power:Poison"), "Poison")
        self.assertEqual(showcase.deck_synergies("CHARACTER.SILENT", cards("CARD.A"), [], {}), [])

    def test_families_match_the_page(self):
        import json, re, shutil, subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("no node")
        src = (Path(__file__).resolve().parents[2] / "js" / "card-face.js").read_text(encoding="utf-8")
        block = re.search(r"const SYNERGY_FAMILIES = (\{.*?^\});", src, re.S | re.M)[1]
        page = json.loads(subprocess.check_output([node, "-e", f"console.log(JSON.stringify({block}))"]))
        self.assertEqual(page, showcase.SYNERGY_FAMILIES)


if __name__ == "__main__":
    unittest.main()
