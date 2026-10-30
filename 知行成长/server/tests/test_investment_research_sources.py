"""Controlled source contracts, cache/replay and private research restore."""
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import db
import psycopg2
from fastapi import FastAPI
from fastapi.testclient import TestClient
from investments.api import register
from test_legacy_cloud_schema import PostgreSQLFixture
from test_investment_strategy_backtest import series


class ResearchSourceTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp();app=FastAPI();self.store=register(app);self.store.initialize();self.client=TestClient(app);self.addCleanup(self.client.close)
        self.account=self.store.create('accounts',{'name':'来源测试','baseline_date':'2026-10-19','opening_cash':'10000'},'source-account')
    def post(self,path,body,key,status=201):
        response=self.client.post('/api/investments/research/'+path,json=body,headers={'X-Copilot-Request':'1','Idempotency-Key':key})
        self.assertEqual(response.status_code,status,response.text);return response.json()
    def test_market_and_history_adapters_preserve_units_and_replay_without_fetch(self):
        packet={'library_version':'test','rows':[{'代码':'000001','名称':'合成甲','最新价':'10','成交量':'123','成交额':'123000','换手率':'3'}]}
        body={'account_id':self.account['id'],'use_confirmed':True}
        with patch('investments.research_sources.now',return_value='2026-10-29T16:00:00+08:00'),patch('investments.research_sources.worker',return_value=packet) as fetch:
            first=self.post('provider/akshare/market',body,'source-market');replay=self.post('provider/akshare/market',body,'source-market')
        self.assertEqual(first,replay);self.assertEqual(fetch.call_count,1)
        self.assertEqual(first['data']['rows'][0]['values']['volume_shares'],'12300')
        history={'library_version':'test','rows':[{'日期':'2026-10-28','开盘':'10','最高':'11','最低':'9','收盘':'10','成交量':'100','成交额':'100000'}]}
        payload={**body,'code':'000001','name':'合成甲','interval':'day','start':'2026-10-28','end':'2026-10-28'}
        with patch('investments.research_sources.worker',return_value=history) as fetch:
            saved=self.post('provider/akshare/history',payload,'source-history')
            cached=self.post('provider/akshare/history',payload,'source-cache')
        self.assertEqual(saved['id'],cached['id']);self.assertEqual(fetch.call_count,1)
        self.assertIsNone(saved['data']['bars'][0]['suspended'])
    def test_tencent_market_is_explicit_and_history_shares_are_not_multiplied_twice(self):
        packet={'library_version':'1.20.1','upstream':'tencent','rows':[{'code':'sz000001','name':'合成甲','zxj':'11','volume':'123','turnover':'456','zsz':'789','pe_ttm':'5.2','pn':'0.47'}]}
        body={'account_id':self.account['id'],'use_confirmed':True,'source':'tencent'}
        with patch('investments.research_sources.now',return_value='2026-10-30T16:00:00+08:00'),patch('investments.research_sources.worker',return_value=packet) as fetch:
            saved=self.post('provider/akshare/market',body,'source-tencent-market')
            self.assertEqual(self.post('provider/akshare/market',body,'source-tencent-market'),saved)
        self.assertEqual(fetch.call_count,1);self.assertEqual(fetch.call_args.args[0]['source'],'tencent')
        values=saved['data']['rows'][0]['values'];self.assertEqual(values['turnover_cny'],'4560000');self.assertNotIn('pe',values)
        self.assertEqual(saved['data']['upstream'],'tencent');self.assertIn('腾讯',saved['data']['source_label'])
        history={'library_version':'1.20.1','upstream':'tencent','volume_unit':'shares','rows':[{'日期':'2026-10-28','开盘':'10','最高':'11','最低':'9','收盘':'10','成交量':'12300','成交额':'123000'}]}
        payload={**body,'code':'000001','name':'合成甲','interval':'day','start':'2026-10-28','end':'2026-10-28'}
        with patch('investments.research_sources.worker',return_value=history) as fetch:
            source=self.post('provider/akshare/history',payload,'source-tencent-history')
            cached=self.post('provider/akshare/history',payload,'source-tencent-cache')
            self.post('provider/akshare/history',{**payload,'interval':'minute'},'source-tencent-minute',422)
        self.assertEqual(fetch.call_count,1);self.assertEqual(source['id'],cached['id'])
        self.assertEqual(source['data']['bars'][0]['volume_shares'],'12300')

    def test_configured_interface_is_not_refetched_and_never_persists_token(self):
        calls=[]
        async def interface(payload):
            calls.append(payload.token);return {'market_date':'2026-10-28','rows':[{'code':'000001','name':'合成','values':{'close':'10'}}]}
        body={'account_id':self.account['id'],'kind':'dataset','url':'https://data.example/quotes','token':'SOURCE_TEST_ONLY_SECRET','source_label':'本人来源','use_confirmed':True}
        with patch('investments.research_sources.interface_json',interface):
            first=self.post('interface',body,'source-interface',200)
            self.assertEqual(self.post('interface',body,'source-interface',200),first)
        self.assertEqual(calls,['SOURCE_TEST_ONLY_SECRET'])
        with db.connect() as c:
            content=''.join(r[0] for r in c.execute('SELECT response FROM investment_requests'))
        self.assertNotIn(body['token'],content)
    def test_interrupted_akshare_read_is_not_fetched_again_with_same_key(self):
        from copilot.core import fail
        body={'account_id':self.account['id'],'use_confirmed':True}
        def lost(_):fail('provider_timeout','controlled timeout',504)
        with patch('investments.research_sources.now',return_value='2026-10-29T16:00:00+08:00'),patch('investments.research_sources.worker',side_effect=lost) as fetch:
            self.post('provider/akshare/market',body,'source-lost',504)
            self.post('provider/akshare/market',body,'source-lost',409)
        self.assertEqual(fetch.call_count,1)
    def test_bad_financial_timestamp_is_validation_and_long_csv_remains_replayable(self):
        body={'account_id':self.account['id'],'market_date':'2026-10-28','source_label':'本人CSV','use_confirmed':True,'text':'code,name,roe_pct,known_at\n000001,合成,10,garbage\n'}
        self.post('datasets/csv',body,'source-bad-timestamp',422)
        history={'account_id':self.account['id'],'code':'000001','name':'合成','source_label':'本人历史','use_confirmed':True,'text':'date,open,high,low,close,volume_shares\n2025-01-02,10,11,9,10,1000\n2026-10-28,10,11,9,10,1000\n'}
        saved=self.post('series/csv',history,'source-long-csv')
        self.assertEqual(len(saved['data']['bars']),2)
        self.assertEqual(saved['data']['calendar_status'],'coverage_unknown')
    def test_csv_and_backtest_survive_private_schema_backup_restore(self):
        payload={'account_id':self.account['id'],'market_date':'2026-10-28','source_label':'本人CSV','use_confirmed':True,'text':'code,name,close,pe\n000001,合成,10,8\n'}
        dataset=self.post('datasets/csv',payload,'source-csv')
        data=series();data.pop('sessions')
        historical=self.post('series',{'account_id':self.account['id'],'use_confirmed':True,**data},'source-series')
        run=self.post('backtests',{'account_id':self.account['id'],'series_id':historical['id'],'config':{'strategy':'threshold','entry_above':'10','exit_below':'10','slippage_bps':'0'},'out_of_sample_start':'2026-10-22','variants':[{'slippage_bps':'20'}]},'source-backtest')
        self.assertEqual(run['data']['result']['status'],'complete')
        before=self.client.get('/api/investments/research/export',params={'account_id':self.account['id']}).json()
        with tempfile.TemporaryDirectory() as folder:
            archive=Path(folder)/'research.dump'
            subprocess.run(['pg_dump','--dbname',self.dsn,'--schema',self.schema,'--format=custom','--file',str(archive)],check=True,capture_output=True)
            with psycopg2.connect(self.dsn) as c:c.cursor().execute('DROP SCHEMA '+self.schema+' CASCADE')
            subprocess.run(['pg_restore','--dbname',self.dsn,str(archive)],check=True,capture_output=True)
        after=self.client.get('/api/investments/research/export',params={'account_id':self.account['id']}).json()
        self.assertEqual(before['objects'],after['objects']);self.assertEqual(before['versions'],after['versions'])
        self.assertEqual(self.store.balance(self.account['id'])['cash'],'10000')
