"""What's new: the posts build_site.py reads from site/whats-new/, and the reactions on them
(infra/lambda/ingest/reactions.py) against a local DynamoDB (moto), so the real conditions and
transactions run: one of each reaction per player, exact counts, the throttle, reading signed
out, and "asked for this" from the feedback notes a post closes.

    infra\\.venv\\Scripts\\python.exe -m unittest infra.tests.test_whats_new
"""
import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

INFRA = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(INFRA / 'lambda' / 'ingest'), str(INFRA), str(INFRA.parent)]
import build_site  # noqa: E402

try:
    import boto3
    from moto import mock_aws
except ImportError:  # the posts tests need neither
    boto3 = None

ME, OTHER = '76561198000000001', '76561198000000002'


class PostsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        patcher = patch.object(build_site, 'POSTS_DIR', self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, name, text):
        (self.dir / name).write_text(text, encoding='utf-8')

    def test_newest_first_with_header_fields(self):
        self.write('2026-11-01-older.html', '<!--\ntitle: Older\n-->\n<p>Old.</p>\n')
        self.write('2026-11-18-span-panel.html', '<!--\ntitle: Add up a stretch\nfixes: FB-12, FB-31\n-->\n<p>New.</p>')
        posts = build_site.posts()
        self.assertEqual([p['id'] for p in posts], ['span-panel', 'older'])
        self.assertEqual(posts[0]['fixes'], [12, 31])
        self.assertEqual(posts[0]['title'], 'Add up a stretch')
        self.assertEqual(posts[0]['body'], '<p>New.</p>')
        self.assertEqual(posts[1]['fixes'], [])

    def test_bad_posts_stop_the_build(self):
        for name, text in [('span-panel.html', '<!-- title: x -->'),             # no date
                           ('2026-02-30-x.html', '<!-- title: x -->'),            # no such day
                           ('2026-11-18-Caps.html', '<!-- title: x -->'),         # not a URL id
                           ('2026-11-18-x.html', '<p>No header.</p>'),            # no title
                           ('2026-11-18-y.html', '<!--\ntitle: y\nfixes: 12\n-->')]:  # not FB-n
            with self.subTest(name=name):
                for f in self.dir.iterdir():
                    f.unlink()
                self.write(name, text)
                with self.assertRaises(build_site.PageError):
                    build_site.posts()

    def test_an_id_once(self):
        self.write('2026-11-01-same.html', '<!-- title: a -->')
        self.write('2026-11-18-same.html', '<!-- title: b -->')
        with self.assertRaises(build_site.PageError):
            build_site.posts()

    def test_page_body_puts_the_posts_at_the_mark(self):
        self.write('2026-11-18-span-panel.html', "<!--\ntitle: Tom & Jerry's\nfixes: FB-7\n-->\n<p>Body</p>")
        page = self.dir.parent / f'{self.dir.name}-page.html'
        self.addCleanup(page.unlink, missing_ok=True)
        page.write_text('<h1>What\'s new</h1>\n<!-- posts -->\n', encoding='utf-8')
        html = build_site.page_body('whats-new', page)
        self.assertIn('<article class="post" id="span-panel" data-post="span-panel" data-fixes="7">', html)
        self.assertIn('<a href="/whats-new/span-panel">Tom &amp; Jerry&#x27;s</a>', html)
        self.assertIn('<time datetime="2026-11-18">November 18, 2026</time>', html)
        self.assertNotIn('<!-- posts -->', html)
        page.write_text('<h1>No mark</h1>', encoding='utf-8')
        with self.assertRaises(build_site.PageError):
            build_site.page_body('whats-new', page)

    def test_site_bar_dot_names_the_newest_post(self):
        self.write('2026-11-01-older.html', '<!-- title: a -->')
        self.write('2026-11-18-newer.html', '<!-- title: b -->')
        label = build_site.site_link_label('whats-new', "What's new")
        self.assertIn('data-latest="2026-11-18-newer"', label)
        self.assertEqual(build_site.site_link_label('about', 'About'), 'About')

    def test_the_real_posts_build(self):
        patch.stopall()
        for name, f, _ in build_site.site_pages():
            build_site.page_body(name, f)


@unittest.skipIf(boto3 is None, 'needs boto3 and moto (infra/requirements-dev.txt)')
class ReactionsTest(unittest.TestCase):
    def setUp(self):
        import feedback
        import reactions
        import session
        from slay_my_stats.feedback_stack import INDEXES, TABLE_NAME
        self.feedback, self.reactions, self.table = feedback, reactions, TABLE_NAME
        env = patch.dict(os.environ, {
            'GAMMA_SESSION_SECRET': 'test-secret', 'ALLOWED_STEAM_IDS': f'{ME},{OTHER}',
            'GAMMA_ORIGIN': 'https://gamma.test', 'ADMIN_STEAM_IDS': ME,
            'FEEDBACK_TABLE': TABLE_NAME, 'FEEDBACK_ENV': 'gamma', 'FEEDBACK_READ_ENVS': 'gamma,prod',
            'AWS_DEFAULT_REGION': 'us-west-2', 'AWS_ACCESS_KEY_ID': 'test', 'AWS_SECRET_ACCESS_KEY': 'test'})
        env.start()
        self.addCleanup(env.stop)
        session._secret = None
        self.addCleanup(setattr, session, '_secret', None)
        reactions._notes.clear()
        aws = mock_aws()
        aws.start()
        self.addCleanup(aws.stop)
        self.db = boto3.client('dynamodb')
        attrs = [{'AttributeName': a, 'AttributeType': 'S'} for a in ['env', 'sk', *INDEXES.values()]]
        self.db.create_table(
            TableName=TABLE_NAME, BillingMode='PAY_PER_REQUEST', AttributeDefinitions=attrs,
            KeySchema=[{'AttributeName': 'env', 'KeyType': 'HASH'}, {'AttributeName': 'sk', 'KeyType': 'RANGE'}],
            GlobalSecondaryIndexes=[{'IndexName': name, 'Projection': {'ProjectionType': 'ALL'},
                                     'KeySchema': [{'AttributeName': 'env', 'KeyType': 'HASH'},
                                                   {'AttributeName': key, 'KeyType': 'RANGE'}]}
                                    for name, key in INDEXES.items()])
        names = patch.object(feedback, '_steam_name', return_value=None)
        names.start()
        self.addCleanup(names.stop)

    def event(self, body=None, query='', steam=ME, origin='https://gamma.test', path='/auth/reactions'):
        cookies = []
        if steam:
            payload = f'{steam}.{int(time.time()) + 1000}'
            sig = hmac.new(b'test-secret', payload.encode(), hashlib.sha256).hexdigest()
            cookies = [f'__Host-gamma={payload}.{sig}']
        return {'rawPath': path, 'cookies': cookies, 'headers': {'origin': origin},
                'requestContext': {'http': {'method': 'POST' if body is not None else 'GET'}},
                'rawQueryString': query, 'body': json.dumps(body) if body is not None else ''}

    def call(self, body=None, **kw):
        import session
        response = session.handle(self.event(body, **kw))
        return response['statusCode'], json.loads(response['body'])

    def react(self, post, kind, on=True, **kw):
        return self.call({'post': post, 'kind': kind, 'on': on}, **kw)

    def test_signed_out_reads_but_cannot_react(self):
        status, data = self.call(query='posts=launch', steam=None)
        self.assertEqual((status, data), (200, {'signedIn': False, 'posts': {'launch': {'counts': {}, 'mine': []}}}))
        self.assertEqual(self.react('launch', 'plus', steam=None)[0], 401)

    def test_one_of_each_per_player_and_exact_counts(self):
        self.react('launch', 'plus')
        self.react('launch', 'plus')            # a double click changes nothing
        self.react('launch', 'skull')
        status, data = self.react('launch', 'plus', steam=OTHER)
        self.assertEqual(status, 200)
        self.assertEqual(data['posts']['launch'], {'counts': {'plus': 2, 'skull': 1}, 'mine': ['plus']})
        self.react('launch', 'plus', on=False)
        self.react('launch', 'plus', on=False)  # taking it back twice takes one
        status, data = self.call(query='posts=launch,other')
        self.assertEqual(data['posts']['launch'], {'counts': {'plus': 1, 'skull': 1}, 'mine': ['skull']})
        self.assertEqual(data['posts']['other'], {'counts': {}, 'mine': []})
        self.assertTrue(data['signedIn'])

    def test_bad_requests(self):
        self.assertEqual(self.react('launch', 'heart')[0], 400)                 # not a kind
        self.assertEqual(self.react('Launch!', 'plus')[0], 400)                 # not a post id
        self.assertEqual(self.react('x' * 61, 'plus')[0], 400)
        self.assertEqual(self.react('launch', 'plus', origin='https://evil.test')[0], 403)
        self.assertEqual(self.call(query='')[0], 400)
        self.assertEqual(self.call(query='posts=a&fixes=b:12')[0], 400)          # fixes for a post not asked
        self.assertEqual(self.call(query='posts=a&fixes=a:FB-12')[0], 400)

    def test_throttle(self):
        with patch.object(self.reactions, 'RATE_WRITES', 3):
            for on in (True, False, True):
                self.assertEqual(self.react('launch', 'eye', on=on)[0], 200)
            status, data = self.react('launch', 'eye', on=False)
        self.assertEqual(status, 429)
        self.assertIn('reactions', data['message'])

    def test_reactions_stay_out_of_the_feedback_inbox(self):
        self.react('launch', 'plus')
        self.assertEqual(self.feedback.all_notes(self.db, self.table, 'gamma'), [])

    def note(self, env, seq, voters):
        """A feedback note with its +1s, as feedback._create and _plus leave them."""
        note_id = f'feedback/{9999999999 - seq:010d}-{seq:032x}.json'
        note = {'id': note_id, 'seq': seq, 'created': 1, 'author': voters[0], 'comment': 'x', 'path': '/'}
        self.db.put_item(TableName=self.table, Item=self.feedback.note_item(env, note, len(voters)))
        for steam in voters:
            self.db.put_item(TableName=self.table, Item=self.feedback.vote_item(env, note_id, steam, 1))

    def test_asked_counts_each_player_once_across_notes_and_envs(self):
        self.note('prod', 12, [OTHER, ME])
        self.note('gamma', 31, [OTHER])
        status, data = self.call(query='posts=span,launch&fixes=span:12.31.99')
        self.assertEqual(status, 200)
        self.assertEqual(data['posts']['span']['asked'], {'count': 2, 'mine': True})
        self.assertNotIn('asked', data['posts']['launch'])
        _, data = self.call(query='posts=span&fixes=span:31', steam=None)
        self.assertEqual(data['posts']['span']['asked'], {'count': 1, 'mine': False})


if __name__ == '__main__':
    unittest.main()
