"""Actual component, HTTP and PostgreSQL in Chromium; no provider calls."""
import socket
import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

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
                <script>window.AIConfig={require:()=>({api_base_url:'https://model.example/v1',api_key:'BROWSER_TEST_ONLY',model_name:'test-model'})}</script>
                <script src="/static/investments.js"></script><script src="/static/investment-analysis.js"></script><script src="/static/investment-market.js"></script><script>Investments.open()</script></html>''')
        calls=[]
        async def model(messages,cfg):
            calls.append(messages)
            snapshot=json.loads(messages[1]['content'])['snapshot']
            evidence=snapshot['evidence'][0]
            report={'summary':'先核对规则和现金流。','facts':[{'evidence_id':evidence['id'],'quote':'营业收入10亿元'}],
                'inferences':['历史收入不代表短期涨幅。'],'counterarguments':['缺少当前行情。'],
                'missing_inputs':['交易规则与费用'], 'suggestions':[{'title':'核对财报现金流','action':'research',
                'reason':'补足证据','trigger':'取得原始财报','invalidation':'公告更正',
                'valid_until':'2030-01-01T15:00:00+08:00','evidence_ids':[evidence['id']]}]}
            yield {'text':json.dumps(report,ensure_ascii=False)}
            yield {'done':True}
        mock=patch('copilot.transport.qwen_stream',model);mock.start();self.addCleanup(mock.stop)
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
            errors=[]
            def page_error(error):
                errors.append(str(error))
                print('INVESTMENT_BROWSER_ERROR',str(error))
            page.on('pageerror',page_error)
            page.goto(f'http://127.0.0.1:{port}')
            page.get_by_role('button',name='新建账户',exact=True).click()
            page.get_by_label('账户名称').fill('测试账户')
            page.get_by_label('核对基准日').fill('2026-10-26')
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
            page.get_by_label('成交时间').fill('2026-10-26T10:00')
            page.get_by_label('手续费').fill('1')
            page.get_by_label('税费').fill('0')
            page.get_by_role('button',name='保存',exact=True).click()
            expect(page.get_by_text('1.231',exact=True)).to_be_visible()
            page.reload()
            page.get_by_role('tab',name='交易簿',exact=True).click()
            expect(page.get_by_text('1.231',exact=True)).to_be_visible()
            page.get_by_role('button',name='核对更正',exact=True).click()
            page.get_by_label('成交价格').fill('1.232')
            page.get_by_label('更正原因').fill('核对券商实际成交')
            page.get_by_role('button',name='保存',exact=True).click()
            expect(page.get_by_text('1.232',exact=True)).to_be_visible()
            page.get_by_role('button',name='导入CSV',exact=True).click()
            page.get_by_label('粘贴成交CSV').fill('code,market,side,price,quantity,fee,tax,executed_at,external_id\n510000,SSE,sell,1.234,100,0,0,2026-10-26T12:00:00+08:00,ui-sell-1\n')
            page.get_by_role('button',name='预览',exact=True).click()
            expect(page.get_by_text('1条可导入，0条需修正。',exact=True)).to_be_visible()
            page.get_by_role('button',name='确认导入',exact=True).click()
            expect(page.get_by_text('1.234',exact=True)).to_be_visible()
            page.get_by_role('tab',name='复盘与策略',exact=True).click()
            page.get_by_role('button',name='写复盘',exact=True).click()
            page.get_by_label('复盘原文').fill('今日按计划观察，等待公告。')
            page.get_by_role('button',name='保存',exact=True).click()
            expect(page.get_by_text('今日按计划观察，等待公告。',exact=True)).to_be_visible()
            page.get_by_role('button',name='修改版本',exact=True).click()
            page.get_by_label('下一项试验').fill('下一周只调整一项规则。')
            page.get_by_role('button',name='保存',exact=True).click()
            expect(page.get_by_text('下一项试验：下一周只调整一项规则。',exact=True)).to_be_visible()
            page.get_by_role('tab',name='今日与计划',exact=True).click()
            page.get_by_role('button',name='保存研究',exact=True).click()
            page.get_by_label('资料标题').fill('公告摘录')
            page.get_by_label('资料原文或观察').fill('营业收入10亿元，现金流仍需核对。')
            page.get_by_role('button',name='保存',exact=True).click()
            expect(page.get_by_text('公告摘录',exact=True)).to_be_visible()
            page.get_by_role('button',name='AI研究与建议',exact=True).click()
            page.get_by_label('想分析的问题').fill('请分析依据并提供反证。')
            page.get_by_label('公告摘录',exact=True).check()
            page.get_by_role('button',name='预览将发送的资料',exact=True).click()
            expect(page.get_by_role('heading',name='核对发送范围')).to_be_visible()
            page.get_by_role('button',name='确认发送并分析',exact=True).click()
            expect(page.get_by_text('先核对规则和现金流。',exact=True)).to_be_visible(timeout=15000)
            page.get_by_role('button',name='保存为思考',exact=True).click()
            expect(page.get_by_text('已保存为投资思考。',exact=True)).to_be_visible()
            page.get_by_role('button',name='关闭',exact=True).click()
            page.get_by_role('tab',name='复盘与策略',exact=True).click()
            expect(page.get_by_text('核对财报现金流\n补足证据',exact=True)).to_be_visible()
            page.get_by_role('button',name='添加盘后行情',exact=True).click()
            page.get_by_label('来源说明',exact=True).fill('本人导出测试资料')
            page.get_by_label('日线CSV',exact=True).fill('date,open,high,low,close,volume,amount\n2026-10-23,1.1,1.3,1,1.2,100,120\n2026-10-26,1.2,1.4,1.1,1.3,200,260\n')
            page.get_by_label('我已核对资料使用范围',exact=False).check()
            page.get_by_role('button',name='保存行情与研究证据',exact=True).click()
            expect(page.get_by_text('已保存 2 条日线及研究证据。',exact=False)).to_be_visible()
            page.get_by_role('button',name='关闭',exact=True).click()
            page.get_by_role('button',name='本地条件筛选',exact=True).click()
            page.get_by_label('数据截至日期',exact=True).fill('2026-10-26')
            page.get_by_label('条件值',exact=True).fill('1.25')
            page.get_by_role('button',name='执行本地筛选',exact=True).click()
            expect(page.get_by_text('本地覆盖 1 个标的 · 命中 1 个',exact=True)).to_be_visible()
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),390)
            page.screenshot(path='/tmp/grow-investment-screen-mobile.png',full_page=True)
            page.get_by_role('button',name='关闭',exact=True).click()
            self.assertEqual(len(calls),2)
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),390)
            self.assertEqual(errors,[])
