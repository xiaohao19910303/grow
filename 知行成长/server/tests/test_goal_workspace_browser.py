"""Real browser goal-to-action journeys, no business storage or model network."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import unittest
import uuid
from playwright.sync_api import sync_playwright, expect


@unittest.skipUnless(os.getenv('RUN_GITHUB_BROWSER')=='1','Opt in to isolated Chrome')
class GoalWorkspaceBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=subprocess.Popen([sys.executable,str(Path(__file__).with_name('serve_goal_workspace_fixture.py'))],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=os.environ.copy())
        cls.addClassCleanup(cls.stop)
        if not select.select([cls.fixture.stdout],[],[],60)[0]:raise RuntimeError('fixture timeout')
        line=cls.fixture.stdout.readline()
        if not line:raise RuntimeError(cls.fixture.stderr.read())
        cls.base=json.loads(line)['url']
        cls.pw=sync_playwright().start();cls.addClassCleanup(cls.pw.stop)
        cls.browser=cls.pw.chromium.launch(headless=True,executable_path=os.getenv('CHROME_EXECUTABLE','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'))
        cls.addClassCleanup(cls.browser.close)

    @classmethod
    def stop(cls):
        cls.fixture.terminate()
        try:cls.fixture.wait(timeout=10)
        except subprocess.TimeoutExpired:cls.fixture.kill();cls.fixture.wait(timeout=5)
        cls.fixture.stdout.close();cls.fixture.stderr.close()

    def setUp(self):
        self.context=self.browser.new_context(viewport={'width':1440,'height':1000})
        self.addCleanup(self.context.close)
        self.context.add_init_script("localStorage.setItem('zhixing-ai-config-v1:agenda-fixture',JSON.stringify({api_base_url:'https://example.invalid/v1',api_key:'TEST_ONLY',model_name:'fixture'}));")
        self.page=self.context.new_page();self.page.set_default_timeout(8000);self.errors=[]
        self.page.on('pageerror',lambda e:self.errors.append(str(e)))
        self.page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(self.base+'/') else r.abort())
        self.page.goto(self.base)
        self.page.locator('[data-group=actions]').click()
        self.page.get_by_role('button',name='目标与计划',exact=True).click()
        expect(self.page.get_by_role('button',name='＋新建',exact=True)).to_be_visible()
        self.prefix=uuid.uuid4().hex[:8]

    def tearDown(self):self.assertEqual(self.errors,[])
    def form(self):return self.page.locator('dialog.action-dialog[open]').last
    def detail(self):return self.page.locator('dialog.gw-detail[open]')

    def new_goal(self):
        self.page.get_by_role('button',name='＋新建',exact=True).click()
        self.form().get_by_role('button',name='目标 ·',exact=False).click()
        form=self.form();form.get_by_label('想达成什么结果',exact=True).fill('表达能力 '+self.prefix)
        form.get_by_label('结果如何衡量',exact=True).select_option('manual')
        form.get_by_label('目标值',exact=True).fill('12');form.get_by_label('单位',exact=True).fill('篇')
        form.get_by_role('button',name='创建目标',exact=True).click()
        expect(self.detail().get_by_role('heading',level=2,name='表达能力 '+self.prefix,exact=True)).to_be_visible()

    def test_goal_plan_action_result_week_ai_and_mobile(self):
        self.new_goal();detail=self.detail();detail.get_by_role('button',name='添加下一步',exact=True).click()
        self.form().get_by_role('button',name='计划 ·',exact=False).click()
        form=self.form();form.get_by_label('这段时间推进什么',exact=True).fill('本周初稿 '+self.prefix)
        form.get_by_role('button',name='创建计划',exact=True).click()
        expect(self.detail().get_by_role('heading',level=2,name='本周初稿 '+self.prefix,exact=True)).to_be_visible()
        self.detail().get_by_role('button',name='添加下一步',exact=True).click();self.form().get_by_role('button',name='行动 ·',exact=False).click()
        form=self.form();form.get_by_label('做什么',exact=True).fill('写出提纲 '+self.prefix)
        expect(form.get_by_label('行动日期（可暂不安排）',exact=True)).to_have_value('')
        form.get_by_role('button',name='保存行动',exact=True).click()
        expect(self.detail().get_by_role('heading',level=2,name='写出提纲 '+self.prefix,exact=True)).to_be_visible()
        self.detail().get_by_role('button',name='安排今日并完成',exact=True).click()
        expect(self.detail().get_by_role('checkbox',name='撤销完成：写出提纲 '+self.prefix,exact=True)).to_be_checked()
        self.detail().get_by_role('button',name='关闭详情',exact=True).click()
        self.page.locator('.gw-card').filter(has_text='表达能力 '+self.prefix).get_by_role('button',name='查看详情',exact=True).click()
        self.detail().get_by_role('button',name='进度与复盘',exact=True).click();self.detail().get_by_role('button',name='更新结果与完成标准',exact=True).click()
        form=self.form();form.get_by_label('当前值',exact=True).fill('4');form.get_by_role('button',name='保存结果',exact=True).click()
        expect(self.detail().get_by_text('4 / 12 篇 · 33.3%',exact=True)).to_be_visible()
        self.detail().get_by_role('button',name='AI 辅助拆解',exact=True).click()
        self.form().get_by_label('目前的基础',exact=True).fill('能够写简单提纲')
        self.form().get_by_role('button',name='预览将发送的内容',exact=True).click()
        self.form().get_by_label('同意发送以上内容到本人配置的 AI 服务',exact=True).check()
        self.form().get_by_role('button',name='确认并生成草案',exact=True).click()
        draft=self.form()
        if draft.get_by_role('button',name='刷新生成结果',exact=True).count():draft.get_by_role('button',name='刷新生成结果',exact=True).click()
        expect(draft.get_by_label('名称',exact=True).first).to_be_visible()
        draft.get_by_role('button',name='采用所选项目',exact=True).click()
        expect(self.form().get_by_text('已采用 2 项，没有重复创建。',exact=True)).to_be_visible()
        self.page.keyboard.press('Escape');self.detail().get_by_role('button',name='关闭详情',exact=True).click()
        self.page.get_by_role('button',name='日程安排',exact=True).click();self.page.get_by_role('button',name='规划本周',exact=True).click()
        self.form().get_by_label('本周可投入分钟（可留空）',exact=True).fill('10')
        self.form().get_by_label('写出三个核心论点',exact=True).check()
        expect(self.form().get_by_text('超出可用时间 10 分钟，可以调整或继续保存。',exact=True)).to_be_visible()
        self.form().get_by_role('button',name='确认本周安排',exact=True).click()
        expect(self.page.locator('dialog.action-dialog[open]')).to_have_count(0)
        self.page.get_by_role('button',name='目标与计划',exact=True).click()
        output=Path(os.getenv('GOAL_EVIDENCE_DIR','/tmp/grow-goal-evidence'));output.mkdir(parents=True,exist_ok=True)
        expect(self.page.locator('#toast')).not_to_have_class(__import__('re').compile(r'\bshow\b'))
        self.page.screenshot(path=str(output/'01-workspace-desktop.png'),full_page=True)
        self.page.set_viewport_size({'width':390,'height':844})
        self.page.locator('.gw-card').filter(has_text='表达能力 '+self.prefix).get_by_role('button',name='查看详情',exact=True).click()
        self.assertEqual(self.detail().bounding_box()['y'],0)
        self.assertEqual(self.detail().bounding_box()['x'],0)
        self.assertEqual(self.detail().bounding_box()['width'],390)
        self.assertEqual(self.detail().bounding_box()['height'],844)
        self.page.screenshot(path=str(output/'02-detail-mobile.png'))
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),390)
        self.assertLessEqual(self.detail().evaluate('(el)=>el.scrollWidth'),390)
        self.page.keyboard.press('Escape')
        self.page.set_viewport_size({'width':1440,'height':1000});self.page.emulate_media(color_scheme='dark')
        self.page.evaluate('window.scrollTo(0,0)')
        self.page.screenshot(path=str(output/'03-workspace-dark.png'),full_page=True,animations='disabled')
        print('GOAL_BROWSER_EVIDENCE '+str(output))

    def test_independent_plan_draft_restore_and_filter(self):
        self.page.get_by_role('button',name='＋新建',exact=True).click();self.form().get_by_role('button',name='计划 ·',exact=False).click()
        form=self.form();form.get_by_label('这段时间推进什么',exact=True).fill('独立月计划 '+self.prefix);form.get_by_label('规划周期',exact=True).select_option('month');form.get_by_role('button',name='稍后继续',exact=True).click()
        self.page.reload();self.page.locator('[data-group=actions]').click();self.page.get_by_role('button',name='目标与计划',exact=True).click()
        self.page.get_by_role('button',name='＋新建',exact=True).click();self.form().get_by_role('button',name='计划 ·',exact=False).click()
        expect(self.form().get_by_label('这段时间推进什么',exact=True)).to_have_value('独立月计划 '+self.prefix)
        self.form().get_by_role('button',name='创建计划',exact=True).click()
        expect(self.detail().get_by_role('heading',level=2,name='独立月计划 '+self.prefix,exact=True)).to_be_visible()
        self.detail().get_by_role('button',name='关闭详情',exact=True).click()
        self.page.get_by_label('搜索目标、计划或行动',exact=True).fill('独立月计划 '+self.prefix)
        expect(self.page.locator('.gw-independent .gw-card')).to_have_count(1)

    def test_goal_unknown_save_keeps_later_draft_and_original_receipt(self):
        self.page.get_by_role('button',name='＋新建',exact=True).click();self.form().get_by_role('button',name='目标 ·',exact=False).click()
        form=self.form();old='原目标 '+self.prefix;new='后续填写 '+self.prefix
        form.get_by_label('想达成什么结果',exact=True).fill(old)
        def lost(route):
            response=route.fetch()
            self.assertEqual(response.status,200)
            route.fulfill(status=503,content_type='application/json',body='{"detail":"模拟保存响应丢失"}')
        self.page.route(self.base+'/api/action-plans/goals',lost)
        form.get_by_role('button',name='创建目标',exact=True).click()
        expect(form.get_by_role('alert')).to_contain_text('模拟保存响应丢失')
        form.get_by_label('想达成什么结果',exact=True).fill(new)
        form.get_by_role('button',name='创建目标',exact=True).click()
        expect(form.get_by_role('alert')).to_contain_text('上次提交')
        self.page.unroute(self.base+'/api/action-plans/goals',lost)
        form.get_by_role('button',name='核对上次提交',exact=True).click()
        expect(self.detail().get_by_role('heading',level=2,name=old,exact=True)).to_be_visible()
        plans=self.context.request.get(self.base+'/api/action-plans/workspace').json()['plans']
        self.assertEqual(sum(x['title']==old for x in plans),1)
        self.assertEqual(sum(x['title']==new for x in plans),0)
        self.detail().get_by_role('button',name='关闭详情',exact=True).click()
        self.page.get_by_role('button',name='＋新建',exact=True).click();self.form().get_by_role('button',name='目标 ·',exact=False).click()
        expect(self.form().get_by_label('想达成什么结果',exact=True)).to_have_value(new)

    def test_batch_adjustments_keep_only_failed_selection(self):
        from datetime import date,timedelta
        today=self.page.locator('#personalDate').input_value();past=str(date.fromisoformat(today)-timedelta(days=2))
        headers={'X-Copilot-Request':'1','X-Grow-Action-Schema':'2','X-Grow-Workspace-Version':'1'}
        def seed(title):
            response=self.context.request.post(self.base+'/api/action-plans',headers=headers,data=dict(title=title,period='day',completion_mode='check',start_date=past,end_date=past,key=str(uuid.uuid4())))
            self.assertEqual(response.status,200,response.text());return response.json()['plans'][0]
        one=seed('批量成功 '+self.prefix);two=seed('批量冲突 '+self.prefix)
        self.page.get_by_role('button',name='日程安排',exact=True).click();root=self.page.locator('#view-action-schedule')
        root.get_by_role('button',name='刷新',exact=True).click();root.get_by_role('button',name='待调整',exact=True).click()
        batch=root.locator('details').filter(has_text='批量调整待安排事项')
        batch.locator('summary').first.click();batch.get_by_label(one['title'],exact=True).check();batch.get_by_label(two['title'],exact=True).check()
        response=self.context.request.post(self.base+'/api/action-plans/'+two['id']+'/operations',headers=headers,data=dict(revision=two['revision'],action='pause',key=str(uuid.uuid4())))
        self.assertEqual(response.status,200,response.text())
        batch.get_by_role('button',name='修改所选日期',exact=True).click()
        expect(root.get_by_role('alert')).to_contain_text(two['title'])
        batch.locator('summary').first.click()
        expect(batch.get_by_label(two['title'],exact=True)).to_be_checked()
        plans=self.context.request.get(self.base+'/api/action-plans/workspace').json()['plans']
        self.assertEqual(next(p for p in plans if p['id']==one['id'])['start_date'],today)
        self.assertEqual(next(p for p in plans if p['id']==two['id'])['start_date'],past)

    def test_repeat_and_template_keep_the_same_action_draft(self):
        self.page.get_by_role('button',name='＋新建',exact=True).click();self.form().get_by_role('button',name='行动 ·',exact=False).click()
        form=self.form();title='重复行动 '+self.prefix;today=self.page.locator('#personalDate').input_value()
        form.get_by_label('做什么',exact=True).fill(title);form.get_by_label('行动日期（可暂不安排）',exact=True).fill(today)
        form.get_by_text('更多设置',exact=True).click()
        form.get_by_label('预计分钟（可选，不决定完成）',exact=True).fill('15')
        form.get_by_role('button',name='保存为行动模板',exact=True).click()
        expect(form.get_by_label('从模板创建（可选）',exact=True).locator('option')).to_contain_text(['不使用模板',title])
        form.get_by_label('重复安排',exact=True).select_option('daily')
        from datetime import date,timedelta
        tomorrow=str(date.fromisoformat(today)+timedelta(days=1))
        form.get_by_label('重复结束日期',exact=True).fill(tomorrow)
        form.get_by_role('button',name='稍后继续',exact=True).click()
        self.page.get_by_role('button',name='＋新建',exact=True).click();self.form().get_by_role('button',name='行动 ·',exact=False).click()
        form=self.form();expect(form.get_by_label('做什么',exact=True)).to_have_value(title)
        form.get_by_text('更多设置',exact=True).click();expect(form.get_by_label('重复安排',exact=True)).to_have_value('daily')
        form.get_by_role('button',name='加入今日',exact=True).click()
        expect(self.detail().get_by_role('heading',level=2,name=title,exact=True)).to_be_visible()
        plans=self.context.request.get(self.base+'/api/action-plans/workspace').json()['plans']
        rows=[p for p in plans if p['title']==title]
        self.assertEqual(len(rows),2)
        self.assertEqual({p['start_date'] for p in rows},{today,tomorrow})
        self.assertTrue(all(p['estimated_minutes']==15 for p in rows))
