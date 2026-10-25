"""Chrome acceptance of opt-in adoption, publication, C2 receipt and stage progress."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest
from playwright.sync_api import sync_playwright, expect


@unittest.skipUnless(os.getenv('RUN_GITHUB_BROWSER') == '1', 'Opt in to isolated Chrome')
class LearningActionsBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=subprocess.Popen([sys.executable,str(Path(__file__).with_name('serve_learning_actions_fixture.py'))],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        cls.addClassCleanup(cls.stop_fixture)
        if not select.select([cls.fixture.stdout],[],[],60)[0]:raise RuntimeError('Learning fixture startup timeout')
        line=cls.fixture.stdout.readline()
        if not line:raise RuntimeError(cls.fixture.stderr.read())
        cls.base=json.loads(line)['url'];cls.pw=sync_playwright().start();cls.addClassCleanup(cls.pw.stop)
        cls.browser=cls.pw.chromium.launch(headless=True,executable_path=os.getenv('CHROME_EXECUTABLE','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'));cls.addClassCleanup(cls.browser.close)
        cls.evidence=Path(os.getenv('LEARNING_ACTIONS_EVIDENCE_DIR') or tempfile.mkdtemp(prefix='grow-learning-browser-'));cls.evidence.mkdir(parents=True,exist_ok=True)

    @classmethod
    def stop_fixture(cls):
        cls.fixture.terminate()
        try:cls.fixture.wait(timeout=15)
        except subprocess.TimeoutExpired:cls.fixture.kill();cls.fixture.wait(timeout=5)
        cls.fixture.stdout.close();cls.fixture.stderr.close()

    def test_adopt_publish_arrange_complete_and_retry_read(self):
        context=self.browser.new_context(viewport={'width':1440,'height':1000});self.addCleanup(context.close)
        page=context.new_page();page.set_default_timeout(15000);errors=[];requests=[];external=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('request',lambda request:requests.append({'method':request.method,'path':request.url.removeprefix(self.base)}))
        def route(request):
            if request.request.url.startswith(self.base+'/'):request.continue_()
            else:external.append(request.request.url);request.abort()
        page.route('**/*',route)
        draft=context.request.post(self.base+'/fixture/learning-draft').json()
        page.goto(self.base);page.evaluate("Account.ready");page.evaluate("goTab('plans')");expect(page.locator('#view-plans')).to_contain_text('已保存草稿');page.evaluate('(id)=>{history.replaceState(null,"","#plans/draft/"+id);enterPlans();}',draft['id'])
        expect(page.get_by_label('同时关联到行动（不指定学习日期）')).to_be_checked()
        page.get_by_label('已阅读这份草稿，确认将其正式保存').check()
        adopt=page.get_by_role('button',name='采用这份规划',exact=True);adopt.focus();page.keyboard.press('Enter')
        card=page.locator('#view-plans .learning-plan-card');expect(card).to_contain_text('已学完 0/2 课')
        pid=card.get_attribute('data-learning-plan');expect(card).to_contain_text('尚未发布')
        course=context.request.post(self.base+'/fixture/learning-course/'+pid).json()
        page.evaluate('(id)=>{history.replaceState(null,"","#plans/draft/"+id);enterPlans();}',course['id'])
        page.get_by_label('已阅读这份草稿，确认将其正式保存').check();page.get_by_role('button',name='保存正式课程',exact=True).click()
        expect(card).to_contain_text('已发布 1 课');card.get_by_role('button',name='查看第 1 课行动',exact=True).click()
        row=page.locator('#view-action-plans [data-plan-id]');expect(row).to_have_count(1)
        expect(row).to_contain_text('未安排');row.get_by_role('button',name='安排今日并开始',exact=True).click()
        page.get_by_role('button',name='本人确认学完',exact=True).click()
        expect(page.locator('#dailyReader')).to_contain_text('本课已完成')
        page.evaluate("goTab('action-plans')")
        progress=page.locator('#view-action-plans .learning-plan-card');expect(progress).to_contain_text('已学完 1/2 课')
        expect(progress.get_by_role('progressbar',name='整体学习进度')).to_have_attribute('value','50')
        expect(progress.get_by_role('progressbar',name='阶段 1：基础学习进度')).to_have_attribute('value','100')
        expect(progress.get_by_role('progressbar',name='阶段 2：应用学习进度')).to_have_attribute('value','0')
        records=context.request.get(self.base+'/api/action-plans/records').json();self.assertEqual(records['total'],1)
        page.reload();page.evaluate("goTab('action-plans')");expect(progress).to_contain_text('已学完 1/2 课')
        page.screenshot(path=str(self.evidence/'stage-progress-desktop.png'),full_page=True)
        page.set_viewport_size({'width':320,'height':850});expect(progress).to_be_visible()
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),320)
        page.screenshot(path=str(self.evidence/'stage-progress-mobile.png'),full_page=True)
        page.route('**/api/plan-actions',lambda route:route.fulfill(status=503,content_type='application/json',body='{"message":"合成读取失败"}'))
        page.evaluate('PlanActions.refresh()');expect(page.locator('#view-action-plans .learning-plan-actions')).to_contain_text('合成读取失败')
        page.unroute('**/api/plan-actions');page.get_by_role('button',name='重试读取课程进度',exact=True).click();expect(progress).to_contain_text('已学完 1/2 课')
        self.assertEqual(errors,[]);self.assertEqual(external,[])
        self.assertFalse(any('/generate' in r['path'] or '/generations' in r['path'] for r in requests))
        (self.evidence/'network.json').write_text(json.dumps(requests,ensure_ascii=False,indent=2))

    def test_partial_success_retry_and_adoption_opt_out(self):
        context=self.browser.new_context(viewport={'width':1100,'height':900});self.addCleanup(context.close)
        page=context.new_page();page.set_default_timeout(15000)
        page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(self.base+'/') else route.abort())
        page.goto(self.base);page.evaluate('Account.ready');page.evaluate("goTab('plans')")
        expect(page.locator('#view-plans')).to_contain_text('正式课程保存在 GitHub')
        draft=context.request.post(self.base+'/fixture/learning-draft').json()
        page.evaluate('(id)=>{history.replaceState(null,"","#plans/draft/"+id);enterPlans();}',draft['id'])
        page.get_by_label('已阅读这份草稿，确认将其正式保存').check()
        context.request.post(self.base+'/fixture/fail-next-learning-link')
        page.get_by_role('button',name='采用这份规划',exact=True).click()
        expect(page.locator('#view-plans')).to_contain_text('正式内容已保存，关联行动尚未同步')
        card=page.locator('#view-plans .learning-plan-card');pid=card.get_attribute('data-learning-plan')
        expect(card.get_by_role('button',name='关联到行动',exact=True)).to_be_visible()
        page.screenshot(path=str(self.evidence/'partial-success-retry.png'),full_page=True)
        card.get_by_role('button',name='关联到行动',exact=True).click()
        expect(card.get_by_role('button',name='同步已发布课程到行动',exact=True)).to_be_visible()
        self.assertTrue(context.request.get(self.base+'/api/plans/'+pid+'/actions').json()['linked'])
        page.get_by_role('button',name='返回列表',exact=True).click()
        draft=context.request.post(self.base+'/fixture/learning-draft').json()
        page.evaluate('(id)=>{history.replaceState(null,"","#plans/draft/"+id);enterPlans();}',draft['id'])
        page.get_by_label('已阅读这份草稿，确认将其正式保存').check()
        page.get_by_label('同时关联到行动（不指定学习日期）').uncheck()
        page.get_by_role('button',name='采用这份规划',exact=True).click()
        expect(card.get_by_role('button',name='关联到行动',exact=True)).to_be_visible()
        pid=card.get_attribute('data-learning-plan')
        self.assertFalse(context.request.get(self.base+'/api/plans/'+pid+'/actions').json()['linked'])
