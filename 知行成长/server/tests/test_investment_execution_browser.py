"""A real browser saves hypothetical execution and retrieves the frozen result after reload."""
import os
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
from test_legacy_cloud_schema import PostgreSQLFixture
from investments.api import register
from investments.replay import import_path

class ExecutionStudyBrowserTests(PostgreSQLFixture):
    def test_mobile_study_and_desktop_history_preserve_costs_and_actual_ledger(self):
        app=FastAPI();store=register(app);store.initialize()
        for target in ('store','replay','execution_studies'):
            p=patch('investments.'+target+'.now',return_value='2026-10-28T16:00:00+08:00');p.start();self.addCleanup(p.stop)
        a=store.create('accounts',{'name':'撮合验收','baseline_date':'2026-10-26','opening_cash':'10000'},'a')
        i=store.create('instruments',{'code':'600000','market':'SSE','kind':'stock','name':'合成股票'},'i')
        store.create('plan-checks',{'instrument_id':i['id'],'quote_price':'10','quote_as_of':'2026-10-26T15:00:00+08:00',
            'sessions':{'2026-10-27':True,'2026-10-28':True},'rules_valid_from':'2026-10-27','rules_valid_until':'2026-10-28',
            'price_tick':'0.01','quantity_step':'100','minimum_quantity':'100','sell_delay_sessions':1,'trading_status':'normal',
            'source_url':'https://example.com/declared','source_note':'本人合成核对资料','acknowledged':True},'check')
        path=import_path(store,{'account_id':a['id'],'instrument_id':i['id'],
            'text':'start,open,high,low,close,volume,amount\n2026-10-27T14:59:00+08:00,10,10.5,9.5,10,10000,100000\n2026-10-28T09:30:00+08:00,11,12,10.5,11,10000,110000\n',
            'source_label':'仅验收合成跨日路径','volume_unit':'shares','amount_unit':'cny','price_basis':'unadjusted','use_confirmed':True},'path')
        static=Path(__file__).resolve().parents[1]/'static';app.mount('/static',StaticFiles(directory=static))
        @app.get('/')
        def index():return HTMLResponse('''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/static/design-tokens.css"><link rel="stylesheet" href="/static/investments.css"><div id="investment-workspace"></div><script src="/static/investments.js"></script><script src="/static/investment-market.js"></script><script>Investments.open()</script></html>''')
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(app,log_level='error'));thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
        self.addCleanup(lambda:thread.join(5));self.addCleanup(lambda:setattr(server,'should_exit',True))
        for _ in range(100):
            if server.started:break
            time.sleep(.02)
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
            page=browser.new_page(viewport={'width':390,'height':900});page.set_default_timeout(7000);page.clock.install(time='2026-10-28T16:00:00+08:00')
            errors=[];calls=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:calls.append(r.url))
            page.goto(f'http://127.0.0.1:{port}');page.get_by_role('tab',name='复盘与策略',exact=True).click()
            page.get_by_role('button',name='撮合情景验证',exact=True).click()
            expect(page.get_by_role('button',name='保存撮合情景',exact=True)).to_be_enabled()
            for label,value in {'情景标题':'含费用的跨日假设','假设初始现金':'10000','期望买入数量':'100','假设失效价':'9','假设目标价':'11',
                '双边佣金万分率':'0','每笔最低佣金（元）':'1','卖出税万分率':'0','单边滑点万分率':'0','每分钟量占比上限（0到1之间）':'0.1',
                '撮合资料与假设说明':'仅合成验收，不能证明真实收益'}.items():page.get_by_label(label,exact=True).fill(value)
            page.get_by_label('每日状态CSV',exact=True).fill('date,status,limit_down,limit_up,available_at,corporate_action\n2026-10-27,normal,8,13,2026-10-27T08:00:00+08:00,none_declared\n2026-10-28,normal,8,13,2026-10-28T08:00:00+08:00,none_declared\n')
            page.get_by_label('我确认这是声明路径的假设撮合，不能证明历史收益或真实可成交',exact=True).check()
            page.get_by_role('button',name='保存撮合情景',exact=True).click()
            expect(page.get_by_text('完整假设净已实现 98 元 · 剩余数量 0',exact=True)).to_be_visible()
            self.assertTrue(page.get_by_role('dialog').evaluate('d=>d.scrollWidth<=d.clientWidth'))
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),390)
            evidence=Path(os.getenv('INVESTMENT_EXECUTION_EVIDENCE_DIR','/tmp/grow-investment-execution'));evidence.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(evidence/'execution-390.png'),full_page=True)
            page.get_by_role('button',name='关闭',exact=True).click()
            page.set_viewport_size({'width':1440,'height':1000});page.reload()
            page.get_by_role('tab',name='复盘与策略',exact=True).click();page.get_by_role('button',name='撮合情景验证',exact=True).click()
            page.get_by_role('button',name='查看已存撮合情景',exact=True).click()
            expect(page.get_by_text('完整假设净已实现 98 元 · 剩余数量 0',exact=True)).to_be_visible()
            page.get_by_text('原始假设、依据与限制',exact=True).click()
            expect(page.get_by_text('输入现金 10000 · 期望数量 100 · 分钟量占比上限 0.1',exact=True)).to_be_visible()
            self.assertTrue(page.get_by_role('dialog').evaluate('d=>d.scrollWidth<=d.clientWidth'))
            page.screenshot(path=str(evidence/'execution-1440.png'),full_page=True)
            self.assertEqual(store.balance(a['id'])['cash'],'10000');self.assertEqual(store.listing('fills',account_id=a['id'])['total'],0)
            self.assertFalse(any('/provider/' in url or '/analysis/jobs' in url for url in calls));self.assertEqual(errors,[])
            browser.close()
