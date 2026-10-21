"""R02 migrations use real, disposable PostgreSQL schemas, never SQLite."""
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import db
from copilot.core import Problem
from test_legacy_cloud_schema import PostgreSQLFixture

from rhythm.schema import BUSINESS_TABLES, MIGRATION_1, SCHEMA_VERSION
from rhythm.store import RhythmStore


class RhythmSchemaTests(PostgreSQLFixture):
    def tables(self):
        with db.connect() as c:
            return {r[0] for r in c.execute(
                'SELECT tablename FROM pg_tables WHERE schemaname=current_schema()')}

    def test_empty_schema_initializes_once_without_enabling_or_enrolling(self):
        first = RhythmStore().initialize()
        second = RhythmStore().initialize()
        self.assertEqual(first, second)
        self.assertEqual(first['schema_version'], SCHEMA_VERSION)
        self.assertEqual(set(BUSINESS_TABLES), self.tables() - {'action_rhythm_migrations'})
        with db.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM action_rhythm_migrations').fetchone()[0], 1)
            for table in BUSINESS_TABLES:
                self.assertEqual(c.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)

    def test_existing_action_schema_and_json_survive_additive_migration(self):
        from action_plans import SCHEMA
        raw = json.dumps({'business_date': '2026-10-19', 'note': 'PRIVATE OLD NOTE'}, ensure_ascii=False)
        with db.connect() as c:
            c.executescript(SCHEMA)
            c.execute('INSERT INTO action_plans VALUES (?,?,?)', ('old', raw, 7))
            c.execute('INSERT INTO action_executions VALUES (?,?,?,?)', ('fact', 'old', 'partial', raw))
        RhythmStore().initialize()
        with db.connect() as c:
            row = c.execute('SELECT data,revision FROM action_plans').fetchone()
            self.assertEqual((row[0], row[1]), (raw, 7))
            self.assertEqual(c.execute('SELECT data FROM action_executions').fetchone()[0], raw)

    def test_concurrent_initializers_serialize_one_migration(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: RhythmStore().initialize(), range(4)))
        self.assertTrue(all(item == results[0] for item in results))
        with db.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM action_rhythm_migrations').fetchone()[0], 1)

    def test_dates_and_business_keys_cannot_duplicate(self):
        RhythmStore().initialize()
        inserts = [
            ('action_focus_days', '(id,local_date,data,revision)', ('first', '2026-10-21', '{}', 1)),
            ('action_rhythm_preferences', '(id,effective_from,data,revision)', ('first', '2026-10-21', '{}', 1)),
            ('action_weekly_cards', '(id,week_start,data,revision)', ('first', '2026-10-19', '{}', 1)),
            ('action_rhythm_events', '(id,dedupe_key,event_name,occurred_at,data)',
             ('first', 'same-operation', 'focus_selected', '2026-10-21T12:00:00Z', '{}')),
            ('action_rhythm_enrollments', '(id,experiment_key,data)', ('first', 'trial-v1', '{}')),
        ]
        for table, columns, values in inserts:
            query = f'INSERT INTO {table} {columns} VALUES ({",".join("?" for _ in values)})'
            with db.connect() as c:
                c.execute(query, values)
            with self.subTest(table=table), self.assertRaises(db.psycopg2.errors.UniqueViolation):
                with db.connect() as c:
                    c.execute(query, ('second', *values[1:]))

    def test_week_boundary_revision_json_and_event_name_are_constrained(self):
        RhythmStore().initialize()
        cases = [
            "INSERT INTO action_weekly_cards VALUES ('x','2026-10-21','{}',1)",
            "INSERT INTO action_focus_days VALUES ('x','2026-10-21','{}',0)",
            "INSERT INTO action_focus_days VALUES ('x','2026-10-21','[]',1)",
            "INSERT INTO action_rhythm_events VALUES ('x','k','private-arbitrary-event',CURRENT_TIMESTAMP,'{}')",
        ]
        for query in cases:
            with self.subTest(query=query), self.assertRaises(db.psycopg2.IntegrityError):
                with db.connect() as c:
                    c.execute(query)

    def test_failed_ddl_rolls_back_marker_and_other_new_tables(self):
        with patch('rhythm.schema.MIGRATION_1', MIGRATION_1 + '\nSELECT rhythm_deliberate_failure;'):
            with self.assertRaises(db.psycopg2.Error):
                RhythmStore().initialize()
        self.assertEqual(self.tables(), set())

    def test_unversioned_rhythm_table_is_preserved_for_explicit_review(self):
        with db.connect() as c:
            c.execute('CREATE TABLE action_focus_days(id TEXT)')
            c.execute("INSERT INTO action_focus_days VALUES ('keep-me')")
        with self.assertRaises(Problem) as caught:
            RhythmStore().initialize()
        self.assertEqual(caught.exception.code, 'RHYTHM_SCHEMA_INCOMPLETE')
        self.assertEqual(self.tables(), {'action_focus_days'})
        with db.connect() as c:
            self.assertEqual(c.execute('SELECT id FROM action_focus_days').fetchone()[0], 'keep-me')

    def test_newer_migration_version_is_refused_without_deleting_data(self):
        RhythmStore().initialize()
        with db.connect() as c:
            c.execute('INSERT INTO action_rhythm_migrations(version) VALUES (?)', (SCHEMA_VERSION + 1,))
        with self.assertRaises(Problem) as caught:
            RhythmStore().initialize()
        self.assertEqual(caught.exception.code, 'CONTRACT_UPGRADE_REQUIRED')
        with db.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM action_rhythm_migrations').fetchone()[0], 2)

    def test_migration_marker_with_missing_table_is_not_silently_repaired(self):
        RhythmStore().initialize()
        with db.connect() as c:
            c.execute('DROP TABLE action_weekly_cards')
        with self.assertRaises(Problem) as caught:
            RhythmStore().initialize()
        self.assertEqual(caught.exception.code, 'RHYTHM_SCHEMA_INCOMPLETE')
        self.assertNotIn('action_weekly_cards', self.tables())
