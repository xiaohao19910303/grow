"""Prospective registration must retain losing cases and immutable protocols."""
from unittest.mock import patch
from copilot.core import Problem
from investments.store import InvestmentStore
from investments.experiments import create_experiment,register_experiment,evaluate_experiment,finish_experiment,update_experiment
from test_legacy_cloud_schema import PostgreSQLFixture

class InvestmentExperimentTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp();self.clock='2026-10-26T09:00:00+08:00'
        for target in ('investments.experiments.now','investments.store.now','investments.planning.now'):
            p=patch(target,side_effect=lambda:self.clock);p.start();self.addCleanup(p.stop)
        self.s=InvestmentStore();self.s.initialize()
        self.a=self.s.create('accounts',{'name':'试验','baseline_date':'2026-10-26','opening_cash':'10000'},'a')
        self.i=self.s.create('instruments',{'market':'SSE','code':'600000','kind':'stock','name':'合成股票'},'i')
        strategy=self.s.create('strategies',{'title':'待验证方法','entry_conditions':'明确条件','exit_conditions':'出现反证','validation_scope':'有限样本'},'s')
        self.strategy=self.s.transition('strategies',strategy['id'],1,'confirmed','sc')
        policy=self.s.create('policies',{'account_id':self.a['id'],'period_start':'2026-10-01','period_end':'2026-10-31',
            'purpose':'试验','liquidity_needs':'合成','loss_capacity':'200','cash_buffer':'0','trade_risk_budget':'200'},'policy')
        self.s.transition('policies',policy['id'],1,'confirmed','policy-confirm')
        self.check=self.s.create('plan-checks',{'instrument_id':self.i['id'],'quote_price':'10','quote_as_of':'2026-10-23T15:00:00+08:00',
            'sessions':{'2026-10-23':True,'2026-10-24':False,'2026-10-25':False,'2026-10-26':True,'2026-10-27':True,'2026-10-28':True},
            'rules_valid_from':'2026-10-23','rules_valid_until':'2026-10-28','price_tick':'0.01','minimum_quantity':'100','quantity_step':'100',
            'sell_delay_sessions':1,'trading_status':'normal','source_url':'https://www.sse.com.cn/','source_note':'合成验收资料','acknowledged':True},'check')

    def draft(self,key='draft',**changes):
        return create_experiment(self.s,{'account_id':self.a['id'],'strategy_id':self.strategy['id'],'strategy_version':2,
            'title':'前向登记','hypothesis':'先记录再评价','counter_case':'费用可能抵消优势','stop_condition':'发生资料缺失先核对',
            'parameters':{'holding_sessions':'2','threshold':'本人条件'},'cost_assumptions':'本人核对实际费用，不省略亏损样例',
            'start_at':'2026-10-26T10:00:00+08:00','end_at':'2026-10-28T15:00:00+08:00',
            'sample_target':10,'additional_roundtrip_costs':['0','1','5'],**changes},key)

    def campaign(self,price,at,key):
        # The plan existed before registration starts but expired before either actual entry.
        previous=self.clock;self.clock='2026-10-26T09:00:00+08:00'
        try:
            plan=self.s.create('trade-plans',{'account_id':self.a['id'],'instrument_id':self.i['id'],'strategy_id':self.strategy['id'],
                'title':'实际观察','rationale':'合成','entry_conditions':'条件','invalidation':'反证','risk_budget':'102','holding_sessions':1,
                'entry_price':'10','invalidation_price':'9','fee_budget':'2','planned_for':'2026-10-26','check_id':self.check['id'],
                'valid_until':'2026-10-26T09:30:00+08:00'},'p'+key)
            self.s.transition('trade-plans',plan['id'],1,'confirmed','confirm'+key)
        finally:self.clock=previous
        self.s.create('fills',{'account_id':self.a['id'],'instrument_id':self.i['id'],'plan_id':plan['id'],'side':'buy',
            'price':'10','quantity':'100','fee':'1','tax':'0','executed_at':at+'T10:00:00+08:00'},'b'+key)
        self.s.create('fills',{'account_id':self.a['id'],'instrument_id':self.i['id'],'side':'sell','price':price,
            'quantity':'100','fee':'1','tax':'0','executed_at':at+'T11:00:00+08:00'},'x'+key)

    def test_registration_freezes_parameters_and_cannot_be_backdated_or_edited(self):
        draft=self.draft();registered=register_experiment(self.s,draft['id'],1,'register')
        self.assertEqual(registered['protocol_snapshot']['parameters']['holding_sessions'],'2')
        with self.assertRaises(Problem):update_experiment(self.s,draft['id'],2,{'parameters':{'holding_sessions':'5'}},'edit')
        self.clock='2026-10-26T12:00:00+08:00'
        late=self.draft('late')
        with self.assertRaises(Problem):register_experiment(self.s,late['id'],1,'late-register')
        self.assertEqual(self.s.get('experiments',draft['id'])['protocol_hash'],registered['protocol_hash'])

    def test_all_matching_wins_losses_and_cost_stress_are_included(self):
        registered=register_experiment(self.s,self.draft()['id'],1,'register')
        self.clock='2026-10-28T16:00:00+08:00'
        self.campaign('11','2026-10-26','win');self.campaign('9','2026-10-27','loss')
        result=evaluate_experiment(self.s,registered['id'])
        self.assertEqual(result['closed_count'],2);self.assertEqual(result['known_net_count'],2)
        self.assertEqual(result['net_realized'],'-4');self.assertEqual(result['win_rate'],'0.5')
        self.assertEqual([x['net_after_extra_cost'] for x in result['cost_sensitivity']],['-4','-6','-14'])
        self.assertEqual(result['pre_recorded_plan_count'],0)  # Expired plans do not prove adherence.
        self.assertFalse(result['edge_proven']);self.assertTrue(result['small_sample'])
        decision=finish_experiment(self.s,registered['id'],2,'reject','成本后不支持原假设',result['evaluation_hash'],'finish')
        self.assertEqual(decision['decision'],'reject')
        self.assertEqual(decision['evaluation_snapshot']['net_realized'],'-4')
        self.assertEqual(finish_experiment(self.s,registered['id'],2,'reject','成本后不支持原假设',result['evaluation_hash'],'finish')['id'],registered['id'])

    def test_strategy_versions_and_changed_ledger_are_not_rewritten_into_old_decisions(self):
        registered=register_experiment(self.s,self.draft()['id'],1,'register')
        self.clock='2026-10-28T16:00:00+08:00';self.campaign('11','2026-10-26','one')
        evaluated=evaluate_experiment(self.s,registered['id'])
        self.campaign('9','2026-10-27','two')
        with self.assertRaises(Problem):finish_experiment(self.s,registered['id'],2,'retain','先复核',evaluated['evaluation_hash'],'stale')
        current=evaluate_experiment(self.s,registered['id'])
        saved=finish_experiment(self.s,registered['id'],2,'inconclusive','证据不足',current['evaluation_hash'],'save')
        self.s.update('strategies',self.strategy['id'],2,{'entry_conditions':'新条件'},'new-strategy')
        # Late accounting corrections change live evidence, never the archived evaluation.
        fill=self.s.listing('fills',account_id=self.a['id'])['items'][0]
        from investments.operations import correct_fill
        correct_fill(self.s,fill['id'],1,{'fee':'2'},'核对费用','correct')
        updated=evaluate_experiment(self.s,registered['id'])
        self.assertTrue(updated['archived_evaluation_outdated'])
        self.assertEqual(self.s.get('experiments',registered['id'])['evaluation_snapshot'],saved['evaluation_snapshot'])
        self.assertEqual(registered['protocol_snapshot']['strategy_snapshot']['entry_conditions'],'明确条件')
