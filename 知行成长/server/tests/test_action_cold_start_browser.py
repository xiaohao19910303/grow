"""Actual homepage/Chrome cold-start test with an in-memory HTTP contract fake.

No PostgreSQL or external service is used; real account/DB acceptance remains in
test_accounts.py. ACTION_COLD_START_REPLAY_OLD_CLIENT=1 replays the old addTask
source in HTTP responses only, without changing production files on disk.
"""
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import unittest
from urllib.parse import urlsplit
import uuid

from playwright.sync_api import expect, sync_playwright


@unittest.skipUnless(os.getenv('RUN_GITHUB_BROWSER')=='1','Opt in to isolated Chrome')
class ActionColdStartBrowser(unittest.TestCase):
    def setUp(self):
        static=Path(__file__).resolve().parents[1]/'static'
        source=(static/'action-plans.js').read_text()
        if os.getenv('ACTION_COLD_START_REPLAY_OLD_CLIENT')=='1':
            current='async function addTask(title,date){\n    await initialized;await load();requireP0();'
            old='async function addTask(title,date){\n    await initialized;requireP0();'
            self.assertEqual(source.count(current),1,'old-client replay must replace exactly the current addTask readiness check')
            source=source.replace(current,old,1)
        self.plans=[];self.submitted=[];self.operations={};self.lock=threading.Lock()
        owner=self

        class Handler(SimpleHTTPRequestHandler):
            def log_message(self,*_args):
                pass

            def reply(self,value,kind='application/json',status=200):
                raw=value if isinstance(value,bytes) else json.dumps(value).encode()
                self.send_response(status);self.send_header('Content-Type',kind)
                self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

            def do_GET(self):
                path=urlsplit(self.path).path
                if path=='/favicon.ico':
                    return self.reply(b'','image/x-icon',status=204)
                if path=='/static/action-plans.js':
                    return self.reply(source.encode(),'text/javascript;charset=utf-8')
                if path=='/api/auth/me':
                    return self.reply({'user':{'id':'cold-start-fixture','username':'tester','is_owner':False}})
                if path=='/api/data':
                    return self.reply(dict(modules=[],checkins={},habits={},customFields=[],customRecords=[],decisions=[],predictions=[],reviews=[],insights=[],todos=[],_revision='cold-start-fixture'))
                if path=='/api/action-plans':
                    with owner.lock:
                        return self.reply({'plans':list(owner.plans),'execution':None,'server_time':datetime.now(timezone.utc).isoformat(),'action_schema_version':2,'capabilities':{'nullable_schedule':True,'completion_modes':['check','time','content']}})
                if path.startswith('/api/'):
                    return self.reply(dict(modules=[],checkins={},lessons=[],plans=[],records=[],items=[],articles=[],jobs=[],entries=[],reports=[],stats={},preferences={},budget={},attempts=[],legacy=[],drafts=[],nodes=[],edges=[],total=0,page=1,page_size=20))
                self.path=self.path.removeprefix('/static')
                super().do_GET()

            def do_POST(self):
                if urlsplit(self.path).path!='/api/action-plans':
                    return self.reply({'message':'Unexpected fixture write'},status=404)
                body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
                with owner.lock:
                    owner.submitted.append(body)
                    if body['key'] not in owner.operations:
                        plan={**body,'id':'cold-'+str(len(owner.plans)+1),'revision':1,'status':'active','blocked':False,'timezone':'Asia/Shanghai','horizon':'short','target':None,'target_count':1,'target_minutes':None,'minimum_minutes':None,'at':None,'reminder':False,'progress':{'minutes':0,'completed':0,'minimum':0,'partial':0,'interrupted':0}}
                        owner.plans.append(plan);owner.operations[body['key']]={'plans':[plan]}
                    return self.reply(owner.operations[body['key']])

        self.server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(static)))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.stop_server)
        self.base='http://127.0.0.1:'+str(self.server.server_port)
        self.playwright=sync_playwright().start();self.addCleanup(self.playwright.stop)
        self.browser=self.playwright.chromium.launch(headless=True,executable_path=os.getenv('CHROME_EXECUTABLE','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'))
        self.addCleanup(self.browser.close)
        self.context=self.browser.new_context(viewport={'width':1280,'height':960});self.addCleanup(self.context.close)
        self.page=self.context.new_page();self.page.set_default_timeout(10000);self.errors=[]
        self.page.on('pageerror',lambda error:self.errors.append(str(error)))
        self.page.on('console',lambda message:self.errors.append(message.text) if message.type=='error' else None)
        self.page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(self.base+'/') else route.abort())

    def stop_server(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)

    def tearDown(self):
        self.assertEqual(self.errors,[])

    def test_first_todo_waits_for_action_snapshot_without_losing_or_duplicating_input(self):
        held=[];released=False
        def hold_first_snapshot(route):
            if route.request.method=='GET' and not released:held.append(route)
            else:route.continue_()
        self.page.route(self.base+'/api/action-plans',hold_first_snapshot)
        try:
            self.page.goto(self.base)
            expect(self.page.locator('#storageStatus')).to_have_text('已连接个人数据库')
            self.assertGreaterEqual(len(held),1,'initial action snapshots are held while general state is ready')
            self.assertIsNone(self.page.evaluate('ActionPlans.snapshot().action_schema_version ?? null'))
            self.page.evaluate('''() => {const original=ActionPlans.addTask;window.firstTodoCalls=0;
              ActionPlans.addTask=(...args)=>{window.firstTodoCalls++;return original(...args);};}''')
            title=uuid.uuid4().hex[:8]+'首次打开直接记录'
            field=self.page.locator('#todoInput0');field.fill(title);field.press('Enter')
            self.page.wait_for_function('window.firstTodoCalls===1')
            self.assertEqual(self.submitted,[])
            expect(field).to_have_value(title)
            with self.page.expect_response(lambda response:response.request.method=='POST' and response.url==self.base+'/api/action-plans') as saved:
                released=True
                for route in held:route.continue_()
            self.assertEqual(saved.value.status,200,saved.value.text())
            expect(self.page.get_by_text(title,exact=True)).to_be_visible()
            expect(field).to_have_value('')
            self.assertEqual(len(self.submitted),1)
            self.assertEqual(self.submitted[0]['title'],title)
            self.assertEqual(sum(plan['title']==title for plan in self.plans),1)
            evidence=Path(os.getenv('ACTION_P0_EVIDENCE_DIR','/tmp/grow-action-cold-start-evidence'))
            evidence.mkdir(parents=True,exist_ok=True);self.page.screenshot(path=str(evidence/'cold-first-todo.png'))
        finally:
            if held and not released:
                released=True
                for route in held:route.continue_()


if __name__=='__main__':unittest.main(verbosity=2)
