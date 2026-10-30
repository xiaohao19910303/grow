"""C05 sessions on real disposable PostgreSQL; canonical upstream mocked only in this unit layer."""
import os
import json
from pathlib import Path
from unittest.mock import patch
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_legacy_cloud_schema import PostgreSQLFixture
import accounts
import zook_web_auth as web
from copilot.core import Problem

class ZookWebSessionsTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        env=patch.dict(os.environ,{'APP_PASSWORD':'SYNTHETIC_OWNER_PASSWORD_24_CHARACTERS','APP_USERNAME':'owner','ACCOUNT_ENCRYPTION_KEY':Fernet.generate_key().decode(),'GROW_ZOOK_WEB_AUTH_ENABLED':'1','LIGHTTICK_BRIDGE_URL':'http://127.0.0.1:31999'})
        env.start();self.addCleanup(env.stop)
        self.calls=[];self.expired=False;self.revoked=False;self.fail_after_refresh=False
        def upstream(path,method='GET',body=None,token=None,headers=None,query=None):
            self.calls.append((path,method,body,token))
            if path.endswith('/auth/login'):
                if body['password']!='SYNTHETIC_PASSWORD':raise Problem('INVALID','Wrong credentials',401)
                return {'accessToken':'access-'+body['account'],'refreshToken':'refresh-'+body['account'],'expiresIn':300}
            if path.endswith('/auth/refresh'):
                if self.revoked:raise Problem('INVALID','Revoked',401)
                self.expired=False
                return {'accessToken':'access-alice','refreshToken':'rotated-alice','expiresIn':300}
            if path.endswith('/auth/logout'):return {'ok':True}
            if path.endswith('/account/session'):
                if self.expired or self.revoked:raise Problem('INVALID','Expired',401)
                if self.fail_after_refresh:
                    self.fail_after_refresh=False;raise Problem('TEMPORARY','Temporary membership outage',503)
                return {'app_id':'lighttick','account_kind':'registered','membership_status':'ACTIVE','user_id':token.removeprefix('access-')}
            raise AssertionError(path)
        fake=patch.object(web,'upstream',side_effect=upstream);fake.start();self.addCleanup(fake.stop)
        self.app=FastAPI();self.accounts=accounts.install(self.app,Path(__file__).parent,lambda user:None);self.accounts.initialize()
        self.client=TestClient(self.app,base_url='https://grow.example');self.addCleanup(self.client.close)
        self.headers={'X-Copilot-Request':'1'}
        self.assertEqual(self.client.post('/api/auth/login',json={'username':'owner','password':os.environ['APP_PASSWORD']},headers=self.headers).status_code,200)
    def post(self,path,body):return self.client.post('/api/auth/zook/'+path,json=body,headers=self.headers)
    def credentials(self,account='alice',consent=True):return {'account':account,'password':'SYNTHETIC_PASSWORD','consent':consent}
    def test_explicit_link_uses_encrypted_tokens_and_no_implicit_merge(self):
        self.assertEqual(self.post('link',self.credentials(consent=False)).status_code,422)
        linked=self.post('link',self.credentials());self.assertEqual(linked.status_code,200,linked.text)
        self.assertNotIn('access-',linked.text);self.assertIn('httponly',linked.headers['set-cookie'].lower())
        with self.accounts.conn() as c:
            stored=c.execute('SELECT encrypted FROM auth_zook_sessions').fetchone()[0]
            self.assertNotIn('access-',stored);self.assertNotIn('refresh-',stored)
        self.assertEqual(self.client.get('/api/auth/me').json()['auth_mode'],'zook')
        self.assertEqual(self.post('link',self.credentials('bob')).status_code,409)
    def test_refresh_revocation_does_not_fall_back_to_legacy_cookie_and_logout_clears(self):
        self.assertEqual(self.post('link',self.credentials()).status_code,200)
        self.expired=True
        self.assertEqual(self.client.get('/api/auth/me').status_code,200)
        self.assertEqual(sum(p.endswith('/auth/refresh') for p,*_ in self.calls),1)
        self.revoked=True
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)
        logout=self.client.post('/api/auth/logout',headers=self.headers);self.assertEqual(logout.status_code,200,logout.text)
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)
    def test_unassociated_zook_identity_cannot_open_existing_grow_space(self):
        self.assertEqual(self.post('login',self.credentials('bob')).status_code,409)
        self.assertEqual(self.client.get('/api/auth/me').json()['user']['id'],'owner')
        denied=self.client.post('/api/auth/zook/link',json=self.credentials(),headers={**self.headers,'Origin':'https://evil.example'})
        self.assertEqual(denied.status_code,403)

    def test_rotated_refresh_survives_membership_outage(self):
        self.assertEqual(self.post('link',self.credentials()).status_code,200)
        self.expired=True;self.fail_after_refresh=True
        self.assertEqual(self.client.get('/api/auth/me').status_code,503)
        with self.accounts.conn() as c:
            saved=self.app.state.zook_web_sessions.decrypt(c.execute('SELECT encrypted FROM auth_zook_sessions').fetchone()[0])
        self.assertEqual(saved['refreshToken'],'rotated-alice')
        self.assertEqual(self.client.get('/api/auth/me').status_code,200)
        self.assertEqual(sum(p.endswith('/auth/refresh') for p,*_ in self.calls),1)

    def test_mapped_record_claim_rejects_other_target_before_claim(self):
        from tenancy import current_user
        from types import SimpleNamespace
        import record_handoff
        token=current_user.set({**self.accounts.owner(),'zook_target_user_id':'alice'})
        try:
            with patch.dict(os.environ,{'GROW_RECORDS_SOURCE_ID':'synthetic','GROW_RECORDS_BRIDGE_SECRET':'synthetic-record-secret-1234567890123456'}),patch('record_handoff.httpx.Client') as client:
                response=SimpleNamespace(status_code=200,json=lambda:{'data':{'target_user_id':'bob'}})
                send=client.return_value.__enter__.return_value.post;send.return_value=response
                with self.assertRaises(Problem) as caught:record_handoff.call({'action':'claim','code':'synthetic-code'})
                self.assertEqual(caught.exception.status,409)
                self.assertEqual(send.call_count,1)
                self.assertEqual(send.call_args.kwargs['json']['action'],'preview')
        finally:current_user.reset(token)

    def test_first_link_serializes_with_inflight_target_handoff(self):
        import threading,time
        from concurrent.futures import ThreadPoolExecutor
        from tenancy import current_user
        entered=threading.Event();release=threading.Event()
        @self.app.post('/api/action-link/preview')
        def incoming_handoff():
            entered.set();release.wait(5)
            web.assert_target('bob')
            with self.accounts.conn() as c:
                c.execute('CREATE TABLE IF NOT EXISTS action_link_state (id INTEGER PRIMARY KEY,data TEXT NOT NULL)')
                c.execute('INSERT INTO action_link_state VALUES (1,?)',(json.dumps({'phase':'preview','target_user_id':'bob'}),))
            return {'target_user_id':'bob'}
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(lambda:self.client.post('/api/action-link/preview',json={},headers=self.headers))
            self.assertTrue(entered.wait(5))
            second=pool.submit(lambda:self.post('link',self.credentials()))
            time.sleep(.1);self.assertFalse(second.done())
            release.set();self.assertEqual(first.result().status_code,200)
            self.assertEqual(second.result().status_code,409)
        self.assertIsNone(self.app.state.zook_web_sessions.association('owner'))
