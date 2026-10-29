"""Real browser source selection, persistence and failure preservation; synthetic data."""
import socket
import threading
import time
from pathlib import Path
from unittest.mock import patch

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import sync_playwright,expect

from copilot.core import Problem
from investments.api import register
from test_legacy_cloud_schema import PostgreSQLFixture


class InvestmentAKShareBrowserTests(PostgreSQLFixture):
    def test_source_switching_stock_etf_and_failure_keep_previous_data(self):
        app=FastAPI();store=register(app);store.initialize()
        account=store.create('accounts',{'name':'行情界面测试','baseline_date':'2026-10-26','opening_cash':'0'},'a')
        stock=store.create('instruments',{'code':'600000','name':'合成股票','market':'SSE','kind':'stock'},'s')
        etf=store.create('instruments',{'code':'159915','name':'合成ETF','market':'SZSE','kind':'etf'},'e')
        calls=[];reject=[False]
        def load(*args):
            calls.append(args)
            if reject[0]:raise Problem('provider_unavailable','合成取数失败，未自动换源。',502)
            return {'library_version':'test','rows':[{'日期':'2026-10-27','开盘':'1.2','最高':'1.4','最低':'1.1',
                '收盘':'1.3','成交量':'100','成交额':'13000'}]}
        mock=patch('investments.akshare_daily.load_rows',side_effect=load);mock.start();self.addCleanup(mock.stop)
        static=Path(__file__).resolve().parents[1]/'static'
        app.mount('/static',StaticFiles(directory=static))
        @app.get('/')
        def index():
            return HTMLResponse('''<!doctype html><html lang="zh"><meta charset="utf-8">
                <meta name="viewport" content="width=device-width,initial-scale=1">
                <link rel="stylesheet" href="/static/design-tokens.css"><link rel="stylesheet" href="/static/investments.css">
                <div id="investment-workspace"></div><script src="/static/investments.js"></script>
                <script src="/static/investment-market.js"></script><script>Investments.open()</script></html>''')
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(app,log_level='error'));thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True)
        thread.start();self.addCleanup(lambda:thread.join(5));self.addCleanup(lambda:setattr(server,'should_exit',True))
        for _ in range(100):
            if server.started:break
            time.sleep(.02)
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
            page=browser.new_page(viewport={'width':390,'height':844});page.set_default_timeout(5000)
            page.clock.install(time='2026-10-28T09:00:00+08:00')
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{port}')
            for instrument in [stock,etf]:
                page.get_by_role('button',name='添加盘后行情',exact=True).click()
                self.assertEqual(page.locator('dialog').count(),1,{'errors':errors,'status':page.locator('[data-inv-status]').inner_text()})
                page.get_by_label('接入方式').select_option('akshare')
                expect(page.get_by_label('Tushare Token',exact=True)).to_be_hidden()
                page.get_by_label('行情标的').select_option(instrument['id'])
                page.get_by_label('开始日期',exact=True).fill('2026-10-23');page.get_by_label('结束日期',exact=True).fill('2026-10-27')
                page.get_by_label('我已核对所选来源的资料使用范围，确认获取未复权盘后日线。',exact=True).check()
                page.get_by_role('button',name='保存行情与研究证据',exact=True).click()
                expect(page.get_by_text('已保存 1 条日线及研究证据。最后数据日 2026-10-27；来源 东方财富（AKShare）。',exact=True)).to_be_visible()
                page.get_by_role('button',name='关闭',exact=True).click()
            page.reload()
            expect(page.get_by_text('合成ETF · 东方财富盘后行情 2026-10-27',exact=True)).to_be_visible()
            reject[0]=True
            page.get_by_role('button',name='添加盘后行情',exact=True).click()
            mode=page.get_by_label('接入方式')
            mode.select_option('tushare');expect(page.get_by_label('Tushare Token',exact=True)).to_be_visible()
            mode.select_option('csv');expect(page.get_by_label('原成交额单位')).to_be_visible()
            mode.select_option('akshare')
            page.get_by_label('开始日期',exact=True).fill('2026-10-23');page.get_by_label('结束日期',exact=True).fill('2026-10-27')
            page.get_by_label('我已核对所选来源的资料使用范围，确认获取未复权盘后日线。',exact=True).check()
            page.get_by_role('button',name='保存行情与研究证据',exact=True).click()
            expect(page.get_by_text('合成取数失败，未自动换源。',exact=True)).to_be_visible()
            expect(mode).to_have_value('akshare')
            self.assertEqual(store.listing('research',account_id=account['id'])['total'],2)
            self.assertEqual([c[0] for c in calls[:2]],['stock','etf'])
            self.assertEqual(len(calls),3);self.assertEqual(errors,[])
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),390)
            page.screenshot(path='/tmp/grow-akshare-390.png',full_page=True)
            page.set_viewport_size({'width':1440,'height':1000})
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),1440)
            browser.close()
