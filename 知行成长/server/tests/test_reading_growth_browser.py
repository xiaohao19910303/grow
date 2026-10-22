"""Real Chromium against private PostgreSQL records and a simulated personal model."""
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
from reading.store import DEFAULT
from test_legacy_cloud_api import CloudHTTPFixture, OWN

GUIDE='''# 用证据改善判断

## 中文导读
文章讨论如何根据证据判断，提醒读者区分事实和解释，主动查找相反观点。阅读时应先识别主张，再检查证据的来源以及适用条件。

## 核心观点
- 先提出可以核验的问题，明确判断标准。
- 区分观察到的事实与个人解释，避免混淆。
- 寻找反例和相反证据，避免过早下结论。

## 证据与边界
本文讨论判断方法，不能据此断言某种做法在所有场景都有效，仍需检查具体条件。

## 英文阅读提示
evidence：证据；decision：判断；careful：审慎。识别主张之后，再找作者使用的限定词。

## 联系实际
下一次工作讨论中，你可以检验哪项假设？先写下一个反例，再说清判断的依据。
'''


@unittest.skipUnless(os.getenv('RUN_LEGACY_BROWSER')=='1','Opt in to Chromium acceptance')
class ReadingGrowthBrowser(CloudHTTPFixture):
    def test_automatic_guide_feedback_search_cache_and_mobile(self):
        from playwright.sync_api import sync_playwright
        self.reader.save_preferences({**DEFAULT,'auto_guide':True})
        self.reader.save_full_text(self.aid,'Evidence supports careful decisions. '*30)
        calls=[]
        async def model(messages,cfg):
            self.assertEqual(cfg['key'],OWN['api_key']);calls.append(messages)
            yield {'text':GUIDE};yield {'done':True}
        self.service.transport=model
        static=Path(__file__).resolve().parents[1]/'static'
        self.app.mount('/static',StaticFiles(directory=static))
        @self.app.get('/')
        def home():
            source=(static/'index.html').read_text()
            style=source[source.index('<style>'):source.index('</style>')+8]
            return HTMLResponse('<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'+style+'''
            <link rel="stylesheet" href="/static/reading.css"><body><main><p id="notice"></p><div id="view-copilot" style="display:none"></div><div id="view-reading"></div></main>
            <script>window.Account={user:{id:'test-owner',is_owner:true}};
            window.toast=text=>document.getElementById('notice').textContent=text;
            window.goTab=()=>enterReading();
            window.renderArticleTranslation=(parent,a,text,markdown)=>markdown(parent,text);
            </script><script src="/static/ai-config.js"></script><script src="/static/copilot.js"></script>
            <script src="/static/reading-growth.js"></script><script src="/static/reading-body.js"></script><script src="/static/reading.js"></script></body></html>''')
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
                    page=browser.new_page(viewport={'width':1280,'height':900},locale='zh-CN');page.set_default_timeout(12000)
                    errors=[];failures=[]
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.on('response',lambda r:failures.append((r.status,r.url)) if r.status>=400 else None)
                    page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(base+'/') else route.abort())
                    page.goto(base);page.evaluate('(config)=>AIConfig.save(config)',OWN);page.evaluate('enterReading()')
                    page.get_by_role('button',name='查看历史文章',exact=True).click()
                    page.get_by_role('button',name='本站阅读',exact=True).click()
                    self.assertEqual(len(calls),0)
                    page.get_by_role('button',name='中文导读',exact=True).click()
                    page.get_by_text('中文导读已保存，下次打开可直接阅读。',exact=True).wait_for()
                    page.get_by_role('heading',name='核心观点',exact=True).wait_for()
                    self.assertEqual(len(calls),1);self.assertNotIn('PRIVATE',str(calls))
                    page.get_by_role('button',name='阅读反馈',exact=True).click()
                    page.get_by_label('这篇对我的价值').select_option('insightful')
                    page.get_by_label('阅读难度').select_option('right')
                    page.get_by_label('一句话收获').fill('PRIVATE 用反例检查判断')
                    page.get_by_text('补充疑问、应用行动和标签',exact=True).click()
                    page.get_by_label('我仍有的疑问').fill('PRIVATE 如何判断来源可信')
                    page.get_by_label('准备怎么用').fill('PRIVATE 下次开会先讲证据')
                    page.get_by_label('回查标签（用逗号分隔）').fill('反例，判断')
                    page.get_by_role('button',name='保存反馈并标记读完',exact=True).click()
                    page.get_by_text('反馈已保存，已标记读完。可用标签、收获或疑问搜索找回。',exact=True).wait_for()
                    page.get_by_role('button',name='改为尚未读完',exact=True).wait_for()
                    page.get_by_label('一句话收获').fill('PRIVATE 未保存的新收获')
                    page.once('dialog',lambda dialog:dialog.dismiss())
                    page.get_by_role('button',name='返回历史文章',exact=True).click()
                    self.assertEqual(page.get_by_label('一句话收获').input_value(),'PRIVATE 未保存的新收获')
                    page.get_by_role('button',name='仅保存反馈',exact=True).click()
                    page.get_by_text('反馈已保存。可用标签、收获或疑问搜索找回。',exact=True).wait_for()
                    page.get_by_role('button',name='返回历史文章',exact=True).click()
                    page.get_by_role('button',name='有反馈',exact=True).click()
                    page.get_by_role('searchbox',name='搜索历史文章',exact=True).fill('未保存的新收获')
                    page.get_by_role('button',name='查看反馈',exact=True).click()
                    self.assertEqual(page.get_by_label('一句话收获').input_value(),'PRIVATE 未保存的新收获')
                    page.reload();page.get_by_role('button',name='中文导读',exact=True).click();page.get_by_role('heading',name='核心观点',exact=True).wait_for()
                    self.assertEqual(len(calls),1)
                    page.screenshot(path='/tmp/grow-reading-growth-desktop.png',full_page=True)
                    page.set_viewport_size({'width':390,'height':844})
                    page.get_by_role('button',name='阅读反馈',exact=True).click()
                    self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'))
                    self.assertEqual(page.get_by_label('一句话收获').input_value(),'PRIVATE 未保存的新收获')
                    page.screenshot(path='/tmp/grow-reading-growth-mobile.png',full_page=True)
                    self.assertFalse(errors,errors);self.assertFalse(failures,failures)
                    self.assertEqual(self.reader.note(self.aid)['text'],'PRIVATE READING NOTE')
                    serialized=json.dumps(self.repository.commits[self.repository.head]['files'])
                    self.assertNotIn('PRIVATE',serialized);self.assertNotIn(OWN['api_key'],serialized)
                    self.assertNotIn(OWN['api_key'],json.dumps(self.reader.article(self.aid)))
                finally:browser.close()
        finally:
            server.should_exit=True;thread.join(timeout=10);sock.close()
