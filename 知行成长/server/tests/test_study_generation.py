import re
"""Progress-based module generation with real PostgreSQL and simulated model/GitHub."""
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
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
        from study_notes import register as register_notes
        register_notes(app)
        self.app = app
        self.client = TestClient(app)
        self.client.__enter__(); self.addCleanup(lambda: self.client.__exit__(None, None, None))
        self.addCleanup(lambda: self.client.portal.call(self.materials.generator.shutdown))
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
        from ai_evidence import read
        with self.materials.conn() as c:
            self.assertEqual(read(c,job['evidence_snapshot_id'])['messages'],self.calls[0]['messages'])
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
        replay = self.client.post(path, json={}, headers=self.h)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json(), published.json())
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
        self.assertEqual(self.client.post(path.removesuffix('/publish') + '/cancel', json={}, headers=self.h).status_code, 409)
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

    def test_incomplete_generation_is_not_publishable_and_explicit_retry_is_required(self):
        self.finish('biaoda')
        async def incomplete(messages, config):
            yield {'text': '{"title":"未完成"'}
        with patch('copilot.transport.qwen_stream', incomplete):
            response = self.begin(key='incomplete-stream')
            job = self.wait('biaoda', response.json()['id'])
        self.assertEqual(job['state'], 'failed')
        self.assertTrue(job['raw'])
        path = '/api/study-materials/biaoda/generations/' + job['id'] + '/publish'
        self.assertEqual(self.client.post(path, json={}, headers=self.h).status_code, 409)
        self.assertEqual(self.repo.ref_updates, 0)
        response = self.begin(key='explicit-retry-next')
        self.assertEqual(self.wait('biaoda', response.json()['id'])['state'], 'ready')

    def test_cancelled_stream_keeps_its_state_and_never_publishes(self):
        import asyncio
        self.finish('biaoda')
        async def paused(messages, config):
            yield {'text': '{"title":"partial"'}
            await asyncio.Event().wait()
        with patch('copilot.transport.qwen_stream', paused):
            job = self.begin(key='cancel-pending-job').json()
            path = '/api/study-materials/biaoda/generations/' + job['id']
            self.assertEqual(self.client.post(path + '/cancel', json={}, headers=self.h).status_code, 200)
            self.client.portal.call(self.materials.generator.shutdown)
            self.assertEqual(self.client.get(path).json()['state'], 'cancelled')
            self.assertEqual(self.client.post(path + '/publish', json={}, headers=self.h).status_code, 409)
        self.assertEqual(self.repo.ref_updates, 0)

    def test_formal_course_paths_keep_notes_and_legacy_import_scope_private(self):
        from cloud_content import ROOTS, is_formal
        from legacy_files import source_files
        self.assertEqual(ROOTS, ('每日认知与通识学习', '认知阅读'))
        self.assertEqual(source_files(self.root), {})
        for module in ('英文阅读', '结构化表达'):
            self.assertTrue(is_formal(module + '/网页课程/第002课.md'))
            with self.assertRaises(Problem):
                self.content.path(module + '/学习记录.md')
            with self.assertRaises(Problem):
                self.content.path(module + '/网页课程/../学习记录.md')

    @unittest.skipUnless(os.getenv('RUN_GITHUB_BROWSER') == '1', 'Opt in to Chrome with RUN_GITHUB_BROWSER=1')
    def test_browser_generate_reload_publish_retry_learn_and_generate_again(self):
        import uvicorn
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
        from playwright.sync_api import sync_playwright
        from study_notes import register as register_notes
        browser_app=FastAPI()
        browser_app.exception_handlers.update(self.app.exception_handlers)
        register_notes(browser_app)
        browser_app.include_router(self.app.router)
        from course_continuations import register as register_continuations
        register_continuations(browser_app,None,None,self.materials,None)
        self.finish('yingyu')
        static = Path(__file__).resolve().parents[1] / 'static'
        browser_app.mount('/static', StaticFiles(directory=static))
        @browser_app.get('/')
        def index():
            return FileResponse(static / 'index.html')
        sock = socket.socket(); sock.bind(('127.0.0.1', 0))
        base = 'http://127.0.0.1:' + str(sock.getsockname()[1])
        server = uvicorn.Server(uvicorn.Config(browser_app, log_level='error'))
        thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True); thread.start()
        for _ in range(100):
            if server.started: break
            time.sleep(.02)
        def unrelated(route):
            endpoint = route.request.url.split(base)[-1].split('?')[0]
            if endpoint.startswith(('/api/study-materials','/api/study-notes','/api/course-continuations')): return route.continue_()
            if endpoint == '/api/action-plans':
                return route.fulfill(json={'plans':[],'execution':None,'server_time':'2026-10-22T12:00:00Z','action_schema_version':2,'capabilities':{'nullable_schedule':True}})
            if endpoint == '/api/auth/me': result = {'user': {'id': 'fixture', 'username': 'tester', 'is_owner': True}}
            elif endpoint == '/api/data': result = dict(modules=[], checkins={}, habits={}, customFields=[], customRecords=[], decisions=[], predictions=[], reviews=[], insights=[], todos=[], _revision='fixture')
            else: result = dict(modules=[], lessons=[], plans=[], records=[], items=[], articles=[], jobs=[], entries=[], reports=[], stats={}, preferences={}, budget={}, attempts=[], legacy=[], drafts=[])
            route.fulfill(json=result)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=os.getenv('CHROME_EXECUTABLE', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'))
                try:
                    page = browser.new_page(viewport={'width': 1280, 'height': 960})
                    page.route('**/api/**', unrelated)
                    errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base)
                    page.get_by_role('button', name='设置', exact=True).click()
                    for selector, value in [('#apiBaseUrl', AI['api_base_url']), ('#apiKey', AI['api_key']), ('#modelName', AI['model_name'])]:
                        page.locator(selector).fill(value)
                    page.get_by_role('button', name='保存配置', exact=True).click()
                    page.locator('[data-group="learning"]').click()
                    library = page.locator('#learningLibrary')
                    library.locator('[data-course-key="yingyu"]').get_by_role('button', name='课程详情').click()
                    english = page.locator('#view-course .course-continuation')
                    english.get_by_role('button', name='直接生成下一课', exact=True).click()
                    english.get_by_role('button', name='保存课程并开始学习', exact=True).wait_for()
                    self.assertEqual(len(self.calls), 1)
                    page.locator('[data-group="personal"]').click()
                    page.locator('#personalDate').fill('2035-01-01')
                    page.locator('#personalDate').dispatch_event('change')
                    page.locator('[data-group="learning"]').click()
                    library.locator('[data-course-key="yingyu"]').get_by_role('button', name='课程详情').click()
                    english.get_by_role('button', name='直接生成下一课', exact=True).click()
                    english.get_by_role('button', name='保存课程并开始学习', exact=True).wait_for()
                    self.assertEqual(len(self.calls), 1, 'Calendar changes must preserve the same progress-based draft')
                    page.reload()
                    page.locator('[data-group="learning"]').click()
                    library.locator('[data-course-key="yingyu"]').get_by_role('button', name='课程详情').click()
                    english.get_by_role('button', name='直接生成下一课', exact=True).click()
                    english.get_by_role('button', name='保存课程并开始学习', exact=True).wait_for()
                    self.assertEqual(len(self.calls), 1, 'Reloading must reuse the existing draft without another model call')
                    page.set_viewport_size({'width': 390, 'height': 844})
                    self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
                    english.locator('.study-generation-panel').screenshot(path='/tmp/grow-next-course-mobile.png')
                    self.repo.fail_update = True
                    english.get_by_role('button', name='保存课程并开始学习', exact=True).click()
                    english.get_by_role('status').filter(has_text='GitHub').wait_for()
                    self.repo.fail_update = False
                    english.get_by_role('button', name='保存课程并开始学习', exact=True).click()
                    reader = page.locator('#dailyReader')
                    reader.get_by_role('heading', name='学习笔记与练习', exact=True).wait_for()
                    reader.get_by_role('link', name='在 GitHub 查看课程', exact=True).wait_for()
                    self.assertEqual(self.repo.ref_updates, 1)
                    self.assertEqual(len(self.calls), 1)
                    note = reader.get_by_label('学习笔记（可选）'); note.fill('NEW PRIVATE LESSON NOTE')
                    reader.get_by_role('button', name='标记学完并保存', exact=True).click()
                    reader.get_by_role('status').filter(has_text='已学完，学习记录已保存').wait_for()
                    reader.get_by_role('button', name='直接生成下一课', exact=True).click()
                    reader.get_by_role('button', name='保存课程并开始学习', exact=True).wait_for()
                    self.assertEqual(json.loads(self.calls[-1]['messages'][1]['content'])['lesson_no'], 3)
                    self.assertNotIn('PRIVATE', json.dumps(self.calls))
                    reader.get_by_role('button', name='放弃草稿', exact=True).click()
                    reader.get_by_role('button', name=re.compile(r'返回(今日安排|我的课程|课程详情|搜索结果|行动安排)')).click()
                    page.locator('#view-course').get_by_role('button', name='返回我的课程').click()
                    library.locator('[data-filter="pending"]').click()
                    library.locator('[data-course-key="biaoda"]').get_by_role('button', name='课程详情').click()
                    expression = page.locator('#view-course')
                    self.assertEqual(expression.get_by_role('button', name='生成下一课', exact=True).count(), 0)
                    expression.locator('.lesson-row').get_by_role('button', name='开始学习', exact=True).click()
                    reader.get_by_role('button', name='标记学完并保存', exact=True).click()
                    reader.get_by_role('status').filter(has_text='已学完，学习记录已保存').wait_for()
                    reader.get_by_role('button', name='直接生成下一课', exact=True).click()
                    reader.get_by_role('button', name='保存课程并开始学习', exact=True).wait_for()
                    reader.get_by_role('button', name='保存课程并开始学习', exact=True).click()
                    reader.get_by_role('heading', name='学习笔记与练习', exact=True).wait_for()
                    reader.get_by_role('link', name='在 GitHub 查看课程', exact=True).wait_for()
                    self.assertEqual(self.repo.ref_updates, 2)
                    self.assertEqual(len(self.calls), 3)
                    self.assertNotIn('PRIVATE', json.dumps(self.repo.commits))
                    self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
                    self.assertEqual(errors, [])
                finally: browser.close()
        finally:
            server.should_exit = True; thread.join(timeout=10); sock.close()
