"""Course completion HTTP loop with isolated PostgreSQL and a GitHub simulator."""
import asyncio
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from cloud_fixtures import AsyncCloudFixture
from copilot.api import register
from copilot.core import Problem

AI_CONFIG = {'api_base_url': 'https://model.example/v1',
             'api_key': 'TEST_ONLY_MODEL_KEY', 'model_name': 'test-model'}
FEEDBACK = {
    'mastery_level': 'basically_understood', 'value_rating': 2,
    'feeling_tags': ['例子很好', '概念很清晰'],
    'key_learnings': '学会了独立思考和批判性思维',
    'questions': '如何应用到实际工作中？', 'next_direction': '想学习更多案例分析',
}


class CourseCompletionLoopTests(AsyncCloudFixture):
    def setUp(self):
        super().setUp()
        self.store = self.seed_courses()
        self.app = FastAPI()

        @self.app.exception_handler(Problem)
        async def problem_handler(request, error):
            return JSONResponse({'error': error.code, 'message': error.message}, status_code=error.status)

        with patch('copilot.api.make_store', return_value=self.store):
            register(self.app, self.root, self.runtime)
        self.prompts = []

        async def model(messages, cfg):
            self.assertEqual(cfg['key'], AI_CONFIG['api_key'])
            self.prompts.append(messages)
            yield {'text': '完整课程总结与进阶建议'}
            yield {'done': True}

        mocked = patch('copilot.transport.qwen_stream', model)
        mocked.start()
        self.addCleanup(mocked.stop)

    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(self.app, client=('127.0.0.1', 1234)),
            base_url='http://localhost', headers={'X-Copilot-Request': '1'})
        self.addAsyncCleanup(self.client.aclose)

    async def generate(self, endpoint, body):
        response = await self.client.post('/api/copilot/summaries/' + endpoint,
                                          json={**body, 'ai_config': AI_CONFIG},
                                          headers={'Accept': 'application/json'})
        self.assertEqual(response.status_code, 202, response.text)
        job_id = response.json()['id']
        async with asyncio.timeout(5):
            while True:
                response = await self.client.get('/api/copilot/background-jobs/' + job_id)
                self.assertEqual(response.status_code, 200, response.text)
                job = response.json()
                if job['state'] not in ('queued', 'generating'):
                    break
                await asyncio.sleep(.01)
        self.assertEqual(job['state'], 'ready', job)
        return job

    async def test_complete_course_completion_loop(self):
        """学完→反馈→归档/取消→总结→进阶草稿，均经真实 API。"""
        response = await self.client.get('/api/copilot/lessons/1')
        self.assertEqual(response.status_code, 200, response.text)
        public_head = self.repo.head
        response = await self.client.post('/api/copilot/lessons/1/complete', json={
            'version': response.json()['version'], 'time_spent_seconds': 120, 'key': 'loop-complete'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.store.get_learning_record(1)['time_spent_seconds'], 120)

        response = await self.client.post('/api/copilot/lessons/1/feedback',
                                          json={**FEEDBACK, 'key': 'loop-feedback'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['mastery_level'], 'basically_understood')
        response = await self.client.get('/api/copilot/lessons/1/feedback')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['mastery_level'], 'basically_understood')
        self.assertIn('例子很好', response.json()['feeling_tags'])

        for action, archived in (('archive', True), ('unarchive', False), ('archive', True)):
            response = await self.client.post('/api/copilot/lessons/1/' + action,
                                              json={'key': 'loop-' + action})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['archived'], archived)
            response = await self.client.get('/api/copilot/lessons/archived')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(any(item['lesson_no'] == 1 for item in response.json()['items']), archived)

        summary = await self.generate('generate', {'key': 'loop-summary', 'scope': 'full_course'})
        response = await self.client.get('/api/copilot/summaries/' + str(summary['result_id']))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['content'], '完整课程总结与进阶建议')
        self.assertIn(FEEDBACK['key_learnings'], str(self.prompts[0]))
        advanced = await self.generate('generate-advanced', {
            'key': 'loop-advanced', 'summary_content': response.json()['content']})
        response = await self.client.get('/api/copilot/drafts/' + advanced['draft_id'])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['content'], '完整课程总结与进阶建议')
        self.assertTrue(response.json()['is_advanced'])
        self.assertEqual(self.repo.head, public_head, '个人完成、反馈与总结必须仅保存在数据库')

    async def test_feedback_validation(self):
        for invalid in ({'mastery_level': 'invalid_level'}, {'value_rating': 5}):
            with self.subTest(invalid=invalid):
                response = await self.client.post('/api/copilot/lessons/1/feedback',
                                                  json={**FEEDBACK, **invalid, 'key': 'invalid-feedback'})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIsNone(self.store.get_feedback(1))

    async def test_archive_requires_completed_lesson(self):
        for number in (1, 99):
            with self.subTest(lesson=number):
                response = await self.client.post(f'/api/copilot/lessons/{number}/archive',
                                                  json={'key': 'incomplete-archive'})
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(response.json()['error'], 'lesson_not_completed')
        self.assertEqual(self.store.list_archived(), [])
