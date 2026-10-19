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
