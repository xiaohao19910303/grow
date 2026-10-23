"""R03/R04 authenticated HTTP isolation across actual account schemas."""
from datetime import datetime, timezone
import os
import unittest
from unittest.mock import patch

import test_accounts as accounts_fixture


@unittest.skipUnless(os.getenv('TEST_ACCOUNTS_PG_DSN'), 'Requires isolated PostgreSQL')
class RhythmAccountTests(unittest.TestCase):
    cleanup_database = accounts_fixture.AccountIntegrationTests.cleanup_database
    register = accounts_fixture.AccountIntegrationTests.register
    invite = accounts_fixture.AccountIntegrationTests.invite
    login = accounts_fixture.AccountIntegrationTests.login

    def setUp(self):
        accounts_fixture.AccountIntegrationTests.setUp(self)
        self.headers['X-Grow-Action-Schema'] = '2'
        clock = patch('action_plans.clock', return_value=datetime(2026, 10, 21, 12, tzinfo=timezone.utc))
        clock.start(); self.addCleanup(clock.stop)

    def enable(self):
        result = self.client.post('/api/action-plans/rhythm/preferences', headers=self.headers,
            json=dict(key='same-key-in-each-account', expected_revision=0, enabled=True))
        self.assertEqual(result.status_code, 200, result.text)

    def test_anonymous_requests_cannot_read_or_write_rhythm(self):
        self.assertEqual(self.client.get('/api/action-plans/rhythm/today').status_code, 401)
        response = self.client.post('/api/action-plans/rhythm/preferences', headers=self.headers,
                                   json=dict(key='anonymous-rhythm-key', expected_revision=0, enabled=True))
        self.assertEqual(response.status_code, 401)

    def test_other_account_cannot_select_or_change_private_focus(self):
        first = self.register('rhythm-alice'); self.enable()
        response = self.client.post('/api/action-plans', headers=self.headers, json=dict(
            key='private-rhythm-plan', title='PRIVATE ALICE ACTION', period='day', completion_mode='check',
            start_date='2026-10-21', end_date='2026-10-21'))
        self.assertEqual(response.status_code, 200, response.text)
        plan = response.json()['plans'][0]
        selected = self.client.post('/api/action-plans/rhythm/focus', headers=self.headers, json=dict(
            key='private-rhythm-focus', expected_revision=0, date='2026-10-21', plan_id=plan['id']))
        self.assertEqual(selected.status_code, 200, selected.text)
        focus = selected.json()['focus']
        self.register('rhythm-bob'); self.enable()
        current = self.client.get('/api/action-plans/rhythm/today')
        self.assertIsNone(current.json()['focus'])
        self.assertNotIn('PRIVATE ALICE ACTION', current.text)
        self.assertEqual(self.client.post('/api/action-plans/rhythm/focus', headers=self.headers, json=dict(
            key='try-foreign-rhythm-focus', expected_revision=0, date='2026-10-21', plan_id=plan['id'])).status_code, 404)
        self.assertEqual(self.client.post('/api/action-plans/rhythm/focus/' + focus['id'] + '/mode',
            headers=self.headers, json=dict(key='try-foreign-rhythm-mode', expected_revision=1, mode='rest')).status_code, 404)
        self.assertEqual(self.client.get('/api/action-plans/rhythm/today',
            headers={'X-Account-Id': first['id']}).status_code, 409)
