"""Bundled course completion against disposable PostgreSQL and synthetic files."""
from pathlib import Path
import os
import socket
import tempfile
import threading
import time
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_legacy_cloud_schema import PostgreSQLFixture


class StudyMaterialTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        from study_materials import initialize, register
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name, folder in [('英文阅读', '每日文章'), ('结构化表达', '每日练习')]:
            directory = self.root / name / folder
            directory.mkdir(parents=True)
            for number in (1, 2, 10):
                (directory / f'Day {number:03d}.md').write_text(f'# {name}第 {number} 课\n\n合成课程内容。')
        (self.root / '英文阅读/学习记录.md').write_text('| 日期 | Day | 完成情况 |\n| 2026-10-12 | Day001 | 已完成 |')
        initialize()
        app = FastAPI()
        register(app, self.root)
        self.client = TestClient(app)
        self.h = {'X-Copilot-Request': '1'}
        self.path = '/api/study-materials/biaoda/Day%20001.md'

    def body(self, **updates):
        data = self.client.get(self.path).json()
        return dict(summary_text='PRIVATE 学习笔记 <script>text</script>', time_spent_seconds=65,
                    version=data['lesson']['version'], revision=0, key='completion-first', **updates)

    def test_completion_notes_replay_updates_and_history_preserve_original_files(self):
        original = (self.root / '结构化表达/每日练习/Day 001.md').read_bytes()
        modules = self.client.get('/api/study-materials').json()['modules']
        self.assertEqual([x['lesson_no'] for x in modules[1]['lessons']], [1, 2, 10])
        self.assertEqual(modules[0]['lessons'][0]['learning_state'], 'completed')
        self.assertIsNone(self.client.get(self.path).json()['record'])
        body = self.body()
        response = self.client.post(self.path + '/learning-record', json=body, headers=self.h)
        self.assertEqual(response.status_code, 200, response.text)
        first = response.json()
        self.assertEqual(first['summary_text'], body['summary_text'])
        self.assertEqual(first['time_spent_seconds'], 65)
        self.assertEqual(first['revision'], 1)
        self.assertEqual(self.client.post(self.path + '/learning-record', json=body, headers=self.h).json(), first)
        body.update(revision=1, key='completion-update', summary_text='Edited private note', time_spent_seconds=2)
        updated = self.client.post(self.path + '/learning-record', json=body, headers=self.h).json()
        self.assertEqual(updated['revision'], 2)
        self.assertEqual(updated['completed_at'], first['completed_at'])
        self.assertEqual(updated['time_spent_seconds'], 65)
        self.assertEqual(self.client.get(self.path + '/learning-record').json(), updated)
        modules = self.client.get('/api/study-materials').json()['modules']
        self.assertEqual(modules[1]['lessons'][0]['learning_state'], 'completed')
        self.assertEqual(modules[1]['lessons'][1]['learning_state'], 'unknown')
        stamp = first['completed_at'][:10]
        history = self.client.get('/api/study-materials/learning-history', params={'start': stamp, 'end': stamp}).json()
        self.assertEqual(history['total'], 1)
        self.assertEqual(history['items'][0]['module_name'], '结构化表达')
        self.assertEqual(history['items'][0]['summary_text'], 'Edited private note')
        self.assertEqual((self.root / '结构化表达/每日练习/Day 001.md').read_bytes(), original)
        self.assertNotIn('PRIVATE', self.client.get('/api/study-materials').text)

    def test_invalid_writes_stale_tabs_and_missing_courses_cannot_overwrite(self):
        body = self.body()
        target = self.path + '/learning-record'
        self.assertEqual(self.client.post(target, json=body).status_code, 403)
        self.assertEqual(self.client.post(target, json={**body, 'user_id': 'someone'}, headers=self.h).status_code, 422)
        self.assertEqual(self.client.post(target, json={**body, 'time_spent_seconds': -1}, headers=self.h).status_code, 422)
        self.assertEqual(self.client.post(target, json={**body, 'summary_text': 'x' * 10001}, headers=self.h).status_code, 422)
        self.assertEqual(self.client.post(target, json={**body, 'version': '0' * 64}, headers=self.h).status_code, 409)
        self.assertEqual(self.client.post(target, json=body, headers={**self.h, 'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.post(target, json=body, headers=self.h).status_code, 200)
        self.assertEqual(self.client.post(target, json={**body, 'key': 'stale-second-tab'}, headers=self.h).status_code, 409)
        self.assertEqual(self.client.post(target, json={**body, 'summary_text': 'changed replay'}, headers=self.h).status_code, 409)
        self.assertEqual(self.client.get('/api/study-materials/biaoda/missing.md').status_code, 404)
        self.assertEqual(self.client.get('/api/study-materials/unknown/Day%20001.md').status_code, 404)
        self.assertEqual(self.client.get('/api/study-materials/learning-history?start=bad&end=bad').status_code, 422)
        self.assertEqual(self.client.get(target).json()['summary_text'], body['summary_text'])

    def test_simultaneous_first_completions_have_one_winner_and_preserve_each_module(self):
        from concurrent.futures import ThreadPoolExecutor
        body = self.body()
        def save(key):
            return self.client.post(self.path + '/learning-record', json={**body, 'key': key}, headers=self.h)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, ['race-request-one', 'race-request-two']))
        self.assertEqual(sorted(r.status_code for r in results), [200, 409])
        expression = self.client.get(self.path + '/learning-record').json()
        english_path = '/api/study-materials/yingyu/Day%20001.md'
        english = self.client.get(english_path).json()
        response = self.client.post(english_path + '/learning-record', json={**body, 'key': 'english-completion',
            'version': english['lesson']['version'], 'summary_text': 'Separate English note'}, headers=self.h)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get(self.path + '/learning-record').json(), expression)
        self.assertEqual(self.client.get(english_path + '/learning-record').json()['summary_text'], 'Separate English note')

    @unittest.skipUnless(os.getenv('RUN_GITHUB_BROWSER') == '1', 'Opt in to real Chrome with RUN_GITHUB_BROWSER=1')
    def test_browser_save_retry_next_course_notes_calendar_and_mobile(self):
        import uvicorn
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
        from playwright.sync_api import sync_playwright
        from study_materials import register

        app = FastAPI()
        register(app, self.root)
        static = Path(__file__).resolve().parents[1] / 'static'
        app.mount('/static', StaticFiles(directory=static))

        @app.get('/')
        def index():
            return FileResponse(static / 'index.html')

        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        base = 'http://127.0.0.1:' + str(sock.getsockname()[1])
        server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
        thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(.02)

        def unrelated(route):
            endpoint = route.request.url.split(base)[-1].split('?')[0]
            if endpoint.startswith('/api/study-materials'):
                return route.continue_()
            if endpoint == '/api/auth/me':
                result = {'user': {'id': 'fixture', 'username': 'tester', 'is_owner': True}}
            elif endpoint == '/api/data':
                result = dict(modules=[], checkins={}, habits={}, customFields=[], customRecords=[], decisions=[], predictions=[], reviews=[], insights=[], todos=[], _revision='fixture')
            elif endpoint.endswith('/by-date'):
                result = {'items': [], 'total': 0}
            elif endpoint.endswith('/months'):
                result = {}
            else:
                result = dict(modules=[], lessons=[], plans=[], records=[], items=[], articles=[], jobs=[], entries=[], reports=[], stats={}, preferences={}, budget={}, attempts=[], legacy=[], drafts=[])
            route.fulfill(json=result)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=os.getenv('CHROME_EXECUTABLE', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'))
                try:
                    page = browser.new_page(viewport={'width': 1280, 'height': 960})
                    page.route('**/api/**', unrelated)
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base)
                    home = page.locator('#dailyLearning')
                    expression = home.locator('.learning-module').filter(has=page.get_by_role('heading', name='结构化表达 · 15 分钟', exact=True))
                    expression.locator(':scope > .lesson-row').get_by_role('button', name='开始学习', exact=True).click()
                    reader = page.locator('#dailyReader')
                    note = reader.get_by_label('学习笔记（可选）')
                    note.fill('PRIVATE 浏览器笔记 <script>alert(1)</script>')
                    page.once('dialog', lambda dialog: dialog.dismiss())
                    page.locator('[data-group="personal"]').click()
                    self.assertTrue(reader.is_visible(), 'Cancelling navigation must keep the draft')
                    self.assertIsNone(self.client.get(self.path + '/learning-record').json())
                    failed = [False]

                    def lose_saved_response(route):
                        if route.request.method == 'POST' and not failed[0]:
                            failed[0] = True
                            self.assertEqual(route.fetch().status, 200)
                            route.abort()
                        else:
                            route.continue_()

                    page.route('**/api/study-materials/biaoda/*/learning-record', lose_saved_response)
                    reader.get_by_role('button', name='标记学完并保存', exact=True).click()
                    reader.get_by_role('status').filter(has_text='保存未完成，笔记仍保留').wait_for()
                    self.assertIn('PRIVATE 浏览器笔记', note.input_value())
                    reader.get_by_role('button', name='标记学完并保存', exact=True).click()
                    reader.get_by_role('status').filter(has_text='已学完，学习记录已保存').wait_for()
                    first = self.client.get(self.path + '/learning-record').json()
                    self.assertEqual(first['revision'], 1, 'Lost-response retries must not duplicate completion')
                    reader.get_by_role('button', name='继续下一课', exact=True).click()
                    reader.get_by_role('heading', name='结构化表达第 2 课', exact=True).first.wait_for()
                    self.assertEqual(note.input_value(), '')
                    reader.get_by_role('button', name='返回学习列表', exact=True).click()
                    expression.get_by_text('已完成课程 · 1 课', exact=True).click()
                    expression.get_by_role('button', name='查看记录', exact=True).click()
                    page.get_by_role('dialog').get_by_text(first['summary_text'], exact=True).wait_for()
                    page.get_by_role('dialog').get_by_role('button', name='关闭', exact=True).click()
                    expression.get_by_role('button', name='再次阅读', exact=True).click()
                    self.assertEqual(note.input_value(), first['summary_text'])
                    note.fill('Edited private note')
                    reader.get_by_role('button', name='保存学习记录', exact=True).click()
                    reader.get_by_role('status').filter(has_text='已学完，学习记录已保存').wait_for()
                    reader.get_by_role('button', name='返回学习列表', exact=True).click()
                    english = home.locator('.learning-module').filter(has=page.get_by_role('heading', name='英文阅读 · 35 分钟', exact=True))
                    english.locator(':scope > .lesson-row').get_by_role('button', name='开始学习', exact=True).click()
                    reader.get_by_role('heading', name='英文阅读第 2 课', exact=True).first.wait_for()
                    note.fill('PRIVATE English learning note')
                    page.set_viewport_size({'width': 390, 'height': 844})
                    self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
                    reader.locator('.study-record-form').screenshot(path='/tmp/grow-study-record-reader.png')
                    reader.get_by_role('button', name='标记学完并保存', exact=True).click()
                    reader.get_by_role('status').filter(has_text='已学完，学习记录已保存').wait_for()
                    reader.get_by_role('button', name='继续下一课', exact=True).click()
                    reader.get_by_role('heading', name='英文阅读第 10 课', exact=True).first.wait_for()
                    reader.get_by_role('button', name='返回学习列表', exact=True).click()
                    page.reload()
                    expression.get_by_text('已完成课程 · 1 课', exact=True).wait_for()
                    english.get_by_text('待学习 1 课 · 累计已完成 2 课', exact=True).wait_for()
                    page.get_by_role('button', name='记录', exact=True).click()
                    page.get_by_role('button', name='学习记录', exact=True).click()
                    history = page.locator('#view-learning-history')
                    history.get_by_text('Edited private note', exact=True).wait_for()
                    history.get_by_text('PRIVATE English learning note', exact=True).wait_for()
                    self.assertEqual(history.locator('.history-card').count(), 2)
                    page.set_viewport_size({'width': 390, 'height': 844})
                    self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
                    self.assertEqual(errors, [])
                finally:
                    browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            sock.close()
