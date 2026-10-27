"""Period results separate cash flows, open risk and subjective process judgments."""
from copilot.core import Problem
from investments.store import InvestmentStore
from investments.reviews import period_summary, campaign_detail
from test_legacy_cloud_schema import PostgreSQLFixture


class InvestmentReviewMetricTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp();self.store=InvestmentStore();self.store.initialize()
        self.a=self.store.create('accounts',{'name':'账户','opening_cash':'10000','baseline_date':'2026-10-26'},'a')
        self.i=self.store.create('instruments',{'name':'ETF','code':'510000','market':'SSE','kind':'etf'},'i')

    def fill(self,key,side,price,quantity,day,fee='1'):
        return self.store.create('fills',{'account_id':self.a['id'],'instrument_id':self.i['id'],'side':side,
            'price':price,'quantity':quantity,'fee':fee,'tax':'0','executed_at':day+'T10:00:00+08:00'},key)

    def test_period_cross_week_partial_position_and_cashflows_not_profit(self):
        self.fill('b','buy','10','100','2026-10-26')
        self.fill('s','sell','12','50','2026-11-02')
        self.store.create('cash-events',{'account_id':self.a['id'],'kind':'deposit','amount':'1000',
            'occurred_at':'2026-11-02T09:00:00+08:00'},'d')
        result=period_summary(self.store,self.a['id'],'2026-11-02','2026-11-02')
        self.assertEqual(result['net_realized'],'98.5')
        self.assertEqual(result['deposit'],'1000')
        self.assertEqual(result['open_count'],1);self.assertEqual(result['closed_count'],0)
        self.assertIsNone(result['win_rate']);self.assertIsNone(result['drawdown'])
        self.assertEqual(result['positions_at_end'][0]['quantity'],'50')
        earlier=period_summary(self.store,self.a['id'],'2026-10-26','2026-10-30')
        self.assertEqual(earlier['net_realized'],'0')
        self.assertEqual(earlier['positions_at_end'][0]['quantity'],'100')

    def test_positive_profit_does_not_imply_adherence_and_unknown_fee_is_not_zero(self):
        self.fill('b','buy','10','100','2026-10-26');self.fill('s','sell','12','100','2026-10-28')
        campaign=self.store.campaigns(self.a['id'])[0]
        self.store.create('reviews',{'account_id':self.a['id'],'campaign_id':campaign['id'],'date':'2026-10-28',
            'text':'盈利但违反入场条件','adherence':'deviated','thesis':'unknown'},'review')
        detail=campaign_detail(self.store,self.a['id'],campaign['id'])
        self.assertEqual(detail['campaign']['net_realized'],'198')
        self.assertEqual(detail['reviews'][0]['adherence'],'deviated')
        self.assertEqual(detail['fills'][0]['plan_status'],'absent')
        self.fill('b2','buy','10','1','2026-10-29',fee=None)
        result=period_summary(self.store,self.a['id'],'2026-10-26','2026-10-31')
        self.assertIsNone(result['net_realized']);self.assertFalse(result['fees_complete'])

    def test_empty_sample_and_before_baseline(self):
        result=period_summary(self.store,self.a['id'],'2026-10-26','2026-10-31')
        self.assertIsNone(result['win_rate']);self.assertEqual(result['closed_count'],0)
        with self.assertRaises(Problem):period_summary(self.store,self.a['id'],'2026-10-01','2026-10-31')
