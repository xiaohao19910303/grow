"""Actual source saves complete linked arrangements; progress stays private."""
from datetime import datetime, timezone
from unittest.mock import patch
import json

from fastapi.testclient import TestClient
from test_legacy_cloud_api import CloudHTTPFixture
import action_plans


class ArrangementSourceTests(CloudHTTPFixture):
    def setUp(self):
        super().setUp()
        action_plans.register(self.app)
        clock=patch('action_plans.clock', return_value=datetime(2026,10,20,12,tzinfo=timezone.utc))
        clock.start();self.addCleanup(clock.stop)
        self.headers={'X-Copilot-Request':'1','X-Grow-Action-Schema':'2'}

    def test_article_confirmation_completes_arrangement_but_feedback_alone_does_not(self):
        with TestClient(self.app,base_url='http://localhost') as client:
            result=client.post('/api/action-plans/schedules',headers=self.headers,json={
                'title':'明日选文','date':'2026-10-20','target':{'kind':'article','course':self.aid},'key':'article-arrangement'})
            self.assertEqual(result.status_code,200,result.text)
            pid=result.json()['plan']['id']
            path='/api/reading/articles/'+self.aid
            saved=client.post(path+'/feedback',headers=self.headers,json={'data':{'version':0,'takeaway':'先记下收获'}})
            self.assertEqual(saved.status_code,200,saved.text)
            self.assertEqual(client.get('/api/action-plans').json()['plans'][0]['status'],'active')
            saved=client.post(path+'/personal',headers=self.headers,json={'data':{'read':True}})
            self.assertEqual(saved.status_code,200,saved.text)
            self.assertEqual(saved.json()['completed_arrangements'],[pid])
            self.assertEqual(client.get('/api/action-plans').json()['plans'][0]['status'],'completed')
            self.assertEqual(client.get('/api/action-plans/records').json()['records'][0]['actual_minutes'],0)

    def test_position_roundtrip_conflict_and_no_github_publication(self):
        original=self.repository.head
        with TestClient(self.app,base_url='http://localhost') as client:
            path='/api/reading/articles/'+self.aid+'/position'
            self.assertEqual(client.get(path).json(),{'ratio':0,'revision':0})
            saved=client.post(path,headers=self.headers,json={'data':{'ratio':.42,'revision':0}})
            self.assertEqual(saved.status_code,200,saved.text)
            self.assertEqual(client.get(path).json()['ratio'],.42)
            self.assertEqual(client.post(path,headers=self.headers,json={'data':{'ratio':.2,'revision':0}}).status_code,409)
            self.assertEqual(client.get(path).json()['ratio'],.42)
            self.assertEqual(client.post(path,headers=self.headers,json={'data':{'ratio':2,'revision':1}}).status_code,422)
            self.assertEqual(client.get('/api/reading/articles/'+self.aid).json()['article']['read'],False)
        self.assertEqual(self.repository.head,original)

    def test_receipt_replay_and_running_time_are_independent(self):
        with TestClient(self.app,base_url='http://localhost') as client:
            plan=client.post('/api/action-plans/schedules',headers=self.headers,json={
                'title':'内容与投入','date':'2026-10-20','target':{'kind':'article','course':self.aid},'key':'receipt-arrange'}).json()['plan']
            def change(p,action,**more):
                return client.post('/api/action-plans/'+p['id']+'/operations',headers=self.headers,
                    json={'key':'receipt-'+action,'revision':p['revision'],'action':action,**more})
            started=change(plan,'start').json()
            path='/api/reading/articles/'+self.aid+'/personal'
            body={'data':{'read':True,'key':'explicit-source-confirm','origin_action_id':plan['id']}}
            confirmed=client.post(path,headers=self.headers,json=body)
            self.assertEqual(confirmed.status_code,200,confirmed.text)
            event=confirmed.json()['source_event_id']
            self.assertIsNotNone(client.get('/api/action-plans').json()['execution'])
            saved=change(started['plan'],'finish',execution_id=started['execution']['id'],actual_minutes=8).json()
            self.assertEqual(saved['execution']['outcome'],'recorded')
            done=change(saved['plan'],'reconcile-content',source_event_id=event)
            self.assertEqual(done.status_code,200,done.text)
            replay=client.post(path,headers=self.headers,json=body)
            self.assertEqual(replay.json()['source_event_id'],event)
            result=client.get('/api/action-plans').json()['plans'][0]
            self.assertEqual((result['progress']['minutes'],result['progress']['completed']),(8,1))

    def test_old_read_flag_cannot_complete_new_arrangement(self):
        with TestClient(self.app,base_url='http://localhost') as client:
            self.reader.update_personal(self.aid,{'read':True})
            plan=client.post('/api/action-plans/schedules',headers=self.headers,json={
                'title':'重新阅读','date':'2026-10-20','target':{'kind':'article','course':self.aid},'key':'reread-arrange'}).json()['plan']
            result=client.post('/api/action-plans/'+plan['id']+'/operations',headers=self.headers,
                json={'key':'reread-reconcile','revision':plan['revision'],'action':'reconcile-content'})
            self.assertEqual(result.status_code,409,result.text)
            self.assertEqual(result.json()['code'],'COMPLETION_EVIDENCE_MISSING')

    def test_C04_C05_C06_scoped_dates_and_delayed_confirmation(self):
        with TestClient(self.app,base_url='http://localhost') as client:
            target={'kind':'article','course':self.aid}
            def arrange(date,key):
                result=client.post('/api/action-plans/schedules',headers=self.headers,json={'title':'日期隔离','target':target,'date':date,'key':key})
                self.assertEqual(result.status_code,200,result.text);return result.json()['plan']
            today=arrange('2026-10-20','scope-today');future=arrange('2026-10-21','scope-future')
            past=arrange('2026-10-19','scope-past');undated=arrange(None,'scope-undated')
            with patch('action_plans.content_completed',side_effect=RuntimeError('sync unavailable')):
                saved=client.post('/api/reading/articles/'+self.aid+'/personal',headers=self.headers,
                    json={'data':{'read':True,'key':'scope-confirm'}})
            event=saved.json()['source_event_id']
            with patch('action_plans.clock',return_value=datetime(2026,10,21,12,tzinfo=timezone.utc)):
                result=client.post('/api/action-plans/'+today['id']+'/operations',headers=self.headers,
                    json={'action':'reconcile-content','revision':today['revision'],'key':'scope-delayed','source_event_id':event})
                self.assertEqual(result.status_code,200,result.text)
                self.assertEqual(result.json()['execution']['business_date'],'2026-10-20')
            plans={p['id']:p for p in client.get('/api/action-plans').json()['plans']}
            self.assertTrue(all(plans[p['id']]['status']=='active' for p in (future,past,undated)))
            confirmed=client.post('/api/reading/articles/'+self.aid+'/personal',headers=self.headers,
                json={'data':{'read':True,'key':'scope-past-confirm','origin_action_id':past['id']}})
            self.assertEqual(confirmed.json()['completed_arrangements'],[past['id']])
            self.assertEqual(client.get('/api/action-plans/records').json()['total'],2)
