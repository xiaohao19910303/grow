"""Real mobile forms for declared path replay and prospective registration; no model."""
import json
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

class InvestmentOfflineBrowserTests(PostgreSQLFixture):
    def test_path_scrubbing_and_frozen_forward_trial(self):
        app=FastAPI();store=register(app);store.initialize();calls=[]
        for target in ('store','planning','replay','experiments'):
            p=patch('investments.'+target+'.now',return_value='2026-10-28T09:00:00+08:00');p.start();self.addCleanup(p.stop)
        a=store.create('accounts',{'name':'离线验收','baseline_date':'2026-10-26','opening_cash':'10000'},'a')
        i=store.create('instruments',{'code':'600000','market':'SSE','kind':'stock','name':'合成股票'},'i')
        strategy=store.create('strategies',{'title':'合成前向策略','entry_conditions':'条件明确','exit_conditions':'出现反证','validation_scope':'先观察'},'s')
        store.transition('strategies',strategy['id'],1,'confirmed','sc')
        for side,price,at in [('buy','10','10:00'),('sell','11','10:02')]:
            store.create('fills',{'account_id':a['id'],'instrument_id':i['id'],'side':side,'price':price,'quantity':'100',
                'fee':'1','tax':'0','executed_at':'2026-10-27T'+at+':00+08:00'},side)
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
            page=browser.new_page(viewport={'width':390,'height':900});page.clock.install(time='2026-10-28T09:00:00+08:00');page.set_default_timeout(7000)
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:calls.append(r.url))
            page.goto(f'http://127.0.0.1:{port}')
            page.get_by_role('tab',name='交易簿',exact=True).click()
            page.get_by_role('button',name='导入分时路径',exact=True).click()
            page.get_by_label('路径来源说明',exact=True).fill('本人合成路径验收')
            page.get_by_label('分钟路径CSV',exact=True).fill('start,open,high,low,close,volume,amount\n2026-10-27T09:59:00+08:00,10,999,1,10,1000,10000\n2026-10-27T10:00:00+08:00,10,10.5,9.5,10.2,1000,10000\n2026-10-27T10:01:00+08:00,10.2,11,10,11,1000,10000\n')
            page.get_by_label('我已核对用途、未复权口径和一分钟区间定义',exact=True).check()
            page.get_by_role('button',name='保存分钟路径',exact=True).click()
            expect(page.get_by_text('已保存 3 条分钟路径',exact=False)).to_be_visible()
            page.get_by_role('button',name='关闭',exact=True).click()
            page.get_by_role('button',name='路径复盘',exact=True).click();page.get_by_role('button',name='核对持有路径',exact=True).click()
            expect(page.get_by_text('完整MAE -51 元 · 完整MFE 99 元',exact=True)).to_be_visible()
            slider=page.get_by_role('slider',name='已覆盖分钟回放');slider.focus();page.keyboard.press('End')
            expect(page.get_by_text('第 2 / 2 条已覆盖分钟；缺段不插值。',exact=True)).to_be_visible()
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),390)
            self.assertTrue(page.get_by_role('dialog').evaluate('d => d.scrollWidth <= d.clientWidth'))
            evidence=Path(os.getenv('INVESTMENT_OFFLINE_EVIDENCE_DIR','/tmp/grow-investment-offline'));evidence.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(evidence/'replay-390.png'),full_page=True)
            page.get_by_role('button',name='关闭',exact=True).click()
            page.get_by_role('tab',name='复盘与策略',exact=True).click();page.get_by_role('button',name='新建前向试验',exact=True).click()
            for label,value in {'试验标题':'本人前向观察','待验证假设':'先定义再观察','试验反例':'成本可能抵消结果','停止观察条件':'出现数据缺失',
                '参数记录（每行 名称=值）':'holding_sessions=2','成本与样本核对约定':'保留亏损和未知样例','试验开始时间':'2026-10-28T10:00',
                '试验结束时间':'2026-10-29T15:00','复核样本目标':'10','额外每条完整交易成本压力（元，逗号分隔）':'0,1,5'}.items():page.get_by_label(label,exact=True).fill(value)
            page.get_by_role('button',name='保存',exact=True).click();expect(page.get_by_role('dialog')).to_have_count(0)
            page.get_by_role('button',name='前向试验列表',exact=True).click();page.get_by_role('button',name='事前登记并冻结',exact=True).click()
            expect(page.get_by_text('已事前登记 · 版本 2',exact=True)).to_be_visible()
            page.get_by_role('button',name='查看前向评价',exact=True).click()
            expect(page.get_by_text('平仓 0 · 开放仓位 0 · 已知净结果 0 · 未知 0',exact=True)).to_be_visible()
            page.get_by_label('本人试验决定',exact=True).select_option('stopped')
            page.get_by_label('试验评价依据',exact=True).fill('合成验收主动停止，不能声称验证有效')
            page.get_by_role('button',name='保存结项评价',exact=True).click()
            expect(page.get_by_text('已保留本人决定与评价快照；不改变策略或风险。',exact=True)).to_be_visible()
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),390)
            page.screenshot(path=str(evidence/'forward-trial-390.png'),full_page=True)
            self.assertFalse(any('/analysis/jobs' in url or '/provider/' in url for url in calls));self.assertEqual(errors,[])
            browser.close()
