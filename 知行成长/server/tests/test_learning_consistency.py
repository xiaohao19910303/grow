"""Learning consistency regressions using disposable localhost PostgreSQL schemas.

Run with TEST_LEGACY_PG_DSN='host=127.0.0.1 dbname=postgres user=hao'.
Course files are temporary copies; no production data, network, or model is used.
"""
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from copilot.core import MODULE, Problem, Store, encoded
from plans.api import register as register_plans
from plans.store import Plans
from test_legacy_cloud_schema import PostgreSQLFixture


class LearningConsistencyTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'materials'
        shutil.copytree(Path(__file__).parent / 'fixtures' / 'renzhi', self.root / MODULE)
        self.runtime = Path(temporary.name) / 'runtime'
        self.store = Store(self.root, self.runtime)
        backend = patch.dict(os.environ, {'PLAN_CONTENT_BACKEND': 'local'})
        backend.start()
        self.addCleanup(backend.stop)

    def set_markdown_status(self, number, status):
        path = self.store.path('学习记录.md')
        lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
        for index, lesson_no, line in self.store.record_rows(''.join(lines)):
            if lesson_no == number:
                cells = line.rstrip('\n').split('|')
                cells[-2] = ' ' + status + ' '
                lines[index] = '|'.join(cells) + '\n'
                break
        else:
            self.fail(f'Fixture does not contain lesson {number}')
        path.write_text(''.join(lines), encoding='utf-8')

    def insert_completion(self, number=1, completed_at='2026-10-15T16:20:00+08:00'):
        with self.store.conn() as connection:
            connection.execute('''
                INSERT INTO copilot_learning_records
                    (module_id, round_id, lesson_no, completion_type, summary_text,
                     time_spent_seconds, completed_at, idempotency_key)
                VALUES ('renzhi', 1, ?, 'summary', ?, 245, ?, ?)
            ''', (number, '保留已有的学习总结', completed_at, f'existing-{number}'))

    def test_local_plans_initialize_repeatedly_and_list_api_works_on_postgresql(self):
        app = FastAPI()
        plans, _ = register_plans(app, self.root, self.runtime)
        plans.initialize()
        plans.initialize()

        with TestClient(app, base_url='http://localhost') as client:
            response = client.get('/api/plans')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['plans'], [])
        self.assertEqual(response.json()['storage'], 'local')
        self.assertEqual(len(response.json()['legacy']), 3)

    def test_local_plans_read_shared_settings_with_or_without_table_on_postgresql(self):
        plans = Plans(self.root, self.runtime)
        self.assertEqual(plans.get_setting('preferred_model', 'fallback'), 'fallback')
        self.store.initialize()
        with self.store.conn() as connection:
            connection.execute('INSERT INTO copilot_settings VALUES (?,?)',
                               ('preferred_model', encoded('saved-model')))
        self.assertEqual(plans.get_setting('preferred_model', 'fallback'), 'saved-model')
        self.assertEqual(plans.get_setting('missing', 'fallback'), 'fallback')

    def test_archive_upgrade_keeps_existing_learning_record_and_is_repeatable(self):
        from copilot.schema import TABLES
        with self.store.conn() as connection:
            connection.executescript(TABLES)
            connection.execute("INSERT INTO copilot_meta VALUES ('schema_version','2')")
            connection.execute('ALTER TABLE copilot_learning_records DROP COLUMN archived')
            connection.execute('ALTER TABLE copilot_learning_records DROP COLUMN archived_at')
        self.insert_completion()

        self.store.initialize()
        with self.store.conn() as connection:
            record = dict(connection.execute('SELECT * FROM copilot_learning_records').fetchone())
        self.assertEqual(record['archived'], 0)
        self.assertIsNone(record['archived_at'])
        self.assertEqual(record['summary_text'], '保留已有的学习总结')
        self.assertEqual(record['time_spent_seconds'], 245)
        self.assertEqual(record['completed_at'], '2026-10-15T16:20:00+08:00')
        self.assertEqual(record['idempotency_key'], 'existing-1')

        self.store.archive_lesson(1, 'upgrade-archive')
        self.store.initialize()
        with self.store.conn() as connection:
            records = connection.execute('SELECT * FROM copilot_learning_records').fetchall()
            self.assertEqual(connection.execute("SELECT value FROM copilot_meta WHERE key='schema_version'").fetchone()[0], '3')
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['id'], record['id'])
        self.assertEqual(records[0]['archived'], 1)
        self.assertTrue(records[0]['archived_at'])

    def test_database_completion_overrides_pending_markdown_label_and_supplies_date(self):
        self.store.initialize()
        self.insert_completion()

        result = self.store.scan()
        lesson = next(item for item in result['lessons'] if item['lesson_no'] == 1)
        self.assertEqual(lesson['learning_state'], 'completed')
        self.assertNotIn('待本人记录', lesson['learning_label'])
        self.assertTrue(lesson['learning_label'].startswith(('已完成', '已学习')))
        self.assertEqual(lesson['completed_at'], '2026-10-15T16:20:00+08:00')
        self.assertEqual(lesson['time_spent_seconds'], 245)
        self.assertEqual(result['completed_count'], 1)
        self.assertEqual([item['lesson_no'] for item in result['pending_learning_lessons']], [2])

    def test_dated_legacy_markdown_completions_are_imported_once_and_visible_in_calendar(self):
        timestamps = {1: '2026-10-15T10:30:00+08:00', 2: '2026-10-16T11:45:00+08:00'}
        self.set_markdown_status(1, f'已完成（本人确认：{timestamps[1]}）')
        self.set_markdown_status(2, f'已学习（总结提交：{timestamps[2]}）')
        self.store.initialize()
        self.store.initialize()

        lessons = self.store.scan()['lessons']
        history = self.store.get_learning_history(0, 30)
        self.assertEqual(history['total'], 2)
        self.assertEqual({item['lesson_no'] for item in history['items']}, {1, 2})
        for lesson in lessons:
            number = lesson['lesson_no']
            with self.subTest(lesson=number):
                self.assertEqual(lesson['learning_state'], 'completed')
                self.assertEqual(lesson['completed_at'], timestamps[number])
                record = self.store.get_learning_record(number)
                self.assertIsNotNone(record)
                self.assertEqual(record['lesson_no'], number)
                self.assertEqual(record['completed_at'], timestamps[number])
                by_date = self.store.get_learning_history_by_date('renzhi', timestamps[number][:10])
                self.assertEqual(by_date['total'], 1)
                self.assertEqual(by_date['items'][0]['lesson_no'], number)
        months = self.store.get_learning_history_months('renzhi', '2026-10-01', '2026-11-01')
        self.assertEqual({str(day): count for day, count in months.items()},
                         {'2026-10-15': 1, '2026-10-16': 1})

    def test_import_keeps_existing_database_summary_time_and_completion_timestamp(self):
        self.store.initialize()
        self.insert_completion()
        self.set_markdown_status(1, '已完成（本人确认：2026-10-14T08:00:00+08:00）')
        self.store.initialize()

        record = self.store.get_learning_record(1)
        self.assertEqual(record['summary_text'], '保留已有的学习总结')
        self.assertEqual(record['time_spent_seconds'], 245)
        self.assertEqual(record['completed_at'], '2026-10-15T16:20:00+08:00')
        self.assertEqual(self.store.get_learning_history(0, 30)['total'], 1)
        self.assertEqual(self.store.get_learning_history_by_date('renzhi', '2026-10-14')['total'], 0)
        self.assertEqual(self.store.get_learning_history_by_date('renzhi', '2026-10-15')['total'], 1)

    def test_pending_and_undated_legacy_statuses_do_not_invent_completion_dates(self):
        self.set_markdown_status(1, '已完成')
        self.store.initialize()
        self.store.initialize()
        lessons = {item['lesson_no']: item for item in self.store.scan()['lessons']}

        self.assertEqual(lessons[1]['learning_state'], 'completed')
        self.assertFalse(lessons[1].get('completed_at'))
        self.assertEqual(lessons[2]['learning_state'], 'unknown')
        self.assertFalse(lessons[2].get('completed_at'))
        self.assertIsNone(self.store.get_learning_record(1))
        self.assertIsNone(self.store.get_learning_record(2))
        self.assertEqual(self.store.get_learning_history(0, 30)['total'], 0)
        self.assertEqual(self.store.get_learning_history_months('renzhi', '2026-10-01', '2026-11-01'), {})

    def test_record_detail_contains_lesson_number_for_completed_course_rendering(self):
        self.store.initialize()
        self.insert_completion()

        record = self.store.get_learning_record(1)
        self.assertEqual(record.get('lesson_no'), 1)
        self.assertEqual(record['completion_type'], 'summary')
        self.assertEqual(record['completed_at'], '2026-10-15T16:20:00+08:00')

    def test_manual_completion_is_durable_and_retry_does_not_erase_notes(self):
        self.store.initialize()
        self.store.writer_session(True)
        self.insert_completion()
        version = self.store.lesson(1)['version']
        result = self.store.learning(1, 'completed', version, 'manual-completion')
        self.assertEqual(result['status'], 'done')
        self.assertEqual(self.store.learning(1, 'completed', version, 'manual-completion'), result)
        record = self.store.get_learning_record(1)
        self.assertEqual(record['summary_text'], '保留已有的学习总结')
        self.assertEqual(record['time_spent_seconds'], 245)
        self.assertEqual(self.store.get_learning_history(0, 30)['total'], 1)

    def test_new_completion_record_is_recovered_with_its_markdown_write(self):
        self.store.initialize()
        self.store.writer_session(True)
        version = self.store.lesson(1)['version']
        original = self.store._resume
        with patch.object(self.store, '_resume', side_effect=OSError('interrupted before publication')):
            with self.assertRaises(OSError):
                self.store.quick_complete(1, 120, version, 'recover-completion')
        with self.store.conn() as connection:
            operation = connection.execute('SELECT id FROM copilot_operations').fetchone()[0]
        # Restart must not turn a pending publication into a fabricated legacy record.
        self.store.initialize()
        self.assertEqual(original(operation)['status'], 'done')
        record = self.store.get_learning_record(1)
        self.assertIsNotNone(record)
        self.assertEqual(record['time_spent_seconds'], 120)
        self.assertEqual(self.store.scan()['completed_count'], 1)
        self.assertEqual(self.store.get_learning_history_by_date('renzhi', record['completed_at'][:10])['total'], 1)

    def test_calendar_and_daily_records_only_include_the_same_round_as_lesson_list(self):
        self.store.initialize()
        self.insert_completion()
        with self.store.conn() as connection:
            connection.execute('''
                INSERT INTO copilot_learning_records
                    (module_id, round_id, lesson_no, completion_type, completed_at)
                VALUES ('renzhi', 2, 2, 'manual', '2026-10-15T18:00:00+08:00')
            ''')

        lessons = {item['lesson_no']: item for item in self.store.scan()['lessons']}
        self.assertEqual(lessons[2]['learning_state'], 'unknown')
        self.assertIsNone(self.store.get_learning_record(2))
        self.assertEqual(self.store.get_learning_history(0, 30)['total'], 1)
        day = self.store.get_learning_history_by_date('renzhi', '2026-10-15')
        self.assertEqual(day['total'], 1)
        self.assertEqual([item['lesson_no'] for item in day['items']], [1])
        months = self.store.get_learning_history_months('renzhi', '2026-10-01', '2026-11-01')
        self.assertEqual({str(date): count for date, count in months.items()}, {'2026-10-15': 1})

    def test_pending_completion_is_not_imported_as_legacy_on_restart(self):
        self.store.initialize()
        self.store.writer_session(True)
        before = self.store.scan()
        version = before['lessons'][0]['version']
        with patch.object(self.store, '_scan', side_effect=[before, OSError('interrupted after file write')]):
            with self.assertRaises(Problem):
                self.store.quick_complete(1, 120, version, 'interrupted-after-file')
        self.store.initialize()
        self.assertIsNone(self.store.get_learning_record(1))
        self.store.writer_session(True)
        with self.store.conn() as connection:
            operation = connection.execute('SELECT id FROM copilot_operations').fetchone()[0]
        self.assertEqual(self.store.recover(operation)['status'], 'done')
        self.assertEqual(self.store.get_learning_record(1)['time_spent_seconds'], 120)
