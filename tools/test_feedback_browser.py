"""Exercise feedback with an isolated mocked inbox at the required device sizes."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    with sync_playwright() as pw:
        for name, engine, options in [('desktop', pw.chromium, {'viewport': {'width': 1920, 'height': 1080}}),
                ('iphone-portrait', pw.webkit, pw.devices['iPhone 16']),
                ('iphone-landscape', pw.webkit, pw.devices['iPhone 16 landscape'])]:
            browser = engine.launch()
            context = browser.new_context(**options)
            notes, errors = [], []

            def route(request):
                path = urlsplit(request.request.url).path
                if path == '/auth/feedback':
                    if request.request.method == 'POST':
                        body = request.request.post_data_json
                        if body.get('action') == 'resolve':
                            notes[0]['resolved'] = body['resolved']
                        else:
                            notes.append({**body, 'id': 'feedback/1234567890-'+'a'*32+'.json',
                                          'created': 1790000000, 'author': 'test', 'resolved': False})
                        request.fulfill(json={'note': notes[0]})
                    else:
                        request.fulfill(json={'notes': notes})
                    return
                file = ROOT / 'dist' / ('index.html' if path == '/' else path.lstrip('/'))
                if file.is_file():
                    request.fulfill(path=str(file))
                else:
                    request.fulfill(status=404, body='{}')

            context.route('https://gamma.slay-my-stats.com/**', route)
            page = context.new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto('https://gamma.slay-my-stats.com/')
            page.get_by_role('button', name='Feedback', exact=True).click()
            page.get_by_role('button', name='Whole page', exact=True).click()
            assert page.locator('#page-url').inner_text() == 'https://gamma.slay-my-stats.com/'
            page.get_by_label('What should change?').fill('Make this clearer')
            page.get_by_role('button', name='Send feedback').click()
            page.get_by_text('Feedback sent to the shared inbox.').wait_for()
            assert notes[0]['url'] == 'https://gamma.slay-my-stats.com/', notes[0]
            page.get_by_role('button', name='Inbox', exact=True).click()
            page.get_by_text('1 latest note · 1 place', exact=True).wait_for()
            assert page.locator('.bucket').count() == 1
            assert 'Whole page' in page.locator('.bucket summary').first.inner_text()
            assert page.locator('.note-url').first.inner_text() == 'https://gamma.slay-my-stats.com/'
            page.get_by_role('button', name='Resolve', exact=True).click()
            page.get_by_role('button', name='Reopen', exact=True).click()
            page.get_by_role('button', name='Resolve', exact=True).wait_for()
            page.get_by_role('button', name='Pin to element / region').click()
            heading = page.locator('h1:visible, h2:visible').first
            heading.click()
            page.get_by_text('Pinned element:', exact=False).wait_for()
            page.get_by_label('What should change?').fill('Pinned comment')
            page.get_by_role('button', name='Send feedback').click()
            page.get_by_text('1 earlier note here', exact=False).wait_for()
            assert 'Pinned comment' in page.locator('#prior').inner_text()
            assert page.locator('#launcher-count').text_content() == '2'
            page.get_by_role('button', name='Inbox', exact=True).click()
            page.get_by_text('2 latest notes · 2 places', exact=True).wait_for()
            assert page.locator('.bucket').count() == 2, page.locator('.bucket summary').all_inner_texts()
            assert any('Whole page' in text for text in page.locator('.bucket summary').all_inner_texts())
            if name == 'desktop':
                page.get_by_role('button', name='Pin to element / region').click()
                page.mouse.move(80, 320)
                page.mouse.down()
                page.mouse.move(300, 410, steps=5)
                page.mouse.up()
                page.get_by_text('Pinned region:', exact=False).wait_for()
            panel = page.get_by_role('dialog', name='Gamma feedback')
            bounds = panel.bounding_box()
            assert bounds['x'] >= 0 and bounds['y'] >= 0
            assert bounds['x'] + bounds['width'] <= page.evaluate('innerWidth')
            assert bounds['y'] + bounds['height'] <= page.evaluate('innerHeight')
            output = ROOT / '.playwright-mcp' / f'feedback-{name}.png'
            output.parent.mkdir(exist_ok=True)
            page.screenshot(path=str(output))
            assert not errors, errors
            print(f'{name}: passed; {output}')
            browser.close()


if __name__ == '__main__':
    main()
