"""Local P0 acceptance gaps: atomic rejection, lifecycle, date and tenant edges."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import uuid
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import action_plans as actions
import db
from test_legacy_cloud_schema import PostgreSQLFixture


class LocalCloseoutTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        timer=patch('action_plans.clock',return_value=datetime(2026,10,19,12,tzinfo=timezone.utc))
        timer.start();self.addCleanup(timer.stop)
        self.app=FastAPI();actions.register(self.app)
        self.client=TestClient(self.app,base_url='http://localhost');self.addCleanup(self.client.close)
        self.h={'X-Copilot-Request':'1','X-Grow-Action-Schema':'2'}

    def create(self,**updates):
        response=self.client.post('/api/action-plans',headers=self.h,json=dict(title='收尾验收',period='day',
            completion_mode='check',start_date='2026-10-19',end_date='2026-10-19',key=str(uuid.uuid4()))|updates)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()['plans'][0]

    def op(self,p,action,**updates):
        return self.client.post('/api/action-plans/'+p['id']+'/operations',headers=self.h,
            json=dict(action=action,revision=p['revision'],key=str(uuid.uuid4()))|updates)

    def snapshot(self):
        with actions.connection() as c:
            return {t:[dict(r) for r in c.execute('SELECT * FROM '+t+' ORDER BY 1')]
                    for t in ('action_plans','action_executions','action_operations','action_content_events')}

    def reject(self,p,action,status,**values):
        before=self.snapshot();response=self.op(p,action,**values)
        self.assertEqual(response.status_code,status,response.text)
        self.assertEqual(self.snapshot(),before)
        return response

    def test_F03_F04_all_boundaries_and_F09_parent_timezone(self):
        for values in ({'title':''},{'title':' '*3},{'start_date':'2026-02-30'},
                       {'completion_mode':'time','minimum_minutes':0},
                       {'completion_mode':'time','target_minutes':True}):
            before=self.snapshot()
            response=self.client.post('/api/action-plans',headers=self.h,json=dict(title='合法',period='day',
                completion_mode='check',start_date='2026-10-19',end_date='2026-10-19',key=str(uuid.uuid4()))|values)
            self.assertEqual(response.status_code,422,response.text)
            self.assertEqual(response.json()['code'],'VALIDATION_ERROR');self.assertEqual(before,self.snapshot())
        parent=self.create(period='week',completion_mode='time',end_date='2026-10-25')
        for values in ({'timezone':'UTC'},{'start_date':'2026-10-26','end_date':'2026-10-26'},
                       {'start_date':None,'end_date':None}):
            response=self.client.post('/api/action-plans',headers=self.h,json=dict(title='子项',period='day',
                completion_mode='check',start_date='2026-10-19',end_date='2026-10-19',parent_id=parent['id'],key=str(uuid.uuid4()))|values)
            self.assertEqual(response.status_code,422,response.text)

    def test_T02_T04_wall_clock_is_not_confirmed_minutes(self):
        p=self.create(completion_mode='time',minimum_minutes=None)
        started=self.op(p,'start').json()
        with patch('action_plans.clock',return_value=datetime(2026,10,19,14,tzinfo=timezone.utc)):
            self.assertEqual(self.client.get('/api/action-plans').json()['execution']['id'],started['execution']['id'])
            self.reject(started['plan'],'finish',422,execution_id=started['execution']['id'],actual_minutes=0)
            result=self.op(started['plan'],'finish',execution_id=started['execution']['id'],actual_minutes=3).json()
        self.assertEqual(result['execution']['outcome'],'partial')
        p=result['plan'];started=self.op(p,'start').json()
        result=self.op(started['plan'],'finish',execution_id=started['execution']['id'],actual_minutes=0,outcome='interrupted').json()
        self.assertEqual(result['execution']['outcome'],'interrupted')
        listed=self.client.get('/api/action-plans').json()['plans'][0]
        self.assertEqual((listed['status'],listed['progress']['minutes'],listed['progress']['completed']),('active',3,0))

    def test_T05_restart_and_concurrent_start_keep_one_session(self):
        a=self.create(completion_mode='time');b=self.create(completion_mode='time')
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda p:self.op(p,'start'),[a,b]))
        self.assertEqual(sorted(r.status_code for r in results),[200,409])
        winner=next(r.json() for r in results if r.status_code==200)
        app=FastAPI();actions.register(app)
        with TestClient(app,base_url='http://localhost') as other:
            self.assertEqual(other.get('/api/action-plans').json()['execution']['id'],winner['execution']['id'])
        with actions.connection() as c:self.assertEqual(c.execute("SELECT count(*) FROM action_executions WHERE state='running'").fetchone()[0],1)

    def test_T06_T07_running_and_parent_operations_are_atomic(self):
        parent=self.create(period='week',completion_mode='time',end_date='2026-10-25')
        p=self.create(completion_mode='time',parent_id=parent['id'])
        started=self.op(p,'start').json();p=started['plan']
        for command in ('pause','cancel','archive','complete'):
            self.reject(parent,command,409)
        fields={k:p[k] for k in actions.PlanFields.model_fields}
        for command,values in [('edit',{'fields':fields}),('pause',{}),('cancel',{}),('reschedule',{'date':None})]:
            self.reject(p,command,409,**values)
        saved=self.op(p,'finish',execution_id=started['execution']['id'],actual_minutes=3).json()['plan']
        fields['target_minutes']=30
        self.reject(saved,'edit',409,fields=fields)
        fields['target_minutes']=20;fields['title']='可编辑标题'
        edited=self.op(saved,'edit',fields=fields)
        self.assertEqual(edited.status_code,200,edited.text)
        paused=self.op(parent,'pause').json()['plan']
        self.reject(edited.json()['plan'],'start',409)
        self.op(paused,'resume')
        self.assertEqual(self.op(edited.json()['plan'],'start').status_code,200)

    def test_T08_K03_mode_and_status_matrix(self):
        check=self.create();time=self.create(completion_mode='time')
        self.reject(check,'start',422);self.reject(check,'reopen',409)
        self.reject(time,'complete',422);self.reject(time,'complete-time',422);self.reject(time,'reopen',422)
        started=self.op(time,'start').json()
        done=self.op(started['plan'],'finish',execution_id=started['execution']['id'],actual_minutes=20).json()['plan']
        self.reject(done,'reopen',422);self.reject(done,'start',409)

    def test_K02_R03_R04_concurrent_completion_and_stale_editor(self):
        p=self.create();keys=[str(uuid.uuid4()),str(uuid.uuid4())]
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda key:self.op(p,'complete',key=key),keys))
        self.assertEqual(sorted(r.status_code for r in results),[200,409])
        i=next(i for i,r in enumerate(results) if r.status_code==200)
        self.assertEqual(self.op(p,'complete',key=keys[i]).json(),results[i].json())
        self.assertEqual(self.client.get('/api/action-plans/records').json()['total'],1)
        self.reject(p,'pause',409)
        self.assertTrue(self.client.get('/api/action-plans/requests/'+keys[i]).json()['found'])

    def test_S04_partial_undate_preserves_fact_snapshot(self):
        p=self.create(completion_mode='time',at='19:00',reminder=True)
        started=self.op(p,'start').json()
        p=self.op(started['plan'],'finish',execution_id=started['execution']['id'],actual_minutes=3).json()['plan']
        facts=self.client.get('/api/action-plans/records').json()
        p=self.op(p,'reschedule',date=None).json()['plan']
        self.assertIsNone(p['at']);self.assertIsNone(p['reminder_at']);self.assertFalse(p['reminder'])
        p=self.op(p,'reschedule',date='2026-10-20').json()['plan']
        self.assertFalse(p['reminder']);self.assertEqual(self.client.get('/api/action-plans/records').json(),facts)

    def test_S07_arrange_saved_even_when_start_conflicts(self):
        current=self.create(completion_mode='time');self.op(current,'start')
        undated=self.create(completion_mode='time',start_date=None,end_date=None)
        self.reject(undated,'start',422)
        arranged=self.op(undated,'reschedule',date='2026-10-19').json()['plan']
        self.assertEqual(self.reject(arranged,'start',409).json()['code'],'RUNNING_CONFLICT')
        saved=next(p for p in self.client.get('/api/action-plans').json()['plans'] if p['id']==undated['id'])
        self.assertEqual(saved['start_date'],'2026-10-19')

    def test_S08_calendar_no_alarm_and_blocked_claims(self):
        parent=self.create(period='week',completion_mode='time',end_date='2026-10-25')
        p=self.create(at='19:00',reminder=False,parent_id=parent['id'])
        calendar=self.client.get('/api/action-plans/'+p['id']+'/calendar.ics')
        self.assertEqual(calendar.status_code,200);self.assertNotIn('VALARM',calendar.text)
        fields={k:p[k] for k in actions.PlanFields.model_fields};fields['reminder']=True
        p=self.op(p,'edit',fields=fields).json()['plan']
        due=p['reminder_at']
        def claim(plan):
            return self.client.post('/api/action-plans/'+plan['id']+'/reminder-claim',headers=self.h,
                json={'device_id':'p0-closeout-device','reminder_at':due}).json()['notify']
        paused=self.op(parent,'pause').json()['plan'];self.assertFalse(claim(p))
        self.op(paused,'resume');self.assertTrue(claim(p));self.assertFalse(claim(p))
        p=self.op(p,'complete').json()['plan'];self.assertFalse(claim(p))

    def test_R05_foreign_resources_receipts_and_cross_site_are_private(self):
        p=self.create()
        self.assertEqual(self.client.get('/api/action-plans/records?plan_id=foreign-action').status_code,404)
        self.assertEqual(self.op({**p,'id':'foreign-action'},'complete').status_code,404)
        self.assertFalse(self.client.get('/api/action-plans/requests/foreign-receipt').json()['found'])
        for headers in ({},self.h|{'Origin':'https://foreign.example'},self.h|{'Sec-Fetch-Site':'cross-site'}):
            response=self.client.post('/api/action-plans/'+p['id']+'/operations',headers=headers,
                json={'action':'complete','revision':1,'key':str(uuid.uuid4())})
            self.assertEqual(response.status_code,403)
        self.assertEqual(self.client.get('/api/action-plans/records').json()['total'],0)

    def test_A04_fact_dates_remain_after_timezone_edit_and_reschedule(self):
        p=self.create(completion_mode='time')
        started=self.op(p,'start').json()
        p=self.op(started['plan'],'finish',execution_id=started['execution']['id'],actual_minutes=3).json()['plan']
        records=self.client.get('/api/action-plans/records').json()
        fields={k:p[k] for k in actions.PlanFields.model_fields};fields['timezone']='America/Los_Angeles'
        p=self.op(p,'edit',fields=fields).json()['plan']
        self.op(p,'reschedule',date='2026-10-18')
        self.assertEqual(self.client.get('/api/action-plans/records').json(),records)
        self.assertEqual(records['records'][0]['timezone'],'Asia/Shanghai')
