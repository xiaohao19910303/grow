"""Selected evidence, two-pass AI, idempotency and no persisted model credentials."""
import asyncio
import json

import db
from copilot.core import Problem
from investments.store import InvestmentStore
from investments.analysis import InvestmentAnalysis
from test_legacy_cloud_schema import PostgreSQLFixture

CONFIG={'api_base_url':'https://model.example/v1','api_key':'INVESTMENT_PRIVATE_TEST_KEY','model_name':'test-model'}


class InvestmentAnalysisTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp();self.store=InvestmentStore();self.store.initialize()
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
                'quote':'明天上涨80%'}],'inferences':[],'counterarguments':[],'missing_inputs':[],'suggestions':[]})}
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
