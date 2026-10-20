"""Real Chrome: study completion updates the read-only check-in page."""
import functools
import json
import os
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import unittest
from zoneinfo import ZoneInfo


@unittest.skipUnless(os.getenv('RUN_GITHUB_BROWSER') == '1', 'Opt in to Chrome')
class LearningCheckinsBrowser(unittest.TestCase):
    def test_completion_checks_in_without_manual_write_and_survives_reload(self):
        from playwright.sync_api import sync_playwright, expect

        static = Path(__file__).resolve().parents[1] / 'static'

        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self):
                self.path = self.path.removeprefix('/static')
                super().do_GET()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(static)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_port}'
        stamp = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
        day = stamp[:10]
        completions, notes, writes, errors = {}, {}, [], []
        modules = [{'id': mid, 'name': name, 'color': '#4F6EF7'} for mid, name in
                   [('renzhi', '认知与通识'), ('yingyu', '英文阅读'), ('biaoda', '结构化表达'), ('fupan', '执行复盘')]]

        def lesson(number):
            return {'lesson_no': number, 'topic': f'英文第{number}课', 'filename': f'lesson-{number}.md',
                    'learning_state': 'completed' if number in completions else 'unknown',
                    'learning_label': '已完成' if number in completions else '待学习', 'version': 'a' * 64}

        def fixture(route):
            request = route.request
            path = request.url.split(base)[-1].split('?')[0]
            if request.method != 'GET':
                writes.append((request.method, path))
            if path == '/api/auth/me':
                result = {'user': {'id': 'fixture', 'username': 'tester', 'is_owner': False}}
            elif path == '/api/data':
                result = dict(modules=modules, checkins={day: {'fupan': 1}}, habits={}, customFields=[],
                              customRecords=[], decisions=[], predictions=[], reviews=[], insights=[], todos=[], _revision='fixture')
            elif path == '/api/learning-checkins':
                result = {'checkins': {day: {'yingyu': 3}} if completions else {},
                          'modules': [{'id': 'plan-demo', 'name': '沟通练习', 'color': '#7C5CF0'}]}
            elif path == '/api/study-materials':
                result = {'modules': [{'id': 'yingyu', 'name': '英文阅读', 'duration': '35 分钟',
                                       'lessons': [lesson(1), lesson(2)]}]}
            elif path.startswith('/api/study-notes/'):
                if request.method == 'PUT':
                    notes[path] = {**request.post_data_json, 'revision': 1}
                result = notes.get(path)
            elif path.startswith('/api/study-materials/yingyu/lesson-'):
                number = int(path.split('lesson-')[1][0])
                if request.method == 'POST':
                    completions[number] = {**request.post_data_json, 'lesson_no': number, 'completed_at': stamp, 'revision': 1}
                    result = completions[number]
                else:
                    result = {'lesson': lesson(number), 'content': '# 英文阅读\n\n学习内容。', 'record': completions.get(number)}
            else:
                result = dict(modules=[], lessons=[], plans=[], records=[], items=[], articles=[], jobs=[],
                              entries=[], reports=[], stats={}, preferences={}, budget={}, attempts=[],
                              server_time=stamp, execution=None)
            route.fulfill(body=json.dumps(result), content_type='application/json')

        def progress(page):
            page.locator('[data-group="growth"]').click()
            page.get_by_role('button', name='学习足迹', exact=True).click()
            expect(page.locator('#checkinStatus')).to_contain_text('已按课程完成日期自动汇总')

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=os.getenv('CHROME_EXECUTABLE', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'))
                try:
                    page = browser.new_page(viewport={'width': 1280, 'height': 960}, timezone_id='Asia/Shanghai')
                    page.route('**/api/**', fixture)
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base)
                    page.locator('.continue-learning > summary').click()
                    page.locator('#dailyLearning').get_by_role('heading', name='英文阅读', exact=True).wait_for()
                    page.locator('#dailyLearning').get_by_role('button', name='开始学习', exact=True).click()
                    page.get_by_label('学习笔记（可选）').fill('只暂存，不完成')
                    page.get_by_role('button', name='暂存笔记与答案', exact=True).click()
                    expect(page.locator('.study-notes-form')).to_contain_text('已暂存到云端')
                    progress(page)
                    expect(page.locator('#todayChips .chip').filter(has_text='英文阅读')).to_contain_text('暂无完成记录')
                    self.assertFalse(completions)
                    for number in (1, 2):
                        page.locator('[data-group="personal"]').click()
                        page.locator('#dailyLearning').get_by_role('button', name='开始学习', exact=True).click()
                        page.get_by_role('button', name='标记学完并保存', exact=True).click()
                        expect(page.locator('#dailyReader')).to_contain_text('已学完，学习记录已保存')
                        progress(page)
                        expect(page.locator('#todayChips .chip').filter(has_text='英文阅读')).to_contain_text('已完成 · 自动记录')
                        row = page.locator('#matrix tr').filter(has_text='英文阅读')
                        self.assertEqual(row.get_by_text('✓', exact=True).count(), 1)
                    expect(page.locator('#todayChips .chip').filter(has_text='执行复盘')).to_contain_text('进行中')
                    expect(page.locator('#todayChips')).to_contain_text('沟通练习')
                    self.assertEqual(page.locator('#todayChips [onclick],#matrix [onclick]').count(), 0)
                    page.reload()
                    progress(page)
                    expect(page.locator('#todayChips .chip').filter(has_text='英文阅读')).to_contain_text('已完成 · 自动记录')
                    screenshot = os.getenv('CHECKIN_SCREENSHOT')
                    if screenshot:
                        page.screenshot(path=screenshot, full_page=True)
                    page.set_viewport_size({'width': 390, 'height': 844})
                    self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
                    self.assertFalse([item for item in writes if item[1] == '/api/data'])
                    self.assertEqual(len(completions), 2)
                    self.assertEqual(errors, [])
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
