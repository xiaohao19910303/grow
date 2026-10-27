from copilot.core import Problem
from investments.store import InvestmentStore
from investments.reviews import period_summary
from test_legacy_cloud_schema import PostgreSQLFixture


class InvestmentReconciliationTests(PostgreSQLFixture):
    def test_corporate_action_marks_results_unknown_until_user_records_resolution(self):
        store=InvestmentStore();store.initialize()
        a=store.create('accounts',{'name':'账户','opening_cash':'10000','baseline_date':'2026-10-26'},'a')
        i=store.create('instruments',{'name':'ETF','code':'510000','market':'SSE','kind':'etf'},'i')
        store.create('fills',{'account_id':a['id'],'instrument_id':i['id'],'side':'buy','price':'10','quantity':'100',
            'fee':'0','tax':'0','executed_at':'2026-10-26T10:00:00+08:00'},'f')
        issue=store.create('ledger-notices',{'account_id':a['id'],'instrument_id':i['id'],'kind':'corporate_action',
            'observed_at':'2026-10-27T10:00:00+08:00','reason':'疑似份额折算，尚未核对'},'issue')
        balance=store.balance(a['id'])
        self.assertIsNone(balance['net_realized']);self.assertFalse(balance['cash_verified'])
        self.assertFalse(balance['positions'][0]['quantity_verified'])
        self.assertIsNone(store.campaigns(a['id'])[0]['net_realized'])
        self.assertIsNone(period_summary(store,a['id'],'2026-10-26','2026-10-31')['net_realized'])
        with self.assertRaises(Problem):store.update('ledger-notices',issue['id'],1,{'status':'resolved'},'bad')
        store.update('ledger-notices',issue['id'],1,{'status':'resolved','resolution':'核对原始资料，实际未发生折算；原账与券商一致'},'resolve')
        self.assertEqual(store.balance(a['id'])['positions'][0]['quantity'],'100')
        self.assertEqual(store.balance(a['id'])['net_realized'],'0')
        self.assertEqual(store.history('ledger-notices',issue['id'])[0]['status'],'open')
