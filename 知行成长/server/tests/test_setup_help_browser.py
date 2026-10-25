"""Production UI acceptance for completion semantics and personal setup."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest
from playwright.sync_api import sync_playwright,expect

@unittest.skipUnless(os.getenv('RUN_GITHUB_BROWSER')=='1','Opt in to isolated Chrome')
class SetupHelpBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=subprocess.Popen([sys.executable,str(Path(__file__).with_name('serve_setup_help_fixture.py'))],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True);cls.addClassCleanup(cls.stop_fixture)
        if not select.select([cls.fixture.stdout],[],[],60)[0]:raise RuntimeError('Settings fixture startup timeout')
        line=cls.fixture.stdout.readline()
        if not line:raise RuntimeError(cls.fixture.stderr.read())
        cls.base=json.loads(line)['url'];cls.pw=sync_playwright().start();cls.addClassCleanup(cls.pw.stop)
        cls.browser=cls.pw.chromium.launch(headless=True,executable_path=os.getenv('CHROME_EXECUTABLE','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'));cls.addClassCleanup(cls.browser.close)
        cls.evidence=Path(os.getenv('SETUP_HELP_EVIDENCE_DIR') or tempfile.mkdtemp(prefix='grow-setup-browser-'));cls.evidence.mkdir(parents=True,exist_ok=True)
    @classmethod
    def stop_fixture(cls):
        cls.fixture.terminate()
        try:cls.fixture.wait(timeout=15)
        except subprocess.TimeoutExpired:cls.fixture.kill();cls.fixture.wait(timeout=5)
        cls.fixture.stdout.close();cls.fixture.stderr.close()
    def setUp(self):
        self.context=self.browser.new_context(viewport={'width':1440,'height':1000});self.addCleanup(self.context.close)
        self.page=self.context.new_page();self.page.set_default_timeout(12000);self.errors=[];self.external=[];self.requests=[]
        self.page.on('pageerror',lambda error:self.errors.append(str(error)))
        self.page.on('request',lambda request:self.requests.append({'method':request.method,'path':request.url.removeprefix(self.base)}))
        def route(request):
            if request.request.url.startswith(self.base+'/'):request.continue_()
            else:self.external.append(request.request.url);request.abort()
        self.page.route('**/*',route);self.page.goto(self.base);self.page.evaluate('Account.ready')
    def tearDown(self):
        self.assertEqual(self.errors,[]);self.assertEqual(self.external,[])
        (self.evidence/(self._testMethodName+'-network.json')).write_text(json.dumps(self.requests,ensure_ascii=False,indent=2))
    def test_completion_help_keyboard_entry_points_and_mobile(self):
        self.page.evaluate("goTab('settings')")
        button=self.page.get_by_role('button',name='完成与进度说明',exact=True);button.focus();self.page.keyboard.press('Enter')
        dialog=self.page.get_by_role('dialog',name='完成与进度说明');expect(dialog).to_be_visible()
        for text in ('计时行动','内容行动','勾选待办','起步','未安排','未发布','不相加'):expect(dialog).to_contain_text(text)
        self.page.screenshot(path=str(self.evidence/'completion-help-desktop.png'))
        self.page.keyboard.press('Escape');expect(dialog).not_to_be_visible();expect(button).to_be_focused()
        self.page.evaluate("goTab('action-plans')");self.page.get_by_role('button',name='完成与进度说明',exact=True).click();expect(dialog).to_be_visible();self.page.keyboard.press('Escape')
        self.page.evaluate("goTab('plans')");self.page.get_by_role('button',name='完成与进度说明',exact=True).click();expect(dialog).to_be_visible()
        self.page.set_viewport_size({'width':320,'height':850});self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),320)
        self.page.screenshot(path=str(self.evidence/'completion-help-mobile.png'))
        self.assertFalse(any(r['path']=='/api/ai/test' or '/generate' in r['path'] for r in self.requests))
