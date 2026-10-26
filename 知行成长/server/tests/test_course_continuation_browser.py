"""Full production continuation UI against isolated PG/GitHub and a synthetic model."""
import copy
import json
import os
from pathlib import Path
import socket
import threading
import time
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from playwright.sync_api import sync_playwright,expect
from cloud_fixtures import CloudFixture
from copilot.core import Problem
from copilot.generation import SEPARATOR
from plans.api import register as register_plans
from copilot.api import register as register_copilot
from course_continuations import register as register_continuations
from study_materials import initialize,register as register_materials,Completion
from study_notes import register as register_notes,Draft,save as save_note
import test_plans

# Hide unrelated fixed chrome only while capturing component screenshots.
SHOT_STYLE='.topbar,#toast,#readingTaskCenter{visibility:hidden!important}'
AI={'api_base_url':'https://model.example/v1','api_key':'BROWSER_TEST_SECRET','model_name':'test'}
class ContinuationBrowserTests(CloudFixture):
    def setUp(self):
        super().setUp();self.calls=[];self.fault={'first':False}
        for name,folder in [('英文阅读','每日文章'),('结构化表达','每日练习')]:
            directory=self.root/name/folder;directory.mkdir(parents=True)
            (directory/'Day 001.md').write_text('# '+name+'基础课\n\n公开的教学内容，作为下一课参考。')
        initialize();app=FastAPI();self.app=app
        @app.exception_handler(Problem)
        async def problem(request,error):return JSONResponse({'error':error.code,'message':error.message},status_code=error.status)
        self.plans,self.generator=register_plans(app,self.root,self.s.db)
        self.cognitive=register_copilot(app,self.root,self.s.db)
        self.cognitive.initialize()
        self.materials=register_materials(app,self.root);register_notes(app)
        self.service=register_continuations(app,self.plans,self.generator,self.materials,self.cognitive)
        async def transport(messages,cfg):
            self.calls.append(copy.deepcopy(messages));ctx=json.loads(messages[1]['content'])
            if 'options' in messages[0]['content']:
                raw=json.dumps({'options':[{'mode':m,'title':title,'goal':'说明进展、问题与支持需求','reason':'衔接当前已学的结构化表达','lesson_count':4} for m,title in [('consolidate','表达基础巩固'),('apply','工作汇报表达'),('advance','论证与说服进阶')]]},ensure_ascii=False)
            elif 'schema' in ctx:
                if self.fault.get('plan'):
                    self.fault['plan']=False;raise RuntimeError('synthetic plan failure')
                count=ctx['brief'].get('lesson_count',2);doc=copy.deepcopy(test_plans.D)
                doc['lessons']=[{**doc['lessons'][0],'number':i,'topic':'汇报主题'+str(i),'minutes':15,'requires':[], 'kind':'review' if i==count else 'lesson'} for i in range(1,count+1)]
                raw=json.dumps(doc)
            elif ctx.get('module_id'):
                raw=json.dumps({'title':'表达迁移训练','content':'## 学习目标\n说明重点。\n## 示范\n'+'教学情境示范。'*60+'\n## 练习\n自己改写。\n## 参考答案\n参考表达。\n## 自查\n解释边界。'})
            else:
                if self.fault['first']:
                    self.fault['first']=False;raise RuntimeError('synthetic model failure')
                raw=test_plans.content(ctx)+SEPARATOR+'教学资料 https://example.org/lesson'
                if not any('https://' in item['content'] for item in ctx['source_entries']):raw=raw.replace('[来源](https://example.org/lesson)','').replace('https://example.org/lesson','前置课程教学内容')
            yield {'text':raw};yield {'done':True}
        self.generator.transport=transport;self.service.transport=transport
        self.mock_stream=patch('copilot.transport.qwen_stream',side_effect=transport);self.mock_stream.start();self.addCleanup(self.mock_stream.stop)
        for module in ('biaoda','yingyu'):
            lesson=self.materials.lessons(module)[0]
            self.materials.save(module,lesson['filename'],Completion(summary_text='PRIVATE_COMPLETION',time_spent_seconds=0,version=lesson['version'],revision=0,key='seed-'+module+'-completed'))
        source=self.materials.lessons('biaoda')[0]
        save_note('biaoda',source['filename'],Draft(notes='PRIVATE_CHOSEN_NOTE',answers={'q':'PRIVATE_ANSWER'},version=source['version'],revision=0,key='browser-private-note'))
        static=Path(__file__).resolve().parents[1]/'static';app.mount('/static',StaticFiles(directory=static))
        @app.get('/')
        def index():return FileResponse(static/'index.html')
        self.sock=socket.socket();self.sock.bind(('127.0.0.1',0));self.base=f'http://127.0.0.1:{self.sock.getsockname()[1]}'
        self.server=uvicorn.Server(uvicorn.Config(app,log_level='error'));self.thread=threading.Thread(target=self.server.run,kwargs={'sockets':[self.sock]},daemon=True);self.thread.start()
        self.addCleanup(lambda:self.thread.join(5));self.addCleanup(lambda:setattr(self.server,'should_exit',True))
        for _ in range(100):
            if self.server.started:break
            time.sleep(.02)
        self.pw=sync_playwright().start();self.addCleanup(self.pw.stop)
        self.browser=self.pw.chromium.launch(headless=True,executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome');self.addCleanup(self.browser.close)
        self.page=self.browser.new_page(viewport={'width':1440,'height':1000},timezone_id='Asia/Shanghai');self.page.set_default_timeout(12000)
        self.errors=[];self.page.on('pageerror',lambda e:self.errors.append(str(e)))
        self.page.route('**/api/**',self.unrelated)
        self.page.add_init_script('localStorage.setItem("zhixing-ai-config-v1:fixture",'+json.dumps(json.dumps(AI))+')')
        self.shots=Path('/tmp/grow-continuation-tests/screenshots');self.shots.mkdir(parents=True,exist_ok=True)

    def unrelated(self,route):
        path=route.request.url.split(self.base)[-1].split('?')[0]
        if path.startswith(('/api/study-materials','/api/plans','/api/course-continuations','/api/study-notes','/api/copilot')):return route.continue_()
        if path=='/api/auth/me':data={'user':{'id':'fixture','username':'tester','is_owner':False}}
        elif path=='/api/data':data=dict(modules=[],checkins={},habits={},customFields=[],customRecords=[],decisions=[],predictions=[],reviews=[],insights=[],todos=[],_revision='fixture')
        elif path=='/api/action-plans':data={'plans':[],'execution':None,'server_time':'2026-10-27T12:00:00+08:00','action_schema_version':2,'capabilities':{'nullable_schedule':True}}
        else:data=dict(modules=[],lessons=[],plans=[],records=[],items=[],articles=[],jobs=[],entries=[],reports=[],stats={},preferences={},budget={},attempts=[],goals=[],occurrences=[])
        route.fulfill(json=data)

    def test_advice_edit_restore_adopt_first_lesson_save_read_and_return(self):
        page=self.page;page.goto(self.base+'/#course/biaoda');detail=page.locator('#view-course');panel=detail.locator('.course-continuation')
        expect(panel.get_by_role('button',name='给我学习建议')).to_be_visible()
        panel.locator('details > summary').click();panel.get_by_label('第1课笔记与练习',exact=True).check()
        panel.get_by_role('button',name='给我学习建议').focus();page.keyboard.press('Enter')
        option=panel.locator('.continuation-option').filter(has=page.get_by_role('heading',name='工作汇报表达'))
        expect(option.get_by_role('button',name='选择并调整')).to_be_visible()
        panel.screenshot(path=str(self.shots/'advice-options.png'),animations='disabled',style=SHOT_STYLE)
        option.get_by_role('button',name='选择并调整').click()
        panel.get_by_label('接下来希望学什么？').fill('工作汇报与项目进展表达')
        panel.get_by_label('目前的困惑（可选）').fill('表达容易分散')
        panel.get_by_role('button',name='暂存填写',exact=True).click()
        expect(panel.get_by_role('status')).to_contain_text('已暂存')
        panel.screenshot(path=str(self.shots/'direction-form.png'),animations='disabled',style=SHOT_STYLE)
        page.reload();expect(panel.get_by_label('接下来希望学什么？')).to_have_value('工作汇报与项目进展表达')
        expect(panel.get_by_label('目前的困惑（可选）')).to_have_value('表达容易分散')
        self.assertEqual(len(self.calls),1,'Reload must not repeat the advice model call')
        self.fault['plan']=True
        panel.get_by_role('button',name='生成建议规划',exact=True).click()
        plan=page.locator('#view-plans');expect(plan).to_contain_text('生成未完成')
        plan.get_by_role('button',name='重新生成一份',exact=True).click()
        expect(plan.locator('.plan-summary')).to_contain_text('自由节奏 · 共4课')
        expect(plan).not_to_contain_text('undefined')
        plan.screenshot(path=str(self.shots/'plan-preview.png'),animations='disabled',style=SHOT_STYLE)
        plan.get_by_role('button',name='调整规划',exact=True).click()
        page.get_by_label('学习方向',exact=True).fill('工作汇报表达进阶')
        page.get_by_role('button',name='保存草稿并预览',exact=True).click()
        page.get_by_label('已阅读这份草稿，确认将其正式保存').check()
        self.fault['first']=True
        page.get_by_role('button',name='采用规划并生成第一课',exact=True).click()
        expect(plan).to_contain_text('生成未完成')
        # The adopted course remains unique when first-lesson generation failed.
        with self.plans.conn() as c:ids=[r[0] for r in c.execute('SELECT id FROM learning_plans')]
        self.assertEqual(len(ids),1);child=ids[0]
        page.goto(self.base+'/#course/biaoda')
        expect(panel.get_by_role('button',name='生成第一课',exact=True)).to_be_visible()
        panel.get_by_role('button',name='生成第一课',exact=True).click()
        expect(plan.get_by_role('button',name='保存正式课程',exact=True)).to_be_visible()
        page.get_by_label('已阅读这份草稿，确认将其正式保存').check();plan.get_by_role('button',name='保存正式课程',exact=True).click()
        expect(plan.get_by_role('button',name='返回课程详情',exact=True)).to_be_visible()
        plan.get_by_role('button',name='返回课程详情',exact=True).click()
        expect(detail.locator('h2')).to_have_text('工作汇报表达进阶')
        expect(detail).to_contain_text('0 / 4')
        detail.get_by_role('button',name='开始学习',exact=True).first.click()
        reader=page.locator('#dailyReader');expect(reader.get_by_role('heading',name='核心概念',exact=True)).to_be_visible()
        reader.get_by_role('button',name='本人确认学完',exact=True).click()
        expect(reader).to_contain_text('本课已完成')
        expect(reader.locator('.course-continuation')).to_contain_text('下一步学什么')
        reader.get_by_role('button',name='返回课程详情',exact=True).click()
        expect(detail).to_contain_text('1 / 4');expect(detail).to_contain_text('关联课程：结构化表达')
        for theme in ('light','dark'):
            page.locator('html').evaluate('(el,theme)=>el.dataset.theme=theme',theme)
            for width in (320,768,1024,1440):
                page.set_viewport_size({'width':width,'height':1000})
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                detail.locator('.course-continuation').screenshot(path=str(self.shots/f'continuation-{theme}-{width}.png'),animations='disabled',style=SHOT_STYLE)
        detail.get_by_role('button',name='关联课程：结构化表达',exact=True).click()
        expect(panel.get_by_role('button',name='关联课程：工作汇报表达进阶',exact=True)).to_be_visible()
        panel.get_by_role('button',name='自己填写方向',exact=True).click()
        expect(panel.get_by_label('接下来希望学什么？')).to_have_value('')
        self.assertEqual(self.plans.lessons(child)[0]['learning_state'],'completed')
        public=str(self.repo.commits[self.repo.head]['files'])
        self.assertNotIn('PRIVATE_CHOSEN_NOTE',public);self.assertNotIn('PRIVATE_ANSWER',public);self.assertNotIn('BROWSER_TEST_SECRET',public)
        self.assertTrue(any('PRIVATE_CHOSEN_NOTE' in str(call) for call in self.calls))
        self.assertEqual(self.errors,[])

    def test_direct_generation_and_manual_direction_without_advice(self):
        page=self.page;page.goto(self.base+'/#course/biaoda');panel=page.locator('#view-course .course-continuation')
        panel.get_by_role('button',name='直接生成下一课',exact=True).click()
        expect(panel.get_by_role('button',name='保存课程并开始学习',exact=True)).to_be_visible()
        panel.get_by_role('button',name='保存课程并开始学习',exact=True).click()
        expect(page.locator('#dailyReader')).to_contain_text('表达迁移训练')
        page.locator('#dailyReader').get_by_role('button',name='返回课程详情').click()
        expect(panel.get_by_role('button',name='继续下一课')).to_be_visible()
        panel.get_by_role('button',name='自己填写方向',exact=True).click()
        panel.get_by_label('接下来希望学什么？').fill('演示项目方案')
        panel.get_by_label('总课数（2–12课）').fill('2')
        panel.get_by_role('button',name='生成建议规划').click()
        plan=page.locator('#view-plans');expect(plan.locator('.plan-summary')).to_contain_text('共2课')
        page.get_by_label('已阅读这份草稿，确认将其正式保存').check();plan.get_by_role('button',name='仅保存规划').click()
        expect(page.locator('#view-course h2')).to_have_text('演示项目方案')
        self.assertFalse(any('options' in c[0]['content'] for c in self.calls))
        self.assertEqual(self.errors,[])
