"""Disposable PostgreSQL transactions, versions and accounting."""
import concurrent.futures

from copilot.core import Problem
from test_legacy_cloud_schema import PostgreSQLFixture
from investments.store import InvestmentStore


class InvestmentStoreTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        self.store = InvestmentStore()
        self.store.initialize()
        self.account = self.store.create('accounts', {'name':'交易', 'baseline_date':'2026-10-26',
            'opening_cash':'10000'}, 'account')
        self.instrument = self.store.create('instruments', {'code':'510000','name':'测试ETF',
            'market':'SSE', 'kind':'etf'}, 'instrument')

    def fill(self, key, side='buy', price='10', quantity='100', **extra):
        return self.store.create('fills', {'account_id':self.account['id'],
            'instrument_id':self.instrument['id'], 'side':side, 'price':price,
            'quantity':quantity, 'fee':'1', 'tax':'0',
            'executed_at':'2026-10-26T10:00:00+08:00', **extra}, key)

    def test_idempotent_fill_replay_and_same_key_conflict(self):
        first = self.fill('buy1')
        self.assertEqual(first, self.fill('buy1'))
        with self.assertRaises(Problem):
            self.fill('buy1',price='11')
        self.assertEqual(self.store.listing('fills')['total'],1)

    def test_partial_sale_and_transactional_oversell(self):
        self.fill('b1')
        self.fill('b2',price='12')
        self.fill('s1',side='sell',price='13',quantity='50')
        result = self.store.balance(self.account['id'], {self.instrument['id']:'12'})
        self.assertEqual(result['cash'],'8447')
        self.assertEqual(result['net_realized'],'98.5')
        before=self.store.listing('fills')['total']
        with self.assertRaises(Problem):
            self.fill('too-many',side='sell',quantity='500')
        self.assertEqual(self.store.listing('fills')['total'],before)

    def test_concurrent_same_request_is_written_once(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:self.fill('same-concurrent'),range(4)))
        self.assertEqual(len({x['id'] for x in results}),1)
        self.assertEqual(self.store.listing('fills')['total'],1)

    def test_unknown_opening_reference_and_bad_time_rejected(self):
        with self.assertRaises(Problem):
            self.store.create('accounts',{'name':'bad','baseline_date':'2026-10-26',
                'opening_cash':'100','opening_positions':[{'instrument_id':'missing',
                'quantity':'1'}]},'bad-account')
        with self.assertRaises(Problem):
            self.fill('too-old',executed_at='2026-10-25T10:00:00+08:00')

    def test_private_missing_object_and_version_history(self):
        with self.assertRaises(Problem) as error:
            self.store.get('accounts','missing')
        self.assertEqual(error.exception.status,404)
        review=self.store.create('reviews',{'account_id':self.account['id'],
            'date':'2026-10-26','text':'今天条件没到，未交易','no_trade':True},'review')
        updated=self.store.update('reviews',review['id'],1,{'account_id':self.account['id'],
            'date':'2026-10-26','text':'继续等待，明天核对公告','no_trade':True},'edit-review')
        self.assertEqual(updated['version'],2)
        self.assertEqual(self.store.history('reviews',review['id'])[0]['text'],review['text'])
        with self.assertRaises(Problem):
            self.store.update('reviews',review['id'],1,review,'stale')

    def test_fill_external_id_deduplicates_different_request_key(self):
        a=self.fill('a',external_id='broker-1')
        b=self.fill('b',external_id='broker-1')
        self.assertEqual(a['id'],b['id'])
        with self.assertRaises(Problem):
            self.fill('c',external_id='broker-1',price='20')
