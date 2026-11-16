"""Exercise feedback with an isolated mocked inbox at the required device sizes."""
import json
import os
from pathlib import Path
from urllib.parse import parse_qsl, quote as urlquote, urlsplit
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DIST = Path(os.environ.get('FEEDBACK_TEST_DIST') or ROOT / 'dist')  # a copy of dist/ can stand in


def summary(page):
    return page.evaluate(r"""() => {
        const root = document.getElementById('gamma-feedback').shadowRoot;
        return root.getElementById('summary').textContent.replace(/\s+/g, ' ').trim();
    }""")


def wait_summary(page, text):
    page.wait_for_function("expected => document.getElementById('gamma-feedback').shadowRoot"
                           ".getElementById('summary').textContent.replace(/\\s+/g, ' ').trim() === expected",
                           arg=text)


def check_note_layout(page, notes, name):
    """Author and time sit in the same place on every note, named or not, typed or not, open or
    resolved; a name seen once is not lost when a later response has none."""
    for item in notes:
        item['resolved'] = True
    steam = 'player-0002'
    notes[:] = [
        {'id': 'feedback/1800001000-' + 'c' * 32 + '.json', 'created': 1800001000, 'author': steam,
         'author_name': 'Jess', 'resolved': False, 'category': 'bug', 'comment': 'Typed, named. ' + 'long ' * 30,
         'path': '/', 'url': 'https://gamma.slay-my-stats.com/', 'target': {'kind': 'page'}},
        {'id': 'feedback/1800000900-' + 'd' * 32 + '.json', 'created': 1800000900, 'author': steam,
         'resolved': False, 'comment': 'Old note, no type, name lookup failed',
         'path': '/', 'url': 'https://gamma.slay-my-stats.com/', 'target': {'kind': 'page'}},
        {'id': 'feedback/1800000800-' + 'e' * 32 + '.json', 'created': 1800000800, 'author': 'player-7252',
         'resolved': True, 'resolved_by': steam, 'outcome': 'done', 'close_note': 'ok', 'resolved_in': 'abc1234',
         'category': 'feature', 'comment': 'Resolved, stranger without a name',
         'path': '/', 'url': 'https://gamma.slay-my-stats.com/', 'target': {'kind': 'page'}},
    ]
    page.get_by_role('tab', name='New note', exact=True).click()
    page.get_by_role('tab', name='Inbox', exact=True).click()
    page.get_by_label('Status').select_option('all')
    wait_summary(page, '3 notes · 2 open · 1 place')
    boxes = page.evaluate(r"""() => {
        const root = document.getElementById('gamma-feedback').shadowRoot;
        return [...root.querySelectorAll('article')].map(a => {
            const base = a.getBoundingClientRect(), who = a.querySelector('.note-who'), time = a.querySelector('time');
            const w = who.getBoundingClientRect(), t = time.getBoundingClientRect();
            return {who: who.textContent, left: w.left - base.left, top: w.top - base.top,
                    timeRight: base.right - t.right, timeTop: t.top - base.top};
        });
    }""")
    assert [b['who'] for b in boxes] == ['Jess', 'Jess', 'Steam …7252'], boxes
    for b in boxes[1:]:
        assert abs(b['left'] - boxes[0]['left']) < 1 and abs(b['top'] - boxes[0]['top']) <= 1.5, boxes
        assert abs(b['timeRight'] - boxes[0]['timeRight']) < 1 and abs(b['timeTop'] - boxes[0]['timeTop']) <= 1.5, boxes
    out = ROOT / 'local_data' / 'feedback' / 'evidence' / f'22-note-layout-{name}.png'
    out.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out))


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
                            if body['resolved']:
                                note.update(resolved_by='76561198000000001', resolved_by_name='Test Admin', resolved_at=1800000100,
                                            outcome=body.get('outcome'), close_note=body.get('close_note'),
                                            resolved_in=body.get('resolved_in'))
                        else:
                            note = {**body, 'id': 'feedback/' + str(1800000000 + len(notes)) + '-' + 'a' * 32 + '.json',
                                    'created': 1800000000 + len(notes), 'author': 'test', 'resolved': False}
                            notes.append(note)
                        request.fulfill(json={'note': note})
                    else:
                        params = dict(parse_qsl(url.query))
                        shown = [item for item in notes
                                 if (params.get('scope') != 'page' or item['path'] == params.get('path'))
                                 and params.get('status', 'all') in ('all', 'resolved' if item['resolved'] else 'open')
                                 and params.get('category', item.get('category')) == item.get('category')]
                        request.fulfill(json={'notes': shown, 'next': None, 'scope': params.get('scope', 'site')})
                    return
                file = DIST / ('index.html' if url.path == '/' else url.path.lstrip('/'))
                if file.is_file():
                    request.fulfill(path=str(file))
                else:
                    request.fulfill(status=404, body='{}')

            context.route('https://gamma.slay-my-stats.com/**', route)
            page = context.new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto('https://gamma.slay-my-stats.com/')
            page.get_by_role('button', name='Feedback', exact=True).click()
            # It opens on the inbox: the first question is whether what you are about to report
            # is already there.
            assert page.get_by_role('tab', name='Inbox', exact=True).get_attribute('aria-selected') == 'true'
            assert page.get_by_role('tab', name='New note', exact=True).get_attribute('aria-selected') == 'false'
            page.get_by_role('tab', name='New note', exact=True).click()
            page.get_by_role('button', name='Whole page', exact=True).click()
            assert page.locator('#page-url').inner_text() == 'https://gamma.slay-my-stats.com/'
            page.get_by_label('What should change?').fill('Make this clearer')
            page.get_by_role('button', name='Send', exact=True).click()
            page.get_by_text('Pick a type first', exact=False).wait_for()
            page.get_by_role('radio', name='Bug', exact=True).click()
            page.get_by_role('button', name='Send', exact=True).click()
            # A successful send closes the panel; the launcher says "Sent" for a moment.
            panel = page.get_by_role('dialog', name='Feedback', exact=True)
            panel.wait_for(state='hidden')
            page.locator('#launcher-label').filter(has_text='Sent').wait_for()
            sent = ROOT / 'local_data' / 'feedback' / 'evidence' / f'7-closed-after-send-{name}.png'
            sent.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(sent))
            created = next(item for item in notes if item['path'] == '/')
            assert created['url'] == 'https://gamma.slay-my-stats.com/', created
            assert created['category'] == 'bug', created
            assert page.locator('#kinds button[aria-checked="true"]').count() == 0
            page.wait_for_function("document.getElementById('gamma-feedback').shadowRoot"
                                   ".getElementById('launcher-count').textContent === '1'")
            # The badge counts the page you are on, hash included: moving to another tab or run
            # must not keep showing the count from the page you left.
            page.evaluate("location.hash = '#elsewhere'")
            page.wait_for_function("document.getElementById('gamma-feedback').shadowRoot"
                                   ".getElementById('launcher-count').hidden")
            page.evaluate("history.back()")
            page.wait_for_function("!document.getElementById('gamma-feedback').shadowRoot"
                                   ".getElementById('launcher-count').hidden")
            assert page.locator('#launcher-count').text_content() == '1'
            # The inbox is a tab of the same panel, not a second button. After a send it reopens on it.
            page.get_by_role('button', name='Feedback', exact=False).click()
            assert page.get_by_role('tab', name='Inbox', exact=True).get_attribute('aria-selected') == 'true'
            wait_summary(page, '1 note · 1 open · 1 place')
            assert page.locator('.bucket').count() == 1
            assert 'Whole page' in page.locator('.bucket summary').first.inner_text()
            assert page.locator('.note-url').first.inner_text() == 'https://gamma.slay-my-stats.com/'
            # One note listed: its own Copy, and a copy-all that says how many it takes.
            assert page.get_by_role('button', name='Copy details', exact=True).count() == 1
            assert page.get_by_role('button', name='Copy all notes (1)', exact=True).is_visible()
            page.get_by_role('button', name='Whole site', exact=True).click()
            wait_summary(page, '2 notes · 2 open · 2 places')
            assert page.locator('.bucket').count() == 2
            page.get_by_role('button', name='This page', exact=True).click()
            wait_summary(page, '1 note · 1 open · 1 place')
            page.get_by_role('button', name='Resolve', exact=True).click()
            # Declining needs a reason; the commit box only belongs to Done.
            page.get_by_label('Outcome').select_option('declined')
            assert not page.get_by_label('Commit').is_visible()
            page.get_by_label('Close note').fill('Not planned')
            page.get_by_role('button', name='Mark resolved', exact=True).click()
            # Resolved notes leave the default Open list and show under Resolved with the outcome.
            wait_summary(page, '0 notes · 0 open · 0 places')
            page.get_by_label('Status').select_option('resolved')
            page.get_by_text('Declined', exact=False).first.wait_for()
            # The resolver shows by name (the mock serves one), not by the end of a Steam ID.
            page.get_by_text('Declined by Test Admin', exact=False).wait_for()
            page.get_by_text('Not planned').wait_for()
            page.get_by_role('button', name='Reopen', exact=True).click()
            wait_summary(page, '0 notes · 0 open · 0 places')
            page.get_by_label('Status').select_option('open')
            wait_summary(page, '1 note · 1 open · 1 place')
            page.locator('#filter-kind').select_option('feature')
            wait_summary(page, '0 notes · 0 open · 0 places')
            page.locator('#filter-kind').select_option('')
            wait_summary(page, '1 note · 1 open · 1 place')
            page.get_by_role('button', name='Resolve', exact=True).click()
            page.get_by_label('Outcome').select_option('done')
            page.get_by_label('Close note').fill('Fixed in the tip')
            page.get_by_label('Commit').fill('abc1234')
            page.get_by_role('button', name='Mark resolved', exact=True).click()
            wait_summary(page, '0 notes · 0 open · 0 places')
            page.get_by_label('Status').select_option('all')
            page.get_by_text('Fixed in the tip · commit abc1234').wait_for()
            page.get_by_role('button', name='Reopen', exact=True).click()
            page.get_by_role('button', name='Resolve', exact=True).wait_for()
            page.get_by_label('Status').select_option('open')
            wait_summary(page, '1 note · 1 open · 1 place')
            page.get_by_role('tab', name='New note', exact=True).click()
            page.get_by_role('button', name='Pick on page', exact=True).click()
            heading = page.locator('h1:visible, h2:visible').first
            heading.click()
            page.get_by_text('Pinned:', exact=False).first.wait_for()
            page.get_by_label('What should change?').fill('Pinned comment')
            page.get_by_role('radio', name='Improvement idea', exact=True).click()
            page.get_by_role('button', name='Send', exact=True).click()
            panel.wait_for(state='hidden')
            page.get_by_role('button', name='Feedback', exact=False).click()
            page.get_by_role('tab', name='New note', exact=True).click()
            page.get_by_text('1 earlier note here', exact=False).wait_for()
            assert 'Pinned comment' in page.locator('#prior').inner_text()
            assert page.locator('#launcher-count').text_content() == '2'
            page.get_by_role('tab', name='Inbox', exact=True).click()
            wait_summary(page, '2 notes · 2 open · 2 places')
            assert page.locator('.bucket').count() == 2, page.locator('.bucket summary').all_inner_texts()
            assert any('Whole page' in text for text in page.locator('.bucket summary').all_inner_texts())
            bounds = panel.bounding_box()
            assert bounds['x'] >= 0 and bounds['y'] >= 0
            assert bounds['x'] + bounds['width'] <= page.evaluate('innerWidth')
            assert bounds['y'] + bounds['height'] <= page.evaluate('innerHeight')
            page.get_by_role('tab', name='New note', exact=True).click()
            page.get_by_role('button', name='Pick on page', exact=True).click()
            page.mouse.move(80, 320)
            page.mouse.down()
            page.mouse.move(300, 410, steps=5)
            page.mouse.up()
            page.get_by_text('Pinned:', exact=False).first.wait_for()
            bounds = panel.bounding_box()
            assert bounds['x'] >= 0 and bounds['y'] >= 0
            assert bounds['x'] + bounds['width'] <= page.evaluate('innerWidth')
            assert bounds['y'] + bounds['height'] <= page.evaluate('innerHeight')
            check_note_layout(page, notes, name)
            output = ROOT / '.playwright-mcp' / f'feedback-{name}.png'
            output.parent.mkdir(exist_ok=True)
            page.screenshot(path=str(output))
            # Opening an existing note from its link must not copy its text into the entry.
            page.goto('https://gamma.slay-my-stats.com/?feedback=' + urlquote(notes[0]['id'], safe=''))
            page.get_by_text('Reviewing:', exact=False).wait_for()
            assert page.get_by_label('What should change?').input_value() == ''
            assert page.get_by_role('radio', name='Bug', exact=True).get_attribute('aria-checked') == 'false'
            assert not errors, errors
            print(f'{name}: passed; {output}')
            browser.close()


if __name__ == '__main__':
    main()