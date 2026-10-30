"""C05 with real canonical Zook auth and data handlers plus disposable PostgreSQL."""
import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import httpx
from cryptography.fernet import Fernet
from fastapi import Request
import accounts
import zook_web_auth as auth
import zook_web_proxy as proxy
from tenancy import current_user
import test_learning_practice_http as fixture

class CanonicalWebHTTPTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.LearningPracticeHTTPTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        env=patch.dict(os.environ,{'APP_PASSWORD':'SYNTHETIC_GROW_PASSWORD_24_CHARACTERS','APP_USERNAME':'owner','ACCOUNT_ENCRYPTION_KEY':Fernet.generate_key().decode(),'GROW_ZOOK_WEB_AUTH_ENABLED':'1'})
        env.start();self.addCleanup(env.stop)
        self.accounts=accounts.install(self.f.app,Path(__file__).parents[1]/'static',lambda user:None);self.accounts.initialize()
        token=current_user.set(self.accounts.owner());self.addCleanup(current_user.reset,token)
        @self.f.app.get('/api/fixture/history/{identifier}')
        def history(identifier:str):return proxy.records('detail',id=identifier)
        from types import SimpleNamespace
        from record_handoff_api import register
        register(self.f.app, SimpleNamespace(conn=self.f.s.conn))
        self.client=self.f.client;self.headers=self.f.headers
        r=self.client.post('/api/auth/login',json={'username':'owner','password':os.environ['APP_PASSWORD']},headers=self.headers);self.assertEqual(r.status_code,200,r.text)
    def link(self,index=0):
        return self.client.post('/api/auth/zook/link',json={'account':self.f.owners[index]['account'],'password':'Password1234','consent':True},headers=self.headers)
    def tokens(self):
        with self.accounts.conn() as c:row=c.execute('SELECT encrypted FROM auth_zook_sessions').fetchone()
        return self.f.app.state.zook_web_sessions.decrypt(row[0])
    def expire(self):
        with self.accounts.conn() as c:
            row=c.execute('SELECT digest,encrypted FROM auth_zook_sessions').fetchone();value=self.f.app.state.zook_web_sessions.decrypt(row[1]);value['accessToken']=self.f.owners[0]['expired_token']
            c.execute('UPDATE auth_zook_sessions SET encrypted=? WHERE digest=?',(self.f.app.state.zook_web_sessions.encrypt(value),row[0]))
    def test_real_login_data_refresh_concurrency_and_expired_logout(self):
        linked=self.link();self.assertEqual(linked.status_code,200,linked.text)
        self.assertNotIn('Token',linked.text);self.assertEqual(self.client.get('/api/auth/me').json()['auth_mode'],'zook')
        _,lesson=self.f.prepare_practice()
        # Public Token route continues to work with the source bridge secret removed.
        with patch.dict(os.environ,{'GROW_ACTION_BRIDGE_SECRET':''}):
            r=self.client.post('/api/action-plans/practices',headers=self.headers,json={'key':'unified-practice-create','title':'One real presentation','source_kind':'lesson','source_id':lesson['id'],'source_version':lesson['content_version'],'date':None,'timezone':'UTC'})
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(len(self.client.get('/api/action-plans/practices').json()['practices']),1)
        record='record-unified-history'
        saved=httpx.put(self.f.url+'/api/v1/lighttick/records/'+record,headers={'Authorization':'Bearer '+self.f.owners[0]['token'],'X-App-Id':'lighttick','Idempotency-Key':'unified-record-create'},json={'raw_text':'Private input','record_date':'2026-10-30','base_version':0})
        self.assertEqual(saved.status_code,200,saved.text)
        detail=self.client.get('/api/fixture/history/'+record);self.assertEqual(detail.status_code,200,detail.text);self.assertEqual(detail.json()['record']['raw_text'],'Private input')
        before=self.tokens()['refreshToken'];self.expire();calls=[];send=auth.upstream
        def counted(path,*args,**kwargs):
            if path.endswith('/auth/refresh'):calls.append(path)
            return send(path,*args,**kwargs)
        with patch.object(auth,'upstream',side_effect=counted),ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.client.get('/api/auth/me').status_code,range(2)))
        self.assertEqual(results,[200,200]);self.assertEqual(len(calls),1);self.assertNotEqual(before,self.tokens()['refreshToken'])
        self.expire();logout=self.client.post('/api/auth/logout',headers=self.headers);self.assertEqual(logout.status_code,200,logout.text)
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)
        with self.accounts.conn() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM auth_zook_sessions').fetchone()[0],0)
    def test_unlinked_identity_cross_target_and_legacy_proxy_are_rejected(self):
        self.assertEqual(self.link().status_code,200)
        ticket=self.f.native('POST','action-link-tickets',{},other=True)
        rejected=self.client.post('/api/action-link/preview',json={'code':ticket['code']},headers=self.headers)
        self.assertEqual(rejected.status_code,409,rejected.text)
        with self.f.s.conn() as c:
            c.execute('CREATE TABLE IF NOT EXISTS reflection_link_state (id INTEGER PRIMARY KEY,data TEXT NOT NULL)')
            c.execute("INSERT INTO reflection_link_state VALUES (1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (json.dumps({'phase':'active'}),))
        # Switching back to Grow credentials explicitly removes the previous BFF cookie.
        r=self.client.post('/api/auth/login',json={'username':'owner','password':os.environ['APP_PASSWORD']},headers=self.headers);self.assertEqual(r.status_code,200)
        self.assertEqual(self.client.get('/api/auth/me').json()['auth_mode'],'grow')
        with patch.object(proxy,'upstream',side_effect=AssertionError('A legacy cookie must not reach Zook')):
            self.assertEqual(self.client.get('/api/record-link/export').status_code,403)
