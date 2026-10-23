"""Tests for course archive functionality."""
import shutil
import tempfile
import unittest
from pathlib import Path
from test_legacy_cloud_schema import PostgreSQLFixture
from unittest.mock import patch

from copilot.core import Store

ROOT = Path(__file__).resolve().parents[3]
DATE = '2026-10-14T10:00:00+08:00'


class ArchiveTest(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        backend=patch.dict('os.environ', {'PLAN_CONTENT_BACKEND':'local'})
        backend.start();self.addCleanup(backend.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copytree(Path(__file__).parent / 'fixtures/renzhi', self.root / '每日认知与通识学习')
        (self.root / 'server').mkdir()
        self.store = Store(self.root, self.root / 'server/data.db')
        self.clock = patch('copilot.core.now', return_value=DATE)
        self.clock.start()
        self.store.initialize()

    def tearDown(self):
        self.clock.stop()
        self.temp.cleanup()

    def _complete_lesson(self, number):
        with self.store.conn() as c:
            c.execute('''
                INSERT INTO copilot_learning_records
                (module_id, round_id, lesson_no, completion_type, completed_at, idempotency_key)
                VALUES ('renzhi', 1, ?, 'quick', ?, ?)
            ''', (number, DATE, f'test-key-{number}'))

    def test_archive_and_unarchive(self):
        self._complete_lesson(1)
        self.store.archive_lesson(1, 'archive-key-001')
        archived = self.store.list_archived()
        self.assertTrue(any(x['lesson_no'] == 1 for x in archived))
        self.store.unarchive_lesson(1, 'unarchive-key-001')
        archived = self.store.list_archived()
        self.assertFalse(any(x['lesson_no'] == 1 for x in archived))

    def test_archive_rejects_incomplete_lesson(self):
        from copilot.core import Problem
        with self.assertRaises(Problem) as e:
            self.store.archive_lesson(99, 'key1')
        self.assertEqual(e.exception.code, 'lesson_not_completed')

    def test_list_archived_empty(self):
        result = self.store.list_archived()
        self.assertEqual(result, [])

    def test_list_archived_includes_feedback_data(self):
        self._complete_lesson(1)
        self.store.save_feedback(1, {
            'mastery_level': 'fully_understood', 'value_rating': 3,
            'feeling_tags': [], 'key_learnings': 'test learning', 'questions': '', 'next_direction': ''
        }, 'key1')
        self.store.archive_lesson(1, 'archive-key-001')
        archived = self.store.list_archived()
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0]['mastery_level'], 'fully_understood')
        self.assertEqual(archived[0]['key_learnings'], 'test learning')
