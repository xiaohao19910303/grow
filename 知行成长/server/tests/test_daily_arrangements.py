"""Date arrangements link existing content, never copy or publish private data."""
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import json
import uuid

import db
import action_plans as actions
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_legacy_cloud_schema import PostgreSQLFixture


class DailyArrangementsTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        self.fixed = patch('action_plans.clock', return_value=datetime(2026, 10, 19, 12, tzinfo=timezone.utc))
        self.fixed.start(); self.addCleanup(self.fixed.stop)
        app = FastAPI(); actions.register(app)
        self.client = TestClient(app, base_url='http://localhost'); self.addCleanup(self.client.close)
        self.headers = {'X-Copilot-Request': '1'}
        self.target = {'kind': 'article', 'course': 'article-' + 'a' * 20}
        self.article = {'id': self.target['course'], 'type': 'article', 'title': '证据与判断', 'read': False,
                        'full_content': '保存的原文', 'note': '私有笔记'}
        with db.connect() as c:
            c.execute('CREATE TABLE reading_records(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
            c.execute('INSERT INTO reading_records VALUES (?,?)', (self.article['id'], json.dumps(self.article)))

    def schedule(self, date='2026-10-20', **updates):
        body = dict(title='证据与判断', target=self.target, date=date, key=str(uuid.uuid4())) | updates
        return self.client.post('/api/action-plans/schedules', json=body, headers=self.headers)

    def change(self, plan, action, **updates):
        body = dict(action=action, revision=plan['revision'], key=str(uuid.uuid4())) | updates
        return self.client.post('/api/action-plans/' + plan['id'] + '/operations', json=body, headers=self.headers)

    def test_same_article_same_day_is_deduplicated_even_for_concurrent_different_keys(self):
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.schedule(), range(2)))
        self.assertEqual([r.status_code for r in results], [200, 200])
        self.assertEqual(results[0].json()['plan']['id'], results[1].json()['plan']['id'])
        plan = results[0].json()['plan']
        self.assertEqual(plan['completion_mode'], 'content')
        self.assertEqual(plan['start_date'], '2026-10-20')
        self.assertEqual(len(self.client.get('/api/action-plans').json()['plans']), 1)
        self.assertEqual(self.change(plan, 'start').status_code, 422)

    def test_reschedule_conflict_cancel_and_readd_keep_source_and_notes(self):
        first = self.schedule().json()['plan']
        second = self.schedule('2026-10-21').json()['plan']
        self.assertEqual(self.change(first, 'reschedule', date='2026-10-21').status_code, 409)
        self.assertEqual(self.change(first, 'reschedule', date='2026-10-19').json()['plan']['start_date'], '2026-10-19')
        cancelled = self.change(second, 'cancel').json()['plan']
        self.assertEqual(cancelled['status'], 'archived')
        replacement = self.schedule('2026-10-21').json()['plan']
        self.assertNotEqual(replacement['id'], second['id'])
        with db.connect() as c:
            self.assertEqual(json.loads(c.execute('SELECT data FROM reading_records').fetchone()[0]), self.article)

    def test_content_confirmation_completes_today_only_without_inventing_time(self):
        today = self.schedule('2026-10-19').json()['plan']
        future = self.schedule().json()['plan']
        timed = actions.create(actions.NewPlan(title='阅读20分钟', period='day', start_date='2026-10-19', end_date='2026-10-19',
                                             target=self.target, key=str(uuid.uuid4())))['plans'][0]
        actions.content_completed(self.target)
        plans = {p['id']: p for p in actions.listing()['plans']}
        self.assertEqual(plans[today['id']]['status'], 'completed')
        self.assertEqual(plans[today['id']]['progress']['minutes'], 0)
        self.assertEqual(plans[future['id']]['status'], 'active')
        self.assertEqual(plans[timed['id']]['status'], 'active')
        actions.content_completed(self.target)
        self.assertEqual(self.client.get('/api/action-plans/records').json()['total'], 1)

    def test_time_target_never_marks_article_read_and_unfinished_does_not_roll_forward(self):
        plan = self.schedule('2026-10-18').json()['plan']
        with patch('action_plans.clock', return_value=datetime(2026, 10, 20, 12, tzinfo=timezone.utc)):
            saved = actions.listing()['plans'][0]
        self.assertEqual(saved['start_date'], '2026-10-18')
        self.assertEqual(saved['status'], 'active')
        self.assertEqual(self.change(plan, 'complete').status_code, 422, 'a content arrangement cannot be ticked without reading confirmation')

    def test_check_task_has_explicit_zero_minute_completion_and_can_reopen(self):
        response = self.client.post('/api/action-plans', json=dict(title='晚上健身', period='day', start_date='2026-10-19',
            end_date='2026-10-19', completion_mode='check', target={'kind':'book'}, key=str(uuid.uuid4())), headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        plan = response.json()['plans'][0]
        done = self.change(plan, 'complete').json()['plan']
        self.assertEqual(done['status'], 'completed')
        reopened = self.change(done, 'reopen').json()['plan']
        self.assertEqual(reopened['status'], 'active')
        self.assertEqual(actions.listing()['plans'][0]['progress']['completed'], 0)

    def test_invalid_missing_foreign_sources_and_csrf_cannot_create_schedule(self):
        self.assertEqual(self.schedule(target={'kind':'article','course':'article-missing'}).status_code, 404)
        self.assertEqual(self.schedule(date='bad').status_code, 422)
        self.assertEqual(self.client.post('/api/action-plans/schedules', json=dict(title='x', target=self.target,
            date='2026-10-20', key=str(uuid.uuid4()))).status_code, 403)
