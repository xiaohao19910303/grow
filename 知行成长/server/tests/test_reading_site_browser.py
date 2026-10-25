"""On-site reading with real HTTP, PostgreSQL and recoverable GitHub publication."""
import asyncio
import json
import os
import socket
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import uvicorn
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from reading.store import DEFAULT
from test_legacy_cloud_api import CloudHTTPFixture

BODY='## Read the argument\n\n'+('\n\n'.join(f'Paragraph {i}. Evidence helps readers examine assumptions and compare explanations before drawing conclusions. ' for i in range(180)))+'\n\nTHE FINAL PARAGRAPH.'

@unittest.skipUnless(os.getenv('RUN_LEGACY_BROWSER')=='1','Opt in to Chromium acceptance')
class ReadingSiteBrowser(CloudHTTPFixture):
    @contextmanager
    def browser(self):
        from playwright.sync_api import sync_playwright
        static=Path(__file__).resolve().parents[1]/'static'
        self.app.mount('/static',StaticFiles(directory=static))
        @self.app.get('/')
        def home():
            source=(static/'index.html').read_text();style='<style>'+(static/'design-tokens.css').read_text()+'</style>'+source[source.index('<style>'):source.index('</style>')+8]
            return HTMLResponse('<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+style+'''
            <link rel="stylesheet" href="/static/reading.css"><body><main class="wrap"><p id="notice"></p><div id="view-copilot" style="display:none"></div><div id="view-reading"></div></main>
            <script>window.Account={user:{id:'test-owner',is_owner:true}};window.toast=text=>document.getElementById('notice').textContent=text;window.goTab=()=>enterReading();</script>
            <script src="/static/ai-config.js"></script><script src="/static/reading-tasks.js"></script><script src="/static/copilot.js"></script><script src="/static/reading-growth.js"></script><script src="/static/reading-body.js"></script><script src="/static/reading.js"></script></body></html>''')
        sock=socket.socket();sock.bind(('127.0.0.1',0));base='http://127.0.0.1:'+str(sock.getsockname()[1])
        server=uvicorn.Server(uvicorn.Config(self.app,log_level='error'));thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
        try:
            for _ in range(100):
                if server.started:break
                time.sleep(.02)
            self.assertTrue(server.started)
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True,executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
                page=browser.new_page(viewport={'width':1280,'height':900});page.set_default_timeout(15000)
                errors=[];external=[];popups=[]
                page.on('pageerror',lambda e:errors.append(str(e)));page.on('popup',lambda p:popups.append(p))
                def route(r):
                    if r.request.url.startswith(base+'/'):r.continue_()
                    else:external.append(r.request.url);r.abort()
                page.route('**/*',route)
                try:yield page,base
                finally:
                    self.assertFalse(errors,errors);self.assertFalse(external,external);self.assertFalse(popups)
                    browser.close()
        finally:server.should_exit=True;thread.join(timeout=10);sock.close()

    def test_auto_body_stays_in_page_preserves_notes_and_survives_restart(self):
        calls=[]
        async def content(url):
            calls.append(url);await asyncio.sleep(1.2);return BODY
        self.reader.save_preferences({**DEFAULT,'auto_guide':True})
        candidate={**self.reader.article(self.aid),'full_content':BODY}
        self.reader.put('reading_records','job-preview',{'id':'job-preview','type':'job','kind':'collect','state':'ready','created_at':'2026-10-17T12:00:00+08:00','date':'2026-10-17','daily':False,'candidates':[candidate,{**candidate,'id':'legacy-pdf','title':'Legacy PDF preview','url':'https://example.org/old.pdf','full_content':'%PDF-legacy-binary '*100}],'sources':[],'warnings':[]})
        with patch('reading.service.fetch_article_content',content),self.browser() as (page,base):
            page.goto(base);page.evaluate('enterReading()')
            page.get_by_role('button',name='查看历史文章',exact=True).click()
            page.get_by_role('heading',name='历史文章',exact=True).wait_for()
            page.get_by_role('button',name='本站阅读',exact=True).wait_for()
            self.assertEqual(page.locator('.reading-card').count(),1)
            page.get_by_role('button',name='历史搜集记录',exact=True).click()
            page.get_by_role('heading',name='历史搜集记录',exact=True).wait_for()
            page.get_by_role('button',name='查看并保存',exact=True).click()
            page.get_by_text('本站预览正文',exact=True).first.click()
            page.get_by_text('THE FINAL PARAGRAPH.',exact=True).wait_for()
            legacy=page.locator('.reading-card').filter(has_text='Legacy PDF preview');legacy.get_by_text('本站预览正文',exact=True).click()
            legacy.get_by_text('本次未取得正文。保存后可在本站尝试重新加载；当前仅有来源摘要。',exact=True).wait_for()
            self.assertNotIn('%PDF-legacy-binary',legacy.inner_text())
            page.get_by_role('button',name='返回阅读',exact=True).click()
            page.get_by_role('button',name='查看历史文章',exact=True).click()
            self.assertEqual(page.get_by_role('link',name='阅读原文 ↗').count(),0)
            page.get_by_role('button',name='本站阅读',exact=True).click()
            page.get_by_role('heading',name='文章正文',exact=True).wait_for()
            page.get_by_role('button',name='我的笔记',exact=True).click()
            notes=page.get_by_placeholder('哪个观点改变了我的假设？哪些证据还不够？我的思考和疑问...');notes.fill('PRIVATE draft while body loads')
            page.get_by_role('button',name='文章正文',exact=True).click()
            page.get_by_text('正文已保存，可直接在本站阅读。',exact=True).wait_for()
            page.get_by_text('THE FINAL PARAGRAPH.',exact=True).first.wait_for()
            self.assertEqual(len(calls),1);self.assertTrue(page.url.startswith(base+'/#reading/article/'))
            page.get_by_role('button',name='我的笔记',exact=True).click();self.assertEqual(notes.input_value(),'PRIVATE draft while body loads')
            page.get_by_role('button',name='保存笔记',exact=True).click();page.get_by_text('笔记已保存',exact=True).wait_for()
            page.get_by_role('button',name='本人确认读完',exact=True).click();page.get_by_role('button',name='改为尚未读完',exact=True).wait_for()
            page.reload();page.get_by_role('heading',name='文章正文',exact=True).wait_for()
            page.get_by_text('THE FINAL PARAGRAPH.',exact=True).first.wait_for();self.assertEqual(len(calls),1)
            self.assertTrue(self.reader.article(self.aid)['read']);self.assertEqual(self.reader.note(self.aid)['text'],'PRIVATE draft while body loads')
            self.assertEqual(self.reader.article(self.aid)['content_version'],2)
            page.set_viewport_size({'width':390,'height':844})
            self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'),page.evaluate('''() => [...document.querySelectorAll('body *')].map(el=>({tag:el.tagName,cls:el.className,left:el.getBoundingClientRect().left,right:el.getBoundingClientRect().right})).filter(el=>el.left<0||el.right>innerWidth).slice(0,15)'''))
            page.screenshot(path='/tmp/grow-reading-onsite-mobile.png',full_page=False)
            self.assertNotIn('PRIVATE draft',json.dumps(self.repository.commits[self.repository.head]['files']))

    def test_failed_body_is_not_fulltext_and_reload_does_not_retry_automatically(self):
        calls=[]
        async def content(url):calls.append(url);return None if len(calls)==1 else BODY
        with patch('reading.service.fetch_article_content',content),self.browser() as (page,base):
            page.goto(base);page.evaluate('enterReading()')
            page.get_by_role('button',name='查看历史文章',exact=True).click()
            page.get_by_role('button',name='本站阅读',exact=True).click()
            page.locator('.article-content-box [role=status]').filter(has_text='未能取得可阅读的正文').wait_for()
            page.get_by_role('heading',name='来源摘要（不是正文）',exact=True).wait_for();self.assertEqual(len(calls),1)
            self.assertFalse(self.reader.article(self.aid).get('full_content'))
            page.reload();page.locator('.article-content-box [role=status]').filter(has_text='未能取得可阅读的正文').wait_for()
            self.assertEqual(len(calls),1)
            page.get_by_role('button',name='重新加载正文',exact=True).click()
            page.get_by_text('正文已保存，可直接在本站阅读。',exact=True).wait_for();self.assertEqual(len(calls),2)
            self.assertEqual(self.reader.note(self.aid)['text'],'PRIVATE READING NOTE')

    def test_short_pasted_body_is_readable_without_network_fetch(self):
        self.reader.import_from_paste('My short saved article','Short body.')
        async def content(url):self.fail('A pasted body must never trigger a source request')
        with patch('reading.service.fetch_article_content',content),self.browser() as (page,base):
            page.goto(base);page.evaluate('enterReading()')
            page.get_by_role('button',name='查看历史文章',exact=True).click()
            page.locator('.reading-card').filter(has_text='My short saved article').get_by_role('button',name='本站阅读',exact=True).click()
            page.get_by_text('已保存的正文，可直接在本站阅读。',exact=True).wait_for()
            page.locator('.article-content-box:visible .article-full-content').get_by_text('Short body.',exact=True).wait_for()
