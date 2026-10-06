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
sys.path[:0] = [str(REPO), str(REPO / "infra" / "lambda" / "ingest"), str(REPO / "tools")]

import handler  # noqa: E402
import run  # noqa: E402
import validate_parser  # noqa: E402

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
        slug = self.slug(steam_id)
        return [r for _, runs in handler.stored_months(self, slug, self.profile(steam_id)) for r in runs]

    def months(self, slug="mrbean"):
        """The month files stored for a profile."""
        prefix = f"users/{slug}/"
        return sorted(k[len(prefix):-len(".json.gz")] for k in self.objects if k.startswith(prefix))

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


def multiplayer_run(start_time, round_ids=False):
    """A two-player run where the uploader (STEAM_ID) is *not* index 0.

    Each player buys a different card at one shop node, so a parser that reads
    player_stats[0] attributes the other player's card (ANGER) to the uploader
    instead of the uploader's own (SNAKEBITE). The other per-player fields
    (HP, gold) differ too, so they can be checked the same way.

    round_ids=True writes the IDs the way some game builds do -- as float64,
    which rounds the last digits -- to exercise the numeric ID match.
    """
    # Far enough from STEAM_ID that float64 rounding can't merge the two IDs.
    other_id = "76561198099999999"

    def ident(steam_id):
        return int(float(steam_id)) if round_ids else steam_id

    def player(pid, char):
        return {"id": pid, "character": char, "deck": [], "relics": []}

    def stats(pid, card, hp, gold):
        return {
            "player_id": pid, "current_hp": hp, "max_hp": 80, "damage_taken": 10,
            "hp_healed": 0, "gold_gained": gold, "gold_spent": 0, "current_gold": gold,
            "card_choices": [{"card": {"id": card}, "was_picked": True}],
            "cards_gained": [{"id": card}],
        }

    node = {
        "map_point_type": "shop",
        "rooms": [{"model_id": "ENCOUNTER.SHOP", "turns_taken": 0}],
        "player_stats": [stats(ident(other_id), "CARD.ANGER", 55, 999),
                         stats(ident(STEAM_ID), "CARD.SNAKEBITE", 70, 100)],
    }
    players = [player(ident(other_id), "CHARACTER.IRONCLAD"),
               player(ident(STEAM_ID), "CHARACTER.SILENT")]
    return minimal_run(start_time, players=players, map_point_history=[[node]])


def shop_run(start_time, bought=("CARD.SNAKEBITE",), shelf=("CARD.ANGER",)):
    """A solo run with one shop node.

    The shop's shelf is listed in card_choices with was_picked false; the card
    actually bought is in cards_gained. A parser reading only card_choices
    reports no buys.
    """
    node = {
        "map_point_type": "shop",
        "rooms": [{"model_id": "ENCOUNTER.SHOP", "turns_taken": 0}],
        "player_stats": [{
            "player_id": 1, "current_hp": 70, "max_hp": 80, "gold_spent": 100,
            "card_choices": [{"card": {"id": cid}, "was_picked": False} for cid in shelf],
            "cards_gained": [{"id": cid} for cid in bought],
        }],
    }
    return minimal_run(start_time, map_point_history=[[node]])


def nonoffer_run(start_time):
    """A run whose nodes hand over cards without ever offering a choice.

    An event option that grants a card, and a rest-site CLONE that duplicates
    one already in the deck. Both land in cards_gained; neither records a card
    offer, so neither may count as a pick. This is the shape a future game
    version could add more of -- things that look like picks but aren't.
    """
    event = {
        "map_point_type": "unknown",
        "rooms": [{"model_id": "EVENT.BYRDONIS_NEST", "turns_taken": 0}],
        "player_stats": [{
            "player_id": 1, "current_hp": 70, "max_hp": 80,
            "event_choices": [{"title": {"key": "BYRDONIS_NEST.pages.INITIAL.options.TAKE.title",
                                         "table": "events"}, "variables": {}}],
            "cards_gained": [{"id": "CARD.BYRDONIS_EGG"}],
        }],
    }
    rest = {
        "map_point_type": "rest_site",
        "rooms": [],
        "player_stats": [{
            "player_id": 1, "current_hp": 40, "max_hp": 80,
            "rest_site_choices": ["CLONE"],
            "cards_gained": [{"id": "CARD.POMMEL_STRIKE"}, {"id": "CARD.POMMEL_STRIKE"}],
        }],
    }
    return minimal_run(start_time, map_point_history=[[event, rest]])


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


TICKET = "14000000" + "ab" * 100


def steam_ticket_says(steam_id=STEAM_ID, result="OK"):
    """Stands in for _http_get on AuthenticateUserTicket."""
    calls = []

    def get(url):
        calls.append(url)
        if result != "OK":
            return json.dumps({"response": {"error": {"errorcode": 101, "errordesc": "Invalid ticket"}}})
        return json.dumps({"response": {"params": {"result": "OK", "steamid": steam_id, "ownersteamid": steam_id}}})
    get.calls = calls
    return get


class VerifyTicketTests(unittest.TestCase):
    def setUp(self):
        self.saved, handler._api_key = handler._api_key, "KEY"

    def tearDown(self):
        handler._api_key = self.saved

    def assertRefused(self, code, ticket=TICKET, get=None):
        with self.assertRaises(handler.IngestError) as cm:
            handler.verify_ticket(ticket, get=get or steam_ticket_says())
        self.assertEqual(cm.exception.code, code)
        return cm.exception

    def test_valid(self):
        get = steam_ticket_says()
        self.assertEqual(handler.verify_ticket(TICKET, get=get), STEAM_ID)
        asked = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(get.calls[0]).query))
        self.assertEqual(asked, {"key": "KEY", "appid": handler.STS2_APP_ID, "ticket": TICKET,
                                 "identity": handler.TICKET_IDENTITY})

    def test_steam_says_invalid(self):
        self.assertRefused("bad_ticket", get=steam_ticket_says(result="Invalid ticket"))

    def test_junk_skips_steam(self):
        get = steam_ticket_says()
        for junk in (None, "", "abcd", "zz" * 40, "ab" * 3000, 5, TICKET + "&key=x"):
            self.assertRefused("bad_ticket", ticket=junk, get=get)
        self.assertEqual(get.calls, [])

    def test_unexpected_answers(self):
        for answer in ("not json", "[]", '{"response": {"params": {"result": "OK", "steamid": "7"}}}',
                       '{"response": {"params": {"result": "OK", "steamid": 76561198000000001}}}',
                       '{"response": {"params": ["OK"]}}'):
            with self.subTest(answer=answer):
                code = "steam_unreachable" if answer == "not json" else "bad_ticket"
                self.assertRefused(code, get=lambda url, answer=answer: answer)

    def test_steam_down_and_key_refused(self):
        def down(url):
            raise OSError("timed out")

        def refused(url):
            raise handler.urllib.error.HTTPError(url, 403, "Forbidden", None, None)
        self.assertEqual(self.assertRefused("steam_unreachable", get=down).status, 502)
        e = self.assertRefused("steam_key_rejected", get=refused)
        # The URL has the key in it; nothing about it may reach the caller.
        self.assertNotIn("KEY", e.message)

    def test_no_key(self):
        handler._api_key = ""
        get = steam_ticket_says()
        self.assertRefused("no_steam_key", get=get)
        self.assertEqual(get.calls, [])


class AuthorizeModTests(Uploads, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.saved, handler._api_key = handler._api_key, "KEY"

    def tearDown(self):
        handler._api_key = self.saved

    def authorize_mod(self, now=NOW, steam_id=STEAM_ID, ticket_for=None, allowlist=(STEAM_ID,), get=None, **body):
        get = get or steam_ticket_says(steam_id if ticket_for is None else ticket_for)
        return handler.authorize_mod({"steamId": steam_id, "ticket": TICKET, **body}, self.store, set(allowlist),
                                     fake_presign, now=now, verify=lambda t: handler.verify_ticket(t, get=get))

    def assertRefused(self, code, **kw):
        with self.assertRaises(handler.IngestError) as cm:
            self.authorize_mod(**kw)
        self.assertEqual(cm.exception.code, code)
        return cm.exception

    def test_hands_out_one_raw_key(self):
        auth = self.authorize_mod()
        self.assertEqual(auth["fields"]["key"], handler.raw_key(STEAM_ID, auth["uploadId"], NOW))
        self.assertEqual((auth["maxBytes"], auth["slug"]), (handler.MOD_UPLOAD_MAX_BYTES, None))

    def test_upload_lands_on_the_same_profile_as_the_site(self):
        self.ingest(body_of(minimal_run(1700000001)))
        auth = self.authorize_mod()
        self.assertEqual(auth["slug"], "mrbean")
        self.store.put(auth["fields"]["key"], body_of(minimal_run(1700000002, slay_my_stats_mod={"mods": ["X"]})),
                       {}, None)
        self.assertEqual(self.process(auth["fields"]["key"])["added"], 1)
        self.assertEqual([r["ts"] for r in self.store.runs()], [1700000001, 1700000002])

    def test_the_mods_a_run_was_played_with_are_kept(self):
        reported = {"version": "v0.0.1", "mods": [
            {"id": "SlayMyStats", "name": "Slay My Stats", "version": "v0.0.1", "affects_gameplay": False},
            {"id": "CheatMod", "name": "Cheats!", "version": "2.0", "affects_gameplay": True},
        ]}
        self.ingest(body_of(minimal_run(1700000001), minimal_run(1700000002, slay_my_stats_mod=reported)))
        plain, modded = self.store.runs()
        self.assertNotIn("mods", plain)
        self.assertEqual(modded["mods"], [{"id": "SlayMyStats", "version": "v0.0.1"},
                                          {"id": "CheatMod", "version": "2.0", "gameplay": True}])

    def test_what_a_mod_says_about_itself_is_cleaned_not_trusted(self):
        reported = {"mods": [
            {"id": "<img src=x onerror=alert(1)>", "version": "1.0 beta", "affects_gameplay": "yes"},
            {"id": "x" * 500}, {"id": ""}, {"id": 7}, {"version": "1"}, "NotAMod", None,
        ] + [{"id": f"Mod{i}"} for i in range(500)]}
        self.assertEqual(self.ingest(body_of(minimal_run(1700000001, slay_my_stats_mod=reported)))["added"], 1)
        mods = self.store.runs()[0]["mods"]
        self.assertEqual(mods[:2], [{"id": "_img_src_x_onerror_alert_1__", "version": "1.0_beta"}, {"id": "x" * 80}])
        # Only the first MAX_MODS_PER_RUN reported are looked at; five of those have no usable id.
        self.assertEqual(len(mods), run.MAX_MODS_PER_RUN - 5)

    def test_a_mod_report_that_is_not_a_list_is_ignored(self):
        for junk in ("yes", 3, ["A"], {"mods": "A"}, {"mods": {"id": "A"}}, {"modded": True}):
            self.assertNotIn("mods", run.parse_run_data(minimal_run(1700000001, slay_my_stats_mod=junk)))

    def test_not_on_the_allowlist_never_reaches_steam(self):
        get = steam_ticket_says()
        self.assertEqual(self.assertRefused("not_allowlisted", allowlist=(), get=get).status, 403)
        self.assertRefused("not_allowlisted", allowlist=("76561198000000002",), get=get)
        self.assertEqual(get.calls, [])
        self.assertEqual(self.store.objects, {})

    def test_someone_elses_ticket(self):
        # An allowlisted id claimed with a real ticket for another account.
        self.assertRefused("bad_ticket", ticket_for="76561198000000002")
        self.assertRefused("bad_ticket", ticket="00")
        self.assertRefused("bad_ticket", get=steam_ticket_says(result="Invalid ticket"))
        self.assertEqual(self.store.objects, {})

    def test_bad_requests(self):
        for body in (None, [], {}, {"steamId": 76561198000000001}, {"steamId": "76561198000000001x"}):
            with self.subTest(body=body), self.assertRaises(handler.IngestError) as cm:
                handler.authorize_mod(body, self.store, {STEAM_ID}, fake_presign, now=NOW)
            self.assertEqual(cm.exception.code, "bad_request")

    def test_cooldown_is_short(self):
        self.authorize_mod()
        self.assertRefused("cooldown", now=NOW + handler.MOD_COOLDOWN_SECONDS - 1)
        self.authorize_mod(now=NOW + handler.MOD_COOLDOWN_SECONDS)

    def test_daily_cap(self):
        step = handler.MOD_COOLDOWN_SECONDS
        for i in range(handler.MOD_UPLOADS_PER_DAY):
            self.authorize_mod(now=NOW + i * step)
        last = NOW + handler.MOD_UPLOADS_PER_DAY * step
        self.assertEqual(self.assertRefused("rate_limited", now=last).status, 429)
        # Another player is unaffected, and the window slides.
        other = "76561198000000002"
        self.authorize_mod(now=last, steam_id=other, allowlist=(STEAM_ID, other))
        self.authorize_mod(now=NOW + handler.MOD_WINDOW_SECONDS + 1)

    def test_separate_from_the_sites_limits(self):
        # Right after a site upload, and more of them than one address gets
        # there: neither the site's cooldown nor its per-IP count applies.
        self.authorize()
        for i in range(handler.IP_UPLOADS_PER_HOUR + 2):
            self.authorize_mod(now=NOW + i * handler.MOD_COOLDOWN_SECONDS)
        self.assertEqual(len(self.store.json(handler.ip_limit_key("203.0.113.7"))["times"]), 1)
        self.authorize(now=NOW + 61, nonce_suffix="2")


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
        self.assertEqual(blob, {"v": 2, "name": "Mr. Bean!", "parser": run.PARSER_VERSION,
                                "months": {"2023-11": [1700000001]}, "noRaw": []})
        month = json.loads(gzip.decompress(self.store.objects["users/mrbean/2023-11.json.gz"][0]))
        self.assertEqual((month["v"], [r["ts"] for r in month["runs"]]), (2, [1700000001]))

    def test_uploads_in_any_order_land_in_month_files(self):
        # 2024-03, 2023-07, then 2023-11 between them and a resend of 2023-07.
        self.ingest(body_of(minimal_run(1710000000), minimal_run(1690000000)))
        res = self.ingest(body_of(minimal_run(1700000000), minimal_run(1690000000)),
                          now=NOW + 120, nonce_suffix="2")
        self.assertEqual((res["added"], res["duplicates"], res["total"]), (1, 1, 3))
        self.assertEqual(self.store.months(), ["2023-07", "2023-11", "2024-03"])
        self.assertEqual(self.store.profile()["months"],
                         {"2023-07": [1690000000], "2023-11": [1700000000], "2024-03": [1710000000]})
        self.assertEqual([r["ts"] for r in self.store.runs()], [1690000000, 1700000000, 1710000000])

    def test_only_touched_months_are_written(self):
        self.ingest(body_of(minimal_run(1690000000), minimal_run(1700000000)))
        july = self.store.objects["users/mrbean/2023-07.json.gz"]
        self.ingest(body_of(minimal_run(1700000001)), now=NOW + 120, nonce_suffix="2")
        self.assertIs(self.store.objects["users/mrbean/2023-07.json.gz"], july)

    def test_resent_run_is_reparsed(self):
        self.ingest(body_of(minimal_run(1700000001)))
        res = self.ingest(body_of(minimal_run(1700000001, ascension=9)), now=NOW + 120, nonce_suffix="2")
        self.assertEqual((res["added"], res["duplicates"]), (0, 1))
        self.assertEqual(self.store.runs()[0]["asc"], 9)
        self.assertEqual(self.stats()["allRuns"], 1)  # counted once

    def test_nothing_new_does_not_write_profile(self):
        self.ingest(body_of(minimal_run(1700000001)))
        before = dict(self.store.objects)
        res = self.ingest(body_of(minimal_run(1700000001)), now=NOW + 120, nonce_suffix="again")
        self.assertEqual((res["added"], res["duplicates"], res["slug"], res["total"]), (0, 1, "mrbean", 1))
        for key in ("users/mrbean.json.gz", "users/mrbean/2023-11.json.gz", handler.INDEX_KEY):
            self.assertIs(self.store.objects[key], before[key])

    def put_v1_profile(self, *ts, **extra):
        """A profile from before month files: every run in the one file."""
        runs = [handler.run.parse_run_data(minimal_run(t), steam_id=STEAM_ID) for t in ts]
        self.store.put(handler.blob_key("mrbean"),
                       handler._pack({"v": 1, "name": "Mr. Bean!", "runs": runs, **extra}), {}, None)
        self.store.put(handler.id_key(STEAM_ID), handler._pack({"slug": "mrbean"}), {}, None)

    def test_legacy_profile_catch_up(self):
        # A profile from before raw uploads: no noRaw key, so none of its runs
        # have a raw copy until they're sent again.
        self.put_v1_profile(1700000001, 1700000002)
        self.ingest(body_of(minimal_run(1700000003)))
        self.assertEqual(self.store.profile()["noRaw"], [1700000001, 1700000002])
        self.ingest(body_of(minimal_run(1700000001), minimal_run(1700000002)), now=NOW + 120, nonce_suffix="2")
        self.assertEqual(self.store.profile()["noRaw"], [])
        self.assertEqual(len(self.store.runs()), 3)

    def test_v1_profile_is_migrated_on_upload(self):
        self.put_v1_profile(1690000000, 1700000001, noRaw=[], parser=0)
        res = self.ingest(body_of(minimal_run(1710000000)))
        self.assertEqual((res["added"], res["total"]), (1, 3))
        doc = self.store.profile()
        self.assertEqual((doc["v"], doc["parser"], doc["noRaw"]), (2, 0, []))  # parser kept: not reparsed
        self.assertEqual(self.store.months(), ["2023-07", "2023-11", "2024-03"])
        self.assertEqual([r["ts"] for r in self.store.runs()], [1690000000, 1700000001, 1710000000])

    def test_migrate_profile_tool(self):
        self.put_v1_profile(1690000000, 1700000001, noRaw=[1690000000])
        self.assertTrue(handler.migrate_profile(self.store, "mrbean"))
        self.assertFalse(handler.migrate_profile(self.store, "mrbean"))  # already done
        self.assertEqual(self.store.profile()["noRaw"], [1690000000])
        self.assertEqual([r["ts"] for r in self.store.runs()], [1690000000, 1700000001])

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
            if key == "users/mrbean/2023-11.json.gz" and not state["raced"]:
                # The other upload writes the same month, a new one, and the
                # summary, all before ours does.
                state["raced"] = True
                handler._merge_upload(racy, STEAM_ID, body_of(minimal_run(1700000009), minimal_run(1702000000)),
                                      NOW, named("Mr. Bean!"))
            orig_put(key, data, metadata, if_match)
        racy.put = put
        self.store = racy
        res = self.ingest(body_of(minimal_run(1700000002)), now=NOW + 120, nonce_suffix="2")
        self.assertEqual(res["total"], 4)
        self.assertEqual([r["ts"] for r in racy.runs()], [1700000001, 1700000002, 1700000009, 1702000000])
        self.assertEqual(racy.profile()["months"], {"2023-11": [1700000001, 1700000002, 1700000009],
                                                    "2023-12": [1702000000]})
        self.assertEqual(self.stats()["allRuns"], 4)

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
        self.assertEqual(self.store.profile()["months"], {"2023-11": [1700000001]})
        self.assertEqual(self.store.months("elsewhere"), ["2023-11"])

    def test_upload_caps(self):
        for cap, value, body, error in [
            ("MAX_RUNS_PER_UPLOAD", 2, body_of(*(minimal_run(1700000000 + i) for i in range(3))), "too_many_runs"),
            ("MAX_MONTHS_PER_UPLOAD", 1, body_of(minimal_run(1690000000), minimal_run(1700000000)),
             "too_many_months"),
        ]:
            self.setUp()
            old = getattr(handler, cap)
            setattr(handler, cap, value)
            try:
                res = self.ingest(body)
            finally:
                setattr(handler, cap, old)
            self.assertEqual((res["status"], res["error"]), ("failed", error))
            self.assertIn(self.last_key, self.store.objects)  # real runs: kept
            self.assertNotIn(handler.id_key(STEAM_ID), self.store.objects)  # nothing saved

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

    def test_multiplayer_reads_only_the_local_players_stats(self):
        # The uploader is index 1 in this run, so every per-player field must
        # come from their own player_stats entry, never index 0's.
        self.ingest(body_of(multiplayer_run(1700000001)))
        run_doc = self.store.runs()[0]
        self.assertTrue(run_doc["mp"])
        self.assertEqual(run_doc["char"], "SILENT")
        self.assertEqual(list(run_doc["cardsOffered"]), ["CARD.SNAKEBITE"])
        self.assertEqual([n["cardPicked"] for n in run_doc["timeline"]], ["CARD.SNAKEBITE"])
        self.assertEqual(run_doc["timeline"][0]["hpAfter"], 70)
        self.assertEqual(run_doc["timeline"][0]["goldGained"], 100)

    def test_shop_card_buys_come_from_cards_gained(self):
        # The shelf (card_choices) is all was_picked false; the bought card is
        # in cards_gained -- both cardsOffered (Most bought) and the Run Detail
        # timeline must see it as a buy, and the shelf card as skipped.
        self.ingest(body_of(shop_run(1700000001)))
        run_doc = self.store.runs()[0]
        loc = run_doc["cardsOffered"]["CARD.SNAKEBITE"][0]
        self.assertEqual((loc["type"], loc["picked"]), ("shop", True))
        node = run_doc["timeline"][0]
        self.assertEqual(node["cardsBought"], ["CARD.SNAKEBITE"])
        self.assertEqual(node["cardPicked"], "CARD.SNAKEBITE")
        self.assertEqual(node["cardsSkipped"], ["CARD.ANGER"])

    def test_cards_gained_without_an_offer_are_not_picks(self):
        # An event handing over a card, and a rest-site CLONE duplicating one,
        # are not choices -- they must not show up as picked. This is the guard
        # for the whole class of "looks like a pick but isn't": only a shop
        # (a real offer you pay for) may turn cards_gained into picks.
        self.ingest(body_of(nonoffer_run(1700000001)))
        run_doc = self.store.runs()[0]
        self.assertEqual(run_doc["cardsOffered"], {})
        event_node, rest_node = run_doc["timeline"]
        for node in (event_node, rest_node):
            self.assertEqual((node["cardPicked"], node["cardsBought"], node["cardsRewarded"]),
                             (None, [], []))
        self.assertEqual(rest_node["restChoice"], "CLONE")

    def test_multiplayer_matches_float_rounded_steam_ids(self):
        # Some game builds write the Steam ID as a float64, which rounds the
        # last digits (76561198012345678 -> 76561198012345680). The uploader
        # must still be found in their own run, not fall back to index 0.
        self.ingest(body_of(multiplayer_run(1700000001, round_ids=True)))
        run_doc = self.store.runs()[0]
        self.assertEqual(run_doc["char"], "SILENT")
        self.assertEqual(list(run_doc["cardsOffered"]), ["CARD.SNAKEBITE"])

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
        runs = self.store.runs()
        for r in runs:
            r["asc"] = -1
        handler.save_profile(self.store, STEAM_ID, slug, etag, doc["name"], runs, {}, NOW,
                             no_raw=doc["noRaw"])

        dry = handler.rebuild_profile(self.store, STEAM_ID, dry_run=True)
        self.assertEqual(self.store.runs()[1]["asc"], -1)
        summary = handler.rebuild_profile(self.store, STEAM_ID)
        self.assertEqual(dry, summary)
        self.assertEqual((summary["runs"], summary["fromRaw"], summary["noRaw"], summary["dropped"]), (4, 3, 1, 0))
        runs = self.store.runs()
        self.assertEqual([r["asc"] for r in runs], [-1, 3, 3, 3])  # the legacy run can't be rebuilt
        self.assertEqual(self.store.profile()["noRaw"], [1600000000])

    def test_rebuild_drops_months_left_empty(self):
        # A run whose raw copy is gone (say, stripped) leaves the profile, and
        # so does its month file when it was the only run in it.
        self.ingest(body_of(minimal_run(1690000000), minimal_run(1700000000)))
        self.store.delete(self.last_key)
        self.ingest(body_of(minimal_run(1700000000)), now=NOW + 120, nonce_suffix="2")
        summary = handler.rebuild_profile(self.store, STEAM_ID)
        self.assertEqual((summary["runs"], summary["dropped"]), (1, 1))
        self.assertEqual(self.store.months(), ["2023-11"])
        self.assertEqual(self.store.profile()["months"], {"2023-11": [1700000000]})

    def test_remove_profile(self):
        self.ingest(body_of(minimal_run(1690000000), minimal_run(1700000000)))
        self.ingest(body_of(minimal_run(1700000001)), steam_id="76561198000000002", name="Other")
        dry = handler.remove_profile(self.store, "mrbean", raw=True, dry_run=True)
        self.assertIn("users/mrbean.json.gz", self.store.objects)
        self.assertEqual(handler.remove_profile(self.store, "mrbean", raw=True), dry)
        self.assertEqual(dry["steamIds"], [STEAM_ID])
        self.assertEqual([k for k in self.store.objects if "mrbean" in k or STEAM_ID in k and "limits" not in k], [])
        self.assertEqual([p["slug"] for p in self.store.index()], ["other"])
        self.assertEqual(len(self.store.runs("76561198000000002")), 1)  # someone else's: untouched
        # Their next upload starts over, under the same slug.
        res = self.ingest(body_of(minimal_run(1700000000)), now=NOW + 120, nonce_suffix="2")
        self.assertEqual((res["slug"], res["added"], res["total"]), ("mrbean", 1, 1))

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

        # A stage with ALLOWED_IPS (gamma) refuses every other address.
        os.environ["ALLOWED_IPS"] = "203.0.113.7,2001:db8:1:2:"
        try:
            event["requestContext"]["http"]["sourceIp"] = "198.51.100.1"
            self.assertEqual(handler.lambda_handler(event, None)["statusCode"], 403)
            event["requestContext"]["http"]["sourceIp"] = "203.0.113.70"
            self.assertEqual(handler.lambda_handler(event, None)["statusCode"], 403)
            event["requestContext"]["http"]["sourceIp"] = "203.0.113.7"
            self.assertEqual(handler.lambda_handler(event, None)["statusCode"], 405)
            event["requestContext"]["http"]["sourceIp"] = "2001:db8:1:2::9"
            self.assertEqual(handler.lambda_handler(event, None)["statusCode"], 405)
        finally:
            del os.environ["ALLOWED_IPS"]

    def test_mod_event_plumbing(self):
        saved = (handler.verify_ticket, handler._mod_allowlist, os.environ.get("MOD_ALLOWLIST"))
        handler.verify_ticket = lambda ticket, get=None: STEAM_ID if ticket == TICKET else "76561198000000002"
        handler._mod_allowlist = (None, frozenset())
        os.environ["MOD_ALLOWLIST"] = f"{STEAM_ID}, not-an-id"
        lines = []
        orig_print, handler.print = getattr(handler, "print", None), lambda line: lines.append(json.loads(line))

        def post(body, path="/mod", **extra):
            event = {"requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.7"}},
                     "rawPath": path, "rawQueryString": "", "body": body, **extra}
            resp = handler.lambda_handler(event, None)
            return resp["statusCode"], json.loads(resp["body"])
        try:
            good = json.dumps({"steamId": STEAM_ID, "ticket": TICKET})
            status, auth = post(good)
            self.assertEqual(status, 200, auth)
            self.assertRegex(auth["fields"]["key"], rf"^raw/{STEAM_ID}/")
            self.assertEqual(auth["maxBytes"], handler.MOD_UPLOAD_MAX_BYTES)
            self.assertEqual(lines[-1], {"via": "mod", "status": 200, "uploadId": auth["uploadId"]})

            self.assertEqual(post(good, path="/mod/")[1]["error"], "cooldown")
            self.assertEqual(lines[-1], {"via": "mod", "status": 429, "code": "cooldown"})
            self.assertEqual(post(json.dumps({"steamId": "76561198000000002", "ticket": TICKET}))[0], 403)
            self.assertEqual(lines[-1], {"via": "mod", "status": 403, "code": "not_allowlisted"})
            self.assertEqual(post(json.dumps({"steamId": STEAM_ID, "ticket": TICKET + "00"}))[1]["error"], "bad_ticket")
            for junk in (None, "", "{", "[1]", '"x"', "x" * (handler.MOD_BODY_MAX_BYTES + 1)):
                self.assertEqual(post(junk)[1]["error"], "bad_request")
            self.assertEqual(post("!!!", isBase64Encoded=True)[1]["error"], "bad_request")

            # Anything else is still the site's way in, and isn't counted as the mod's.
            self.assertEqual(post(good, path="/")[1]["error"], "bad_openid")
            self.assertEqual(lines[-1], {"status": 401, "code": "bad_openid"})
        finally:
            handler.verify_ticket, handler._mod_allowlist, allowlist = saved
            if orig_print is None:
                del handler.print
            if allowlist is None:
                os.environ.pop("MOD_ALLOWLIST", None)
            else:
                os.environ["MOD_ALLOWLIST"] = allowlist

    def test_mod_allowlist_is_reread(self):
        saved = (handler._mod_allowlist, os.environ.get("MOD_ALLOWLIST"))
        handler._mod_allowlist = (None, frozenset())
        try:
            os.environ["MOD_ALLOWLIST"] = STEAM_ID
            self.assertEqual(handler.mod_allowlist(now=NOW), {STEAM_ID})
            os.environ["MOD_ALLOWLIST"] = "76561198000000002"
            self.assertEqual(handler.mod_allowlist(now=NOW + handler.MOD_ALLOWLIST_SECONDS - 1), {STEAM_ID})
            self.assertEqual(handler.mod_allowlist(now=NOW + handler.MOD_ALLOWLIST_SECONDS), {"76561198000000002"})
        finally:
            handler._mod_allowlist, allowlist = saved
            if allowlist is None:
                os.environ.pop("MOD_ALLOWLIST", None)
            else:
                os.environ["MOD_ALLOWLIST"] = allowlist

    def test_failure_handler_tells_the_page(self):
        key = handler.raw_key("76561197960287930", "abcDEF123456abcd", 1700000000)
        s3_event = {"Records": [{"s3": {"object": {"key": urllib.parse.quote_plus(key)}}}]}
        alerts = []
        orig_alert, handler._alert = handler._alert, lambda subject, message: alerts.append(message)
        try:
            handler.failure_handler({"requestPayload": s3_event,
                                     "responsePayload": {"errorMessage": "Task timed out"}}, None)
        finally:
            handler._alert = orig_alert
        result = self.store.json(handler.result_key("abcDEF123456abcd"))
        self.assertEqual((result["status"], result["error"]), ("failed", "process_failed"))
        self.assertEqual(len(alerts), 1)
        self.assertIn(key, alerts[0])
        self.assertIn("Task timed out", alerts[0])

class ValidatorTests(unittest.TestCase):
    """The parser validator must reject a parse that picked the wrong player.

    tools/validate_parser.py is only useful if it can fail; without this guard
    it could quietly accept everything and prove nothing.
    """

    def test_rejects_a_parse_of_the_wrong_player(self):
        data = multiplayer_run(1700000001)
        self.assertEqual(validate_parser.validate_run(data, STEAM_ID), [])
        original = run.local_player_index
        run.local_player_index = lambda _data, _sid: 0   # the old multiplayer bug
        try:
            problems = validate_parser.validate_run(data, STEAM_ID)
        finally:
            run.local_player_index = original
        self.assertTrue(problems, "validator accepted a parse of the wrong player")


class RealHistoryTests(unittest.TestCase):
    """Uploading real .run files must store everything the ingest path computes.

    NOTE: this compares the Lambda's output against run.parse_run() -- the same
    parse_run_data on both sides -- so it proves the plumbing is faithful, NOT
    that the parse is right. tools/validate_parser.py checks the parse against
    the game's own labels (players[].id, player_stats[].player_id).
    
    """

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
