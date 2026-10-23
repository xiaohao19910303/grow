"""Actual application bootstrap, first access, tenancy and old state roundtrip."""
import json
import os
import unittest

import psycopg2
from psycopg2 import sql

from rhythm.schema import BUSINESS_TABLES
import test_accounts as account_tests


@unittest.skipUnless(os.getenv('TEST_ACCOUNTS_PG_DSN'), 'Requires isolated localhost PostgreSQL')
class RhythmInitializationTests(unittest.TestCase):
    # Reuse the real account/GitHub-isolation setup, not its unrelated test cases.
    setUp = account_tests.AccountIntegrationTests.setUp
    cleanup_database = account_tests.AccountIntegrationTests.cleanup_database
    register = account_tests.AccountIntegrationTests.register
    invite = account_tests.AccountIntegrationTests.invite
    login = account_tests.AccountIntegrationTests.login

    def in_schema(self, schema, query, params=None):
        with psycopg2.connect(self.dsn) as c:
            cursor = c.cursor()
            cursor.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            cursor.execute(query, params)
            return cursor.fetchall() if cursor.description else None

    def assert_initialized(self, schema):
        for table in BUSINESS_TABLES:
            result = self.in_schema(schema, 'SELECT to_regclass(%s)', (table,))
            self.assertIsNotNone(result[0][0], table)

    def test_owner_bootstrap_creates_tables_but_no_preferences_events_or_trial(self):
        self.assert_initialized(self.schema)
        for table in BUSINESS_TABLES:
            self.assertEqual(self.in_schema(self.schema, f'SELECT count(*) FROM {table}')[0][0], 0)
        self.login('owner', os.environ['APP_PASSWORD'])
        capability = self.client.get('/api/action-plans/rhythm/capabilities')
        self.assertEqual(capability.status_code, 200)
        self.assertFalse(capability.json()['supported'])

    def test_new_accounts_initialize_on_first_access_and_keep_their_rows_private(self):
        schemas = []
        for username in ('alice', 'bob'):
            user = self.register(username)
            schema = 'learner_' + user['id']
            schemas.append(schema)
            self.assertEqual(self.client.get('/api/data').status_code, 200)
            self.assert_initialized(schema)
            self.in_schema(schema, 'INSERT INTO action_focus_days VALUES (%s,%s,%s,%s)',
                           ('same-id', '2026-10-21', json.dumps({'owner': username}), 1))
        for schema, username in zip(schemas, ('alice', 'bob')):
            self.assertEqual(json.loads(self.in_schema(schema, 'SELECT data FROM action_focus_days')[0][0]),
                             {'owner': username})
        self.assertEqual(self.in_schema(self.schema, 'SELECT count(*) FROM action_focus_days')[0][0], 0)

    def test_existing_account_with_old_action_tables_is_still_migrated(self):
        user = self.register('existing')
        schema = 'learner_' + user['id']
        from action_plans import SCHEMA
        self.in_schema(schema, SCHEMA)
        raw = '{"note":"PRIVATE EXISTING NOTE","business_date":"2026-10-19"}'
        self.in_schema(schema, 'INSERT INTO action_plans VALUES (%s,%s,%s)', ('old', raw, 4))
        self.assertEqual(self.client.get('/api/data').status_code, 200)
        self.assert_initialized(schema)
        self.assertEqual(self.in_schema(schema, 'SELECT data,revision FROM action_plans'), [(raw, 4)])

    def test_legacy_http_save_does_not_erase_any_rhythm_table(self):
        user = self.register('legacy-save')
        schema = 'learner_' + user['id']
        response = self.client.get('/api/data')
        self.assertEqual(response.status_code, 200)
        snapshot = response.json()
        self.in_schema(schema, "INSERT INTO action_rhythm_preferences VALUES ('p','2026-10-21','{}',1)")
        self.in_schema(schema, "INSERT INTO action_focus_days VALUES ('f','2026-10-21','{}',1)")
        self.in_schema(schema, "INSERT INTO action_weekly_cards VALUES ('w','2026-10-19','{}',1)")
        self.in_schema(schema, "INSERT INTO action_rhythm_events VALUES ('e','key','focus_selected',CURRENT_TIMESTAMP,'{}')")
        self.in_schema(schema, "INSERT INTO action_rhythm_enrollments VALUES ('t','test-trial','{}')")
        response = self.client.put('/api/data', json=snapshot,
                                   headers=self.headers | {'X-Legacy-State-Protocol': '1'})
        self.assertEqual(response.status_code, 200, response.text)
        for table in BUSINESS_TABLES:
            self.assertEqual(self.in_schema(schema, f'SELECT count(*) FROM {table}')[0][0], 1, table)
        self.assertTrue(set(BUSINESS_TABLES).isdisjoint(self.dashboard.TABLES))
