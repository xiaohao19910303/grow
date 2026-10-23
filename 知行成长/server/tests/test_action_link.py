"""Single-writer handoff tests against a disposable localhost schema."""
from unittest.mock import patch
from datetime import datetime,timezone,timedelta
import uuid

from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
import db
import action_plans as actions
import action_link as link
from tenancy import current_user
from test_legacy_cloud_schema import PostgreSQLFixture

class ActionLinkTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp();app=FastAPI();actions.register(app);self.client=TestClient(app,base_url='http://localhost');self.addCleanup(self.client.close)
        token=current_user.set({'id':'grow-test-alice','is_owner':False});self.addCleanup(current_user.reset,token)
        env=patch.dict('os.environ',{'LIGHTTICK_BRIDGE_URL':'http://127.0.0.1:9876','GROW_ACTION_BRIDGE_SECRET':'TEST_ONLY_BRIDGE_SECRET_01234567890123456789'});env.start();self.addCleanup(env.stop)
        self.headers={'X-Copilot-Request':'1','X-Grow-Action-Schema':'2'};self.code='a'*36;self.imports=[];self.sources=[];self.drop_response=False;self.bad_receipt=False
        mock=patch('action_link.call',self.remote);mock.start();self.addCleanup(mock.stop)
    def remote(self,source,body):
        self.sources.append(source)
        if body['action']=='preview':return {'target_user_id':'lighttick-test-alice','expires_at':(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}
        if body['action']=='claim':return {'binding_id':'binding-test','target_user_id':'lighttick-test-alice','phase':'staged'}
        if body['action']=='import':
            self.imports.append(body)
            receipt={'binding_id':'binding-test','target_user_id':'lighttick-test-alice','snapshot_hash':body['snapshot_hash'],'source_counts':link.counts(body['snapshot'])}
            if self.drop_response:self.drop_response=False;raise HTTPException(503,'response lost')
            if self.bad_receipt:receipt['snapshot_hash']='0'*64
            return receipt
        if body['action']=='request':return {'from':'zook','path':body['path'],'method':body['method']}
    def post(self,path,body):return self.client.post('/api/action-link'+path,json=body,headers=self.headers)
    def create(self,title='先读书'):
        response=self.client.post('/api/action-plans',json=dict(title=title,period='day',start_date='2026-10-20',end_date='2026-10-20',key=str(uuid.uuid4())),headers=self.headers);self.assertEqual(response.status_code,200,response.text)
        # This suite exercises the legacy import protocol, not P0 eligibility.
        # New P0/rhythm data is rejected in the separate boundary tests.
        plan=response.json()['plans'][0];plan['schema_version']=1
        with actions.connection(True) as c:
            actions.write(c,plan)
            c.execute('DELETE FROM action_operations')
        return plan
    def preview(self):
        response=self.post('/preview',{'code':self.code});self.assertEqual(response.status_code,200,response.text);return response.json()
    def confirm(self,preview,**extra):return self.post('/confirm',{'code':self.code,'preview_id':preview['preview_id'],'consent':True}|extra)
    def test_preview_consent_exact_snapshot_backup_and_proxy(self):
        self.create();p=self.preview();self.assertEqual(p['counts']['plans'],1)
        self.assertEqual(self.confirm(p,consent=False).status_code,422)
        result=self.confirm(p);self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['phase'],'active')
        forwarded=self.client.get('/api/action-plans');self.assertEqual(forwarded.json()['from'],'zook')
        self.assertTrue(all(s=='grow-test-alice' for s in self.sources))
        with actions.connection() as c:
            metadata,backup=link.state(c);self.assertEqual(len(backup['plans']),1);self.assertEqual(link.fingerprint(backup),metadata['snapshot_hash'])
            self.assertEqual(c.execute('SELECT count(*) FROM action_plans').fetchone()[0],1)
            self.assertNotIn(self.code,actions.encoded(metadata));self.assertNotIn('TEST_ONLY_BRIDGE_SECRET',actions.encoded(metadata))
        with self.assertRaises(HTTPException):actions.create(actions.NewPlan(title='不得双写',period='day',start_date='2026-10-20',end_date='2026-10-20',key='blocked-local-key'))
        with patch.dict('os.environ',{'GROW_ACTION_BRIDGE_SECRET':''}):
            # The trusted transport is mocked, so validate the configuration guard separately.
            self.assertIsNone(link.configuration())
    def test_lost_import_response_stays_frozen_and_retry_uses_identical_backup(self):
        self.create();p=self.preview();self.drop_response=True
        self.assertEqual(self.confirm(p).status_code,503)
        self.assertEqual(self.client.get('/api/action-plans').status_code,503)
        self.assertEqual(self.client.post('/api/action-plans',json={},headers=self.headers).status_code,503)
        result=self.post('/retry',{});self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['phase'],'active')
        self.assertEqual(self.imports[0],self.imports[1]);self.assertEqual(len(self.imports),2)
        self.assertEqual(self.post('/retry',{}).status_code,200);self.assertEqual(len(self.imports),2)
    def test_changed_facts_stale_preview_and_receipt_mismatch_never_activate(self):
        self.create();p=self.preview();self.create('第二项');self.assertEqual(self.confirm(p).status_code,409)
        self.assertEqual(self.client.get('/api/action-link').json()['phase'],'local')
        p=self.preview();self.bad_receipt=True;self.assertEqual(self.confirm(p).status_code,503)
        self.assertEqual(self.client.get('/api/action-link').json()['phase'],'pending');self.assertEqual(self.client.get('/api/action-plans').status_code,503)
    def test_same_origin_identity_and_configuration_bounds(self):
        self.assertEqual(self.client.post('/api/action-link/preview',json={'code':self.code}).status_code,403)
        self.assertEqual(self.client.post('/api/action-link/preview',json={'code':self.code},headers=self.headers|{'Origin':'https://foreign.example'}).status_code,403)
        self.preview();self.assertEqual(self.sources,['grow-test-alice'])
        for url in ['http://remote.example','https://user:password@example.com','https://example.com?token=value','https://example.com/other']:
            with patch.dict('os.environ',{'LIGHTTICK_BRIDGE_URL':url}):self.assertIsNone(link.configuration())
    def test_new_content_or_check_schedule_is_never_silently_converted(self):
        plan=self.create()
        with actions.connection(True) as c:
            import json
            row=c.execute('SELECT data FROM action_plans WHERE id=?',(plan['id'],)).fetchone()
            value=json.loads(row[0]);value['completion_mode']='check'
            c.execute('UPDATE action_plans SET data=? WHERE id=?',(actions.encoded(value),plan['id']))
        response=self.post('/preview',{'code':self.code});self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(self.client.get('/api/action-link').json()['phase'],'local');self.assertEqual(self.imports,[])
