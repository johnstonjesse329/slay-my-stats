"""Check the built local synergy explorer on desktop and mobile.

Run with infra/.venv/Scripts/python tools/test_synergy_explorer.py
Requires tools/serve_site.py on port 8123 and synced local profiles.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def capture_explorer(page, path):
    # Full-element screenshots don't reliably trigger offscreen lazy art in WebKit.
    page.locator('.synergy-explorer img').evaluate_all("imgs => imgs.forEach(img => img.loading = 'eager')")
    page.wait_for_function("Array.from(document.querySelectorAll('.synergy-explorer img')).every(img => img.complete && img.naturalWidth > 0)")
    page.locator('.synergy-explorer').screenshot(path=str(path), scale='css')


def main():
    with sync_playwright() as p:
        cases = [("desktop-1920", "chromium", {"viewport": {"width": 1920, "height": 1080}}),
                 ("iphone-16-portrait", "webkit", p.devices["iPhone 16"]),
                 ("iphone-16-landscape", "webkit", p.devices["iPhone 16 landscape"])]
        for name, engine, device in cases:
            browser = getattr(p, engine).launch()
            page = browser.new_page(**device)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto("http://127.0.0.1:8123/u/milworkz#detail/1794716014")
            page.wait_for_selector(".synergy-archetype")
            assert page.locator(".synergy-archetype[open]").count() == 0
            shots = page.locator(".synergy-archetype").filter(has=page.locator(".synergy-group-title", has_text="Shots"))
            shots.locator(":scope > summary").click()
            aim = shots.locator(".synergy-connection").first
            assert aim.locator(".synergy-flow").is_visible()
            assert aim.locator(".synergy-reason").is_visible()
            assert aim.locator("details").count() == 0
            synergy_face = aim.get_by_role("button", name="Inspect Heavy Shot", exact=True).locator(".cardface")
            deck_face = page.locator('.deck-tile-row .cardface[alt="Heavy Shot"]').first
            assert synergy_face.is_visible()
            if name == 'desktop-1920':
                assert abs(synergy_face.bounding_box()["width"] - deck_face.bounding_box()["width"]) < 1
            else:
                assert aim.locator('.synergy-items').first.evaluate("el => getComputedStyle(el).gridTemplateColumns.split(' ').length === 3")
                assert synergy_face.bounding_box()['width'] <= deck_face.bounding_box()['width'] + 1
            assert synergy_face.get_attribute('src') == deck_face.get_attribute('src')
            for role in ("Song Bow", "Heavy Shot"):
                item = aim.get_by_role("button", name="Inspect " + role, exact=True)
                if not device.get("has_touch"):
                    item.hover()
                    tooltip = page.locator(".chart-tooltip-rich")
                    assert tooltip.is_visible()
                    assert tooltip.evaluate("el => getComputedStyle(el).opacity === '1'")
                    assert tooltip.locator("img").count() > 0
                item.click()
                dialog = page.get_by_role("dialog")
                assert dialog.is_visible()
                assert dialog.locator("img").count() > 0
                page.keyboard.press("Tab")
                assert page.get_by_role("button", name="Close preview").evaluate("el => el === document.activeElement")
                page.keyboard.press("Escape")
                assert page.get_by_role("dialog").count() == 0
                assert item.evaluate("el => el === document.activeElement")
            sadness = page.locator(".synergy-archetype").filter(has=page.locator(".synergy-group-title", has_text="Sadness"))
            sadness.locator(":scope > summary").click()
            assert page.locator(".synergy-archetype[open]").count() == 2
            if name == "desktop-1920":
                assert shots.bounding_box()["width"] >= page.locator(".synergy-groups").bounding_box()["width"] * .98
                face = aim.locator(".synergy-item-face .cardface").first
                assert face.is_visible() and face.bounding_box()["width"] >= 170
            # Expanding/collapsing preserves one ordered column, including x positions.
            assert page.locator(".synergy-archetype").evaluate_all("els => els.every((el, i) => !i || (Math.abs(el.getBoundingClientRect().x - els[i-1].getBoundingClientRect().x) < 1 && el.getBoundingClientRect().top >= els[i-1].getBoundingClientRect().bottom))")
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.locator(".synergy-archetype").evaluate_all("els => els.forEach(el => el.open = true)")
            page.mouse.move(0, 0)
            page.evaluate("hideSharedTooltip(); document.activeElement.blur()")
            capture_explorer(page, ROOT / f"local_data/synergy-explorer-{name}.png")
            # Every live connection survives grouping for all six characters.
            counts = page.evaluate("""() => Object.keys(DATA.archetypes).map(character => {
              const deck = Object.entries(DATA.cardData).filter(([,c]) => c.pool === character).map(([id]) => ({id,upgrade:0}));
              const holder = document.createElement('div');
              holder.innerHTML = renderDeckLinksHtml(deck, [], character);
              return {character, expected:deckLinks(deck, []).length, actual:holder.querySelectorAll('.synergy-connection').length};
            })""")
            assert len(counts) == 6, counts
            assert all(c["actual"] == c["expected"] and c["actual"] > 0 for c in counts), counts
            # Every connection uses the same source/payoff alignment, regardless of counts.
            page.goto("about:blank")
            page.goto("http://127.0.0.1:8123/u/milworkz#detail/1791694088")
            page.wait_for_selector(".synergy-archetype")
            page.locator(".synergy-archetype").evaluate_all("els => els.forEach(el => el.open = true)")
            shiv = page.locator(".synergy-archetype").filter(has=page.locator(".synergy-group-title", has_text="Shiv"))
            lanes = shiv.locator(".synergy-flow > div")
            if name == "desktop-1920":
                assert page.locator('.synergy-flow > div:last-child').evaluate_all('els => els.every(e => Math.abs(e.getBoundingClientRect().left - els[0].getBoundingClientRect().left) < 1)')
                strip = lanes.nth(0).locator(".synergy-items")
                assert strip.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            capture_explorer(page, ROOT / f"local_data/synergy-sparse-payoffs-{name}.png")
            page.goto("about:blank")
            page.goto("http://127.0.0.1:8123/u/milworkz#detail/1794711851")
            page.wait_for_selector(".synergy-archetype")
            page.locator(".synergy-archetype").evaluate_all("els => els.forEach(el => el.open = true)")
            assert page.locator(".synergy-group-title").filter(has_text="Orbs").count() == 0
            assert page.locator(".synergy-connection-heading").filter(has_text="Lightning focus").count() == 1
            assert page.locator(".synergy-items").evaluate_all("els => els.every(el => el.scrollWidth <= el.clientWidth + 1)")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            if name == "desktop-1920":
                assert page.locator(".synergy-flow > div:last-child .synergy-items").evaluate_all("els => els.every(el => getComputedStyle(el).gridTemplateColumns.split(' ').length <= 3)")
            page.locator('.synergy-explorer img').evaluate_all("imgs => imgs.forEach(img => img.loading = 'eager')")
            page.wait_for_function("Array.from(document.querySelectorAll('.synergy-explorer img')).every(img => img.complete && img.naturalWidth > 0)")
            page.locator(".synergy-archetype").first.screenshot(path=str(ROOT / f"local_data/synergy-orbs-{name}.png"), scale="css")
            assert not errors, errors
            print(f"{name}: groups, card/relic inspection, keyboard, overflow, and all six characters passed.")
            page.close()
            browser.close()


if __name__ == "__main__":
    main()
