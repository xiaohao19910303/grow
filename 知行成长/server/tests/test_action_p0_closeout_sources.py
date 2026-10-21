"""The same C01-C10 contract runs against both real supported source APIs."""
from datetime import datetime, timezone
import json
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
import action_plans as actions
from test_legacy_cloud_api import CloudHTTPFixture
from test_action_p0_sources import CourseReceiptFixture


class SourceContract:
    def arrange(self,date='2026-10-19',**updates):
        response=self.client.post('/api/action-plans/schedules',headers=self.headers,
            json=dict(title='双来源验收',target=self.target,date=date,key=str(uuid.uuid4()))|updates)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()['plan']

    def op(self,p,action,**updates):
        return self.client.post('/api/action-plans/'+p['id']+'/operations',headers=self.headers,
            json=dict(action=action,revision=p['revision'],key=str(uuid.uuid4()))|updates)

    def current(self,p):
        return next(x for x in self.client.get('/api/action-plans').json()['plans'] if x['id']==p['id'])

    def count(self):
        return self.client.get('/api/action-plans/records').json()['total']

    def test_C01_C02_content_after_recorded_time_counts_once(self):
        started=self.op(self.plan,'start').json()
        saved=self.op(started['plan'],'finish',execution_id=started['execution']['id'],actual_minutes=20).json()
        self.assertEqual(saved['execution']['outcome'],'recorded')
        self.assertEqual(self.current(self.plan)['progress']['completed'],0)
        response=self.confirm(key=str(uuid.uuid4()))
        self.assertEqual(response.status_code,200,response.text)
        p=self.current(self.plan)
        self.assertEqual((p['status'],p['progress']['completed'],p['progress']['minutes']),('completed',1,20))
        self.assertEqual(self.count(),2)
        self.assertEqual(self.op(p,'reopen').status_code,422)

    def test_C03_C09_unread_and_notes_do_not_revoke_history_or_confirm_new_action(self):
        self.assertEqual(self.confirm(key=str(uuid.uuid4())).status_code,200)
        old=self.current(self.plan);self.assertEqual(old['status'],'completed')
        self.assertEqual(self.unconfirm().status_code,200)
        self.assertEqual(self.current(self.plan)['completion_record_id'],old['completion_record_id'])
        fresh=self.arrange('2026-10-18');self.plan=fresh
        self.save_notes()
        response=self.op(fresh,'reconcile-content')
        self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(response.json()['code'],'COMPLETION_EVIDENCE_MISSING')
        self.assertEqual(self.count(),1)
        self.assertEqual(self.confirm(key=str(uuid.uuid4())).json()['completed_arrangements'],[fresh['id']])
        self.assertEqual(self.count(),2)

    def test_C04_C05_C06_dates_origin_and_delayed_reconcile(self):
        future=self.arrange('2026-10-20');past=self.arrange('2026-10-18');undated=self.arrange(None)
        with patch('action_plans.content_completed',side_effect=RuntimeError('synthetic sync failure')):
            response=self.confirm(key=str(uuid.uuid4()),origin_action_id=None)
        self.assertEqual(response.status_code,200,response.text)
        event=response.json()['source_event_id']
        self.assertEqual(self.current(self.plan)['status'],'active')
        with patch('action_plans.clock',return_value=datetime(2026,10,20,12,tzinfo=timezone.utc)):
            done=self.op(self.plan,'reconcile-content',source_event_id=event)
        self.assertEqual(done.status_code,200,done.text)
        self.assertEqual(done.json()['execution']['business_date'],'2026-10-19')
        self.assertEqual(self.op(done.json()['plan'],'reconcile-content',source_event_id=event).status_code,409)
        for p in (future,past,undated):self.assertEqual(self.current(p)['status'],'active')
        self.plan=past
        self.assertEqual(self.confirm(key=str(uuid.uuid4())).json()['completed_arrangements'],[past['id']])
        fact=self.client.get('/api/action-plans/records?plan_id='+past['id']).json()['records'][0]
        self.assertEqual((fact['planned_date'],fact['business_date']),('2026-10-18','2026-10-19'))

    def test_C06_rearranged_pending_evidence_cannot_bypass_future_or_undated(self):
        with patch('action_plans.content_completed',side_effect=RuntimeError('synthetic sync failure')):
            response=self.confirm(key=str(uuid.uuid4()))
        event=response.json()['source_event_id'];p=self.plan
        for date in ('2026-10-20',None):
            p=self.op(p,'reschedule',date=date).json()['plan']
            rejected=self.op(p,'reconcile-content',source_event_id=event)
            self.assertEqual(rejected.status_code,422,rejected.text)
            self.assertEqual(self.count(),0)
        p=self.op(p,'reschedule',date='2026-10-19').json()['plan']
        self.assertEqual(self.op(p,'reconcile-content',source_event_id=event).status_code,200)
        self.assertEqual(self.count(),1)

    def test_C07_running_is_not_ended_by_source_confirmation(self):
        started=self.op(self.plan,'start').json()
        event=self.confirm(key=str(uuid.uuid4())).json()['source_event_id']
        self.assertEqual(self.client.get('/api/action-plans').json()['execution']['id'],started['execution']['id'])
        self.assertEqual(self.current(self.plan)['status'],'active')
        finished=self.op(started['plan'],'finish',execution_id=started['execution']['id'],actual_minutes=8).json()
        done=self.op(finished['plan'],'reconcile-content',source_event_id=event)
        self.assertEqual(done.status_code,200,done.text)
        self.assertEqual((self.current(self.plan)['progress']['completed'],self.current(self.plan)['progress']['minutes']),(1,8))

    def test_C08_replay_and_foreign_wrong_old_evidence(self):
        response=self.confirm(key=str(uuid.uuid4()),origin_action_id='foreign-action')
        self.assertEqual(response.status_code,404,response.text);self.assertFalse(self.source_done())
        for changes,status in (({'event_id':'foreign-event'},404),({'normalized_target':{'kind':'article','course':'another'}},409),
                               ({'confirmed_at':'2026-10-18T12:00:00+00:00'},409),({'origin_action_id':'another-action'},409)):
            if changes.get('event_id')=='foreign-event':
                event_id='foreign-event'
            else:
                event_id='source-'+uuid.uuid4().hex
                event=dict(event_id=event_id,request_key=str(uuid.uuid4()),owner=self.schema,
                    normalized_target=self.target,confirmed_at=actions.clock().isoformat())|changes
                with actions.connection() as c:c.execute('INSERT INTO action_content_events VALUES (?,?,?)',(event_id,event['request_key'],json.dumps(event)))
            response=self.op(self.plan,'reconcile-content',source_event_id=event_id)
            self.assertEqual(response.status_code,status,response.text);self.assertEqual(self.count(),0)
        key=str(uuid.uuid4());first=self.confirm(key=key);second=self.confirm(key=key)
        self.assertEqual(first.json()['source_event_id'],second.json()['source_event_id']);self.assertEqual(self.count(),1)
        self.assertEqual(self.confirm(key=key,origin_action_id=None).status_code,409)

    def test_S02_normalized_identity_timezone_and_null_buckets(self):
        normalized=self.arrange(title='同源异名',target=self.target|{'course':self.target.get('course',''),'lesson_no':self.target.get('lesson_no',1)})
        self.assertEqual(normalized['id'],self.plan['id'])
        utc=self.arrange(timezone='UTC');self.assertNotEqual(utc['id'],self.plan['id'])
        undated=self.arrange(None);self.assertNotEqual(undated['id'],self.plan['id'])
        self.assertEqual(self.arrange(None,title='未安排异名')['id'],undated['id'])

    def test_C10_source_and_receipt_rollback_together(self):
        import action_content
        import psycopg2
        original=action_content.event_sql
        with patch('action_content.event_sql',side_effect=lambda event:original(event)+[('SELECT 1/0',[])]):
            with self.assertRaises(psycopg2.errors.DivisionByZero):self.confirm(key=str(uuid.uuid4()))
        with actions.connection() as c:self.assertEqual(c.execute('SELECT count(*) FROM action_content_events').fetchone()[0],0)
        self.assertEqual(self.current(self.plan)['status'],'active');self.assertEqual(self.count(),0)
        self.assertFalse(self.source_done())

    def test_T07_S01_S03_S05_source_lifecycle(self):
        repeat=self.arrange(title='同来源不同标题');self.assertEqual(repeat['id'],self.plan['id'])
        tomorrow=self.arrange('2026-10-20')
        before=self.current(tomorrow)
        conflict=self.op(tomorrow,'reschedule',date='2026-10-19')
        self.assertEqual(conflict.status_code,409);self.assertEqual(self.current(tomorrow),before)
        started=self.op(self.plan,'start').json()
        saved=self.op(started['plan'],'finish',execution_id=started['execution']['id'],actual_minutes=3).json()['plan']
        cancelled=self.op(saved,'cancel').json()['plan'];self.assertEqual(cancelled['status'],'archived')
        replacement=self.arrange();self.assertNotEqual(replacement['id'],self.plan['id'])
        self.assertEqual(self.count(),1);self.assertFalse(self.source_done())
        self.assertEqual(self.op(cancelled,'resume').status_code,409)

    def test_T07_parent_blocks_source_consumption_until_resumed(self):
        response=self.client.post('/api/action-plans',headers=self.headers,json=dict(title='上级',period='week',
            start_date='2026-10-19',end_date='2026-10-25',key=str(uuid.uuid4())))
        parent=response.json()['plans'][0]
        fields={k:self.plan[k] for k in actions.PlanFields.model_fields};fields['parent_id']=parent['id']
        self.plan=self.op(self.plan,'edit',fields=fields).json()['plan']
        parent=self.op(parent,'pause').json()['plan']
        event=self.confirm(key=str(uuid.uuid4())).json()['source_event_id']
        self.assertEqual(self.current(self.plan)['status'],'active');self.assertEqual(self.count(),0)
        self.assertEqual(self.op(self.plan,'reconcile-content',source_event_id=event).status_code,409)
        self.op(parent,'resume')
        self.assertEqual(self.op(self.plan,'reconcile-content',source_event_id=event).status_code,200)

    def test_A02_cross_midnight_content_fact_is_separate_from_session(self):
        with patch('action_plans.clock',return_value=datetime(2026,10,19,15,58,tzinfo=timezone.utc)):
            started=self.op(self.plan,'start').json()
        with patch('action_plans.clock',return_value=datetime(2026,10,19,16,10,tzinfo=timezone.utc)):
            saved=self.op(started['plan'],'finish',execution_id=started['execution']['id'],actual_minutes=12).json()
            self.plan=saved['plan'];self.assertEqual(self.confirm(key=str(uuid.uuid4())).status_code,200)
        records=self.client.get('/api/action-plans/records?plan_id='+self.plan['id']).json()['records']
        by_kind={r['record_kind']:r for r in records}
        self.assertEqual((by_kind['session']['business_date'],by_kind['session']['actual_minutes']),('2026-10-19',12))
        self.assertEqual((by_kind['completion']['business_date'],by_kind['completion']['actual_minutes']),('2026-10-20',0))
        self.assertEqual(self.current(self.plan)['progress']['completed'],1)

    def test_R05_real_second_schema_cannot_read_action_source_event_or_receipt(self):
        import db
        import psycopg2
        with patch('action_plans.content_completed',side_effect=RuntimeError('synthetic sync failure')):
            event=self.confirm(key='tenant-a-private-source').json()['source_event_id']
        other='p0_other_'+uuid.uuid4().hex
        with psycopg2.connect(self.dsn) as c:c.cursor().execute('CREATE SCHEMA '+other)
        try:
            def connect(*args,**kwargs):return db.CompatConnection(psycopg2.connect(self.dsn+' options=-csearch_path='+other))
            with patch('db.connect',connect):
                self.assertEqual(self.client.get('/api/action-plans').json()['plans'],[])
                self.assertEqual(self.op(self.plan,'reconcile-content',source_event_id=event).status_code,404)
                self.assertFalse(self.client.get('/api/action-plans/requests/tenant-a-private-source').json()['found'])
                response=self.client.post('/api/action-plans/schedules',headers=self.headers,
                    json=dict(title='不泄露其他账号来源',target=self.target,date='2026-10-19',key=str(uuid.uuid4())))
                self.assertEqual(response.status_code,404,response.text)
            self.assertEqual(self.count(),0);self.assertEqual(self.current(self.plan)['status'],'active')
        finally:
            with psycopg2.connect(self.dsn) as c:c.cursor().execute('DROP SCHEMA '+other+' CASCADE')


class ArticleSourceCloseout(SourceContract,CloudHTTPFixture):
    def setUp(self):
        super().setUp();actions.register(self.app)
        timer=patch('action_plans.clock',return_value=datetime(2026,10,19,12,tzinfo=timezone.utc));timer.start();self.addCleanup(timer.stop)
        self.client=TestClient(self.app,base_url='http://localhost');self.addCleanup(self.client.close)
        self.headers={'X-Copilot-Request':'1','X-Grow-Action-Schema':'2'}
        self.target={'kind':'article','course':self.aid};self.plan=self.arrange()

    def confirm(self,key,**updates):
        return self.client.post('/api/reading/articles/'+self.aid+'/personal',headers=self.headers,
            json={'data':{'read':True,'key':key,'origin_action_id':self.plan['id'],**updates}})

    def unconfirm(self):
        return self.client.post('/api/reading/articles/'+self.aid+'/personal',headers=self.headers,json={'data':{'read':False}})

    def save_notes(self):
        response=self.client.post('/api/reading/articles/'+self.aid+'/feedback',headers=self.headers,
            json={'data':{'version':0,'takeaway':'私人笔记不完成'}})
        self.assertEqual(response.status_code,200,response.text)

    def source_done(self):return self.reader.article(self.aid)['read']


class CourseSourceCloseout(SourceContract,CourseReceiptFixture):
    def unconfirm(self):
        return self.client.post('/api/plans/'+self.pid+'/lessons/1/feedback',headers=self.headers,
            json={'data':{'state':'unknown','comment':'私人笔记','key':str(uuid.uuid4())}})

    def save_notes(self):self.assertEqual(self.unconfirm().status_code,200)

    def source_done(self):return self.s.lessons(self.pid)[0]['learning_state']=='completed'
