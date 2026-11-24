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


class Build(unittest.TestCase):
    def test_window_and_gaps(self):
        old = run(NOW - 31 * 86400, deck=90, op=True)
        out = showcase.build([old, run(NOW - 86400, op=True), run(NOW - 2 * 86400, deck=40, blocked=30, held=55)], NOW)
        self.assertEqual([e["ts"] for e in out["op"]], [NOW - 86400])
        self.assertEqual([e["n"] for e in out["deck"]], [40, 20])
        self.assertEqual([e["n"] for e in out["blocked"]], [30])
        self.assertEqual([e["n"] for e in out["held"]], [55])
        self.assertEqual(out["hit"], [])

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
