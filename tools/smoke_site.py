"""
Smoke test for a deployed site: fetch the pages the way a first-time visitor's browser
would and fail on what leaves it blank or broken.

    python tools/smoke_site.py                       # https://slay-my-stats.com
    python tools/smoke_site.py gamma.slay-my-stats.com [--player SLUG]

tools/deploy.py runs it (without --player) after every site deploy. CloudFront takes a minute or two to finish
the invalidation, so a failing check is retried until --wait seconds pass (default 240)
before it counts.

What it checks, and why each one exists:
  - The home page and a player's page (any /u/ path serves index.html) answer 200.
  - Nothing in <head> that blocks rendering comes from another origin. A hung CDN request
    (Chart.js from jsdelivr, once) leaves the page blank until it times out, and a plain
    fetch can't see that, so this reads the markup instead.
  - Every script and stylesheet the page names answers 200 with a matching content type.
  - catalog.json parses. With --player SLUG, that player's page, summary and newest month
    file load too.

  - With Playwright installed (pip install playwright, then playwright install chromium), the
    home page and the player's page must show content within BROWSER_BUDGET seconds in a real
    browser while every request to another host is left hanging. That is the check that
    matters: it catches any third-party thing that can stop the page painting, not just the
    pattern above. Without Playwright it is skipped with a note (--browser makes that an error).

It only reads: no uploads, no logins.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

TYPES = {".js": "javascript", ".css": "text/css", ".json": "json", ".html": "text/html"}


class SmokeError(Exception):
    pass


def get(url: str, timeout: int = 30) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip", "User-Agent": "slay-my-stats-smoke/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, headers, body = r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        status, headers, body = e.code, dict(e.headers), b""
    except OSError as e:
        raise SmokeError(f"{url}: no answer ({e})")
    if headers.get("Content-Encoding") == "gzip":
        body = gzip.decompress(body)
    return status, headers, body


class Head(HTMLParser):
    """Collects what the page loads: (tag, url, blocking_in_head)."""

    def __init__(self):
        super().__init__()
        self.in_head = False
        self.refs: list[tuple[str, str, bool]] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "head":
            self.in_head = True
        elif tag == "script" and a.get("src"):
            blocking = "async" not in a and "defer" not in a and a.get("type") != "module"
            self.refs.append(("script", a["src"], blocking))
        elif tag == "link" and a.get("rel") == "stylesheet" and a.get("href"):
            self.refs.append(("css", a["href"], True))

    def handle_endtag(self, tag):
        if tag == "head":
            self.in_head = False


def check_page(base: str, path: str) -> list[str]:
    """Fetch one page and every asset it names; return the problems."""
    problems = []
    status, _, body = get(base + path)
    if status != 200:
        return [f"{path}: HTTP {status}"]
    head = Head()
    head.feed(body.decode("utf-8", "replace"))
    host = urllib.parse.urlparse(base).netloc
    for kind, ref, blocking in head.refs:
        url = urllib.parse.urljoin(base + path, ref)
        if urllib.parse.urlparse(url).netloc != host and blocking:
            problems.append(f"{path}: blocking {kind} from another origin ({url}); if that host hangs, the page stays blank")
            continue
        s, h, b = get(url)
        want = TYPES.get("." + urllib.parse.urlparse(url).path.rsplit(".", 1)[-1], "")
        if s != 200:
            problems.append(f"{path}: {url} answered {s}")
        elif want and want not in h.get("Content-Type", ""):
            problems.append(f"{path}: {url} served as {h.get('Content-Type')!r}, expected {want}")
        elif not b:
            problems.append(f"{path}: {url} is empty")
    if not head.refs:
        problems.append(f"{path}: names no scripts or stylesheets")
    return problems


def check_data(base: str, player: str | None) -> list[str]:
    problems = []
    s, _, b = get(base + "/catalog.json")
    try:
        if s != 200 or not json.loads(b):
            problems.append(f"/catalog.json: HTTP {s} or empty")
    except ValueError:
        problems.append("/catalog.json: not JSON")
    if not player:
        return problems
    s, _, b = get(f"{base}/users/{player}.json.gz")
    if s != 200:
        return problems + [f"/users/{player}.json.gz: HTTP {s}"]
    try:
        summary = json.loads(b)
    except ValueError:
        return problems + [f"/users/{player}.json.gz: not JSON"]
    months = sorted(set(re.findall(r"\d{4}-\d{2}", json.dumps(summary))))
    if months:
        s, _, b = get(f"{base}/users/{player}/{months[-1]}.json.gz")
        if s != 200:
            problems.append(f"/users/{player}/{months[-1]}.json.gz: HTTP {s}")
    return problems


BROWSER_BUDGET = 2.0  # seconds to first content, third parties hanging


def check_browser(host: str, player: str | None, required: bool) -> list[str]:
    """Open each page in Chromium with every other host's requests left unanswered; it must paint fast."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        if required:
            return ["--browser needs Playwright: pip install playwright && playwright install chromium"]
        print("Note: Playwright isn't installed, so the in-browser render check was skipped.")
        return []
    problems = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for path in ["/"] + ([f"/u/{player}"] if player else []):
            page = browser.new_context().new_page()
            page.route(lambda u: urllib.parse.urlparse(u).netloc != host, lambda route: None)  # never answered
            t0 = time.time()
            page.goto(f"https://{host}{path}", wait_until="commit", timeout=30000)
            try:
                page.wait_for_function("document.body && document.body.innerText.length > 200",
                                       timeout=BROWSER_BUDGET * 1000, polling=50)
            except Exception:
                problems.append(f"{path}: nothing on screen after {BROWSER_BUDGET:g}s with other hosts hanging")
            page.context.close()
        browser.close()
    return problems


def run_once(host: str, player: str | None, browser: bool = False) -> list[str]:
    base = f"https://{host}"
    problems = check_page(base, "/") + (check_page(base, f"/u/{player}") if player else [])
    problems += check_data(base, player)
    return problems if problems else check_browser(host, player, browser)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("host", nargs="?", default="slay-my-stats.com")
    ap.add_argument("--player", default=None, help="a player slug to load (their summary and newest month)")
    ap.add_argument("--browser", action="store_true", help="fail, rather than skip, when Playwright isn't installed")
    ap.add_argument("--wait", type=int, default=240, help="seconds to keep retrying while CloudFront catches up")
    args = ap.parse_args()
    deadline = time.time() + args.wait
    while True:
        try:
            problems = run_once(args.host, args.player, args.browser)
        except SmokeError as e:
            problems = [str(e)]
        if not problems:
            print(f"Smoke test passed: {args.host}")
            return 0
        if time.time() >= deadline:
            print(f"Smoke test FAILED: {args.host}", file=sys.stderr)
            for p in problems:
                print(f"  - {p}", file=sys.stderr)
            return 1
        time.sleep(15)


if __name__ == "__main__":
    sys.exit(main())
