"""Real desktop/mobile Chrome, production research UI and isolated PostgreSQL APIs."""
import json
import asyncio
import socket
import threading
import time
from pathlib import Path
from unittest.mock import patch

import uvicorn
import db
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import sync_playwright,expect
from investments.api import register
from investments.research_history import SeriesInput,save_series
from investments.research_tools import ResearchTools
from test_legacy_cloud_schema import PostgreSQLFixture
from test_investment_strategy_backtest import series


class ResearchBrowserTests(PostgreSQLFixture):
    def test_screen_alert_replay_backtest_export_and_mobile_recovery(self):
        app=FastAPI();store=register(app);store.initialize()
        account=store.create('accounts',{'name':'浏览器研究','baseline_date':'2026-10-19','opening_cash':'10000'},'browser-research-account')
        source=series();source.pop('sessions')
        saved=save_series(ResearchTools(store),SeriesInput(account_id=account['id'],use_confirmed=True,**source),'browser-history')
        with db.connect() as c:
            tools=ResearchTools(store);tools.initialize(c)
            for i in range(101):tools.save(c,'preset',account['id'],{'name':f'历史方案{i:03d}','conditions':[],'combine':'all','sort_by':'close','descending':False,'enabled':True})
        static=Path(__file__).resolve().parents[1]/'static';app.mount('/static',StaticFiles(directory=static))
        @app.get('/')
        def index():
            return HTMLResponse('<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/static/design-tokens.css"><link rel="stylesheet" href="/static/investments.css"><link rel="stylesheet" href="/static/investment-research.css"><button id="open">市场研究工具</button><script>window.Account={user:{id:"research-ui"},verify:async()=>true,isCurrent:()=>true};</script><script src="/static/investment-research-charts.js"></script><script src="/static/investment-research.js"></script><script>document.getElementById("open").onclick=()=>InvestmentResearch.open('+json.dumps({'accountId':account['id']})+');</script></html>')
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'));thread=threading.Thread(target=server.run,daemon=True);thread.start()
        self.addCleanup(lambda:(setattr(server,'should_exit',True),thread.join(5)))
        for _ in range(100):
            if server.started:break
            time.sleep(.03)
        with patch('investments.research_tools.now',return_value='2026-10-29T10:00:01+08:00'),sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
            for width in (1440,390):
                context=browser.new_context(viewport={'width':width,'height':1000});
                if width==1440:context.grant_permissions(['notifications'])
                page=context.new_page();errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto('http://127.0.0.1:'+str(port));page.locator('#open').click();dialog=page.get_by_role('dialog',name='市场研究工具')
                dialog.locator('[data-source-label]').fill('合成合法CSV');dialog.locator('[data-use]').check();dialog.locator('[data-market-date]').fill('2026-10-28')
                dialog.locator('[data-market-csv]').fill('code,name,close,turnover_rate_pct,pe\n000001,合成甲,10,3,8\n600000,合成乙,20,,12\n300001,合成丙,30,1,-1\n')
                dialog.get_by_role('button',name='保存市场CSV',exact=True).click()
                try:expect(dialog.locator('[data-status]')).to_contain_text('市场资料已保存')
                except AssertionError as failure:raise AssertionError(str(failure)+' UI error: '+dialog.locator('[data-error]').inner_text()+' page errors: '+str(errors)) from failure
                dialog.get_by_role('button',name='添加条件',exact=True).click();row=dialog.locator('[data-conditions] fieldset').last
                row.locator('[data-field]').select_option('turnover_rate_pct');row.locator('[data-op]').select_option('gte');row.locator('[data-value]').fill('2')
                dialog.get_by_role('button',name='执行全市场筛选',exact=True).click();expect(dialog.locator('[data-screen-results]')).to_contain_text('入选 1 · 未知 1')
                dialog.locator('[data-preset-name]').fill('合成方案'+str(width));dialog.get_by_role('button',name='保存筛选方案',exact=True).click();expect(dialog.locator('[data-status]')).to_contain_text('方案已保存')
                dialog.locator('[data-record-next="preset"]').click();expect(dialog.locator('[data-preset]')).to_contain_text('历史方案000');expect(dialog.locator('[data-record-page="preset"]')).to_contain_text('第2页');dialog.locator('[data-record-prev="preset"]').click();expect(dialog.locator('[data-record-page="preset"]')).to_contain_text('第1页')
                symbol='000001' if width==1440 else '600000'
                dialog.get_by_role('tab',name='价格提醒',exact=True).click();dialog.locator('[data-alert-code]').fill(symbol);dialog.locator('[data-alert-name]').fill('合成甲');dialog.locator('[data-alert-threshold]').fill('10')
                dialog.get_by_role('button',name='保存价格提醒',exact=True).click();expect(dialog.locator('[data-alert-list]')).to_contain_text('合成甲')
                if width==1440:
                    dialog.get_by_role('button',name='开启浏览器通知',exact=True).click();expect(dialog.locator('[data-status]')).to_contain_text('浏览器通知已允许')
                dialog.locator('[data-quotes]').fill(json.dumps([{'code':symbol,'price':'11','previous_close':'10','quoted_at':'2026-10-29T10:00:00+08:00'}]))
                dialog.get_by_role('button',name='核对所填报价',exact=True).click();expect(dialog.locator('[data-alert-check]')).to_contain_text('triggered')
                interface_keys=[]
                page.on('request',lambda request:interface_keys.append(request.headers.get('idempotency-key')) if request.url.endswith('/api/investments/research/interface') else None)
                from copilot.core import fail
                async def lost_quotes(payload):fail('source_unavailable','合成来源结果未确认',502)
                dialog.get_by_text('本人配置的数据接口',exact=True).click();dialog.locator('[data-interface-url]').fill('https://data.example/quotes')
                with patch('investments.research_sources.interface_json',lost_quotes) as lost:
                    dialog.get_by_role('button',name='从本人接口核对一次',exact=True).click();expect(dialog.locator('[data-error]')).to_contain_text('结果未确认')
                    dialog.locator('[data-alert-code]').fill('300001');dialog.get_by_role('button',name='保存价格提醒',exact=True).click();expect(dialog.locator('[data-status]')).to_contain_text('价格提醒已保存')
                    dialog.get_by_role('button',name='从本人接口核对一次',exact=True).click();expect(dialog.locator('[data-error]')).to_contain_text('不会自动重新请求')
                self.assertEqual(len(interface_keys),2);self.assertEqual(interface_keys[0],interface_keys[1])
                dialog.get_by_role('button',name='保留旧结果，重新发起',exact=True).click()
                async def slow_quotes(payload):
                    await asyncio.sleep(.6)
                    return {'quotes':[{'code':symbol,'price':'11','previous_close':'10','quoted_at':'2026-10-29T10:00:00+08:00'}]}
                page.evaluate('window.researchIntervals=[];window.originalResearchInterval=window.setInterval;window.setInterval=(fn,ms)=>{if(ms>=60000)window.researchIntervals.push(ms);return window.originalResearchInterval(fn,ms)}')
                with patch('investments.research_sources.interface_json',slow_quotes):
                    dialog.get_by_role('button',name='开始网页内监控',exact=True).click();dialog.get_by_role('button',name='停止监控',exact=True).click()
                    expect(dialog.get_by_role('button',name='开始网页内监控',exact=True)).to_be_enabled()
                self.assertEqual(page.evaluate('window.researchIntervals'),[])
                expect(dialog.locator('[data-status]')).to_contain_text('监控已停止')
                dialog.get_by_role('tab',name='历史与回放',exact=True).click();dialog.locator('[data-series]').select_option(saved['id']);dialog.get_by_role('button',name='打开历史行情',exact=True).click()
                expect(dialog.locator('[data-candle-chart] svg')).to_be_visible();dialog.locator('[data-playback-position]').fill('2');dialog.locator('[data-playback-position]').dispatch_event('input')
                dialog.get_by_role('button',name='下一根',exact=True).click();expect(dialog.locator('[data-playback-position]')).to_have_value('3')
                dialog.get_by_role('tab',name='策略回测',exact=True).click();dialog.locator('[data-backtest-series]').select_option(saved['id'])
                dialog.get_by_text('费用、成交与样本假设',exact=True).click()
                for selector,value in [('initial_cash','10000'),('quantity','100'),('entry_above','10'),('exit_below','10'),('commission_rate','0'),('minimum_commission','5'),('sell_tax_rate','0.0005'),('slippage_bps','0'),('max_participation','1')]:dialog.locator('[data-config="'+selector+'"]').fill(value)
                dialog.locator('[data-config="strategy"]').select_option('threshold')
                dialog.get_by_role('button',name='运行策略回测',exact=True).click();expect(dialog.locator('[data-backtest-results]')).to_contain_text('-410.4')
                expect(dialog.locator('[data-equity-chart] svg')).to_be_visible();expect(dialog.locator('[data-trade-marker]')).to_have_count(2)
                with page.expect_download() as download:dialog.get_by_role('button',name='导出交易CSV',exact=True).click()
                self.assertTrue(download.value.suggested_filename.endswith('.csv'))
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                self.assertLessEqual(dialog.evaluate('e=>e.scrollWidth-e.clientWidth'),1)
                page.screenshot(path='/tmp/grow-research-'+str(width)+'.png',full_page=True)
                self.assertEqual(errors,[]);dialog.get_by_role('button',name='关闭研究工具',exact=True).click()
                page.locator('#open').click();dialog=page.get_by_role('dialog',name='市场研究工具');dialog.get_by_role('tab',name='策略回测',exact=True).click()
                expect(dialog.locator('[data-backtest-history] option[value]:not([value=""])')).not_to_have_count(0)
                dialog.locator('[data-backtest-history]').select_option(index=1);dialog.get_by_role('button',name='打开历史结果',exact=True).click();expect(dialog.locator('[data-backtest-results]')).to_contain_text('-410.4')
                dialog.get_by_role('tab',name='市场筛选',exact=True).click();dialog.locator('[data-screen-history]').select_option(index=1);dialog.get_by_role('button',name='打开历史筛选',exact=True).click();expect(dialog.locator('[data-screen-results]')).to_contain_text('入选 1 · 未知 1')
                dialog.locator('[data-use]').check();dialog.locator('[data-ak-market-source]').select_option('eastmoney')
                previous_dataset=dialog.locator('[data-dataset]').input_value()
                def selected_source(request):
                    if request.get('source')=='eastmoney':fail('provider_connection','东方财富连接中断，未自动换源。',502)
                    return {'upstream':'tencent','library_version':'1.20.1','rows':[{'code':'sz000001','name':'合成腾讯','zxj':'11','volume':'123','turnover':'456','hsl':'3','pe_ttm':'5.2'}]}
                with patch('investments.research_sources.worker',side_effect=selected_source) as selected:
                    dialog.get_by_role('button',name='读取盘后全市场（AKShare）',exact=True).click();expect(dialog.locator('[data-error]')).to_contain_text('东方财富连接中断')
                    self.assertEqual(selected.call_count,1);self.assertEqual(dialog.locator('[data-dataset]').input_value(),previous_dataset)
                    dialog.locator('[data-ak-market-source]').select_option('tencent');dialog.get_by_role('button',name='读取盘后全市场（AKShare）',exact=True).click();expect(dialog.locator('[data-dataset-note]')).to_contain_text('腾讯全市场快照')
                    self.assertEqual([c.args[0]['source'] for c in selected.call_args_list],['eastmoney','tencent'])
                self.assertEqual(errors,[])
                page.screenshot(path='/tmp/grow-akshare-fix-20261030/source-choice-'+str(width)+'.png',full_page=True)
                context.close()
