"""Actual homepage in Chrome with synthetic courses; no personal data or network."""
import functools
import os
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest
from datetime import datetime, timezone


@unittest.skipUnless(os.getenv('RUN_GITHUB_BROWSER') == '1', 'Opt in to Chrome with RUN_GITHUB_BROWSER=1')
class SequentialLearningBrowser(unittest.TestCase):
    def test_resume_by_course_number_independent_of_calendar(self):
        from playwright.sync_api import sync_playwright

        static = Path(__file__).resolve().parents[1] / 'static'

        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self):
                self.path = self.path.removeprefix('/static')
                super().do_GET()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(static)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        lessons = [
            {'lesson_no': 10, 'topic': '第十课', 'date': '2099-01-01', 'learning_state': 'unknown'},
            {'lesson_no': 2, 'topic': '第二课', 'date': '2000-01-01', 'learning_state': 'unknown'},
            {'lesson_no': 1, 'topic': '第一课', 'date': '2000-01-01', 'learning_state': 'completed'},
            {'lesson_no': 3, 'topic': '第三课', 'date': '', 'learning_state': 'unknown'},
        ]
        for lesson in lessons:
            lesson.update(learning_label='本人确认完成' if lesson['learning_state'] == 'completed' else '待本人反馈', complete=True)
        expression = [
            {'topic': '表达第十课', 'date': '2099-01-01', 'learning_state': 'unknown', 'learning_label': '待本人反馈', 'filename': 'Day 010 - 十.md'},
            {'topic': '表达第一课', 'date': '2000-01-01', 'learning_state': 'unknown', 'learning_label': '待本人反馈', 'filename': 'Day 001 - 一.md'},
        ]
        mutations, errors = [], []

        def fixture(route):
            request = route.request
            endpoint = request.url.split(base)[-1].split('?')[0]
            if request.method != 'GET':
                mutations.append(endpoint)
            if endpoint == '/api/copilot/today-task':
                result = {'lessons': lessons}
            elif endpoint == '/api/study-materials':
                result = {'modules': [
                    {'id': 'biaoda', 'name': '结构化表达', 'duration': '15 分钟', 'lessons': expression},
                    {'id': 'yingyu', 'name': '英文阅读', 'duration': '15 分钟', 'lessons': []}]}
            elif endpoint.startswith('/api/study-materials/biaoda/'):
                result = {'content': '# 表达练习\n\n阅读后填写自己的反馈。', 'lesson': {'version': 'fixture-version'}, 'record': None}
            elif endpoint == '/api/plans':
                result = {'plans': [{'id': 'plan', 'name': '自定义计划', 'brief': {'minutes': 20}, 'lessons': [
                    {'lesson_no': 1, 'topic': '计划第一课', 'date': '2099-01-01', 'learning_state': 'unknown', 'learning_label': '待本人反馈'}]}], 'drafts': [], 'legacy': []}
            elif endpoint == '/api/data':
                result = dict(modules=[], checkins={}, habits={}, customFields=[], customRecords=[], decisions=[], predictions=[], reviews=[], insights=[], todos=[], _revision='fixture')
            elif endpoint == '/api/action-plans':
                result = {'plans': [], 'execution': None, 'server_time': datetime.now(timezone.utc).isoformat(), 'action_schema_version': 2}
            elif endpoint == '/api/auth/me':
                result = {'user': {'id': 'fixture', 'username': 'tester', 'is_owner': False}}
            else:
                result = dict(modules=[], lessons=[], plans=[], records=[], items=[], articles=[], jobs=[], entries=[], reports=[], stats={}, preferences={}, budget={}, attempts=[])
            route.fulfill(json=result)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=os.getenv('CHROME_EXECUTABLE', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'))
                try:
                    page = browser.new_page(viewport={'width': 1280, 'height': 960})
                    page.route('**/api/**', fixture)
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base)
                    page.get_by_text('继续学习 · 可选内容', exact=True).click()
                    home = page.locator('#dailyLearning')
                    home.get_by_role('heading', name='认知与通识', exact=True).wait_for()
                    self.assertEqual(page.locator('#dailyLearningTitle').inner_text(), '继续学习')
                    cognitive_next = home.locator('.learning-module').filter(has=page.get_by_role('heading', name='认知与通识', exact=True))
                    self.assertEqual(cognitive_next.locator('.lesson-title').all_text_contents(), ['第二课'])
                    self.assertNotIn('逾期', home.inner_text())
                    self.assertNotIn('2000-01-01', home.inner_text())
                    self.assertNotIn('undefined', home.inner_text())
                    self.assertIn('第 1 课', home.locator('.learning-module').nth(1).inner_text())
                    self.assertEqual(home.locator('.learning-module').nth(1).locator('.lesson-title').inner_text(), '表达第一课')
                    self.assertEqual(home.locator('.learning-module').nth(2).locator('.lesson-title').inner_text(), '计划第一课')
                    # The homepage exposes the next course; the library preserves all
                    # completed and future courses in lesson-number order.
                    home.get_by_role('button', name='查看全部课程', exact=True).click()
                    library = page.locator('#learningLibrary')
                    cognitive = library.locator('.learning-module').filter(has=page.get_by_role('heading', name='认知与通识 · 15–20 分钟', exact=True, include_hidden=True))
                    expression_module = library.locator('.learning-module').filter(has=page.get_by_role('heading', name='结构化表达 · 15 分钟', exact=True, include_hidden=True))
                    cognitive.get_by_role('button', name='再次阅读', exact=True).wait_for()
                    self.assertEqual(cognitive.locator('.lesson-title').all_text_contents(), ['第一课', '第二课', '第三课', '第十课'])
                    self.assertEqual(cognitive.locator('.lesson-row:not(.completed)').count(), 3)
                    self.assertEqual(cognitive.locator('.lesson-row.completed').count(), 1)
                    self.assertEqual(cognitive.locator('.lesson-row.completed .lesson-title').inner_text(), '第一课')
                    self.assertEqual(expression_module.locator('.lesson-title').all_text_contents(), ['表达第一课', '表达第十课'])
                    self.assertIn('尚无已保存课程', library.locator('.learning-module').nth(2).inner_text())
                    self.assertEqual(library.locator('.learning-module').nth(3).locator('.lesson-title').inner_text(), '计划第一课')
                    self.assertNotIn('逾期', library.inner_text())
                    self.assertNotIn('2000-01-01', library.inner_text())
                    self.assertNotIn('undefined', library.inner_text())
                    # Returning from the actual reader reloads saved completion state.
                    expression_module.locator('.lesson-row').first.get_by_role('button', name='开始学习', exact=True).click()
                    try:
                        page.locator('#dailyReader').get_by_role('heading', name='表达第一课', exact=True).wait_for(timeout=10000)
                    except Exception:
                        self.fail(f'Reader did not open: {page.locator("#dailyReader").inner_text()}; browser errors: {errors}')
                    expression[1]['learning_state'] = 'completed'
                    expression[1]['learning_label'] = '本人确认完成'
                    page.locator('#dailyReader').get_by_role('button', name='返回我的课程', exact=True).click()
                    expression_module.locator('.lesson-row.completed .lesson-title').get_by_text('表达第一课', exact=True).wait_for()
                    self.assertEqual(expression_module.get_by_role('button', name='再次阅读', exact=True).count(), 1)
                    self.assertEqual(expression_module.get_by_role('button', name='查看记录', exact=True).count(), 1)
                    page.get_by_role('button', name='今日', exact=True).click()
                    home.locator('.learning-module').nth(1).locator(':scope > .lesson-row .lesson-title').get_by_text('表达第十课', exact=True).wait_for()
                    self.assertIn('第 10 课', home.locator('.learning-module').nth(1).inner_text())
                    self.assertEqual(home.locator('.learning-module').nth(1).get_by_role('button', name='查看记录').count(), 0)
                    # Selecting another personal calendar date must not change the course queue.
                    page.locator('#personalDate').fill('1999-01-01')
                    page.locator('#personalDate').dispatch_event('change')
                    self.assertEqual(cognitive_next.locator('.lesson-title').inner_text(), '第二课')
                    lessons[1]['learning_state'] = 'completed'
                    page.locator('#view-personal').get_by_role('button', name='刷新', exact=True).click()
                    cognitive_next.locator('.lesson-title').get_by_text('第三课', exact=True).wait_for()
                    self.assertEqual(cognitive.locator('.lesson-row:not(.completed)').count(), 2)
                    self.assertEqual(cognitive.locator('.lesson-row.completed').count(), 2)
                    lessons[3]['learning_state'] = 'completed'
                    page.reload()
                    page.get_by_text('继续学习 · 可选内容', exact=True).click()
                    cognitive_next.locator('.lesson-title').get_by_text('第十课', exact=True).wait_for()
                    self.assertEqual(cognitive.locator('.lesson-row:not(.completed)').count(), 1)
                    self.assertEqual(cognitive.locator('.lesson-row.completed').count(), 3)
                    lessons[0]['learning_state'] = 'completed'
                    page.locator('#view-personal').get_by_role('button', name='刷新', exact=True).click()
                    cognitive_next.wait_for(state='detached')
                    home.get_by_role('button', name='查看全部课程', exact=True).click()
                    self.assertEqual(cognitive.locator('.lesson-row.completed').count(), 4)
                    self.assertEqual(cognitive.get_by_role('button', name='开始学习').count(), 0)
                    self.assertEqual(cognitive.get_by_role('button', name='再次阅读', exact=True).count(), 4)
                    page.set_viewport_size({'width': 390, 'height': 844})
                    self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
                    self.assertEqual(mutations, [], 'Displaying or refreshing courses must never mark them completed')
                    self.assertEqual(errors, [])
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
