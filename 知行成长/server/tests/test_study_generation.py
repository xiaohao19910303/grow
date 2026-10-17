"""Progress-based module generation with real PostgreSQL and simulated model/GitHub."""
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from cloud_content import ModuleContent
from copilot.core import Problem
from study_materials import initialize, register
from test_github_plans import Repository
from test_legacy_cloud_schema import PostgreSQLFixture

AI = {'api_base_url': 'https://model.example/v1', 'api_key': 'TEST_SECRET_NEVER_STORE', 'model_name': 'fixture-model'}


def output(module):
    if module == 'biaoda':
        sections = ('学习目标', '示范', '练习', '参考答案', '自查')
        body = '\n\n'.join('## ' + heading + '\n' + ('这是合成教学材料，先说结论再解释理由。' * 12) for heading in sections)
    else:
        body = '## 英文正文\n' + ('Clear evidence helps us understand the world around us. ' * 25)
        body += '\n\n' + '\n\n'.join('## ' + heading + '\n' + ('教学内容与解释。' * 12) for heading in ('中文译文', '词汇', '长句', '练习', '参考答案', '自查'))
    return json.dumps({'title': '循序渐进的练习', 'content': body}, ensure_ascii=False)


class StudyGenerationTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name, folder in [('英文阅读', '每日文章'), ('结构化表达', '每日练习')]:
            path = self.root / name / folder; path.mkdir(parents=True)
            (path / 'Day 001.md').write_text('# 已有第一课\n\n已有教学内容。')
        initialize()
        self.repo = Repository()
        self.content = ModuleContent('owner/courses', 'main', 'TEST_GITHUB_SECRET', transport=httpx.MockTransport(self.repo))
        mock = patch('cloud_content.configured_content', return_value=self.content)
        mock.start(); self.addCleanup(mock.stop)
        self.calls = []

        async def model(messages, config):
            self.calls.append({'messages': messages, 'config': config})
            module = json.loads(messages[1]['content'])['module_id']
            yield {'text': output(module)}
            yield {'done': True}

        self.model = patch('copilot.transport.qwen_stream', model)
        self.model.start(); self.addCleanup(self.model.stop)
        app = FastAPI()
        @app.exception_handler(Problem)
        async def problem(request, error):
            return JSONResponse({'message': error.message}, status_code=error.status)
        self.materials = register(app, self.root)
        self.client = TestClient(app)
        self.client.__enter__(); self.addCleanup(lambda: self.client.__exit__(None, None, None))
        self.h = {'X-Copilot-Request': '1'}

    def finish(self, module):
        path = '/api/study-materials/' + module + '/Day%20001.md'
        lesson = self.client.get(path).json()['lesson']
        response = self.client.post(path + '/learning-record', json={'version': lesson['version'], 'revision': 0,
            'summary_text': 'PRIVATE NOTE MUST NOT REACH MODEL OR GITHUB', 'time_spent_seconds': 20, 'key': 'finish-' + module}, headers=self.h)
        self.assertEqual(response.status_code, 200, response.text)

    def begin(self, module='biaoda', key='generate-next-001'):
        return self.client.post('/api/study-materials/' + module + '/generations',
            json={'key': key, 'ai_config': AI}, headers=self.h)

    def wait(self, module, key):
        for _ in range(150):
            response = self.client.get('/api/study-materials/' + module + '/generations/' + key)
            self.assertEqual(response.status_code, 200, response.text)
            job = response.json()
            if job['state'] not in ('queued', 'generating'):
                return job
            time.sleep(.02)
        self.fail('Generation did not finish')

    def test_complete_preview_publish_resume_and_read_immutable_github_course(self):
        blocked = self.begin()
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(self.calls, [])
        self.finish('biaoda')
        response = self.begin()
        self.assertEqual(response.status_code, 200, response.text)
        job = self.wait('biaoda', response.json()['id'])
        self.assertEqual(job['state'], 'ready', job)
        self.assertEqual(job['lesson_no'], 2)
        self.assertEqual(self.repo.ref_updates, 0, 'Generating a draft must not publish it')
        context = json.loads(self.calls[0]['messages'][1]['content'])
        self.assertEqual(context['lesson_no'], 2)
        self.assertNotIn('date', context)
        self.assertNotIn('PRIVATE NOTE', json.dumps(self.calls))
        replay = self.begin()
        self.assertEqual(replay.json()['id'], job['id'])
        self.assertEqual(len(self.calls), 1)
        path = '/api/study-materials/biaoda/generations/' + job['id'] + '/publish'
        published = self.client.post(path, json={}, headers=self.h)
        self.assertEqual(published.status_code, 200, published.text)
        self.assertEqual(self.client.post(path, json={}, headers=self.h).status_code, 200)
        self.assertEqual(self.repo.ref_updates, 1)
        modules = self.client.get('/api/study-materials').json()['modules']
        course = modules[1]['lessons'][-1]
        self.assertEqual(course['lesson_no'], 2)
        self.assertEqual(course['date'], '')
        self.assertEqual(course['learning_state'], 'unknown')
        read = self.client.get('/api/study-materials/biaoda/' + course['filename'])
        self.assertEqual(read.status_code, 200, read.text)
        self.assertIn('## 练习', read.json()['content'])
        self.assertIn('github_url', read.json()['lesson'])
        self.assertNotIn('PRIVATE NOTE', json.dumps(self.repo.commits))
        with self.materials.conn() as c:
            saved = '\n'.join(r[0] for r in c.execute('SELECT data FROM study_generation_jobs'))
        self.assertNotIn(AI['api_key'], saved)
        self.assertEqual(self.begin(key='cannot-skip-course').status_code, 409)

    def test_english_next_course_failed_stream_and_publication_recovery(self):
        self.finish('yingyu')
        response = self.begin('yingyu', 'english-next-001')
        self.assertEqual(response.status_code, 200, response.text)
        job = self.wait('yingyu', response.json()['id'])
        self.assertEqual(job['state'], 'ready', job)
        self.repo.lose_response = True
        path = '/api/study-materials/yingyu/generations/' + job['id'] + '/publish'
        self.assertEqual(self.client.post(path, json={}, headers=self.h).status_code, 503)
        self.repo.lose_response = False
        self.assertEqual(self.client.post(path, json={}, headers=self.h).status_code, 200)
        self.assertEqual(self.repo.ref_updates, 1)
        course = self.client.get('/api/study-materials').json()['modules'][0]['lessons'][-1]
        self.assertIn('英文正文', self.client.get('/api/study-materials/yingyu/' + course['filename']).json()['content'])

    def test_missing_credentials_and_cross_origin_requests_never_call_model(self):
        self.finish('biaoda')
        path = '/api/study-materials/biaoda/generations'
        self.assertEqual(self.client.post(path, json={'key': 'missing-config'}, headers=self.h).status_code, 422)
        self.assertEqual(self.client.post(path, json={'key': 'cross-origin', 'ai_config': AI}, headers={**self.h, 'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.calls, [])
