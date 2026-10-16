"""Real Chromium, actual plan UI/API, temporary DB, simulated GitHub and model."""
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from copilot.core import Problem
from plans.api import register
from plans.github import GitHubContent
from test_github_plans import Repository, SQLitePlans, D, content


@unittest.skipUnless(os.getenv('RUN_GITHUB_BROWSER') == '1', 'Opt in with RUN_GITHUB_BROWSER=1 and install playwright')
class BrowserLifecycle(unittest.TestCase):
    def test_generate_publish_read_and_reload(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as tmp:
            repository = Repository()
            storage = GitHubContent('owner/courses', 'main', 'TEST_ONLY_TOKEN', transport=httpx.MockTransport(repository))
            store = SQLitePlans('/no-content-directory', '/no-runtime-directory', storage)
            store.db_file = Path(tmp)/'test.db'; store.initialize()
            app = FastAPI()
            @app.exception_handler(Problem)
            async def problem(request, exc):return JSONResponse({'message':exc.message}, status_code=exc.status)
            with patch('plans.api.make_store', return_value=store):
                _, generator = register(app, '/missing', '/missing')
            async def model(messages, config):
                ctx = json.loads(messages[1]['content'])
                yield {'text':json.dumps(D) if 'schema' in ctx else content(ctx)+'\n<!-- COPILOT_SOURCES -->\n摘要 [来源](https://example.org/lesson)'}
                yield {'done':True}
            generator.transport = model
            app.mount('/static', StaticFiles(directory=Path(__file__).resolve().parents[1]/'static'))
            @app.get('/')
            def index():
                return HTMLResponse('''<!doctype html><html lang="zh"><meta charset="utf-8"><body>
                <div id="notices" role="status"></div><div id="view-copilot" hidden></div>
                <div id="view-plans"></div><div id="dailyReader" hidden></div>
                <script>
                window.toast=t=>document.getElementById('notices').textContent=t;
                window.goTab=name=>{document.getElementById('view-plans').style.display=name==='plans'?'block':'none';if(name==='plans')window.enterPlans();};
                window.rememberLearningOrigin=()=>{};window.returnFromLesson=()=>goTab('plans');
                </script><script src="/static/copilot.js"></script><script src="/static/plans.js"></script>
                <script>window.addEventListener('load',()=>window.loadPlans());</script></body></html>''')
            sock = socket.socket(); sock.bind(('127.0.0.1', 0))
            base = 'http://127.0.0.1:'+str(sock.getsockname()[1])
            server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
            thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True); thread.start()
            try:
                for _ in range(100):
                    if server.started: break
                    time.sleep(.02)
                self.assertTrue(server.started)
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True, executable_path=os.getenv('CHROME_EXECUTABLE', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'))
                    try:
                        page = browser.new_page(); errors = []
                        page.on('pageerror', lambda e: errors.append(str(e)))
                        page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base+'/') else route.abort())
                        page.goto(base)
                        page.get_by_role('button', name='创建学习计划', exact=True).click()
                        for name, value in [('学习方向','经济学'),('希望学会什么','理解经济新闻'),('周期（周）','2'),('每周学习次数','1'),('每次分钟数','20')]:
                            page.get_by_label(name, exact=True).fill(value)
                        page.get_by_role('button', name='让AI生成规划草稿').click()
                        page.get_by_label('已阅读这份草稿，确认将其正式保存').check()
                        page.get_by_role('button', name='采用这份规划', exact=True).click()
                        page.get_by_role('button', name='准备本课资料', exact=True).click()
                        page.get_by_label('标题（书名/文章名/主题）', exact=True).fill('教学资料')
                        page.get_by_label('内容（链接、书名、或粘贴相关资料）', exact=True).fill('明确选择的教学摘要 https://example.org/lesson')
                        page.get_by_role('button', name='保存', exact=True).click()
                        page.get_by_role('button', name='生成下一课草稿', exact=True).click()
                        page.get_by_label('已阅读这份草稿，确认将其正式保存').check()
                        page.get_by_role('button', name='保存正式课程', exact=True).click()
                        page.get_by_role('button', name='阅读', exact=True).click()
                        reader = page.locator('#dailyReader')
                        reader.get_by_role('heading', name='核心概念', exact=True).wait_for()
                        link = reader.get_by_role('link', name='在 GitHub 打开课程', exact=True)
                        self.assertTrue(link.get_attribute('href').startswith('https://github.com/owner/courses/blob/'))
                        page.get_by_text('参考资料与边界', exact=True).click()
                        reader.get_by_role('link', name='在 GitHub 打开参考资料', exact=True).wait_for()
                        page.get_by_label('本课反馈（可选，填写后保存；不会自动发送给AI）').fill('PRIVATE BROWSER NOTE')
                        page.get_by_role('button', name='本人确认学完', exact=True).click()
                        page.get_by_text('已记录本人反馈', exact=True).wait_for()
                        self.assertNotIn('PRIVATE BROWSER NOTE', json.dumps(repository.commits[repository.head]['files']))
                        pid = store.rows('learning_plans')[0]['id']
                        # Fresh storage instance has no cache or content directory.
                        fresh = GitHubContent('owner/courses', 'main', 'TEST_ONLY_TOKEN', transport=httpx.MockTransport(repository))
                        store.content = fresh
                        self.assertIn('核心概念', store.read_course(pid, 1)['content'])
                        page.reload()
                        page.get_by_role('button', name='查看计划', exact=True).click()
                        page.get_by_role('button', name='阅读', exact=True).click()
                        reader.get_by_role('heading', name='核心概念', exact=True).wait_for()
                        self.assertEqual(errors, [])
                    finally:browser.close()
            finally:
                server.should_exit = True; thread.join(timeout=10); sock.close()


if __name__ == '__main__':unittest.main()
