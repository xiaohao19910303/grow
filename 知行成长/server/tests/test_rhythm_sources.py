"""R04 real article/course source APIs capture private rhythm context durably."""
from datetime import datetime, timezone
import json
from unittest.mock import patch

import action_plans as actions
from fastapi.testclient import TestClient
from rhythm.store import RhythmStore
from test_action_p0_sources import CourseReceiptFixture
from test_legacy_cloud_api import CloudHTTPFixture


def enable_and_select(test, plan, day):
    response = test.client.post('/api/action-plans/rhythm/preferences', headers=test.headers,
        json=dict(key='source-rhythm-preferences', expected_revision=0, enabled=True))
    test.assertEqual(response.status_code, 200, response.text)
    response = test.client.post('/api/action-plans/rhythm/focus', headers=test.headers,
        json=dict(key='source-rhythm-focus', expected_revision=0, date=day, plan_id=plan['id']))
    test.assertEqual(response.status_code, 200, response.text)
    return response.json()['focus']


class RhythmCourseSourceTests(CourseReceiptFixture):
    def setUp(self):
        super().setUp()
        RhythmStore().initialize()
        self.focus = enable_and_select(self, self.plan, '2026-10-19')

    def test_real_course_source_and_repeat_return_same_execution_receipt(self):
        first = self.confirm()
        self.assertEqual(first.status_code, 200, first.text)
        event_id = first.json()['source_event_id']
        receipt = first.json()['action_completion_receipts'][0]
        self.assertEqual(self.confirm().json()['action_completion_receipts'], [receipt])
        with actions.connection() as c:
            event = json.loads(c.execute('SELECT data FROM action_content_events WHERE id=?', (event_id,)).fetchone()[0])
            self.assertEqual(event['rhythm_snapshot']['focus_day_id'], self.focus['id'])
            self.assertEqual(c.execute('SELECT count(*) FROM action_executions').fetchone()[0], 1)
        self.assertNotIn(self.focus['id'], json.dumps(self.repo.commits))

    def test_source_snapshot_survives_running_conflict_and_later_focus_change(self):
        start = self.client.post('/api/action-plans/' + self.plan['id'] + '/operations', headers=self.headers,
            json=dict(key='course-rhythm-start', revision=self.plan['revision'], action='start')).json()
        source = self.confirm()
        self.assertIn('arrangement_sync_error', source.json())
        self.assertEqual(source.json()['action_completion_receipts'], [])
        other = actions.create(actions.NewPlan(title='另一个行动', period='day', completion_mode='check',
            start_date='2026-10-19', end_date='2026-10-19', key='course-rhythm-another'))['plans'][0]
        changed = self.client.post('/api/action-plans/rhythm/focus', headers=self.headers,
            json=dict(key='course-rhythm-new-focus', expected_revision=1, date='2026-10-19', plan_id=other['id']))
        self.assertEqual(changed.status_code, 200, changed.text)
        saved = actions.mutate(self.plan['id'], actions.Mutation(action='finish', revision=start['plan']['revision'],
            key='course-rhythm-finish', execution_id=start['execution']['id'], actual_minutes=3))
        with patch('action_plans.clock', return_value=datetime(2026, 10, 20, 12, tzinfo=timezone.utc)):
            result = actions.mutate(self.plan['id'], actions.Mutation(action='reconcile-content', key='course-rhythm-reconcile',
                revision=saved['plan']['revision'], source_event_id=source.json()['source_event_id']))
        self.assertEqual(result['execution']['focus_plan_id_snapshot'], self.plan['id'])
        self.assertEqual(result['execution']['activity_date'], '2026-10-19')
        self.assertEqual(result['action_completion_receipts'][0]['execution_id'], result['execution']['id'])


class RhythmArticleSourceTests(CloudHTTPFixture):
    def setUp(self):
        super().setUp()
        clock = patch('action_plans.clock', return_value=datetime(2026, 10, 21, 12, tzinfo=timezone.utc))
        clock.start(); self.addCleanup(clock.stop)
        actions.register(self.app)
        self.client = TestClient(self.app, base_url='http://localhost'); self.addCleanup(self.client.close)
        self.headers = {'X-Copilot-Request': '1', 'X-Grow-Action-Schema': '2'}
        RhythmStore().initialize()

    def test_real_article_source_replays_receipt_without_leaking_focus_to_github(self):
        response = self.client.post('/api/action-plans/schedules', headers=self.headers, json=dict(
            title='读一篇文章', target={'kind': 'article', 'course': self.aid}, date='2026-10-21', key='rhythm-article-arrange'))
        self.assertEqual(response.status_code, 200, response.text)
        plan = response.json()['plan']
        focus = enable_and_select(self, plan, '2026-10-21')
        payload = {'data': {'read': True, 'key': 'rhythm-article-confirm', 'origin_action_id': plan['id']}}
        path = '/api/reading/articles/' + self.aid + '/personal'
        first = self.client.post(path, headers=self.headers, json=payload)
        self.assertEqual(first.status_code, 200, first.text)
        repeated = self.client.post(path, headers=self.headers, json=payload)
        self.assertEqual(repeated.json()['action_completion_receipts'], first.json()['action_completion_receipts'])
        with actions.connection() as c:
            event = json.loads(c.execute('SELECT data FROM action_content_events WHERE id=?', (first.json()['source_event_id'],)).fetchone()[0])
            self.assertEqual(event['rhythm_snapshot']['focus_plan_id_snapshot'], plan['id'])
        self.assertNotIn(focus['id'], json.dumps(self.repository.commits))
