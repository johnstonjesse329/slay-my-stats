"""Exercise feedback with an isolated mocked inbox at the required device sizes."""
import json
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    with sync_playwright() as pw:
        for name, engine, options in [('desktop', pw.chromium, {'viewport': {'width': 1920, 'height': 1080}}),
                ('iphone-portrait', pw.webkit, pw.devices['iPhone 16']),
                ('iphone-landscape', pw.webkit, pw.devices['iPhone 16 landscape'])]:
            browser = engine.launch()
            context = browser.new_context(**options)
            notes, errors = [{'id': 'feedback/1234567890-' + 'b' * 32 + '.json', 'created': 1780000000,
                              'author': 'test', 'resolved': False, 'comment': 'Elsewhere',
                              'path': '/u/elsewhere', 'url': 'https://gamma.slay-my-stats.com/u/elsewhere',
                              'target': {'kind': 'page'}}], []

            def route(request):
                url = urlsplit(request.request.url)
                if url.path == '/auth/feedback':
                    if request.request.method == 'POST':
                        body = request.request.post_data_json
                        if body.get('action') == 'resolve':
                            note = next(item for item in notes if item['id'] == body['id'])
                            note['resolved'] = body['resolved']
                        else:
                            note = {**body, 'id': 'feedback/' + str(1800000000 + len(notes)) + '-' + 'a' * 32 + '.json',
                                    'created': 1800000000 + len(notes), 'author': 'test', 'resolved': False}
                            notes.append(note)
                        request.fulfill(json={'note': note})
                    else:
                        params = dict(parse_qsl(url.query))
                        shown = [item for item in notes
                                 if params.get('scope') != 'page' or item['path'] == params.get('path')]
                        request.fulfill(json={'notes': shown, 'next': None, 'scope': params.get('scope', 'site')})
                    return
                file = ROOT / 'dist' / ('index.html' if url.path == '/' else url.path.lstrip('/'))
                if file.is_file():
                    request.fulfill(path=str(file))
                else:
                    request.fulfill(status=404, body='{}')

            context.route('https://gamma.slay-my-stats.com/**', route)
            page = context.new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto('https://gamma.slay-my-stats.com/')
            page.get_by_role('button', name='Feedback', exact=True).click()
            page.get_by_role('button', name='Comment on the page', exact=True).click()
            assert page.locator('#page-url').inner_text() == 'https://gamma.slay-my-stats.com/'
            page.get_by_label('What should change?').fill('Make this clearer')
            page.get_by_role('button', name='Send', exact=True).click()
            page.get_by_text('Sent. Everyone on gamma can see it.').wait_for()
            created = next(item for item in notes if item['path'] == '/')
            assert created['url'] == 'https://gamma.slay-my-stats.com/', created
            assert page.locator('#inbox-count').text_content() == '1'
            # The inbox is its own panel: "This page" is the default scope, and the
            # note seeded on another page only appears under "Whole site".
            page.get_by_role('button', name='Inbox', exact=True).click()
            page.get_by_text('1 note · 1 open · 1 place', exact=True).wait_for()
            assert page.locator('.bucket').count() == 1
            assert 'Whole page' in page.locator('.bucket summary').first.inner_text()
            assert page.locator('.note-url').first.inner_text() == 'https://gamma.slay-my-stats.com/'
            page.get_by_role('button', name='Whole site', exact=True).click()
            page.get_by_text('2 notes · 2 open · 2 places', exact=True).wait_for()
            assert page.locator('.bucket').count() == 2
            page.get_by_role('button', name='This page', exact=True).click()
            page.get_by_text('1 note · 1 open · 1 place', exact=True).wait_for()
            page.get_by_role('button', name='Resolve', exact=True).click()
            page.get_by_role('button', name='Reopen', exact=True).click()
            page.get_by_role('button', name='Resolve', exact=True).wait_for()
            page.locator('#inbox-close').click()
            page.get_by_role('button', name='Feedback', exact=True).click()
            page.get_by_role('button', name='Pin to an element or region', exact=True).click()
            heading = page.locator('h1:visible, h2:visible').first
            heading.click()
            page.get_by_text('Element:', exact=False).first.wait_for()
            page.get_by_label('What should change?').fill('Pinned comment')
            page.get_by_role('button', name='Send', exact=True).click()
            page.get_by_text('1 earlier note here', exact=False).wait_for()
            assert 'Pinned comment' in page.locator('#prior').inner_text()
            assert page.locator('#inbox-count').text_content() == '2'
            page.get_by_role('button', name='Inbox', exact=True).click()
            page.get_by_text('2 notes · 2 open · 2 places', exact=True).wait_for()
            assert page.locator('.bucket').count() == 2, page.locator('.bucket summary').all_inner_texts()
            assert any('Whole page' in text for text in page.locator('.bucket summary').all_inner_texts())
            panel = page.get_by_role('dialog', name='Feedback inbox')
            bounds = panel.bounding_box()
            assert bounds['x'] >= 0 and bounds['y'] >= 0
            assert bounds['x'] + bounds['width'] <= page.evaluate('innerWidth')
            assert bounds['y'] + bounds['height'] <= page.evaluate('innerHeight')
            page.locator('#inbox-close').click()
            page.get_by_role('button', name='Feedback', exact=True).click()
            page.get_by_role('button', name='Pin to an element or region', exact=True).click()
            page.mouse.move(80, 320)
            page.mouse.down()
            page.mouse.move(300, 410, steps=5)
            page.mouse.up()
            page.get_by_text('Region:', exact=False).first.wait_for()
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