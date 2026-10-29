"""Real Chromium learning/practice recovery and responsive interaction."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest
from playwright.sync_api import sync_playwright, expect


@unittest.skipUnless(os.getenv('RUN_GITHUB_BROWSER') == '1', 'Explicit isolated browser opt-in')
class LearningPracticeBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proc = subprocess.Popen([sys.executable, str(Path(__file__).with_name('serve_learning_practice_fixture.py'))], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        cls.addClassCleanup(cls.stop)
        if not select.select([cls.proc.stdout], [], [], 60)[0]:
            raise RuntimeError('Practice browser fixture startup timeout')
        line = cls.proc.stdout.readline()
        if not line:
            raise RuntimeError(cls.proc.stderr.read())
        cls.fixture = json.loads(line)
        cls.base = cls.fixture['url']
        cls.pw = sync_playwright().start()
        cls.addClassCleanup(cls.pw.stop)
        cls.browser = cls.pw.chromium.launch(headless=True, executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
        cls.addClassCleanup(cls.browser.close)

    @classmethod
    def stop(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
            cls.proc.wait(timeout=5)
        cls.proc.stdout.close()
        cls.proc.stderr.close()

    def test_course_practice_loss_reload_feedback_and_mobile_layout(self):
        context = self.browser.new_context(viewport={'width': 1440, 'height': 1000})
        self.addCleanup(context.close)
        page = context.new_page()
        page.set_default_timeout(15000)
        errors, external = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def local_only(route):
            if route.request.url.startswith(self.base + '/'):
                route.continue_()
            else:
                external.append(route.request.url)
                route.abort()
        page.route('**/*', local_only)
        page.goto(self.base + '/#mobile/learn/' + self.fixture['lesson_id'])
        summary = page.get_by_text('学后用 · 实践与反馈', exact=True)
        expect(summary).to_be_visible()
        summary.click()
        title = page.get_by_label('实践准备做什么')
        expect(title).to_be_visible()
        title.fill('Use an idea in a real report')
        context.request.post(self.base + '/fixture/drop-next')
        page.get_by_role('button', name='确认创建实践', exact=True).click()
        expect(title).to_be_disabled()
        expect(page.get_by_text('保存已提交，隔离验收模拟响应丢失。 输入已保留。', exact=True)).to_be_visible()
        page.reload()
        expect(summary).to_be_visible()
        summary.click()
        expect(title).to_have_value('Use an idea in a real report')
        expect(title).to_be_disabled()
        page.get_by_role('button', name='重试原实践提交', exact=True).click()
        expect(page.locator('[data-practice-id]')).to_have_count(1)
        expect(title).to_have_value('')
        snapshot = context.request.get(self.base + '/api/action-plans/practices').json()
        self.assertEqual(len(snapshot['practices']), 1)
        self.assertEqual(context.request.get(self.base + '/api/action-plans/records').json()['total'], 0)
        page.get_by_role('button', name='记录应用结果', exact=True).click()
        page.get_by_label('实际结果', exact=True).fill('Tried it; colleague feedback pending')
        page.route('**/api/action-plans', lambda route: route.fulfill(status=503,content_type='application/json',body='{"message":"Synthetic refresh failure"}'))
        page.get_by_role('button', name='保存应用反馈', exact=True).click()
        expect(page.get_by_text('已保存，暂时无法刷新。可重新读取，切勿再次创建。',exact=True)).to_be_visible()
        expect(page.get_by_role('button',name='保存应用反馈',exact=True)).to_have_count(0)
        page.unroute('**/api/action-plans')
        page.get_by_role('button',name='重新读取已保存实践',exact=True).click()
        expect(page.get_by_text('Tried it; colleague feedback pending', exact=True)).to_be_visible()
        practice = context.request.get(self.base + '/api/action-plans/practices').json()['practices'][0]
        self.assertEqual(practice['status'], 'active')
        self.assertEqual(len(practice['practice_feedback']), 1)
        evidence = Path(os.getenv('PRACTICE_EVIDENCE_DIR') or tempfile.mkdtemp(prefix='practice-browser-evidence-'))
        evidence.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(evidence / 'practice-desktop.png'), full_page=True)
        page.set_viewport_size({'width': 375, 'height': 850})
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 375)
        page.screenshot(path=str(evidence / 'practice-mobile.png'), full_page=True)
        self.assertEqual(errors, [])
        self.assertEqual(external, [])
