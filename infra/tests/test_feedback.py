"""The gamma feedback inbox against a local DynamoDB (moto), so the real conditions and
transactions run: numbering, +1 once per player, the conditional resolve, cursors, the
Gamma / Prod / Both merge, the throttle and the 403s.

    infra\\.venv\\Scripts\\python.exe -m unittest infra.tests.test_feedback

moto is a test-only install (infra/requirements-dev.txt), never in the Lambda bundle.
"""
import hashlib
import hmac
import json
import os
import sys
import time
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

import boto3
from moto import mock_aws

INFRA = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(INFRA / 'lambda' / 'ingest'), str(INFRA), str(INFRA.parent)]  # the repo root holds run.py
import feedback  # noqa: E402
import session  # noqa: E402
from slay_my_stats.feedback_stack import INDEXES, TABLE_NAME  # noqa: E402

ADMIN, OTHER = '76561198000000001', '76561198000000002'


def note_id(i):
    return f"feedback/{9999999999 - i:010d}-{i:032x}.json"


class FeedbackTest(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {
            'GAMMA_SESSION_SECRET': 'test-secret', 'ALLOWED_STEAM_IDS': f'{ADMIN},{OTHER}',
            'ADMIN_STEAM_IDS': ADMIN, 'GAMMA_ORIGIN': 'https://gamma.test',
            'FEEDBACK_TABLE': TABLE_NAME, 'FEEDBACK_ENV': 'gamma', 'FEEDBACK_READ_ENVS': 'gamma,prod',
            'AWS_DEFAULT_REGION': 'us-west-2', 'AWS_ACCESS_KEY_ID': 'test', 'AWS_SECRET_ACCESS_KEY': 'test'})
        env.start()
        self.addCleanup(env.stop)
        session._secret = None
        self.addCleanup(setattr, session, '_secret', None)
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

    # --- helpers -------------------------------------------------------------------------

    def event(self, body=None, expiry=None, query='', steam=ADMIN):
        payload = f'{steam}.{expiry or int(time.time()) + 1000}'
        sig = hmac.new(b'test-secret', payload.encode(), hashlib.sha256).hexdigest()
        return {'cookies': [f'__Host-gamma={payload}.{sig}'],
                'headers': {'origin': 'https://gamma.test'},
                'requestContext': {'http': {'method': 'POST' if body else 'GET'}},
                'rawQueryString': query,
                'body': json.dumps(body) if body else ''}

    def call(self, body=None, **kw):
        response = feedback.handle(self.event(body, **kw))
        return response['statusCode'], json.loads(response['body'])

    def note(self, body=None, **kw):
        status, data = self.call(body, **kw)
        self.assertEqual(status, 200, data)
        return data['note']

    def ids(self, query, **kw):
        status, data = self.call(query=query, **kw)
        self.assertEqual(status, 200, data)
        return [n['id'] for n in data['notes']]

    def put(self, i, env='gamma', plus=0, **fields):
        """A stored note, as the migration or an earlier write left it."""
        note = {'id': note_id(i), 'seq': i, 'created': 100 + i, 'author': ADMIN, 'comment': f'n{i}',
                'path': '/a', 'target': {'kind': 'page', 'w': 12.5}, 'resolved': False, **fields}
        self.db.put_item(TableName=TABLE_NAME, Item=feedback.note_item(env, note, plus))
        return note['id']

    def stored(self, nid, env='gamma'):
        return self.db.get_item(TableName=TABLE_NAME, Key={'env': {'S': env}, 'sk': {'S': nid}})['Item']

    def every(self, query, **kw):
        """Every page of a view, following its cursor."""
        seen, cursor = [], None
        while True:
            q = query + ('&cursor=' + urllib.parse.quote(cursor) if cursor else '')
            status, data = self.call(query=q, **kw)
            self.assertEqual(status, 200, data)
            self.assertLessEqual(len(data['notes']), feedback.PAGE_SIZE)
            seen += [n['id'] for n in data['notes']]
            cursor = data['next']
            if not cursor:
                return seen

    # --- access --------------------------------------------------------------------------

    def test_direct_url_requires_valid_session(self):
        with patch('boto3.client') as client:
            self.assertEqual(feedback.handle({})['statusCode'], 401)
            self.assertEqual(feedback.handle(self.event(expiry=1))['statusCode'], 401)
            self.assertEqual(feedback.handle(self.event(steam='76561198000000009'))['statusCode'], 401)
            client.assert_not_called()

    def test_refuses_cross_origin_and_invalid_notes(self):
        event = self.event({'comment': 'hello', 'path': '/'})
        event['headers']['origin'] = 'https://elsewhere.test'
        self.assertEqual(feedback.handle(event)['statusCode'], 403)
        for body in [{'comment': ' ', 'path': '/'}, {'comment': 'x' * 4001, 'path': '/'},
                     {'comment': 'x', 'path': 'https://elsewhere.test'}, {'comment': 'x', 'path': '/\elsewhere.test'},
                     {'comment': 'x', 'path': '/	/elsewhere.test'}, {'action': 'resolve', 'id': '../secret'},
                     {'action': 'nope'}, ['not', 'an', 'object']]:
            self.assertEqual(self.call(body)[0], 400, body)
        self.assertEqual(self.db.scan(TableName=TABLE_NAME)['Count'], 0)

    # --- create --------------------------------------------------------------------------

    def test_create_and_list(self):
        note = self.note({'comment': ' Fix this ', 'path': '/u/test#runs', 'url': 'https://gamma.test/u/test#runs',
                          'target': {'kind': 'element', 'selector': '#runs', 'w': 10.25}})
        self.assertEqual((note['comment'], note['author'], note['url'], note['env']),
                         ('Fix this', ADMIN, 'https://gamma.test/u/test#runs', 'gamma'))
        self.assertEqual((note['seq'], note['plus_count'], note['plus_mine']), (1, 1, True))  # the author's +1
        self.assertNotIn('plus', note)
        status, data = self.call()
        self.assertEqual([n['id'] for n in data['notes']], [note['id']])
        self.assertEqual(data['notes'][0]['target']['w'], 10.25)  # fractions survive (kept as JSON)
        self.assertEqual((data['env'], data['envs'], data['admin'], data['me']), ('gamma', ['gamma', 'prod'], True, ADMIN))

    def test_numbers_continue_one_sequence_across_envs(self):
        self.db.put_item(TableName=TABLE_NAME, Item={'env': {'S': 'counter'}, 'sk': {'S': 'seq'}, 'value': {'N': '27'}})
        self.assertEqual(self.note({'comment': 'a', 'path': '/'})['seq'], 28)
        self.assertEqual(self.note({'comment': 'b', 'path': '/'})['seq'], 29)

    def test_notes_carry_steam_names_not_stored(self):
        with patch.object(feedback, '_steam_name', return_value='Jess'):
            note = self.note({'comment': 'Hi', 'path': '/', 'url': 'https://gamma.test/', 'target': {}})
        self.assertEqual(note['author_name'], 'Jess')
        self.assertNotIn('author_name', json.loads(self.stored(note['id'])['body']['S']))

    def test_category_is_kept_and_checked(self):
        body = {'comment': 'x', 'path': '/'}
        for category in ('bug', 'feature', 'improvement', 'kudos'):
            self.assertEqual(self.note({**body, 'category': category})['category'], category)
        plain = self.note(body)
        self.assertNotIn('category', plain)
        self.assertNotIn('cat', self.stored(plain['id']))  # kept out of the type indexes
        self.assertEqual(self.call({**body, 'category': 'idea'})[0], 400)
        _, text = feedback.build_report([{'created': 100, 'author': '1234', 'comment': 'x', 'path': '/',
                                          'category': 'feature'}], 100, 'daily', 'https://gamma.test', 'Gamma')
        self.assertIn('[Feature request] x', text)

    def test_note_carries_the_full_page_url(self):
        path = '/u/test#detail/1794615305'
        body = {'comment': 'hello', 'path': path, 'target': {'kind': 'page'}}
        self.assertEqual(self.note(body)['url'], 'https://gamma.test' + path)  # older clients send no url
        self.assertEqual(self.note({**body, 'url': 'https://gamma.test' + path})['url'], 'https://gamma.test' + path)
        for url in ['https://elsewhere.test' + path, 'https://gamma.test.evil.test' + path,
                    'ftp://gamma.test' + path, {'href': path}]:
            self.assertEqual(self.call({**body, 'url': url})[0], 400, url)

    # --- reads ---------------------------------------------------------------------------

    def test_list_pages_and_scopes(self):
        made = [self.put(i, path='/a' if i % 2 else '/b') for i in range(30)]
        # +1 and throttle items share the partition and must never show as notes
        feedback._plus(self.db, TABLE_NAME, 'gamma', made[0], OTHER, True)
        feedback._throttle(self.db, TABLE_NAME, 'gamma', OTHER, False)
        status, first = self.call(query='scope=site')
        self.assertEqual((len(first['notes']), first['scope']), (feedback.PAGE_SIZE, 'site'))
        self.assertEqual(self.every('scope=site'), sorted(made))  # newest first, nothing twice
        page = self.every('scope=page&path=%2Fa')
        self.assertEqual(page, sorted(m for i, m in enumerate(made) if i % 2))
        self.assertEqual(self.call(query='scope=nope')[0], 400)
        self.assertEqual(self.call(query='scope=page')[0], 400)

    def test_cursors_are_checked_strictly(self):
        for i in range(30):
            self.put(i)
        good = self.call(query='scope=site')[1]['next']
        def forged(plain):
            import base64
            return urllib.parse.quote(base64.urlsafe_b64encode(json.dumps(plain).encode()).decode())
        key = {'env': 'gamma', 'sk': note_id(5)}
        for cursor in ['../raw', 'e30=', forged([]), forged({'prod': key | {'env': 'prod'}}),
                       forged({'gamma': {**key, 'extra': 'x'}}), forged({'gamma': {**key, 'sk': 'vote#x'}}),
                       forged({'gamma': {**key, 'env': 'prod'}}), forged({'counter': None})]:
            self.assertEqual(self.call(query='scope=site&cursor=' + cursor)[0], 400, cursor)
        # an index cursor must match its own index
        status_cursor = forged({'gamma': {**key, 'st': 'open#' + note_id(6)}})
        self.assertEqual(self.call(query='scope=site&status=open&cursor=' + status_cursor)[0], 400)
        self.assertEqual(self.call(query='scope=site&cursor=' + urllib.parse.quote(good))[0], 200)
        self.assertEqual(self.call(query='scope=site&status=open&cursor=' + urllib.parse.quote(good))[0], 400)

    def test_environment_filter_and_both_merge(self):
        gamma = [self.put(i) for i in range(0, 40, 2)]
        prod = [self.put(i, env='prod') for i in range(1, 40, 2)]
        self.assertEqual(self.every('scope=site'), sorted(gamma))  # default: the write env
        self.assertEqual(self.every('scope=site&env=prod'), sorted(prod))
        both = self.every('scope=site&env=both')
        self.assertEqual(both, sorted(gamma + prod))  # merged newest first, no skips or repeats
        status, data = self.call(query='scope=site&env=both')
        self.assertEqual({n['env'] for n in data['notes']}, {'gamma', 'prod'})
        self.assertEqual(self.call(query='scope=site&env=nope')[0], 400)
        with patch.dict(os.environ, {'FEEDBACK_READ_ENVS': 'gamma'}):  # prod's own Lambda never reads gamma
            self.assertEqual(self.call(query='scope=site&env=prod')[0], 400)
            self.assertEqual(self.every('scope=site&env=both'), sorted(gamma))

    def test_both_merge_when_one_env_runs_out(self):
        gamma = [self.put(i) for i in range(30)]
        prod = [self.put(100 + i, env='prod') for i in range(3)]  # older than every gamma note
        self.assertEqual(self.every('scope=site&env=both'), sorted(gamma + prod))

    def test_filters_by_status_and_category(self):
        kinds = ['bug', 'feature', 'improvement', None]
        for i in range(8):
            extra = {'category': kinds[i % 4]} if kinds[i % 4] else {}
            self.put(i, resolved=i % 2 == 0, **extra)
        def ask(query):
            return [json.loads(self.stored(nid)['body']['S']) for nid in self.ids(query)]
        self.assertEqual(len(ask('scope=site')), 8)
        self.assertEqual({n['resolved'] for n in ask('scope=site&status=open')}, {False})
        self.assertEqual(len(ask('scope=site&status=resolved')), 4)
        self.assertEqual({n.get('category') for n in ask('scope=site&category=bug')}, {'bug'})
        both = ask('scope=site&status=open&category=feature')
        self.assertEqual([(n['resolved'], n['category']) for n in both], [(False, 'feature')] * 2)
        page = ask('scope=page&path=%2Fa&status=resolved&category=bug')
        self.assertEqual([(n['resolved'], n['category']) for n in page], [(True, 'bug')] * 2)
        self.assertEqual(self.call(query='scope=site&status=nope')[0], 400)
        self.assertEqual(self.call(query='scope=site&category=nope')[0], 400)

    def test_a_feedback_link_finds_its_note_in_any_readable_env(self):
        nid = self.put(3, env='prod')
        status, data = self.call(query='id=' + urllib.parse.quote(nid))
        self.assertEqual([(n['id'], n['env']) for n in data['notes']], [(nid, 'prod')])
        self.assertEqual(self.call(query='id=' + urllib.parse.quote(note_id(4)))[1]['notes'], [])
        self.assertEqual(self.call(query='id=../x')[0], 400)

    def test_all_notes_is_only_notes(self):
        nid = self.put(1)
        self.put(2, env='prod')
        feedback._plus(self.db, TABLE_NAME, 'gamma', nid, OTHER, True)
        feedback._throttle(self.db, TABLE_NAME, 'gamma', OTHER, True)
        self.assertEqual([n['id'] for n in feedback.all_notes(self.db, TABLE_NAME, 'gamma')], [nid])

    # --- +1 ------------------------------------------------------------------------------

    def test_plus_one_is_one_per_player_and_exact(self):
        nid = self.put(1, plus=1)  # the author's
        def plus(on, steam=OTHER):
            return self.note({'action': 'plus', 'id': nid, 'on': on}, steam=steam)
        self.assertEqual((plus(True)['plus_count'], plus(True)['plus_count']), (2, 2))  # a repeat changes nothing
        mine = self.call(query='scope=site', steam=ADMIN)[1]['notes'][0]
        self.assertEqual((mine['plus_count'], mine['plus_mine']), (2, False))  # ADMIN's vote isn't an item here
        self.assertNotIn('plus', mine)
        gone = plus(False)
        self.assertEqual((gone['plus_count'], gone['plus_mine']), (1, False))
        self.assertEqual(plus(False)['plus_count'], 1)
        missing = self.call({'action': 'plus', 'id': note_id(9), 'on': True})
        self.assertEqual(missing[0], 404)
        self.assertNotIn('Item', self.db.get_item(TableName=TABLE_NAME, Key=feedback.vote_key('gamma', note_id(9), ADMIN)))

    def test_prod_notes_are_read_only_from_gamma(self):
        nid = self.put(1, env='prod')
        for body in ({'action': 'plus', 'id': nid, 'on': True, 'env': 'prod'},
                     {'action': 'edit', 'id': nid, 'env': 'prod', 'comment': 'new text'},
                     {'action': 'resolve', 'id': nid, 'env': 'prod', 'resolved': True, 'outcome': 'declined', 'close_note': 'x'},
                     {'action': 'backlog', 'id': nid, 'env': 'prod', 'on': True}):
            self.assertEqual(self.call(body)[0], 403, body)
        # without env, the write env is meant: no gamma note by that id
        self.assertEqual(self.call({'action': 'plus', 'id': nid, 'on': True})[0], 404)
        self.assertEqual(self.stored(nid, 'prod')['plus_count'], {'N': '0'})

    def test_the_author_can_edit_only_the_comment(self):
        nid = self.put(1, plus=3, author=OTHER, category='bug', resolved=True,
                       outcome='done', close_note='fixed', resolved_by=ADMIN, history=[{'close_note': 'earlier'}])
        saved = self.stored(nid)
        body = {'action': 'edit', 'id': nid, 'comment': '  new\ntext  ', 'path': '/new',
                'category': 'kudos', 'author': ADMIN, 'plus_count': 0, 'resolved': False}
        self.assertEqual(self.call(body)[0], 403)  # even an admin cannot edit someone else's note
        self.assertEqual(self.stored(nid), saved)
        for bad in (' ', 'x' * 4001, 3, None):
            self.assertEqual(self.call({**body, 'comment': bad}, steam=OTHER)[0], 400)
        note = self.note(body, steam=OTHER)
        self.assertEqual(note['comment'], 'new\ntext')
        saved_body = json.loads(saved.pop('body')['S'])
        edited = self.stored(nid)
        self.assertEqual(json.loads(edited.pop('body')['S']), {**saved_body, 'comment': 'new\ntext'})
        self.assertEqual(edited, saved)

    def test_inbox_hydrates_fresh_text_and_votes_when_an_index_lags(self):
        nid = self.put(1, plus=1)
        moved = self.put(2)
        old = [feedback._from_item(self.stored(note)) for note in (nid, moved)]
        self.note({'action': 'edit', 'id': nid, 'comment': 'updated'})
        self.note({'action': 'plus', 'id': nid, 'on': True})
        self.note({'action': 'backlog', 'id': moved, 'on': True})
        with patch.object(feedback, '_read', return_value=(old, 'cursor')):
            status, data = self.call(query='scope=page&path=%2Fa&status=open')
        self.assertEqual((status, data['next']), (200, 'cursor'))
        self.assertEqual([note['id'] for note in data['notes']], [nid])
        note = data['notes'][0]
        self.assertEqual((note['comment'], note['plus_count'], note['plus_mine']), ('updated', 2, True))

    # --- resolve / backlog ---------------------------------------------------------------

    def resolve(self, nid, steam=ADMIN, **fields):
        status, data = self.call({'action': 'resolve', 'id': nid, **fields}, steam=steam)
        return status, data.get('note')

    def test_resolution_is_recorded_and_indexed(self):
        nid = self.put(1, category='bug')
        status, note = self.resolve(nid, resolved=True, outcome='done', close_note=' Fixed the tip. ', resolved_in='ABC1234')
        self.assertEqual(status, 200)
        self.assertEqual((note['resolved_by'], note['close_note'], note['resolved_in'], note['outcome']),
                         (ADMIN, 'Fixed the tip.', 'abc1234', 'done'))
        self.assertIsInstance(note['resolved_at'], int)
        self.assertEqual(self.ids('scope=site&status=open'), [])
        self.assertEqual(self.ids('scope=site&status=resolved&category=bug'), [nid])

    def test_a_refused_resolve_says_what_is_missing(self):
        nid = self.put(1)
        cases = [
            ({'outcome': 'done', 'resolved_in': 'abc1234'}, 'Done needs a note on what changed.'),
            ({'outcome': 'done', 'close_note': 'x', 'resolved_in': 'not-a-hash'}, 'The commit should be a git hash'),
            ({'outcome': 'declined'}, 'Declined needs a note saying why.'),
            ({'outcome': 'duplicate', 'duplicate_of': 'FB-3'}, 'Duplicate needs the id of the note it repeats.'),
            ({'outcome': 'shrug'}, 'That change could not be saved.'),
        ]
        for fields, message in cases:
            status, data = self.call({'action': 'resolve', 'id': nid, 'resolved': True, **fields})
            self.assertEqual(status, 400, fields)
            self.assertTrue(data['message'].startswith(message), (fields, data['message']))
        self.assertIn('1–4000', self.call({'comment': ''})[1]['message'])
        self.assertEqual(self.ids('scope=site&status=open'), [nid])
        status, note = self.resolve(nid, resolved=True, outcome='done', close_note='Works now.')
        self.assertEqual((status, note['outcome'], note['resolved_in']), (200, 'done', ''))

    def test_only_admins_resolve_or_backlog(self):
        nid = self.put(1)
        self.assertEqual(self.resolve(nid, steam=OTHER, resolved=True, outcome='declined', close_note='x')[0], 403)
        self.assertEqual(self.call({'action': 'backlog', 'id': nid, 'on': True}, steam=OTHER)[0], 403)
        self.assertEqual(self.call(query='scope=site', steam=OTHER)[1]['admin'], False)
        self.assertEqual(self.note({'action': 'plus', 'id': nid, 'on': True}, steam=OTHER)['plus_count'], 1)

    def test_only_admins_see_other_players_steam_ids(self):
        nid = self.note({'comment': 'mine', 'path': '/'})['id']  # by ADMIN
        theirs = self.call(query='scope=site', steam=OTHER)[1]['notes'][0]
        self.assertNotIn(ADMIN, json.dumps(theirs))
        again = self.call(query='scope=site', steam=OTHER)[1]['notes'][0]
        self.assertEqual(theirs['author'], again['author'])  # one person stays one tag
        own = self.note({'comment': 'yours', 'path': '/'}, steam=OTHER)
        self.assertEqual(own['author'], OTHER)
        self.assertNotIn(ADMIN, json.dumps(self.note({'action': 'plus', 'id': nid, 'on': True}, steam=OTHER)))
        self.assertEqual({n['author'] for n in self.call(query='scope=site')[1]['notes']}, {ADMIN, OTHER})
        # Backlog, resolution and reopen history all name the admin; none of it reaches OTHER.
        self.resolve(nid, resolved=True, outcome='declined', close_note='x')
        self.resolve(nid, resolved=False)
        self.resolve(nid, resolved=True, outcome='declined', close_note='y')
        seen = json.dumps(self.call(query='id=' + nid, steam=OTHER)[1])
        self.assertNotIn(ADMIN, seen)
        self.assertEqual(self.call(query='id=' + nid)[1]['notes'][0]['history'][0]['reopened_by'], ADMIN)
        parked = self.note({'comment': 'later', 'path': '/'})['id']
        self.call({'action': 'backlog', 'id': parked, 'on': True})
        self.assertEqual(self.call(query='id=' + parked)[1]['notes'][0]['backlog']['by'], ADMIN)
        self.assertNotIn(ADMIN, json.dumps(self.call(query='id=' + parked, steam=OTHER)[1]))

    def test_reopen_keeps_the_resolution_in_history(self):
        nid = self.put(1)
        self.resolve(nid, resolved=True, outcome='done', close_note='done', resolved_in='abc1234')
        _, reopened = self.resolve(nid, resolved=False)
        self.assertFalse(reopened['resolved'])
        self.assertNotIn('close_note', reopened)
        self.assertEqual([(h['outcome'], h['close_note'], h['reopened_by']) for h in reopened['history']],
                         [('done', 'done', ADMIN)])
        self.resolve(nid, resolved=True, outcome='declined', close_note='really done')
        _, again = self.resolve(nid, resolved=False)
        self.assertEqual([h['close_note'] for h in again['history']], ['done', 'really done'])

    def test_second_resolve_does_not_overwrite_the_first(self):
        nid = self.put(1)
        self.resolve(nid, resolved=True, outcome='declined', close_note='first')
        _, twice = self.resolve(nid, resolved=True, outcome='declined', close_note='second')
        self.assertEqual(twice['close_note'], 'first')

    def test_a_concurrent_change_is_a_conflict_not_an_overwrite(self):
        nid = self.put(1)
        def meanwhile(note):  # another reviewer resolves it between the read and the write
            self.db.update_item(TableName=TABLE_NAME, Key={'env': {'S': 'gamma'}, 'sk': {'S': nid}},
                                UpdateExpression='SET st = :s', ExpressionAttributeValues={':s': {'S': 'resolved#' + nid}})
            note['backlog'] = {'by': ADMIN}
            return True
        with self.assertRaises(feedback.Refused) as refused:
            feedback._change(self.db, TABLE_NAME, 'gamma', nid, ADMIN, meanwhile)
        self.assertEqual(refused.exception.status, 409)
        self.assertNotIn('backlog', json.loads(self.stored(nid)['body']['S']))

    def test_a_concurrent_comment_edit_conflicts_even_when_the_state_is_unchanged(self):
        nid = self.put(1)
        def meanwhile(note):
            self.note({'action': 'edit', 'id': nid, 'comment': 'committed first'})
            note['comment'] = 'stale'
            return True
        with self.assertRaises(feedback.Refused) as refused:
            feedback._change(self.db, TABLE_NAME, 'gamma', nid, ADMIN, meanwhile)
        self.assertEqual(refused.exception.status, 409)
        self.assertEqual(json.loads(self.stored(nid)['body']['S'])['comment'], 'committed first')

    def test_resolve_keeps_a_plus_count_that_moved(self):
        nid = self.put(1, plus=1)
        self.note({'action': 'plus', 'id': nid, 'on': True}, steam=OTHER)
        _, note = self.resolve(nid, resolved=True, outcome='declined', close_note='no')
        self.assertEqual(note['plus_count'], 2)

    def test_bad_resolution_fields_are_refused(self):
        nid, other = self.put(1), note_id(2)
        for fields in ({'outcome': 'done', 'close_note': 'x', 'resolved_in': 'not a commit'},
                       {'outcome': 'declined', 'close_note': 'x' * 2001}, {'outcome': 'declined', 'close_note': 5},
                       {}, {'outcome': 'wontfix', 'close_note': 'x'},
                       {'outcome': 'done', 'resolved_in': 'abc1234'},  # done without a commit is fine
                       {'outcome': 'declined'}, {'outcome': 'declined', 'close_note': '  '},
                       {'outcome': 'duplicate'}, {'outcome': 'duplicate', 'duplicate_of': '../secret'}):
            self.assertEqual(self.resolve(nid, resolved=True, **fields)[0], 400, fields)
        status, note = self.resolve(nid, resolved=True, outcome='duplicate', duplicate_of=other)
        self.assertEqual((status, note['duplicate_of'], note['resolved_in']), (200, other, ''))
        self.assertEqual(self.resolve(note_id(7), resolved=True, outcome='declined', close_note='x')[0], 404)

    def test_backlog_is_an_open_state_with_its_own_filter(self):
        nid = self.put(1)
        note = self.note({'action': 'backlog', 'id': nid, 'on': True, 'reason': 'after the map work'})
        self.assertEqual(note['backlog']['reason'], 'after the map work')
        self.assertEqual((self.ids('scope=site&status=open'), self.ids('scope=site&status=backlog')), ([], [nid]))
        self.assertNotIn('backlog', self.note({'action': 'backlog', 'id': nid, 'on': False}))
        self.assertEqual(self.ids('scope=site&status=open'), [nid])
        self.assertEqual(self.call({'action': 'backlog', 'id': nid, 'on': True, 'reason': 'x' * 501})[0], 400)
        self.note({'action': 'backlog', 'id': nid, 'on': True})
        closed = self.resolve(nid, resolved=True, outcome='declined', close_note='no')[1]
        self.assertNotIn('backlog', closed)
        self.assertEqual(self.ids('scope=site&status=backlog'), [])

    # --- throttle (FB-24) ----------------------------------------------------------------

    def test_new_notes_are_capped_per_hour(self):
        for i in range(feedback.RATE_NOTES):
            self.note({'comment': f'n{i}', 'path': '/'}, steam=OTHER)
        status, data = self.call({'comment': 'one more', 'path': '/'}, steam=OTHER)
        self.assertEqual(status, 429, data)
        self.assertEqual(len(feedback.all_notes(self.db, TABLE_NAME, 'gamma')), feedback.RATE_NOTES)
        self.note({'comment': 'mine', 'path': '/'}, steam=ADMIN)  # each player has their own count
        nid = self.ids('scope=site')[0]
        self.note({'action': 'plus', 'id': nid, 'on': True}, steam=OTHER)  # other writes still go

    def test_all_writes_are_capped_per_hour(self):
        nid = self.put(1)
        for i in range(feedback.RATE_WRITES):
            self.note({'action': 'plus', 'id': nid, 'on': i % 2 == 0}, steam=OTHER)
        self.assertEqual(self.call({'action': 'plus', 'id': nid, 'on': True}, steam=OTHER)[0], 429)
        self.assertEqual(self.stored(nid)['plus_count'], {'N': '0'})
        hour = int(time.time() // 3600)
        rate = self.stored(f'rate#{OTHER}#{hour}')
        self.assertEqual(int(rate['expires']['N']), (hour + 25) * 3600)  # TTL clears it


    # --- migration from S3 ---------------------------------------------------------------

    def test_migration_copies_once_and_only_raises_the_counter(self):
        sys.path.insert(0, str(INFRA.parent / 'tools'))
        import feedback_migrate
        s3 = boto3.client('s3')
        s3.create_bucket(Bucket='old', CreateBucketConfiguration={'LocationConstraint': 'us-west-2'})
        def s3_note(i, **extra):
            note = {'id': note_id(i), 'seq': i, 'created': 100 + i, 'author': ADMIN, 'comment': f'n{i}',
                    'path': '/a', 'target': {'w': 1.5}, 'resolved': False, **extra}
            s3.put_object(Bucket='old', Key=note['id'], Body=json.dumps(note).encode())
        s3_note(2, plus=[OTHER, ADMIN, OTHER])
        s3_note(3, resolved=True, outcome='declined', close_note='no', history=[{'outcome': 'done'}])
        s3.put_object(Bucket='old', Key='feedback/stray.txt', Body=b'x')
        run = lambda apply: feedback_migrate.migrate(s3, self.db, apply, bucket='old', table=TABLE_NAME, out=lambda *_: None)
        self.assertEqual(run(False), (2, 0, []))
        self.assertEqual(self.db.scan(TableName=TABLE_NAME)['Count'], 0)  # a dry run writes nothing
        self.assertEqual(run(True), (2, 0, []))
        voted = self.call(query='id=' + urllib.parse.quote(note_id(2)), steam=OTHER)[1]['notes'][0]
        self.assertEqual((voted['plus_count'], voted['plus_mine'], voted['seq']), (2, True, 2))
        self.assertNotIn('plus', json.loads(self.stored(note_id(2))['body']['S']))  # voters never sent
        closed = self.call(query='id=' + urllib.parse.quote(note_id(3)))[1]['notes'][0]
        self.assertEqual((closed['outcome'], closed['history']), ('declined', [{'outcome': 'done'}]))
        self.assertEqual(self.ids('scope=site&status=resolved'), [note_id(3)])
        self.assertEqual(self.note({'comment': 'new', 'path': '/'})['seq'], 4)  # continues after the highest
        s3_note(5)
        self.resolve(note_id(2), resolved=True, outcome='declined', close_note='x')  # changed on gamma meanwhile
        self.assertEqual(run(True), (1, 2, ['FB-2']))  # only the new one; the changed one is listed, kept
        self.assertTrue(json.loads(self.stored(note_id(2))['body']['S'])['resolved'])
        counter = lambda: self.db.get_item(TableName=TABLE_NAME, Key={'env': {'S': 'counter'}, 'sk': {'S': 'seq'}})['Item']['value']['N']
        self.assertEqual(counter(), '5')
        self.db.put_item(TableName=TABLE_NAME, Item={'env': {'S': 'counter'}, 'sk': {'S': 'seq'}, 'value': {'N': '40'}})
        run(True)
        self.assertEqual(counter(), '40')  # never lowered

    # --- emails --------------------------------------------------------------------------

    def test_feedback_emails(self):
        now, day = 1_800_000_000, 86400
        def note(created, **extra):
            return {'created': created, 'author': ADMIN, 'comment': 'c', 'path': '/p', 'resolved': False, **extra}
        notes = [note(now - 100), note(now - 3 * day), note(now - 20 * day),
                 note(now - 10 * day, resolved=True, resolved_at=now - 2 * day),
                 note(now - 10 * day, resolved=True, resolved_at=now - 9 * day)]
        subject, body = feedback.build_report(notes, now, 'daily', 'https://gamma.test', 'Gamma')
        self.assertEqual(subject, 'Gamma feedback: 1 new, 3 open')
        self.assertIn('https://gamma.test/p', body)
        self.assertIsNone(feedback.build_report(notes[2:], now, 'daily', 'https://gamma.test', 'Gamma'))
        subject, body = feedback.build_report(notes, now, 'weekly', 'https://gamma.test', 'Gamma')
        self.assertEqual(subject, 'Gamma feedback, this week: 3 open, 2 in, 1 resolved')
        self.assertIn('Still open:', body)
        self.assertEqual(feedback.build_report([], now, 'weekly', 'https://gamma.test', 'Gamma')[0],
                         'Gamma feedback, this week: 0 open, 0 in, 0 resolved')

    def test_prod_preview_lists_the_most_recently_touched(self):
        now, day = 1_800_000_000, 86400
        notes = [{'created': now - (30 - i) * day, 'author': ADMIN, 'comment': f'n{i}', 'path': '/',
                  'seq': i, 'resolved': False} for i in range(14)]
        notes[0]['history'] = [{'reopened_at': now - 100}]  # oldest filed, reopened last
        notes[1]['backlog'] = {'at': now - 50}  # backlogged notes aren't open
        self.assertEqual(feedback.touched(notes[0]), now - 100)
        data = feedback.report_data(notes, now, 'weekly', 'https://prod.test', 'Prod', preview=10)
        self.assertEqual(data['listed'], 'recent')
        self.assertEqual([r['seq'] for r in data['rows']], [0, 13, 12, 11, 10, 9, 8, 7, 6, 5])
        self.assertEqual(data['more'], 3)
        _, body = feedback.build_report(notes, now, 'weekly', 'https://prod.test', 'Prod', preview=10)
        self.assertIn('Open, most recently touched:', body)
        self.assertIn('…and 3 more open', body)
        # Without a preview (gamma), every open note, oldest first.
        data = feedback.report_data(notes, now, 'weekly', 'https://gamma.test', 'Gamma')
        self.assertEqual([r['seq'] for r in data['rows']], [0] + list(range(2, 14)))
        self.assertEqual(data['more'], 0)

    def test_morning_email_carries_both_sites(self):
        import handler
        monday, day = 1_799_020_800 + 13 * 3600, 86400  # Monday 2027-01-04, 13:00 UTC
        self.assertEqual(time.gmtime(monday).tm_wday, 0)
        notes = {'prod': [{'created': monday - 3 * day, 'author': ADMIN, 'comment': 'p', 'path': '/'}], 'gamma': []}
        sites = 'prod=https://prod.test,gamma=https://gamma.test'
        with patch.dict(os.environ, {'FEEDBACK_DIGEST_SITES': sites}):
            # Tuesday: prod's note is three days old, gamma has none, so nothing to add.
            self.assertEqual(handler.feedback_sections(monday + day, notes.get), [])
            # Monday: the weekly counts for both, even when nothing came in.
            sections = handler.feedback_sections(monday, notes.get)
        self.assertEqual([h for h, _ in sections], ['Prod feedback, this week: 1 open, 1 in, 0 resolved',
                                                     'Gamma feedback, this week: 0 open, 0 in, 0 resolved'])
        self.assertIn('https://prod.test/', sections[0][1])
        sent = []
        with patch.object(handler, 'build_digest', return_value=('Uploads', 'body')), \
                patch.object(handler, '_get_store'), \
                patch.object(handler, '_alert', side_effect=lambda *a: sent.append(a)), \
                patch.object(handler, 'feedback_sections', return_value=sections):
            handler.digest_handler({}, None)
        subject, body = sent[0]
        self.assertTrue(subject.startswith('Uploads | Prod feedback, this week'))
        self.assertIn('\n\nGamma feedback, this week: 0 open, 0 in, 0 resolved\n---', body)


if __name__ == '__main__':
    unittest.main()
