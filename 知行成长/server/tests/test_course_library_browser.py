"""Actual app UI and private PG resume routes; synthetic content, no model calls."""
import os
from pathlib import Path
import socket
import threading
import time

from fastapi import APIRouter, FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from test_legacy_cloud_schema import PostgreSQLFixture


class CourseLibraryBrowserTests(PostgreSQLFixture):
    def test_hierarchy_resume_completion_history_and_responsive_layout(self):
        from playwright.sync_api import sync_playwright, expect
        from course_activity import install_routes
        from study_notes import register as register_notes

        static = Path(__file__).resolve().parents[1] / 'static'
        app = FastAPI()
        router = APIRouter(prefix='/api/study-materials')
        install_routes(router); app.include_router(router); register_notes(app)
        app.mount('/static', StaticFiles(directory=static))

        @app.get('/')
        def index():
            return HTMLResponse((static / 'index.html').read_text())

        sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
        thread = threading.Thread(target=server.run, kwargs={'sockets':[sock]}, daemon=True); thread.start()
        self.addCleanup(lambda: thread.join(5))
        self.addCleanup(lambda: setattr(server, 'should_exit', True))
        for _ in range(100):
            if server.started: break
            time.sleep(.02)
        base = f'http://127.0.0.1:{port}'
        stamp = '2026-10-26T12:00:00+08:00'
        def lesson(n, done=False):
            return {'lesson_no':n,'topic':f'课次主题{n}','filename':f'Day {n:03d}.md',
                    'learning_state':'completed' if done else 'unknown', 'learning_label':'已学完' if done else '待本人反馈',
                    'complete':True, 'completed_at':stamp if done else None, 'version':'a'*64}
        def plan(pid, name, lessons, status='active', count=3):
            return {'id':pid,'name':name,'status':status,'version':1,'brief':{'goal':'理解概念并练习应用','level':'零基础','minutes':20,'weeks':2,'sessions':2},
                    'lessons':lessons,'curriculum':{'prerequisites':'无需先修','stages':[{'title':'基础阶段','goal':'理解概念'},{'title':'应用阶段','goal':'举例应用'}],
                    'lessons':[{'number':n,'topic':f'规划主题{n}','stage':1 if n<3 else 2} for n in range(1,count+1)]}}
        partial = plan('partial','经济学入门',[lesson(1,True)])
        ready = plan('ready','新的完整规划',[lesson(1),lesson(2),lesson(3)])
        completed = plan('done','已完成课程',[lesson(1,True),lesson(2,True)],count=2)
        paused = plan('paused','暂停的课程',[lesson(1,True)],status='paused')
        archived = plan('archived','归档的课程',[lesson(1,True)],status='archived')
        expression = [lesson(1),lesson(2)]
        flags = {'activity_failure':False, 'expression_failure':False, 'plans_failure':False}
        writes, errors = [], []

        def fixture(route):
            request = route.request; path = request.url.split(base)[-1].split('?')[0]
            if path == '/api/study-materials/library/activity':
                if flags['activity_failure']: route.fulfill(status=503,json={'message':'test unavailable'})
                else: route.continue_()
                return
            if path.startswith('/api/study-notes'):
                route.continue_(); return
            if request.method != 'GET': writes.append(path)
            if path == '/api/auth/me': result = {'user':{'id':'fixture','username':'tester','is_owner':False}}
            elif path == '/api/data': result = dict(modules=[],checkins={},habits={},customFields=[],customRecords=[],decisions=[],predictions=[],reviews=[],insights=[],todos=[],_revision='fixture')
            elif path == '/api/action-plans': result = {'plans':[],'execution':None,'server_time':stamp,'action_schema_version':2,'capabilities':{'nullable_schedule':True}}
            elif path == '/api/copilot/today-task': result = {'lessons':[lesson(1,True)]}
            elif path == '/api/study-materials': result = {'modules':[
                {'id':'biaoda','name':'结构化表达与日常工作场景中的清晰沟通练习','duration':'15 分钟','lessons':expression},
                {'id':'yingyu','name':'英文阅读','duration':'35 分钟','lessons':[lesson(1,True)]}]}
            elif path == '/api/plans':
                if flags['plans_failure']: route.fulfill(status=503,json={'message':'unavailable'});return
                result = {'plans':[partial,ready,completed,paused,archived],'attempts':[],'drafts':[],'legacy':[],'budget':{}}
            elif path == '/api/plans/ready': result = {'plan':ready,'current':{'brief':ready['brief'],'document':ready['curriculum']},'lessons':ready['lessons'],'feedback':[],'versions':[],'external':{'content':'规划正文','changed':False}}
            elif path.startswith('/api/plans/ready/lessons/'):
                n = int(path.rsplit('/',1)[-1]); result = {'lesson':ready['lessons'][n-1],'content':'# 规划课程正文\n\n课程内容','sources':'合成参考资料'}
            elif path.startswith('/api/study-materials/biaoda/'):
                if flags['expression_failure']: route.fulfill(status=503,json={'message':'test unavailable'});return
                if path.endswith('/learning-record'):
                    n = 2 if '002' in path else 1
                    expression[n-1].update(learning_state='completed',learning_label='本人确认完成',completed_at=stamp)
                    result = {'revision':1,'completed_at':stamp,'time_spent_seconds':0}
                else: result = {'content':'# 表达课程正文\n\n练习清晰表达。','lesson':{'version':'a'*64},'record':None}
            else: result = dict(modules=[],lessons=[],plans=[],records=[],items=[],articles=[],jobs=[],entries=[],reports=[],stats={},preferences={},budget={},attempts=[],checkins={})
            route.fulfill(json=result)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=os.getenv('CHROME_EXECUTABLE','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'))
            page = browser.new_page(viewport={'width':1440,'height':960},timezone_id='Asia/Shanghai')
            page.set_default_timeout(7000);page.on('pageerror',lambda e:errors.append(str(e)));page.route('**/api/**',fixture)
            page.goto(base);page.locator('[data-group="learning"]').click()
            library=page.locator('#learningLibrary');detail=page.locator('#view-course')
            expect(library.locator('[data-filter="learning"]')).to_have_attribute('aria-pressed','true')
            expect(library.locator('.course-cards').first.locator('.course-card')).to_have_count(3)
            expect(library.locator('.lesson-row')).to_have_count(0)
            expect(library.locator('[data-course-key="renzhi"]')).to_contain_text('已学至最新')
            expect(library.locator('[data-course-key="plan:partial"]')).to_contain_text('1 / 3')
            expect(page.locator('#subnav')).not_to_contain_text('课程规划')
            expect(library.locator('.course-inactive')).not_to_have_attribute('open','')
            library.locator('.course-inactive > summary').click()
            expect(library.locator('[data-course-key="plan:paused"]')).to_contain_text('已暂停')
            expect(library.locator('[data-course-key="plan:archived"]')).to_contain_text('已归档')
            library.locator('[data-course-key="plan:partial"]').get_by_role('button',name='查看后续规划').click()
            expect(detail.locator('h2')).to_have_text('经济学入门')
            expect(detail.locator('[data-section="stage-0"]')).to_have_attribute('open','')
            expect(detail.locator('[data-section="stage-1"]')).not_to_have_attribute('open','')
            expect(detail.locator('.course-unpublished')).to_have_count(2)
            page.reload();expect(detail.locator('h2')).to_have_text('经济学入门')
            page.go_back();expect(page.locator('#view-library')).to_be_visible()
            library.locator('[data-filter="completed"]').click()
            expect(library.locator('.course-cards').first.locator('.course-card')).to_have_count(1)
            expect(library.locator('[data-course-key="plan:done"]')).to_contain_text('完成于 2026-10-26')
            library.locator('[data-filter="pending"]').click()
            expression_card=library.locator('[data-course-key="biaoda"]')
            expression_card.get_by_role('button',name='课程详情').click()
            # A failed content request must not create a started course.
            flags['expression_failure']=True
            detail.locator('.lesson-row').nth(1).get_by_role('button',name='开始学习').click()
            expect(page.locator('#dailyReader')).to_contain_text('读取失败')
            page.locator('#dailyReader').get_by_role('button',name='返回课程详情').click()
            flags['expression_failure']=False
            # Position write failure is visible, retryable, and does not block the reader.
            flags['activity_failure']=True
            detail.locator('.lesson-row').nth(1).get_by_role('button',name='开始学习').click()
            reader=page.locator('#dailyReader')
            expect(reader.get_by_role('heading',name='表达课程正文')).to_be_visible()
            expect(page.locator('#courseActivityNotice')).to_contain_text('学习位置暂未同步')
            flags['activity_failure']=False
            page.locator('#courseActivityNotice').get_by_role('button',name='重试学习位置同步').click()
            expect(page.locator('#courseActivityNotice')).to_be_hidden()
            reader.get_by_role('button',name='返回课程详情').click()
            expect(detail).to_contain_text('继续上次课次：第 2 课')
            page.reload();expect(detail).to_contain_text('继续上次课次：第 2 课')
            detail.get_by_role('button',name='返回我的课程').click()
            library.locator('[data-filter="learning"]').click()
            expression_card.get_by_role('button',name='继续学习').click()
            expect(reader.get_by_role('heading',name='课次主题2',exact=True)).to_be_visible()
            reader.get_by_role('button',name='标记学完并保存').click()
            expect(reader).to_contain_text('已学完，学习记录已保存')
            reader.get_by_role('button',name='返回我的课程').click()
            expect(expression_card).to_contain_text('1 / 2')
            expression_card.get_by_role('button',name='课程详情').click()
            expect(detail).to_contain_text('接下来：第 1 课')
            shots=Path(os.getenv('COURSE_LIBRARY_SCREENSHOTS','/tmp/grow-course-library-tests/screenshots'));shots.mkdir(parents=True,exist_ok=True)
            for width in (320,768,1024,1440):
                page.set_viewport_size({'width':width,'height':960})
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                page.screenshot(path=str(shots/f'course-detail-{width}.png'),full_page=True,animations='disabled')
            detail.screenshot(path=str(shots/'course-detail-panel.png'),animations='disabled')
            detail.get_by_role('button',name='返回我的课程').click()
            for width in (320,768,1024,1440):
                page.set_viewport_size({'width':width,'height':960})
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                page.screenshot(path=str(shots/f'course-library-{width}.png'),full_page=True,animations='disabled')
            library.screenshot(path=str(shots/'course-library-panel.png'),animations='disabled')
            # Keyboard filters remain native focusable buttons with explicit selection.
            library.locator('[data-filter="pending"]').focus();page.keyboard.press('Enter')
            expect(library.locator('[data-filter="pending"]')).to_be_focused()
            library.locator('[data-course-key="plan:ready"]').get_by_role('button',name='课程详情').click()
            detail.get_by_role('button',name='开始学习',exact=True).first.click()
            expect(reader.get_by_role('heading',name='规划课程正文')).to_be_visible()
            reader.get_by_role('button',name='返回课程详情').click()
            expect(detail).to_contain_text('继续上次课次：第 1 课')
            detail.get_by_role('button',name='返回我的课程').click()
            # Source failures preserve the existing course cache and are explicit.
            flags['plans_failure']=True
            page.locator('#view-library').get_by_role('button',name='刷新课程').click()
            expect(library).to_contain_text('课程规划：读取失败')
            flags['plans_failure']=False
            library.get_by_role('button',name='重试读取课程').click()
            expect(library.locator('.course-source-error')).to_have_count(0)
            page.locator('#view-library').get_by_role('button',name='新建课程',exact=True).click()
            expect(page.get_by_label('学习方向',exact=True)).to_be_visible()
            self.assertEqual(writes,['/api/study-materials/biaoda/Day%20002.md/learning-record'])
            self.assertEqual(errors,[])
            browser.close()
