"""Actual mobile forms: manually checked plan, holiday-aware week and fund batches."""
import socket
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


class InvestmentPlanningBrowserTests(PostgreSQLFixture):
    def test_manual_check_to_confirmed_plan_week_and_fund_batches(self):
        app=FastAPI();store=register(app);store.initialize()
        app.mount('/static',StaticFiles(directory=Path(__file__).resolve().parents[1]/'static'))
        @app.get('/')
        def index():
            return HTMLResponse('''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/static/design-tokens.css"><link rel="stylesheet" href="/static/investments.css"><div id="investment-workspace"></div><script src="/static/investments.js"></script><script>Investments.open()</script>''')
        for target in ('investments.planning.now','investments.plan_checks.now','investments.store.now','investments.operations.now'):
            p=patch(target,return_value='2026-10-28T09:00:00+08:00');p.start();self.addCleanup(p.stop)
        a=store.create('accounts',{'name':'表单测试','opening_cash':'10000','baseline_date':'2026-10-26'},'a')
        i=store.create('instruments',{'name':'核对股票','code':'600000','market':'SSE','kind':'stock'},'i')
        fund=store.create('instruments',{'name':'分批基金','code':'000001','market':'FUND','kind':'fund'},'fund')
        policy=store.create('policies',{'account_id':a['id'],'period_start':'2026-10-01','period_end':'2026-10-31',
            'purpose':'交易','liquidity_needs':'留备用金','loss_capacity':'300','cash_buffer':'2000','trade_risk_budget':'300'},'p')
        store.transition('policies',policy['id'],1,'confirmed','pc')
        strategy=store.create('strategies',{'title':'前向观察','entry_conditions':'达到条件','exit_conditions':'逻辑失效','validation_scope':'前向一个月'},'s')
        store.transition('strategies',strategy['id'],1,'confirmed','sc')
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
        thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
        self.addCleanup(lambda:thread.join(5));self.addCleanup(lambda:setattr(server,'should_exit',True))
        for _ in range(100):
            if server.started:break
            time.sleep(.02)
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
            page=browser.new_page(viewport={'width':390,'height':844});page.set_default_timeout(5000)
            page.clock.install(time='2026-10-28T09:00:00+08:00')
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{port}')
            page.get_by_role('button',name='核对日历与交易规则',exact=True).click()
            page.get_by_label('核对标的',exact=True).select_option(i['id'])
            values={'最近完成开市日的收盘价':'10','收盘资料时点':'2026-10-27T15:00',
                '逐日日历（每行：日期,开市 或 日期,休市）':'2026-10-26,开市\n2026-10-27,开市\n2026-10-28,开市\n2026-10-29,开市\n2026-10-30,开市\n2026-10-31,休市\n2026-11-01,休市\n2026-11-02,开市',
                '规则适用开始':'2026-10-26','规则适用截至':'2026-11-02','最小价格变动单位':'0.01',
                '买入数量递增单位':'100','最低买入数量':'100','买入后至少间隔的开市日数':'1',
                '核对原始链接':'https://www.sse.com.cn/','资料位置与核对说明':'本人核对的测试资料，不表示生产规则'}
            for label,value in values.items():page.get_by_label(label,exact=True).fill(value)
            page.get_by_label('已核对交易状态',exact=True).select_option('normal')
            page.get_by_label('本人已核对资料和适用证券',exact=True).check()
            page.get_by_role('button',name='保存',exact=True).click()
            expect(page.get_by_role('button',name='交易计划',exact=True)).to_be_enabled()
            page.get_by_role('button',name='交易计划',exact=True).click()
            page.get_by_label('计划标题',exact=True).fill('本人条件计划')
            page.get_by_label('计划标的',exact=True).select_option(i['id'])
            page.get_by_label('关联策略',exact=True).select_option(strategy['id'])
            for label,value in {'交易理由（可留空）':'等待条件','触发条件（可留空）':'达到10','失效条件（可留空）':'低于9','风险预算（可留空）':'250',
                '预计持有交易日（可留空）':'3','计划入场价格（可留空）':'10','计划失效价格（可留空）':'9',
                '预计本次进出总费用（可留空）':'2','计划开市日（可留空）':'2026-10-28','有效截至':'2026-10-28T15:00'}.items():
                page.get_by_label(label,exact=True).fill(value)
            page.get_by_label('本人核对资料',exact=True).select_option(index=1)
            page.get_by_role('button',name='保存',exact=True).click()
            plan=page.locator('article').filter(has=page.get_by_role('heading',name='本人条件计划 · 核对股票',exact=True))
            plan.get_by_role('button',name='估算数量与核对',exact=True).click()
            expect(page.get_by_text('估算数量 200 · 计划价格差损失含费用 202',exact=True)).to_be_visible()
            page.get_by_role('button',name='关闭',exact=True).click()
            plan.get_by_role('button',name='确认',exact=True).click()
            expect(page.get_by_text('本人核对的条件计划 · 数量 200 · 最晚复核 2026-10-30',exact=True)).to_be_visible()
            page.get_by_role('button',name='周日准备计划',exact=True).click()
            page.get_by_label('准备计划标题',exact=True).fill('本周只观察')
            page.get_by_label('准备周期',exact=True).select_option('week')
            page.get_by_label('准备开始日期',exact=True).fill('2026-10-26')
            page.get_by_label('准备结束日期',exact=True).fill('2026-11-01')
            page.get_by_label('本期关注与检查事项',exact=True).fill('只核对公告')
            page.get_by_label('本人核对资料',exact=True).select_option(index=1)
            page.get_by_label('本期选择不交易',exact=True).check()
            page.get_by_role('button',name='保存',exact=True).click()
            week=page.locator('article').filter(has=page.get_by_role('heading',name='本周只观察 · 周计划',exact=True))
            week.get_by_role('button',name='确认',exact=True).click()
            expect(week.get_by_text('已核对开市日',exact=False)).to_be_visible()
            week.get_by_role('button',name='记录未交易决定',exact=True).click()
            page.get_by_label('决定原因',exact=True).fill('没有出现触发条件')
            page.get_by_role('button',name='保存',exact=True).click()
            expect(page.get_by_text('状态原因：没有出现触发条件',exact=True)).to_be_visible()
            order=store.create('fund-orders',{'account_id':a['id'],'instrument_id':fund['id'],'side':'subscription',
                'amount':'1000','applied_at':'2026-10-26T10:00:00+08:00'},'f')
            page.get_by_role('button',name='刷新',exact=True).click()
            page.get_by_role('tab',name='交易簿',exact=True).click()
            for index in range(2):
                page.get_by_role('button',name='确认净值与份额',exact=True).click()
                for label,value in {'确认净值':'1','确认份额':'400','实际手续费':'1','实际税费':'0','本批实际收支净额（含费用）':'401',
                    '净值日期':'2026-10-26','确认时间':f'2026-10-{27+index}T10:00'}.items():page.get_by_label(label,exact=True).fill(value)
                if index==0:page.get_by_label('本申请全部确认完毕',exact=True).uncheck()
                page.get_by_role('button',name='保存',exact=True).click()
                expect(page.get_by_role('dialog')).to_have_count(0)
                expect(page.get_by_role('button',name='基金申请',exact=True)).to_be_enabled()
            self.assertEqual(len(store.get('fund-orders',order['id'])['confirmations']),2)
            page.get_by_role('tab',name='今日与计划',exact=True).click()
            page.get_by_role('button',name='结构化研究',exact=True).click()
            page.get_by_label('研究标题',exact=True).fill('股票资料不足时先观察')
            page.get_by_label('研究标的',exact=True).select_option(i['id'])
            page.get_by_label('研究持有视角',exact=True).select_option('short')
            page.get_by_label('公司风险',exact=False).fill('公告与实际交易状态仍需核对')
            page.get_by_label('缺少输入',exact=False).fill('缺少公告、财报和当前行情')
            page.get_by_role('button',name='保存',exact=True).click()
            expect(page.get_by_text('股票资料不足时先观察 · 短线',exact=True)).to_be_visible()
            expect(page.get_by_text('选定原文 0 份，研究笔记不等于核验事实。',exact=True)).to_be_visible()
            self.assertEqual(errors,[])
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),390)
            page.screenshot(path='/tmp/grow-investment-planning-390.png',full_page=True)
            browser.close()
