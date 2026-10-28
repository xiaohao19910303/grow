"""Reproducible Chrome P0 acceptance against disposable local HTTP fixtures."""
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

EVIDENCE=Path(os.environ['TEST_ARTIFACTS_DIR'])/'action-p0' if os.getenv('TEST_ARTIFACTS_DIR') else Path(__file__).resolve().parents[3]/'openspec/changes/action-plans-p0-clarity/evidence'


@unittest.skipUnless(os.getenv('RUN_GITHUB_BROWSER')=='1','Opt in to isolated real Chrome')
class P0BrowserAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=subprocess.Popen([sys.executable,str(Path(__file__).with_name('serve_daily_arrangements_fixture.py'))],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=os.environ.copy())
        cls.addClassCleanup(cls.stop_fixture)
        if not select.select([cls.fixture.stdout],[],[],60)[0]:raise RuntimeError('Fixture startup timed out')
        line=cls.fixture.stdout.readline()
        if not line:raise RuntimeError(cls.fixture.stderr.read())
        cls.info=json.loads(line);cls.base=cls.info['url']
        cls.playwright=sync_playwright().start();cls.addClassCleanup(cls.playwright.stop)
        cls.browser=cls.playwright.chromium.launch(headless=True,executable_path=os.getenv('CHROME_EXECUTABLE','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'))
        cls.addClassCleanup(cls.browser.close)
        EVIDENCE.mkdir(parents=True,exist_ok=True)

    @classmethod
    def stop_fixture(cls):
        cls.fixture.terminate()
        try:cls.fixture.wait(timeout=10)
        except subprocess.TimeoutExpired:cls.fixture.kill();cls.fixture.wait(timeout=5)
        cls.fixture.stdout.close();cls.fixture.stderr.close()

    def setUp(self):
        self.context=self.browser.new_context(viewport={'width':1280,'height':960})
        self.addCleanup(self.context.close)
        self.page=self.context.new_page();self.page.set_default_timeout(10000);self.errors=[]
        self.page.on('pageerror',lambda error:self.errors.append(error.stack))
        self.page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(self.base+'/') else route.abort())
        self.page.goto(self.base)
        expect(self.page.locator('#agendaList')).not_to_contain_text('正在读取安排')
        self.prefix=uuid.uuid4().hex[:8]

    def tearDown(self):self.assertEqual(self.errors,[])

    def quick(self):
        self.page.locator('#view-personal .day-actions').get_by_role('button',name='添加行动',exact=True).click()
        return self.page.get_by_role('dialog')

    def plans(self):return self.context.request.get(self.base+'/api/action-plans').json()['plans']

    def seed(self,title,**values):
        today=self.page.locator('#personalDate').input_value()
        response=self.context.request.post(self.base+'/api/action-plans',headers={'X-Copilot-Request':'1','X-Grow-Action-Schema':'2'},
            data=dict(title=title,period='day',completion_mode='check',start_date=today,end_date=today,key=str(uuid.uuid4()))|values)
        self.assertEqual(response.status,200,response.text());return response.json()['plans'][0]

    def operation(self,p,action,**values):
        response=self.context.request.post(self.base+'/api/action-plans/'+p['id']+'/operations',
            headers={'X-Copilot-Request':'1','X-Grow-Action-Schema':'2'},
            data={'revision':p['revision'],'action':action,'key':str(uuid.uuid4()),**values})
        self.assertEqual(response.status,200,response.text());return response.json()

    def finish(self,minutes,interrupted=False):
        bar=self.page.locator('#actionExecution')
        if bar.locator('details').get_attribute('open') is None:bar.locator('summary').click()
        bar.get_by_role('button',name='中断并保留记录' if interrupted else '记录完成',exact=True).click()
        d=self.page.get_by_role('dialog');d.get_by_label('实际执行分钟').fill(str(minutes))
        d.get_by_role('button',name='保存中断' if interrupted else '确认并记录',exact=True).click();expect(d).to_have_count(0)

    def test_first_create_waits_for_initial_action_capabilities(self):
        delayed=[]
        def hold(route):delayed.append(route)
        # A fresh page starts with no action snapshot. Click while the GET is delayed.
        self.page.route('**/api/action-plans',hold)
        self.page.reload(wait_until='domcontentloaded')
        d=self.quick()
        expect(d).to_have_count(0)
        self.assertEqual(len(delayed),1)
        delayed[0].continue_()
        expect(d.get_by_label('做什么',exact=True)).to_be_focused()
        self.page.unroute('**/api/action-plans',hold)
        self.page.keyboard.press('Escape')

    def test_F03_F04_F06_F07_F10_conditional_fields_keyboard_and_errors(self):
        d=self.quick();name=d.get_by_label('做什么',exact=True)
        expect(name).to_be_focused();name.fill(self.prefix+'条件字段')
        mode=d.get_by_label('怎样算完成');expect(d.get_by_label('标准分钟',exact=True)).to_be_hidden()
        mode.select_option('time');minutes=d.get_by_label('标准分钟',exact=True);expect(minutes).to_be_visible()
        d.get_by_text('更多设置',exact=True).click()
        for value in ('0','-1','1441','1.5'):
            minutes.fill(value);self.assertFalse(minutes.evaluate('(e)=>e.checkValidity()'))
        minutes.fill('1');expect(d.get_by_label('起步分钟（留空关闭）')).to_have_value('1')
        minutes.fill('20');d.get_by_label('起步分钟（留空关闭）').fill('')
        d.get_by_label('计划时区').fill('bad/zone')
        d.get_by_role('button',name='加入今日',exact=True).click()
        expect(d.get_by_role('alert')).to_contain_text('请检查填写字段')
        expect(name).to_have_value(self.prefix+'条件字段')
        d.get_by_label('计划时区').fill('Asia/Shanghai')
        d.get_by_label('到时提醒（网页打开时）').check()
        d.get_by_role('button',name='加入今日',exact=True).click()
        expect(d.get_by_role('alert')).to_contain_text('请检查填写字段')
        d.get_by_label('到时提醒（网页打开时）').uncheck()
        mode.select_option('content');self.assertFalse(d.get_by_label('对应内容').evaluate('(e)=>e.checkValidity()'))
        mode.select_option('check');expect(minutes).to_be_hidden();expect(d.get_by_label('对应内容')).to_be_hidden()
        name.fill(self.prefix+'键盘完成');self.page.keyboard.press('Enter');expect(d).to_have_count(0)
        saved=next(p for p in self.plans() if p['title']==self.prefix+'键盘完成')
        self.assertIsNone(saved['target']);self.assertIsNone(saved['target_minutes']);self.assertIsNone(saved['minimum_minutes'])
        self.assertIsNone(saved['at']);self.assertFalse(saved['reminder'])
        d=self.quick();d.get_by_label('做什么',exact=True).fill(self.prefix+'键盘草稿');self.page.keyboard.press('Escape')
        expect(d).to_have_count(0)
        self.assertEqual(self.page.locator(':focus').text_content(),'添加行动')
        d=self.quick();expect(d.get_by_label('做什么',exact=True)).to_have_value(self.prefix+'键盘草稿')
        for width in (320,390,768,1024,1440):
            self.page.set_viewport_size({'width':width,'height':960})
            self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth>innerWidth'))
            self.assertFalse(d.evaluate('(e)=>e.scrollWidth>e.clientWidth'))
        d.screenshot(path=str(EVIDENCE/'05-closeout-keyboard-draft.png'));self.page.keyboard.press('Escape')

    def test_F08_saved_post_failed_refresh_and_R03_R04_original_key_recovery(self):
        d=self.quick();title=self.prefix+'已保存刷新失败';d.get_by_label('做什么',exact=True).fill(title)
        failed=[]
        def fail_refresh(route):
            if route.request.method=='GET':failed.append(True);route.abort()
            else:route.continue_()
        self.page.route(self.base+'/api/action-plans',fail_refresh)
        with self.page.expect_response(lambda r:r.url==self.base+'/api/action-plans' and r.request.method=='POST') as saved:
            d.get_by_role('button',name='加入今日',exact=True).click()
        self.assertEqual(saved.value.status,200)
        expect(d).to_have_count(0)
        expect(self.page.locator('.toast').last).to_contain_text('已保存，列表暂未刷新')
        self.assertTrue(failed);self.assertEqual(sum(p['title']==title for p in self.plans()),1)
        self.page.unroute(self.base+'/api/action-plans',fail_refresh)
        d=self.quick();expect(d.get_by_label('做什么',exact=True)).to_have_value('')
        self.page.keyboard.press('Escape')
        d=self.quick();old=self.prefix+'失联原提交';new=self.prefix+'后续新输入'
        d.get_by_label('做什么',exact=True).fill(old)
        def lose_response(route):
            if route.request.method=='POST':self.assertEqual(route.fetch().status,200);route.abort()
            else:route.continue_()
        self.page.route(self.base+'/api/action-plans',lose_response)
        d.get_by_role('button',name='加入今日',exact=True).click()
        expect(d.get_by_role('alert')).not_to_have_text('正在保存…')
        d.get_by_label('做什么',exact=True).fill(new)
        d.get_by_role('button',name='加入今日',exact=True).click()
        expect(d.get_by_role('alert')).to_contain_text('上次提交尚未确认')
        self.page.unroute(self.base+'/api/action-plans',lose_response)
        d.get_by_role('button',name='核对上次提交').click();expect(d).to_have_count(0)
        self.assertEqual(sum(p['title']==old for p in self.plans()),1);self.assertEqual(sum(p['title']==new for p in self.plans()),0)
        d=self.quick();expect(d.get_by_label('做什么',exact=True)).to_have_value(new)
        d.screenshot(path=str(EVIDENCE/'06-closeout-lost-response-draft.png'))

    def test_S06_S07_past_running_paused_and_partial_arrange_feedback(self):
        from datetime import date,timedelta
        today=date.fromisoformat(self.page.locator('#personalDate').input_value());past=(today-timedelta(days=1)).isoformat()
        paused=self.seed(self.prefix+'过期暂停',start_date=past,end_date=past)
        running=self.seed(self.prefix+'昨日运行',completion_mode='time',start_date=past,end_date=past)
        undated=self.seed(self.prefix+'未安排冲突',completion_mode='time',start_date=None,end_date=None)
        h={'X-Copilot-Request':'1','X-Grow-Action-Schema':'2'}
        for p,action in ((paused,'pause'),(running,'start')):
            response=self.context.request.post(self.base+'/api/action-plans/'+p['id']+'/operations',headers=h,
                data={'revision':p['revision'],'action':action,'key':str(uuid.uuid4())});self.assertEqual(response.status,200)
        self.page.reload();self.page.get_by_role('button',name='查看日程',exact=True).click()
        schedule=self.page.locator('#view-action-schedule');schedule.get_by_role('button',name='待调整',exact=True).click()
        expect(schedule).to_contain_text(self.prefix+'过期暂停');expect(schedule).not_to_contain_text(self.prefix+'昨日运行')
        expect(schedule.locator('[data-plan-id="'+paused['id']+'"]')).to_contain_text('已暂停')
        schedule.get_by_role('button',name='未安排',exact=True).click()
        schedule.locator('[data-plan-id="'+undated['id']+'"]').get_by_role('button',name='安排今日并开始').click()
        expect(self.page.locator('.toast').last).to_contain_text('已安排今日，但尚未开始或完成')
        saved=next(p for p in self.plans() if p['id']==undated['id']);self.assertEqual(saved['start_date'],today.isoformat())
        self.page.screenshot(path=str(EVIDENCE/'07-closeout-arrange-partial-success.png'))
        execution=self.context.request.get(self.base+'/api/action-plans').json()['execution']
        current=next(p for p in self.plans() if p['id']==running['id'])
        self.context.request.post(self.base+'/api/action-plans/'+running['id']+'/operations',headers=h,
            data={'revision':current['revision'],'action':'finish','execution_id':execution['id'],'actual_minutes':0,'outcome':'interrupted','key':str(uuid.uuid4())})

    def test_T01_T03_K01_A05_timer_check_copy_and_stale_tabs(self):
        p=self.seed(self.prefix+'累计计时',completion_mode='time')
        self.page.reload();row=self.page.locator('#agendaList [data-plan-id="'+p['id']+'"]')
        row.get_by_role('button',name='开始行动',exact=True).click();self.finish(5)
        expect(row).to_contain_text('已确认累计 5 分钟')
        row.get_by_role('button',name='开始行动',exact=True).click();self.finish(15)
        expect(row).to_contain_text('已完成')
        interrupted=self.seed(self.prefix+'中断达标',completion_mode='time');self.page.reload()
        row=self.page.locator('#agendaList [data-plan-id="'+interrupted['id']+'"]')
        row.get_by_role('button',name='开始行动',exact=True).click();self.finish(20,True)
        row.get_by_role('button',name='确认完成',exact=True).click();expect(row).to_contain_text('已完成')
        check=self.seed(self.prefix+'勾选复制');self.page.reload()
        row=self.page.locator('#agendaList [data-plan-id="'+check['id']+'"]')
        row.get_by_role('checkbox').check();expect(row).to_contain_text('已完成')
        completed=self.page.locator('#agendaList > .agenda-completed')
        if completed.get_attribute('open') is None:completed.locator(':scope > summary').click()
        row.get_by_role('checkbox').uncheck();expect(row).to_contain_text('待执行')
        row.get_by_role('checkbox').check();expect(row).to_contain_text('已完成')
        completed=self.page.locator('#agendaList > .agenda-completed')
        if completed.get_attribute('open') is None:completed.locator(':scope > summary').click()
        row.locator('summary').click();row.get_by_role('button',name='复制为新行动').click()
        d=self.page.get_by_role('dialog');d.get_by_label('做什么',exact=True).fill(self.prefix+'新副本')
        d.get_by_role('button',name='加入今日',exact=True).click();expect(d).to_have_count(0)
        copied=next(p for p in self.plans() if p['title']==self.prefix+'新副本')
        self.assertEqual((copied['status'],copied['progress']['completed'],copied['progress']['minutes']),('active',0,0))
        # Two real pages keep the same base revision, and a stale editor cannot overwrite.
        row=self.page.locator('#agendaList [data-plan-id="'+copied['id']+'"]');row.locator('summary').click();row.get_by_role('button',name='编辑',exact=True).click()
        other=self.context.new_page();other.goto(self.base)
        other.locator('#agendaList [data-plan-id="'+copied['id']+'"]').locator('summary').click();other.locator('#agendaList [data-plan-id="'+copied['id']+'"]').get_by_role('button',name='编辑',exact=True).click()
        d=self.page.get_by_role('dialog');d.get_by_label('做什么',exact=True).fill(self.prefix+'服务器新标题')
        d.get_by_role('button',name='保存修改',exact=True).click();expect(d).to_have_count(0)
        stale=other.get_by_role('dialog');stale.get_by_label('做什么',exact=True).fill(self.prefix+'旧页新输入')
        stale.get_by_role('button',name='保存修改',exact=True).click()
        expect(stale.get_by_role('alert')).to_contain_text('其他页面更新')
        expect(stale.get_by_label('做什么',exact=True)).to_have_value(self.prefix+'旧页新输入')
        self.assertEqual(next(p for p in self.plans() if p['id']==copied['id'])['title'],self.prefix+'服务器新标题')
        other.close()
        self.page.screenshot(path=str(EVIDENCE/'08-closeout-cumulative-and-check.png'))

    def source_flow(self,kind):
        target={'kind':'article','course':self.info['article']} if kind=='article' else {'kind':'plan','plan_id':self.info['course_plan'],'lesson_no':1}
        for p in self.plans():
            if p['completion_mode']=='content' and p['target'] and p['target']['kind']==kind and p['status'] in ('active','paused'):
                self.operation(p,'cancel')
        self.page.reload();self.page.locator('[data-group="learning"]').click()
        if kind=='article':
            self.page.get_by_role('button',name='阅读',exact=True).click()
            self.page.get_by_role('button',name='查看历史文章',exact=True).click()
            self.page.get_by_role('button',name='本站阅读',exact=True).click()
            root=self.page.locator('#view-reading')
            controls=root.locator('.agenda-content-controls')
        else:
            plans=self.context.request.get(self.base+'/api/plans').json()['plans']
            name=next(p['name'] for p in plans if p['id']==target['plan_id'])
            self.page.locator('#learningLibrary [data-filter="pending"]').click()
            self.page.locator('[data-course-key="plan:'+target['plan_id']+'"]').get_by_role('button',name='课程详情',exact=True).click()
            root=self.page.locator('#view-course')
            controls=root.locator('.agenda-content-controls').first
        controls.get_by_role('button',name='安排到明日',exact=True).click()
        expect(controls.get_by_text('已在明日安排',exact=True)).to_be_visible()
        matching=lambda:[p for p in self.plans() if p['completion_mode']=='content' and p['status']!='archived' and p['target'] and p['target']['kind']==kind]
        arranged=matching()[0]
        repeated=self.context.request.post(self.base+'/api/action-plans/schedules',headers={'X-Copilot-Request':'1','X-Grow-Action-Schema':'2'},
            data={'title':arranged['title'],'target':target,'date':arranged['start_date'],'key':str(uuid.uuid4())})
        self.assertEqual(repeated.status,200,repeated.text());self.assertEqual(repeated.json()['plan']['id'],arranged['id'])
        controls.get_by_role('button',name='取消安排',exact=True).click()
        expect(controls.get_by_role('button',name='安排到明日',exact=True)).to_be_visible()
        controls.get_by_role('button',name='安排到明日',exact=True).click()
        expect(controls.get_by_role('button',name='改期',exact=True)).to_be_visible()
        replacement=matching()[0];self.assertNotEqual(replacement['id'],arranged['id'])
        controls.get_by_role('button',name='改期',exact=True).click()
        d=self.page.get_by_role('dialog');d.locator('input[type=date]').fill(self.page.locator('#personalDate').input_value())
        d.get_by_role('button',name='保存安排',exact=True).click();expect(d).to_have_count(0)
        self.page.locator('[data-group="personal"]').click()
        row=self.page.locator('#agendaList [data-plan-id="'+replacement['id']+'"]')
        row.locator('summary').click();row.get_by_role('button',name='计时记录投入').click()
        reader=self.page.locator('#view-reading' if kind=='article' else '#dailyReader')
        if kind=='plan':
            reader.get_by_label('学习笔记（可选）').fill('私人验收笔记，不代表完成')
            reader.get_by_role('button',name='暂存笔记与答案').click()
            expect(reader.get_by_label('学习笔记（可选）')).to_have_value('私人验收笔记，不代表完成')
        self.assertEqual(matching()[0]['status'],'active')
        # The article button already contains '本次读完' before the POST returns.
        # Wait for the durable receipt before ending the running session; otherwise
        # a delayed source response can legitimately complete it before manual reconcile.
        suffix='/personal' if kind=='article' else '/feedback'
        with self.page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith(suffix)) as confirmation:
            reader.get_by_role('button',name='确认本次读完' if kind=='article' else '本人确认学完',exact=True).click()
        self.assertEqual(confirmation.value.status,200)
        self.assertIn('source_event_id',confirmation.value.json())
        self.assertEqual(confirmation.value.json().get('completed_arrangements'),[])
        expect(reader).to_contain_text('本次读完' if kind=='article' else '本课已完成')
        bar=self.page.locator('#actionExecution');expect(bar).to_be_visible()
        self.assertEqual(matching()[0]['status'],'active')
        if bar.locator('details').get_attribute('open') is None:bar.locator('summary').click()
        bar.get_by_role('button',name='记录投入',exact=True).click()
        d=self.page.get_by_role('dialog');d.get_by_label('实际执行分钟').fill('8')
        d.get_by_role('button',name='确认并记录',exact=True).click();expect(d).to_have_count(0)
        self.page.locator('[data-group="personal"]').click()
        row.locator('summary').click();row.get_by_role('button',name='核对完成',exact=True).click();expect(row).to_contain_text('已完成')
        completed=self.page.locator('#agendaList .agenda-completed')
        if completed.count() and completed.get_attribute('open') is None:completed.locator(':scope > summary').click()
        self.assertEqual((matching()[0]['progress']['completed'],matching()[0]['progress']['minutes']),(1,8))
        row.scroll_into_view_if_needed()
        self.page.screenshot(path=str(EVIDENCE/('09-closeout-'+kind+'-receipt.png')))

    def test_article_source_schedule_cancel_timer_and_confirm(self):self.source_flow('article')

    def test_course_source_schedule_cancel_timer_and_confirm(self):self.source_flow('plan')

    def test_R01_R02_multiple_drafts_account_switch_and_reload(self):
        d=self.quick();d.get_by_label('做什么',exact=True).fill(self.prefix+'账号A草稿');self.page.keyboard.press('Escape')
        # The fixture intentionally has no authentication service. Switch only its
        # account response; API tenant isolation is separately proved with two schemas.
        def account_b(route):route.fulfill(json={'user':{'id':'synthetic-B','username':'账号B','is_owner':True}})
        self.page.route(self.base+'/api/auth/me',account_b);self.page.reload()
        d=self.quick();expect(d.get_by_label('做什么',exact=True)).to_have_value('')
        d.get_by_label('做什么',exact=True).fill(self.prefix+'账号B草稿');self.page.keyboard.press('Escape')
        self.page.unroute(self.base+'/api/auth/me',account_b);self.page.reload()
        d=self.quick();expect(d.get_by_label('做什么',exact=True)).to_have_value(self.prefix+'账号A草稿')
        # Forking an unknown submission creates two same-context drafts; the next
        # open must offer an explicit choice and keep both titles.
        self.page.get_by_role('button',name='模拟下次保存响应丢失（隔离验收）').is_visible()
        self.page.keyboard.press('Escape')
        self.page.locator('#fixtureDropNext').click();d=self.quick()
        d.get_by_role('button',name='加入今日',exact=True).click()
        expect(d.get_by_role('alert')).to_contain_text('保存已提交')
        d.get_by_label('做什么',exact=True).fill(self.prefix+'A第二份草稿');self.page.keyboard.press('Escape')
        chooser=self.quick();expect(chooser).to_contain_text('选择未提交的行动')
        expect(chooser).to_contain_text(self.prefix+'账号A草稿');expect(chooser).to_contain_text(self.prefix+'A第二份草稿')
        chooser.get_by_role('button',name='新建另一份',exact=True).click()
        expect(self.page.get_by_role('dialog').get_by_label('做什么',exact=True)).to_have_value('')
