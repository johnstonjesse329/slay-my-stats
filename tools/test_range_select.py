"""Check the Run page's floor-range selection: drag a chart, add up what changed.

Dragging across a floor chart picks the floors under the pointer and the page adds up what the
run changed in them. This test drags the Keeping Up damage chart over floors it knows changed
the deck, holds the panel to the run file (the floors, fights and damage, the cards that came in
and the relics), checks the band is drawn on every floor chart, and that a click clears it.

Run with infra/.venv/Scripts/python tools/test_range_select.py
Needs tools/serve_site.py on 8000 (or SMS_SITE) and splitswigs' local profile.
"""
import gzip
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
RUN_FILE = ROOT / "local_data" / "users" / "splitswigs" / "2026-11.json.gz"
RUN_TS = 1793922945
BASE = os.environ.get("SMS_SITE", "http://127.0.0.1:8000")
URL = f"{BASE}/u/splitswigs#detail/{RUN_TS}"
FROM, TO = 9, 15


def load_run():
    with gzip.open(RUN_FILE, "rt", encoding="utf-8") as f:
        return next(r for r in json.load(f)["runs"] if r.get("ts") == RUN_TS)


def expected(run):
    """What the panel should say for the span, from the run file alone: the floors, fights and
    damage, and the cards and relics whose floor_added_to_deck falls inside it."""
    nodes = [n for n in run["timeline"] if FROM <= n["floor"] + 1 <= TO]
    cards_in = {c["id"] for c, added in zip(run.get("finalDeck") or [], run.get("deckAdded") or [])
                if FROM <= added <= TO}
    relics_in = {r["id"] for r, added in zip(run.get("finalRelics") or [], run.get("relicsAdded") or [])
                 if FROM <= added <= TO}
    # A card or relic that came in and later went out isn't in the final list, but it still
    # came in.
    cards_in |= {cid for cid, added, _ in run.get("cardsLost") or [] if FROM <= added <= TO}
    relics_in |= {rid for rid, added, _ in run.get("relicsLost") or [] if FROM <= added <= TO}
    return {
        "floors": len(nodes),
        "fights": sum(1 for n in nodes if n.get("turns")),
        "damage": sum(n.get("dmg") or 0 for n in nodes),
        "cards_in": cards_in,
        "relics_in": relics_in,
    }


def drag(page, canvas_id, from_floor, to_floor):
    """Drag the mouse across the chart from one floor's column to the other's."""
    el = page.locator(f"#{canvas_id}")
    el.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    box = el.bounding_box()
    xs = page.evaluate(
        """([id, from, to]) => {
             const c = Chart.getChart(document.getElementById(id));
             const at = floor => c.data.labels.findIndex(l => Number(l) === floor);
             const m = c.getDatasetMeta(0);
             return [m.data[at(from)].x, m.data[at(to)].x];
           }""",
        [canvas_id, from_floor, to_floor])
    y = box["y"] + 60
    page.mouse.move(box["x"] + xs[0], y)
    page.mouse.down()
    page.mouse.move(box["x"] + xs[1], y, steps=10)
    page.mouse.up()
    page.wait_for_timeout(400)


def group_ids(page, head):
    return set(page.evaluate(
        """head => {
             for (const g of document.querySelectorAll('#detail-range-panel .range-group')) {
               if (g.querySelector('.range-head').textContent.trim() === head)
                 return [...g.querySelectorAll('.range-chip')].map(c => c.dataset.id);
             }
             return [];
           }""", head))


def main():
    if not RUN_FILE.exists():
        print("skipped: needs splitswigs' local profile")
        return
    run = load_run()
    want = expected(run)
    assert want["cards_in"], "the span should have brought cards in"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(URL)
        page.wait_for_selector("#detail-keep-damage-chart", state="attached", timeout=20000)
        page.wait_for_function("() => typeof detailKeepCharts !== 'undefined' && detailKeepCharts.length > 0")

        drag(page, "detail-keep-damage-chart", FROM, TO)

        panel = page.locator("#detail-range-panel")
        assert panel.count() == 1, "the drag should open the panel"
        text = panel.inner_text()
        assert f"Floors {FROM}–{TO}" in text, text
        assert f"{want['floors']} floors" in text, text
        assert f"{want['fights']} fights" in text, text
        assert f"{want['damage']} damage taken" in text, text
        assert group_ids(page, "Cards in") == want["cards_in"], (group_ids(page, "Cards in"), want["cards_in"])
        assert group_ids(page, "Relics in") == want["relics_in"], (group_ids(page, "Relics in"), want["relics_in"])

        # The same span is drawn on every floor chart, not just the one dragged.
        drawn = page.evaluate(
            """() => [detailHpChart, detailGoldChart, detailDeckChart, detailRelicChart, ...detailKeepCharts]
                 .filter(Boolean).filter(c => c.config.plugins.some(p => p.id === 'rangeBand')).length""")
        charts = page.evaluate(
            """() => [detailHpChart, detailGoldChart, detailDeckChart, detailRelicChart, ...detailKeepCharts]
                 .filter(Boolean).length""")
        assert drawn == charts and charts >= 4, (drawn, charts)

        # A drag on another chart moves the panel to it and takes the new span.
        drag(page, "detail-hp-chart", FROM + 2, TO + 2)
        assert page.locator("#detail-range-panel").count() == 1, "still one panel"
        assert f"Floors {FROM + 2}–{TO + 2}" in page.locator("#detail-range-panel").inner_text()

        # A click clears it, and the bands go with it.
        page.mouse.click(30, 30)
        page.wait_for_timeout(300)
        assert page.locator("#detail-range-panel").count() == 0, "a click should clear the span"
        assert not errors, errors
        print(f"range select: floors {FROM}-{TO}, {want['cards_in']} cards in, "
              f"{want['relics_in']} relics, band on {charts} charts, clear on click.")

        browser.close()


if __name__ == "__main__":
    main()
