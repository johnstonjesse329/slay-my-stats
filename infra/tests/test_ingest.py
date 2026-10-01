"""Tests for the ingest Lambda's core, with Steam and S3 stubbed out.

    infra\\.venv\\Scripts\\python.exe -m unittest discover infra/tests

The round-trip test uses real .run files from this machine's STS2 history
when there are any, and is skipped otherwise.
"""
import gzip
import json
import os
import sys
import tempfile
import unittest
import urllib.parse
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

    def list(self, prefix):
        return [k for k in self.objects if k.startswith(prefix)]

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
        # A small body that inflates past the cap: must be cut off, not inflated.
        # (The cap is lowered here so the test doesn't inflate gigabytes.)
        bomb = gzip.compress(b"\n" * (30 * 1024 * 1024), compresslevel=9)
        old = handler.MAX_DECOMPRESSED_BYTES
        handler.MAX_DECOMPRESSED_BYTES = 10 * 1024 * 1024
        try:
            with self.assertRaises(handler.IngestError) as cm:
                for _ in handler.iter_upload_lines(bomb):
                    pass
        finally:
            handler.MAX_DECOMPRESSED_BYTES = old
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


def fake_presign(key, max_bytes, expires):
    return {"url": "https://s3.example/", "fields": {"key": key, "Content-Type": "application/gzip"}}


class Uploads:
    """Drives an upload end to end: authorize, the browser's POST to S3 (a
    plain put here), then the S3 event's processing."""
    def setUp(self):
        self.store = MemStore()

    def authorize(self, now=NOW, ip="203.0.113.7", issued=None, **param_kw):
        issued = now - 60 if issued is None else issued
        return handler.authorize(openid_params(issued=issued, **param_kw), ip, self.store, ALLOWED,
                                 fake_presign, now=now, post=steam_says())

    def process(self, key, now=NOW, name="Mr. Bean!"):
        return handler.process_upload(key, self.store, now=now, lookup_name=named(name))

    def ingest(self, body, now=NOW, name="Mr. Bean!", ip="203.0.113.7", **param_kw):
        auth = self.authorize(now=now, ip=ip, **param_kw)
        key = auth["fields"]["key"]
        self.store.put(key, body, {}, None)
        self.last_key = key
        return self.process(key, now=now, name=name)

    def stats(self):
        return self.store.json(handler.STATS_KEY)


class AuthorizeTests(Uploads, unittest.TestCase):
    def assertRefused(self, code, **kw):
        with self.assertRaises(handler.IngestError) as cm:
            self.authorize(**kw)
        self.assertEqual(cm.exception.code, code)

    def test_hands_out_one_raw_key(self):
        auth = self.authorize()
        self.assertRegex(auth["fields"]["key"], rf"^raw/{STEAM_ID}/\d{{8}}T\d{{6}}Z-[A-Za-z0-9_-]{{16}}\.ndjson\.gz$")
        self.assertEqual(auth["fields"]["key"], handler.raw_key(STEAM_ID, auth["uploadId"], NOW))
        self.assertEqual((auth["maxBytes"], auth["slug"]), (handler.UPLOAD_MAX_BYTES, None))
        self.assertNotEqual(auth["uploadId"], self.authorize(now=NOW + 120, nonce_suffix="2")["uploadId"])

    def test_returns_known_slug(self):
        self.ingest(body_of(minimal_run(1700000001)))
        self.assertEqual(self.authorize(now=NOW + 120, nonce_suffix="2")["slug"], "mrbean")

    def test_bad_signin(self):
        with self.assertRaises(handler.IngestError):
            handler.authorize(openid_params(), "1.2.3.4", self.store, ALLOWED, fake_presign, now=NOW,
                              post=steam_says(False))

    def test_cooldown(self):
        self.authorize()
        self.assertRefused("cooldown", now=NOW + 10, nonce_suffix="soon")
        self.authorize(now=NOW + 61, nonce_suffix="later")

    def test_signin_reused_after_cooldown(self):
        self.authorize()
        self.authorize(now=NOW + 120, issued=NOW - 60)

    def test_ip_limit(self):
        for i in range(handler.IP_UPLOADS_PER_HOUR):
            self.authorize(steam_id=f"7656119800000001{i}", now=NOW + i)
        self.assertRefused("rate_limited", steam_id="76561198000000020", now=NOW + 10)
        # Another address is unaffected, and the window slides.
        self.authorize(steam_id="76561198000000021", ip="198.51.100.1", now=NOW + 10)
        self.authorize(steam_id="76561198000000022", now=NOW + handler.IP_WINDOW_SECONDS + 1)

    def test_ip_limit_is_per_ipv6_block(self):
        self.assertEqual(handler.ip_limit_key("2001:db8:1:2::1"), handler.ip_limit_key("2001:db8:1:2:ffff::9"))
        self.assertNotEqual(handler.ip_limit_key("2001:db8:1:2::1"), handler.ip_limit_key("2001:db8:1:3::1"))
        self.assertNotIn("203.0.113.7", handler.ip_limit_key("203.0.113.7"))

    def test_ip_limit_checked_before_steam(self):
        for i in range(handler.IP_UPLOADS_PER_HOUR):
            self.authorize(steam_id=f"7656119800000001{i}", now=NOW + i)
        post = steam_says()
        with self.assertRaises(handler.IngestError):
            handler.authorize(openid_params(steam_id="76561198000000020"), "203.0.113.7", self.store,
                              ALLOWED, fake_presign, now=NOW + 10, post=post)
        self.assertEqual(post.calls, [])


class ProcessTests(Uploads, unittest.TestCase):
    def result(self, key=None):
        m = handler.RAW_KEY_RE.match(key or self.last_key)
        return self.store.json(handler.result_key(m.group(3)))

    def test_first_upload_then_dedupe(self):
        res = self.ingest(body_of(minimal_run(1700000002), minimal_run(1700000001), minimal_run(1700000001)))
        self.assertEqual((res["added"], res["duplicates"], res["rejected"], res["total"]), (2, 0, 0, 2))
        self.assertEqual([r["ts"] for r in self.store.runs()], [1700000001, 1700000002])
        self.assertEqual(self.result(), res)
        self.assertEqual(res["status"], "done")

        res = self.ingest(body_of(minimal_run(1700000001), minimal_run(1700000003)),
                          now=NOW + 120, nonce_suffix="second")
        self.assertEqual((res["added"], res["duplicates"], res["total"]), (1, 1, 3))
        self.assertEqual([r["ts"] for r in self.store.runs()], [1700000001, 1700000002, 1700000003])

    def test_raw_upload_is_kept(self):
        body = body_of(minimal_run(1700000001))
        self.ingest(body)
        self.assertEqual(self.store.objects[self.last_key][0], body)

    def test_stored_blob_is_gzip_json(self):
        self.ingest(body_of(minimal_run(1700000001)))
        blob = json.loads(gzip.decompress(self.store.objects["users/mrbean.json.gz"][0]))
        self.assertEqual((blob["v"], blob["name"], blob["noRaw"], blob["parser"]),
                         (1, "Mr. Bean!", [], run.PARSER_VERSION))

    def test_resent_run_is_reparsed(self):
        self.ingest(body_of(minimal_run(1700000001)))
        res = self.ingest(body_of(minimal_run(1700000001, ascension=9)), now=NOW + 120, nonce_suffix="2")
        self.assertEqual((res["added"], res["duplicates"]), (0, 1))
        self.assertEqual(self.store.runs()[0]["asc"], 9)
        self.assertEqual(self.stats()["allRuns"], 1)  # counted once

    def test_nothing_new_does_not_write_profile(self):
        self.ingest(body_of(minimal_run(1700000001)))
        before = self.store.objects["users/mrbean.json.gz"]
        res = self.ingest(body_of(minimal_run(1700000001)), now=NOW + 120, nonce_suffix="again")
        self.assertEqual((res["added"], res["duplicates"], res["slug"]), (0, 1, "mrbean"))
        self.assertIs(self.store.objects["users/mrbean.json.gz"], before)

    def test_legacy_profile_catch_up(self):
        # A profile from before raw uploads: no noRaw key, so none of its runs
        # have a raw copy until they're sent again.
        runs = [handler.run.parse_run_data(minimal_run(ts), steam_id=STEAM_ID) for ts in (1700000001, 1700000002)]
        handler.save_profile(self.store, STEAM_ID, None, None, "Mr. Bean!", runs, {}, NOW)
        self.assertNotIn("noRaw", self.store.profile())
        self.ingest(body_of(minimal_run(1700000003)))
        self.assertEqual(self.store.profile()["noRaw"], [1700000001, 1700000002])
        self.ingest(body_of(minimal_run(1700000001), minimal_run(1700000002)), now=NOW + 120, nonce_suffix="2")
        self.assertEqual(self.store.profile()["noRaw"], [])
        self.assertEqual(len(self.store.runs()), 3)

    def test_rejected_runs_keep_the_upload(self):
        res = self.ingest(body_of(
            minimal_run(1700000001),
            minimal_run(1700000002, seed="<script>alert(1)</script>"),
            minimal_run(12),  # implausible start time
            [1, 2, 3],
            {"no": "fields"},
        ) + gzip.compress(b"\n{not json"))
        self.assertEqual((res["added"], res["rejected"]), (1, 5))
        self.assertIn(self.last_key, self.store.objects)

    def test_unparseable_run_shaped_upload_is_kept(self):
        # Looks like runs, but the parser can't take them: maybe the parser's
        # fault, so the upload stays for a rebuild after a fix.
        res = self.ingest(body_of(minimal_run(12), minimal_run(13)))
        self.assertEqual((res["status"], res["added"], res["rejected"]), ("done", 0, 2))
        self.assertIn(self.last_key, self.store.objects)
        self.assertNotIn(handler.id_key(STEAM_ID), self.store.objects)  # no empty profile

    def test_junk_is_deleted(self):
        for i, body in enumerate([b"not gzip", body_of({"no": "fields"}, [1]), body_of()]):
            res = self.ingest(body, now=NOW + 120 * i, nonce_suffix=str(i))
            self.assertEqual(res["status"], "failed", body)
            self.assertNotIn(self.last_key, self.store.objects)
            self.assertEqual(self.result()["status"], "failed")
        self.assertEqual(self.result()["error"], "no_runs")

    def test_other_keys_ignored(self):
        self.store.put("raw/not-a-steam-id/x.ndjson.gz", b"x", {}, None)
        self.assertIsNone(self.process("raw/not-a-steam-id/x.ndjson.gz"))
        self.assertIsNone(self.process(handler.raw_key(STEAM_ID, "A" * 16, NOW)))  # already gone

    def test_first_upload_creates_profile_record_and_index(self):
        res = self.ingest(body_of(minimal_run(1700000001)))
        self.assertEqual((res["slug"], res["name"]), ("mrbean", "Mr. Bean!"))
        self.assertEqual(self.store.slug(), "mrbean")
        self.assertEqual(self.store.index(),
                         [{"slug": "mrbean", "name": "Mr. Bean!", "runs": 1, "updated": int(NOW)}])

    def test_steam_id_never_public(self):
        self.ingest(body_of(minimal_run(1700000001)))
        self.assertNotIn(STEAM_ID, json.dumps(self.authorize(now=NOW + 120, nonce_suffix="x")["slug"]))
        for key, (data, *_rest) in self.store.objects.items():
            if key.startswith("users/"):
                self.assertNotIn(STEAM_ID, key)
                self.assertNotIn(STEAM_ID.encode(), gzip.decompress(data))

    def test_slugify(self):
        for name, slug in [("Mr. Bean!", "mrbean"), ("Zoë-99", "zoe99"), ("日本語", "player"),
                           ("a" * 80, "a" * 32), ("ＦＵＬＬ", "full")]:
            self.assertEqual(handler.slugify(name), slug, name)
        self.assertEqual(handler.clean_name("  x​\n y "), "x y")
        self.assertIsNone(handler.clean_name(" \t"))

    def test_same_name_gets_numbered_slug(self):
        self.ingest(body_of(minimal_run(1700000001)))
        res = self.ingest(body_of(minimal_run(1700000001)), steam_id="76561198000000002", name="mr bean")
        self.assertEqual(res["slug"], "mrbean-2")
        res = self.ingest(body_of(minimal_run(1700000001)), steam_id="76561198000000003", name="MRBEAN")
        self.assertEqual(res["slug"], "mrbean-3")
        self.assertEqual([p["slug"] for p in self.store.index()], ["mrbean", "mrbean-2", "mrbean-3"])

    def test_slug_taken_but_not_yet_indexed(self):
        self.store.put("users/mrbean.json.gz", b"x", {}, None)
        self.assertEqual(self.ingest(body_of(minimal_run(1700000001)))["slug"], "mrbean-2")
        self.assertEqual(self.store.objects["users/mrbean.json.gz"][0], b"x")

    def test_rename_keeps_slug(self):
        self.ingest(body_of(minimal_run(1700000001)))
        res = self.ingest(body_of(minimal_run(1700000002)), now=NOW + 120, nonce_suffix="2", name="Sir Bean")
        self.assertEqual((res["slug"], res["name"]), ("mrbean", "Sir Bean"))
        self.assertEqual([(p["slug"], p["name"], p["runs"]) for p in self.store.index()], [("mrbean", "Sir Bean", 2)])

    def test_new_player_without_name_is_retried(self):
        with self.assertRaises(handler.IngestError) as cm:
            self.ingest(body_of(minimal_run(1700000001)), name=None)
        self.assertEqual(cm.exception.status, 502)  # the Lambda retries it
        self.assertIn(self.last_key, self.store.objects)
        self.assertNotIn(handler.id_key(STEAM_ID), self.store.objects)
        res = self.process(self.last_key)
        self.assertEqual((res["added"], res["slug"]), (1, "mrbean"))

    def test_returning_player_keeps_name_if_steam_is_down(self):
        self.ingest(body_of(minimal_run(1700000001)))
        res = self.ingest(body_of(minimal_run(1700000002)), now=NOW + 120, nonce_suffix="2", name=None)
        self.assertEqual((res["added"], res["name"]), (1, "Mr. Bean!"))

    def test_redelivered_event_counts_once(self):
        self.ingest(body_of(minimal_run(1700000001), minimal_run(1700000002)))
        again = self.process(self.last_key)
        self.assertEqual((again["added"], again["duplicates"]), (0, 2))
        self.assertEqual(self.stats()["allRuns"], 2)

    def test_racing_upload_is_merged_not_lost(self):
        # Another upload's write lands between our read and our put; the
        # merge is redone on top of it.
        self.ingest(body_of(minimal_run(1700000001)))
        store = self.store

        class Racy(MemStore):
            pass
        racy = Racy()
        racy.objects, racy.puts = store.objects, store.puts
        orig_put = racy.put
        state = {"raced": False}

        def put(key, data, metadata, if_match):
            if key == "users/mrbean.json.gz" and not state["raced"]:
                state["raced"] = True
                other = [handler.run.parse_run_data(minimal_run(ts), steam_id=STEAM_ID)
                         for ts in (1700000001, 1700000009)]
                handler.save_profile(racy, STEAM_ID, "mrbean", racy.objects[key][2], "Mr. Bean!", other, {}, NOW,
                                     no_raw=[])
            orig_put(key, data, metadata, if_match)
        racy.put = put
        self.store = racy
        self.ingest(body_of(minimal_run(1700000002)), now=NOW + 120, nonce_suffix="2")
        self.assertEqual([r["ts"] for r in racy.runs()], [1700000001, 1700000002, 1700000009])

    def test_racing_first_uploads_leave_no_orphan(self):
        class Racy(MemStore):
            def put(self, key, data, metadata, if_match):
                if key == handler.id_key(STEAM_ID) and key not in self.objects and not getattr(self, "done", 0):
                    self.done = 1
                    super().put(key, handler._pack({"slug": "elsewhere"}), {}, None)
                super().put(key, data, metadata, if_match)
        self.store = Racy()
        self.ingest(body_of(minimal_run(1700000001)))
        self.assertNotIn("users/mrbean.json.gz", self.store.objects)
        self.assertIn("users/elsewhere.json.gz", self.store.objects)

    def test_profile_cap(self):
        old = handler.MAX_RUNS_TOTAL
        handler.MAX_RUNS_TOTAL = 2
        try:
            res = self.ingest(body_of(*(minimal_run(1700000000 + i) for i in range(2))))
            self.assertEqual(res["added"], 2)
            res = self.ingest(body_of(minimal_run(1700000009)), now=NOW + 120, nonce_suffix="2")
            self.assertEqual((res["status"], res["error"]), ("failed", "too_many_runs"))
            self.assertIn(self.last_key, self.store.objects)  # real runs: kept
        finally:
            handler.MAX_RUNS_TOTAL = old

    def test_stats_count_each_run_once(self):
        self.ingest(body_of(minimal_run(1700000001), minimal_run(1700000002, win=False)))
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
        parse = lambda ts, **kw: handler.run.parse_run_data(minimal_run(ts, **kw))
        a = [parse(1700000001), parse(1700000002, win=False)]
        b = [parse(1700000003, run_time=900), parse(1700000004, run_time=3000)]
        merged = handler.merge_stats(handler.merge_stats(handler.empty_stats(), handler.tally(a, "x")),
                                     handler.tally(b, "y"))
        whole = handler.merge_stats(handler.empty_stats(), handler.tally(a + b, "y"))
        self.assertEqual(merged, whole)
        self.assertEqual(merged["solo"]["records"]["fastestWin"]["mins"], 15)


class RebuildTests(Uploads, unittest.TestCase):
    def test_rebuild_reparses_raw_and_keeps_legacy_runs(self):
        legacy = handler.run.parse_run_data(minimal_run(1600000000), steam_id=STEAM_ID)
        handler.save_profile(self.store, STEAM_ID, None, None, "Mr. Bean!", [legacy], {}, NOW)
        self.ingest(body_of(minimal_run(1700000001), minimal_run(1700000002)))
        self.ingest(body_of(minimal_run(1700000003)), now=NOW + 120, nonce_suffix="2")

        # Simulate an old parser's output on the profile.
        slug, etag, doc = handler._read_profile(self.store, STEAM_ID)
        for r in doc["runs"]:
            r["asc"] = -1
        handler.save_profile(self.store, STEAM_ID, slug, etag, doc["name"], doc["runs"], {}, NOW,
                             no_raw=doc["noRaw"])

        dry = handler.rebuild_profile(self.store, STEAM_ID, dry_run=True)
        self.assertEqual(self.store.runs()[1]["asc"], -1)
        summary = handler.rebuild_profile(self.store, STEAM_ID)
        self.assertEqual(dry, summary)
        self.assertEqual((summary["runs"], summary["fromRaw"], summary["noRaw"], summary["dropped"]), (4, 3, 1, 0))
        runs = self.store.runs()
        self.assertEqual([r["asc"] for r in runs], [-1, 3, 3, 3])  # the legacy run can't be rebuilt
        self.assertEqual(self.store.profile()["noRaw"], [1600000000])

    def test_rebuild_needs_a_profile(self):
        with self.assertRaises(handler.IngestError):
            handler.rebuild_profile(self.store, STEAM_ID)


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
    def setUp(self):
        self.store = MemStore()
        self.store.presign_post = fake_presign
        handler._store = self.store
        self.saved = (handler.verify_openid, handler.time.time, handler.lookup_steam_name,
                      os.environ.get("ALLOWED_RETURN_TO"))
        orig_verify = handler.verify_openid
        handler.verify_openid = lambda p, a, now=None, post=None: orig_verify(p, a, now=NOW, post=steam_says())
        handler.time.time = lambda: NOW
        handler.lookup_steam_name = named("Mr. Bean!")
        os.environ["ALLOWED_RETURN_TO"] = ",".join(ALLOWED)

    def tearDown(self):
        handler._store = None
        handler.verify_openid, handler.time.time, handler.lookup_steam_name, allowed = self.saved
        if allowed is None:
            os.environ.pop("ALLOWED_RETURN_TO", None)
        else:
            os.environ["ALLOWED_RETURN_TO"] = allowed

    def test_event_plumbing(self):
        event = {
            "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.7"}},
            "rawQueryString": urllib.parse.urlencode(openid_params()),
        }
        resp = handler.lambda_handler(event, None)
        self.assertEqual(resp["statusCode"], 200, resp["body"])
        auth = json.loads(resp["body"])
        key = auth["fields"]["key"]
        self.assertEqual((auth["url"], auth["slug"]), ("https://s3.example/", None))
        self.assertEqual(handler.lambda_handler(event, None)["statusCode"], 429)  # same sign-in again: cooldown

        # S3 URL-encodes keys in events.
        self.store.put(key, body_of(minimal_run(1700000001)), {}, None)
        handler.process_handler({"Records": [{"s3": {"object": {"key": urllib.parse.quote_plus(key)}}}]}, None)
        upload_id = handler.RAW_KEY_RE.match(key).group(3)
        result = self.store.json(handler.result_key(upload_id))
        self.assertEqual((result["added"], result["slug"]), (1, "mrbean"))

        event["requestContext"]["http"]["method"] = "GET"
        self.assertEqual(handler.lambda_handler(event, None)["statusCode"], 405)


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
        key = handler.raw_key(steam_id, "A" * 16, NOW)
        store.put(key, body, {}, None)
        res = handler.process_upload(key, store, now=NOW, lookup_name=named("Me"))
        self.assertEqual(res["rejected"], 0, res)
        expected = sorted((run.parse_run(f) for f in files), key=lambda r: r["ts"])
        self.assertEqual(store.runs(steam_id), json.loads(json.dumps(expected)))


if __name__ == "__main__":
    unittest.main()
