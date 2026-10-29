"""Unified provider contracts and real private PostgreSQL writes; no supplier access."""
import importlib.util
import os
from datetime import date
from decimal import localcontext
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import pandas as pd
import db
from investments.market_data import AKShareProvider, MarketDataError, normalized_daily, stock_identity
from test_legacy_cloud_schema import PostgreSQLFixture


class MarketProviderTests(TestCase):
    def test_misleading_test_dsn_is_rejected_before_connection(self):
        fake="host=production.example application_name='host=127.0.0.1' port=55441 user=test dbname=test"
        with patch.dict(os.environ,{'TEST_LEGACY_PG_DSN':fake}),patch('psycopg2.connect') as connect:
            with self.assertRaises(RuntimeError):PostgreSQLFixture().setUp()
            connect.assert_not_called()
    def test_conflicting_response_identity_and_storage_rounding_are_rejected(self):
        with self.assertRaises(MarketDataError):
            stock_identity({'ts_code':'000001.SZ','code':'600000','name':'矛盾身份'})
        row={'ts_code':'600000.SH','trade_date':'20261028','open':'10','high':'11','low':'9','close':'10','vol':'100','amount':'1000'}
        with self.assertRaises(MarketDataError):
            normalized_daily([row],'000001.SZ',date(2026,10,28),date(2026,10,28),'tushare')
        row={**row,'ts_code':'000001.SZ','vol':'123456789012345678.123456789012'}
        with self.assertRaises(MarketDataError):
            normalized_daily([row],'000001.SZ',date(2026,10,28),date(2026,10,28),'tushare')
        with localcontext() as ctx:
            ctx.prec=6
            result=normalized_daily([{'date':'2026-10-28','open':'10','high':'11','low':'9','close':'10','volume':'123456789.12','amount':'123456789.12'}],'000001.SZ',date(2026,10,28),date(2026,10,28),'akshare')
            self.assertEqual(result[0]['vol'],'1234567.8912')
    def test_identity_and_daily_units_are_canonical(self):
        provider = AKShareProvider()
        with patch.object(provider.ak, 'stock_info_a_code_name', return_value=pd.DataFrame([
                {'code': '000001', 'name': '深圳合成'}, {'code': '600000', 'name': '上海合成'},
                {'code': '920001', 'name': '北京合成'}])):
            rows = provider.get_stock_list()
        self.assertEqual([r['ts_code'] for r in rows], ['000001.SZ', '600000.SH', '920001.BJ'])
        frame = pd.DataFrame([{'date': date(2026, 10, 28), 'open': 10, 'high': 11,
            'low': 9, 'close': 10, 'volume': 12345, 'amount': 123456.7}])
        with patch.object(provider.ak, 'stock_zh_a_daily', return_value=frame) as fetch:
            rows = provider.get_daily_data('000001.SZ', date(2026, 10, 28), date(2026, 10, 28))
        fetch.assert_called_once_with(symbol='sz000001', start_date='20261028', end_date='20261028', adjust='')
        self.assertEqual(rows[0]['trade_date'], date(2026, 10, 28))
        self.assertEqual((rows[0]['vol'], rows[0]['amount']), ('123.45', '123.4567'))

    def test_invalid_identity_duplicate_dates_and_nonfinite_price_are_rejected(self):
        provider = AKShareProvider()
        for code in ('000001.SH', 'abc', '123456.XX'):
            with self.subTest(code=code), self.assertRaises(MarketDataError):
                provider.get_daily_data(code, date(2026,10,28), date(2026,10,28))
        row = {'date': date(2026,10,28), 'open': 10, 'high': 11, 'low': 9, 'close': 10, 'volume': 100, 'amount': 1000}
        for rows in ([row, row], [{**row, 'close': float('nan')}], [{**row, 'volume': -1}]):
            with patch.object(provider.ak, 'stock_zh_a_daily', return_value=pd.DataFrame(rows)), self.assertRaises(MarketDataError):
                provider.get_daily_data('000001.SZ', date(2026,10,28), date(2026,10,28))


class MarketSyncTests(PostgreSQLFixture):
    def test_cli_sync_preserves_shenzhen_identity_and_persists_normalized_daily(self):
        spec = importlib.util.spec_from_file_location('market_sync_fixture', Path(__file__).resolve().parents[3]/'docs/sync_market_data.py')
        sync = importlib.util.module_from_spec(spec); spec.loader.exec_module(sync)
        sync.initialize_tables()
        provider = AKShareProvider()
        frame = pd.DataFrame([{'date': date(2026,10,28), 'open':10,'high':11,'low':9,'close':10,'volume':12345,'amount':123456.7}])
        with patch.object(sync,'get_provider',return_value=provider), patch.object(provider.ak,'stock_info_a_code_name',return_value=pd.DataFrame([{'code':'000001','name':'深圳合成'}])), patch.object(provider.ak,'stock_zh_a_daily',return_value=frame):
            self.assertEqual(sync.sync_stock_list('akshare'),1)
            self.assertEqual(sync.sync_daily_data('sz000001',date(2026,10,28),date(2026,10,28),'akshare'),1)
        with db.connect() as c:
            stock=c.execute('SELECT ts_code,market FROM investment_stock_basic').fetchone()
            self.assertEqual((stock[0],stock[1]),('000001.SZ','SZSE'))
            row=c.execute('SELECT trade_date,vol,amount FROM investment_daily_data').fetchone()
            self.assertEqual(row[0],date(2026,10,28))
            self.assertEqual((str(row[1].normalize()),str(row[2].normalize())),('123.45','123.4567'))
