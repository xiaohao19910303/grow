"""Action plans use disposable PostgreSQL schemas; no personal files or model calls."""
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import psycopg2
import db
import action_plans as actions
from test_legacy_cloud_schema import PostgreSQLFixture


class ActionPlansTests(PostgreSQLFixture):
    def setUp(self):
        self.raw_connect = db.connect
        super().setUp()
        app = FastAPI()
        actions.register(app)
        self.client = TestClient(app, base_url='http://localhost')
        self.addCleanup(self.client.close)
        fixed = patch('action_plans.clock', return_value=datetime(2026, 10, 18, 12, tzinfo=timezone.utc))
        fixed.start();self.addCleanup(fixed.stop)
        self.headers = {'X-Copilot-Request': '1', 'X-Grow-Action-Schema':'2'}

    def create(self, **updates):
        data = dict(title='减少短视频，阅读20分钟', period='day', start_date='2026-10-18', end_date='2026-10-18',
                    at='19:00', reminder=True, key=str(uuid.uuid4())) | updates
        response = self.client.post('/api/action-plans', json=data, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['plans'][0]

    def change(self, plan, action, **updates):
        body = dict(action=action, revision=plan['revision'], key=str(uuid.uuid4())) | updates
        return self.client.post('/api/action-plans/' + plan['id'] + '/operations', json=body, headers=self.headers)

    def test_hierarchy_progress_and_minimum_interruption_do_not_invent_completions(self):
        year = self.create(title='年度阅读', period='year', start_date='2026-01-01', end_date='2026-12-31', target_count=200)
        week = self.create(title='本周读5次', period='week', start_date='2026-10-12', end_date='2026-10-18', parent_id=year['id'], target_count=5)
        day = self.create(parent_id=week['id'])
        start = self.change(day, 'start', variant='minimum').json()
        finished = self.change(start['plan'], 'finish', execution_id=start['execution']['id'], actual_minutes=5).json()
        self.assertEqual(finished['execution']['outcome'], 'minimum')
        self.assertEqual(finished['plan']['status'], 'active')
        start = self.change(finished['plan'], 'start').json()
        interrupted = self.change(start['plan'], 'finish', execution_id=start['execution']['id'], outcome='interrupted', actual_minutes=2).json()
        start = self.change(interrupted['plan'], 'start').json()
        self.assertEqual(self.change(start['plan'], 'finish', execution_id=start['execution']['id'], actual_minutes=20).status_code, 200)
        result = self.client.get('/api/action-plans').json()
        self.assertIsNone(result['execution'])
        by_id = {p['id']: p for p in result['plans']}
        self.assertEqual(by_id[year['id']]['progress'], dict(minutes=27, completed=1, minimum=1, partial=0, interrupted=1))
        self.assertEqual(by_id[week['id']]['progress']['completed'], 1)
        self.assertEqual(self.client.get('/api/action-plans/records').json()['total'], 3)
        with db.connect() as c:
            self.assertIsNone(c.execute("SELECT to_regclass('copilot_learning_records')").fetchone()[0])
            self.assertIsNone(c.execute("SELECT to_regclass('course_study_notes')").fetchone()[0])

    def test_create_and_finish_are_idempotent_and_stale_edit_cannot_overwrite(self):
        body = dict(title='阅读', period='day', start_date='2026-10-18', end_date='2026-10-18', key='same-create-key')
        first = self.client.post('/api/action-plans', json=body, headers=self.headers)
        self.assertEqual(first.json(), self.client.post('/api/action-plans', json=body, headers=self.headers).json())
        self.assertEqual(self.client.post('/api/action-plans', json={**body, 'title': '更改'}, headers=self.headers).status_code, 409)
        plan = first.json()['plans'][0]
        started = self.change(plan, 'start').json()
        self.assertEqual(self.change(plan, 'pause').status_code, 409)
        payload = dict(action='finish', revision=started['plan']['revision'], execution_id=started['execution']['id'], actual_minutes=20, key='same-finish-key')
        endpoint = '/api/action-plans/' + plan['id'] + '/operations'
        first = self.client.post(endpoint, json=payload, headers=self.headers)
        self.assertEqual(first.json(), self.client.post(endpoint, json=payload, headers=self.headers).json())
        self.assertEqual(self.client.get('/api/action-plans/records').json()['total'], 1)

    def test_one_running_execution_survives_service_reregistration_and_concurrent_start(self):
        plans = [self.create(), self.create(title='另一项')]
        with ThreadPoolExecutor(2) as pool:
            responses = list(pool.map(lambda plan: self.change(plan, 'start'), plans))
        self.assertEqual(sorted(r.status_code for r in responses), [200, 409])
        fresh = FastAPI();actions.register(fresh)
        with TestClient(fresh) as client:
            self.assertIsNotNone(client.get('/api/action-plans').json()['execution'])

    def test_parent_pause_blocks_children_and_active_descendant_blocks_pause(self):
        week = self.create(period='week', start_date='2026-10-12', end_date='2026-10-18')
        day = self.create(parent_id=week['id'])
        pause = self.change(week, 'pause').json()['plan']
        self.assertEqual(self.change(day, 'start').status_code, 409)
        child = next(p for p in self.client.get('/api/action-plans').json()['plans'] if p['id'] == day['id'])
        self.assertTrue(child['blocked'])
        week = self.change(pause, 'resume').json()['plan']
        self.change(day, 'start')
        self.assertEqual(self.change(week, 'archive').status_code, 409)

    def test_reminders_claim_once_per_device_snooze_and_calendar_timezone(self):
        plan = self.create()
        endpoint = '/api/action-plans/' + plan['id'] + '/reminder-claim'
        body = dict(device_id='test-device-123', reminder_at=plan['reminder_at'])
        self.assertTrue(self.client.post(endpoint, json=body, headers=self.headers).json()['notify'])
        self.assertFalse(self.client.post(endpoint, json=body, headers=self.headers).json()['notify'])
        changed = self.change(plan, 'snooze').json()['plan']
        self.assertEqual(changed['reminder_at'], '2026-10-18T12:15:00+00:00')
        self.assertFalse(self.client.post(endpoint, json={**body, 'reminder_at': changed['reminder_at']}, headers=self.headers).json()['notify'])
        calendar = self.client.get('/api/action-plans/' + plan['id'] + '/calendar.ics')
        self.assertIn('DTSTART:20261018T121500Z', calendar.text)
        self.assertIn('BEGIN:VALARM', calendar.text)
        self.assertIn('text/calendar', calendar.headers['content-type'])
        with patch('action_plans.clock', return_value=datetime(2026, 10, 18, 15, tzinfo=timezone.utc)):
            self.assertFalse(self.client.post(endpoint, json={**body, 'reminder_at': changed['reminder_at'], 'device_id': 'other-device'}, headers=self.headers).json()['notify'])

    def test_validation_repetition_csrf_and_foreign_reference(self):
        for updates in [dict(minimum_minutes=25), dict(timezone='Invalid/Zone'), dict(title='  '),
                        dict(period='week', end_date='2026-10-27'), dict(target_count=2), dict(target={'kind': 'article', 'course': 'javascript:alert(1)'})]:
            body = dict(title='阅读', period='day', start_date='2026-10-18', end_date='2026-10-18', key='validation-key') | updates
            self.assertEqual(self.client.post('/api/action-plans', json=body, headers=self.headers).status_code, 422)
        body = dict(title='工作日阅读', period='day', start_date='2026-10-12', end_date='2026-10-12', key='repeat-test-key',
                    repeat_dates=['2026-10-12', '2026-10-13', '2026-10-14', '2026-10-15', '2026-10-16'])
        response = self.client.post('/api/action-plans', json=body, headers=self.headers)
        self.assertEqual(len(response.json()['plans']), 5)
        self.assertEqual(self.client.post('/api/action-plans', json=body).status_code, 403)
        self.assertEqual(self.client.post('/api/action-plans', json=body, headers={**self.headers, 'Origin': 'https://foreign.example'}).status_code, 403)
        body.update(key='foreign-source-key', repeat_dates=[], target={'kind': 'plan', 'plan_id': 'plan-foreign', 'lesson_no': 1})
        self.assertEqual(self.client.post('/api/action-plans', json=body, headers=self.headers).status_code, 404)

    def test_recurrence_expands_daily_and_weekly_dates(self):
        daily = self.client.post('/api/action-plans', json=dict(
            title='每天阅读', period='day', start_date='2026-10-19', end_date='2026-10-19', key=str(uuid.uuid4()),
            recurrence={'freq': 'daily', 'interval': 1}, until='2026-10-22'), headers=self.headers).json()['plans']
        self.assertEqual([p['start_date'] for p in daily], ['2026-10-19', '2026-10-20', '2026-10-21', '2026-10-22'])
        weekly = self.client.post('/api/action-plans', json=dict(
            title='隔天阅读', period='day', start_date='2026-10-19', end_date='2026-10-19', key=str(uuid.uuid4()),
            recurrence={'freq': 'weekly', 'interval': 1, 'byday': [1, 3, 5]}, until='2026-10-30'), headers=self.headers).json()['plans']
        self.assertEqual([p['start_date'] for p in weekly], ['2026-10-19', '2026-10-21', '2026-10-23', '2026-10-26', '2026-10-28', '2026-10-30'])
        self.assertEqual(self.client.get('/api/action-plans').json()['plans'][0]['horizon'], 'short')

    def test_recurrence_validation_and_no_matching_dates(self):
        for updates in [dict(recurrence={'freq': 'daily', 'byday': [1]}),
                        dict(recurrence={'freq': 'daily'}),
                        dict(recurrence={'freq': 'weekly', 'byday': [1]}, until='2026-10-25'),
                        dict(recurrence={'freq': 'weekly'}, period='week')]:
            body = dict(title='阅读', period='day', start_date='2026-10-20', end_date='2026-10-20', key=str(uuid.uuid4())) | updates
            self.assertEqual(self.client.post('/api/action-plans', json=body, headers=self.headers).status_code, 422)

    def test_template_crud(self):
        # Create template
        body = dict(name='每日阅读', period='day', completion_mode='time', target_minutes=30, minimum_minutes=10)
        result = self.client.post('/api/action-plans/templates', json=body, headers=self.headers)
        self.assertEqual(result.status_code, 200)
        tid = result.json()['id']

        # List templates
        templates = self.client.get('/api/action-plans/templates', headers=self.headers).json()['templates']
        self.assertEqual(len(templates), 1)
        self.assertEqual(templates[0]['name'], '每日阅读')
        self.assertEqual(templates[0]['target_minutes'], 30)

        # Delete template
        self.assertEqual(self.client.delete('/api/action-plans/templates/' + tid, headers=self.headers).status_code, 200)
        templates = self.client.get('/api/action-plans/templates', headers=self.headers).json()['templates']
        self.assertEqual(len(templates), 0)

    def test_another_tenant_cannot_read_or_mutate_original_plan(self):
        plan = self.create()
        other = 'action_other_' + uuid.uuid4().hex
        with psycopg2.connect(self.dsn) as c:
            c.cursor().execute('CREATE SCHEMA ' + other)
        try:
            with patch('db.connect', lambda *a, **kw: self.raw_connect(self.dsn + ' options=-csearch_path=' + other, tenant=False)):
                self.assertEqual(self.client.get('/api/action-plans').json()['plans'], [])
                self.assertEqual(self.change(plan, 'start').status_code, 404)
        finally:
            with psycopg2.connect(self.dsn) as c:
                c.cursor().execute('DROP SCHEMA ' + other + ' CASCADE')
