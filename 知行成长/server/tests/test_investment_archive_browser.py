"""Real Chrome with production UI and APIs, isolated DB, desktop/mobile archive flows."""
import json,os,socket,tempfile,threading,time
from pathlib import Path
from unittest.mock import patch
import db,uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import sync_playwright,expect
from investments.api import register
from investments.research_tools import ResearchTools,DatasetInput,ScreenInput
from test_legacy_cloud_schema import PostgreSQLFixture

class ResearchArchiveBrowserTests(PostgreSQLFixture):
    def test_archive_compare_export_reopen_paging_desktop_mobile(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        env=patch.dict(os.environ,{'INVESTMENT_RESEARCH_ARCHIVE_ROOT':tmp.name+'/archive'});env.start();self.addCleanup(env.stop)
        app=FastAPI();store=register(app);store.initialize();tools=ResearchTools(store)
        account=store.create('accounts',{'name':'Archive UI fixture','baseline_date':'2026-10-19','opening_cash':'10000'},'archive-ui-account');runs=[]
        for n in range(2):
            dataset=tools.dataset(DatasetInput(account_id=account['id'],source_label='合法CSV',use_confirmed=True,market_date='2026-10-'+str(28+n),rows=[{'code':'000001','name':'<script>text only</script>','values':{'close':'11.000000000'+str(n+1)}}]),'ui-data-'+str(n))
            runs.append(tools.screen(ScreenInput(account_id=account['id'],dataset_id=dataset['id'],conditions=[{'field':'close','op':'gt','value':'10'}]),'ui-screen-'+str(n)))
        from investments.research_history import SeriesInput,save_series,run_backtest,BacktestInput
        from test_investment_strategy_backtest import series
        from investments.strategy_backtest import BacktestConfig
        history=series();history.pop('sessions');saved=save_series(tools,SeriesInput(account_id=account['id'],use_confirmed=True,**history),'archive-ui-history')
        base={'strategy':'threshold','entry_above':'10','exit_below':'10','initial_cash':'10000','quantity':'100','commission_rate':'0','minimum_commission':'0','slippage_bps':'0','sell_tax_rate':'0','max_participation':'1'}
        backtests=[run_backtest(tools,BacktestInput(account_id=account['id'],series_id=saved['id'],config=BacktestConfig(**{**base,'minimum_commission':str(fee)})),'archive-ui-backtest-'+str(fee)) for fee in (0,5)]
        with db.connect() as c,patch('investments.research_tools.now',return_value='2026-11-01T00:00:00+08:00'):
            for n in range(51):tools.save(c,'dataset',account['id'],{**dataset['data'],'source_label':'分页快照'+str(n)})
        static=Path(__file__).resolve().parents[1]/'static';app.mount('/static',StaticFiles(directory=static))
        @app.get('/')
        def index():return HTMLResponse('<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/static/design-tokens.css"><link rel="stylesheet" href="/static/investments.css"><link rel="stylesheet" href="/static/investment-research.css"><button id="open">市场研究工具</button><script>window.Account={user:{id:"archive-ui"},verify:async()=>true,isCurrent:()=>true};</script><script src="/static/investment-research-charts.js"></script><script src="/static/investment-research-archive.js"></script><script src="/static/investment-research.js"></script><script>document.getElementById("open").onclick=()=>InvestmentResearch.open('+json.dumps({'accountId':account['id']})+');</script></html>')
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close();server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'));thread=threading.Thread(target=server.run,daemon=True);thread.start();self.addCleanup(lambda:(setattr(server,'should_exit',True),thread.join(5)))
        for _ in range(100):
            if server.started:break
            time.sleep(.03)
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
            for width in (1440,390):
                page=browser.new_page(viewport={'width':width,'height':1000});errors=[];page.on('pageerror',lambda error:errors.append(str(error)));page.goto('http://127.0.0.1:'+str(port));page.locator('#open').click();dialog=page.get_by_role('dialog');dialog.get_by_role('tab',name='归档与对比',exact=True).click()
                expect(dialog.locator('[data-archive-enabled]')).to_contain_text('私有归档已启用');dialog.locator('[data-archive-next]').click();expect(dialog.locator('[data-archive-page]')).to_contain_text('第2页')
                verify=dialog.locator('[data-archive-verify]').first;expect(verify).to_be_visible();verify.click();expect(dialog.locator('[data-status]')).to_contain_text('校验通过')
                with page.expect_download() as download:dialog.locator('[data-archive-download]').first.click()
                self.assertEqual(download.value.suggested_filename,'research-archive.zip')
                dialog.locator('[data-compare-left]').select_option(runs[0]['id']);dialog.locator('[data-compare-right]').select_option(runs[1]['id']);dialog.locator('[data-compare-name]').fill('同规则跨日'+str(width));dialog.locator('[data-compare-create]').click();expect(dialog.locator('[data-comparison-result]')).to_contain_text('0.0000000001');expect(dialog.locator('[data-comparison-result]')).to_contain_text('<script>text only</script>');self.assertEqual(dialog.locator('[data-comparison-result] script').count(),0)
                for format in ('json','csv'):
                    with page.expect_download() as download:dialog.locator('[data-comparison-'+format+']').click()
                    self.assertEqual(download.value.suggested_filename,'research-comparison.'+format)
                self.assertLessEqual(dialog.evaluate('e=>e.scrollWidth-e.clientWidth'),1);self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                page.screenshot(path='/tmp/grow-archive-ui-'+str(width)+'.png',full_page=True)
                dialog.locator('[data-close]').click();page.locator('#open').click();dialog=page.get_by_role('dialog');dialog.get_by_role('tab',name='归档与对比',exact=True).click();dialog.locator('[data-compare-history]').select_option(index=1);dialog.locator('[data-compare-open]').click();expect(dialog.locator('[data-comparison-result]')).to_contain_text('0.0000000001');dialog.locator('[data-compare-kind]').select_option('backtest');expect(dialog.locator('[data-compare-left]')).to_contain_text('v1');dialog.locator('[data-compare-left]').select_option(backtests[0]['id']);dialog.locator('[data-compare-right]').select_option(backtests[1]['id']);dialog.locator('[data-compare-create]').click();expect(dialog.locator('[data-comparison-result]')).to_contain_text('net_profit');expect(dialog.locator('[data-comparison-result]')).to_contain_text('-10');self.assertEqual(errors,[]);page.close()
            browser.close()
        self.assertEqual(store.balance(account['id'])['cash'],'10000')
