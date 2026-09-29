"""Tests for the ingest Lambda's core, with Steam and S3 stubbed out.

    infra\\.venv\\Scripts\\python.exe -m unittest discover infra/tests

The round-trip test uses real .run files from this machine's STS2 history
when there are any, and is skipped otherwise.
"""
import gzip
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "infra" / "lambda" / "ingest")]

import handler  # noqa: E402
import run  # noqa: E402

STEAM_ID = "76561198000000001"
NOW = 1_800_000_000.0
ALLOWED = ["https://slay-my-stats.com/"]


def openid_params(steam_id=STEAM_ID, issued=NOW - 60, nonce_suffix="abc", **overrides):
    stamp = datetime.fromtimestamp(issued, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ident = f"https://steamcommunity.com/openid/id/{steam_id}"
    p = {
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "id_res",
        "openid.op_endpoint": handler.STEAM_OPENID_ENDPOINT,
        "openid.claimed_id": ident,
        "openid.identity": ident,
        "openid.return_to": "https://slay-my-stats.com/upload",
        "openid.response_nonce": stamp + nonce_suffix,
        "openid.assoc_handle": "1234567890",
        "openid.signed": "signed,op_endpoint,claimed_id,identity,return_to,response_nonce,assoc_handle",
        "openid.sig": "c2ln",
    }
    p.update(overrides)
    return p


def steam_says(valid=True):
    calls = []

    def post(params):
        calls.append(params)
        return "ns:http://specs.openid.net/auth/2.0\nis_valid:" + ("true" if valid else "false") + "\n"
    post.calls = calls
    return post


def body_of(*runs):
    return gzip.compress("\n".join(json.dumps(r) for r in runs).encode())


class MemStore:
    def __init__(self):
        self.objects = {}  # key -> (bytes, mtime, etag, meta)
        self.puts = 0
        self.clock = 0.0

    def get(self, key):
        return self.objects.get(key)

    def put(self, key, data, metadata, if_match):
        cur = self.objects.get(key)
        if (cur[2] if cur else None) != if_match:
            raise handler.StoreConflict()
        self.puts += 1
        self.objects[key] = (data, self.clock, f"etag{self.puts}", dict(metadata))

    def delete(self, key):
        self.objects.pop(key, None)

    def json(self, key):
        return json.loads(gzip.decompress(self.objects[key][0]))

    def slug(self, steam_id=STEAM_ID):
        return self.json(handler.id_key(steam_id))["slug"]

    def profile(self, steam_id=STEAM_ID):
        return self.json(handler.blob_key(self.slug(steam_id)))

    def runs(self, steam_id=STEAM_ID):
        return self.profile(steam_id)["runs"]

    def index(self):
        return self.json(handler.INDEX_KEY)["players"]


def named(name):
    return lambda steam_id: name


def minimal_run(start_time, **extra):
    """The smallest raw .run shape parse_run_data accepts."""
    r = {
        "start_time": start_time, "run_time": 1200, "ascension": 3, "win": True,
        "was_abandoned": False, "killed_by_encounter": "NONE.NONE", "seed": "ABC123",
        "build_id": "v0.99.1", "game_mode": "standard",
        "players": [{"character": "CHARACTER.IRONCLAD", "deck": [], "relics": []}],
        "map_point_history": [],
    }
    r.update(extra)
    return r


class VerifyOpenIdTests(unittest.TestCase):
    def verify(self, params, post=None):
        return handler.verify_openid(params, ALLOWED, now=NOW, post=post or steam_says())

    def assertRejected(self, params, code="bad_openid", post=None):
        with self.assertRaises(handler.IngestError) as cm:
            self.verify(params, post)
        self.assertEqual(cm.exception.code, code)

    def test_valid(self):
        post = steam_says()
        self.assertEqual(self.verify(openid_params(), post), STEAM_ID)
        self.assertEqual(post.calls[0]["openid.mode"], "check_authentication")
        self.assertEqual(post.calls[0]["openid.sig"], "c2ln")

    def test_steam_says_invalid(self):
        self.assertRejected(openid_params(), post=steam_says(False))

    def test_wrong_mode(self):
        self.assertRejected(openid_params(**{"openid.mode": "cancel"}))

    def test_wrong_endpoint(self):
        self.assertRejected(openid_params(**{"openid.op_endpoint": "https://evil.example/openid/login"}))

    def test_identity_mismatch(self):
        self.assertRejected(openid_params(**{"openid.identity": "https://steamcommunity.com/openid/id/76561198000000002"}))

    def test_bad_claimed_id(self):
        self.assertRejected(openid_params(**{"openid.claimed_id": "https://steamcommunity.com.evil/openid/id/1",
                                             "openid.identity": "https://steamcommunity.com.evil/openid/id/1"}))

    def test_other_sites_return_to(self):
        # An assertion another site obtained for its own users must not work here.
        self.assertRejected(openid_params(**{"openid.return_to": "https://other-site.example/login"}))
        self.assertRejected(openid_params(**{"openid.return_to": "https://slay-my-stats.com.evil.example/"}))
        self.assertRejected(openid_params(**{"openid.return_to": "https://slay-my-stats.com@evil.example/"}))
        self.assertRejected(openid_params(**{"openid.return_to": "http://slay-my-stats.com/"}))
        self.assertRejected(openid_params(**{"openid.return_to": "garbage"}))

    def test_localhost_port_must_match(self):
        allowed = ["http://localhost:8123"]
        ok = openid_params(**{"openid.return_to": "http://localhost:8123/upload"})
        self.assertEqual(handler.verify_openid(ok, allowed, now=NOW, post=steam_says()), STEAM_ID)
        for bad in ("http://localhost:8123.evil.example/", "http://localhost:9999/"):
            with self.assertRaises(handler.IngestError):
                handler.verify_openid(openid_params(**{"openid.return_to": bad}), allowed, now=NOW, post=steam_says())

    def test_unsigned_return_to(self):
        self.assertRejected(openid_params(**{"openid.signed": "signed,op_endpoint,claimed_id,identity,response_nonce"}))

    def test_expired(self):
        self.assertRejected(openid_params(issued=NOW - 31 * 60), code="signin_expired")

    def test_future_nonce(self):
        self.assertRejected(openid_params(issued=NOW + 10 * 60))

    def test_garbage_nonce(self):
        self.assertRejected(openid_params(**{"openid.response_nonce": "yesterday"}))

    def test_steam_down(self):
        def post(_):
            raise OSError("timed out")
        self.assertRejected(openid_params(), code="steam_unreachable", post=post)

    def test_local_checks_skip_steam(self):
        post = steam_says()
        self.assertRejected(openid_params(**{"openid.mode": "cancel"}), post=post)
        self.assertEqual(post.calls, [])


class BodyTests(unittest.TestCase):
    def test_bad_gzip(self):
        with self.assertRaises(handler.IngestError) as cm:
            list(handler.iter_upload_lines(b"not gzip"))
        self.assertEqual(cm.exception.code, "bad_body")

    def test_truncated(self):
        with self.assertRaises(handler.IngestError):
            list(handler.iter_upload_lines(body_of(minimal_run(1700000000))[:-10]))

    def test_lines_and_blank_lines(self):
        lines = list(handler.iter_upload_lines(gzip.compress(b'{"a":1}\n\n{"b":2}\n')))
        self.assertEqual(lines, [b'{"a":1}', b'{"b":2}'])

    def test_decompression_bomb(self):
        # ~200 KB compressed that inflates to 300 MB: must be cut off, not inflated.
        bomb = gzip.compress(b"\n" * (300 * 1024 * 1024), compresslevel=9)
        with self.assertRaises(handler.IngestError) as cm:
            for _ in handler.iter_upload_lines(bomb):
                pass
        self.assertEqual(cm.exception.code, "too_large")

    def test_huge_line(self):
        with self.assertRaises(handler.IngestError):
            list(handler.iter_upload_lines(gzip.compress(b"x" * (handler.MAX_LINE_BYTES + 10))))


class SafetyTests(unittest.TestCase):
    def test_allows_real_shapes(self):
        self.assertTrue(handler.check_safe({"character": "IRONCLAD", "floors": [1, 2.5, None, True], 3: {"x": "CARD.STRIKE_R"}}))

    def test_rejects_markup(self):
        for bad in ["<img src=x onerror=alert(1)>", "a b", "\"quote", "x" * 81, "é"]:
            self.assertFalse(handler.check_safe({"k": bad}), bad)
            self.assertFalse(handler.check_safe({bad: 1}), bad)

    def test_rejects_non_finite_and_huge(self):
        self.assertFalse(handler.check_safe(float("nan")))
        self.assertFalse(handler.check_safe(float("inf")))
        self.assertFalse(handler.check_safe(2 ** 60))

    def test_rejects_deep_nesting(self):
        v = 1
        for _ in range(handler.MAX_DEPTH + 2):
            v = [v]
        self.assertFalse(handler.check_safe(v))


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.store = MemStore()

    def ingest(self, body, now=NOW, name="Mr. Bean!", **param_kw):
        return handler.ingest(openid_params(issued=now - 60, **param_kw), body, self.store, ALLOWED,
                              now=now, post=steam_says(), lookup_name=named(name))

    def test_first_upload_then_dedupe(self):
        res = self.ingest(body_of(minimal_run(1700000002), minimal_run(1700000001), minimal_run(1700000001)))
        self.assertEqual((res["added"], res["duplicates"], res["rejected"], res["total"]), (2, 1, 0, 2))
        self.assertEqual([r["ts"] for r in self.store.runs()], [1700000001, 1700000002])
        # steam_id comes from the verified sign-in, never from the upload.
        self.assertTrue(all(r.get("steam_id", STEAM_ID) == STEAM_ID for r in self.store.runs()))

        self.store.clock = NOW
        res = self.ingest(body_of(minimal_run(1700000001), minimal_run(1700000003)),
                          now=NOW + 120, nonce_suffix="second")
        self.assertEqual((res["added"], res["duplicates"], res["total"]), (1, 1, 3))
        self.assertEqual([r["ts"] for r in self.store.runs()], [1700000001, 1700000002, 1700000003])

    def test_stored_blob_is_gzip_json(self):
        self.ingest(body_of(minimal_run(1700000001)))
        blob = json.loads(gzip.decompress(self.store.objects["users/mrbean.json.gz"][0]))
        self.assertEqual((blob["v"], blob["name"]), (1, "Mr. Bean!"))

    def test_nothing_new_does_not_write(self):
        self.ingest(body_of(minimal_run(1700000001)))
        puts = self.store.puts
        self.store.clock = NOW
        res = self.ingest(body_of(minimal_run(1700000001)), now=NOW + 120, nonce_suffix="again")
        self.assertEqual((res["added"], res["duplicates"], res["slug"]), (0, 1, "mrbean"))
        self.assertEqual(self.store.puts, puts)

    def test_slugify(self):
        for name, slug in [("Mr. Bean!", "mrbean"), ("Zoë-99", "zoe99"), ("日本語", "player"),
                           ("a" * 80, "a" * 32), ("ＦＵＬＬ", "full")]:
            self.assertEqual(handler.slugify(name), slug, name)
        self.assertEqual(handler.clean_name("  x​\n y "), "x y")
        self.assertIsNone(handler.clean_name(" \t"))

    def test_first_upload_creates_profile_record_and_index(self):
        res = self.ingest(body_of(minimal_run(1700000001)))
        self.assertEqual((res["slug"], res["name"]), ("mrbean", "Mr. Bean!"))
        self.assertEqual(self.store.slug(), "mrbean")
        self.assertEqual(self.store.index(),
                         [{"slug": "mrbean", "name": "Mr. Bean!", "runs": 1, "updated": int(NOW)}])

    def test_steam_id_never_public(self):
        self.ingest(body_of(minimal_run(1700000001)))
        self.assertNotIn("steamId", self.ingest(body_of(), nonce_suffix="x", now=NOW + 120))
        for key, (data, *_rest) in self.store.objects.items():
            if key.startswith("users/"):
                self.assertNotIn(STEAM_ID, key)
                self.assertNotIn(STEAM_ID.encode(), gzip.decompress(data))

    def test_same_name_gets_numbered_slug(self):
        self.ingest(body_of(minimal_run(1700000001)))
        other = "76561198000000002"
        res = self.ingest(body_of(minimal_run(1700000001)), steam_id=other, name="mr bean")
        self.assertEqual(res["slug"], "mrbean-2")
        res = self.ingest(body_of(minimal_run(1700000001)), steam_id="76561198000000003", name="MRBEAN")
        self.assertEqual(res["slug"], "mrbean-3")
        self.assertEqual([p["slug"] for p in self.store.index()], ["mrbean", "mrbean-2", "mrbean-3"])

    def test_slug_taken_but_not_yet_indexed(self):
        # Another new player created "mrbean" but hasn't updated the index yet.
        self.store.put("users/mrbean.json.gz", b"x", {}, None)
        self.assertEqual(self.ingest(body_of(minimal_run(1700000001)))["slug"], "mrbean-2")
        self.assertEqual(self.store.objects["users/mrbean.json.gz"][0], b"x")

    def test_rename_keeps_slug(self):
        self.ingest(body_of(minimal_run(1700000001)))
        self.store.clock = NOW
        res = self.ingest(body_of(minimal_run(1700000002)), now=NOW + 120, nonce_suffix="2", name="Sir Bean")
        self.assertEqual((res["slug"], res["name"]), ("mrbean", "Sir Bean"))
        self.assertEqual(self.store.profile()["name"], "Sir Bean")
        self.assertEqual([(p["slug"], p["name"], p["runs"]) for p in self.store.index()], [("mrbean", "Sir Bean", 2)])

    def test_new_player_needs_a_name(self):
        with self.assertRaises(handler.IngestError) as cm:
            self.ingest(body_of(minimal_run(1700000001)), name=None)
        self.assertEqual(cm.exception.code, "steam_unreachable")
        self.assertEqual(self.store.objects, {})

    def test_returning_player_keeps_name_if_steam_is_down(self):
        self.ingest(body_of(minimal_run(1700000001)))
        self.store.clock = NOW
        res = self.ingest(body_of(minimal_run(1700000002)), now=NOW + 120, nonce_suffix="2", name=None)
        self.assertEqual((res["added"], res["name"]), (1, "Mr. Bean!"))

    def test_racing_first_uploads_leave_no_orphan(self):
        # Between our read of ids/<steamid> and our write, another tab's first
        # upload for the same player recorded a different slug.
        class Racy(MemStore):
            def put(self, key, data, metadata, if_match):
                if key == handler.id_key(STEAM_ID) and key not in self.objects:
                    super().put(key, handler._pack({"slug": "elsewhere"}), {}, None)
                super().put(key, data, metadata, if_match)
        self.store = Racy()
        with self.assertRaises(handler.IngestError) as cm:
            self.ingest(body_of(minimal_run(1700000001)))
        self.assertEqual(cm.exception.code, "conflict")
        self.assertNotIn("users/mrbean.json.gz", self.store.objects)

    def stats(self):
        return self.store.json(handler.STATS_KEY)

    def test_stats_count_each_run_once(self):
        self.ingest(body_of(minimal_run(1700000001), minimal_run(1700000002, win=False)))
        self.store.clock = NOW
        self.ingest(body_of(minimal_run(1700000001), minimal_run(1700000003, run_time=900)),
                    now=NOW + 120, nonce_suffix="second")
        s = self.stats()
        solo = s["solo"]
        self.assertEqual((s["allRuns"], solo["runs"], solo["wins"], solo["minutes"]), (3, 3, 2, 55))
        self.assertEqual(solo["chars"], {"IRONCLAD": [3, 2]})
        self.assertEqual(solo["records"]["fastestWin"]["mins"], 15)
        self.assertEqual(solo["records"]["fastestWin"]["slug"], "mrbean")

    def test_stats_split_multiplayer_and_leave_out_daily(self):
        second = {"character": "CHARACTER.SILENT", "deck": [], "relics": []}
        players = [{"character": "CHARACTER.IRONCLAD", "deck": [], "relics": []}, second]
        self.ingest(body_of(minimal_run(1700000001), minimal_run(1700000002, players=players, win=False),
                            minimal_run(1700000003, game_mode="daily")))
        s = self.stats()
        self.assertEqual((s["allRuns"], s["solo"]["runs"], s["multi"]["runs"], s["multi"]["wins"]), (3, 1, 1, 0))

    def test_stats_retry_on_conflict(self):
        class Busy(MemStore):
            clashes = 2
            def put(self, key, data, metadata, if_match):
                if key == handler.STATS_KEY and self.clashes:
                    self.clashes -= 1
                    raise handler.StoreConflict()
                super().put(key, data, metadata, if_match)
        self.store = Busy()
        self.ingest(body_of(minimal_run(1700000001)))
        self.assertEqual(self.stats()["solo"]["runs"], 1)

    def test_tallies_add_up_to_a_recount(self):
        run = lambda ts, **kw: handler.run.parse_run_data(minimal_run(ts, **kw))
        a = [run(1700000001), run(1700000002, win=False)]
        b = [run(1700000003, run_time=900), run(1700000004, run_time=3000)]
        merged = handler.merge_stats(handler.merge_stats(handler.empty_stats(), handler.tally(a, "x")),
                                     handler.tally(b, "y"))
        whole = handler.merge_stats(handler.empty_stats(), handler.tally(a + b, "y"))
        self.assertEqual(merged, whole)
        self.assertEqual(merged["solo"]["records"]["fastestWin"], whole["solo"]["records"]["fastestWin"])
        self.assertEqual(merged["solo"]["records"]["fastestWin"]["mins"], 15)

    def test_cooldown(self):
        self.store.clock = NOW
        self.ingest(body_of(minimal_run(1700000001)))
        with self.assertRaises(handler.IngestError) as cm:
            self.ingest(body_of(minimal_run(1700000002)), now=NOW + 10, nonce_suffix="soon")
        self.assertEqual(cm.exception.status, 429)

    def test_replayed_signin(self):
        self.store.clock = NOW - 1000
        self.ingest(body_of(minimal_run(1700000001)))
        with self.assertRaises(handler.IngestError) as cm:
            self.ingest(body_of(minimal_run(1700000002)))
        self.assertEqual(cm.exception.code, "signin_used")

    def test_bad_runs_rejected_not_fatal(self):
        res = self.ingest(body_of(
            minimal_run(1700000001),
            minimal_run(1700000002, seed="<script>alert(1)</script>"),
            minimal_run(12),  # implausible start time
            [1, 2, 3],
            {"no": "fields"},
        ) + gzip.compress(b"\n{not json"))
        self.assertEqual((res["added"], res["rejected"]), (1, 5))

    def test_conflict(self):
        # Another write to this profile lands between our read and our put.
        class Racy(MemStore):
            racing = False
            def put(self, key, *a):
                if self.racing:
                    raise handler.StoreConflict()
                super().put(key, *a)
        self.store = Racy()
        self.ingest(body_of(minimal_run(1700000001)))
        self.store.clock, self.store.racing = NOW, True
        with self.assertRaises(handler.IngestError) as cm:
            self.ingest(body_of(minimal_run(1700000002)), now=NOW + 120, nonce_suffix="2")
        self.assertEqual(cm.exception.status, 409)

    def test_too_many_runs(self):
        old = handler.MAX_RUNS_PER_UPLOAD
        handler.MAX_RUNS_PER_UPLOAD = 2
        try:
            with self.assertRaises(handler.IngestError) as cm:
                self.ingest(body_of(*(minimal_run(1700000000 + i) for i in range(3))))
            self.assertEqual(cm.exception.status, 413)
        finally:
            handler.MAX_RUNS_PER_UPLOAD = old


class DirStoreTests(unittest.TestCase):
    def test_roundtrip_and_conflict(self):
        with tempfile.TemporaryDirectory() as d:
            store = handler.DirStore(d)
            key = handler.blob_key("mrbean")
            self.assertIsNone(store.get(key))
            store.put(key, b"one", {"last-nonce": "n1"}, None)
            data, _, etag, meta = store.get(key)
            self.assertEqual((data, meta), (b"one", {"last-nonce": "n1"}))
            with self.assertRaises(handler.StoreConflict):
                store.put(key, b"two", {}, None)
            store.put(key, b"two", {}, etag)
            self.assertEqual(store.get(key)[0], b"two")


class LambdaHandlerTests(unittest.TestCase):
    def test_event_plumbing(self):
        import base64
        import urllib.parse
        store = MemStore()
        handler._store = store
        orig_post = handler._post_to_steam
        orig_verify = handler.verify_openid
        handler.verify_openid = lambda p, a, now=None, post=None: orig_verify(p, a, now=NOW, post=steam_says())
        orig_time = handler.time.time
        handler.time.time = lambda: NOW
        orig_lookup = handler.lookup_steam_name
        handler.lookup_steam_name = named("Mr. Bean!")
        try:
            import os
            os.environ["ALLOWED_RETURN_TO"] = ",".join(ALLOWED)
            event = {
                "requestContext": {"http": {"method": "POST"}},
                "rawQueryString": urllib.parse.urlencode(openid_params()),
                "body": base64.b64encode(body_of(minimal_run(1700000001))).decode(),
                "isBase64Encoded": True,
            }
            resp = handler.lambda_handler(event, None)
            self.assertEqual(resp["statusCode"], 200, resp["body"])
            self.assertEqual(json.loads(resp["body"])["added"], 1)
            self.assertEqual(json.loads(resp["body"])["slug"], "mrbean")

            event["requestContext"]["http"]["method"] = "GET"
            self.assertEqual(handler.lambda_handler(event, None)["statusCode"], 405)
        finally:
            handler._store = None
            handler._post_to_steam = orig_post
            handler.verify_openid = orig_verify
            handler.time.time = orig_time
            handler.lookup_steam_name = orig_lookup


class RealHistoryTests(unittest.TestCase):
    """Uploading real .run files must store exactly what run.py computes locally."""

    def test_matches_local_parse(self):
        dirs = run.find_history_dirs()
        if not dirs:
            self.skipTest("no local STS2 history")
        files = sorted(dirs[0].glob("*.run"), key=lambda p: int(p.stem))
        steam_id = dirs[0].parts[-4]
        body = gzip.compress("\n".join(json.dumps(json.loads(f.read_text(encoding="utf-8"))) for f in files).encode())

        store = MemStore()
        res = handler.ingest(openid_params(steam_id=steam_id), body, store, ALLOWED, now=NOW, post=steam_says(),
                             lookup_name=named("Me"))
        self.assertEqual(res["rejected"], 0, res)
        expected = sorted((run.parse_run(f) for f in files), key=lambda r: r["ts"])
        self.assertEqual(store.runs(steam_id), json.loads(json.dumps(expected)))


if __name__ == "__main__":
    unittest.main()
