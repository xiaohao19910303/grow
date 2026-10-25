"""Real HTTP Zook + disposable source PostgreSQL; no personal accounts or data."""
import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch
import httpx
from cloud_fixtures import CloudFixture
from copilot.core import Problem
from reflections.store import ReflectionsStore
from tenancy import current_user
import record_handoff as handoff
from record_handoff_api import proxy

SECRET='record-handoff-integration-test-secret-123456'
class RecordHandoffTests(CloudFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        zook=Path(os.environ['TEST_ZOOK_WORKTREE']);cls.stderr=tempfile.TemporaryFile(mode='w+')
        cls.server=subprocess.Popen(['node','--experimental-transform-types','test/support/lighttick-record-handoff-http-fixture.ts'],cwd=zook,stdout=subprocess.PIPE,stderr=cls.stderr,text=True,env={**os.environ,'LIGHTTICK_RECORD_HANDOFF_ENABLED':'1','GROW_RECORDS_SOURCE_ID':'grow-source-test','GROW_RECORDS_BRIDGE_SECRET':SECRET,'LIGHTTICK_TEST_DATABASE_URL':'postgresql://localhost:55439/postgres'})
        while True:
            line=cls.server.stdout.readline()
            if line.startswith('READY '):cls.fixture=json.loads(line[6:]);break
            if not line:
                cls.stderr.seek(0);raise RuntimeError(cls.stderr.read())
        cls.url='http://127.0.0.1:'+str(cls.fixture['port'])
    @classmethod
    def tearDownClass(cls):
        cls.server.terminate();cls.server.wait(timeout=20);cls.stderr.close();super().tearDownClass()
    def setUp(self):
        super().setUp()
        self.env=patch.dict(os.environ,{'LIGHTTICK_BRIDGE_URL':self.url,'GROW_RECORDS_SOURCE_ID':'grow-source-test','GROW_RECORDS_BRIDGE_SECRET':SECRET});self.env.start();self.addCleanup(self.env.stop)
        self.owner=self.fixture['owners'][0];self.other=self.fixture['owners'][1]
        self.identity=current_user.set({'id':'source-'+self.schema,'schema_name':self.schema,'is_owner':True});self.addCleanup(current_user.reset,self.identity)
        self.store=ReflectionsStore(self.root,self.runtime);self.store.initialize()
        self.data={'record_date':'2026-10-25','raw_text':'PRIVATE first original','prompt_kind':'自由记录','guided_answers':{'补充':'回答😀'},'tags':['synthetic']}
        self.id=self.store.create(self.data,'source-create-key')['id']
    def api(self,method,path,body=None,key=None,owner=None):
        headers={'Authorization':'Bearer '+(owner or self.owner)['token'],'X-App-Id':'lighttick'}
        if key:headers['Idempotency-Key']=key
        return httpx.request(method,self.url+'/api/v1/lighttick/'+path,json=body,headers=headers)
    def ticket(self):return self.api('POST','record-link/tickets',{}).json()['data']['code']
    def preview(self):
        code=self.ticket();return code,handoff.preview(self.store,code)
    def reset_target(self):
        # Each source test uses a separate target by deleting only this synthetic app owner.
        self.api('DELETE','account')
    def test_01_preserves_history_gaps_ai_and_cross_end_edits(self):
        self.store.update(self.id,{**self.data,'base_version':1,'raw_text':'PRIVATE second'},'source-update-key')
        self.store._put('reflection_ai_attempts','source-ready-attempt',{'id':'source-ready-attempt','entry_id':self.id,'kind':'organize','status':'ready','version_at_request':2,'sections':[{'kind':'event','text':'PRIVATE AI SUMMARY'}]})
        self.store.adopt(self.id,'source-ready-attempt','source-adopt-key');self.store.archive(self.id,'source-archive-key');self.store.restore(self.id,'source-restore-key')
        code,preview=self.preview();self.assertEqual(preview['counts'],{'records':1,'versions':2,'history_gaps':2})
        result=handoff.confirm(self.store,code,preview['preview_id'],True);self.assertEqual(result['phase'],'active')
        entries=self.api('GET','records?archived=all').json()['data']['items'];record=next(e for e in entries if e.get('source',{}).get('id')==self.id)
        self.assertEqual(record['source']['missing_versions'],[3,4]);self.assertEqual(record['version'],5)
        self.assertIn('PRIVATE AI SUMMARY',self.api('GET','records/export').text)
        self.assertNotIn('PRIVATE',self.api('GET','records/export',owner=self.other).text)
        saved=self.api('PUT','records/'+record['id'],{**{k:record[k] for k in ('raw_text','record_date','prompt_kind','guided_answers','tags')},'raw_text':'NATIVE EDIT','base_version':5},'native-update-key');self.assertEqual(saved.status_code,200,saved.text)
        detail=proxy(self.store,'/api/reflections/'+self.id,'GET',{},{});self.assertEqual(detail['entry']['raw_text'],'NATIVE EDIT')
        version=detail['entry']['version'];proxy(self.store,'/api/reflections/'+record['id'],'PUT',{},dict(self.data,base_version=version,raw_text='WEB EDIT',key='web-update-key'))
        self.assertEqual(self.api('GET','records/'+record['id']).json()['data']['raw_text'],'WEB EDIT')
        before=self.store.entry(self.id)
        with self.assertRaises(Problem):self.store.update(self.id,{**self.data,'base_version':5},'late-local-key')
        with self.assertRaises(Problem):self.store._put('reflection_ai_attempts','source-ready-attempt',{})
        fresh=ReflectionsStore(self.root,self.runtime);fresh.initialize();self.assertEqual(fresh.entry(self.id),before)
        self.assertEqual(handoff.finish(fresh)['receipt'],result['receipt'])
    def test_02_preview_stale_and_no_consent_leave_source_writable(self):
        code,preview=self.preview()
        with self.assertRaises(Problem):handoff.confirm(self.store,code,preview['preview_id'],False)
        self.store.update(self.id,{**self.data,'base_version':1},'source-after-preview')
        with self.assertRaises(Problem):handoff.confirm(self.store,code,preview['preview_id'],True)
        self.assertEqual(handoff.state(self.store)['phase'],'preview')
    def test_03_activation_response_loss_does_not_overwrite_newer_target(self):
        # Use a different synthetic target for the second activated source.
        self.owner=self.other
        code,preview=self.preview();real=handoff.call
        def lose(body):
            result=real(body)
            if body['action']=='activate':raise Problem('lost','simulated response loss',503)
            return result
        with patch('record_handoff.call',side_effect=lose),self.assertRaises(Problem):handoff.confirm(self.store,code,preview['preview_id'],True)
        self.assertEqual(handoff.state(self.store)['phase'],'frozen')
        entry=self.api('GET','records').json()['data']['items'][0]
        self.assertEqual(self.api('PUT','records/'+entry['id'],{**{k:entry[k] for k in ('raw_text','record_date','prompt_kind','guided_answers','tags')},'raw_text':'NEWER TARGET','base_version':entry['version']},'after-lost-response').status_code,200)
        with self.assertRaises(Problem):handoff.cancel(self.store)
        result=handoff.finish(self.store);self.assertEqual(result['phase'],'active')
        self.assertEqual(self.api('GET','records/'+entry['id']).json()['data']['raw_text'],'NEWER TARGET')
        recovery=self.api('POST','record-link/readonly',{});self.assertEqual(recovery.status_code,200,recovery.text);self.assertIn('NEWER TARGET',recovery.text)
        with self.assertRaises(Problem):proxy(self.store,'/api/reflections/'+entry['id'],'PUT',{},dict(self.data,base_version=2,key='blocked-web-update'))
    def test_04_stage_response_loss_can_cancel_before_activation(self):
        # Claim a previously cancelled operation on the same target using a fresh ticket.
        # Use a separate fixture user because both earlier users are actively linked.
        code=self.ticket()
        with patch('record_handoff.call',return_value={'target_user_id':self.owner['userId'],'expires_at':'2099-01-01T00:00:00Z'}):preview=handoff.preview(self.store,code)
        real=handoff.call
        def unavailable(body):
            if body['action']=='preview':return real(body)
            if body['action']=='status':raise Problem('not_found','not bound',404)
            if body['action']=='claim':return {'operation_id':handoff.state(self.store)['operation_id'],'target_user_id':self.owner['userId'],'binding_id':'synthetic-cancel-binding'}
            if body['action']=='stage':raise Problem('offline','synthetic offline',503)
            if body['action']=='cancel':return {'phase':'cancelled'}
        with patch('record_handoff.call',side_effect=unavailable),self.assertRaises(Problem):handoff.confirm(self.store,code,preview['preview_id'],True)
        with patch('record_handoff.call',side_effect=unavailable):handoff.cancel(self.store)
        self.store.update(self.id,{**self.data,'base_version':1,'raw_text':'WRITABLE AFTER CANCEL'},'after-cancel-key')
        self.assertEqual(self.store.entry(self.id)['raw_text'],'WRITABLE AFTER CANCEL')

    def test_05_confirmed_cancel_can_start_a_new_real_handoff(self):
        self.owner=self.fixture['owners'][2]
        code,preview=self.preview();real=handoff.call
        def before_activation(body):
            if body['action']=='activate':raise Problem('offline','activation was not sent',503)
            return real(body)
        with patch('record_handoff.call',side_effect=before_activation),self.assertRaises(Problem):handoff.confirm(self.store,code,preview['preview_id'],True)
        self.assertEqual(self.api('GET','records').json()['data']['items'],[])
        self.assertEqual(handoff.cancel(self.store)['phase'],'local')
        self.store.update(self.id,{**self.data,'base_version':1,'raw_text':'after confirmed cancel'},'source-after-cancel')
        code,preview=self.preview();self.assertEqual(handoff.confirm(self.store,code,preview['preview_id'],True)['phase'],'active')
        record=self.api('GET','records').json()['data']['items'][0];self.assertEqual(record['raw_text'],'after confirmed cancel');self.assertEqual(record['version'],2)
    def test_06_multiple_adoptions_preserve_unknown_old_basis_without_invention(self):
        self.owner=self.fixture['owners'][3]
        def adopt(key,text):
            version=self.store.entry(self.id)['version']
            self.store._put('reflection_ai_attempts',key,{'id':key,'entry_id':self.id,'kind':'organize','status':'ready','version_at_request':version,'sections':[{'kind':'event','text':text}]})
            self.store.adopt(self.id,key,key+'-adopt')
        def update(key):self.store.update(self.id,{**self.data,'base_version':self.store.entry(self.id)['version']},key)
        adopt('first-summary','PRIVATE FIRST SUMMARY');update('edit-3');update('edit-4');update('edit-5')
        adopt('second-summary','PRIVATE SECOND SUMMARY');update('edit-7')
        code,preview=self.preview();self.assertEqual(handoff.confirm(self.store,code,preview['preview_id'],True)['phase'],'active')
        exported=self.api('GET','records/export').json()['data']['records'][0]
        self.assertEqual(exported['record']['summary_basis_version'],5)
        old=next(v for v in exported['versions'] if v['version']==3);self.assertNotIn('adopted_summary',old)
        private=exported['source_history']['private_history'];self.assertEqual(private['normalization']['summary_basis_missing_versions'],[3,4,5])
        self.assertEqual(next(v for v in private['versions'] if v['version']==3)['adopted_summary']['sections'][0]['text'],'PRIVATE FIRST SUMMARY')
        self.assertIn('PRIVATE SECOND SUMMARY',json.dumps(private))
