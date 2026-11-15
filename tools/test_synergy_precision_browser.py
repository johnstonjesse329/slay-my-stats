"""Verify the precision pass on real runs at the project's review baselines.

Requires synced local profiles and tools/serve_site.py on port 8123.
Run with infra/.venv/Scripts/python tools/test_synergy_precision_browser.py.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
RUNS = [
    ('ironclad', 'rightneow', 1789961608, 'Exhaust', ['exhaust', 'exhaust skills', 'exhaust attacks', 'card Block', 'power:Strength']),
    ('silent', 'smallpurplemexican', 1794516659, 'Discard', ['discard', 'shiv', 'power:Poison']),
    ('necrobinder', 'sikigamiizumo', 1791364375, 'Osty', ['Osty health', 'Osty attacks', 'Osty damage', 'souls', 'ethereal']),
    ('regent', 'sikigamiizumo', 1791767642, 'Stars', ['stars', 'star spending', 'star-cost cards', 'forge', 'creation']),
]


def main():
    with sync_playwright() as p:
        for name, engine, device in [
            ('desktop', p.chromium, {'viewport': {'width': 1920, 'height': 1080}}),
            ('portrait', p.webkit, p.devices['iPhone 16']),
            ('landscape', p.webkit, p.devices['iPhone 16 landscape']),
        ]:
            browser = engine.launch()
            for char, slug, ts, family, keys in RUNS:
                page = browser.new_page(**device)
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:8123/u/{slug}#detail/{ts}')
                page.wait_for_selector('.synergy-archetype')
                # Verify runtime rows, not just union catalog metadata.
                links = page.evaluate('''({ts}) => {
                    const r = DATA.runsData.find(r => r.ts === ts);
                    return deckLinks(r.finalDeck || [], r.finalRelics || []).map(l => l.key);
                }''', {'ts': ts})
                assert set(keys) <= set(links), (char, links)
                assert not {'osty', 'orbs', 'power:Confused', 'power:Parry', 'power:SeekingEdge'} & set(links)
                assert page.evaluate('''() => {
                  const keys = ids => deckLinks(ids.map(id => ({id,upgrade:0})), []).map(l => l.key);
                  return !keys(['CARD.WELL_LAID_PLANS','CARD.TACTICIAN']).includes('discard')
                    && keys(['CARD.ACROBATICS','CARD.TACTICIAN']).includes('discard')
                    && !keys(['CARD.BODYGUARD','CARD.POKE']).includes('Osty health')
                    && keys(['CARD.AFTERLIFE','CARD.UNLEASH']).includes('Osty health')
                    && keys(['CARD.CALCIFY','CARD.POKE']).includes('Osty damage')
                    && !keys(['CARD.NEUROSURGE','CARD.TIMES_UP','CARD.SHROUD']).includes('power:Doom')
                    && keys(['CARD.NEUROSURGE','CARD.TIMES_UP','CARD.SHROUD']).includes('Doom application')
                    && !keys(['CARD.GLOW','CARD.CHILD_OF_THE_STARS']).includes('star spending')
                    && keys(['CARD.COMET','CARD.CHILD_OF_THE_STARS']).includes('star spending');
                }''')
                panel = page.locator('.synergy-archetype').filter(has=page.locator('.synergy-group-title', has_text=family))
                panel.locator(':scope > summary').click()
                assert page.locator('.synergy-items:visible').evaluate_all('els => els.every(e => e.scrollWidth <= e.clientWidth + 1)')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                # A base card never inherits an upgrade-only zero-cost synergy.
                assert not page.evaluate('''() => deckLinks([{id:'CARD.ZAP',upgrade:0},{id:'CARD.ALL_FOR_ONE',upgrade:0}], []).some(l => l.key === 'zero-cost')''')
                assert page.evaluate('''() => deckLinks([{id:'CARD.ZAP',upgrade:1},{id:'CARD.ALL_FOR_ONE',upgrade:0}], []).some(l => l.key === 'zero-cost')''')
                # Collapse/reopen keeps the same family order and left edge.
                order = page.locator('.synergy-group-title').all_text_contents()
                panel.locator(':scope > summary').click()
                panel.locator(':scope > summary').click()
                assert order == page.locator('.synergy-group-title').all_text_contents()
                assert page.locator('.synergy-archetype').evaluate_all('els => els.every((e,i) => !i || (Math.abs(e.getBoundingClientRect().left - els[i-1].getBoundingClientRect().left) < 1 && e.getBoundingClientRect().top >= els[i-1].getBoundingClientRect().bottom))')
                page.mouse.move(0, 0)
                page.evaluate('hideSharedTooltip(); document.activeElement.blur()')
                page.locator('.synergy-explorer').screenshot(path=str(ROOT / f'local_data/precision-{char}-{name}.png'), scale='css')
                assert not errors, errors
                print(f'{name}: {char} precision and stable layout passed.')
                page.close()
            browser.close()


if __name__ == '__main__':
    main()
