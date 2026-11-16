"""Gamma inbox access and persistence checks (no AWS calls)."""
import hashlib
import hmac
import io
import json
import os
import sys
import time
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lambda' / 'ingest'))
import feedback


class FeedbackTest(unittest.TestCase):
    steam = '76561198000000001'

    def setUp(self):
        self.env = patch.dict(os.environ, {'GAMMA_SESSION_SECRET': 'test-secret',
            'ALLOWED_STEAM_IDS': '76561198000000001', 'GAMMA_ORIGIN': 'https://gamma.test', 'DATA_BUCKET': 'test'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store = Mock()
        self.client = patch('boto3.client', return_value=self.store)
        self.client.start()
        self.addCleanup(self.client.stop)

    def event(self, body=None, expiry=None, query=''):
        payload = f'76561198000000001.{expiry or int(time.time())+1000}'
        sig = hmac.new(b'test-secret', payload.encode(), hashlib.sha256).hexdigest()
        return {'cookies': [f'__Host-gamma={payload}.{sig}'],
                'headers': {'origin': 'https://gamma.test'},
                'requestContext': {'http': {'method': 'POST' if body else 'GET'}},
                'rawQueryString': query,
                'body': json.dumps(body) if body else ''}

    def test_direct_url_requires_valid_session(self):
        self.assertEqual(feedback.handle({})['statusCode'], 401)
        self.assertEqual(feedback.handle(self.event(expiry=1))['statusCode'], 401)
        self.store.assert_not_called()

    def test_create_and_list(self):
        response = feedback.handle(self.event({'comment': ' Fix this ', 'path': '/u/test#runs',
                                               'url': 'https://gamma.test/u/test#runs',
                                               'target': {'kind': 'element', 'selector': '#runs'}}))
        self.assertEqual(response['statusCode'], 200)
        note = json.loads(response['body'])['note']
        self.assertEqual(note['comment'], 'Fix this')
        self.assertEqual(note['author'], '76561198000000001')
        self.assertEqual(note['url'], 'https://gamma.test/u/test#runs')
        self.store.list_objects_v2.return_value = {'Contents': [{'Key': note['id']}]}
        self.store.get_object.return_value = {'Body': io.BytesIO(json.dumps(note).encode())}
        self.assertEqual(json.loads(feedback.handle(self.event())['body'])['notes'], [note])

    def test_category_is_kept_and_checked(self):
        body = {'comment': 'x', 'path': '/'}
        for category in ('bug', 'feature', 'improvement'):
            note = json.loads(feedback.handle(self.event({**body, 'category': category}))['body'])['note']
            self.assertEqual(note['category'], category)
        self.assertNotIn('category', json.loads(feedback.handle(self.event(body))['body'])['note'])
        self.assertEqual(feedback.handle(self.event({**body, 'category': 'idea'}))['statusCode'], 400)
        _, text = feedback.build_report([{'created': 100, 'author': '1234', 'comment': 'x', 'path': '/',
                                          'category': 'feature'}], 100, 'daily', 'https://gamma.test')
        self.assertIn('[Feature request] x', text)

    def test_refuses_cross_origin_and_invalid_notes(self):
        event = self.event({'comment': 'hello', 'path': '/'})
        event['headers']['origin'] = 'https://elsewhere.test'
        self.assertEqual(feedback.handle(event)['statusCode'], 403)
        for body in [{'comment': ' ', 'path': '/'}, {'comment': 'x'*4001, 'path': '/'},
                     {'comment': 'x', 'path': 'https://elsewhere.test'}, {'action': 'resolve', 'id': '../secret'}]:
            self.assertEqual(feedback.handle(self.event(body))['statusCode'], 400)
        self.store.put_object.assert_not_called()

    def test_note_carries_the_full_page_url(self):
        path = '/u/test#detail/1794615305'
        body = {'comment': 'hello', 'path': path, 'target': {'kind': 'page'}}
        derived = json.loads(feedback.handle(self.event(body))['body'])['note']
        self.assertEqual(derived['url'], 'https://gamma.test' + path)  # older clients send no url
        exact = json.loads(feedback.handle(self.event({**body, 'url': 'https://gamma.test' + path}))['body'])['note']
        self.assertEqual(exact['url'], 'https://gamma.test' + path)
        for url in ['https://elsewhere.test' + path, 'https://gamma.test.evil.test' + path,
                    'ftp://gamma.test' + path, {'href': path}]:
            self.assertEqual(feedback.handle(self.event({**body, 'url': url}))['statusCode'], 400, url)

    def test_list_pages_and_scopes(self):
        keys = [f"feedback/{9999999999 - i:010d}-{i:032x}.json" for i in range(30)]
        docs = {key: {'id': key, 'path': '/a' if i % 2 else '/b', 'target': {'kind': 'page'}, 'resolved': False}
                for i, key in enumerate(keys)}
        ordered = sorted(keys)  # S3 lists keys in lexicographic order: newest note first
        self.store.list_objects_v2.side_effect = lambda **kw: {
            'Contents': [{'Key': key} for key in [k for k in ordered if k > kw.get('StartAfter', '')][:kw.get('MaxKeys', 1000)]],
            'IsTruncated': False}
        self.store.get_object.side_effect = lambda **kw: {'Body': io.BytesIO(json.dumps(docs[kw['Key']]).encode())}

        first = json.loads(feedback.handle(self.event(query='scope=site'))['body'])
        self.assertEqual(len(first['notes']), feedback.PAGE_SIZE)
        self.assertEqual(first['scope'], 'site')
        rest = json.loads(feedback.handle(
            self.event(query='scope=site&cursor=' + urllib.parse.quote(first['next'])))['body'])
        self.assertEqual(len(rest['notes']), 30 - feedback.PAGE_SIZE)
        self.assertIsNone(rest['next'])
        self.assertEqual([note['id'] for note in first['notes'] + rest['notes']], ordered)

        page = json.loads(feedback.handle(self.event(query='scope=page&path=%2Fa'))['body'])
        self.assertTrue(page['notes'])
        self.assertEqual({note['path'] for note in page['notes']}, {'/a'})

        self.assertEqual(feedback.handle(self.event(query='scope=nope'))['statusCode'], 400)
        self.assertEqual(feedback.handle(self.event(query='scope=page'))['statusCode'], 400)
        self.assertEqual(feedback.handle(self.event(query='scope=site&cursor=../raw'))['statusCode'], 400)

    def test_resolve(self):
        key = 'feedback/1234567890-' + 'a'*32 + '.json'
        self.store.get_object.return_value = {'Body': io.BytesIO(json.dumps({'id': key}).encode())}
        result = feedback.handle(self.event({'action': 'resolve', 'id': key, 'resolved': True, 'outcome': 'declined', 'close_note': 'Not planned.'}))
        self.assertTrue(json.loads(result['body'])['note']['resolved'])

    def resolve(self, key, stored, **fields):
        self.store.get_object.return_value = {'Body': io.BytesIO(json.dumps(stored).encode())}
        result = feedback.handle(self.event({'action': 'resolve', 'id': key, **fields}))
        return result['statusCode'], json.loads(result['body']).get('note')

    def test_resolution_is_recorded(self):
        key = 'feedback/1234567890-' + 'a'*32 + '.json'
        status, note = self.resolve(key, {'id': key}, resolved=True, outcome='done', close_note=' Fixed the tip. ', resolved_in='ABC1234')
        self.assertEqual(status, 200)
        self.assertEqual((note['resolved_by'], note['close_note'], note['resolved_in'], note['outcome']),
                         (self.steam, 'Fixed the tip.', 'abc1234', 'done'))
        self.assertIsInstance(note['resolved_at'], int)

    def test_reopen_keeps_the_resolution_in_history(self):
        key = 'feedback/1234567890-' + 'a'*32 + '.json'
        _, closed = self.resolve(key, {'id': key}, resolved=True, outcome='done', close_note='done', resolved_in='abc1234')
        _, reopened = self.resolve(key, closed, resolved=False)
        self.assertFalse(reopened['resolved'])
        self.assertNotIn('close_note', reopened)
        self.assertNotIn('outcome', reopened)
        self.assertEqual(len(reopened['history']), 1)
        self.assertEqual(reopened['history'][0]['outcome'], 'done')
        self.assertEqual(reopened['history'][0]['close_note'], 'done')
        self.assertEqual(reopened['history'][0]['reopened_by'], self.steam)
        _, again = self.resolve(key, reopened, resolved=True, outcome='declined', close_note='really done')
        _, again = self.resolve(key, again, resolved=False)
        self.assertEqual([h['close_note'] for h in again['history']], ['done', 'really done'])

    def test_second_resolve_does_not_overwrite_the_first(self):
        key = 'feedback/1234567890-' + 'a'*32 + '.json'
        _, closed = self.resolve(key, {'id': key}, resolved=True, outcome='declined', close_note='first')
        _, twice = self.resolve(key, closed, resolved=True, outcome='declined', close_note='second')
        self.assertEqual(twice['close_note'], 'first')

    def test_bad_resolution_fields_are_refused(self):
        key = 'feedback/1234567890-' + 'a'*32 + '.json'
        other = 'feedback/1234567891-' + 'b'*32 + '.json'
        for fields in ({'outcome': 'done', 'close_note': 'x', 'resolved_in': 'not a commit'},
                       {'outcome': 'declined', 'close_note': 'x' * 2001}, {'outcome': 'declined', 'close_note': 5},
                       {}, {'outcome': 'wontfix', 'close_note': 'x'},
                       {'outcome': 'done', 'close_note': 'x'}, {'outcome': 'done', 'resolved_in': 'abc1234'},
                       {'outcome': 'declined'}, {'outcome': 'declined', 'close_note': '  '},
                       {'outcome': 'duplicate'}, {'outcome': 'duplicate', 'duplicate_of': '../secret'}):
            self.assertEqual(self.resolve(key, {'id': key}, resolved=True, **fields)[0], 400, fields)
        status, note = self.resolve(key, {'id': key}, resolved=True, outcome='duplicate', duplicate_of=other)
        self.assertEqual((status, note['duplicate_of'], note['resolved_in']), (200, other, ''))

    def test_filters_by_status_and_category(self):
        kinds = ['bug', 'feature', 'improvement', None]
        keys = [f"feedback/{9999999999 - i:010d}-{i:032x}.json" for i in range(8)]
        docs = {key: {'id': key, 'path': '/a', 'target': {'kind': 'page'}, 'resolved': i % 2 == 0,
                      **({'category': kinds[i % 4]} if kinds[i % 4] else {})} for i, key in enumerate(keys)}
        ordered = sorted(keys)
        self.store.list_objects_v2.side_effect = lambda **kw: {
            'Contents': [{'Key': key} for key in [k for k in ordered if k > kw.get('StartAfter', '')][:kw.get('MaxKeys', 1000)]],
            'IsTruncated': False}
        self.store.get_object.side_effect = lambda **kw: {'Body': io.BytesIO(json.dumps(docs[kw['Key']]).encode())}
        def ask(query):
            return [docs[n['id']] for n in json.loads(feedback.handle(self.event(query=query))['body'])['notes']]
        self.assertEqual(len(ask('scope=site')), 8)
        self.assertEqual({n['resolved'] for n in ask('scope=site&status=open')}, {False})
        self.assertEqual(len(ask('scope=site&status=resolved')), 4)
        self.assertEqual({n.get('category') for n in ask('scope=site&category=bug')}, {'bug'})
        both = ask('scope=site&status=open&category=feature')
        self.assertEqual([(n['resolved'], n['category']) for n in both], [(False, 'feature')] * len(both))
        self.assertEqual(feedback.handle(self.event(query='scope=site&status=nope'))['statusCode'], 400)
        self.assertEqual(feedback.handle(self.event(query='scope=site&category=nope'))['statusCode'], 400)

    def test_feedback_emails(self):
        now, day = 1_800_000_000, 86400
        def note(created, **extra):
            return {'created': created, 'author': '76561198000000001', 'comment': 'c', 'path': '/p', 'resolved': False, **extra}
        notes = [note(now - 100), note(now - 3 * day), note(now - 20 * day),
                 note(now - 10 * day, resolved=True, resolved_at=now - 2 * day),
                 note(now - 10 * day, resolved=True, resolved_at=now - 9 * day)]
        subject, body = feedback.build_report(notes, now, 'daily', 'https://gamma.test')
        self.assertEqual(subject, 'Gamma feedback: 1 new, 3 open')
        self.assertIn('https://gamma.test/p', body)
        self.assertIsNone(feedback.build_report(notes[2:], now, 'daily', 'https://gamma.test'))
        subject, body = feedback.build_report(notes, now, 'weekly', 'https://gamma.test')
        self.assertEqual(subject, 'Gamma feedback, this week: 3 open, 2 in, 1 resolved')
        self.assertIn('Still open:', body)
        self.assertEqual(feedback.build_report([], now, 'weekly', 'https://gamma.test')[0],
                         'Gamma feedback, this week: 0 open, 0 in, 0 resolved')


if __name__ == '__main__':
    unittest.main()
