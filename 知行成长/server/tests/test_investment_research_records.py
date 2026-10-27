from copilot.core import Problem
from investments.store import InvestmentStore
from test_legacy_cloud_schema import PostgreSQLFixture


class InvestmentResearchRecordTests(PostgreSQLFixture):
    def test_watchlist_dossier_and_principle_keep_versions_and_check_source_scope(self):
        store=InvestmentStore();store.initialize()
        a=store.create('accounts',{'name':'A','opening_cash':'0','baseline_date':'2026-10-26'},'a')
        b=store.create('accounts',{'name':'B','opening_cash':'0','baseline_date':'2026-10-26'},'b')
        i=store.create('instruments',{'name':'ETF','code':'510000','market':'SSE','kind':'etf'},'i')
        evidence=store.create('research',{'account_id':a['id'],'instrument_id':i['id'],'title':'基金资料','content':'原文摘录',
            'available_at':'2026-10-26T10:00:00+08:00'},'e')
        self.assertEqual(len(evidence['evidence_hash']),64)
        watch=store.create('watchlist',{'account_id':a['id'],'instrument_id':i['id'],'stage':'observing','reason':'等待资料'},'w')
        watch=store.update('watchlist',watch['id'],1,{'stage':'archived'},'archive')
        self.assertEqual(store.history('watchlist',watch['id'])[0]['stage'],'observing')
        dossier=store.create('dossiers',{'account_id':a['id'],'instrument_id':i['id'],'title':'ETF波段研究',
            'horizon':'swing','liquidity':'成交额仍需核对','nav_context':'最新净值有时差','evidence_ids':[evidence['id']]},'d')
        self.assertEqual(dossier['source_snapshots'][0]['evidence_hash'],evidence['evidence_hash'])
        with self.assertRaises(Problem):
            store.create('dossiers',{'account_id':b['id'],'instrument_id':i['id'],'title':'越范围',
                'evidence_ids':[evidence['id']]},'bad')
        review=store.create('reviews',{'account_id':a['id'],'date':'2026-10-26','text':'一次亏损，未能证明规则'},'r')
        principle=store.create('principles',{'account_id':a['id'],'title':'先作前向试验','rule':'只在条件明确后参与',
            'source_review_ids':[review['id']],'supporting_case':'这笔偏离了计划'},'p')
        with self.assertRaises(Problem):store.transition('principles',principle['id'],1,'confirmed','bad-trial')
        edited=store.update('principles',principle['id'],1,{'contrary_case':'可能错过有效入场','validation_scope':'下10次观察，不推定胜率'},'edit')
        trial=store.transition('principles',principle['id'],edited['version'],'confirmed','trial')
        self.assertEqual(trial['source_snapshots'][0]['text'],'一次亏损，未能证明规则')
        self.assertEqual(store.listing('strategies')['total'],0)
