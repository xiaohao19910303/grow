"""Tests for course feedback schema and CRUD."""
from unittest.mock import patch

from cloud_fixtures import CloudFixture
from copilot.core import Problem

DATE = '2026-10-14T10:00:00+08:00'


class FeedbackSchemaTest(CloudFixture):
    def setUp(self):
        super().setUp()
        self.store = self.seed_courses()
        self.clock = patch('copilot.core.now', return_value=DATE)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_feedback_table_created_on_initialize(self):
        with self.store.conn() as c:
            row = c.execute("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name='copilot_feedback'").fetchone()
        self.assertIsNotNone(row)

    def test_summaries_table_created_on_initialize(self):
        with self.store.conn() as c:
            row = c.execute("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name='copilot_summaries'").fetchone()
        self.assertIsNotNone(row)

    def test_learning_records_has_archived_column(self):
        with self.store.conn() as c:
            columns = {row[0] for row in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='copilot_learning_records'").fetchall()}
        self.assertIn('archived', columns)
        self.assertIn('archived_at', columns)


class FeedbackCrudTest(CloudFixture):
    def setUp(self):
        super().setUp()
        self.store = self.seed_courses()
        self.clock = patch('copilot.core.now', return_value=DATE)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def _complete_lesson(self, number):
        """Mark a lesson as completed in the learning records."""
        with self.store.conn() as c:
            c.execute('''
                INSERT INTO copilot_learning_records
                (module_id, round_id, lesson_no, completion_type, completed_at, idempotency_key)
                VALUES ('renzhi', 1, ?, 'quick', ?, ?)
            ''', (number, DATE, f'test-key-{number}'))

    def test_save_and_get_feedback(self):
        self._complete_lesson(1)
        data = {
            'mastery_level': 'fully_understood',
            'value_rating': 3,
            'feeling_tags': ['例子很好', '概念很清晰'],
            'key_learnings': '核心观点是...',
            'questions': '',
            'next_direction': '想深入逻辑谬误'
        }
        result = self.store.save_feedback(1, data, 'test-key-001')
        self.assertEqual(result['lesson_no'], 1)
        fetched = self.store.get_feedback(1)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched['mastery_level'], 'fully_understood')
        self.assertEqual(fetched['value_rating'], 3)
        self.assertEqual(fetched['feeling_tags'], ['例子很好', '概念很清晰'])
        self.assertEqual(fetched['key_learnings'], '核心观点是...')

    def test_get_feedback_returns_none_when_not_found(self):
        result = self.store.get_feedback(99)
        self.assertIsNone(result)

    def test_save_feedback_updates_existing(self):
        self._complete_lesson(1)
        data1 = {'mastery_level': 'partially_understood', 'value_rating': 1,
                 'feeling_tags': [], 'key_learnings': 'first', 'questions': '', 'next_direction': ''}
        self.store.save_feedback(1, data1, 'key1')
        data2 = {'mastery_level': 'fully_understood', 'value_rating': 3,
                 'feeling_tags': ['例子很好'], 'key_learnings': 'updated', 'questions': '', 'next_direction': ''}
        self.store.save_feedback(1, data2, 'key2')
        fetched = self.store.get_feedback(1)
        self.assertEqual(fetched['mastery_level'], 'fully_understood')
        self.assertEqual(fetched['key_learnings'], 'updated')

    def test_save_feedback_rejects_incomplete_lesson(self):
        data = {'mastery_level': 'fully_understood', 'value_rating': 3,
                'feeling_tags': [], 'key_learnings': '', 'questions': '', 'next_direction': ''}
        with self.assertRaises(Problem) as e:
            self.store.save_feedback(99, data, 'key1')
        self.assertEqual(e.exception.code, 'lesson_not_completed')

    def test_list_feedback(self):
        self._complete_lesson(1)
        self._complete_lesson(2)
        self.store.save_feedback(1, {
            'mastery_level': 'fully_understood', 'value_rating': 3,
            'feeling_tags': [], 'key_learnings': 'a', 'questions': '', 'next_direction': ''
        }, 'key1')
        self.store.save_feedback(2, {
            'mastery_level': 'basically_understood', 'value_rating': 2,
            'feeling_tags': [], 'key_learnings': 'b', 'questions': '', 'next_direction': ''
        }, 'key2')
        items = self.store.list_feedback()
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['lesson_no'], 1)
        self.assertEqual(items[1]['lesson_no'], 2)
