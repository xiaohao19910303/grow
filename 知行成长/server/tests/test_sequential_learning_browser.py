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
        from playwright.sync_api import sync_playwright, expect

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
                result = {'content': '# 表达练习\n\n阅读后填写自己的反馈。', 'lesson': {'version': 'a' * 64}, 'record': None}
            elif endpoint.startswith('/api/study-notes/'):
                result = None
            elif endpoint == '/api/plans':
                result = {'plans': [{'id': 'plan', 'name': '自定义计划', 'brief': {'minutes': 20}, 'lessons': [
                    {'lesson_no': 1, 'topic': '计划第一课', 'date': '2099-01-01', 'learning_state': 'unknown', 'learning_label': '待本人反馈'}]}], 'drafts': [], 'legacy': []}
            elif endpoint == '/api/data':
                result = dict(modules=[], checkins={}, habits={}, customFields=[], customRecords=[], decisions=[], predictions=[], reviews=[], insights=[], todos=[], _revision='fixture')
            elif endpoint == '/api/action-plans':
                result = {'plans': [], 'execution': None, 'server_time': datetime.now(timezone.utc).isoformat(), 'action_schema_version': 2}
            elif endpoint == '/api/auth/me':
                result = {'user': {'id': 'fixture', 'username': 'tester', 'is_owner': False}}
            elif endpoint == '/api/action-plans':
                result = {'plans':[],'execution':None,'server_time':'2026-10-22T12:00:00Z','action_schema_version':2,'capabilities':{'nullable_schedule':True}}
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
                    page.locator('[data-group="personal"]').click()
                    # The home continuation list is compact; the learning library owns
                    # the full ordered course list, including completed courses.
                    if page.locator('.continue-learning').get_attribute('open') is None:
                        page.locator('.continue-learning > summary').click()
                    home = page.locator('#dailyLearning')
                    cognitive = home.locator('.learning-module').filter(has=page.locator('h3').filter(has_text='认知与通识'))
                    expect(cognitive.locator('.lesson-title')).to_have_text(['第二课'])
                    self.assertEqual(page.locator('#dailyLearningTitle').inner_text(), '继续学习')
                    self.assertNotIn('逾期', home.inner_text())
                    self.assertNotIn('2000-01-01', home.inner_text())
                    self.assertNotIn('undefined', home.inner_text())
                    page.locator('[data-group="learning"]').click()
                    library = page.locator('#learningLibrary')
                    cognitive_library = library.locator('.learning-module').first
                    expect(cognitive_library.locator('.lesson-title')).to_have_text(['第一课', '第二课', '第三课', '第十课'])
                    self.assertEqual(cognitive_library.get_by_role('button', name='再次阅读', exact=True).count(), 1)
                    expression_library = library.locator('.learning-module').nth(1)
                    expect(expression_library.locator('.lesson-title')).to_have_text(['表达第一课', '表达第十课'])
                    self.assertIn('尚无已保存课程', library.locator('.learning-module').nth(2).inner_text())
                    self.assertEqual(library.locator('.learning-module').nth(3).locator('.lesson-title').inner_text(), '计划第一课')
                    # Returning from the actual reader reloads saved completion state.
                    expression_library.locator('.lesson-row').first.get_by_role('button', name='开始学习', exact=True).click()
                    page.locator('#dailyReader').get_by_role('heading', name='表达第一课', exact=True).wait_for()
                    expression[1]['learning_state'] = 'completed'
                    page.locator('#dailyReader').get_by_role('button', name=re.compile(r'返回(今日安排|我的课程|搜索结果|行动安排)')).click()
                    expect(expression_library.locator('.lesson-row').first).to_have_class(re.compile(r'completed'))
                    self.assertEqual(expression_library.locator('.lesson-row').first.get_by_role('button', name='再次阅读', exact=True).count(), 1)
                    page.locator('[data-group="personal"]').click()
                    expect(home.locator('.learning-module').nth(1).locator('.lesson-title')).to_have_text(['表达第十课'])
                    self.assertIn('第 10 课', home.locator('.learning-module').nth(1).inner_text())
                    self.assertEqual(home.locator('.learning-module').nth(1).get_by_role('button', name='查看记录').count(), 0)
                    # Selecting another personal calendar date must not change the course queue.
                    page.locator('#personalDate').fill('1999-01-01')
                    page.locator('#personalDate').dispatch_event('change')
                    expect(cognitive.locator('.lesson-title')).to_have_text(['第二课'])
                    lessons[1]['learning_state'] = 'completed'
                    page.locator('.continue-learning').get_by_role('button', name='刷新', exact=True).click()
                    expect(cognitive.locator('.lesson-title')).to_have_text(['第三课'])
                    lessons[3]['learning_state'] = 'completed'
                    page.reload()
                    if page.locator('.continue-learning').get_attribute('open') is None:
                        page.locator('.continue-learning > summary').click()
                    expect(cognitive.locator('.lesson-title')).to_have_text(['第十课'])
                    lessons[0]['learning_state'] = 'completed'
                    page.locator('.continue-learning').get_by_role('button', name='刷新', exact=True).click()
                    expect(cognitive).to_have_count(0)
                    page.locator('[data-group="learning"]').click()
                    expect(cognitive_library.locator('.lesson-row.completed')).to_have_count(4)
                    self.assertEqual(cognitive_library.get_by_role('button', name='开始学习').count(), 0)
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
