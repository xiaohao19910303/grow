"""Tests for AI course summary generation."""
import asyncio
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

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
            with patch('copilot.summary.generation_config', return_value={'key': 'test', 'url': 'http://test', 'model': 'fixture'}):
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


class SummaryEvidenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from test_background_generations import Store, BackgroundGenerations
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.storage = Store(Path(temporary.name)/'evidence.db')
        BackgroundGenerations(self.storage).initialize()

    async def generate(self, feedback, *, persist=False):
        from copilot.summary import SummaryGenerator
        store = Mock()
        store.conn.side_effect = self.storage.conn
        store._scan.return_value = {'lessons': [
            {'lesson_no': 1, 'topic': '证据', 'learning_state': 'completed', 'completed_at': DATE},
            {'lesson_no': 2, 'topic': '因果', 'learning_state': 'pending'},
        ]}
        store.list_feedback.return_value = feedback
        captured = []
        class Transport:
            async def stream(self, messages, cfg):
                captured.extend(messages)
                yield {'text': '依据本人反馈整理'}
                yield {'done': True}
        with patch('copilot.summary.generation_config', return_value={'model':'fixture'}):
            stream = SummaryGenerator(store, Transport()).generate('renzhi', 1, persist=persist)
        # A source edit after prompt preparation must not change this analysis's basis.
        if feedback:
            feedback[0]['key_learnings'] = '后来修改的收获'
            feedback[0]['feeling_tags'].append('后来修改')
        events = [json.loads(block.split('data: ', 1)[1]) async for block in stream]
        return events[-1], captured, store

    async def test_snapshot_matches_selected_input_and_direct_save_despite_later_edits(self):
        original = {'lesson_no': 1, 'mastery_level': 'fully_understood', 'value_rating': 3,
                    'key_learnings': '能区分记录和解释', 'feeling_tags': ['清晰']}
        unused = {**original, 'lesson_no': 2, 'key_learnings': '未完成课程的反馈'}
        complete, messages, store = await self.generate(json.loads(json.dumps([original, unused])), persist=True)
        self.assertEqual(complete['feedback_snapshot'], [original])
        self.assertEqual(store.save_summary.call_args.args[-1], [original])
        prompt = messages[-1]['content']
        self.assertIn(original['key_learnings'], prompt)
        self.assertNotIn(unused['key_learnings'], prompt)
        self.assertNotIn('后来修改', prompt)
        self.assertIn('本人自评', prompt)
        self.assertIn('未提供课程正文、练习评分或实际应用结果', prompt)
        self.assertIn('不能推断没有理解或没有学习', prompt)
        store.list_feedback.assert_called_once_with('renzhi', 1)

    async def test_no_feedback_is_an_explicit_empty_snapshot(self):
        complete, messages, store = await self.generate([])
        self.assertEqual(complete['feedback_snapshot'], [])
        self.assertIn('暂无反馈数据', messages[-1]['content'])
        store.save_summary.assert_not_called()

    async def test_advanced_prompt_does_not_promote_self_ratings_into_ability_evidence(self):
        from copilot.summary import SummaryGenerator
        store = Mock()
        store.conn.side_effect = self.storage.conn
        store.list_feedback.return_value = [{'lesson_no': 1, 'mastery_level': 'fully_understood'}]
        captured = []
        class Transport:
            async def stream(self, messages, cfg):
                captured.extend(messages)
                yield {'text': '建议先做一次巩固练习'}
                yield {'done': True}
        gen = SummaryGenerator(store, Transport())
        with patch('copilot.summary.generation_config', return_value={'model':'fixture'}), patch.object(gen, '_get_next_lesson_no', return_value=2):
            results = [block async for block in gen.generate_advanced('本人反馈总结', persist=False)]
        self.assertTrue(results[-1].startswith('event: complete'))
        self.assertIn('本人自评理解充分的课次：\n第001课', captured[-1]['content'])
        self.assertIn('不根据自评自动提高难度', captured[-1]['content'])
        self.assertIn('没有练习结果时不得推断学习效果', captured[-1]['content'])
