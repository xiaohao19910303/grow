"""NB09 canonical object identity, bounded C05 proxy and rejection recovery."""
import os
import uuid
from unittest.mock import patch
import httpx
from test_zook_web_http import CanonicalWebHTTPTests


class NativeBasicPlansTests(CanonicalWebHTTPTests):
    def setUp(self):
        super().setUp()
        flag=patch.dict(os.environ,{'GROW_NATIVE_BASIC_PLANS_ENABLED':'1'});flag.start();self.addCleanup(flag.stop)

    def payload(self):
        return {'title':'Same canonical goal','completion_criteria':'One example','period_start':'2026-10-31','period_end':'2026-11-01','tasks':[{'id':'one','title':'A small action','scheduled_for':None,'estimated_minutes':None,'completion_criteria':'An example','guidance':''}]}

    def web_plan(self,path='',method='GET',body=None,key=None):
        return self.client.request(method,'/api/native-plans/'+path,json=body,headers={**self.headers,'Idempotency-Key':key or 'web-plan-'+uuid.uuid4().hex})

    def native_plan(self,path,method='GET',body=None,key=None,other=False):
        return httpx.request(method,self.f.url+'/api/v1/lighttick/'+path,json=body,headers={'Authorization':'Bearer '+self.f.owners[1 if other else 0]['token'],'X-App-Id':'lighttick','X-LightTick-Task-Schema':'2','Idempotency-Key':key or 'native-plan-'+uuid.uuid4().hex})

    def test_same_plan_native_web_conflict_and_explicit_confirmation(self):
        self.assertEqual(self.link().status_code,200)
        r=self.web_plan('manual-plans','POST',self.payload(),'web-create-stable');self.assertIn(r.status_code,(200,201),r.text);p=r.json()['data']
        native=self.native_plan('manual-plans/'+p['id']);self.assertEqual(native.status_code,200,native.text);self.assertEqual(native.json()['data']['id'],p['id'])
        edited={**p['draft'],'base_version':p['version']};edited['tasks'][0]['title']='Edited from native'
        r=self.native_plan('manual-plans/'+p['id'],'PATCH',edited);self.assertEqual(r.status_code,200,r.text);latest=r.json()['data']
        conflict=self.web_plan('manual-plans/'+p['id'],'PATCH',{**p['draft'],'base_version':p['version']});self.assertEqual(conflict.status_code,409,conflict.text)
        r=self.web_plan('manual-plans/'+p['id']);self.assertEqual(r.json()['data']['version'],latest['version']);self.assertEqual(r.json()['data']['draft']['tasks'][0]['title'],'Edited from native')
        foreign=self.native_plan('manual-plans/'+p['id'],other=True);self.assertEqual(foreign.status_code,404)
        body={'base_version':latest['version'],'goal_base_version':latest['goal_version']}
        r=self.web_plan('manual-plans/'+p['id']+'/confirm','POST',body,'web-confirm-stable');self.assertEqual(r.status_code,200,r.text)
        replay=self.web_plan('manual-plans/'+p['id']+'/confirm','POST',body,'web-confirm-stable');self.assertEqual(replay.json(),r.json())
        self.assertEqual(self.native_plan('manual-plans/'+p['id']).json()['data']['status'],'active')
        # The proxy has no Grow plan write path, and the target retains exactly one basic plan.
        self.assertEqual(len(self.native_plan('manual-plans').json()['data']['items']),1)

    def test_proxy_allowlist_csrf_owner_and_flag(self):
        self.assertEqual(self.link().status_code,200)
        for path in ['records','planning-sessions','manual-plans/x/confirm/extra','goals/x/conditions']:
            r=self.web_plan(path);self.assertEqual(r.status_code,403,(path,r.text))
        self.assertEqual(self.web_plan('manual-plans?owner=other').status_code,422)
        self.assertEqual(self.client.post('/api/native-plans/manual-plans',json=self.payload()).status_code,403)
        mismatch=self.client.post('/api/native-plans/manual-plans',json=self.payload(),headers={**self.headers,'X-Account-Id':'wrong','Idempotency-Key':'cross-account-key'});self.assertEqual(mismatch.status_code,409)
        with patch.dict(os.environ,{'GROW_NATIVE_BASIC_PLANS_ENABLED':'0'}):
            self.assertFalse(self.client.get('/api/native-plans/config').json()['enabled'])
            self.assertEqual(self.client.get('/native-plans').status_code,404)
            self.assertEqual(self.web_plan('manual-plans').status_code,503)
        self.assertEqual(self.native_plan('manual-plans').status_code,200)

    def test_expired_web_session_refreshes_then_revocation_rejects(self):
        self.assertEqual(self.link().status_code,200);self.expire()
        self.assertEqual(self.web_plan('manual-plans').status_code,200)
        self.assertEqual(self.client.post('/api/auth/logout',headers=self.headers).status_code,200)
        self.assertEqual(self.web_plan('manual-plans').status_code,401)
        self.assertEqual(self.native_plan('manual-plans').status_code,200)
