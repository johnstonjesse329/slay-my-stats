"""Check the Run page's "Keeping up, fight by fight" chart against the run file.

The chart plots damage taken and fight turns as a multiple of the average win on the same
fight (tools/power_curve/fight_demand.py), and marks the floors that changed the deck. This
test recomputes the two series in Python from the run's profile and fight_demand.json and
holds the page to them, then checks the ticks, the legend, and the phone layout.

Run with infra/.venv/Scripts/python tools/test_keep_share_chart.py
Needs tools/serve_site.py on 8000 (or SMS_SITE) and splitswigs' local profile.
"""
import gzip
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
RUN_FILE = ROOT / "local_data" / "users" / "splitswigs" / "2026-11.json.gz"
DEMAND = ROOT / "fight_demand.json"
RUN_TS = 1793922945
BASE = os.environ.get("SMS_SITE", "http://127.0.0.1:8000")
URL = f"{BASE}/u/splitswigs#detail/{RUN_TS}"


def load_run():
    with gzip.open(RUN_FILE, "rt", encoding="utf-8") as f:
        return next(r for r in json.load(f)["runs"] if r.get("ts") == RUN_TS)


def expected_series(run, demand):
    """The two multiples the page should draw, keyed by node index: fightReadings' rows,
    with a lost final fight's damage taken from its log when there is one."""
    nodes = run["timeline"]
    measured = {m["floor"]: m for m in run.get("measured") or []}
    last = max((i for i, n in enumerate(nodes) if n.get("turns")), default=-1)
    out = {}
    for i, node in enumerate(nodes):
        if not node.get("turns"):
            continue
        how = (demand.get(node.get("fight") or node.get("enc") or "") or {}).get("tiers", [{}] * 2)[0]
        if not how.get("turns"):
            continue
        lost = not run["won"] and i == last
        log = measured.get(node["floor"] + 1)
        gross = log["taken"] if lost and log else node.get("dmg") or 0
        total = max(0, gross - (node.get("healed") or 0))
        out[i] = {"taken": (total + 1) / (how["taken"] + 1), "turns": node["turns"] / how["turns"]}
    return out


def series_from_page(page):
    return page.evaluate("""() => {
      const c = detailKeepCharts.find(x => x.canvas.id === 'detail-keep-share-chart');
      if (!c) return null;
      return {
        plugins: c.config.plugins.map(p => p.id),
        yMin: c.scales.y.min,
        datasets: c.data.datasets.map(d => ({label: d.label, data: d.data})),
        legend: document.getElementById('detail-keep-share-legend').innerText,
        caption: document.getElementById('detail-keep-share-picks').style.display,
      };
    }""")


def tick_kinds(page):
    """What the tick painter is handed for each kind of change: colour, and the markers that
    say removed (down) or upgraded (hollow)."""
    return page.evaluate("""() => {
      const one = type => Object.keys(DATA.cardData).find(id => DATA.cardData[id].type === type);
      const add = id => choiceTick({cards: [[id, false, 1]], relics: []});
      return {
        Attack: add(one('Attack')), Skill: add(one('Skill')), Power: add(one('Power')), Curse: add(one('Curse')),
        removed: choiceTick({cards: [[one('Attack'), false, -1]], relics: []}),
        upgraded: choiceTick({cards: [[one('Skill'), true, 0]], relics: []}),
        relic: choiceTick({cards: [], relics: [['RELIC.ANCHOR', false, 1]]}),
      };
    }""")


def main():
    if not RUN_FILE.exists() or not DEMAND.exists():
        print("skipped: needs splitswigs' local profile and fight_demand.json")
        return
    demand = json.loads(DEMAND.read_text(encoding="utf-8"))["encounters"]
    want = expected_series(load_run(), demand)
    assert len(want) >= 10, f"only {len(want)} fights to check"

    with sync_playwright() as p:
        for name, engine, device in [
            ("desktop-1920", "chromium", {"viewport": {"width": 1920, "height": 1080}}),
            ("iphone-16-portrait", "webkit", p.devices["iPhone 16"]),
            ("iphone-16-landscape", "webkit", p.devices["iPhone 16 landscape"]),
        ]:
            browser = getattr(p, engine).launch()
            page = browser.new_page(**device)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(URL)
            if not page.locator("#detail-keep-share-chart").count():
                page.evaluate(f"location.hash = '#detail/{RUN_TS}'")
            page.wait_for_selector("#detail-keep-share-chart", state="attached", timeout=20000)
            page.wait_for_function("() => typeof detailKeepCharts !== 'undefined' && detailKeepCharts.some(c => c.canvas.id === 'detail-keep-share-chart')")

            got = series_from_page(page)
            assert got, "the share chart did not render"
            assert "choiceTicks" in got["plugins"], got["plugins"]
            assert got["yMin"] == 0, got["yMin"]
            labels = [d["label"] for d in got["datasets"]]
            assert labels == ["Average win", "Damage taken", "Fight turns"], labels
            assert "Damage taken" in got["legend"] and "Fight turns" in got["legend"], got["legend"]
            assert got["caption"] == "", "the tick caption should show when the run changed cards"

            taken = got["datasets"][1]["data"]
            turns = got["datasets"][2]["data"]
            for i, row in want.items():
                assert taken[i] is not None and abs(taken[i] - row["taken"]) < 1e-6, (i, taken[i], row)
                assert turns[i] is not None and abs(turns[i] - row["turns"]) < 1e-6, (i, turns[i], row)

            counts = tick_kinds(page)
            assert counts["Attack"]["color"] == "#d25030", counts
            assert counts["Skill"]["color"] == "#40a35c", counts
            assert counts["Power"]["color"] == "#8459c3", counts
            assert counts["Curse"]["color"] == "#b83b76", counts
            assert counts["removed"]["dir"] == -1 and counts["removed"]["color"] == "#9a9aae", counts
            assert counts["upgraded"]["hollow"] and counts["upgraded"]["color"] == "#40a35c", counts
            assert counts["relic"]["color"] == "#cfcbe0", counts

            assert page.evaluate("document.documentElement.scrollWidth - window.innerWidth <= 20")
            if device.get("has_touch"):
                assert page.locator("#detail-keep-actpick button").count() >= 1
                chart = page.evaluate("""() => {
                  const c = detailKeepCharts.find(x => x.canvas.id === 'detail-keep-share-chart');
                  return {min: c.options.scales.x.min, max: c.options.scales.x.max, w: c.canvas.clientWidth,
                          wrap: document.getElementById('detail-keep-share-chart').closest('.chart-wrap').clientWidth,
                          narrow: matchMedia('(max-width: 700px)').matches};
                }""")
                assert chart["w"] <= chart["wrap"] + 1, chart
                if chart["narrow"]:
                    assert chart["min"] is not None and chart["max"] is not None, chart
            assert not errors, errors
            print(f"{name}: series, ticks, legend and layout passed.")
            page.close()
            browser.close()


if __name__ == "__main__":
    main()
