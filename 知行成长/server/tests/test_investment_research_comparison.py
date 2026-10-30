"""Frozen comparisons separate rule changes, coverage and unknowns; exact deltas."""
import json,os
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from investments.api import register
from test_legacy_cloud_schema import PostgreSQLFixture

class ResearchComparisonTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp();app=FastAPI();self.store=register(app);self.store.initialize();self.client=TestClient(app);self.addCleanup(self.client.close)
        self.account=self.store.create('accounts',{'name':'对比账户','baseline_date':'2026-10-19','opening_cash':'10000'},'compare-account')
    def post(self,path,body,key,status=201):
        r=self.client.post('/api/investments/research/'+path,json=body,headers={'X-Copilot-Request':'1','Idempotency-Key':key});self.assertEqual(r.status_code,status,r.text[:400]);return r.json()
    def screen(self,key,day,rows,threshold='10'):
        dataset=self.post('datasets',{'account_id':self.account['id'],'market_date':day,'source_label':'同一合法CSV来源','use_confirmed':True,'rows':[{'code':code,'name':code,'values':{'close':price}} for code,price in rows]},key+'-dataset')
        return self.post('screens',{'account_id':self.account['id'],'dataset_id':dataset['id'],'conditions':[{'field':'close','op':'gt','value':threshold}]},key+'-screen')
    def compare(self,left,right,key='compare-pair'):
        return self.post('comparisons',{'account_id':self.account['id'],'left_id':left['id'],'left_version':left['version'],'right_id':right['id'],'right_version':right['version']},key)
    def test_date_comparison_distinguishes_unknown_and_coverage_from_rule_exit(self):
        left=self.screen('left','2026-10-28',[('000001','11.0000000001'),('600000','20'),('300001',None),('600001','9')])
        right=self.screen('right','2026-10-29',[('000001','11.0000000002'),('300001','12'),('600001','11'),('600002','15')])
        compared=self.compare(left,right);result=compared['data']['result'];self.assertEqual(result['mode'],'same_rules_different_dates')
        by_code={r['code']:r for r in result['changes']};self.assertEqual(by_code['600000.SH']['category'],'coverage_removed')
        self.assertEqual(by_code['300001.SZ']['category'],'unknown_transition');self.assertEqual(by_code['600001.SH']['category'],'entered')
        self.assertEqual(by_code['000001.SZ']['value_changes'][0]['delta'],'0.0000000001')
        self.assertEqual(self.compare(left,right),compared);self.assertEqual(self.store.balance(self.account['id'])['cash'],'10000')
    def test_mixed_inputs_are_labeled_and_other_account_cannot_compare(self):
        left=self.screen('left','2026-10-28',[('000001','11')]);right=self.screen('right','2026-10-29',[('000001','12')],'11')
        result=self.compare(left,right)['data']['result'];self.assertEqual(result['mode'],'mixed_inputs');self.assertTrue(result['warnings']);self.assertFalse(result['comparable'])
        other=self.store.create('accounts',{'name':'另一账户','baseline_date':'2026-10-19','opening_cash':'0'},'compare-other')
        self.post('comparisons',{'account_id':other['id'],'left_id':left['id'],'left_version':1,'right_id':right['id'],'right_version':1},'wrong-comparison',422)
    def test_backtest_cost_difference_matches_exact_hand_calculation(self):
        from test_investment_strategy_backtest import series
        data=series();data.pop('sessions');saved=self.post('series',{'account_id':self.account['id'],'use_confirmed':True,**data},'compare-series')
        config={'strategy':'threshold','entry_above':'10','exit_below':'10','initial_cash':'10000','quantity':'100','commission_rate':'0','minimum_commission':'0','slippage_bps':'0','sell_tax_rate':'0','max_participation':'1'}
        a=self.post('backtests',{'account_id':self.account['id'],'series_id':saved['id'],'config':config},'compare-backtest-a')
        b=self.post('backtests',{'account_id':self.account['id'],'series_id':saved['id'],'config':{**config,'minimum_commission':'5'}},'compare-backtest-b')
        result=self.compare(a,b)['data']['result'];self.assertTrue(result['comparable']);metrics={r['field']:r for r in result['metrics']}
        self.assertEqual(metrics['net_profit']['delta'],'-10');self.assertEqual(metrics['total_fees_and_tax']['delta'],'10')
        self.assertEqual(result['summary']['trade_changed'],2)

    def test_incompatible_baseline_suppresses_every_delta_and_csv_retains_null(self):
        from investments.research_comparison import backtest_result,export_csv
        def record(cash):return {'data':{'request':{'config':{'initial_cash':cash}},'series_hash':'same','result':{'status':'complete','algorithm':'same','metrics':{'sharpe':None,'net_profit':'2'},'trades':[{'time':'T','side':'buy','cash_after':cash}],'orders':[{'signal_at':'S','cash':cash}]}}}
        a,b=record('1000'),record('2000');result=backtest_result(a,b,{'data':{}},{'data':{}})
        self.assertFalse(result['comparable']);self.assertTrue(all(r['delta'] is None for r in result['metrics']))
        for group in ('changes','order_changes'):
            self.assertTrue(all(f['delta'] is None for r in result[group] for f in r['fields']))
        self.assertIn('metrics,sharpe,null,null,null',export_csv({'data':{'result':result}}))
