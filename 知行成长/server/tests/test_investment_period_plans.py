from unittest.mock import patch
from copilot.core import Problem
from investments.store import InvestmentStore
from test_legacy_cloud_schema import PostgreSQLFixture


class InvestmentPeriodPlanTests(PostgreSQLFixture):
    def test_week_and_holiday_skip_require_calendar_and_keep_reason(self):
        store=InvestmentStore();store.initialize()
        a=store.create('accounts',{'name':'账户','opening_cash':'10000','baseline_date':'2026-10-26'},'a')
        i=store.create('instruments',{'name':'ETF','code':'510000','market':'SSE','kind':'etf'},'i')
        context=store.create('plan-checks',{'instrument_id':i['id'],'quote_price':'1','quote_as_of':'2026-10-23T15:00:00+08:00',
            'sessions':'2026-10-26,开市\n2026-10-27,开市\n2026-10-28,开市\n2026-10-29,开市\n2026-10-30,开市\n2026-10-31,休市\n2026-11-01,休市',
            'rules_valid_from':'2026-10-26','rules_valid_until':'2026-11-01','price_tick':'0.001','quantity_step':'100',
            'minimum_quantity':'100','sell_delay_sessions':1,'trading_status':'unknown','source_url':'https://www.sse.com.cn/',
            'source_note':'手工日历夹具，非生产规则','acknowledged':True},'c')
        week=store.create('period-plans',{'account_id':a['id'],'period':'week','period_start':'2026-10-26',
            'period_end':'2026-11-01','title':'先观察','check_id':context['id'],'focus':'核对公告与原计划','no_trade':True},'w')
        with patch('investments.planning.now',return_value='2026-10-26T09:00:00+08:00'):
            confirmed=store.transition('period-plans',week['id'],1,'confirmed','wc')
        self.assertEqual(len(confirmed['session_dates']),5)
        skip=store.transition('period-plans',week['id'],2,'skipped','skip',reason='未出现条件，主动休息')
        self.assertEqual(skip['state_reason'],'未出现条件，主动休息')
        self.assertEqual(len(store.history('period-plans',week['id'])),3)
        day=store.create('period-plans',{'account_id':a['id'],'period':'day','period_start':'2026-10-31',
            'period_end':'2026-10-31','title':'休市复核','focus':'只核对','no_trade':False,'check_id':context['id']},'d')
        with patch('investments.planning.now',return_value='2026-10-26T09:00:00+08:00'),self.assertRaises(Problem):
            store.transition('period-plans',day['id'],1,'confirmed','dc')
