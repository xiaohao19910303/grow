import asyncio
import os
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from cloud_auth import guard
from reading.scheduled import PATH, register
from reading.service import Reader
from reading.store import DEFAULT, TABLE
from test_legacy_cloud_content import CloudFixture, DATE

class ScheduleAuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cryptography.hazmat.primitives.asymmetric import rsa
        cls.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        self.env = patch.dict(os.environ, {'APP_PASSWORD': 'OWNER_TEST_PASSWORD_' + 'x' * 30})
        self.env.start(); self.addCleanup(self.env.stop)
        self.keys = patch('reading.scheduled.jwks.get_signing_key_from_jwt',
                          return_value=SimpleNamespace(key=self.private.public_key()))
        self.keys.start(); self.addCleanup(self.keys.stop)
        self.service = SimpleNamespace(daily_tick=Mock())
        self.store = SimpleNamespace(jobs=lambda: [], prefs=lambda: DEFAULT)
        app = FastAPI(); router = APIRouter(prefix='/api/reading')
        register(router, self.store, self.service); app.include_router(router)
        self.client = TestClient(app)

    def token(self, **changes):
        import time
        import jwt
        from reading.scheduled import ISSUER, AUDIENCE, REPOSITORY, REPOSITORY_ID, WORKFLOW
        now = int(time.time())
        claims = {'iss':ISSUER, 'aud':AUDIENCE, 'sub':'repo:owner/repo:ref:refs/heads/main',
                  'exp':now+300, 'iat':now, 'nbf':now-1, 'repository':REPOSITORY,
                  'repository_id':REPOSITORY_ID, 'workflow_ref':WORKFLOW,
                  'ref':'refs/heads/main', 'event_name':'schedule', **changes}
        return jwt.encode(claims, self.private, algorithm='RS256', headers={'kid':'test-key'})

    def test_signed_identity_and_read_only_status(self):
        for headers in ({}, {'Authorization':'Bearer wrong'}):
            self.assertEqual(self.client.post(PATH, headers=headers).status_code, 403)
        h = {'Authorization':'Bearer '+self.token()}
        self.assertEqual(self.client.get(PATH, headers=h).status_code, 200)
        self.service.daily_tick.assert_not_called()
        result = self.client.post(PATH, headers=h)
        self.assertEqual(result.status_code, 200)
        self.service.daily_tick.assert_called_once()
        self.assertNotIn(h['Authorization'], result.text)

    def test_expiration_signature_and_workflow_scope(self):
        import jwt
        for changes in ({'exp':1}, {'aud':'elsewhere'}, {'iss':'https://attacker.example'},
                        {'repository_id':'other'}, {'ref':'refs/heads/other'},
                        {'workflow_ref':'another-workflow'}, {'event_name':'pull_request'}):
            self.assertEqual(self.client.post(PATH, headers={'Authorization':'Bearer '+self.token(**changes)}).status_code, 403)
        forged = jwt.encode({'aud':'anything'}, 'UNTRUSTED_TEST_ONLY_SECRET_32_BYTES', algorithm='HS256')
        self.assertEqual(self.client.post(PATH, headers={'Authorization':'Bearer '+forged}).status_code, 403)
        from cryptography.hazmat.primitives.asymmetric import rsa
        with patch('reading.scheduled.jwks.get_signing_key_from_jwt',
                   return_value=SimpleNamespace(key=rsa.generate_private_key(public_exponent=65537,key_size=2048).public_key())):
            self.assertEqual(self.client.post(PATH, headers={'Authorization':'Bearer '+self.token()}).status_code, 403)

    def test_pause_prevents_trigger_and_is_reported(self):
        self.store.prefs=lambda: {**DEFAULT,'enabled':False}
        result=self.client.post(PATH,headers={'Authorization':'Bearer '+self.token()})
        self.assertEqual(result.json()['state'],'paused')
        self.service.daily_tick.assert_not_called()

    def test_schedule_identity_never_grants_access_to_other_routes(self):
        token = self.token()
        def request(path, method='GET'):
            return Request({'type':'http', 'method':method, 'path':path,
                'headers':[(b'authorization', ('Bearer '+token).encode())]})
        self.assertIsNone(guard(request(PATH)))
        self.assertIsNone(guard(request(PATH, 'POST')))
        for path in ('/api/reading', '/api/plans', PATH+'/extra'):
            self.assertEqual(guard(request(path)).status_code, 401)
        self.assertEqual(guard(request(PATH, 'DELETE')).status_code, 401)
        self.assertEqual(self.client.get(PATH, auth=('owner',os.environ['APP_PASSWORD'])).status_code,200)


class CloudDailyReadingTests(CloudFixture):
    def test_mixed_collection_fills_target_when_classics_are_already_read(self):
        from reading.sources import choose
        rows=[{'id':str(i),'title':'Technology science and society','summary':'psychology',
               'language':'en','source':str(i),'category':'recent','topics':['科技'],
               'published_at':DATE[:10]} for i in range(4)]
        self.assertEqual(len(choose(rows,DEFAULT,set(),DATE[:10])),3)

    def test_daily_collection_persists_once_and_recovers_after_restart(self):
        self.reader.save_preferences({**DEFAULT, 'mode': 'classic'})
        service = Reader(self.reader)
        dt = datetime.fromisoformat(DATE)
        async def run():
            with patch('reading.service.now', return_value=DATE), \
                 patch('reading.service.fetch_article_content', return_value='Public full article text'):
                job = service.daily_tick(dt)
                self.assertIsNotNone(job)
                await asyncio.gather(*list(service.tasks.values()))
            result = self.reader.record(job['id'])
            self.assertEqual(result['state'], 'ready', result)
            self.assertEqual(len(result['saved_ids']), 3)
            self.assertIsNone(service.daily_tick(dt))
            self.reader.initialize()
            self.assertIsNone(Reader(self.reader).daily_tick(dt))
            for aid in result['saved_ids']:
                self.assertTrue(self.reader.article(aid)['hashes'])
        asyncio.run(run())

    def test_failed_daily_jobs_retry_with_cooldown_and_limit(self):
        self.reader.save_preferences(DEFAULT)
        dt = datetime.fromisoformat(DATE)
        service = Reader(self.reader)
        base = 'daily-' + DATE[:10]
        for attempt in range(3):
            key = base if not attempt else base+'-retry-'+str(attempt)
            self.reader.put(TABLE, 'job-'+key, {'id':'job-'+key, 'type':'job', 'kind':'collect',
                'state':'failed', 'daily':True, 'date':DATE[:10], 'created_at':DATE,
                'finished_at':DATE, 'error':'Test network failure'})
            with patch.object(service, 'begin', return_value={'id':'next'}) as begin:
                self.assertIsNone(service.daily_tick(dt+timedelta(minutes=1)))
                result = service.daily_tick(dt+timedelta(minutes=20))
                if attempt < 2:
                    self.assertEqual(result, {'id':'next'})
                    self.assertEqual(begin.call_args.args[0]['key'],base+'-retry-'+str(attempt+1))
                else:
                    self.assertIsNone(result); begin.assert_not_called()
        self.reader.save_preferences({**DEFAULT, 'enabled':False})
        with patch.object(service, 'begin') as begin:
            self.assertIsNone(service.daily_tick(dt+timedelta(hours=1)))
            begin.assert_not_called()
