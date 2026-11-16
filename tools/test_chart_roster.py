"""Check that every per-character chart draws the whole roster, an unknown character included.

A character found only in the runs (a new one the catalog and colour list lack) joins
DATA.characters in js/data.js, so no chart can leave it out while another shows it. This test
adds a sixth, unknown character to a profile's runs on the way in (the month file is rewritten
in the browser's request, nothing on disk or in the bucket changes), then holds each chart that
draws one dataset per character to DATA.characters mapped through fmtCharName, and the
character picker to the same list.

Run with infra/.venv/Scripts/python tools/test_chart_roster.py
Needs tools/serve_site.py on 8000 (or SMS_SITE) and splitswigs' local profile.
"""
import copy
import json
import os
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("SMS_SITE", "http://127.0.0.1:8000")
SLUG = "splitswigs"
UNKNOWN = "TESTBOT"
# Charts that must be per-character (the test fails if one is missing); any other chart whose
# datasets carry a roster name is held to the same rule.
NAMED = ["ascWinChart", "monthlyWinChart"]


def add_unknown_character(route):
    """Serve the month's runs with one extra run by a character nothing else knows."""
    resp = route.fetch()
    body = resp.json()
    runs = body["runs"]
    extra = copy.deepcopy(runs[0])
    extra.update(char=UNKNOWN, ts=extra["ts"] + 1, won=True, mp=False, mode="standard")
    extra.pop("party", None)
    body["runs"] = runs + [extra]
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


def main():
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.on("pageerror", lambda e: errors.append(str(e)))
        # The newest month only: one added run is enough, and the others pass through.
        months = sorted(p.name[:7] for p in (ROOT / "local_data" / "users" / SLUG).glob("????-??.json.gz"))
        page.route(re.compile(rf"/users/{SLUG}/{months[-1]}\.json\.gz"), add_unknown_character)
        page.goto(f"{BASE}/u/{SLUG}#overview")
        page.wait_for_selector(".pb-table", timeout=30000)
        page.wait_for_timeout(1500)

        roster = page.evaluate("DATA.characters.map(fmtCharName)")
        assert len(roster) >= 6 and "Testbot" in roster, roster
        assert page.evaluate("DATA.characters.length === new Set(DATA.characters).size"), "roster repeats a character"
        assert page.evaluate(f"charColor('{UNKNOWN}') === CHAR_FALLBACK_COLOR"), "unknown character has no fallback colour"

        charts = page.evaluate("""(roster) => Object.fromEntries(Object.values(Chart.instances).map(c => [
            c.canvas.id, c.data.datasets.map(d => d.label).filter(l => roster.includes(l) || l === 'Testbot')
        ]))""", roster)
        per_char = {cid: labels for cid, labels in charts.items() if labels}
        for cid in NAMED:
            assert cid in per_char, f"{cid} is not a per-character chart on the page: {sorted(charts)}"
        for cid, labels in per_char.items():
            assert labels == roster, f"{cid} draws {labels}, roster is {roster}"

        picker = page.evaluate("[...document.querySelectorAll('#shared-char-selector .char-btn[data-char]')].map(b => b.textContent.trim())")
        assert picker == roster, f"character picker shows {picker}, roster is {roster}"
        assert not errors, errors
        browser.close()
    print(f"PASS: {', '.join(sorted(per_char))} and the character picker all list {len(roster)} characters, the unknown one included.")


if __name__ == "__main__":
    main()
