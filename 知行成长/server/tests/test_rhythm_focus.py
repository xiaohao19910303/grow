"""R03: real PostgreSQL preference and focus writes share action transactions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import uuid
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import action_plans as actions
import db
from rhythm.store import RhythmStore
from test_legacy_cloud_schema import PostgreSQLFixture


class RhythmFixture(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        self.clock = patch('action_plans.clock', return_value=datetime(2026, 10, 21, 12, tzinfo=timezone.utc))
        self.clock.start(); self.addCleanup(self.clock.stop)
        RhythmStore().initialize()
        self.app = FastAPI(); actions.register(self.app)
        self.client = TestClient(self.app, base_url='http://localhost'); self.addCleanup(self.client.close)
        self.headers = {'X-Copilot-Request': '1', 'X-Grow-Action-Schema': '2'}

    def post(self, path, **body):
        return self.client.post('/api/action-plans/rhythm' + path,
                                json={'key': str(uuid.uuid4()), **body}, headers=self.headers)

    def enable(self):
        response = self.post('/preferences', expected_revision=0, enabled=True)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def create(self, **updates):
        body = dict(title='今天的行动', period='day', start_date='2026-10-21', end_date='2026-10-21',
                    completion_mode='time', key=str(uuid.uuid4())) | updates
        result = self.client.post('/api/action-plans', json=body, headers=self.headers)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()['plans'][0]

    def select(self, plan, **updates):
        return self.post('/focus', expected_revision=0, date='2026-10-21', plan_id=plan['id'], **updates)

    def op(self, plan, action, **updates):
        return self.client.post('/api/action-plans/' + plan['id'] + '/operations', headers=self.headers,
                                json=dict(key=str(uuid.uuid4()), revision=plan['revision'], action=action) | updates)

    def today(self, **query):
        result = self.client.get('/api/action-plans/rhythm/today', params=query)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()


class RhythmFocusTests(RhythmFixture):
    def test_default_read_is_disabled_and_does_not_create_preferences_or_events(self):
        current = self.today()
        self.assertFalse(current['preferences']['enabled'])
        self.assertIsNone(current['focus'])
        self.assertFalse(self.client.get('/api/action-plans/rhythm/capabilities').json()['supported'])
        with db.connect() as c:
            for table in ('action_focus_days', 'action_rhythm_preferences', 'action_rhythm_events'):
                self.assertEqual(c.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)

    def test_preferences_replay_and_stale_revision_do_not_overwrite(self):
        body = dict(key='same-preferences-request', expected_revision=0, enabled=True)
        first = self.post('/preferences', **body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(self.post('/preferences', **body).json(), first.json())
        self.assertEqual(self.post('/preferences', expected_revision=0, enabled=False).status_code, 409)
        self.assertEqual(self.post('/preferences', **(body | {'weekly_target_days': 4})).status_code, 409)
        self.assertTrue(self.today()['preferences']['enabled'])

    def test_first_preferences_use_selected_timezone_local_date(self):
        with patch('action_plans.clock', return_value=datetime(2026, 10, 21, 1, tzinfo=timezone.utc)):
            result = self.post('/preferences', expected_revision=0, enabled=True, timezone='America/New_York')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['preferences']['effective_from'], '2026-10-20')

    def test_goal_and_timezone_take_effect_next_week_with_version_history(self):
        self.enable()
        changed = self.post('/preferences', expected_revision=1, enabled=True, weekly_target_days=5, timezone='UTC')
        self.assertEqual(changed.status_code, 200, changed.text)
        result = changed.json()
        self.assertEqual(result['preferences']['weekly_target_days'], 3)
        self.assertEqual(result['pending_preferences']['effective_from'], '2026-10-26')
        self.assertEqual(result['pending_preferences']['timezone'], 'UTC')
        self.assertEqual(self.post('/preferences', expected_revision=2, enabled=True,
                                   weekly_target_days=4, timezone='UTC').status_code, 200)
        with db.connect() as c:
            rows = c.execute('SELECT data FROM action_rhythm_preferences ORDER BY effective_from').fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual(json.loads(rows[0][0])['weekly_target_days'], 3)
            self.assertEqual(json.loads(rows[1][0])['history'][0]['weekly_target_days'], 5)
        with patch('action_plans.clock', return_value=datetime(2026, 10, 26, 1, tzinfo=timezone.utc)):
            self.assertEqual(self.today()['preferences']['weekly_target_days'], 4)
            self.assertEqual(self.today()['preferences']['timezone'], 'UTC')

    def test_disable_takes_effect_immediately_even_with_pending_goal(self):
        self.enable()
        self.post('/preferences', expected_revision=1, enabled=True, weekly_target_days=5)
        disabled = self.post('/preferences', expected_revision=2, enabled=False, weekly_target_days=5)
        self.assertEqual(disabled.status_code, 200, disabled.text)
        self.assertFalse(self.today()['preferences']['enabled'])
        plan = self.create()
        self.assertEqual(self.select(plan).json()['code'], 'FEATURE_DISABLED')

    def test_preference_activation_compares_instants_across_timezone_offsets(self):
        self.enable()
        self.post('/preferences', expected_revision=1, enabled=True, weekly_target_days=5, timezone='UTC')
        with patch('action_plans.clock', return_value=datetime(2026, 10, 25, 16, 1, tzinfo=timezone.utc)):
            changed = self.post('/preferences', expected_revision=2, enabled=True, weekly_target_days=5, timezone='UTC')
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()['preferences']['effective_from'], '2026-10-25')

    def test_focus_selection_requires_enabled_feature_and_keeps_same_day_identity(self):
        first, second = self.create(), self.create(title='另一个行动')
        self.assertEqual(self.select(first).json()['code'], 'FEATURE_DISABLED')
        self.enable()
        selected = self.select(first, key='first-focus-request')
        self.assertEqual(selected.status_code, 200, selected.text)
        self.assertEqual(self.select(first, key='first-focus-request').json(), selected.json())
        self.assertEqual(self.select(second).json()['code'], 'REVISION_CONFLICT')
        changed = self.post('/focus', expected_revision=1, date='2026-10-21', plan_id=second['id'])
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()['focus']['id'], selected.json()['focus']['id'])
        self.assertEqual(self.today()['focus']['plan_id'], second['id'])
        with db.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM action_focus_days').fetchone()[0], 1)
            self.assertEqual(c.execute('SELECT count(*) FROM action_plans').fetchone()[0], 2)

    def test_focus_rejects_missing_wrong_period_date_and_blocked_plans(self):
        self.enable()
        cases = [(self.create(start_date='2026-10-20', end_date='2026-10-20'), 422),
                 (self.create(start_date=None, end_date=None), 422),
                 (self.create(period='week', start_date='2026-10-19', end_date='2026-10-25'), 422)]
        paused = self.create(); paused = self.op(paused, 'pause').json()['plan']
        cases.append((paused, 409))
        for plan, status in cases:
            with self.subTest(plan=plan['id']):
                self.assertEqual(self.select(plan).status_code, status)
        self.assertEqual(self.select({'id': 'action-foreign'}).status_code, 404)
        self.assertEqual(self.post('/focus', expected_revision=0, date='2026-10-20', plan_id=paused['id']).status_code, 422)

    def test_concurrent_focus_selections_have_one_winner(self):
        self.enable(); plans = [self.create(), self.create(title='另一个')]
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(self.select, plans))
        self.assertEqual(sorted(r.status_code for r in responses), [200, 409])
        with db.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM action_focus_days').fetchone()[0], 1)

    def test_mode_rest_and_historical_read_do_not_write_action_facts(self):
        self.enable(); focus = self.select(self.create()).json()['focus']
        minimum = self.post('/focus/' + focus['id'] + '/mode', expected_revision=1,
                            mode='minimum', minimum_step='只读一段')
        self.assertEqual(minimum.status_code, 200, minimum.text)
        rest = self.post('/focus/' + focus['id'] + '/mode', expected_revision=2, mode='rest')
        self.assertTrue(rest.json()['focus']['rest'])
        self.assertTrue(self.today(date='2026-10-20')['read_only'])
        with db.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM action_executions').fetchone()[0], 0)

    def test_new_endpoints_keep_csrf_version_and_link_owner_boundaries(self):
        body = dict(key='cross-site-preferences', expected_revision=0, enabled=True)
        path = '/api/action-plans/rhythm/preferences'
        self.assertEqual(self.client.post(path, json=body).status_code, 403)
        self.assertEqual(self.client.post(path, json=body, headers={'X-Copilot-Request': '1'}).status_code, 409)
        self.assertEqual(self.client.post(path, json=body, headers=self.headers | {'Origin': 'https://other.example'}).status_code, 403)
        self.assertEqual(self.post('/preferences', expected_revision=True).status_code, 422)
        with actions.connection(True, allow_link=True) as c:
            c.execute("INSERT INTO action_link_state VALUES (1,?,NULL)", (actions.encoded({'phase': 'active'}),))
        with patch('action_link.call') as bridge:
            capability = self.client.get('/api/action-plans/rhythm/capabilities')
            self.assertEqual(capability.status_code, 200, capability.text)
            self.assertFalse(capability.json()['supported'])
            self.assertEqual(self.client.get('/api/action-plans/rhythm/today').status_code, 409)
            self.assertEqual(self.post('/preferences', **body).status_code, 409)
            bridge.assert_not_called()

    def test_old_handoff_is_blocked_before_contacting_bridge_if_rhythm_data_exists(self):
        self.enable()
        with patch('action_link.identity', return_value='fixture-user'), patch('action_link.call') as bridge:
            result = self.client.post('/api/action-link/preview', headers=self.headers, json={'code': 'a' * 36})
            self.assertEqual(result.status_code, 409, result.text)
            self.assertEqual(result.json()['code'], 'CONTRACT_UPGRADE_REQUIRED')
            bridge.assert_not_called()
