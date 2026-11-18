"""Tests for page-view counting (views.py) and its part of the morning digest.

    infra\\.venv\\Scripts\\python.exe -m unittest discover infra/tests
"""
import gzip
import os
import sys
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "infra" / "lambda" / "ingest"), str(REPO / "infra" / "tests")]  # the repo root holds run.py

import handler  # noqa: E402
import views  # noqa: E402
from test_ingest import MemStore  # noqa: E402

FIELDS = ("date time x-edge-location sc-bytes c-ip cs-method cs(Host) cs-uri-stem sc-status "
          "cs(Referer) cs(User-Agent) cs-uri-query").split()
UA = "Mozilla/5.0%20(Windows%20NT%2010.0)"


def line(stem, query="-", day="2026-11-17", ip="1.2.3.4", ua=UA, referer="-", status="200", method="GET"):
    values = dict(zip(FIELDS, [day, "12:00:00", "SEA19-C1", "100", ip, method, "x.cloudfront.net", stem,
                               status, referer, ua, query]))
    return "\t".join(values[f] for f in FIELDS)


def ping(path, tab=None, run=None, **kw):
    q = {"p": path}
    if tab:
        q["t"] = tab
    if run:
        q["r"] = run
    return line(views.PING, urllib.parse.urlencode(q), **kw)


def log_file(lines):
    text = "#Version: 1.0\n#Fields: " + " ".join(FIELDS) + "\n" + "\n".join(lines) + "\n"
    return gzip.compress(text.encode())


def count(lines, day="2026-11-17"):
    return views.count_views(views.read_log(log_file(lines)), day)


class CountViews(unittest.TestCase):
    def test_pages_tabs_players_and_runs(self):
        c = count([
            ping("/"), ping("/about"),
            ping("/u/jesse", "overview"), ping("/u/jesse", "cards"),
            ping("/u/jesse", "detail", "1731000000"), ping("/u/jesse", "detail", "1731000000", ip="192.0.2.8"),
            ping("/u/splitswigs-2", "detail", "1732000000"),
        ])
        self.assertEqual(c["views"], 7)
        self.assertEqual(c["visitors"], 2)
        self.assertEqual(c["pages"], {"/": 1, "/about": 1, "/u/<player>": 5})
        self.assertEqual(c["tabs"], {"overview": 1, "cards": 1, "detail": 3})
        self.assertEqual(c["players"], {"jesse": 4, "splitswigs-2": 1})
        self.assertEqual(c["runs"], {"jesse#1731000000": 2, "splitswigs-2#1732000000": 1})

    def test_a_new_page_or_tab_is_counted_without_a_code_change(self):
        c = count([ping("/patch-notes"), ping("/u/jesse", "relics"), ping("/u/jesse", "some-new-tab")])
        self.assertEqual(c["pages"], {"/patch-notes": 1, "/u/<player>": 2})
        self.assertEqual(c["tabs"], {"relics": 1, "some-new-tab": 1})

    def test_junk_bots_failures_and_other_days_are_left_out(self):
        c = count([
            ping("/<script>"), ping("/u/jesse", "BAD TAB"), ping("/u/jesse", "detail", "12abc"),
            line(views.PING, "-"), ping("/u/jesse", ua="Googlebot/2.1"), ping("/u/jesse", status="403"),
            ping("/u/jesse", day="2026-11-16"),
        ])
        self.assertEqual(c["views"], 0)
        self.assertEqual(c["pages"], {})

    def test_a_query_cloudfront_encoded_twice_still_reads(self):
        c = count([line(views.PING, "p=%252Fu%252Fjesse&t=cards")])
        self.assertEqual(c["players"], {"jesse": 1})

    def test_page_loads_by_source_skip_assets_pings_and_page_bodies(self):
        c = count([
            line("/u/jesse", referer="https://www.reddit.com/r/slaythespire/"),
            line("/", "ref=discord"), line("/about"), line("/index.html"),
            line("/app.0123456789.js"), line("/page-about.html"), ping("/"),
            line("/about", ua="bingbot"),
        ])
        self.assertEqual(c["loads"], 4)
        self.assertEqual(c["sources"], {"reddit.com": 1, "?ref=discord": 1, "(direct)": 2})

    def test_nothing_identifying_is_kept(self):
        c = count([ping("/u/jesse", "cards", ip="192.0.2.9")])
        self.assertNotIn("192.0.2.9", repr(c))


class ViewsSection(unittest.TestCase):
    def setUp(self):
        self.store, self.logs = MemStore(), MemStore()

    def log(self, key, lines):
        self.logs.objects[key] = (log_file(lines), 0.0, "e", {})

    def test_counts_the_day_keeps_it_and_adds_the_week(self):
        self.log("site/EDIST.2026-11-17-12.abc.gz", [ping("/u/jesse", "cards"), ping("/")])
        self.log("site/EDIST.2026-11-17-13.def.gz", [ping("/u/jesse", "detail", "1731000000")])
        self.log("site/EDIST.2026-11-16-23.ghi.gz", [ping("/")])  # the day before: not listed
        self.log("site/OTHER.2026-11-17-12.x.gz", [ping("/")])  # another distribution
        self.store.objects["analytics/views/2026-11-15.json.gz"] = (handler._pack(
            {"day": "2026-11-15", "views": 10, "pages": {"/": 10}}), 0.0, "e", {})
        headline, text = handler.views_section(self.store, "2026-11-17", self.logs, "site/EDIST.")
        self.assertEqual(headline, "Page views: 3 yesterday, 13 in 2 days")
        kept = self.store.json("analytics/views/2026-11-17.json.gz")
        self.assertEqual(kept["pages"], {"/u/<player>": 2, "/": 1})
        self.assertIn("https://slay-my-stats.com/u/jesse#detail/1731000000", text)
        self.assertRegex(text, r"/\s+1\s+11")  # yesterday 1, two days 11

    def test_running_twice_overwrites_the_day(self):
        self.log("site/EDIST.2026-11-17-12.abc.gz", [ping("/")])
        handler.views_section(self.store, "2026-11-17", self.logs, "site/EDIST.")
        handler.views_section(self.store, "2026-11-17", self.logs, "site/EDIST.")
        self.assertEqual(self.store.json("analytics/views/2026-11-17.json.gz")["views"], 1)

    def test_a_day_with_no_logs_is_zero(self):
        headline, _ = handler.views_section(self.store, "2026-11-17", self.logs, "site/EDIST.")
        self.assertEqual(headline, "Page views: 0 yesterday, 0 in 1 day")


class DigestEmail(unittest.TestCase):
    def run_digest(self, views_section):
        sent = []
        env = {"ACCESS_LOG_BUCKET": "logs"}
        with patch.dict(os.environ, env), patch.object(handler, "_get_store", return_value=MemStore()), \
             patch.object(handler, "views_section", views_section), \
             patch.object(handler, "feedback_sections", lambda now, tally=None: []), \
             patch.object(handler, "_alert", lambda s, b: sent.append((s, b))):
            handler.digest_handler({}, None)
        return sent[0]

    def test_views_go_last_and_stay_out_of_the_subject(self):
        subject, body = self.run_digest(lambda store, day: ("Page views: 5 yesterday, 5 in 1 day", "By page"))
        self.assertNotIn("Page views", subject)
        self.assertTrue(body.endswith("Page views: 5 yesterday, 5 in 1 day\n"
                                      "-----------------------------------\nBy page"))

    def test_a_views_failure_still_sends_the_email(self):
        def broken(store, day):
            raise RuntimeError("logs unreadable")
        subject, body = self.run_digest(broken)
        self.assertIn("no uploads yesterday", subject)
        self.assertNotIn("Page views", body)


if __name__ == "__main__":
    unittest.main()
