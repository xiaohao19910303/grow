"""Daily rhythm real-browser acceptance, no production data or network."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest
import uuid
from playwright.sync_api import sync_playwright, expect


@unittest.skipUnless(os.getenv('RUN_GITHUB_BROWSER')=='1','Opt in to isolated Chromium')
class RhythmBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=subprocess.Popen([sys.executable,str(Path(__file__).with_name('serve_rhythm_fixture.py'))],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=os.environ.copy())
        cls.addClassCleanup(cls.stop_fixture)
        if not select.select([cls.fixture.stdout],[],[],60)[0]:raise RuntimeError('Rhythm fixture startup timeout')
        line=cls.fixture.stdout.readline()
        if not line:raise RuntimeError(cls.fixture.stderr.read())
        cls.info=json.loads(line);cls.base=cls.info['url']
        cls.pw=sync_playwright().start();cls.addClassCleanup(cls.pw.stop)
        cls.browser=cls.pw.chromium.launch(headless=True,executable_path=os.getenv('CHROME_EXECUTABLE','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'))
        cls.addClassCleanup(cls.browser.close)
        cls.evidence=Path(tempfile.mkdtemp(prefix='grow-rhythm-browser-'))
        print('RHYTHM_BROWSER_EVIDENCE '+str(cls.evidence),flush=True)

    @classmethod
    def stop_fixture(cls):
        cls.fixture.terminate()
        try:cls.fixture.wait(timeout=15)
        except subprocess.TimeoutExpired:cls.fixture.kill();cls.fixture.wait(timeout=5)
        cls.fixture.stdout.close();cls.fixture.stderr.close()

    def setUp(self):
        self.context=self.browser.new_context(viewport={'width':1280,'height':960});self.addCleanup(self.context.close)
        self.page=self.context.new_page();self.page.set_default_timeout(12000);self.errors=[]
        self.page.on('pageerror',lambda e:self.errors.append(e.stack))
        self.page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(self.base+'/') else route.abort())
        self.page.goto(self.base);expect(self.page.locator('#dailyRhythm')).to_be_visible(timeout=15000)
        self.headers={'X-Copilot-Request':'1','X-Grow-Action-Schema':'2'}
        self.today=self.page.locator('#personalDate').input_value()
        self.prefix=uuid.uuid4().hex[:8]

    def tearDown(self):self.assertEqual(self.errors,[])

    def get(self,path):return self.context.request.get(self.base+'/api/action-plans'+path).json()
    def post(self,path,**body):
        result=self.context.request.post(self.base+'/api/action-plans'+path,headers=self.headers,data={'key':str(uuid.uuid4()),**body})
        self.assertEqual(result.status,200,result.text());return result.json()
    def enable(self):
        p=self.get('/rhythm/today')['preferences']
        if not p['enabled']:
            self.page.locator('#dailyRhythm').get_by_role('button',name='设置日常节奏').click()
            root=self.page.locator('#rhythmSettings');root.get_by_label('开启日常节奏').check()
            root.get_by_role('button',name='保存节奏设置').click()
            expect(root.get_by_role('button',name='保存节奏设置')).to_be_enabled()
        self.page.get_by_role('button',name='今日',exact=True).first.click()
        expect(self.page.locator('#dailyRhythm')).to_contain_text('本周已行动')
    def seed(self,**values):
        return self.post('',**(dict(title=self.prefix+'行动',period='day',completion_mode='check',start_date=self.today,end_date=self.today)|values))['plans'][0]
    def choose(self,p):
        self.page.reload();self.page.get_by_role('button',name='今日',exact=True).first.click();expect(self.page.locator('#dailyRhythm')).to_contain_text('本周已行动')
        self.page.locator('#dailyRhythm').get_by_role('button',name='更换或编辑今日一件事' if self.get('/rhythm/today')['focus'] else '选择今日一件事',exact=True).click()
        d=self.page.get_by_role('dialog');d.get_by_label('今日行动',exact=True).select_option(p['id'])
        d.get_by_role('button',name='设为今日一件事',exact=True).click();expect(d).not_to_be_visible()
        expect(self.page.locator('#dailyRhythm')).to_contain_text(p['title'])

    def test_settings_reload_initializes_form_and_preserves_unsaved_edits(self):
        self.page.get_by_role('button',name='设置',exact=True).click()
        self.page.reload()
        settings=self.page.locator('#rhythmSettings')
        expect(settings.get_by_role('button',name='保存节奏设置',exact=True)).to_be_visible()
        zone=settings.get_by_label('时区',exact=True)
        zone.fill('Europe/London')
        self.page.evaluate('()=>window.DailyRhythm.refresh()')
        expect(zone).to_have_value('Europe/London')

    def test_minimum_check_recap_reload_weekly_and_mobile(self):
        self.enable();p=self.seed();self.choose(p)
        self.page.locator('#dailyRhythm').get_by_role('button',name='今天轻一点',exact=True).click()
        d=self.page.get_by_role('dialog');d.get_by_label('这次的最小一步').fill('只列一个问题');d.get_by_role('button',name='确认',exact=True).click();expect(d).not_to_be_visible()
        self.page.locator('#dailyRhythm').get_by_role('button',name='确认做过最小一步',exact=True).click()
        self.page.get_by_role('dialog').get_by_role('button',name='我已做过这一步',exact=True).click()
        d=self.page.get_by_role('dialog');expect(d).to_contain_text('行动已保存')
        d.get_by_label('一句收获、卡点或结果').fill('问题更清楚了');d.get_by_label('下一步（可选）').fill('明天核对一条证据')
        d.get_by_role('button',name='保存一句总结',exact=True).click();expect(d).not_to_be_visible()
        self.page.reload();expect(self.page.locator('#dailyRhythm')).to_contain_text('问题更清楚了')
        current=self.get('/rhythm/today');r=current['records'][-1]
        self.assertEqual(r['actual_minutes'],0);self.assertEqual(next(p for p in self.get('')['plans'] if p['id']==r['plan_id'])['status'],'active')
        self.page.locator('#dailyRhythm').get_by_role('button',name='回看本周成果').click()
        expect(self.page.locator('#weeklyRhythm')).to_contain_text('问题更清楚了')
        self.page.locator('#weeklyRhythm').get_by_role('button',name='选择成果与一项调整' if not self.get('/rhythm/weeks/'+self.week())['card'] else '重新确认本周成果').click()
        d=self.page.get_by_role('dialog');d.get_by_label('下一周的一项调整（可选）').fill('开始时先看证据');d.get_by_label('关联今天或未来的行动（可选）').select_option(p['id']);d.get_by_role('checkbox').first.check();d.get_by_role('button',name='确认本周成果',exact=True).click();expect(d).not_to_be_visible()
        # Clearing a previously saved link must survive closing and reopening a draft.
        self.page.locator('#weeklyRhythm').get_by_role('button',name='重新确认本周成果').click()
        d=self.page.get_by_role('dialog');d.get_by_label('关联今天或未来的行动（可选）').select_option('')
        d.get_by_role('button',name='稍后回看',exact=True).click();expect(d).not_to_be_visible()
        self.page.locator('#weeklyRhythm').get_by_role('button',name='重新确认本周成果').click()
        d=self.page.get_by_role('dialog');expect(d.get_by_label('关联今天或未来的行动（可选）')).to_have_value('')
        d.get_by_role('button',name='确认本周成果',exact=True).click();expect(d).not_to_be_visible()
        self.assertIsNone(self.get('/rhythm/weeks/'+self.week())['card']['adjustment_target_plan_id'])
        expect(self.page.locator('#weeklyRhythm')).to_contain_text('开始时先看证据')
        self.page.set_viewport_size({'width':375,'height':812});self.page.screenshot(path=str(self.evidence/'weekly-mobile.png'),full_page=True)
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),375)

    def week(self):
        from datetime import date,timedelta
        day=date.fromisoformat(self.today);return str(day-timedelta(days=day.weekday()))

    def test_time_finish_fields_and_historical_read_only(self):
        self.enable();p=self.seed(completion_mode='time',target_minutes=20,minimum_minutes=5);self.choose(p)
        self.page.locator('#dailyRhythm').get_by_role('button',name='开始这次行动',exact=True).click()
        bar=self.page.locator('#actionExecution');expect(bar).to_contain_text(p['title'])
        bar.locator('summary').click();bar.get_by_role('button',name='记录完成',exact=True).click();d=self.page.get_by_role('dialog');d.get_by_label('实际执行分钟').fill('2');d.get_by_label('收获或中断原因（可选）').fill('读了两分钟');d.get_by_label('下一步（可选）').fill('接着看例子');d.get_by_role('button',name='确认并记录',exact=True).click();expect(d).not_to_be_visible()
        self.page.get_by_role('button',name='今日',exact=True).first.click()
        expect(self.page.locator('#dailyRhythm')).to_contain_text('读了两分钟')
        current=self.get('/rhythm/today');self.assertIsNone(current['execution'])
        self.assertTrue(any(r.get('recap_revision')==1 and r.get('note')=='读了两分钟' for r in current['records']))
        self.page.locator('#personalDate').fill('2026-01-01');self.page.locator('#personalDate').dispatch_event('change')
        expect(self.page.locator('#dailyRhythm')).to_contain_text('主任务历史只读')
        expect(self.page.locator('#dailyRhythm').get_by_role('button',name='选择今日一件事',exact=True)).to_have_count(0)
        self.page.screenshot(path=str(self.evidence/'history-desktop.png'),full_page=True)

    def test_created_focus_lost_response_retry_does_not_create_twice(self):
        self.enable()
        label='更换或编辑今日一件事' if self.get('/rhythm/today')['focus'] else '选择今日一件事'
        self.page.locator('#dailyRhythm').get_by_role('button',name=label,exact=True).click()
        d=self.page.get_by_role('dialog');d.get_by_label('今日行动',exact=True).select_option('new')
        title=self.prefix+'新建焦点';d.get_by_label('新待办名称').fill(title)
        dropped=[]
        def response_loss(route):
            if route.request.method=='POST' and not dropped:
                response=route.fetch();self.assertEqual(response.status,200);dropped.append(True)
                route.fulfill(status=503,content_type='application/json',body='{"detail":"模拟提交成功后响应丢失"}')
            else:route.continue_()
        self.page.route('**/api/action-plans/rhythm/focus',response_loss)
        d.get_by_role('button',name='设为今日一件事',exact=True).click()
        expect(d).to_contain_text('行动已创建，尚未设为今日一件事')
        d.get_by_role('button',name='设为今日一件事',exact=True).click();expect(d).not_to_be_visible()
        self.assertEqual(sum(p['title']==title for p in self.get('')['plans']),1)
        expect(self.page.locator('#dailyRhythm')).to_contain_text(title)

    def test_recap_pending_recovery_preserves_edits_after_unsent_request(self):
        self.enable();p=self.seed();self.choose(p)
        record=self.post('/'+p['id']+'/operations',revision=p['revision'],action='complete')['execution']
        self.page.evaluate('(id)=>window.DailyRhythm.recap(id)',record['id'])
        d=self.page.get_by_role('dialog');note=d.get_by_label('一句收获、卡点或结果')
        note.fill('提交前的原文')
        dropped=[]
        def unsent(route):
            if route.request.method=='POST' and not dropped:
                dropped.append(True);route.abort()
            else:route.continue_()
        self.page.route('**/api/action-plans/rhythm/executions/*/recap',unsent)
        d.get_by_role('button',name='保存一句总结',exact=True).click()
        expect(d.get_by_role('button',name='恢复上次提交',exact=True)).to_be_visible()
        note.fill('中断后继续修改的原文')
        d.get_by_role('button',name='保存一句总结',exact=True).click()
        expect(d).to_contain_text('上次提交结果尚未确认')
        # Keep recovery in flight long enough to distinguish the old editor from
        # the replacement editor opened with the committed recap revision.
        self.page.evaluate('''() => {
            const original = window.fetch;
            window.fetch = async (input, options = {}) => {
                if (String(input).endsWith('/recap') && options.method === 'POST')
                    await new Promise(resolve => setTimeout(resolve, 300));
                return original(input, options);
            };
        }''')
        old_dialog=d.element_handle()
        d.get_by_role('button',name='恢复上次提交',exact=True).click()
        self.page.wait_for_function('(element) => !element.isConnected',arg=old_dialog)
        d=self.page.get_by_role('dialog')
        expect(d).to_be_visible()
        expect(d).to_contain_text('已保存的最新总结：提交前的原文')
        expect(d.get_by_label('一句收获、卡点或结果')).to_have_value('中断后继续修改的原文')
        d.get_by_role('button',name='保存一句总结',exact=True).click();expect(d).not_to_be_visible()
        saved=self.get('/rhythm/executions/'+record['id'])['execution']
        self.assertEqual(saved['note'],'中断后继续修改的原文')
        self.assertEqual(saved['recap_revision'],2)

    def test_source_completion_article_and_course_recap_uses_receipt(self):
        self.enable()
        for kind,target in [('article',dict(kind='article',course=self.info['article'])),
                            ('plan',dict(kind='plan',plan_id=self.info['course_plan'],lesson_no=1))]:
            p=self.post('/schedules',title=self.prefix+kind,date=self.today,target=target)['plan']
            self.choose(p)
            row=self.page.locator('#agendaList [data-plan-id="'+p['id']+'"]')
            row.get_by_role('button',name='打开文章' if kind=='article' else '打开课程',exact=True).click()
            reader=self.page.locator('#view-reading' if kind=='article' else '#dailyReader')
            suffix='/personal' if kind=='article' else '/feedback'
            with self.page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith(suffix)) as receipt:
                reader.get_by_role('button',name='确认本次读完' if kind=='article' else '本人确认学完',exact=True).click()
            execution_id=receipt.value.json()['action_completion_receipts'][0]['execution_id']
            d=self.page.get_by_role('dialog');expect(d).to_contain_text('本次完成已保存')
            d.get_by_role('button',name='为这次完成留一句总结').click()
            d=self.page.get_by_role('dialog');d.get_by_label('一句收获、卡点或结果').fill('来源总结 '+kind)
            d.get_by_role('button',name='保存一句总结',exact=True).click();expect(d).not_to_be_visible()
            r=self.get('/rhythm/executions/'+execution_id)['execution']
            self.assertEqual(r['note'],'来源总结 '+kind)
            self.assertEqual(sum(r['id']==execution_id for r in self.get('/records')['records']),1)
