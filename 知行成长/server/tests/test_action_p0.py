"""P0 acceptance against disposable PostgreSQL; no production accounts or AI."""
from datetime import datetime, timezone
from unittest.mock import patch
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import action_plans as actions
import db
from test_legacy_cloud_schema import PostgreSQLFixture


class ActionP0Tests(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        self.time = patch('action_plans.clock', return_value=datetime(2026, 10, 19, 12, tzinfo=timezone.utc))
        self.time.start(); self.addCleanup(self.time.stop)
        app = FastAPI(); actions.register(app)
        self.client = TestClient(app, base_url='http://localhost'); self.addCleanup(self.client.close)
        self.headers = {'X-Copilot-Request': '1', 'X-Grow-Action-Schema': '2'}

    def create(self, **values):
        body = dict(title='P0行动', period='day', completion_mode='check', start_date='2026-10-19',
                    end_date='2026-10-19', key=str(uuid.uuid4())) | values
        response = self.client.post('/api/action-plans', json=body, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['plans'][0]

    def change(self, plan, action, **values):
        return self.client.post('/api/action-plans/' + plan['id'] + '/operations', headers=self.headers,
            json=dict(action=action, revision=plan['revision'], key=str(uuid.uuid4())) | values)

    def test_F01_F02_nullable_check_and_no_fake_time(self):
        plan = self.create(start_date=None, end_date=None)
        for name in ('start_date', 'end_date', 'at', 'reminder_at', 'target', 'target_minutes', 'minimum_minutes'):
            self.assertIsNone(plan[name], name)
        self.assertEqual(self.client.get('/api/action-plans').json()['action_schema_version'], 2)
        self.assertEqual(self.change(plan, 'complete').status_code, 422)

    def test_T01_cumulative_time_and_actual_date(self):
        plan = self.create(completion_mode='time', start_date='2026-10-18', end_date='2026-10-18')
        for minutes in (5, 15):
            started = self.change(plan, 'start').json()
            result = self.change(started['plan'], 'finish', execution_id=started['execution']['id'], actual_minutes=minutes)
            self.assertEqual(result.status_code, 200, result.text)
            plan = result.json()['plan']
        self.assertEqual(plan['status'], 'completed')
        saved = self.client.get('/api/action-plans').json()['plans'][0]
        self.assertEqual((saved['progress']['minutes'], saved['progress']['completed']), (20, 1))
        facts = self.client.get('/api/action-plans/records').json()['records']
        self.assertTrue(all(r['business_date'] == '2026-10-19' and r['planned_date'] == '2026-10-18' for r in facts))

    def test_K01_reversal_keeps_original_fact(self):
        plan = self.create()
        done = self.change(plan, 'complete').json()['plan']
        reopened = self.change(done, 'reopen').json()['plan']
        records = self.client.get('/api/action-plans/records').json()['records']
        self.assertEqual({r['record_kind'] for r in records}, {'completion', 'reversal'})
        self.assertEqual(len(records), 2)
        self.assertEqual(self.client.get('/api/action-plans').json()['plans'][0]['progress']['completed'], 0)
        self.assertEqual(self.change(reopened, 'complete').json()['plan']['status'], 'completed')

    def test_T03_interrupted_threshold_requires_explicit_confirmation(self):
        plan = self.create(completion_mode='time')
        started = self.change(plan, 'start').json()
        saved = self.change(started['plan'], 'finish', execution_id=started['execution']['id'],
                            actual_minutes=20, outcome='interrupted').json()['plan']
        self.assertEqual(saved['status'], 'active')
        done = self.change(saved, 'complete-time')
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(done.json()['plan']['status'], 'completed')

    def test_R06_write_contract_and_read_only_receipts(self):
        response = self.client.post('/api/action-plans', headers={'X-Copilot-Request': '1'},
            json=dict(title='旧客户端', period='day', start_date='2026-10-19', end_date='2026-10-19', key='old-client-key'))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'CONTRACT_UPGRADE_REQUIRED')

    def test_S04_remove_date_preserves_identity_and_turns_off_reminder(self):
        plan = self.create(at='21:00', reminder=True)
        response = self.change(plan, 'reschedule', date=None)
        self.assertEqual(response.status_code, 200, response.text)
        changed = response.json()['plan']
        self.assertEqual(changed['id'], plan['id'])
        self.assertIsNone(changed['start_date']); self.assertIsNone(changed['at'])
        self.assertFalse(changed['reminder'])

    def source(self):
        target={'kind':'article','course':'article-p0-a'}
        with db.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS reading_records (id TEXT PRIMARY KEY,data TEXT NOT NULL)')
            c.execute('INSERT INTO reading_records VALUES (?,?) ON CONFLICT(id) DO NOTHING',(target['course'],'{}'))
        return target

    def test_F03_F04_F05_invalid_fields_are_atomic(self):
        cases=[dict(title=' '),dict(title='x'*161),dict(start_date=None),dict(end_date='2026-10-20'),
               dict(timezone='bad/zone'),dict(completion_mode='content'),
               dict(completion_mode='content',target={'kind':'library'}),dict(reminder=True,at=None)]
        cases += [dict(completion_mode='time',target_minutes=v) for v in (0,-1,1441,2.5)]
        cases += [dict(completion_mode='time',target_minutes=3,minimum_minutes=5)]
        for updates in cases:
            with self.subTest(updates=updates):
                body=dict(title='x',period='day',completion_mode='check',start_date='2026-10-19',end_date='2026-10-19',key=str(uuid.uuid4()))|updates
                result=self.client.post('/api/action-plans',headers=self.headers,json=body)
                self.assertEqual(result.status_code,422,result.text)
        self.assertEqual(self.client.get('/api/action-plans').json()['plans'],[])
        plan=self.create(completion_mode='time',target_minutes=1)
        self.assertEqual(plan['minimum_minutes'],1)

    def test_S01_S02_concurrent_content_dedup_and_null_bucket(self):
        from concurrent.futures import ThreadPoolExecutor
        target=self.source()
        def schedule(date):
            return self.client.post('/api/action-plans/schedules',headers=self.headers,
                json={'title':'内容','target':target,'date':date,'key':str(uuid.uuid4())})
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(schedule,['2026-10-19']*2))
        self.assertTrue(all(r.status_code==200 for r in results),[r.text for r in results])
        self.assertEqual(results[0].json()['plan']['id'],results[1].json()['plan']['id'])
        undated=schedule(None).json()['plan']
        self.assertEqual(schedule(None).json()['plan']['id'],undated['id'])
        self.assertNotEqual(undated['id'],results[0].json()['plan']['id'])
        self.create(title='同名');self.create(title='同名')
        self.assertEqual(len(self.client.get('/api/action-plans').json()['plans']),4)

    def test_S03_S05_conflict_and_cancel_preserve_facts(self):
        target=self.source();first=self.create(completion_mode='content',target=target)
        second=self.create(completion_mode='content',target=target,start_date='2026-10-20',end_date='2026-10-20')
        conflict=self.change(first,'reschedule',date='2026-10-20')
        self.assertEqual(conflict.status_code,409,conflict.text)
        self.assertEqual(conflict.json()['existing_plan_id'],second['id'])
        current={p['id']:p for p in self.client.get('/api/action-plans').json()['plans']}[first['id']]
        self.assertEqual(current['revision'],first['revision']);self.assertEqual(current['start_date'],first['start_date'])
        cancelled=self.change(second,'cancel').json()['plan']
        self.assertEqual(self.change(cancelled,'resume').status_code,409)
        replacement=self.create(completion_mode='content',target=target,start_date='2026-10-20',end_date='2026-10-20')
        self.assertNotEqual(replacement['id'],second['id'])

    def test_T06_T07_F09_state_locks_parent_and_future(self):
        parent=self.create(period='week',completion_mode='time',start_date='2026-10-19',end_date='2026-10-25')
        plan=self.create(parent_id=parent['id'])
        paused=self.change(parent,'pause').json()['plan']
        self.assertEqual(self.change(plan,'complete').status_code,409)
        self.change(paused,'resume')
        done=self.change(plan,'complete').json()['plan']
        fields={k:done[k] for k in actions.PlanFields.model_fields if k in done}
        self.assertEqual(self.change(done,'edit',fields=fields).status_code,409)
        future=self.create(start_date='2026-10-20',end_date='2026-10-20')
        self.assertEqual(self.change(future,'complete').json()['code'],'FUTURE_ACTION')
        timed=self.create(completion_mode='time')
        started=self.change(timed,'start').json()
        self.assertEqual(self.change(started['plan'],'reschedule',date=None).status_code,409)
        self.assertEqual(self.change(timed,'pause').json()['code'],'REVISION_CONFLICT')

    def test_A02_midnight_date_snapshot_and_A01_review_overdue(self):
        plan=self.create(completion_mode='time',target_minutes=12)
        with patch('action_plans.clock',return_value=datetime(2026,10,19,15,58,tzinfo=timezone.utc)):
            started=self.change(plan,'start').json()
        with patch('action_plans.clock',return_value=datetime(2026,10,19,16,10,tzinfo=timezone.utc)):
            finished=self.change(started['plan'],'finish',execution_id=started['execution']['id'],actual_minutes=12).json()
        self.assertEqual(finished['execution']['business_date'],'2026-10-19')
        preview=self.client.post('/api/action-plans/reviews/preview',headers=self.headers,
            json={'plan_id':plan['id'],'start_date':'2026-10-19','end_date':'2026-10-20'})
        self.assertEqual(preview.status_code,200,preview.text)
        self.assertEqual(preview.json()['stats']['minutes'],12)

    def test_R06_connected_old_backend_is_gated_and_receipts_remain_readable(self):
        from tenancy import current_user
        import json
        plan=self.create()
        with actions.connection() as c:
            request_key=c.execute('SELECT key FROM action_operations ORDER BY key LIMIT 1').fetchone()[0]
            c.execute('INSERT INTO action_link_state VALUES (1,?,NULL)',(json.dumps({'phase':'active'}),))
        token=current_user.set({'id':'synthetic-user'})
        try:
            with patch('action_link.call',side_effect=lambda source,body: {'found':False,'result':None} if body.get('path','').startswith('/requests/') else {'plans':[]}) as bridge:
                response=self.change(plan,'complete')
                self.assertEqual(response.status_code,409,response.text)
                self.assertEqual(response.json()['code'],'CONTRACT_UPGRADE_REQUIRED')
                self.assertEqual(bridge.call_count,1)
                receipt=self.client.get('/api/action-plans/requests/unknown-key')
                self.assertEqual(receipt.status_code,200,receipt.text)
                self.assertFalse(receipt.json()['found'])
                found=self.client.get('/api/action-plans/requests/'+request_key)
                self.assertTrue(found.json()['found'])
                with actions.connection() as c:c.execute('UPDATE action_link_state SET data=? WHERE id=1',(json.dumps({'phase':'pending'}),))
                self.assertTrue(self.client.get('/api/action-plans/requests/'+request_key).json()['found'])
        finally:current_user.reset(token)

    def test_S08_no_phantom_calendar_or_reminder(self):
        plan=self.create()
        result=self.client.get('/api/action-plans/'+plan['id']+'/calendar.ics')
        self.assertEqual(result.status_code,422,result.text)
        claim=self.client.post('/api/action-plans/'+plan['id']+'/reminder-claim',headers=self.headers,
            json={'device_id':'test-device-123','reminder_at':'2026-10-19T12:00:00+00:00'})
        self.assertFalse(claim.json()['notify'])

    def test_A04_legacy_read_keeps_dates_minutes_and_completion(self):
        import json
        plan=self.create(completion_mode='time',at='21:00')
        legacy={k:v for k,v in plan.items() if k not in ('schema_version','completion_record_id','completed_at')}
        legacy.pop('completion_mode');legacy['status']='completed'
        record=dict(id='legacy-fact',plan_id=plan['id'],title='旧记录',outcome='completed',actual_minutes=20,
                    started_at='2026-10-18T12:00:00+00:00',ended_at='2026-10-18T12:20:00+00:00',business_date='2026-10-17',timezone='Asia/Shanghai')
        with actions.connection() as c:
            c.execute('UPDATE action_plans SET data=? WHERE id=?',(json.dumps(legacy),plan['id']))
            c.execute('INSERT INTO action_executions VALUES (?,?,?,?)',(record['id'],plan['id'],'completed',json.dumps(record)))
        saved=self.client.get('/api/action-plans').json()['plans'][0]
        self.assertEqual((saved['completion_mode'],saved['at'],saved['status']),('time','21:00','completed'))
        self.assertEqual((saved['progress']['minutes'],saved['progress']['completed']),(20,1))
        fact=self.client.get('/api/action-plans/records').json()['records'][0]
        self.assertEqual((fact['business_date'],fact['date_basis']),('2026-10-17','legacy_planned'))

    def test_R06_p0_pairing_does_not_freeze_or_export_without_contract(self):
        from tenancy import current_user
        self.create()
        token=current_user.set({'id':'p0-synthetic'})
        try:
            with patch('action_link.call') as bridge:
                response=self.client.post('/api/action-link/preview',headers=self.headers,json={'code':'a'*36})
                self.assertEqual(response.status_code,409,response.text)
                bridge.assert_not_called()
            with actions.connection() as c:
                self.assertEqual(c.execute('SELECT count(*) FROM action_link_state').fetchone()[0],0)
        finally:current_user.reset(token)
