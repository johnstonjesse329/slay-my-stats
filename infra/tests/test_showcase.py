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
    def test_block_and_overkill_by_turn(self):
        log = {"log": [
            {"k": "blk", "f": 1, "t": 1, "a": {"c": "P", "n": 7}},
            {"k": "blk", "f": 1, "t": 1, "a": {"c": "P", "n": 5}},
            {"k": "blk", "f": 1, "t": 2, "a": {"c": "E", "n": 99}},
            {"k": "hit", "f": 1, "t": 2, "a": {"by": "P", "t": "Louse", "ovk": 4}},
            {"k": "hit", "f": 1, "t": 2, "a": {"by": "P", "t": "Louse", "ovk": 6}},
            {"k": "hit", "f": 1, "t": 3, "a": {"by": "P", "t": "P", "ovk": 50}},
        ]}
        self.assertEqual(showcase.turn_peaks(log), {"blocked": 12, "overkill": 10})

    def test_missing_figures_are_left_out(self):
        self.assertEqual(showcase.turn_peaks({"log": []}), {})
        self.assertEqual(showcase.turn_peaks(None), {})


class Build(unittest.TestCase):
    def test_window_and_gaps(self):
        old = run(NOW - 31 * 86400, deck=90, op=True)
        out = showcase.build([old, run(NOW - 86400, op=True), run(NOW - 2 * 86400, deck=40, blocked=30)], NOW)
        self.assertEqual([e["ts"] for e in out["op"]], [NOW - 86400])
        self.assertEqual([e["n"] for e in out["deck"]], [40, 20])
        self.assertEqual([e["n"] for e in out["blocked"]], [30])
        self.assertEqual(out["overkill"], [])

    def test_handful(self):
        out = showcase.build([run(NOW - i, deck=i + 1) for i in range(1, 20)], NOW, per_tab=3)
        self.assertEqual(len(out["deck"]), 3)
        self.assertEqual(out["deck"][0]["n"], 20)


if __name__ == "__main__":
    unittest.main()
