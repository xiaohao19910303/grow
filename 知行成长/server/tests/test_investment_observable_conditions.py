"""Observable conditions and compatibility of historical report/plan records."""
import json
import unittest

import db
from pydantic import ValidationError
from copilot.core import Problem
from investments.analysis import validate_report
from investments.observable_conditions import validate_condition_text
from investments.contracts import PlanInput
from investments.store import InvestmentStore
from test_legacy_cloud_schema import PostgreSQLFixture


class ObservableConditionTests(unittest.TestCase):
    def test_unobservable_information_intent_and_guarantees_are_rejected(self):
        for text in ['确认无未公开重大事项','核实不存在尚未对外披露的重大风险','掌握内幕消息后参与',
                     '排除非公开风险','确认主力真实意图','确认机构的真实动机','保证盈利后入场',
                     '保证未来盈利','确认不存在任何风险','排除全部潜在风险','no undisclosed material events',
                     'verify non-public information','确认无未\u200b公 开重大事项']:
            with self.subTest(text=text),self.assertRaises(ValueError):validate_condition_text(text)

    def test_public_evidence_unknown_and_bounded_checks_remain_valid(self):
        for text in ['核对截至复核日已公开的公司公告；尚未核对则继续观察',
                     '核对所列公告是否提示重大风险；未发现不代表不存在风险',
                     '取得同口径最新日线后重新计算均线，数据不足则不采用',
                     '核对本人券商记录的实际可卖数量，记录缺失则等待',
                     '公开披露的机构持仓仅作参考，不能保证盈利',
                     '截至复核日最新净值尚未披露则等待；公告材料缺失则停止采用',
                     'check published disclosures at the review date; missing data means wait']:
            with self.subTest(text=text):self.assertEqual(validate_condition_text(text),text)

    def test_final_report_rejects_bad_conditions_but_preserves_critical_discussion(self):
        snapshot={'kind':'research','evidence':[],'plans':[],'decision_at':'2026-10-28T09:00:00+08:00'}
        report={'summary':'只讨论可核对的公开资料','counterarguments':['不能确认无未公开重大事项，不能用其作条件'],
            'suggestions':[{'title':'研究条件','action':'conditional_entry','reason':'公开资料核对',
                'trigger':'确认无未公开重大事项','invalidation':'已公开公告出现风险提示时停止',
                'valid_until':'2026-11-01T15:00:00+08:00'}]}
        draft=validate_report(json.dumps(report),snapshot,check_conditions=False)
        self.assertIn('未公开',draft['suggestions'][0]['trigger'])
        with self.assertRaises(ValueError):validate_report(json.dumps(report),snapshot)
        report['suggestions'][0]['trigger']='核对截至复核日已公开的公告；资料不足则等待'
        fixed=validate_report(json.dumps(report),snapshot)
        self.assertEqual(fixed['counterarguments'],report['counterarguments'])


class ObservablePlanTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp();self.store=InvestmentStore();self.store.initialize()
        self.account=self.store.create('accounts',{'name':'条件核对','opening_cash':'0','baseline_date':'2026-10-28'},'a')
        self.instrument=self.store.create('instruments',{'name':'股票','code':'600000','market':'SSE','kind':'stock'},'i')
        self.payload={'account_id':self.account['id'],'instrument_id':self.instrument['id'],'title':'条件研究',
            'entry_conditions':'核对截至复核日已公开公告，资料缺失则等待','invalidation':'出现公开风险提示时停止',
            'valid_until':'2030-01-01T15:00:00+08:00'}

    def test_create_and_edit_reject_unverifiable_conditions_without_mutating_versions(self):
        with self.assertRaises(ValidationError):PlanInput(**{**self.payload,'entry_conditions':'确认无未公开重大事项'})
        plan=self.store.create('trade-plans',self.payload,'p')
        with self.assertRaises(Problem):self.store.update('trade-plans',plan['id'],1,{'invalidation':'确认主力真实意图'},'bad-edit')
        self.assertEqual(self.store.get('trade-plans',plan['id']),plan)
        self.assertEqual(len(self.store.history('trade-plans',plan['id'])),1)

    def test_legacy_draft_cannot_confirm_but_can_be_read_corrected_or_declined(self):
        plan=self.store.create('trade-plans',self.payload,'legacy')
        legacy={**plan,'version':2,'entry_conditions':'确认无未公开重大事项'}
        with db.connect() as c:self.store.save(c,'trade-plans',legacy)
        with self.assertRaises(Problem) as caught:self.store.transition('trade-plans',plan['id'],2,'confirmed','confirm')
        self.assertEqual(caught.exception.code,'unverifiable_conditions')
        self.assertEqual(self.store.get('trade-plans',plan['id'])['state'],'draft')
        fixed=self.store.update('trade-plans',plan['id'],2,{'entry_conditions':self.payload['entry_conditions']},'fix')
        self.assertEqual(fixed['version'],3)
        self.assertEqual(self.store.history('trade-plans',plan['id'])[1]['entry_conditions'],'确认无未公开重大事项')
        declined=self.store.transition('trade-plans',plan['id'],3,'declined','decline')
        self.assertEqual(declined['state'],'declined')
