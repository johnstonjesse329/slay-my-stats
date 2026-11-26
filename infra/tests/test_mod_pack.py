import contextlib
import gzip
import io
import json
import re
import unittest
from unittest import mock

import test_benchmark  # noqa: F401 -- sets up the import path
import benchmark
import mod_pack

STATIC = {"synergy": {"cards": {}}, "archetypes": {}, "basic": ["CARD.STRIKE"]}
BENCH = {"encounters": {"ENCOUNTER.A": {"pool": [90, 110], "many": False, "count": 1, "tiers": [
    {"turns": 3.1, "taken": 6.2, "rate": 2, "n": 40, "fast": 2,
     "coop": {"turns": 4, "taken": 5, "n": 6, "rate": 1}}, {}]}},
    "cuts": {"acts": [], "run": {"guard": [0, 1], "pace": [0, 1]}}, "ratings": {"x": 1}}
STATS = {"solo": {"chars": {"FOOL": [20, 15]}, "cards": {"CARD.A": [20, 15]}, "relics": {},
                  "killers": {"X": 1},
                  "records": {"fastestWin": {"slug": "me", "steamId": "76561198000000001"}},
                  "picks": {"FOOL": {"cards": {"CARD.A": [1, 2, 3, 4, 5, 6, 7],
                                               "CARD.B": [1, 2, 3, 4]},
                                     "events": {"E": {}}}}}}


class Build(unittest.TestCase):
    def test_pack(self):
        pack, name, body = mod_pack.build(BENCH, STATS, STATIC, 100.5)
        self.assertEqual((pack["v"], pack["built"], pack["synergy"]), (1, 100, name))
        self.assertEqual(pack["ruler"]["encounters"]["ENCOUNTER.A"], {"pool": [90, 110], "tiers": [
            {"turns": 3.1, "taken": 6.2, "n": 40, "coop": {"turns": 4, "taken": 5, "n": 6}}, {}]})
        self.assertNotIn("ratings", pack["ruler"])
        solo = pack["lanes"]["solo"]
        self.assertEqual(set(solo), {"chars", "cards", "relics", "picks"})
        self.assertEqual(solo["picks"], {"FOOL": {"cards": {"CARD.A": [1, 2, 5, 6]}, "relics": {}}})
        self.assertEqual(json.loads(body)["basic"], ["CARD.STRIKE"])
        self.assertRegex(name, r"^synergy\.[0-9a-f]{10}\.json$")

    def test_no_game_data_leaves_out_synergy(self):
        pack, name, body = mod_pack.build(BENCH, {}, {}, 0)
        self.assertEqual((name, body, pack["synergy"]), (None, None, None))


class FakeStore:
    def __init__(self, objects):
        self.objects = objects

    def get(self, key):
        return (self.objects[key], 0, "etag", {}) if key in self.objects else None

    def put(self, key, data, metadata, if_match):
        self.objects[key] = data


class Publish(unittest.TestCase):
    def test_writes_both_files_without_steam_ids(self):
        store = FakeStore({benchmark.STATS_KEY: benchmark._pack(STATS)})
        with mock.patch.object(mod_pack, "static_data", return_value=STATIC), \
                contextlib.redirect_stdout(io.StringIO()):
            benchmark.publish_mod_pack(store, BENCH, 100)
            benchmark.publish_mod_pack(store, BENCH, 200)  # the next day replaces the pack
        files = {k: gzip.decompress(v).decode() for k, v in store.objects.items() if k.startswith("mod/v1/")}
        self.assertEqual(len(files), 2)
        pack = json.loads(files[mod_pack.PACK_KEY])
        self.assertEqual(pack["built"], 200)
        self.assertIn(mod_pack.PREFIX + pack["synergy"], files)
        for text in files.values():
            self.assertIsNone(re.search(r"7656119\d{10}", text))

    def test_a_failure_is_logged_not_raised(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            benchmark.publish_mod_pack(FakeStore({}), BENCH, 0)
        self.assertIn("mod_pack_failed", out.getvalue())


if __name__ == "__main__":
    unittest.main()
