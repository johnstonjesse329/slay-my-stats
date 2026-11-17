"""Every per-character view lists the whole roster, even a character with no runs.

Loads a profile in the local preview, removes every run of one character (the zero-runs case),
re-renders, and fails naming each section that no longer lists that character. Run it after
any change to a chart, table or lane, with the preview up:

    python tools/serve_site.py --port 8095     # from a folder with the Steam ID in its path
    python tools/test_roster.py [http://localhost:8095/u/splitswigs#overview] [CHARACTER]
"""
import sys
from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8095/u/splitswigs#overview"
GONE = sys.argv[2] if len(sys.argv) > 2 else "FOOL"
SECTIONS = ["personal-bests-cards", "asc-readings-chart", "time-lanes", "run-end-lanes",
            "final-boss-win-table", "asc-tracker-cards"]

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1920, "height": 1080})
    page.goto(URL, wait_until="networkidle")
    page.wait_for_function("typeof updateAll === 'function' && DATA.runsData.length")
    result = page.evaluate("""async (gone) => {
      DATA.runsData = DATA.runsData.filter(run => run.char !== gone);
      updateAll();
      await new Promise(r => setTimeout(r, 300));
      const label = char => fmtCharName(char).toLowerCase();
      const missing = {};
      for (const id of %s) {
        const el = document.getElementById(id);
        const text = el ? el.innerText.toLowerCase() : null;
        missing[id] = text === null ? ['(section not found)'] : DATA.characters.filter(c => !text.includes(label(c)));
      }
      const charts = (window.Chart && Chart.instances) ? Object.values(Chart.instances) : [];
      const sets = charts.map(c => ({id: c.canvas.id, labels: (c.data.datasets || []).map(d => d.label)}))
        .filter(c => c.labels.some(l => DATA.characters.some(ch => label(ch) === String(l).toLowerCase())));
      const chartMissing = sets.map(c => ({id: c.id, missing: DATA.characters.filter(ch => !c.labels.map(l => String(l).toLowerCase()).includes(label(ch)))}));
      return {missing, chartMissing, roster: DATA.characters};
    }""" % SECTIONS, GONE)
    browser.close()

bad = {k: v for k, v in result["missing"].items() if v}
bad.update({"chart " + c["id"]: c["missing"] for c in result["chartMissing"] if c["missing"]})
print("roster:", result["roster"], "| runs of", GONE, "removed")
if bad:
    for section, chars in bad.items():
        print("MISSING in", section, ":", chars)
    sys.exit(1)
print("ok: all", len(result["roster"]), "characters listed in", len(SECTIONS), "sections and",
      len(result["chartMissing"]), "charts")
