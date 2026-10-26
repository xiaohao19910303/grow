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

    def test_confirmed_versions_and_plan_snapshot_remain_immutable(self):
        strategy=self.store.create('strategies',{'title':'趋势观察','entry_conditions':'条件明确',
            'exit_conditions':'逻辑失效','validation_scope':'前向观察'},'strategy')
        confirmed=self.store.transition('strategies',strategy['id'],1,'confirmed','confirm-strategy')
        edited=self.store.update('strategies',strategy['id'],2,{'title':'新版本'},'edit-strategy')
        self.assertEqual(edited['state'],'draft')
        self.assertEqual(self.store.history('strategies',strategy['id'])[1],confirmed)

    def test_campaign_partial_exit_close_and_next_cycle(self):
        self.fill('b1')
        self.fill('b2',price='12')
        self.fill('s1',side='sell',price='13',quantity='50')
        items=self.store.campaigns(self.account['id'])
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]['state'],'open')
        self.assertEqual(items[0]['quantity'],'150')
        self.fill('s2',side='sell',price='12',quantity='150')
        self.assertEqual(self.store.campaigns(self.account['id'])[0]['state'],'closed')
        self.fill('b3')
        self.assertEqual(len(self.store.campaigns(self.account['id'])),2)

    def test_unverified_trade_plan_cannot_become_executable(self):
        plan=self.store.create('trade-plans',{'account_id':self.account['id'],
            'instrument_id':self.instrument['id'],'title':'观察',
            'valid_until':'2026-12-01T15:00:00+08:00'},'plan')
        with self.assertRaises(Problem):
            self.store.transition('trade-plans',plan['id'],1,'confirmed','confirm-plan')

    def test_same_security_cannot_split_into_duplicate_positions(self):
        again=self.store.create('instruments',{'code':'510000.SH','name':'别名',
            'market':'SSE','kind':'etf'},'instrument-alias')
        self.assertEqual(again['id'],self.instrument['id'])
        self.assertEqual(self.store.listing('instruments')['total'],1)
