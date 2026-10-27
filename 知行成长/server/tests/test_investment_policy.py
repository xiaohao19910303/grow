"""Capital constraints affect proposals, never hide actual transaction facts."""
from copilot.core import Problem
from investments.planning import policy_status
from investments.store import InvestmentStore
from test_legacy_cloud_schema import PostgreSQLFixture


class InvestmentPolicyTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp();self.store=InvestmentStore();self.store.initialize()
        self.account=self.store.create('accounts',{'name':'账户','opening_cash':'10000','baseline_date':'2026-10-26'},'a')
        self.instrument=self.store.create('instruments',{'name':'股票','code':'600000','market':'SSE','kind':'stock'},'i')

    def policy(self,key='policy',**changes):
        return self.store.create('policies',{'account_id':self.account['id'],'period_start':'2026-10-01',
            'period_end':'2026-10-31','purpose':'交易资金','liquidity_needs':'保留生活资金','loss_capacity':'可承受100',
            'planned_deposit':'1000','planned_withdrawal':'500','cash_buffer':'2000','trade_risk_budget':'100',**changes},key)

    def test_policy_overlap_and_draft_edit_preserves_effective_version(self):
        p=self.policy();confirmed=self.store.transition('policies',p['id'],1,'confirmed','confirm')
        self.store.update('policies',p['id'],confirmed['version'],{'pause_new_risk':True},'edit')
        status=policy_status(self.store,self.account['id'],'2026-10-31')
        self.assertFalse(status['policy']['pause_new_risk'])
        self.assertEqual(status['policy']['version'],2)
        overlap=self.policy('overlap')
        with self.assertRaises(Problem):
            self.store.transition('policies',overlap['id'],1,'confirmed','confirm-overlap')

    def test_pause_flags_plan_but_fact_remains_recordable_and_flows_separate(self):
        p=self.policy(pause_new_risk=True);self.store.transition('policies',p['id'],1,'confirmed','confirm')
        self.store.create('cash-events',{'account_id':self.account['id'],'kind':'deposit','amount':'200',
            'occurred_at':'2026-10-28T10:00:00+08:00'},'deposit')
        plan=self.store.create('trade-plans',{'account_id':self.account['id'],'instrument_id':self.instrument['id'],
            'title':'条件计划','risk_budget':'150','valid_until':'2026-10-31T15:00:00+08:00'},'plan')
        status=policy_status(self.store,self.account['id'],'2026-10-31',plan['id'])
        self.assertIn('new_risk_paused',status['conflicts'])
        self.assertIn('risk_budget_exceeded',status['conflicts'])
        self.assertEqual(status['actual_deposit'],'200')
        self.assertEqual(status['deposit_gap'],'-800')
        self.store.create('fills',{'account_id':self.account['id'],'instrument_id':self.instrument['id'],
            'side':'buy','price':'10','quantity':'100','fee':'0','tax':'0','executed_at':'2026-10-28T11:00:00+08:00'},'actual')
        self.assertEqual(self.store.balance(self.account['id'])['cash'],'9200')

    def test_absent_policy_and_unknown_fee_do_not_invent_available_budget(self):
        result=policy_status(self.store,self.account['id'],'2026-10-31')
        self.assertIsNone(result['policy']);self.assertIsNone(result['available_after_buffer'])
