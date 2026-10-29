"""Real Chrome acceptance of production cards, real PG facts and reminder reuse."""
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
class CoachFactsBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=subprocess.Popen([sys.executable,str(Path(__file__).with_name('serve_coach_facts_fixture.py'))],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        cls.addClassCleanup(cls.stop_fixture)
        if not select.select([cls.fixture.stdout],[],[],60)[0]:raise RuntimeError('Coach fixture startup timeout')
        line=cls.fixture.stdout.readline()
        if not line:raise RuntimeError(cls.fixture.stderr.read())
        cls.base=json.loads(line)['url'];cls.pw=sync_playwright().start();cls.addClassCleanup(cls.pw.stop)
        cls.browser=cls.pw.chromium.launch(headless=True,executable_path=os.getenv('CHROME_EXECUTABLE','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'))
        cls.addClassCleanup(cls.browser.close)
        cls.evidence=Path(os.getenv('COACH_EVIDENCE_DIR') or tempfile.mkdtemp(prefix='grow-coach-browser-'));cls.evidence.mkdir(parents=True,exist_ok=True)

    @classmethod
    def stop_fixture(cls):
        cls.fixture.terminate()
        try:cls.fixture.wait(timeout=15)
        except subprocess.TimeoutExpired:cls.fixture.kill();cls.fixture.wait(timeout=5)
        cls.fixture.stdout.close();cls.fixture.stderr.close()

    def setUp(self):
        self.context=self.browser.new_context(viewport={'width':1440,'height':1000});self.addCleanup(self.context.close)
        self.page=self.context.new_page();self.page.set_default_timeout(15000);self.errors=[];self.requests=[];self.external=[]
        self.page.on('pageerror',lambda error:self.errors.append(error.stack))
        self.page.on('request',lambda request:self.requests.append({'method':request.method,'url':request.url.removeprefix(self.base)}))
        def route(request):
            if request.request.url.startswith(self.base+'/'):request.continue_()
            else:self.external.append(request.request.url);request.abort()
        self.page.route('**/*',route)
        self.mode('activity');self.page.goto(self.base)
        expect(self.page.locator('#coachFactToday')).to_contain_text('最近7天有 1 天')

    def mode(self, value):
        result=self.context.request.post(self.base+'/fixture/coach/'+value)
        self.assertEqual(result.status,200,result.text())

    def tearDown(self):
        self.assertEqual(self.errors,[])
        self.assertEqual(self.external,[])
        self.assertFalse(any('/generate' in r['url'] or '/generations' in r['url'] for r in self.requests))
        (self.evidence/(self._testMethodName+'-network.json')).write_text(json.dumps(self.requests,ensure_ascii=False,indent=2))

    def test_auto_facts_navigation_keyboard_dismiss_and_responsive_layout(self):
        card=self.page.locator('#coachFactToday');expect(card).to_contain_text('北京时间')
        first=self.context.request.get(self.base+'/api/coach-facts').json()
        self.assertFalse(first['uses_model']);self.assertEqual(first['fact']['kind'],'activity')
        self.page.get_by_role('button',name='成长',exact=True).click()
        growth=self.page.locator('#coachFactOverview');expect(growth).to_contain_text(first['fact']['message'])
        for width in (320,768,1024,1440):
            self.page.set_viewport_size({'width':width,'height':1000})
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),width)
            expect(growth.get_by_role('button',name='今天先不显示')).to_be_visible()
        self.page.screenshot(path=str(self.evidence/'growth-desktop.png'),full_page=True)
        self.page.set_viewport_size({'width':320,'height':850});self.page.screenshot(path=str(self.evidence/'growth-mobile.png'),full_page=True)
        dismiss=growth.get_by_role('button',name='今天先不显示');dismiss.focus();self.page.keyboard.press('Enter');expect(growth).not_to_be_visible()
        self.assertTrue(self.page.locator(':focus').is_visible(), 'Dismissal must leave keyboard focus on visible content')
        self.page.reload();expect(self.page.locator('#coachFactOverview')).not_to_be_visible()
        self.page.get_by_role('button',name='今日',exact=True).first.click();expect(card).not_to_be_visible()

    def test_threshold_rules_and_failure_retry_do_not_generate_ai(self):
        for mode,expected in (('decrease','3、2、1'),('course','距今 14 天'),('predictions','准确率 80%')):
            self.mode(mode);self.page.reload();expect(self.page.locator('#coachFactToday')).to_contain_text(expected)
        self.page.screenshot(path=str(self.evidence/'prediction-fact.png'),full_page=True)
        self.page.route('**/api/coach-facts',lambda route:route.fulfill(status=503,content_type='application/json',body='{"detail":"synthetic outage"}'))
        self.page.reload();card=self.page.locator('#coachFactToday');expect(card).to_contain_text('暂未读取')
        self.assertNotIn('80%',card.inner_text())
        # Drain the initial/queued read while the outage is still active; otherwise
        # a late automatic response can remove the retry button before the click.
        self.page.evaluate('()=>window.CoachFacts.refresh(true)')
        self.page.unroute('**/api/coach-facts')
        # Recover the synthetic service on the user's click, not a racing startup
        # refresh. The real button and successful HTTP request are still exercised.
        self.page.evaluate('''()=>{
          window.__coachUserRetry=false;
          document.addEventListener('click',e=>{if(e.target.closest('#coachFactToday button')?.textContent==='重试')window.__coachUserRetry=true;},true);
          const original=window.fetch;
          window.fetch=(url,options={})=>original(url,{...options,headers:{...options.headers,'X-Coach-Fixture-Retry':window.__coachUserRetry?'1':'0'}});
        }''')
        self.page.route('**/api/coach-facts',lambda route:route.continue_() if route.request.headers.get('x-coach-fixture-retry')=='1' else route.fulfill(status=503,content_type='application/json',body='{"detail":"synthetic outage"}'))
        card.get_by_role('button',name='重试',exact=True).click();expect(card).to_contain_text('80%')

    def test_due_action_yields_coach_and_completion_restores_the_card(self):
        response=self.context.request.post(self.base+'/api/action-plans',headers={'X-Copilot-Request':'1','X-Grow-Action-Schema':'2'},data={
            'title':'先处理这件事','period':'day','completion_mode':'check','start_date':'2026-10-25','end_date':'2026-10-25','at':'11:59','reminder':True,'key':'coach-browser-due-action'})
        self.assertEqual(response.status,200,response.text())
        self.page.reload();banner=self.page.locator('#actionReminder');expect(banner).to_contain_text('先处理这件事')
        expect(self.page.locator('#coachFactToday')).not_to_be_visible()
        banner.get_by_role('button',name='完成事项',exact=True).click();expect(banner).not_to_be_visible()
        expect(self.page.locator('#coachFactToday')).to_contain_text('最近7天有 1 天')
