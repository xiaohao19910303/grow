"""Eastmoney daily units, invalid-input boundaries and existing-entry isolation."""
import json
import subprocess
import unittest
from unittest.mock import patch

from copilot.core import Problem
from investments.akshare_daily import AKShareDailyProvider,load_rows
from investments.store import InvestmentStore
from investments.screening import screen,ScreenInput
from test_legacy_cloud_schema import PostgreSQLFixture


class InvestmentAKShareWorkerTests(unittest.TestCase):
    def test_worker_calls_only_selected_daily_endpoint_without_adjustment_or_credentials(self):
        import pandas as pd
        from investments.akshare_worker import fetch
        frame=pd.DataFrame([{'日期':'2026-10-27','开盘':1.23,'最高':1.24,'最低':1.22,
            '收盘':1.234,'成交量':123,'成交额':15233.73}])
        for kind,code in [('stock','600000'),('etf','159915')]:
            with patch('akshare.stock_zh_a_hist',return_value=frame) as stock,patch('akshare.fund_etf_hist_em',return_value=frame) as etf:
                result=fetch({'kind':kind,'code':code,'start':'2026-10-23','end':'2026-10-27'})
                chosen,unused=(stock,etf) if kind=='stock' else (etf,stock)
                chosen.assert_called_once_with(symbol=code,period='daily',start_date='20261023',end_date='20261027',adjust='',
                    **({'timeout':15} if kind=='stock' else {}))
                unused.assert_not_called()
                self.assertEqual(result['rows'][0]['收盘'],'1.234')
                self.assertEqual(result['rows'][0]['成交额'],'15233.73')


class InvestmentAKShareTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        clock=patch('investments.akshare_daily.now',return_value='2026-10-28T09:00:00+08:00')
        clock.start();self.addCleanup(clock.stop)
        self.store=InvestmentStore();self.store.initialize()
        self.stock=self.store.create('instruments',{'code':'600000','name':'合成股票','market':'SSE','kind':'stock'},'s')
        self.etf=self.store.create('instruments',{'code':'159001','name':'合成ETF','market':'SZSE','kind':'etf'},'e')
        self.calls=[]
        self.packet={'library_version':'test','rows':[{'日期':'2026-10-27','开盘':'1.231','最高':'1.24','最低':'1.22',
            '收盘':'1.234','成交量':'123.45','成交额':'15233.73'}]}
        def loader(*args):
            self.calls.append(args)
            return self.packet
        self.provider=AKShareDailyProvider(self.store,loader)

    def fetch(self,instrument=None,key='daily',**kwargs):
        return self.provider.fetch((instrument or self.stock)['id'],'2026-10-23','2026-10-27',True,key,**kwargs)

    def test_stock_and_etf_keep_exact_units_provenance_evidence_and_replay(self):
        for instrument,endpoint in [(self.stock,'stock_zh_a_hist'),(self.etf,'fund_etf_hist_em')]:
            result=self.fetch(instrument,instrument['id'])
            bar=result['bars'][0]
            self.assertEqual((bar['close'],bar['source_volume'],bar['volume_shares']),('1.234','123.45','12345'))
            self.assertEqual((bar['source_amount'],bar['turnover_cny']),('15233.73','15233.73'))
            self.assertEqual(result['endpoint'],endpoint)
            self.assertEqual(result['provider'],'akshare_eastmoney');self.assertFalse(result['realtime'])
            evidence=self.store.get('research',result['evidence_id'])
            scope=json.loads(evidence['content'])['summary_scope']
            self.assertEqual(scope['stored_bar_count'],len(result['bars']))
            self.assertEqual(scope['source_completeness'],'not_independently_verified')
            self.assertIn(endpoint,evidence['content']);self.assertEqual(evidence['available_at'],result['retrieved_at'])
            self.assertEqual(self.fetch(instrument,instrument['id'])['snapshot_id'],result['snapshot_id'])
        self.assertEqual(len(self.calls),2)
        local=screen(self.store,ScreenInput(as_of='2026-10-27'))
        self.assertEqual(local['total'],2)
        self.assertEqual({r['provider'] for r in local['items']},{'akshare_eastmoney'})

    def test_empty_response_retains_existing_snapshot_without_zero_or_duplicate_evidence(self):
        saved=self.fetch()
        self.packet={'rows':[]}
        with self.assertRaises(Problem) as caught:self.fetch(key='empty')
        self.assertEqual(caught.exception.code,'provider_empty')
        self.assertEqual(self.store.get('market-snapshots',saved['snapshot_id'])['bars'],saved['bars'])
        self.assertEqual(self.store.listing('research')['total'],1)

    def test_invalid_or_closed_dates_bad_ohlc_missing_and_nonfinite_values_do_not_save(self):
        original=dict(self.packet['rows'][0])
        for change in [{'日期':'2026-10-25'},{'日期':'2026-10-29'},{'最高':'1'},{'成交量':'-1'},
                       {'成交额':'NaN'},{'成交额':None}]:
            self.packet['rows']=[{**original,**change}]
            with self.subTest(change=change):
                with self.assertRaises(Problem):self.fetch(key=str(change))
        self.packet['rows']=[original,original]
        with self.assertRaises(Problem):self.fetch(key='duplicate')
        self.assertEqual(self.store.listing('research')['total'],0)

    def test_confirmation_scope_dates_and_idempotency_are_checked_before_network(self):
        with self.assertRaises(Problem):self.provider.fetch(self.stock['id'],'2026-10-23','2026-10-27',False,'no-ack')
        for start,end in [('2026-10-28','2026-10-28'),('2026-10-23','2026-10-29'),
                          ('2026-01-01','2026-10-27'),('2026-10-28','2026-10-27')]:
            with self.assertRaises(Problem):self.provider.fetch(self.stock['id'],start,end,True,'bad-range')
        self.assertEqual(self.calls,[])
        self.fetch()
        with self.assertRaises(Problem):self.fetch(self.etf)
        self.assertEqual(len(self.calls),1)

    def test_wrong_market_bse_and_expired_calendar_never_fetch(self):
        wrong=self.store.create('instruments',{'code':'600000','name':'错误市场','market':'SZSE','kind':'stock'},'wrong')
        bse=self.store.create('instruments',{'code':'920001','name':'北交所','market':'BSE','kind':'stock'},'bse')
        for instrument in [wrong,bse]:
            with self.assertRaises(Problem):self.fetch(instrument)
        with patch('investments.akshare_daily.now',return_value='2026-12-01T09:00:00+08:00'):
            with self.assertRaises(Problem):self.fetch()
        self.assertEqual(self.calls,[])

    def test_timeout_and_upstream_error_are_bounded_and_do_not_echo_details(self):
        with patch('investments.akshare_daily.subprocess.run',side_effect=subprocess.TimeoutExpired('worker',45)) as run:
            with self.assertRaises(Problem) as caught:load_rows('stock','600000','2026-10-23','2026-10-27')
            self.assertEqual(caught.exception.code,'provider_timeout')
            self.assertEqual(run.call_args.kwargs['timeout'],45)
        result=subprocess.CompletedProcess([],0,'{"error":"upstream_unavailable"}','PRIVATE_FAILURE_DETAIL')
        with patch('investments.akshare_daily.subprocess.run',return_value=result):
            with self.assertRaises(Problem) as caught:load_rows('etf','159001','2026-10-23','2026-10-27')
            self.assertNotIn('PRIVATE_FAILURE_DETAIL',caught.exception.message)
        for output,code in [('[]','provider_unavailable'),('{"error":"dependency_missing"}','provider_dependency_missing')]:
            with patch('investments.akshare_daily.subprocess.run',return_value=subprocess.CompletedProcess([],0,output,'')):
                with self.assertRaises(Problem) as caught:load_rows('stock','600000','2026-10-23','2026-10-27')
                self.assertEqual(caught.exception.code,code)
        self.assertEqual(self.store.listing('research')['total'],0)
