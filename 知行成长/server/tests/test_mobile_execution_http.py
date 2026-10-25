"""Real public Zook routes + private Grow source, using synthetic disposable PG."""
import copy
import json
import os
from pathlib import Path
import select
import subprocess
import tempfile
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import action_plans as actions
import mobile_progress
from cloud_fixtures import CloudFixture
from plans.api import register
from tenancy import current_user
from test_plans import B,D,S,content
from test_action_source_http import source_database_url,zook_worktree

SECRET='synthetic-mobile-execution-secret-1234567890'


class MobileExecutionHTTPTests(CloudFixture):
    def setUp(self):
        super().setUp()
        self.stderr=tempfile.TemporaryFile(mode='w+')
        self.proc=subprocess.Popen(['node','--experimental-transform-types','test/support/lighttick-record-handoff-http-fixture.ts'],cwd=zook_worktree(),text=True,stdout=subprocess.PIPE,stderr=self.stderr,
            env={**os.environ,'LIGHTTICK_TEST_DATABASE_URL':source_database_url(self.dsn),'LIGHTTICK_ACTIONS_ENABLED':'1','LIGHTTICK_ACTIONS_V2_ENABLED':'1','GROW_ACTION_BRIDGE_SECRET':SECRET})
        self.addCleanup(self.stop)
        if not select.select([self.proc.stdout],[],[],30)[0]:raise RuntimeError('Synthetic Zook fixture startup timed out')
        raw=self.proc.stdout.readline()
        if not raw.startswith('READY '):self.stderr.seek(0);raise RuntimeError(self.stderr.read())
        value=json.loads(raw[6:]);self.url='http://127.0.0.1:'+str(value['port']);self.owners=value['owners']
        env=patch.dict(os.environ,{'LIGHTTICK_BRIDGE_URL':self.url,'GROW_ACTION_BRIDGE_SECRET':SECRET,'GROW_PUBLIC_URL':'http://localhost/'})
        env.start();self.addCleanup(env.stop)
        token=current_user.set({'id':'mobile-source-'+self.schema,'schema_name':self.schema,'is_owner':True});self.addCleanup(current_user.reset,token)
        self.app=FastAPI()
        with patch('plans.api.make_store',return_value=self.s):register(self.app,self.root,self.runtime)
        actions.register(self.app);self.client=TestClient(self.app,base_url='http://localhost');self.addCleanup(self.client.close)
        self.headers={'X-Copilot-Request':'1','X-Grow-Action-Schema':'2'}

    def stop(self):
        self.proc.terminate();self.proc.wait(timeout=20);self.proc.stdout.close();self.stderr.close()

    def native(self,method,path='',body=None,other=False):
        headers={'Authorization':'Bearer '+self.owners[1 if other else 0]['token'],'X-App-Id':'lighttick','X-Grow-Action-Schema':'2'}
        r=httpx.request(method,self.url+'/api/v1/lighttick/'+path,headers=headers,json=body)
        self.assertEqual(r.status_code,200,r.text);return r.json()['data']

    def web(self,path,data):
        r=self.client.post('/api/'+path,json=data,headers=self.headers)
        self.assertEqual(r.status_code,200,r.text);return r.json()

    def test_h5_authoring_three_modes_source_completion_and_stage_progress_share_facts(self):
        doc=copy.deepcopy(D);doc['stages'].append({'title':'应用','goal':'用于现实'});doc['lessons'][1]['stage']=2
        draft=self.s.draft({'brief':B,'document':doc});pid=self.s.adopt(draft['id'],'mobile-adopt')['plan_id']
        self.s.save_sources(pid,S);ctx=self.s.course_context(pid);course=self.s.course_draft(ctx,content(ctx),'来源摘要')
        self.web('plans/drafts/'+course['id']+'/publish',{'data':{'key':'mobile-publish','expected_hash':course['content_hash']}})
        self.web('plans/'+pid+'/actions',{'data':{'key':'mobile-link-courses','expected_version':self.s.plan(pid)['version']}})
        day=actions.clock().date().isoformat()
        for mode in ('time','check'):
            actions.create(actions.NewPlan(title='手机'+mode,period='day',completion_mode=mode,start_date=day,end_date=day,timezone='UTC',key='mobile-create-'+mode))
        ticket=self.native('POST','action-link-tickets',{})
        preview=self.web('action-link/preview',{'code':ticket['code']});self.assertEqual(preview['snapshot_version'],2)
        active=self.web('action-link/confirm',{'code':ticket['code'],'preview_id':preview['preview_id'],'consent':True});self.assertEqual(active['phase'],'active')
        plans=self.native('GET','action-plans')['plans'];self.assertEqual({p['completion_mode'] for p in plans},{'time','check','content'})
        content_plan=next(p for p in plans if p['completion_mode']=='content');self.assertIsNone(content_plan['start_date']);self.assertIsNone(content_plan['target_minutes'])
        def op(p,action,key,**values):return self.native('POST','action-plans/'+p['id']+'/operations',{'key':key,'revision':p['revision'],'action':action,**values})
        c=op(content_plan,'reschedule','mobile-date-content',date=day)['plan']
        learned=self.web('plans/'+pid+'/lessons/1/feedback',{'data':{'key':'mobile-learned','state':'completed','comment':'PRIVATE NOTE NEVER TRANSFER','origin_action_id':c['id']}})
        self.assertEqual(learned['source_delivery_state'],'completed')
        self.assertEqual(next(p for p in self.native('GET','action-plans')['plans'] if p['id']==c['id'])['status'],'completed')
        send=mobile_progress.call
        def lost(source,payload):
            send(source,payload)
            raise RuntimeError('synthetic response loss after target commit')
        with patch('mobile_progress.call',lost):
            with self.assertRaises(RuntimeError):mobile_progress.sync(self.s)
        mobile_progress.sync(self.s);progress=self.native('GET','action-plans/learning-progress')['progress'];plan=progress['plans'][0]
        self.assertEqual((plan['completed_lessons'],plan['total_lessons'],plan['percent']),(1,2,50));self.assertEqual([s['percent'] for s in plan['stages']],[100,0]);self.assertNotIn('PRIVATE NOTE',json.dumps(progress))
        mobile_progress.sync(self.s);self.assertEqual(self.native('GET','action-plans/learning-progress')['progress']['source_revision'],1)
        check=next(p for p in plans if p['completion_mode']=='check');done=op(check,'complete','mobile-check-once');op(done['plan'],'reopen','mobile-check-reversal')
        time=next(p for p in plans if p['completion_mode']=='time')
        for minutes in (5,15):
            started=op(time,'start','mobile-start-'+str(minutes));time=op(started['plan'],'finish','mobile-finish-'+str(minutes),execution_id=started['execution']['id'],actual_minutes=minutes)['plan']
        self.assertEqual(time['status'],'completed')
        snapshot=self.native('GET','action-plans');self.assertEqual(next(p for p in snapshot['plans'] if p['id']==time['id'])['progress']['minutes'],20)
        self.assertEqual(self.native('GET','action-plans',other=True)['plans'],[]);self.assertIsNone(self.native('GET','action-plans/learning-progress',other=True)['progress'])

    def test_explicit_reading_scope_real_http_versions_privacy_response_loss_and_revoke(self):
        import mobile_library
        class Materials:
            def lessons(self,module):return [dict(filename='Day001.md',lesson_no=1,topic='Day001 Reading',learning_state='unknown'),dict(filename='Day002.md',lesson_no=2,topic='Day002 Writing',learning_state='unknown')]
            def lesson(self,module,filename):return {'content':'# '+filename+'\n\nPublished body.','record':{'summary_text':'PRIVATE ANSWER MUST NEVER BE MIRRORED'}}
        material=Materials();mobile_library.register(self.app,self.s,material)
        draft=self.s.draft({'brief':B,'document':copy.deepcopy(D)});pid=self.s.adopt(draft['id'],'reading-formal-plan')['plan_id']
        self.s.save_sources(pid,S);ctx=self.s.course_context(pid);draft=self.s.course_draft(ctx,content(ctx),'Published references')
        self.s.publish_course(draft['id'],'reading-formal-publish')
        actions.create(actions.NewPlan(title='连接阅读',period='day',completion_mode='check',key='reading-fixture-plan'))
        ticket=self.native('POST','action-link-tickets',{});preview=self.web('action-link/preview',{'code':ticket['code']})
        self.web('action-link/confirm',{'code':ticket['code'],'preview_id':preview['preview_id'],'consent':True})
        self.assertFalse(self.native('GET','learning-library')['consent_enabled'])
        bad=self.client.post('/api/mobile-learning/consent',json={'enabled':True,'consent':True});self.assertEqual(bad.status_code,403)
        self.web('mobile-learning/consent',{'enabled':True,'consent':True})
        original=mobile_library.call;once=True
        def lost(*args):
            nonlocal once
            receipt=original(*args)
            if once:once=False;raise RuntimeError('synthetic lost reading receipt')
            return receipt
        with patch('mobile_library.call',side_effect=lost):
            with self.assertRaises(RuntimeError):mobile_library.sync(self.s,material)
            first=self.native('GET','learning-library');mobile_library.sync(self.s,material)
        index=self.native('GET','learning-library');self.assertEqual(index,first);self.assertEqual(len(index['lessons']),3)
        english=next(x for x in index['lessons'] if x['collection_id']=='yingyu' and x['number']==1)
        formal=next(x for x in index['lessons'] if x['collection_id']==pid)
        self.assertIn('Published references',self.native('GET','learning-library/'+formal['id'])['lesson']['references'])
        lesson=self.native('GET','learning-library/'+english['id'])['lesson']
        self.assertIn('Published body',lesson['content']);self.assertNotIn('PRIVATE',json.dumps(lesson));self.assertEqual(lesson['learning_state'],'unknown')
        self.assertEqual(self.native('GET','learning-library',other=True)['lessons'],[])
        target=self.client.get('/api/mobile-learning/source/'+lesson['id']);self.assertEqual(target.json()['filename'],'Day001.md')
        self.web('mobile-learning/consent',{'enabled':False,'consent':True});mobile_library.sync(self.s,material)
        self.assertFalse(self.native('GET','learning-library')['consent_enabled'])
        r=httpx.get(self.url+'/api/v1/lighttick/learning-library/'+lesson['id'],headers={'Authorization':'Bearer '+self.owners[0]['token'],'X-App-Id':'lighttick'});self.assertEqual(r.status_code,404)

    def test_reading_only_pairing_does_not_migrate_or_freeze_actions_even_with_rhythm(self):
        import mobile_library
        class Materials:
            def lessons(self,module):return [dict(filename='Day001.md',lesson_no=1,topic='English',learning_state='unknown')]
            def lesson(self,module,filename):return {'content':'# English\n\nPublished learning body.'}
        material=Materials();mobile_library.register(self.app,self.s,material)
        ticket=self.native('POST','action-link-tickets',{})
        with patch('rhythm.store.has_data',return_value=True):
            proposal=self.web('mobile-learning/preview',{'code':ticket['code']})
            result=self.web('mobile-learning/connect',{'code':ticket['code'],'preview_id':proposal['preview_id'],'consent':True})
        self.assertTrue(result['enabled']);mobile_library.sync(self.s,material)
        self.assertEqual(len(self.native('GET','learning-library')['lessons']),1)
        self.assertEqual(self.native('GET','action-plans')['plans'],[])
        with actions.connection() as c:link,_=__import__('action_link').state(c)
        self.assertEqual(link.get('phase','local'),'local')
        local=actions.create(actions.NewPlan(title='网页继续本地行动',period='day',completion_mode='check',key='reading-keeps-actions-local'))
        self.assertTrue(local['plans'][0]['id']);self.assertEqual(self.native('GET','action-plans')['plans'],[])
