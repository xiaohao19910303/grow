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
        self.headers={'X-Copilot-Request':'1'}

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
            self.assertTrue(saved.json()['read'])
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

    def test_course_completion_updates_linked_arrangement_and_preserves_record_contract(self):
        from study_materials import initialize,register
        initialize();register(self.app,self.root)
        directory=self.root/'结构化表达/每日练习';directory.mkdir(parents=True)
        (directory/'Day 001.md').write_text('# 结论先行\n\n用两个事实支持结论。')
        with TestClient(self.app,base_url='http://localhost') as client:
            arranged=client.post('/api/action-plans/schedules',headers=self.headers,json={
                'title':'结论先行','date':'2026-10-20','target':{'kind':'biaoda','course':'Day 001.md'},'key':'course-arrangement'})
            self.assertEqual(arranged.status_code,200,arranged.text)
            path='/api/study-materials/biaoda/Day%20001.md'
            lesson=client.get(path).json()['lesson']
            saved=client.post(path+'/learning-record',headers=self.headers,json={
                'summary_text':'先给建议，再说依据','time_spent_seconds':90,'revision':0,
                'version':lesson['version'],'key':'complete-arranged-course'})
            self.assertEqual(saved.status_code,200,saved.text)
            self.assertEqual(client.get(path+'/learning-record').json(),saved.json())
            self.assertEqual(client.get('/api/action-plans').json()['plans'][0]['status'],'completed')
            self.assertEqual(client.get('/api/action-plans/records').json()['records'][0]['actual_minutes'],0)
