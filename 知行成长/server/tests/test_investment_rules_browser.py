"""真实Chrome组件+隔离HTTP；模型/行情合成，真实服务另验收。"""
import json
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

from investments.api import register
from investments.market_import import import_history
from test_legacy_cloud_schema import PostgreSQLFixture
from test_investment_rule_screening import fixture


class RulesBrowserTests(PostgreSQLFixture):
    def test_desktop_mobile_natural_rules_templates_recovery_and_analysis(self):
        app=FastAPI();store=register(app);store.initialize()
        account=store.create('accounts',{'name':'规则UI','baseline_date':'2026-10-28','opening_cash':'0'},'a')
        stock=store.create('instruments',{'name':'合成股票','code':'600001','kind':'stock','market':'SSE'},'i')
        bars=fixture()['universe'][0]['bars']
        text='date,open,high,low,close,volume,amount,turnover_rate_pct\n'+''.join(','.join(b[k] for k in ('date','open','high','low','close','volume_shares','turnover_cny','turnover_rate_pct'))+'\n' for b in bars)
        import_history(store,stock['id'],text,'shares','cny','合成来源',True,'csv',account['id'])
        static=Path(__file__).resolve().parents[1]/'static';app.mount('/static',StaticFiles(directory=static))
        context={'accountId':account['id'],'instruments':[stock]}
        @app.get('/')
        def index():
            return HTMLResponse('<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="/static/design-tokens.css"><link rel="stylesheet" href="/static/investments.css"><button id="open">规则选股</button><script>window.Account={user:{id:"rule-test"},verify:async()=>true,isCurrent:()=>true};window.AIConfig={read:()=>({api_base_url:"https://model.example/v1",model_name:"test",api_key:"TEST_RULE_PRIVATE_KEY"})};</script>'+''.join('<script src="/static/'+name+'"></script>' for name in ('investment-browser-core.js','investment-browser.js','investment-screening-v2.js','investment-rule-screen.js'))+'<script>document.getElementById("open").onclick=()=>InvestmentRuleScreen.open('+json.dumps(context,ensure_ascii=False)+');</script></html>')
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'));thread=threading.Thread(target=server.run,daemon=True);thread.start()
        self.addCleanup(lambda:(setattr(server,'should_exit',True),thread.join(5)))
        for _ in range(100):
            if server.started:break
            time.sleep(.03)
        source='近5日涨幅至少3%，换手适中，按量比排序'
        relay_host=patch.dict('os.environ',{'INVESTMENT_AI_RELAY_HOSTS':'model.example'});relay_host.start();self.addCleanup(relay_host.stop)
        resolver=patch('investments.ai_relay.destination',return_value=['93.184.216.34']);resolver.start();self.addCleanup(resolver.stop)
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
            for width,transport in ((1440,'direct'),(390,'direct'),(1440,'relay')):
                ctx=browser.new_context(viewport={'width':width,'height':1000});page=ctx.new_page();errors=[];calls=[];platform=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('request',lambda r:platform.append(r.post_data or '') if '/api/investments/' in r.url else None)
                def output(body):
                    calls.append(body)
                    if 'schema' in body and 'text' in body:
                        raw={'parser_version':'screen-rule-parser-v1','screen':{'as_of':'2026-10-28','conditions':[{'field':'return_5d_pct','op':'gte','value':'3'},{'field':'turnover_rate_pct','op':'between','value':'2','upper_value':'8'}],'combine':'all','sort_by':'volume_ratio_5','descending':True,'limit':20},
                            'mappings':[{'source':'explicit','quote':'近5日涨幅至少3%','reason':''},{'source':'suggested','quote':'换手适中','reason':'示例建议，尚未验证有效性'}],'sort_mapping':{'source':'explicit','quote':'按量比排序','reason':''},'ambiguities':[],'unsupported':[]}
                    else:
                        e=body['snapshot']['evidence'][0]
                        raw={'summary':'仅作研究，条件待本人核对','facts':[{'evidence_id':e['id'],'quote':'"execution_location": "browser"'}],'counterarguments':['来源真实性仍需核对']}
                    return json.dumps(raw,ensure_ascii=False)
                def model(route):
                    if route.request.method=='OPTIONS':route.fulfill(status=204,headers={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'*','Access-Control-Allow-Methods':'POST, OPTIONS'});return
                    route.fulfill(status=200,headers={'Access-Control-Allow-Origin':'*'},json={'choices':[{'finish_reason':'stop','message':{'content':output(json.loads(route.request.post_data_json['messages'][1]['content']))}}]})
                async def relay_stream(messages,cfg):yield {'text':output(json.loads(messages[1]['content']))};yield {'done':True}
                relay=patch('copilot.transport.qwen_stream',relay_stream);relay.start();self.addCleanup(relay.stop)
                page.route('https://model.example/**',model)
                page.goto(f'http://127.0.0.1:{port}/');page.locator('#open').click();d=page.get_by_role('dialog',name='规则选股')
                expect(d).to_be_visible();d.locator('[data-iid]').check();d.locator('[data-date]').fill('2026-10-28');d.locator('[data-text]').fill(source)
                if transport=='relay':
                    d.get_by_text('模型配置（仅生成条件或研究候选时需要）',exact=True).click();d.locator('[data-transport]').select_option('relay');d.locator('[data-relay-consent]').check()
                    def lose_reply(route):route.fetch();route.abort('failed')
                    page.route('**/api/investments/ai-relay',lose_reply)
                    d.locator('[data-generate]').click();expect(d.get_by_role('button',name='读取原转发回执（不调用模型）',exact=True)).to_be_visible()
                    page.unroute('**/api/investments/ai-relay',lose_reply)
                    page.reload();page.locator('#open').click();d=page.get_by_role('dialog',name='规则选股')
                    d.get_by_role('button',name='读取原转发回执（不调用模型）',exact=True).click();d.get_by_role('button',name='恢复已收到的解析输出（不调用模型）',exact=True).click()
                    d.get_by_text('模型配置（仅生成条件或研究候选时需要）',exact=True).click();d.locator('[data-relay-consent]').check()
                else:d.locator('[data-generate]').click()
                expect(d.locator('[data-accept]')).to_be_visible();self.assertEqual(len(calls),1)
                d.locator('[data-run]').click();expect(d.locator('[data-error]')).to_contain_text('接受AI建议');self.assertIsNone(page.evaluate('async()=>{let s=await InvestmentRuleScreen.read("rule-test:'+account['id']+':rule-v2");return s.cp||null}'))
                page.reload();page.locator('#open').click();d=page.get_by_role('dialog',name='规则选股');expect(d.locator('[data-accept]')).to_be_visible();self.assertEqual(len(calls),1)
                d.locator('[data-accept]').check();d.locator('[data-name]').fill('UI模板'+str(width));d.locator('[data-save-template]').click();expect(d.locator('[data-status]')).to_contain_text('版本 1')
                d.locator('[data-run]').click();expect(d.locator('[data-results]')).to_contain_text('入选 1');self.assertEqual(len(calls),1)
                d.locator('[data-candidate]').check();
                if transport=='relay':
                    d.get_by_text('模型配置（仅生成条件或研究候选时需要）',exact=True).click();d.locator('[data-relay-consent]').check()
                d.locator('[data-preview]').click();expect(d.locator('[data-ai-preview]')).to_contain_text('实际发送内容');self.assertEqual(len(calls),1)
                d.locator('[data-analyze]').click();expect(d.locator('[data-status]')).to_contain_text('本轮已停止执行',timeout=15000);expect(d.locator('[data-results] button')).to_contain_text('查看候选报告')
                page.wait_for_function('async()=>{const s=await InvestmentRuleScreen.read("rule-test:'+account['id']+':rule-v2");return s?.cp?.run?.state==="ready"}')
                self.assertEqual(page.evaluate('async()=>{const s=await InvestmentRuleScreen.read("rule-test:'+account['id']+':rule-v2");return s.cp.run.state}'),'ready')
                self.assertEqual(len(calls),3,json.dumps({'width':width,'stages':[c.get('phase','parser') for c in calls],'status':d.locator('[data-status]').inner_text(),'checkpoint':page.evaluate('async()=>await InvestmentRuleScreen.read("rule-test:'+account['id']+':rule-v2")')},ensure_ascii=False));self.assertTrue(all('TEST_RULE_PRIVATE_KEY' not in x for x in platform) if transport=='direct' else sum('TEST_RULE_PRIVATE_KEY' in x for x in platform)==3)
                saved=page.evaluate('async()=>JSON.stringify(await InvestmentRuleScreen.read("rule-test:'+account['id']+':rule-v2"))');self.assertNotIn('TEST_RULE_PRIVATE_KEY',saved)
                self.assertEqual(errors,[]);self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                page.screenshot(path=f'/tmp/grow-rule-screen-{width}.png',full_page=True)
                page.reload();page.locator('#open').click();d=page.get_by_role('dialog',name='规则选股');expect(d.locator('[data-results]')).to_contain_text('入选 1');self.assertEqual(len(calls),3)
                d.locator('[data-new]').click();expect(d.locator('[data-status]')).to_contain_text('原检查点');d.locator('[data-history]').select_option(index=1);d.locator('[data-restore]').click();expect(d.locator('[data-results]')).to_contain_text('入选 1');self.assertEqual(len(calls),3)
                # 无模型仍可手工筛选；未填完的表单也应刷新恢复。
                d.locator('[data-new]').click();expect(d.locator('[data-status]')).to_contain_text('原检查点')
                d.locator('[data-clear]').click()
                while d.locator('[data-remove]').count():d.locator('[data-remove]').first.click()
                d.locator('[data-add]').click();expect(d.locator('[data-value]')).to_have_value('')
                page.wait_for_function('async()=>!!(await InvestmentRuleScreen.read("rule-test:'+account['id']+':rule-v2"))?.form_draft')
                page.reload();page.locator('#open').click();d=page.get_by_role('dialog',name='规则选股')
                expect(d.locator('[data-value]')).to_have_value('');d.locator('[data-op]').select_option('gte');d.locator('[data-value]').fill('3')
                d.get_by_text('模型配置（仅生成条件或研究候选时需要）',exact=True).click();d.locator('[data-transport]').select_option('direct');d.locator('[data-url]').fill('');d.locator('[data-model]').fill('');d.locator('[data-secret]').fill('')
                d.locator('[data-run]').click();expect(d.locator('[data-results]')).to_contain_text('入选 1');self.assertEqual(len(calls),3)
                # 陈旧标签页不能覆盖当前检查点。
                revision=page.evaluate('async()=>{const s=await InvestmentRuleScreen.read("rule-test:'+account['id']+':rule-v2");return s.revision}')
                conflict=page.evaluate('async revision=>{const s=await InvestmentRuleScreen.read("rule-test:'+account['id']+':rule-v2");try{await InvestmentRuleScreen.put(s,revision-1);return false}catch(e){return e.message.includes("另一个页面")}}',revision)
                self.assertTrue(conflict)
                ctx.close()
            browser.close()
