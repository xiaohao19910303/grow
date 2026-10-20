"""Durable delivery state survives lost responses without changing source success."""
import json
from unittest.mock import patch
from test_action_p0_sources import CourseReceiptFixture
from tenancy import current_user
import action_plans as actions

class SourceDeliveryTests(CourseReceiptFixture):
    def setUp(self):
        super().setUp()
        self.token=current_user.set({'id':'grow-fixture','is_owner':1,'schema_name':self.schema})
        self.addCleanup(current_user.reset,self.token)
        from action_link import put
        with actions.connection(True,allow_link=True) as c:
            put(c,dict(phase='active',binding_id='binding-fixture',target_user_id='zook-fixture'))

    def test_offline_confirmation_has_atomic_outbox_and_recovers_after_restart(self):
        from action_source_delivery import retry_due
        with patch('action_link.call',side_effect=RuntimeError('network offline')):
            saved=self.confirm(origin_action_id=None)
        self.assertEqual(saved.status_code,200,saved.text)
        event=saved.json()['source_event_id']
        with actions.connection() as c:attempts=c.execute('SELECT attempts FROM action_source_outbox').fetchone()[0]
        with patch('action_link.call',side_effect=AssertionError('backoff must prevent an immediate send')):
            self.assertEqual(retry_due(),[])
        with actions.connection() as c:self.assertEqual(c.execute('SELECT attempts FROM action_source_outbox').fetchone()[0],attempts)
        self.assertEqual(self.s.lessons(self.pid)[0]['learning_state'],'completed')
        with actions.connection() as c:
            row=c.execute('SELECT * FROM action_source_outbox').fetchone()
            payload=json.loads(row['payload']);self.assertEqual(payload['event']['event_id'],event)
            self.assertNotIn('comment',row['payload']);self.assertNotIn('source_result',row['payload'])
        from action_link import fingerprint
        receipt=dict(accepted=True,binding_id='binding-fixture',target_user_id='zook-fixture',event_id=event,
                     payload_hash=fingerprint(payload['event']),status='completed',completed_arrangements=[self.plan['id']],record_id='execution-fixture',reason=None)
        calls=[]
        def deliver(source,body):calls.append(body);return receipt
        with patch('action_link.call',side_effect=deliver):
            retry_due(force=True)
            retry_due(force=True)
        self.assertEqual(len(calls),1)
        with actions.connection() as c:self.assertEqual(c.execute('SELECT state FROM action_source_outbox').fetchone()[0],'completed')
        # The frozen local action workspace is never used as fallback.
        with actions.connection() as c:self.assertEqual(c.execute('SELECT count(*) FROM action_executions').fetchone()[0],0)

    def test_source_and_event_and_outbox_roll_back_in_same_database_commit(self):
        import action_content
        real=action_content.event_sql
        with patch('action_content.event_sql',side_effect=lambda e:real(e)+[('SELECT 1/0',[])]):
            import psycopg2
            with self.assertRaises(psycopg2.errors.DivisionByZero):self.confirm(key='source-outbox-atomic-rollback',origin_action_id=None)
        with actions.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM action_content_events').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM action_source_outbox').fetchone()[0],0)
        self.assertEqual(self.s.lessons(self.pid)[0]['learning_state'],'unknown')

    def test_unproved_origin_keeps_source_success_and_blocks_unsafe_completion(self):
        with patch('action_link.call',side_effect=RuntimeError('network offline')):
            saved=self.confirm()
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual(self.s.lessons(self.pid)[0]['learning_state'],'completed')
        with actions.connection() as c:
            row=c.execute('SELECT state,data FROM action_source_outbox').fetchone()
            self.assertEqual(row[0],'blocked');self.assertIn('ORIGIN_CONTEXT_REQUIRED',row[1])

    def test_delivery_inspection_is_tenant_scoped_and_manual_retry_cannot_bypass_missing_proof(self):
        with patch('action_link.call',side_effect=RuntimeError('offline')):self.confirm(key='source-proof-blocked')
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import action_link
        app=FastAPI();action_link.register(app)
        with TestClient(app,base_url='http://localhost') as client:
            self.assertEqual(client.get('/api/action-link/source-deliveries').json()['deliveries'][0]['state'],'blocked')
            self.assertEqual(client.post('/api/action-link/source-deliveries/retry').status_code,403)
            with patch('action_link.call',side_effect=AssertionError('missing proof must not be retried')):
                retried=client.post('/api/action-link/source-deliveries/retry',headers={'X-Copilot-Request':'1'})
            self.assertEqual(retried.status_code,200,retried.text)
            self.assertEqual(retried.json()['deliveries'][0]['reason'],'ORIGIN_CONTEXT_REQUIRED')
        token=current_user.set(None)
        try:
            with TestClient(app,base_url='http://localhost') as client:self.assertEqual(client.get('/api/action-link/source-deliveries').status_code,401)
        finally:current_user.reset(token)

    def test_invalid_receipt_never_marks_delivered_and_source_failure_has_no_outbox(self):
        from action_source_delivery import retry_due
        with patch('action_link.call',return_value={'accepted':True,'status':'completed'}):
            saved=self.confirm(origin_action_id=None)
            retry_due(force=True)
        with actions.connection() as c:
            self.assertEqual(c.execute('SELECT state FROM action_source_outbox').fetchone()[0],'pending')
        with patch.object(self.s,'publish',side_effect=RuntimeError('source rollback')):
            with self.assertRaises(RuntimeError):self.confirm(key='delivery-source-fails',origin_action_id=None)
        with actions.connection() as c:self.assertEqual(c.execute('SELECT count(*) FROM action_source_outbox').fetchone()[0],1)

from test_legacy_cloud_api import CloudHTTPFixture
from fastapi.testclient import TestClient
class FirstSourceReceiptTests(CloudHTTPFixture):
    def test_first_source_confirmation_initializes_schema_without_nested_ddl_lock(self):
        import db
        real=db.connect
        def bounded(*args,**kwargs):
            c=real(*args,**kwargs);c.execute('SET statement_timeout=1000');return c
        with patch('db.connect',bounded),TestClient(self.app,base_url='http://localhost') as client:
            result=client.post('/api/reading/articles/'+self.aid+'/personal',headers={'X-Copilot-Request':'1'},json={'data':{'read':True,'key':'first-source-receipt'}})
        self.assertEqual(result.status_code,200,result.text)
        self.assertIn('source_event_id',result.json())
