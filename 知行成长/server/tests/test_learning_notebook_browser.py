"""Real notebook discovery, editing and return navigation on isolated HTTP/PG."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest
import uuid

from playwright.sync_api import expect, sync_playwright


class LearningNotebookBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = subprocess.Popen([sys.executable, str(Path(__file__).with_name('serve_daily_arrangements_fixture.py'))],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=os.environ.copy())
        cls.addClassCleanup(cls.stop_fixture)
        if not select.select([cls.fixture.stdout], [], [], 30)[0]:
            raise RuntimeError('Notebook fixture startup timed out')
        message = cls.fixture.stdout.readline()
        if not message:
            raise RuntimeError('Notebook fixture did not start')
        cls.base = json.loads(message)['url']
        cls.playwright = sync_playwright().start(); cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch(headless=True, executable_path=os.getenv(
            'CHROME_EXECUTABLE', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'))
        cls.addClassCleanup(cls.browser.close)

    @classmethod
    def stop_fixture(cls):
        cls.fixture.terminate()
        try: cls.fixture.wait(timeout=10)
        except subprocess.TimeoutExpired: cls.fixture.kill(); cls.fixture.wait(timeout=5)
        cls.fixture.stdout.close(); cls.fixture.stderr.close()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 960})
        self.addCleanup(self.context.close)
        self.context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(self.base + '/') else route.abort())
        self.page = self.context.new_page(); self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.prefix = 'notebook-' + uuid.uuid4().hex[:8]

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def save(self, kind, course, notes='', answers=None, version='a'*64):
        response = self.context.request.put(self.base + '/api/study-notes/' + kind + '/' + course,
            headers={'X-Copilot-Request': '1'}, data=dict(notes=notes, answers=answers or {}, version=version,
                                                       revision=0, key='notebook-' + uuid.uuid4().hex))
        self.assertEqual(response.status, 200, response.text())

    def enter(self):
        self.page.goto(self.base)
        self.page.locator('[data-group="learning"]').click()
        self.page.locator('#subnav').get_by_role('button', name='学习笔记', exact=True).click()
        return self.page.locator('#view-learning-notes')

    def search(self, root, text):
        root.get_by_label('搜索笔记与答案').fill(text)
        root.get_by_role('button', name='搜索', exact=True).click()

    def test_saved_unfinished_note_opens_edits_and_returns_to_filtered_notebook(self):
        material = self.context.request.get(self.base + '/api/study-materials/biaoda/Day%20001.md').json()
        self.save('biaoda', 'Day%20001.md', self.prefix + ' <img src=x onerror=alert(1)>', version=material['lesson']['version'])
        self.save('yingyu', 'Day%20001.md', '其他模块的笔记 ' + self.prefix)
        root = self.enter(); self.search(root, self.prefix)
        root.get_by_label('学习模块').select_option('biaoda')
        expect(root.locator('.notebook-card')).to_have_count(1)
        expect(root.locator('.notebook-card')).to_contain_text('<img src=x onerror=alert(1)>')
        expect(root.locator('.notebook-card img')).to_have_count(0)
        root.locator('.notebook-open').click()
        reader = self.page.locator('#dailyReader')
        note = reader.get_by_label('学习笔记（可选）', exact=True)
        expect(note).to_have_value(self.prefix + ' <img src=x onerror=alert(1)>')
        note.fill(self.prefix + ' 新的工作应用笔记')
        reader.get_by_role('button', name='暂存笔记与答案', exact=True).click()
        expect(reader.locator('.study-notes-form [aria-live=polite]')).to_contain_text('已暂存到云端')
        reader.get_by_role('button', name='返回学习笔记', exact=True).click()
        expect(root).to_be_visible()
        expect(root.get_by_label('搜索笔记与答案')).to_have_value(self.prefix)
        expect(root.get_by_label('学习模块')).to_have_value('biaoda')
        expect(root.locator('.notebook-card')).to_contain_text('新的工作应用笔记')
        saved = self.context.request.get(self.base + '/api/study-materials/biaoda/Day%20001.md').json()
        self.assertIsNone(saved['record'], 'Saving notes must not create a completion')
        self.page.reload()
        expect(root).to_be_visible()
        expect(root.locator('.notebook-card').filter(has_text=self.prefix + ' 新的工作应用笔记')).to_have_count(1)

    def test_pagination_answer_search_empty_results_and_narrow_layout(self):
        for index in range(22):
            self.save('renzhi', self.prefix + '-' + str(index), answers={'q': self.prefix + ' 答案 ' + str(index)})
        root = self.enter(); self.search(root, self.prefix)
        expect(root.locator('.notebook-card')).to_have_count(20)
        root.get_by_role('button', name='下一页', exact=True).click()
        expect(root.locator('.notebook-card')).to_have_count(2)
        expect(root.get_by_role('navigation', name='学习笔记分页')).to_contain_text('第 2 / 2 页')
        self.search(root, self.prefix + '-no-match')
        expect(root).to_contain_text('没有找到匹配的笔记')
        self.page.set_viewport_size({'width': 360, 'height': 800})
        self.search(root, self.prefix)
        expect(root.locator('.notebook-card')).to_have_count(20)
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
        directory = os.getenv('GROW_NOTEBOOK_SCREENSHOT_DIR')
        if directory:
            target = Path(directory); target.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(target / 'notebook-360.png'))

    def test_failed_list_can_retry_without_losing_saved_notes(self):
        self.save('renzhi', self.prefix, self.prefix + ' 仍然保留')
        failures = {'remaining': 1}
        def fault(route):
            if failures['remaining']:
                failures['remaining'] -= 1
                route.fulfill(status=503, content_type='application/json', body='{}')
            else: route.continue_()
        self.page.route('**/api/study-notes?*', fault)
        root = self.enter()
        expect(root).to_contain_text('笔记暂时无法读取')
        root.get_by_role('button', name='重试读取笔记').click()
        self.search(root, self.prefix)
        expect(root.locator('.notebook-card')).to_have_count(1)
        expect(root.locator('.notebook-card')).to_contain_text('仍然保留')
