"""Production index, real login/tenancy and HTTP; only model transport is synthetic."""
import json
import os
import socket
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import uvicorn
from playwright.sync_api import sync_playwright,expect
import test_accounts as account_fixture


class InvestmentJourneyBrowserTests(unittest.TestCase):
    setUp=account_fixture.AccountIntegrationTests.setUp
    cleanup_database=account_fixture.AccountIntegrationTests.cleanup_database
    login=account_fixture.AccountIntegrationTests.login

    def journey(self,width):
        self.stamp='2026-10-28T09:00:00+08:00'
        for target in ('store','analysis','planning','operations','plan_checks','rules'):
            clock=patch('investments.'+target+'.now',side_effect=lambda:self.stamp);clock.start();self.addCleanup(clock.stop)
        calls=[]
        async def model(messages,cfg):
            content=json.loads(messages[1]['content']);snapshot=content['snapshot'];calls.append(content)
            evidence=snapshot['evidence'][0]
            report={'summary':'合成验收：仅在条件满足后核对，不代表真实投资建议。',
                'facts':[{'evidence_id':evidence['id'],'quote':'合成测试公告'}],
                'inferences':['样例不能证明后续涨跌'],'counterarguments':['当前交易状态仍由本人核对'],
                'missing_inputs':['真实服务质量尚未验收'],
                'suggestions':[{'title':'合成条件计划','action':'conditional_entry','reason':'前向观察',
                    'trigger':'本人检查价格达到10','invalidation':'跌破9或出现反证',
                    'valid_until':'2026-10-29T15:00:00+08:00','evidence_ids':[evidence['id']]}]}
            yield {'text':json.dumps(report,ensure_ascii=False)};yield {'done':True}
        mock=patch('copilot.transport.qwen_stream',model);mock.start();self.addCleanup(mock.stop)
        self.login('owner',os.environ['APP_PASSWORD'])
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(self.dashboard.app,log_level='error',lifespan='off'))
        thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
        self.addCleanup(lambda:thread.join(5));self.addCleanup(lambda:setattr(server,'should_exit',True))
        for _ in range(100):
            if server.started:break
            time.sleep(.02)
        url=f'http://127.0.0.1:{port}'
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
            context=browser.new_context(viewport={'width':width,'height':1000})
            context.add_cookies([{'name':'zhixing_session','value':self.client.cookies.get('zhixing_session'),'url':url,'httpOnly':True,'secure':False,'sameSite':'Lax'}])
            page=context.new_page();page.clock.install(time=self.stamp);page.set_default_timeout(10000)
            errors=[];external=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            def route(request):
                if request.request.url.startswith(url+'/'):request.continue_()
                else:external.append(request.request.url);request.abort()
            page.route('**/*',route)
            page.goto(url);page.evaluate('Account.ready');page.evaluate("goTab('stocks')")
            root=page.locator('#investment-workspace')
            def button(name):return page.get_by_role('button',name=name,exact=True)
            def control(label):
                scope=page.locator('#view-settings') if label in ('API Base URL','API Key','模型名称') else page.get_by_role('dialog')
                return scope.get_by_label(label,exact=True)
            def fields(values):
                for label,value in values.items():control(label).fill(value)
            def save():
                button('保存').click();expect(page.get_by_role('dialog')).to_have_count(0)
                expect(root.get_by_role('button',name='刷新',exact=True)).to_be_enabled()
            button('新建账户').click();fields({'账户名称':'全链路验收','核对基准日':'2026-10-26','期初现金':'10000'});save()
            button('配置与验收要求').click();expect(page.get_by_role('dialog')).to_contain_text('不需要券商登录密码');button('关闭').click()
            button('添加标的').click();fields({'证券代码':'600000','证券名称':'合成验收股票'});control('品种').select_option('stock');save()
            button('资金预算').click()
            fields({'开始日期':'2026-10-01','结束日期':'2026-10-31','资金用途':'合成交易用途','近期用钱需求':'保留生活备用',
                '能承受的损失':'合成预算300','现金缓冲（可留空）':'2000','单笔风险预算（可留空）':'300'})
            save()
            policy=root.locator('article').filter(has=page.get_by_role('heading',name='2026-10-01 至 2026-10-31',exact=True))
            policy.get_by_role('button',name='确认',exact=True).click();expect(policy).to_contain_text('已确认')
            button('新增策略').click();fields({'策略名称':'合成前向策略','适用环境（可留空）':'仅作验收',
                '入场条件':'达到条件后核对','退出条件':'逻辑失效','验证范围':'先观察10次'})
            save()
            page.get_by_role('tab',name='复盘与策略',exact=True).click()
            strategy=root.locator('article').filter(has=page.get_by_role('heading',name='合成前向策略',exact=True))
            strategy.get_by_role('button',name='确认',exact=True).click();expect(strategy).to_contain_text('已确认')
            page.get_by_role('tab',name='今日与计划',exact=True).click()
            button('核对日历与交易规则').click();button('自动填入公开规则与日历').click()
            expect(control('最小价格变动单位')).to_have_value('0.01')
            expect(control('已核对交易状态')).to_have_value('unknown')
            expect(control('本人已核对资料和适用证券')).not_to_be_checked()
            fields({'最近完成开市日的收盘价':'10','收盘资料时点':'2026-10-27T15:00'})
            control('已核对交易状态').select_option('normal');control('本人已核对资料和适用证券').check();save()
            button('保存研究').click();fields({'资料标题':'合成资料','资料原文或观察':'合成测试公告，仅用于程序验收，不代表真实上市公司信息。','资料可获知时间':'2026-10-28T08:00'});save()
            page.evaluate("goTab('settings')");fields({'API Base URL':'https://model.example/v1','API Key':'SYNTHETIC_JOURNEY_ONLY','模型名称':'synthetic-json-model'})
            button('保存配置').click();expect(page.locator('#apiStatus')).to_contain_text('已保存')
            page.evaluate("goTab('stocks')");button('AI研究与建议').click()
            control('分析标的').select_option(label='合成验收股票 · 600000')
            fields({'想分析的问题':'根据合成资料形成未来条件草稿，给出反证。'})
            control('合成资料').check();button('预览将发送的资料').click();button('确认发送并分析').click()
            expect(page.get_by_text('合成验收：仅在条件满足后核对，不代表真实投资建议。',exact=True)).to_be_visible(timeout=15000)
            button('采用为计划草稿').click();expect(page.get_by_text('已关联计划，请查看当前版本与状态；不会下单。',exact=True)).to_be_visible();button('关闭').click()
            plan=root.locator('article').filter(has=page.get_by_role('heading',name='合成条件计划 · 合成验收股票',exact=True))
            plan.get_by_role('button',name='修改版本',exact=True).click()
            control('关联策略').select_option(label='合成前向策略 · 已确认')
            control('本人核对资料').select_option(index=1)
            fields({'风险预算（可留空）':'250','预计持有交易日（可留空）':'2','计划入场价格（可留空）':'10',
                '计划失效价格（可留空）':'9','预计本次进出总费用（可留空）':'2','计划开市日（可留空）':'2026-10-28'})
            save();plan.get_by_role('button',name='确认',exact=True).click();expect(plan).to_contain_text('本人核对的条件计划 · 数量 200')
            page.get_by_role('tab',name='交易簿',exact=True).click()
            for side,price,quantity,stamp in [('buy','10','100','2026-10-28T10:00'),('buy','10','100','2026-10-28T10:01'),('sell','11','200','2026-10-29T10:00')]:
                self.stamp=stamp+':00+08:00'
                button('记录成交').click();control('操作').select_option(side)
                fields({'成交价格':price,'成交数量':quantity,'手续费（可留空）':'1','税费（可留空）':'0','成交时间':stamp})
                if side=='buy':control('关联事前计划').select_option(label='合成条件计划 · 已确认')
                save()
            cycle=root.locator('article').filter(has=page.get_by_role('heading',name='合成验收股票 · 已平仓',exact=True))
            expect(cycle).to_contain_text('已实现净盈亏 197')
            cycle.get_by_role('button',name='对照复盘',exact=True).click();expect(page.get_by_role('dialog')).to_contain_text('原计划版本')
            button('写这笔复盘').click();fields({'复盘原文':'合成验收：按事前版本记录，结果不证明方法有效。'})
            control('执行评价').select_option('followed');save()
            page.get_by_role('tab',name='复盘与策略',exact=True).click();button('形成试验原则').click()
            fields({'原则标题':'只作一项前向试验','候选规则':'下一阶段只观察，不增加风险','支持案例（可留空）':'记录齐全便于核对',
                '反例与失效情形（可留空）':'盈利样例不能证明方法有效','前向试验范围（可留空）':'未来10次观察，保留失败'})
            control('选择原始复盘').select_option(index=0);save()
            principle=root.locator('article').filter(has=page.get_by_role('heading',name='只作一项前向试验',exact=True))
            principle.get_by_role('button',name='确认',exact=True).click();expect(principle).to_contain_text('已确认')
            page.reload();page.evaluate('Account.ready');page.evaluate("goTab('stocks')");page.get_by_role('tab',name='复盘与策略',exact=True).click()
            expect(page.get_by_role('heading',name='只作一项前向试验',exact=True)).to_be_visible()
            context.set_offline(True);root.get_by_role('button',name='刷新',exact=True).click();expect(root.locator('[data-inv-status]')).to_have_attribute('role','alert')
            expect(page.get_by_role('heading',name='只作一项前向试验',exact=True)).to_be_visible()
            context.set_offline(False);root.get_by_role('button',name='刷新',exact=True).click();expect(root.get_by_role('button',name='刷新',exact=True)).to_be_enabled()
            self.assertEqual(len(calls),2);self.assertFalse(calls[0]['snapshot']['include_amounts'])
            self.assertEqual(external,[]);self.assertEqual(errors,[])
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
            evidence=Path(os.getenv('INVESTMENT_EVIDENCE_DIR',self.tmp.name));evidence.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(evidence/f'journey-{width}.png'),full_page=True)
            export=self.client.get('/api/investments/export').json()
            self.assertNotIn('SYNTHETIC_JOURNEY_ONLY',json.dumps(export))
            browser.close()

    def test_production_journey_desktop(self):self.journey(1440)
    def test_production_journey_mobile(self):self.journey(390)
