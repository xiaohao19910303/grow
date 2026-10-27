import json
import db
from copilot.core import Problem
from investments.legacy import link_record, list_legacy
from investments.store import InvestmentStore
from test_legacy_cloud_schema import PostgreSQLFixture


class InvestmentLegacyBridgeTests(PostgreSQLFixture):
    def test_reconciled_link_does_not_import_estimated_profit_or_change_legacy(self):
        store=InvestmentStore();store.initialize()
        original={'id':'old-sell','stock_code':'510000','stock_name':'旧卖出','action':'sell','price':1.234,
            'quantity':100,'profit_loss':-3.5,'actual_price':1.269,'date':'2026-10-26'}
        with db.connect() as c:
            c.execute('CREATE TABLE stock_records(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
            c.execute('INSERT INTO stock_records VALUES (?,?)',('old-sell',json.dumps(original)))
        i=store.create('instruments',{'name':'ETF','code':'510000','market':'SSE','kind':'etf'},'i')
        a=store.create('accounts',{'name':'账户','opening_cash':'0','baseline_date':'2026-10-26',
            'opening_positions':[{'instrument_id':i['id'],'quantity':'100','cost':None}]},'a')
        fill=store.create('fills',{'account_id':a['id'],'instrument_id':i['id'],'side':'sell','price':'1.234',
            'quantity':'100','fee':'0','tax':'0','executed_at':'2026-10-26T10:00:00+08:00'},'f')
        link=link_record(store,'old-sell','fills',fill['id'],'本人核对券商成交；旧比较盈亏不采用',True,'link')
        again=link_record(store,'old-sell','fills',fill['id'],'本人核对券商成交；旧比较盈亏不采用',True,'link-again')
        self.assertEqual(link['id'],again['id'])
        self.assertEqual(store.listing('fills')['total'],1)
        self.assertIsNone(store.balance(a['id'])['net_realized'])
        self.assertEqual(list_legacy(store)['items'][0]['original'],original)
        with db.connect() as c:self.assertEqual(json.loads(c.execute('SELECT data FROM stock_records').fetchone()[0]),original)
        with self.assertRaises(Problem):link_record(store,'not-mine','fills',fill['id'],'核对',True,'bad')
