"""User-provided unadjusted OHLCV supports local screening without paid credentials."""
from copilot.core import Problem
from investments.market_import import import_history
from investments.screening import ScreenInput, screen
from investments.store import InvestmentStore
from test_legacy_cloud_schema import PostgreSQLFixture


class InvestmentMarketImportTests(PostgreSQLFixture):
    def test_csv_units_preview_basis_and_repeatable_snapshot(self):
        store=InvestmentStore();store.initialize()
        instrument=store.create('instruments',{'name':'ETF','code':'510000','market':'SSE','kind':'etf'},'i')
        text='date,open,high,low,close,volume,amount\n2026-10-23,1.1,1.3,1,1.2,100,120\n2026-10-26,1.2,1.4,1.1,1.3,200,260\n'
        result=import_history(store,instrument['id'],text,'lots','thousand_cny','BaoStock导出',True,'import')
        self.assertEqual(result['bars'][-1]['volume_shares'],'20000')
        self.assertEqual(result['bars'][-1]['turnover_cny'],'260000')
        self.assertEqual(result['freshness'],'manual_unverified')
        again=import_history(store,instrument['id'],text,'lots','thousand_cny','BaoStock导出',True,'import')
        self.assertEqual(result['snapshot_id'],again['snapshot_id'])
        selected=screen(store,ScreenInput.model_validate({'as_of':'2026-10-26','conditions':[
            {'field':'close','op':'gte','value':'1.25'}]}))
        self.assertEqual(selected['total'],1)
        self.assertFalse(selected['full_market'])

    def test_unacknowledged_or_inconsistent_bars_do_not_enter_cache(self):
        store=InvestmentStore();store.initialize()
        instrument=store.create('instruments',{'name':'ETF','code':'510000','market':'SSE','kind':'etf'},'i')
        bad='date,open,high,low,close,volume,amount\n2026-10-26,10,9,11,12,1,1\n'
        with self.assertRaises(Problem):
            import_history(store,instrument['id'],bad,'shares','cny','本人导出',True,'bad')
        self.assertEqual(store.listing('research')['total'],0)
        negative='date,open,high,low,close,volume,amount\n2026-10-26,10,12,9,11,-1,1\n'
        with self.assertRaises(Problem) as caught:
            import_history(store,instrument['id'],negative,'shares','cny','本人导出',True,'negative')
        self.assertEqual(caught.exception.status,422)

    def test_public_holiday_record_and_incomplete_today_are_rejected(self):
        from unittest.mock import patch
        store=InvestmentStore();store.initialize()
        instrument=store.create('instruments',{'name':'股票','code':'600000','market':'SSE','kind':'stock'},'i')
        text='date,open,high,low,close,volume,amount\n2026-10-01,10,11,9,10,1,10\n'
        with patch('investments.market_import.now',return_value='2026-10-28T15:10:00+08:00'):
            with self.assertRaises(Problem) as caught:
                import_history(store,instrument['id'],text,'shares','cny','合成来源',True,'closed')
            self.assertEqual(caught.exception.code,'closed_session_record')
            with self.assertRaises(Problem):
                import_history(store,instrument['id'],text.replace('2026-10-01','2026-10-28'),'shares','cny','合成来源',True,'incomplete')
        self.assertEqual(store.listing('research')['total'],0)

    def test_long_historical_span_retains_unknown_calendar_instead_of_crashing(self):
        from unittest.mock import patch
        store=InvestmentStore();store.initialize()
        instrument=store.create('instruments',{'name':'股票','code':'600000','market':'SSE','kind':'stock'},'i')
        text='date,open,high,low,close,volume,amount\n2024-01-02,10,11,9,10,1,10\n2026-10-27,10,11,9,10,1,10\n'
        with patch('investments.market_import.now',return_value='2026-10-28T09:00:00+08:00'):
            result=import_history(store,instrument['id'],text,'shares','cny','合成历史来源',True,'long-history')
        self.assertEqual(result['calendar_comparison']['status'],'coverage_unknown')
        self.assertEqual(len(result['bars']),2)
