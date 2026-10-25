"""Chromium exercises the existing legacy course and reading interfaces."""
import json
import os
import socket
import threading
import time
import unittest
from pathlib import Path

import uvicorn
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from test_legacy_cloud_api import CloudHTTPFixture, OWN


@unittest.skipUnless(os.getenv('RUN_LEGACY_BROWSER')=='1','Opt in to Chromium acceptance')
class LegacyCloudBrowser(CloudHTTPFixture):
    def test_course_and_reading_complete_browser_flow(self):
        from playwright.sync_api import sync_playwright, expect
        from study_notes import register as register_study_notes
        register_study_notes(self.app)
        static=Path(__file__).resolve().parents[1]/'static'
        self.reader.save_full_text(self.aid,'Public saved article body. '*20)
        from test_reading_growth_browser import GUIDE
        async def reading_model(messages,cfg):
            self.assertEqual(cfg['key'],OWN['api_key'])
            yield {'text':GUIDE+'\n\nPublic generated reading guide.'}
            yield {'done':True}
        self.service.transport=reading_model
        self.app.mount('/static',StaticFiles(directory=static))
        @self.app.get('/')
        def home():
            source=(static/'index.html').read_text()
            style='<style>'+(static/'design-tokens.css').read_text()+'</style>'+source[source.index('<style>'):source.index('</style>')+8]
            language='<script src="/static/language.js"></script>' if (static/'language.js').exists() else ''
            return HTMLResponse('''<!doctype html><html lang="zh"><meta charset="utf-8">'''+style+'''
            <body><input id="autoTranslateArticles" type="checkbox" hidden><nav><button onclick="goTab('copilot')">旧认知课程</button><button onclick="goTab('reading')">认知阅读</button></nav>
            <p id="notice" role="status"></p><main><div id="view-copilot"></div><div id="view-reading" style="display:none"></div></main>
            <script>
            let currentTab='copilot';
            window.Account={user:{id:'migration-test-owner',username:'owner',is_owner:true}};
            window.toast=text=>document.getElementById('notice').textContent=text;
            window.rememberLearningOrigin=()=>{};window.returnFromLesson=()=>{document.querySelector('#view-copilot .cp-reader').hidden=true;document.querySelector('.cp-management').open=true;loadCopilot();};
            window.goTab=name=>{if(currentTab==='copilot'&&name!=='copilot')window.leaveCopilot?.();currentTab=name;document.getElementById('view-copilot').style.display=name==='copilot'?'block':'none';document.getElementById('view-reading').style.display=name==='reading'?'block':'none';if(name==='reading')enterReading();else loadCopilot();};
            window.renderArticleTranslation=(parent,a,text,markdown)=>{const box=document.createElement('div');markdown(box,text);parent.append(box);return box;};
            </script>'''+language+'''<script src="/static/ai-config.js"></script><script src="/static/reading-tasks.js"></script><script src="/static/study-note-session.js"></script><script src="/static/study-notes.js"></script><script src="/static/copilot.js"></script><script src="/static/reading-growth.js"></script><script src="/static/reading-body.js"></script><script src="/static/reading.js"></script>
            </body></html>''')
        sock=socket.socket();sock.bind(('127.0.0.1',0));base='http://127.0.0.1:'+str(sock.getsockname()[1])
        server=uvicorn.Server(uvicorn.Config(self.app,log_level='error'))
        thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
        try:
            for _ in range(100):
                if server.started:break
                time.sleep(.02)
            self.assertTrue(server.started)
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True,executable_path=os.getenv('CHROME_EXECUTABLE','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'))
                try:
                    page=browser.new_page(viewport={'width':1280,'height':900},locale='zh-CN');page.set_default_timeout(10000);errors=[];failures=[]
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.on('response',lambda r:failures.append((r.status,r.url)) if r.status>=400 else None)
                    page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(base+'/') else route.abort())
                    page.goto(base)
                    page.evaluate('(config)=>AIConfig.save(config)',OWN)
                    page.get_by_role('button',name='旧认知课程',exact=True).click()
                    page.get_by_role('button',name='生成第3课草稿',exact=True).click()
                    page.get_by_role('button',name='确认保存为正式课程',exact=True).click()
                    course=page.locator('.cp-row').filter(has_text='第003课').first
                    course.get_by_role('button',name='阅读',exact=True).click()
                    # Exercise the actual timer callback before completing, so
                    # missing navigation globals cannot pass on fast machines.
                    expect(page.locator('.cp-reading-info')).not_to_contain_text('0:00 / 3:00')
                    page.get_by_role('button',name='本人确认学完',exact=True).click()
                    page.get_by_role('button',name='撤销本人完成记录',exact=True).wait_for()
                    page.screenshot(path='/tmp/grow-legacy-course-browser.png')
                    page.get_by_role('button',name='认知阅读',exact=True).click()
                    page.get_by_role('button',name='查看历史文章',exact=True).click()
                    page.get_by_role('button',name='本站阅读',exact=True).click()
                    page.get_by_role('button',name='我的笔记',exact=True).click()
                    notes=page.get_by_placeholder('哪个观点改变了我的假设？哪些证据还不够？我的思考和疑问...')
                    notes.fill('PRIVATE BROWSER NOTE')
                    page.get_by_role('button',name='保存笔记',exact=True).click()
                    page.get_by_text('笔记已保存',exact=True).wait_for()
                    page.get_by_role('button',name='生成/更新AI导读',exact=True).click()
                    page.get_by_text('已生成并保存，可随时返回查看。',exact=True).wait_for()
                    self.assertEqual(page.get_by_placeholder('哪个观点改变了我的假设？哪些证据还不够？我的思考和疑问...').input_value(),'PRIVATE BROWSER NOTE')
                    page.get_by_text('Public generated reading guide.',exact=True).filter(visible=True).wait_for()
                    page.reload()
                    page.get_by_role('button',name='我的笔记',exact=True).click()
                    self.assertEqual(page.get_by_placeholder('哪个观点改变了我的假设？哪些证据还不够？我的思考和疑问...').input_value(),'PRIVATE BROWSER NOTE')
                    page.screenshot(path='/tmp/grow-legacy-reading-browser.png')
                    self.assertFalse(errors,errors);self.assertFalse(failures,failures)
                    self.assertNotIn('PRIVATE BROWSER NOTE',json.dumps(self.repository.commits[self.repository.head]['files']))
                finally:browser.close()
        finally:
            server.should_exit=True;thread.join(timeout=10);sock.close()
