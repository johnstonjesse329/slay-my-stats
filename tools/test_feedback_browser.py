"""Exercise feedback with an isolated mocked inbox at the required device sizes."""
import json
import os
from pathlib import Path
from urllib.parse import parse_qsl, quote as urlquote, urlsplit
from playwright.sync_api import expect, sync_playwright

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
    expect(page.locator('.bucket-author')).to_have_text('Jess')
    expect(page.locator('.bucket-snippet')).to_contain_text('Typed, named.')
    expect(page.get_by_role('button', name='Edit note', exact=True)).to_have_count(0)
    for b in boxes[1:]:
        assert abs(b['left'] - boxes[0]['left']) < 1 and abs(b['top'] - boxes[0]['top']) <= 1.5, boxes
        assert abs(b['timeRight'] - boxes[0]['timeRight']) < 1 and abs(b['timeTop'] - boxes[0]['timeTop']) <= 1.5, boxes
    out = ROOT / 'local_data' / 'feedback' / 'evidence' / f'22-note-layout-{name}.png'
    out.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out))


def check_find_and_plus(page, notes, name):
    """Search and the author filter narrow the loaded notes; +1 is one per person and can be taken back."""
    page.get_by_label('Status').select_option('all')
    wait_summary(page, '3 notes · 2 open · 1 place')
    page.get_by_label('Search notes').fill('stranger')
    wait_summary(page, '1 note of 3 loaded · 0 open · 1 place')
    page.get_by_label('Search notes').fill('')
    page.get_by_label('Author').select_option('player-7252')
    wait_summary(page, '1 note of 3 loaded · 0 open · 1 place')
    page.get_by_label('Author').select_option('')
    wait_summary(page, '3 notes · 2 open · 1 place')
    plus = page.locator('.plus').first
    count = page.locator('.vote-count').first
    expect(plus).to_have_attribute('aria-pressed', 'false')
    expect(count).to_have_text('0 votes')
    plus.click()
    expect(plus).to_have_text('✓ +1')
    expect(plus).to_have_attribute('aria-pressed', 'true')
    expect(count).to_have_text('1 vote')
    out = ROOT / 'local_data' / 'feedback' / 'evidence' / f'23-search-author-plus-{name}.png'
    page.screenshot(path=str(out))
    plus.click()
    expect(plus).to_have_attribute('aria-pressed', 'false')
    expect(count).to_have_text('0 votes')
    notes[0]['plus_count'] = 1
    page.get_by_role('button', name='Refresh', exact=True).click()
    expect(count).to_have_text('1 vote')
    plus.click()
    expect(plus).to_have_attribute('aria-pressed', 'true')
    expect(count).to_have_text('2 votes')
    plus.click()
    expect(plus).to_have_attribute('aria-pressed', 'false')
    expect(count).to_have_text('1 vote')
    page.get_by_role('button', name='Refresh', exact=True).click()
    expect(plus).to_have_attribute('aria-pressed', 'false')
    expect(count).to_have_text('1 vote')


def check_vote_sort(page, notes, paging):
    """Ranks all pages with the selected scope and filters, then restores the location view."""
    notes[0]['plus_count'], notes[1]['plus_count'], notes[2]['plus_count'] = 2, 2, 5
    outside = {**notes[2], 'id': 'feedback/1800000700-' + 'f' * 32 + '.json', 'created': 1800000700,
               'plus_count': 10, 'resolved': False, 'path': '/elsewhere', 'comment': 'Another page'}
    notes.append(outside)
    sort = page.get_by_label('Sort by')
    paging['split'] = True
    page.get_by_role('button', name='This page', exact=True).click()
    sort.select_option('votes')

    def order(expected):
        assert page.locator('article').evaluate_all('(articles) => articles.map(a => a.dataset.id)') == [
            item['id'] for item in expected]

    wait_summary(page, '3 notes · 2 open · 1 place')
    order([notes[2], notes[0], notes[1]])
    expect(page.locator('.bucket-meta').first).to_contain_text('5 votes')
    expect(page.locator('.bucket-author').first).to_have_text('Steam …7252')
    page.get_by_role('button', name='Whole site', exact=True).click()
    wait_summary(page, '4 notes · 3 open · 2 places')
    order([outside, notes[2], notes[0], notes[1]])
    page.get_by_label('Status').select_option('open')
    wait_summary(page, '3 notes · 3 open · 2 places')
    order([outside, notes[0], notes[1]])
    page.get_by_role('button', name='This page', exact=True).click()
    wait_summary(page, '2 notes · 2 open · 1 place')
    order([notes[0], notes[1]])
    notes.pop()
    paging['split'] = False
    sort.select_option('newest')
    expect(page.locator('.bucket')).to_have_count(1)
    if page.get_by_role('button', name='Expand all').count():
        page.get_by_role('button', name='Expand all').click()


def check_backlog(page):
    """Backlog keeps a note open but out of the open count; it has its own filter and goes back with one click."""
    page.get_by_label('Status').select_option('open')
    wait_summary(page, '2 notes · 2 open · 1 place')
    if page.get_by_role('button', name='Expand all').count():
        page.get_by_role('button', name='Expand all').click()
    before = page.locator('article').count()
    article = page.locator('article').first
    article.get_by_role('button', name='Backlog', exact=True).click()
    page.get_by_label('Why later').fill('after the map work')
    page.get_by_role('button', name='Move to backlog').click()
    expect(page.locator('article')).to_have_count(before - 1)
    page.get_by_label('Status').select_option('backlog')
    expect(page.locator('article')).to_have_count(1)
    if page.get_by_role('button', name='Expand all').count():
        page.get_by_role('button', name='Expand all').click()
    expect(page.locator('article').first).to_contain_text('after the map work')
    assert page.locator('.pill.backlog').count() == 1
    page.locator('article').first.get_by_role('button', name='Move to open').click()
    expect(page.locator('article')).to_have_count(0)
    page.get_by_label('Status').select_option('open')


def check_other_env(page, notes):
    """A prod note read on gamma is marked Prod and read-only: no +1 to give, nothing to resolve."""
    notes.append({'id': 'feedback/1700000000-' + 'f' * 32 + '.json', 'created': 1700000000, 'author': 'player-9999',
                  'env': 'prod', 'plus_count': 2, 'plus_mine': False, 'resolved': False, 'comment': 'From prod',
                  'path': '/', 'url': 'https://slay-my-stats.com/', 'target': {'kind': 'page'}})
    page.get_by_label('Status').select_option('all')
    env = page.get_by_label('Environment')
    assert env.is_visible() and env.input_value() == 'gamma'
    page.get_by_text('From prod').wait_for(state='detached')
    env.select_option('both')
    if page.get_by_role('button', name='Expand all').count():
        page.get_by_role('button', name='Expand all').click()
    article = page.locator('article').filter(has_text='From prod')
    expect(article).to_have_count(1)
    expect(article.locator('.pill.kind').filter(has_text='Prod')).to_have_count(1)
    expect(article.locator('.plus')).to_be_disabled()
    expect(article.locator('.vote-count')).to_have_text('2 votes')
    expect(article.get_by_role('button', name='Edit note', exact=True)).to_be_hidden()
    expect(article.get_by_role('button', name='Resolve', exact=True)).to_be_hidden()
    expect(article.get_by_role('button', name='Backlog', exact=True)).to_be_hidden()
    env.select_option('gamma')
    expect(page.locator('article').filter(has_text='From prod')).to_have_count(0)
    notes.pop()
    page.get_by_label('Status').select_option('open')


def main():
    with sync_playwright() as pw:
        for name, engine, options in [('desktop', pw.chromium, {'viewport': {'width': 1920, 'height': 1080}}),
                ('iphone-portrait', pw.webkit, pw.devices['iPhone 16']),
                ('iphone-landscape', pw.webkit, pw.devices['iPhone 16 landscape'])]:
            browser = engine.launch()
            context = browser.new_context(**options)
            notes, errors = [{'id': 'feedback/1234567890-' + 'b' * 32 + '.json', 'created': 1780000000,
                              'author': 'test', 'resolved': False, 'comment': 'Elsewhere', 'env': 'gamma',
                              'path': '/u/elsewhere', 'url': 'https://gamma.slay-my-stats.com/u/elsewhere',
                              'target': {'kind': 'page'}}], []

            about = {'me': 'test', 'env': 'gamma', 'envs': ['gamma', 'prod'], 'admin': True}
            paging = {'split': False}
            vote_response = {}

            def route(request):
                url = urlsplit(request.request.url)
                if url.path == '/auth/feedback':
                    if request.request.method == 'POST':
                        body = request.request.post_data_json
                        if body.get('action') == 'plus':
                            note = next(item for item in notes if item['id'] == body['id'])
                            if body['on'] != note.get('plus_mine', False):
                                note['plus_count'] = note.get('plus_count', 0) + (1 if body['on'] else -1)
                            note['plus_mine'] = body['on']
                            if vote_response.pop('delay', False):
                                vote_response.update(route=request, payload={**about, 'note': dict(note)})
                                return
                        elif body.get('action') == 'edit':
                            note = next(item for item in notes if item['id'] == body['id'])
                            note['comment'] = body['comment'].strip()
                        elif body.get('action') == 'backlog':
                            note = next(item for item in notes if item['id'] == body['id'])
                            if body['on']:
                                note['backlog'] = {'by': 'test', 'at': 1800000200, 'reason': body.get('reason', '')}
                            else:
                                note.pop('backlog', None)
                        elif body.get('action') == 'resolve':
                            note = next(item for item in notes if item['id'] == body['id'])
                            if not body['resolved'] and note.get('resolved'):
                                note.setdefault('history', []).append({key: note.get(key) for key in ('resolved_in', 'resolved_at', 'close_note')})
                            note['resolved'] = body['resolved']
                            if body['resolved']:
                                note.update(resolved_by='76561198000000001', resolved_by_name='Test Admin', resolved_at=1800000100,
                                            outcome=body.get('outcome'), close_note=body.get('close_note'),
                                            resolved_in=body.get('resolved_in'))
                        else:
                            note = {**body, 'env': 'gamma', 'plus_count': 1, 'plus_mine': True, 'id': 'feedback/' + str(1800000000 + len(notes)) + '-' + 'a' * 32 + '.json',
                                    'created': 1800000000 + len(notes), 'author': 'test', 'resolved': False, 'seq': 100 + len(notes)}
                            notes.append(note)
                        request.fulfill(json={**about, 'note': note})
                    else:
                        params = dict(parse_qsl(url.query))
                        shown = [item for item in notes
                                 if (params.get('scope') != 'page' or item['path'] == params.get('path'))
                                 and params.get('status', 'all') in ('all', 'resolved' if item['resolved'] else 'backlog' if item.get('backlog') else 'open')
                                 and params.get('category', item.get('category')) == item.get('category')
                                 and params.get('env', 'gamma') in ('both', item.get('env', 'gamma'))]
                        if 'id' in params:
                            shown = [item for item in notes if item['id'] == params['id']]
                        cursor = None
                        if 'cursor' in params:
                            shown = shown[2:]
                        elif paging['split'] and len(shown) > 2:
                            shown, cursor = shown[:2], 'later'
                        request.fulfill(json={**about, 'notes': shown, 'next': cursor, 'scope': params.get('scope', 'site')})
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
            wait_summary(page, '1 note · 1 open · 1 place')
            assert page.locator('#scope button').all_inner_texts() == ['Whole site', 'This page']
            expect(page.get_by_role('button', name='Whole site', exact=True)).to_have_attribute('aria-pressed', 'true')
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
            page.get_by_role('button', name='This page', exact=True).click()
            wait_summary(page, '1 note · 1 open · 1 place')
            assert page.locator('.bucket').count() == 1
            assert 'Whole page' in page.locator('.bucket summary').first.inner_text()
            # Groups start collapsed, showing the newest comment; one button opens or closes them all.
            assert page.locator('.bucket[open]').count() == 0
            expect(page.locator('.bucket-author').first).to_have_text('Steam …test')
            expect(page.locator('.bucket-snippet').first).to_have_text('Make this clearer')
            assert page.locator('#toggle-all').inner_text() == 'Expand all'
            page.locator('#toggle-all').click()
            assert page.locator('.bucket[open]').count() == 1
            expect(page.locator('#toggle-all')).to_have_text('Collapse all')
            edit = page.get_by_role('button', name='Edit note', exact=True)
            edit.click()
            page.get_by_label('Edit note text').fill('This draft will be dropped')
            page.get_by_role('button', name='Cancel', exact=True).click()
            expect(page.locator('.note-comment')).to_have_text('Make this clearer')
            edit.click()
            page.get_by_label('Edit note text').fill('Edited feedback')
            upvote = page.get_by_role('button', name='Upvote', exact=True)
            upvote.click()
            expect(upvote).to_have_attribute('aria-pressed', 'false')
            expect(page.get_by_label('Edit note text')).to_have_value('Edited feedback')
            vote_response['delay'] = True
            upvote.click()
            page.get_by_role('button', name='Save changes', exact=True).click()
            expect(page.locator('.note-comment')).to_have_text('Edited feedback')
            # Keep the edited text when a delayed vote response arrives with the old comment.
            expect(upvote).to_be_disabled()
            vote_response['route'].fulfill(json=vote_response['payload'])
            expect(upvote).to_have_attribute('aria-pressed', 'true')
            expect(page.locator('.note-comment')).to_have_text('Edited feedback')
            page.get_by_role('button', name='Refresh', exact=True).click()
            expect(page.locator('.note-comment')).to_have_text('Edited feedback')
            expect(page.locator('.vote-count')).to_have_text('1 vote')
            expect(page.locator('.pill.open')).to_have_text('Open')
            # The inbox follows the site's tabs: a note filed on another page shows when you move there.
            page.evaluate("location.hash = '#elsewhere'")
            wait_summary(page, '0 notes · 0 open · 0 places')
            page.evaluate("history.back()")
            wait_summary(page, '1 note · 1 open · 1 place')
            page.locator('#toggle-all').click() if page.locator('.bucket[open]').count() == 0 else None
            # The left-edge grip widens the panel toward the left.
            before = page.locator('#panel').bounding_box()
            grip = page.locator('#grip').bounding_box()
            if name == 'desktop':
                page.mouse.move(grip['x'] + 6, grip['y'] + grip['height'] / 2)
                page.mouse.down(); page.mouse.move(grip['x'] - 120, grip['y'] + grip['height'] / 2, steps=5); page.mouse.up()
                after = page.locator('#panel').bounding_box()
                assert after['width'] > before['width'] + 80 and abs((after['x'] + after['width']) - (before['x'] + before['width'])) < 2, (before, after)
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
            expect(page.locator('.note-resolution').get_by_role('link', name='abc1234', exact=True)).to_have_attribute('href', 'https://github.com/johnstonjesse329/slay-my-stats/commit/abc1234')
            page.get_by_role('button', name='Reopen', exact=True).click()
            page.get_by_role('button', name='Resolve', exact=True).wait_for()
            expect(page.locator('.note-history').get_by_role('link', name='abc1234', exact=True)).to_have_attribute('href', 'https://github.com/johnstonjesse329/slay-my-stats/commit/abc1234')
            page.get_by_label('Status').select_option('open')
            wait_summary(page, '1 note · 1 open · 1 place')
            page.get_by_role('tab', name='New note', exact=True).click()
            draft = page.get_by_label('What should change?')
            draft.fill('Draft before picking')
            page.get_by_role('button', name='Pick on page', exact=True).click()
            guidance = page.locator('#pick-instructions').bounding_box()
            cancel = page.get_by_role('button', name='Cancel', exact=True)
            button = cancel.bounding_box()
            assert guidance['y'] + guidance['height'] <= button['y']
            for bounds in (guidance, button):
                assert bounds['x'] >= 0 and bounds['y'] >= 0
                assert bounds['x'] + bounds['width'] <= page.evaluate('innerWidth')
                assert bounds['y'] + bounds['height'] <= page.evaluate('innerHeight')
            expect(page.locator('#grip')).to_be_hidden()
            if name == 'desktop':
                cancel.click()
                page.get_by_role('button', name='Pick on page', exact=True).click()
                page.keyboard.press('Escape')
            else:
                cancel.tap()
            expect(panel).to_be_visible()
            expect(page.get_by_role('button', name='Pick on page', exact=True)).to_be_focused()
            expect(draft).to_have_value('Draft before picking')
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
            check_find_and_plus(page, notes, name)
            check_vote_sort(page, notes, paging)
            check_backlog(page)
            check_other_env(page, notes)
            page.evaluate("""() => {
                const r = document.getElementById('gamma-feedback').shadowRoot;
                const body = r.getElementById('view-inbox');
                const spacer = document.createElement('div');
                spacer.style.height = '2000px';
                body.append(spacer);
                const header = r.querySelector('header');
                const before = header.getBoundingClientRect().top;
                body.scrollTop = 1000;
                if (body.scrollTop === 0) throw Error('Inbox did not scroll');
                if (header.getBoundingClientRect().top !== before) throw Error('Header scrolled away');
                if (r.getElementById('panel').scrollTop !== 0) throw Error('Outer panel scrolled');
                spacer.remove(); body.scrollTop = 0;
            }""")
            output = ROOT / '.playwright-mcp' / f'feedback-{name}.png'
            output.parent.mkdir(exist_ok=True)
            page.screenshot(path=str(output))
            # Open location lands on the inbox with that note's group opened and the note marked,
            # not on a blank new note.
            page.goto('https://gamma.slay-my-stats.com/?feedback=' + urlquote(notes[0]['id'], safe=''))
            assert page.get_by_role('tab', name='Inbox', exact=True).get_attribute('aria-selected') == 'true'
            expect(page.locator('article.focused')).to_have_count(1)
            assert page.locator('.bucket[open]').count() == 1
            assert not errors, errors
            print(f'{name}: passed; {output}')
            browser.close()


if __name__ == '__main__':
    main()
