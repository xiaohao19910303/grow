"""User-verified context enables conditional planning without paid quotes."""
from unittest.mock import patch
from decimal import Decimal,localcontext
from copilot.core import Problem
from investments.store import InvestmentStore
from investments.plan_checks import assess_plan
from test_legacy_cloud_schema import PostgreSQLFixture


class InvestmentPlanCheckTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp();self.store=InvestmentStore();self.store.initialize()
        self.a=self.store.create('accounts',{'name':'交易','opening_cash':'10000','baseline_date':'2026-10-26'},'a')
        self.i=self.store.create('instruments',{'name':'证券','code':'600000','market':'SSE','kind':'stock'},'i')
        policy=self.store.create('policies',{'account_id':self.a['id'],'period_start':'2026-10-01','period_end':'2026-10-31',
            'purpose':'交易','liquidity_needs':'留备用金','loss_capacity':'300','cash_buffer':'2000','trade_risk_budget':'300'},'p')
        self.clock=patch('investments.planning.now',return_value='2026-10-28T09:00:00+08:00');self.clock.start();self.addCleanup(self.clock.stop)
        self.store.transition('policies',policy['id'],1,'confirmed','pc')
        strategy=self.store.create('strategies',{'title':'条件观察','entry_conditions':'达到价格','exit_conditions':'逻辑失效','validation_scope':'前向观察'},'s')
        self.strategy=self.store.transition('strategies',strategy['id'],1,'confirmed','sc')

    def context(self,**changes):
        return self.store.create('plan-checks',{'instrument_id':self.i['id'],'quote_price':'10','quote_as_of':'2026-10-27T15:00:00+08:00',
            'sessions':{'2026-10-27':True,'2026-10-28':True,'2026-10-29':True,'2026-10-30':True,'2026-10-31':False,'2026-11-01':False,'2026-11-02':True},
            'rules_valid_from':'2026-10-27','rules_valid_until':'2026-11-02','price_tick':'0.01','quantity_step':'100','minimum_quantity':'100',
            'sell_delay_sessions':1,'trading_status':'normal','source_url':'https://www.sse.com.cn/',
            'source_note':'本人核对券商与交易所资料，测试夹具不代表生产规则','acknowledged':True,**changes},'context'+str(len(changes)))

    def plan(self,context,**changes):
        return self.store.create('trade-plans',{'account_id':self.a['id'],'instrument_id':self.i['id'],
            'strategy_id':self.strategy['id'],'title':'下一次开市条件计划','rationale':'只在条件满足时参与',
            'entry_conditions':'达到计划价格','invalidation':'低于9或出现反证','risk_budget':'250','entry_price':'10',
            'invalidation_price':'9','fee_budget':'2','holding_sessions':3,'planned_for':'2026-10-28',
            'check_id':context['id'],'valid_until':'2026-10-28T15:00:00+08:00',**changes},'plan'+str(len(changes)))

    def test_exact_size_calendar_freeze_and_retrospective_not_reclassified(self):
        context=self.context();plan=self.plan(context)
        result=assess_plan(self.store,plan['id'],'2026-10-28T09:00:00+08:00')
        self.assertEqual(result['quantity'],'200');self.assertEqual(result['planned_loss'],'202')
        self.assertEqual(result['review_on'],'2026-10-30');self.assertFalse(result['realtime'])
        confirmed=self.store.transition('trade-plans',plan['id'],1,'confirmed','confirm')
        self.assertEqual(confirmed['strategy_snapshot']['version'],2)
        fill=self.store.create('fills',{'account_id':self.a['id'],'instrument_id':self.i['id'],'plan_id':plan['id'],
            'side':'buy','price':'10','quantity':'100','fee':'1','tax':'0','executed_at':'2026-10-28T10:00:00+08:00'},'f')
        self.assertTrue(fill['plan_recorded_before_execution']);self.assertEqual(fill['strategy_snapshot']['version'],2)
        self.store.update('trade-plans',plan['id'],2,{'invalidation_price':'8'},'widen')
        self.assertEqual(self.store.get('fills',fill['id'])['plan_snapshot']['invalidation_price'],'9')
        late=self.store.create('fills',{'account_id':self.a['id'],'instrument_id':self.i['id'],'plan_id':plan['id'],
            'side':'buy','price':'10','quantity':'100','fee':'1','tax':'0','executed_at':'2026-10-29T10:00:00+08:00'},'late-entry')
        self.assertEqual(late['plan_snapshot']['version'],2)
        self.assertTrue(late['plan_recorded_before_execution']);self.assertFalse(late['plan_valid_at_execution'])
        early=self.store.create('fills',{'account_id':self.a['id'],'instrument_id':self.i['id'],'plan_id':plan['id'],
            'side':'buy','price':'10','quantity':'100','fee':'1','tax':'0','executed_at':'2026-10-28T08:00:00+08:00'},'retrospective')
        self.assertFalse(early['plan_recorded_before_execution'])

    def test_closed_session_missing_calendar_stale_quote_and_tick_are_blocked(self):
        context=self.context();plan=self.plan(context,planned_for='2026-10-31',valid_until='2026-10-31T15:00:00+08:00')
        with self.assertRaises(Problem):assess_plan(self.store,plan['id'],'2026-10-28T09:00:00+08:00')
        changed=self.store.update('trade-plans',plan['id'],1,{'planned_for':'2026-10-28','entry_price':'10.005'},'tick')
        with self.assertRaises(Problem):assess_plan(self.store,changed['id'],'2026-10-28T09:00:00+08:00')
        stale=self.context(quote_as_of='2026-10-26T15:00:00+08:00')
        p=self.plan(stale,planned_for='2026-10-29')
        with self.assertRaises(Problem):assess_plan(self.store,p['id'],'2026-10-28T09:00:00+08:00')

    def test_partial_entry_r_uses_frozen_actual_entry_risk_not_entire_budget(self):
        context=self.context();plan=self.plan(context)
        self.store.transition('trade-plans',plan['id'],1,'confirmed','confirm')
        buy=self.store.create('fills',{'account_id':self.a['id'],'instrument_id':self.i['id'],'plan_id':plan['id'],
            'side':'buy','price':'10','quantity':'100','fee':'1','tax':'0','executed_at':'2026-10-28T10:00:00+08:00'},'buy')
        self.store.update('trade-plans',plan['id'],2,{'invalidation_price':'8'},'widen')
        self.store.create('fills',{'account_id':self.a['id'],'instrument_id':self.i['id'],'side':'sell',
            'price':'11','quantity':'100','fee':'1','tax':'0','executed_at':'2026-10-28T11:00:00+08:00'},'sell')
        cycle=self.store.campaigns(self.a['id'])[0]
        self.assertEqual(cycle['risk_basis'],'102')
        with localcontext() as ctx:
            ctx.prec=60
            self.assertLess(abs(Decimal(cycle['realized_r'])-Decimal(98)/102),Decimal('1e-50'))
        self.assertEqual(self.store.get('fills',buy['id'])['initial_risk_snapshot']['invalidation_price'],'9')

    def test_entry_before_planned_session_has_no_verified_initial_risk(self):
        context=self.context();plan=self.plan(context,planned_for='2026-10-29',valid_until='2026-10-29T15:00:00+08:00')
        self.store.transition('trade-plans',plan['id'],1,'confirmed','confirm')
        actual=self.store.create('fills',{'account_id':self.a['id'],'instrument_id':self.i['id'],'plan_id':plan['id'],
            'side':'buy','price':'10','quantity':'100','fee':'1','tax':'0','executed_at':'2026-10-28T10:00:00+08:00'},'early')
        self.assertFalse(actual['plan_valid_at_execution']);self.assertIsNone(actual['initial_risk_snapshot'])

    def test_exit_draft_never_gets_buy_sizing(self):
        context=self.context();plan=self.plan(context,intent='exit')
        with self.assertRaises(Problem) as caught:
            assess_plan(self.store,plan['id'],'2026-10-28T09:00:00+08:00')
        self.assertEqual(caught.exception.code,'research_only_plan')

    def test_automatic_reference_mismatch_blocks_confirmation_without_rejecting_facts(self):
        context=self.context(sell_delay_sessions=0)
        plan=self.plan(context)
        with self.assertRaises(Problem) as caught:
            self.store.transition('trade-plans',plan['id'],1,'confirmed','bad-reference')
        self.assertEqual(caught.exception.code,'rule_reference_mismatch')
        fill=self.store.create('fills',{'account_id':self.a['id'],'instrument_id':self.i['id'],'side':'buy',
            'price':'10','quantity':'5','fee':'1','tax':'0','executed_at':'2026-10-28T10:00:00+08:00'},'actual-odd')
        self.assertEqual(fill['quantity'],'5')

    def test_automatic_reference_freezes_hash_and_respects_maintenance_expiry(self):
        from investments.rules import RULEBOOK_ID
        context=self.context(rulebook_id=RULEBOOK_ID)
        plan=self.plan(context)
        confirmed=self.store.transition('trade-plans',plan['id'],1,'confirmed','auto-reference')
        reference=confirmed['assessment_snapshot']['rule_comparison']
        self.assertEqual(reference['status'],'matched_reference_subset')
        self.assertEqual(len(reference['rules']['snapshot_hash']),64)
        with self.assertRaises(Problem) as caught:
            assess_plan(self.store,plan['id'],'2026-12-01T09:00:00+08:00')
        self.assertEqual(caught.exception.code,'rule_reference_unavailable')

    def test_star_single_share_increment_and_limit_order_cap(self):
        a=self.store.create('accounts',{'name':'大额合成账户','opening_cash':'5000000','baseline_date':'2026-10-26'},'large')
        policy=self.store.create('policies',{'account_id':a['id'],'period_start':'2026-10-01','period_end':'2026-10-31',
            'purpose':'程序边界验收','liquidity_needs':'合成','loss_capacity':'250000','cash_buffer':'0','trade_risk_budget':'250000'},'large-policy')
        self.store.transition('policies',policy['id'],1,'confirmed','large-confirm')
        self.i=self.store.create('instruments',{'name':'合成科创板','code':'688001','market':'SSE','kind':'stock'},'star')
        context=self.context(quote_price='1',minimum_quantity='200',quantity_step='1')
        plan=self.plan(context,account_id=a['id'],entry_price='1',invalidation_price='0.99',risk_budget='250000')
        self.assertEqual(assess_plan(self.store,plan['id'],'2026-10-28T09:00:00+08:00')['quantity'],'100000')
        second=self.plan(context,account_id=a['id'],entry_price='1',invalidation_price='0.99',risk_budget='4.01',title='201股取整')
        self.assertEqual(assess_plan(self.store,second['id'],'2026-10-28T09:00:00+08:00')['quantity'],'201')
