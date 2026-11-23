"""export_run_records.records: overkill rides along, and damage figures stay exactly as they were.

    infra\.venv\Scripts\python.exe -m unittest tools.test_run_records_overkill
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_run_records as er  # noqa: E402


def log(*hits):
    ev = [{"k": "action0", "f": 0, "t": 1, "q": 0, "a": {}},
          {"k": "fight0", "f": 0, "t": 0, "q": 0, "a": {"enc": "ENCOUNTER.TOAD"}}]
    for i, a in enumerate(hits):
        ev.append({"k": "hit", "f": 0, "t": 1, "q": i + 1,
                   "a": {"by": "P", "t": "Toad", "enemy": True, "sourceSlot": 0, "card": "CARD.STRIKE", **a}})
    return {"log": ev}


class Overkill(unittest.TestCase):
    def test_largest_hit_includes_overkill_but_damage_does_not(self):
        r = er.records(log({"total": 12, "unb": 12, "ovk": 9}, {"total": 15, "unb": 15, "ovk": 0}), 0)
        self.assertEqual((r["largestHit"]["n"], r["largestHit"]["dealt"], r["largestHit"]["overkill"]), (21, 12, 9))
        self.assertEqual(r["damageInTurn"]["n"], 27)  # 12 + 15, overkill not in it
        self.assertEqual((r["mostOverkill"]["n"], r["overkillTotal"]), (9, 9))

    def test_a_log_without_ovk_says_nothing_about_overkill(self):
        r = er.records(log({"total": 12, "unb": 12}), 0)
        self.assertEqual((r["mostOverkill"], r["overkillTotal"]), (None, None))
        self.assertEqual(r["largestHit"]["n"], 12)

    def test_zero_overkill_is_recorded_as_zero(self):
        r = er.records(log({"total": 5, "unb": 5, "ovk": 0}), 0)
        self.assertEqual((r["mostOverkill"], r["overkillTotal"]), (None, 0))


if __name__ == "__main__":
    unittest.main()
