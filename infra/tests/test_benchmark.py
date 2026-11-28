import contextlib
import gzip
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambda" / "ingest"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import benchmark

KEY = "raw/76561198000000001/20261101T000000Z-abcdefghijklmnop.ndjson.gz"
RUN = {"start_time": 1, "map_point_history": [[]], "players": [{}]}


def gz(*lines):
    return gzip.compress(b"\n".join(lines) + b"\n")


class FakeStore:
    def __init__(self, objects):
        self.objects = objects

    def get(self, key):
        return (self.objects[key], {}, "etag") if key in self.objects else None


class UploadFights(unittest.TestCase):
    def test_showcase_reads_the_uploading_players_deck_and_boss_damage(self):
        uploader = "76561198000000001"
        boss = {"map_point_type": "boss", "player_stats": [{"damage_taken": 7}, {"damage_taken": 0}],
                "rooms": [{"model_id": "ENCOUNTER.A"}]}
        raw = {**RUN, "win": True, "players": [
            {"id": "76561198000000002", "character": "CHARACTER.DEFECT", "deck": [{"id": "CARD.A"}]},
            {"id": uploader, "character": "CHARACTER.SILENT", "deck": [{"id": "CARD.B"}, {"id": "CARD.C"}]},
        ], "map_point_history": [[], [], [boss]]}
        facts = {}
        with mock.patch.object(benchmark, "run_fights", return_value=[[{"each": [14, 3]}]]):
            benchmark.upload_fights(FakeStore({KEY: gz(json.dumps(raw).encode())}), {uploader: {1}}, KEY, facts)
        self.assertEqual(facts[(uploader, 1)]["slot"], 1)
        self.assertEqual(facts[(uploader, 1)]["char"], "CHARACTER.SILENT")
        self.assertEqual(facts[(uploader, 1)]["deck"], 2)
        self.assertTrue(facts[(uploader, 1)]["boss_no_damage"])

    def test_coop_unmatched_uploader_does_not_qualify_for_zero_boss_damage(self):
        uploader = "76561198000000001"
        boss = {"map_point_type": "boss", "player_stats": [{"damage_taken": 0}, {"damage_taken": 0}],
                "rooms": [{"model_id": "ENCOUNTER.A"}]}
        raw = {**RUN, "win": True, "players": [{}, {}], "map_point_history": [[], [], [boss]]}
        facts = {}
        benchmark.upload_fights(FakeStore({KEY: gz(json.dumps(raw).encode())}), {uploader: {1}}, KEY, facts)
        self.assertFalse(facts[(uploader, 1)]["boss_no_damage"])

    def fights(self, body, key=KEY):
        published = {"76561198000000001": {1}}
        with mock.patch.object(benchmark, "run_fights", return_value=[["f"]]):
            return benchmark.upload_fights(FakeStore({key: body}), published, key)

    def test_long_run_is_read(self):
        # Prod's benchmark failed on 11-22 and 11-23 on mod runs over 4 MB.
        big = json.dumps({**RUN, "pad": "x" * (12 * 1024 * 1024)}).encode()
        self.assertEqual(self.fights(gz(big), KEY.replace(".ndjson", ".mod.ndjson")),
                         {("76561198000000001", 1): ["f"]})

    def test_bad_upload_is_skipped_and_logged(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertIsNone(self.fights(b"not gzip"))
        self.assertIn(KEY, out.getvalue())


class Refresh(unittest.TestCase):
    def test_only_zero_damage_boss_wins_are_published_in_boss_tab(self):
        uploader = "76561198000000001"
        now = 100 * 86400
        boss = {"map_point_type": "boss", "player_stats": [{"damage_taken": 0}],
                "rooms": [{"model_id": "ENCOUNTER.A"}]}
        raw = {"start_time": now - 1, "win": True, "players": [{"character": "CHARACTER.SILENT"}],
               "map_point_history": [[], [], [boss]]}
        damaged_boss = {**boss, "player_stats": [{"damage_taken": 4, "hp_healed": 4}],
                        "rooms": [{"model_id": "ENCOUNTER.A", "turns_taken": 1}]}
        damaged_run = {**raw, "start_time": now - 2, "map_point_history": [[], [], [damaged_boss]]}
        storage = FakeStore({
            KEY: gz(json.dumps(raw).encode(), json.dumps(damaged_run).encode()),
            benchmark.id_key(uploader): benchmark._pack({"slug": "player"}),
            benchmark.blob_key("player"): benchmark._pack({"name": "Player", "months": {"2026-11": [now - 1, now - 2]}}),
        })
        with mock.patch.object(benchmark, "_get_store") as gs, \
                mock.patch.object(benchmark.time, "time", return_value=now), \
                mock.patch.object(benchmark, "cuts_of", return_value={}), \
                contextlib.redirect_stdout(io.StringIO()):
            store = gs.return_value
            store.get.side_effect = storage.get
            store.list.return_value = [KEY]
            benchmark.refresh({}, None)
        outputs = {call.args[0]: call.args[1] for call in store.put.call_args_list}
        saved = benchmark._unpack(outputs[benchmark.SHOWCASE_KEY])
        self.assertEqual([(r["slug"], r["ts"]) for r in saved["boss_no_damage"]], [("player", now - 1)])
        self.assertEqual(saved["modes"]["solo"]["boss_no_damage"], saved["boss_no_damage"])
        self.assertEqual(saved["modes"]["multiplayer"]["boss_no_damage"], [])

    def test_skipped_uploads_are_counted(self):
        out = io.StringIO()
        with mock.patch.object(benchmark, "_get_store") as gs, \
                mock.patch.object(benchmark, "published_starts", return_value={1}), \
                mock.patch.object(benchmark, "upload_fights", side_effect=[None, {("a", 1): ["f"]}]), \
                mock.patch.object(benchmark, "table", return_value={}), \
                mock.patch.object(benchmark, "cuts_of", return_value={}), \
                mock.patch.object(benchmark, "rating_mix", return_value={}), \
                contextlib.redirect_stdout(out):
            store = gs.return_value
            store.get.return_value = None
            store.list.return_value = [
                "raw/76561198000000001/20261101T000000Z-aaaaaaaaaaaaaaaa.ndjson.gz",
                "raw/76561198000000001/20261102T000000Z-bbbbbbbbbbbbbbbb.ndjson.gz"]
            benchmark.refresh({}, None)
        self.assertEqual(json.loads(out.getvalue().splitlines()[-1])["skipped_uploads"], 1)

    def test_the_rating_mix_is_published_with_the_benchmark(self):
        mix = {"CHARACTER.A": {"0": [1, 2, 3, 4]}}
        with mock.patch.object(benchmark, "_get_store") as gs, \
                mock.patch.object(benchmark, "published_starts", return_value={1}), \
                mock.patch.object(benchmark, "upload_fights", return_value={("a", 1): ["f"]}), \
                mock.patch.object(benchmark, "table", return_value={}), \
                mock.patch.object(benchmark, "cuts_of", return_value={"run": 1}), \
                mock.patch.object(benchmark, "rating_mix", return_value=mix), \
                mock.patch.object(benchmark, "publish_showcase"), \
                contextlib.redirect_stdout(io.StringIO()):
            store = gs.return_value
            store.get.return_value = None
            store.list.return_value = ["raw/76561198000000001/20261101T000000Z-aaaaaaaaaaaaaaaa.ndjson.gz"]
            benchmark.refresh({}, None)
        key, body = store.put.call_args_list[0].args[:2]
        self.assertEqual(key, benchmark.BENCHMARK_KEY)
        self.assertEqual(benchmark._unpack(body)["ratings"], mix)


if __name__ == "__main__":
    unittest.main()
