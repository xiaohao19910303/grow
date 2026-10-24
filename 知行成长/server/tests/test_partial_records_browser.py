"""Real browser download/reset UX against the real application and disposable PG."""
import json
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from playwright.sync_api import sync_playwright
import test_accounts as accounts_fixture

class PartialRecordBrowser(unittest.TestCase):
    def test_download_scope_and_failed_then_confirmed_reset(self):
        fixture=accounts_fixture.AccountIntegrationTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.login('owner',fixture.env.values['APP_PASSWORD'])
        client=fixture.client;h={**fixture.headers,'X-Legacy-State-Protocol':'1','X-Grow-Action-Schema':'2'}
        state=client.get('/api/data').json();state['reviews']=[{'date':'2026-10-22','thought':'LEGACY COPY RECORD'}]
        saved=client.put('/api/data',json=state,headers=h);self.assertEqual(saved.status_code,200,saved.text)
        action=client.post('/api/action-plans',json={'title':'ACTION MUST REMAIN','period':'day','completion_mode':'check','start_date':None,'end_date':None,'key':'partial-copy-action'},headers=h)
        self.assertEqual(action.status_code,200,action.text)
        note=client.put('/api/study-notes/renzhi/1',json={'notes':'NOTE MUST REMAIN','answers':{},'version':'a'*64,'revision':0,'key':'partial-copy-note'},headers=h);self.assertEqual(note.status_code,200,note.text)
        with sync_playwright() as p, ExitStack() as resources:
            chrome='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
            browser=p.chromium.launch(headless=True,**({'executable_path':chrome} if Path(chrome).is_file() else {}));resources.callback(browser.close)
            context=browser.new_context(accept_downloads=True);resources.callback(context.close)
            errors=[];page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)));fail=[True]
            def route(request):
                req=request.request
                if req.url.startswith('https://learning.example/'):
                    if req.method=='PUT' and req.url.endswith('/api/data') and fail[0]:
                        request.fulfill(status=503,content_type='application/json',body='{"message":"synthetic unavailable"}');return
                    response=client.request(req.method,req.url,content=req.post_data_buffer,headers={k:v for k,v in req.headers.items() if k.lower() not in ('host','cookie','content-length')})
                    request.fulfill(status=response.status_code,headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-encoding','content-length','transfer-encoding')},body=response.content)
                else:request.abort()
            context.route('**/*',route)
            page.goto('https://learning.example/');page.locator('#storageStatus').filter(has_text='已连接').wait_for()
            page.evaluate("goTab('settings')")
            page.get_by_role('button',name='导出局部记录副本',exact=True).wait_for()
            with page.expect_download() as download:page.get_by_role('button',name='导出局部记录副本',exact=True).click()
            with tempfile.TemporaryDirectory() as temp:
                path=Path(temp)/'partial.json';download.value.save_as(path);copy=json.loads(path.read_text())
            self.assertIn('LEGACY COPY RECORD',json.dumps(copy));self.assertNotIn('ACTION MUST REMAIN',json.dumps(copy));self.assertNotIn('NOTE MUST REMAIN',json.dumps(copy))
            self.assertTrue(download.value.suggested_filename.startswith('grow-partial-records-'))
            page.get_by_text('清空局部表单记录',exact=True).click();page.get_by_role('button',name='重置',exact=True).click()
            page.get_by_role('button',name='确认清空局部记录',exact=True).click();page.locator('#resetResult').filter(has_text='失败或结果未确认').wait_for()
            self.assertEqual(len(client.get('/api/data').json()['reviews']),1)
            fail[0]=False;page.get_by_role('button',name='确认清空局部记录',exact=True).click()
            page.locator('#storageStatus').filter(has_text='局部表单记录已清空').wait_for()
            self.assertEqual(client.get('/api/data').json()['reviews'],[])
            self.assertEqual(client.get('/api/action-plans').json()['plans'][0]['title'],'ACTION MUST REMAIN')
            self.assertEqual(client.get('/api/study-notes/renzhi/1').json()['notes'],'NOTE MUST REMAIN')
            self.assertEqual(errors,[])
