"""Gamma inbox access and persistence checks (no AWS calls)."""
import hashlib
import hmac
import io
import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lambda' / 'ingest'))
import feedback


class FeedbackTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'GAMMA_SESSION_SECRET': 'test-secret',
            'ALLOWED_STEAM_IDS': '76561198000000001', 'GAMMA_ORIGIN': 'https://gamma.test', 'DATA_BUCKET': 'test'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store = Mock()
        self.client = patch('boto3.client', return_value=self.store)
        self.client.start()
        self.addCleanup(self.client.stop)

    def event(self, body=None, expiry=None):
        payload = f'76561198000000001.{expiry or int(time.time())+1000}'
        sig = hmac.new(b'test-secret', payload.encode(), hashlib.sha256).hexdigest()
        return {'cookies': [f'__Host-gamma={payload}.{sig}'],
                'headers': {'origin': 'https://gamma.test'},
                'requestContext': {'http': {'method': 'POST' if body else 'GET'}},
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

    def test_resolve(self):
        key = 'feedback/1234567890-' + 'a'*32 + '.json'
        self.store.get_object.return_value = {'Body': io.BytesIO(json.dumps({'id': key}).encode())}
        result = feedback.handle(self.event({'action': 'resolve', 'id': key, 'resolved': True}))
        self.assertTrue(json.loads(result['body'])['note']['resolved'])


if __name__ == '__main__':
    unittest.main()
