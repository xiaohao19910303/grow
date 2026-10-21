"""Course source transactions and durable completion recovery acceptance."""
from datetime import datetime, timezone
import json
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from cloud_fixtures import CloudFixture
import test_plans
import action_plans as actions


class CourseReceiptFixture(CloudFixture):
    def setUp(self):
        super().setUp()
        self.pid=test_plans.StoreTests.adopt(self); test_plans.StoreTests.course(self,self.pid)
        clock=patch('action_plans.clock',return_value=datetime(2026,10,19,12,tzinfo=timezone.utc))
        clock.start();self.addCleanup(clock.stop)
        self.app=FastAPI()
        from plans.api import register
        with patch('plans.api.make_store',return_value=self.s):register(self.app,self.root,self.runtime)
        actions.register(self.app)
        self.client=TestClient(self.app,base_url='http://localhost');self.addCleanup(self.client.close)
        self.headers={'X-Copilot-Request':'1','X-Grow-Action-Schema':'2'}
        self.target={'kind':'plan','plan_id':self.pid,'lesson_no':1}
        response=self.client.post('/api/action-plans/schedules',headers=self.headers,
            json={'title':'课程验收','target':self.target,'date':'2026-10-19','key':'course-p0-arrange'})
        self.assertEqual(response.status_code,200,response.text)
        self.plan=response.json()['plan']

    def confirm(self,key='course-p0-confirm',**updates):
        return self.client.post('/api/plans/'+self.pid+'/lessons/1/feedback',headers=self.headers,
            json={'data':{'state':'completed','comment':'只存私人反馈','key':key,'origin_action_id':self.plan['id'],**updates}})


class CourseReceiptTests(CourseReceiptFixture):
    def test_C01_C06_course_receipt_survives_sync_failure_and_replays_once(self):
        with patch('action_plans.content_completed',side_effect=RuntimeError('synthetic outage')):
            saved=self.confirm()
        self.assertEqual(saved.status_code,200,saved.text)
        event=saved.json()['source_event_id']
        self.assertIn('arrangement_sync_error',saved.json())
        self.assertEqual(self.s.lessons(self.pid)[0]['learning_state'],'completed')
        replay=self.confirm()
        self.assertEqual(replay.json()['source_event_id'],event)
        plan=self.client.get('/api/action-plans').json()['plans'][0]
        self.assertEqual(plan['status'],'completed')
        self.assertEqual((plan['progress']['completed'],plan['progress']['minutes']),(1,0))
        self.assertEqual(self.client.get('/api/action-plans/records').json()['total'],1)
        self.assertNotIn(event,json.dumps(self.repo.commits))
        self.assertEqual(self.confirm(comment='different payload').status_code,409)

    def test_C10_source_transaction_failure_never_creates_receipt(self):
        with patch.object(self.s,'publish',side_effect=RuntimeError('synthetic source failure')):
            with self.assertRaises(RuntimeError):self.confirm()
        with actions.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM action_content_events').fetchone()[0],0)
        self.assertEqual(self.client.get('/api/action-plans').json()['plans'][0]['status'],'active')

    def test_C10_receipt_and_source_sql_roll_back_together(self):
        import action_content
        real=action_content.event_sql
        def failing(event):return real(event)+[('SELECT 1/0',[])]
        with patch('action_content.event_sql',side_effect=failing):
            import psycopg2
            with self.assertRaises(psycopg2.errors.DivisionByZero):self.confirm()
        with actions.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM action_content_events').fetchone()[0],0)
        self.assertEqual(self.s.lessons(self.pid)[0]['learning_state'],'unknown')
