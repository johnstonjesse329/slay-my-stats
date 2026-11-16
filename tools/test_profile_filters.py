"""Playwright regression checks for Overview scope and saved/shared filters.

    infra/.venv/Scripts/python tools/test_profile_filters.py --local-assets
    infra/.venv/Scripts/python tools/test_profile_filters.py --base https://gamma.slay-my-stats.com

Read-only against the site: changes only isolated browser storage. --local-assets
serves the built HTML/JS/CSS from dist while reading public profile data remotely.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="https://slay-my-stats.com")
    parser.add_argument("--local-assets", action="store_true")
    parser.add_argument("--other-profile", default="sikigamiizumo")
    args = parser.parse_args()
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        def context():
            ctx = browser.new_context(viewport={"width": 1440, "height": 1100},
                                      permissions=["clipboard-read", "clipboard-write"])
            if args.local_assets:
                def route(request):
                    path = urlsplit(request.request.url).path
                    asset = ROOT / "dist" / ("index.html" if path.startswith("/u/") else path.lstrip("/"))
                    if not path.startswith("/users/") and asset.is_file():
                        request.fulfill(path=str(asset))
                    else:
                        request.continue_()
                ctx.route(args.base + "/**", route)
            return ctx

        ctx = context()
        page = ctx.new_page()
        page.on("pageerror", lambda error: errors.append(error.stack))
        page.on("console", lambda message: print(message.text) if message.type == "warning" else None)

        def load(slug="splitswigs", query=""):
            page.goto("about:blank")
            page.goto(f"{args.base}/u/{slug}{query}#overview")
            page.wait_for_selector(".asc-readings-char")
            assert page.locator("#shared-filter-bar").is_visible()
            assert page.locator("#shared-filter-bar").evaluate("e => e.classList.contains('filters-locked')")
            assert page.locator("#shared-filters-reset").is_disabled()
            characters = page.evaluate("new Set(overviewRuns().map(r => r.char)).size")
            assert page.locator(".pb-table thead th").count() == characters + (2 if characters > 1 else 1)
            assert page.locator(".asc-readings-char").count() == characters

        def tab(name):
            page.locator(f"#tab-{name}").click()

        def expand():
            if page.locator("#shared-filter-summary").get_attribute("aria-expanded") != "true":
                page.locator("#shared-filter-summary").click()

        load()
        full_stats = page.locator(".pb-table").inner_text()
        total_runs = page.evaluate("DATA.runsData.length")
        standard_runs = page.evaluate("overviewRuns().length")
        tab("detail")
        assert "Default filters applied" in page.locator("#shared-filter-summary").inner_text()
        assert not page.locator("#shared-filter-bar").evaluate("e => e.classList.contains('filters-active')")
        assert page.locator("#shared-filter-presets").input_value() == "default"
        tab("overview")
        assert "Daily" in page.locator("#overview-history-summary").inner_text()
        state = page.evaluate("({...currentSharedFilterState(), builds:['v0.107.1'], allBuilds:false})")
        page.evaluate("state => localStorage.setItem('sts2_filter_prefs', JSON.stringify(state))", state)
        load()
        assert page.locator(".pb-table").inner_text() == full_stats
        tab("detail")
        assert page.locator(".detail-run-item").count() == 34, page.evaluate("({state:currentSharedFilterState(), rows:document.querySelectorAll('.detail-run-item').length})")
        assert f"34 of {total_runs}" in page.locator("#shared-filter-summary").inner_text()
        assert "v0.107.1" in page.locator("#shared-filter-summary").inner_text()
        tab("overview")
        assert page.locator(".pb-table").inner_text() == full_stats
        tab("detail")
        assert page.locator(".detail-run-item").count() == 34
        expand()
        assert page.locator("#shared-filter-bar > .filter-row").last.evaluate("e => e.classList.contains('filter-preset-toolbar')")
        assert page.locator("#shared-filter-presets").input_value() == ""
        assert page.locator("#shared-filter-presets option").first.inner_text() == "Default"
        assert "Custom" not in page.locator("#shared-filter-presets option").all_text_contents()
        page.locator("#shared-filter-preset-name").fill("Patch 107")
        page.locator("#shared-filter-preset-save").click()
        assert page.locator("#shared-filter-presets").input_value() == "preset:Patch 107"
        page.locator("#shared-players-solo").click()
        assert page.locator("#shared-filter-presets").input_value() == ""
        assert page.locator("#shared-filters-unsaved").is_visible()
        assert page.locator("#shared-filters-unsaved").text_content() == "!"
        page.locator("#shared-players-all").click()
        assert page.locator("#shared-filter-presets").input_value() == "preset:Patch 107"
        page.locator("#shared-filter-copy-link").click()
        page.wait_for_function("location.search.includes('filters=')")
        shared_url = page.url
        fresh = context()
        linked = fresh.new_page()
        linked.goto(shared_url)
        linked.wait_for_selector(".detail-run-item")
        assert linked.locator(".detail-run-item").count() == 34
        assert linked.evaluate("localStorage.getItem('sts2_filter_prefs')") is None
        fresh.close()
        page.locator("#shared-filters-reset").click()
        assert page.evaluate("localStorage.getItem('sts2_filter_prefs')") is None
        assert "filters=" not in page.url
        load()
        tab("detail")
        assert page.locator(".detail-run-item").count() == standard_runs
        expand()
        page.locator("#shared-filter-presets").select_option("preset:Patch 107")
        assert page.locator(".detail-run-item").count() == 34
        page.locator("#shared-filter-preset-delete").click()
        assert page.locator("#shared-filter-presets option").count() == 2
        assert page.locator("#shared-filter-preset-name").input_value() == ""
        # A saved preset matching built-in defaults must keep its identity,
        # so Delete removes that preset rather than acting on "default".
        page.locator("#shared-filter-presets").select_option("default")
        page.locator("#shared-filter-preset-name").fill("Everyday")
        page.locator("#shared-filter-preset-save").click()
        assert page.locator("#shared-filter-presets").input_value() == "preset:Everyday"
        page.locator("#shared-filter-preset-delete").click()
        assert "Everyday" not in page.locator("#shared-filter-presets option").all_text_contents()
        assert page.evaluate("JSON.parse(localStorage.getItem('sts2_filter_presets')).length") == 0
        load()
        tab("detail")
        expand()
        assert "Everyday" not in page.locator("#shared-filter-presets option").all_text_contents()
        assert page.locator("#shared-filters-save").inner_text() == "Save as default"
        assert page.locator("#shared-filters-reset").evaluate("e => !e.parentElement.contains(document.getElementById('shared-filter-preset-name'))")
        # Another profile has no runs from the saved build: use all its builds.
        page.evaluate("state => localStorage.setItem('sts2_filter_prefs', JSON.stringify(state))",
                      {**state, "builds": ["unavailable-build"]})
        load(args.other_profile)
        tab("detail")
        assert page.locator(".detail-run-item").count() == page.evaluate("overviewRuns().length")
        # All builds means all future builds, even with an older saved list.
        all_state = {**state, "allBuilds": True}
        page.evaluate("state => localStorage.setItem('sts2_filter_prefs', JSON.stringify(state))", all_state)
        load()
        tab("detail")
        assert page.locator(".detail-run-item").count() == standard_runs
        # URL wins over saved defaults; intentional empty selection remains empty.
        empty = {**state, "builds": [], "char": "FOOL", "players": "multi",
                 "modes": [], "mods": "modded", "ascGranular": True, "ascs": [],
                 "tsFrom": 4102444800, "tsTo": 4102531200}
        load(query="?" + urlencode({"filters": json.dumps(empty)}))
        assert page.locator(".pb-table").inner_text() == full_stats
        tab("detail")
        assert page.locator(".detail-run-item").count() == 0
        assert f"0 of {total_runs} runs" in page.locator("#shared-filter-summary").inner_text()
        load(query="?filters=invalid-json")
        assert not errors, errors
        # Visual checks at both sizes with a restricted selection.
        load()
        tab("detail")
        page.evaluate("state => {applySharedFilterState(state); rerenderCurrentPage();}", state)
        expand()
        (ROOT / "local_data").mkdir(exist_ok=True)
        page.screenshot(path=str(ROOT / "local_data/filter-presets-desktop.png"))
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(ROOT / "local_data/filter-presets-mobile.png"))
        assert page.locator("#shared-filter-summary").is_visible()
        assert page.locator("#shared-filter-summary").bounding_box()["width"] <= 390
        browser.close()
    print("PASS: Overview ignores filters; selections survive tabs; reset persists; presets, links, cross-profile builds, empty states and mobile layout work.")


if __name__ == "__main__":
    main()
