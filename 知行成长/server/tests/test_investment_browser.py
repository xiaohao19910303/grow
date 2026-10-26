"""Actual component, HTTP and PostgreSQL in Chromium; no provider calls."""
import socket
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import sync_playwright, expect

from investments.api import register
from test_legacy_cloud_schema import PostgreSQLFixture


class InvestmentBrowserTests(PostgreSQLFixture):
    def test_three_views_record_and_restore_partial_trade(self):
        app=FastAPI()
        store=register(app);store.initialize()
        static=Path(__file__).resolve().parents[1]/'static'
        app.mount('/static',StaticFiles(directory=static))
        @app.get('/')
        def index():
            return HTMLResponse('''<!doctype html><html lang="zh"><meta charset="utf-8">
                <meta name="viewport" content="width=device-width,initial-scale=1">
                <link rel="stylesheet" href="/static/design-tokens.css">
                <link rel="stylesheet" href="/static/investments.css">
                <div id="investment-workspace"></div>
                <script src="/static/investments.js"></script><script>Investments.open()</script></html>''')
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
        thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
        self.addCleanup(lambda:thread.join(5))
        self.addCleanup(lambda:setattr(server,'should_exit',True))
        for _ in range(100):
            if server.started:break
            time.sleep(.02)
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True,
                executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
            page=browser.new_page(viewport={'width':390,'height':844})
            page.set_default_timeout(5000)
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{port}')
            page.get_by_role('button',name='新建账户',exact=True).click()
            page.get_by_label('账户名称').fill('测试账户')
            page.get_by_label('期初现金').fill('10000')
            page.get_by_role('button',name='保存',exact=True).click()
            expect(page.get_by_label('当前账户')).to_contain_text('测试账户')
            page.get_by_role('button',name='添加标的',exact=True).click()
            page.get_by_label('证券代码').fill('510000')
            page.get_by_label('证券名称').fill('测试ETF')
            page.get_by_role('button',name='保存',exact=True).click()
            page.get_by_role('tab',name='交易簿',exact=True).click()
            page.get_by_role('button',name='记录成交',exact=True).click()
            page.get_by_label('成交价格').fill('1.231')
            page.get_by_label('成交数量').fill('1000')
            page.get_by_label('手续费').fill('1')
            page.get_by_label('税费').fill('0')
            page.get_by_role('button',name='保存',exact=True).click()
            expect(page.get_by_text('1.231',exact=True)).to_be_visible()
            page.reload()
            page.get_by_role('tab',name='交易簿',exact=True).click()
            expect(page.get_by_text('1.231',exact=True)).to_be_visible()
            page.get_by_role('tab',name='复盘与策略',exact=True).click()
            page.get_by_role('button',name='写复盘',exact=True).click()
            page.get_by_label('复盘原文').fill('今日按计划观察，等待公告。')
            page.get_by_role('button',name='保存',exact=True).click()
            expect(page.get_by_text('今日按计划观察，等待公告。',exact=True)).to_be_visible()
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),390)
            self.assertEqual(errors,[])
