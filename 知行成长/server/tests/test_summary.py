"""Tests for AI course summary generation."""
import asyncio
from unittest.mock import patch

from cloud_fixtures import CloudFixture
from copilot.core import Problem

DATE = '2026-10-14T10:00:00+08:00'


class SummaryTest(CloudFixture):
    def setUp(self):
        super().setUp()
        self.store = self.seed_courses()
        self.clock = patch('copilot.core.now', return_value=DATE)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def _complete_lesson(self, number):
        with self.store.conn() as c:
            c.execute('''
                INSERT INTO copilot_learning_records
                (module_id, round_id, lesson_no, completion_type, completed_at, idempotency_key)
                VALUES ('renzhi', 1, ?, 'quick', ?, ?)
            ''', (number, DATE, f'test-key-{number}'))

    def test_save_and_list_summaries(self):
        self.store.save_summary('renzhi', 1, 'full_course', 'test content', [])
        items = self.store.list_summaries()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['content'], 'test content')

    def test_get_summary_not_found(self):
        from copilot.core import Problem
        with self.assertRaises(Problem):
            self.store.get_summary(999)

    def test_summary_prompt_includes_feedback(self):
        from copilot.summary import SummaryGenerator
        self._complete_lesson(1)
        self.store.save_feedback(1, {
            'mastery_level': 'fully_understood', 'value_rating': 3,
            'feeling_tags': [], 'key_learnings': 'test learning', 'questions': '', 'next_direction': ''
        }, 'key1')
        captured = []
        class MockTransport:
            async def stream(self, messages, cfg):
                captured.append(messages)
                yield {'text': 'summary text'}
                yield {'done': True}
        async def _run():
            with patch('copilot.summary.generation_config', return_value={'key': 'test', 'url': 'http://test'}):
                gen = SummaryGenerator(self.store, MockTransport())
                results = []
                async for item in gen.generate('renzhi', 1, 'full_course'):
                    results.append(item)
                return results
        asyncio.run(_run())
        self.assertTrue(len(captured) > 0)
        all_content = ' '.join(m['content'] for batch in captured for m in batch)
        # The prompt should contain the feedback section header and the actual feedback data
        self.assertIn('用户反馈', all_content)
        self.assertIn('test learning', all_content)
