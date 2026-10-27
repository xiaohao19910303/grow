"""Selected evidence, two-pass AI, idempotency and no persisted model credentials."""
import asyncio
import json
from unittest.mock import patch

import db
from copilot.core import Problem
from investments.store import InvestmentStore
from investments.analysis import InvestmentAnalysis, validate_report
from investments.operations import correct_fill
from copilot.core import now
from test_legacy_cloud_schema import PostgreSQLFixture

CONFIG={'api_base_url':'https://model.example/v1','api_key':'INVESTMENT_PRIVATE_TEST_KEY','model_name':'test-model'}


class InvestmentAnalysisTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        for target in ('investments.analysis.now','investments.store.now','investments.planning.now','investments.operations.now'):
            clock=patch(target,return_value='2026-10-26T12:00:00+08:00');clock.start();self.addCleanup(clock.stop)
        self.store=InvestmentStore();self.store.initialize()
        self.evidence=self.store.create('research',{'title':'公告摘录','content':'营业收入10亿元，费用仍待核对。',
            'available_at':'2026-10-25T10:00:00+08:00'},'evidence')
        self.calls=[]
        async def model(messages,cfg):
            self.calls.append(messages)
            report={'summary':'资料不足，先核对风险。','facts':[{'evidence_id':self.evidence['id'],
                'quote':'营业收入10亿元'}], 'inferences':['历史收入不能直接推导短期上涨。'],
                'counterarguments':['缺少现金流和当前行情。'],'missing_inputs':['当前行情、费用和交易规则'],
                'suggestions':[{'title':'继续研究','action':'research','reason':'资料尚不完整',
                    'trigger':'取得新公告后复核','invalidation':'原始资料更正','valid_until':'2026-11-01T15:00:00+08:00',
                    'evidence_ids':[self.evidence['id']]}]}
            yield {'text':json.dumps(report,ensure_ascii=False)}
            yield {'done':True}
        self.service=InvestmentAnalysis(self.store,model)

    def preview(self):
        return self.service.preview({'kind':'research','question':'检查这段资料与反证',
            'evidence_ids':[self.evidence['id']],'decision_at':'2026-10-26T15:00:00+08:00'})

    def test_exact_preview_and_future_information_rejected(self):
        preview=self.preview()
        self.assertEqual(len(preview['snapshot']['evidence']),1)
        self.assertNotIn('opening_cash',json.dumps(preview))
        with self.assertRaises(Problem):
            self.service.preview({'kind':'research','question':'只看当时资料',
                'evidence_ids':[self.evidence['id']],'decision_at':'2026-10-24T15:00:00+08:00'})

    def test_capital_context_hides_amounts_and_bounds_scenarios(self):
        account=self.store.create('accounts',{'name':'自用','opening_cash':'10000','baseline_date':'2026-10-26'},'capital-a')
        policy=self.store.create('policies',{'account_id':account['id'],'period_start':'2026-01-01','period_end':'2030-12-31',
            'purpose':'交易','liquidity_needs':'保留备用金','loss_capacity':'可承受有限损失','cash_buffer':'8000'},'capital-p')
        policy=self.store.transition('policies',policy['id'],1,'confirmed','capital-confirm')
        request={'kind':'capital','question':'比较保留现金与分阶段计划','account_id':account['id'],
            'policy_ids':[policy['id']],'decision_at':now()}
        hidden=self.service.preview(request)['snapshot']
        self.assertNotIn('cash_buffer',json.dumps(hidden));self.assertNotIn('balance',hidden)
        full=self.service.preview({**request,'include_amounts':True})['snapshot']
        scenario={'name':'先保留备用金','mode':'personal_draft','assumptions':['用途与需求仍不变'],
            'constraints':['不得突破现金缓冲'],'allocation':{'研究资金':'2000'},'next_step':'由本人核对','missing_inputs':[]}
        report={'summary':'比较情景，非自动配置','counterarguments':['缺少完整资产与负债资料'],'scenarios':[scenario,{**scenario,'name':'继续观察','allocation':{}}]}
        self.assertEqual(len(validate_report(json.dumps(report),full)['scenarios']),2)
        with self.assertRaises(ValueError):validate_report(json.dumps(report),hidden)
        report['scenarios'][0]['allocation']['研究资金']='3000'
        with self.assertRaises(ValueError):validate_report(json.dumps(report),full)
        report['scenarios'][0]['allocation']['研究资金']='2000'
        async def capital_model(messages,cfg):
            yield {'text':json.dumps(report,ensure_ascii=False)}
            yield {'done':True}
        self.service.transport=capital_model
        preview=self.service.preview({**request,'include_amounts':True})
        async def run():
            job=await self.service.submit(preview['id'],preview['snapshot_hash'],CONFIG,'capital-analysis')
            await self.service.tasks[job['id']]
            return job
        job=asyncio.run(run())
        adopted=self.service.capital_draft(job['id'],0,'capital-adopt')
        again=self.service.capital_draft(job['id'],0,'capital-adopt-again')
        self.assertEqual(adopted,again)
        draft=self.store.get('policies',policy['id'])
        self.assertEqual(draft['state'],'draft');self.assertEqual(draft['cash_buffer'],'8000')
        self.assertEqual(self.service.get(job['id'])['current_input_status'],'outdated')

    def test_past_balance_uses_known_versions_not_later_corrections_or_fills(self):
        with patch('investments.store.now',return_value='2026-10-26T12:00:00+08:00'):
            a=self.store.create('accounts',{'name':'历史核对','opening_cash':'10000','baseline_date':'2026-10-26'},'history-a')
            i=self.store.create('instruments',{'name':'ETF','code':'510000','market':'SSE','kind':'etf'},'history-i')
            fill=self.store.create('fills',{'account_id':a['id'],'instrument_id':i['id'],'side':'buy','price':'10','quantity':'100',
                'fee':'0','tax':'0','executed_at':'2026-10-26T10:00:00+08:00'},'history-fill')
        with patch('investments.operations.now',return_value='2026-10-28T12:00:00+08:00'):
            correct_fill(self.store,fill['id'],1,{'price':'12'},'后续核对','history-correction')
        with patch('investments.store.now',return_value='2026-10-28T12:00:00+08:00'):
            self.store.create('fills',{'account_id':a['id'],'instrument_id':i['id'],'side':'sell','price':'13','quantity':'50',
                'fee':'0','tax':'0','executed_at':'2026-10-27T10:00:00+08:00'},'later-entered')
        snapshot=self.service.preview({'kind':'research','account_id':a['id'],'question':'只看当时可知记录',
            'decision_at':'2026-10-27T15:00:00+08:00','include_amounts':True})['snapshot']
        self.assertEqual(snapshot['balance']['cash'],'9000')
        self.assertEqual(snapshot['balance']['positions'][0]['quantity'],'100')

    def test_calculation_citations_must_match_frozen_values_and_hash(self):
        snapshot=self.preview()['snapshot']
        snapshot['plans']=[{'id':'plan-test','calculation':{'quantity':'200','calculation_hash':'a'*64}}]
        report={'summary':'程序值核对','counterarguments':['数量不是成交承诺'],'calculations':[{'plan_id':'plan-test','calculation_hash':'a'*64,'field':'quantity','value':'200'}]}
        self.assertEqual(validate_report(json.dumps(report),snapshot)['calculations'][0]['value'],'200')
        report['calculations'][0]['value']='300'
        with self.assertRaises(ValueError):validate_report(json.dumps(report),snapshot)

    def test_two_pass_reconnect_deduplicates_and_key_never_persists(self):
        preview=self.preview()
        async def run():
            first=await self.service.submit(preview['id'],preview['snapshot_hash'],CONFIG,'analysis-key')
            duplicate=await self.service.submit(preview['id'],preview['snapshot_hash'],CONFIG,'analysis-key')
            self.assertEqual(first['id'],duplicate['id'])
            task=self.service.tasks.get(first['id'])
            if task:await task
            return self.service.get(first['id'])
        job=asyncio.run(run())
        self.assertEqual(job['state'],'ready',job)
        self.assertEqual(len(self.calls),2)
        self.assertTrue(job['same_model_review'])
        self.assertEqual(job['report']['facts'][0]['quote'],'营业收入10亿元')
        with db.connect() as c:
            texts=[r[0] for r in c.execute('SELECT data FROM investment_analysis_jobs')]
            texts += [r[0] for r in c.execute('SELECT data FROM investment_objects')]
            texts += [r[0] for r in c.execute('SELECT response FROM investment_requests')]
        self.assertNotIn(CONFIG['api_key'],''.join(texts))

    def test_unsupported_fact_is_not_accepted(self):
        async def invalid(messages,cfg):
            yield {'text':json.dumps({'summary':'x','facts':[{'evidence_id':self.evidence['id'],
                'quote':'明天上涨80%'}],'inferences':[],'counterarguments':['来源不足，不能推定涨幅'],'missing_inputs':[],'suggestions':[]})}
            yield {'done':True}
        self.service.transport=invalid
        preview=self.preview()
        async def run():
            job=await self.service.submit(preview['id'],preview['snapshot_hash'],CONFIG,'bad-analysis')
            await self.service.tasks[job['id']]
            return self.service.get(job['id'])
        job=asyncio.run(run())
        self.assertEqual(job['state'],'failed')
        self.assertNotIn('report',job)

    def test_conflicting_restatement_keeps_sources_and_later_release_is_excluded(self):
        corrected=self.store.create('research',{'title':'更正原文','content':'更正公告：营业收入8亿元。',
            'period_end':'2026-06-30','available_at':'2026-10-26T10:00:00+08:00'},'restated')
        request={'kind':'research','question':'核对相互矛盾的来源','evidence_ids':[self.evidence['id'],corrected['id']],
            'decision_at':'2026-10-26T15:00:00+08:00'}
        snapshot=self.service.preview(request)['snapshot']
        report={'summary':'两份摘录的数值不同','facts':[{'evidence_id':self.evidence['id'],'quote':'营业收入10亿元'},
            {'evidence_id':corrected['id'],'quote':'营业收入8亿元'}],'counterarguments':['应核对更正时点和原文口径，不能取均值作为事实']}
        self.assertEqual(len(validate_report(json.dumps(report),snapshot)['facts']),2)
        report['facts'][0]['quote']='营业收入9亿元'
        with self.assertRaisesRegex(ValueError,'事实引用'):validate_report(json.dumps(report),snapshot)
        late=self.store.create('research',{'title':'后发报告','content':'统计期很早，实际在之后发布',
            'period_end':'2026-06-30','available_at':'2026-10-27T10:00:00+08:00'},'late-release')
        with self.assertRaises(Problem):self.service.preview({**request,'evidence_ids':[late['id']]})
    def test_cancel_stops_work_and_restart_marks_interrupted(self):
        async def run():
            started=asyncio.Event()
            async def slow(messages,cfg):
                started.set()
                await asyncio.Event().wait()
                yield {'done':True}
            self.service.transport=slow
            preview=self.preview()
            job=await self.service.submit(preview['id'],preview['snapshot_hash'],CONFIG,'cancel-me')
            await started.wait()
            cancelled=await self.service.cancel(job['id'])
            self.assertEqual(cancelled['state'],'cancelled')
        asyncio.run(run())
        with db.connect() as c:
            job={'id':'interrupted-job','state':'running','worker':'old-process','created_at':'2026-10-26T10:00:00+08:00'}
            c.execute('INSERT INTO investment_analysis_jobs VALUES (?,?,?,?)',
                ('interrupted-job','running','fingerprint',json.dumps(job)))
        restarted=InvestmentAnalysis(self.store)
        self.assertEqual(restarted.get('interrupted-job')['state'],'interrupted')

    def test_adoption_is_idempotent_and_creates_a_draft_only(self):
        account=self.store.create('accounts',{'name':'账户','opening_cash':'10000','baseline_date':'2026-10-26'},'account')
        instrument=self.store.create('instruments',{'code':'510000','market':'SSE','kind':'etf','name':'ETF'},'instrument')
        original=self.service.transport
        async def model(messages,cfg):
            async for packet in original(messages,cfg):
                if packet.get('text'):
                    output=json.loads(packet['text']);output['suggestions'][0]['action']='conditional_entry'
                    packet={'text':json.dumps(output)}
                yield packet
        self.service.transport=model
        preview=self.service.preview({'kind':'research','account_id':account['id'],'instrument_id':instrument['id'],
            'question':'有条件地评估','evidence_ids':[self.evidence['id']],
            'decision_at':'2026-10-26T15:00:00+08:00'})
        async def run():
            job=await self.service.submit(preview['id'],preview['snapshot_hash'],CONFIG,'adopt-job')
            await self.service.tasks[job['id']]
            return job
        job=asyncio.run(run())
        decision=self.service.decide(job['id'],0,'adopted','','adopt')
        again=self.service.decide(job['id'],0,'adopted','','adopt-again')
        self.assertEqual(decision['linked_id'],again['linked_id'])
        plan=self.store.get('trade-plans',decision['linked_id'])
        self.assertEqual(plan['state'],'draft')
        self.assertEqual(self.store.listing('trade-plans')['total'],1)
        self.assertEqual(self.store.listing('fills')['total'],0)

    def test_expired_or_changed_inputs_block_new_adoption(self):
        account=self.store.create('accounts',{'name':'账户','opening_cash':'10000','baseline_date':'2026-10-26'},'a')
        review=self.store.create('reviews',{'account_id':account['id'],'date':'2026-10-26','text':'保留原始判断'},'r')
        preview=self.service.preview({'kind':'review','account_id':account['id'],'question':'检查原始判断','include_amounts':True,
            'review_ids':[review['id']],'evidence_ids':[self.evidence['id']],'decision_at':'2026-10-26T15:00:00+08:00'})
        async def run():
            job=await self.service.submit(preview['id'],preview['snapshot_hash'],CONFIG,'expiry-job')
            await self.service.tasks[job['id']];return job
        job=asyncio.run(run())
        with patch('investments.analysis.now',return_value='2026-11-02T09:00:00+08:00'):
            self.assertEqual(self.service.get(job['id'])['expired_suggestion_count'],1)
            with self.assertRaises(Problem) as caught:self.service.decide(job['id'],0,'adopted','','expired')
            self.assertEqual(caught.exception.code,'expired_suggestion')
        self.store.create('cash-events',{'account_id':account['id'],'kind':'deposit','amount':'100',
            'occurred_at':'2026-10-26T13:00:00+08:00'},'later-money')
        self.assertIn('ledger_changed',self.service.get(job['id'])['changed_input_ids'])
        with self.assertRaises(Problem) as caught:self.service.decide(job['id'],0,'adopted','','stale-ledger')
        self.assertEqual(caught.exception.code,'analysis_outdated')
        self.assertEqual(self.store.listing('reviews')['total'],1)

    def test_campaign_review_scope_redacts_amounts_and_checks_trade_citations(self):
        a=self.store.create('accounts',{'name':'复盘','opening_cash':'10000','baseline_date':'2026-10-26'},'campaign-a')
        i=self.store.create('instruments',{'name':'ETF','code':'510000','market':'SSE','kind':'etf'},'campaign-i')
        fill=self.store.create('fills',{'account_id':a['id'],'instrument_id':i['id'],'side':'buy','price':'10',
            'quantity':'100','fee':'0','tax':'0','executed_at':'2026-10-26T10:00:00+08:00'},'campaign-f')
        campaign=self.store.campaigns(a['id'])[0]
        request={'kind':'review','account_id':a['id'],'question':'对照原始成交','campaign_ids':[campaign['id']],
            'decision_at':'2026-10-26T15:00:00+08:00'}
        hidden=self.service.preview(request)['snapshot']
        self.assertNotIn('price',hidden['campaigns'][0]['fills'][0])
        report={'summary':'所录成交核对','counterarguments':['没有事前计划'],'trade_citations':[
            {'campaign_id':campaign['id'],'fill_id':fill['id'],'field':'price','value':'10'}]}
        with self.assertRaises(ValueError):validate_report(json.dumps(report),hidden)
        full=self.service.preview({**request,'include_amounts':True})['snapshot']
        self.assertEqual(validate_report(json.dumps(report),full)['trade_citations'][0]['value'],'10')
        report['trade_citations'][0]['value']='11'
        with self.assertRaises(ValueError):validate_report(json.dumps(report),full)
