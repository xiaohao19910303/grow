"""Import preview, atomic corrections and delayed fund settlement."""
from copilot.core import Problem
from test_legacy_cloud_schema import PostgreSQLFixture
from investments.store import InvestmentStore
from investments.operations import preview_csv, commit_csv, correct_fill, confirm_fund, settle_fund


class InvestmentFlowTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp();self.store=InvestmentStore();self.store.initialize()
        self.account=self.store.create('accounts',{'name':'账户','opening_cash':'10000',
            'baseline_date':'2026-10-26'},'account')
        self.instrument=self.store.create('instruments',{'name':'ETF','code':'510000','market':'SSE','kind':'etf'},'instrument')

    def test_csv_preview_and_atomic_repeatable_commit(self):
        text='code,market,side,price,quantity,fee,tax,executed_at,external_id\n510000,SSE,buy,1.231,1000,1,0,2026-10-26T10:00:00+08:00,trade-1\n'
        preview=preview_csv(self.store,self.account['id'],text)
        self.assertEqual(preview['errors'],[])
        commit_csv(self.store,self.account['id'],text,preview['token'],'commit')
        commit_csv(self.store,self.account['id'],text,preview['token'],'commit-again')
        self.assertEqual(self.store.listing('fills')['total'],1)
        bad=text+'510000,SSE,sell,1.234,5000,0,0,2026-10-26T11:00:00+08:00,too-many\n'
        before=self.store.listing('fills')['total']
        with self.assertRaises(Problem):
            commit_csv(self.store,self.account['id'],bad,preview_csv(self.store,self.account['id'],bad)['token'],'bad-batch')
        self.assertEqual(self.store.listing('fills')['total'],before)

    def test_correction_keeps_original_and_rejects_stale_version(self):
        fill=self.store.create('fills',{'account_id':self.account['id'],'instrument_id':self.instrument['id'],
            'side':'buy','price':'10','quantity':'100','fee':'1','tax':'0',
            'executed_at':'2026-10-26T10:00:00+08:00'},'fill')
        corrected=correct_fill(self.store,fill['id'],1,{'price':'12'},'核对券商成交价格','correct')
        self.assertEqual(corrected['price'],'12')
        self.assertEqual(self.store.history('fills',fill['id'])[0]['price'],'10')
        self.assertEqual(self.store.balance(self.account['id'])['cash'],'8799')
        with self.assertRaises(Problem):
            correct_fill(self.store,fill['id'],1,{'price':'13'},'过时修改','stale')

    def test_fund_redemption_cash_waits_for_actual_receipt(self):
        fund=self.store.create('instruments',{'name':'基金','code':'000001','market':'FUND','kind':'fund'},'fund')
        order=self.store.create('fund-orders',{'account_id':self.account['id'],'instrument_id':fund['id'],
            'side':'subscription','amount':'1000','applied_at':'2026-10-26T10:00:00+08:00'},'sub')
        self.assertEqual(self.store.balance(self.account['id'])['cash'],'10000')
        confirm_fund(self.store,order['id'],1,{'price':'1.25','quantity':'800','fee':'0','tax':'0',
            'confirmed_at':'2026-10-27T10:00:00+08:00','nav_date':'2026-10-26'},'confirm-sub')
        self.assertEqual(self.store.balance(self.account['id'])['cash'],'9000')
        redemption=self.store.create('fund-orders',{'account_id':self.account['id'],'instrument_id':fund['id'],
            'side':'redemption','quantity':'100.5','applied_at':'2026-10-28T10:00:00+08:00'},'redeem')
        confirmed=confirm_fund(self.store,redemption['id'],1,{'price':'1.5','quantity':'100.5','fee':'0.5','tax':'0',
            'confirmed_at':'2026-10-29T10:00:00+08:00','nav_date':'2026-10-28'},'confirm-redeem')
        balance=self.store.balance(self.account['id'])
        self.assertEqual(balance['cash'],'9000')
        self.assertEqual(balance['receivables'],'150.25')
        with self.assertRaises(Problem):
            correct_fill(self.store,confirmed['fill_id'],1,{'price':'2'},'不可单独改确认成交','fund-correction')
        self.assertEqual(self.store.balance(self.account['id'])['receivables'],'150.25')
        settle_fund(self.store,redemption['id'],confirmed['version'],'2026-10-30T10:00:00+08:00','settle')
        self.assertEqual(self.store.balance(self.account['id'])['cash'],'9150.25')

    def test_fund_partial_confirmation_preserves_batches_and_actual_holding_fees(self):
        fund=self.store.create('instruments',{'name':'基金','code':'000002','market':'FUND','kind':'fund'},'fund2')
        order=self.store.create('fund-orders',{'account_id':self.account['id'],'instrument_id':fund['id'],
            'side':'subscription','amount':'1000','applied_at':'2026-10-26T10:00:00+08:00'},'sub2')
        first=confirm_fund(self.store,order['id'],1,{'price':'1','quantity':'400','fee':'1','tax':'0',
            'confirmed_at':'2026-10-27T10:00:00+08:00','nav_date':'2026-10-26','final_confirmation':False},'part1')
        self.assertEqual(first['state'],'partially_confirmed')
        second=confirm_fund(self.store,order['id'],2,{'price':'1.1','quantity':'500','fee':'2','tax':'0',
            'confirmed_at':'2026-10-28T10:00:00+08:00','nav_date':'2026-10-27'},'part2')
        self.assertEqual(len(second['confirmations']),2)
        self.assertEqual(self.store.balance(self.account['id'])['cash'],'9047')
        redeem=self.store.create('fund-orders',{'account_id':self.account['id'],'instrument_id':fund['id'],
            'side':'redemption','quantity':'200','applied_at':'2026-10-29T10:00:00+08:00'},'red2')
        part=confirm_fund(self.store,redeem['id'],1,{'price':'1.2','quantity':'100','fee':'1.5','tax':'0',
            'confirmed_at':'2026-10-30T10:00:00+08:00','nav_date':'2026-10-29','final_confirmation':False},'redpart1')
        final=confirm_fund(self.store,redeem['id'],part['version'],{'price':'1.3','quantity':'100','fee':'0.1','tax':'0',
            'confirmed_at':'2026-11-02T10:00:00+08:00','nav_date':'2026-10-30'},'redpart2')
        self.assertEqual(final['receivable'],'248.4')
        self.assertEqual(self.store.balance(self.account['id'])['cash'],'9047')
        settle_fund(self.store,redeem['id'],final['version'],'2026-11-03T10:00:00+08:00','settled2')
        self.assertEqual(self.store.balance(self.account['id'])['cash'],'9295.4')
