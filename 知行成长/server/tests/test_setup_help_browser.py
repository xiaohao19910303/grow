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
        self.page.evaluate("goTab('action-plans')");self.page.locator('#view-action-plans .gw-menu > summary').filter(has_text='工作区设置').click();self.page.get_by_role('button',name='完成与进度说明',exact=True).click();expect(dialog).to_be_visible();self.page.keyboard.press('Escape')
        self.page.evaluate("goTab('plans')");self.page.get_by_role('button',name='完成与进度说明',exact=True).click();expect(dialog).to_be_visible()
        self.page.set_viewport_size({'width':320,'height':850});self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),320)
        self.page.screenshot(path=str(self.evidence/'completion-help-mobile.png'))
        self.assertFalse(any(r['path']=='/api/ai/test' or '/generate' in r['path'] for r in self.requests))

    def test_account_menu_keyboard_mobile_escape_and_settings(self):
        self.page.wait_for_function('dataLoaded === true')
        trigger=self.page.get_by_role('button',name='账户菜单',exact=True)
        panel=self.page.locator('#userMenuPanel')
        for width in (1440,320):
            self.page.set_viewport_size({'width':width,'height':900})
            expect(trigger).to_have_attribute('aria-expanded','false');expect(panel).to_be_hidden()
            trigger.focus();self.page.keyboard.press('Enter')
            expect(trigger).to_have_attribute('aria-expanded','true')
            expect(panel.get_by_role('button',name='退出登录',exact=True)).to_be_visible()
            self.page.keyboard.press('Tab');expect(panel.get_by_role('button',name='账户设置',exact=True)).to_be_focused()
            self.page.keyboard.press('Escape');expect(panel).to_be_hidden();expect(trigger).to_be_focused()
            self.page.keyboard.press('Space');expect(panel).to_be_visible()
            panel.get_by_role('button',name='账户设置',exact=True).click()
            expect(panel).to_be_hidden();expect(self.page.locator('#view-settings')).to_be_visible()
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),width)

    def guide(self,model='test-model'):
        self.page.evaluate("goTab('settings')")
        self.page.get_by_role('button',name='开始配置引导',exact=True).click()
        expect(self.page.locator('#aiSetupStep')).to_contain_text('1/3')
        self.page.get_by_label('API Base URL',exact=True).fill('https://model.example/v1')
        self.page.get_by_role('button',name='下一步',exact=True).click()
        self.page.get_by_label('API Key',exact=True).fill('TEST_SETUP_PRIVATE_KEY')
        self.page.get_by_label('模型名称',exact=True).fill(model)
        self.page.get_by_role('button',name='下一步',exact=True).click()
        expect(self.page.locator('#aiSetupStep')).to_contain_text('3/3')

    def test_setup_save_without_model_request_and_new_browser_is_empty(self):
        self.guide();review=self.page.locator('#aiSetupReview')
        expect(review).to_contain_text('test-model');expect(review).not_to_contain_text('TEST_SETUP_PRIVATE_KEY')
        self.page.screenshot(path=str(self.evidence/'ai-setup-review-desktop.png'))
        self.page.set_viewport_size({'width':320,'height':850});review.scroll_into_view_if_needed();self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),320)
        self.page.screenshot(path=str(self.evidence/'ai-setup-review-mobile.png'))
        self.page.get_by_role('button',name='保存配置',exact=True).click();expect(self.page.locator('#apiStatus')).to_contain_text('已保存')
        self.assertFalse(any(r['path']=='/api/ai/test' or '/generate' in r['path'] for r in self.requests))
        self.page.reload();self.page.evaluate("goTab('settings')");expect(self.page.get_by_label('模型名称',exact=True)).to_have_value('test-model')
        other=self.browser.new_context();self.addCleanup(other.close);p=other.new_page();p.goto(self.base);p.evaluate('Account.ready');p.evaluate("goTab('settings')");expect(p.get_by_label('模型名称',exact=True)).to_have_value('')
        self.page.get_by_role('button',name='清除本地配置',exact=True).click();self.page.reload();self.page.evaluate("goTab('settings')");expect(self.page.get_by_label('模型名称',exact=True)).to_have_value('')

    def test_setup_validation_explicit_test_failure_retry_and_stale_response(self):
        self.page.evaluate("goTab('settings')");self.page.get_by_role('button',name='开始配置引导',exact=True).click()
        self.page.get_by_label('API Base URL',exact=True).fill('http://invalid.example')
        self.page.get_by_role('button',name='下一步',exact=True).click();expect(self.page.locator('#apiStatus')).to_contain_text('HTTPS')
        expect(self.page.locator('#aiSetupStep')).to_contain_text('1/3')
        self.page.get_by_label('API Base URL',exact=True).fill('https://model.example/v1');self.page.get_by_role('button',name='下一步',exact=True).click()
        self.page.get_by_label('API Key',exact=True).fill('TEST_SETUP_PRIVATE_KEY');self.page.get_by_label('模型名称',exact=True).fill('test-model');self.page.get_by_role('button',name='下一步',exact=True).click()
        self.context.request.post(self.base+'/fixture/setup-mode/error');self.page.locator('#apiSettingsForm').get_by_role('button',name='测试连接',exact=True).click();expect(self.page.locator('#apiStatus')).to_contain_text('连接失败')
        self.page.screenshot(path=str(self.evidence/'ai-setup-test-failure.png'))
        self.context.request.post(self.base+'/fixture/setup-mode/success');self.page.locator('#apiSettingsForm').get_by_role('button',name='测试连接',exact=True).click();expect(self.page.locator('#apiStatus')).to_contain_text('连接成功')
        expect(self.page.locator('#apiStatus')).not_to_contain_text('PRIVATE')
        self.context.request.post(self.base+'/fixture/setup-mode/slow');self.page.locator('#apiSettingsForm').get_by_role('button',name='测试连接',exact=True).click()
        self.page.get_by_role('button',name='上一步',exact=True).click();self.page.get_by_label('模型名称',exact=True).fill('changed-model')
        self.page.wait_for_timeout(1200);expect(self.page.locator('#apiStatus')).not_to_contain_text('连接成功')

        self.page.get_by_role('button',name='下一步',exact=True).click();self.page.locator('#apiSettingsForm').get_by_role('button',name='测试连接',exact=True).click()
        self.page.get_by_role('button',name='取消测试',exact=True).click();expect(self.page.locator('#apiStatus')).to_contain_text('已取消')
        self.page.wait_for_timeout(1200);expect(self.page.locator('#apiStatus')).not_to_contain_text('连接成功')

    def test_storage_denial_preserves_previous_saved_configuration(self):
        self.guide('old-model');self.page.get_by_role('button',name='保存配置',exact=True).click()
        self.guide('new-model')
        self.page.evaluate("""() => {
          const original=Storage.prototype.setItem;
          Storage.prototype.setItem=function(key,value){if(key.startsWith('zhixing-ai-config-v1:'))throw new DOMException('Synthetic storage denial');return original.call(this,key,value);};
        }""")
        self.page.get_by_role('button',name='保存配置',exact=True).click();expect(self.page.locator('#apiStatus')).to_contain_text('不允许保存')
        self.page.screenshot(path=str(self.evidence/'ai-setup-storage-denied.png'))
        self.page.reload();self.page.evaluate("goTab('settings')");expect(self.page.get_by_label('模型名称',exact=True)).to_have_value('old-model')

    def test_missing_config_entry_respects_leave_guard_and_never_replays_generation(self):
        self.page.evaluate("goTab('plans')")
        configure=self.page.locator('#view-plans').get_by_role('button',name='配置个人模型',exact=True);expect(configure).to_be_visible()
        self.page.evaluate("window.fixtureOriginalGuard=window.beforePlansLeave;window.beforePlansLeave=()=>false")
        configure.click();expect(self.page.locator('#view-settings')).not_to_be_visible()
        self.page.evaluate('window.beforePlansLeave=window.fixtureOriginalGuard')
        configure.focus();self.page.keyboard.press('Enter');expect(self.page.locator('#aiSetupStep')).to_be_focused()
        expect(self.page.locator('#aiSetupStep')).to_contain_text('1/3')
        self.page.get_by_label('API Base URL',exact=True).fill('https://model.example/v1');self.page.get_by_role('button',name='下一步',exact=True).click()
        self.page.get_by_label('API Key',exact=True).fill('TEST_SETUP_PRIVATE_KEY');self.page.get_by_label('模型名称',exact=True).fill('test-model')
        self.page.get_by_role('button',name='直接编辑全部字段',exact=True).click()
        expect(self.page.get_by_label('API Base URL',exact=True)).to_have_value('https://model.example/v1')
        expect(self.page.get_by_label('模型名称',exact=True)).to_have_value('test-model')
        self.page.get_by_role('button',name='保存配置',exact=True).click();self.page.evaluate("goTab('plans')")
        expect(configure).to_have_count(0)
        self.assertFalse(any('/generate' in r['path'] or r['path']=='/api/ai/test' for r in self.requests))
