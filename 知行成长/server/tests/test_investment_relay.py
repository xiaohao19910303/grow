"""The optional relay is private, bounded and never repeats an uncertain call."""
import json
import asyncio
import threading
from unittest.mock import patch

import db
from fastapi import FastAPI
from fastapi.testclient import TestClient
from investments.api import register
from investments.market_import import import_history
from investments.ai_relay import InvestmentRelay
from investments.ai_relay import RelayInput
from test_legacy_cloud_schema import PostgreSQLFixture

CONFIG={'api_base_url':'https://model.example/v1','api_key':'RELAY_TEST_ONLY_SECRET','model_name':'model-test'}


class RelayTests(PostgreSQLFixture):
    def test_cancelling_after_durable_completion_preserves_ready_receipt(self):
        from investments.analysis import InvestmentAnalysis
        from investments.browser_screening_v2 import ExecutionV2
        relay=InvestmentRelay(self.store,ExecutionV2(self.store,InvestmentAnalysis(self.store)))
        written=threading.Event();release=threading.Event();finish=relay.finish
        def delayed(key,data,state):
            result=finish(key,data,state)
            if state=='ready':written.set();release.wait(5)
            return result
        async def stream(messages,cfg):yield {'text':'durable output'};yield {'done':True}
        class Request:
            async def is_disconnected(self):return False
        async def run():
            task=asyncio.create_task(relay.call(RelayInput.model_validate(json.loads(json.dumps(self.body))),'relay-cancel-after-write',Request()))
            self.assertTrue(await asyncio.to_thread(written.wait,5))
            task.cancel();release.set();await asyncio.gather(task,return_exceptions=True)
        with patch.object(relay,'finish',side_effect=delayed),patch('copilot.transport.qwen_stream',stream):asyncio.run(run())
        receipt=self.client.get('/api/investments/ai-relay/calls/relay-cancel-after-write')
        self.assertEqual(receipt.status_code,200,receipt.text);self.assertEqual(receipt.json()['raw'],'durable output')

    def test_ready_receipt_cannot_be_downgraded_after_cancellation(self):
        from investments.analysis import InvestmentAnalysis
        from investments.browser_screening_v2 import ExecutionV2
        relay=InvestmentRelay(self.store,ExecutionV2(self.store,InvestmentAnalysis(self.store)))
        async def stream(messages,cfg):yield {'text':'complete'};yield {'done':True}
        with patch('copilot.transport.qwen_stream',stream):first=self.send()
        relay.finish('relay-call-unique',{'state':'uncertain'},'uncertain')
        recovered=self.client.get('/api/investments/ai-relay/calls/relay-call-unique')
        self.assertEqual(recovered.status_code,200);self.assertEqual(recovered.json()['raw'],'complete')

    def test_candidate_lost_response_can_recover_after_pause_without_model_retry(self):
        instrument=self.store.create('instruments',{'name':'合成ETF','code':'510000','market':'SSE','kind':'etf'},'relay-instrument')
        import_history(self.store,instrument['id'],'date,open,high,low,close,volume,amount\n2026-10-28,10,12,9,11,100,1100\n','shares','cny','合成',True,'relay-market',self.account['id'])
        headers={'X-Copilot-Request':'1'};executor='relay-browser-owner-unique'
        def post(path,body,key):
            response=self.client.post('/api/investments/'+path,json=body,headers={**headers,'Idempotency-Key':key})
            self.assertEqual(response.status_code,200,response.text);return response.json()
        run=post('local-runs',{'account_id':self.account['id'],'instrument_ids':[instrument['id']],'model':'model-test','question':'核对合成资料','executor':executor,'screen':{'as_of':'2026-10-28','conditions':[],'limit':1}},'relay-run')
        post('local-runs/'+run['id']+'/screening',{'algorithm':'browser-screen-rational-v1','executor':executor,'input_hash':run['input_hash'],'total':1,'unresolved':0,
            'items':[{'instrument_id':instrument['id'],'data_date':'2026-10-28','condition_results':[],'values':{'market':'SSE','kind':'etf','name':'合成ETF','close':'11','turnover_cny':'1100','close_change_pct':None,'volume_ratio_5':None,'price_above_ma20':None}}]},'relay-screen')
        job=post('local-runs/'+run['id']+'/candidates/'+instrument['id'],{'executor':executor},'relay-candidate')
        selected=self.client.get('/api/investments/local-jobs/'+job['id']+'/input',headers={'X-Local-Executor':executor}).json()
        snapshot=json.loads(selected['evidence']['messages'][1]['content'])['snapshot'];evidence=snapshot['evidence'][0]
        raw=json.dumps({'summary':'合成核对','facts':[{'evidence_id':evidence['id'],'quote':evidence['content'][:40]}],'counterarguments':['来源仍需核对'],'suggestions':[]})
        calls=[]
        async def stream(messages,cfg):calls.append(1);yield {'text':raw};yield {'done':True}
        body={'account_id':self.account['id'],'purpose':'candidate','job_id':job['id'],'executor':executor,'input_hash':selected['evidence']['input_hash'],'ai_config':CONFIG,'consent':True}
        with patch('copilot.transport.qwen_stream',stream):
            reply=self.send(body,'relay-candidate-call');self.assertEqual(reply.status_code,200,reply.text)
        post('local-jobs/'+job['id']+'/pause',{'executor':executor,'status':'call_uncertain'},'relay-pause')
        receipt=post('ai-relay/jobs/'+job['id']+'/recover',{'executor':executor,'call_key':'relay-candidate-call'},'relay-recover')
        uploaded=post('local-jobs/'+job['id']+'/draft',{'executor':executor,'input_hash':selected['evidence']['input_hash'],'raw':receipt['raw']},'relay-recovered-draft')
        self.assertEqual(uploaded['state'],'running');self.assertEqual(calls,[1])

    def setUp(self):
        super().setUp(); self.app=FastAPI(); self.store=register(self.app); self.store.initialize()
        self.account=self.store.create('accounts',{'name':'转发测试','baseline_date':'2026-10-28','opening_cash':'0'},'relay-account')
        self.client=TestClient(self.app);self.addCleanup(self.client.close)
        self.configured=patch.dict('os.environ',{'INVESTMENT_AI_RELAY_HOSTS':'model.example'});self.configured.start();self.addCleanup(self.configured.stop)
        resolver=patch('socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443))]);resolver.start();self.addCleanup(resolver.stop)
        self.body={'account_id':self.account['id'],'purpose':'parse','messages':[{'role':'user','content':'只处理合成条件：涨幅至少3%'}],
            'ai_config':CONFIG,'consent':True}

    def send(self,body=None,key='relay-call-unique'):
        return self.client.post('/api/investments/ai-relay',json=body or self.body,headers={'X-Copilot-Request':'1','Idempotency-Key':key})

    def test_completed_call_replays_exactly_once_and_persists_no_credentials(self):
        calls=[]
        async def stream(messages,cfg):
            calls.append(cfg.copy());yield {'text':'{"synthetic":true}'};yield {'done':True}
        with patch('copilot.transport.qwen_stream',stream):
            first=self.send();second=self.send()
        self.assertEqual(first.status_code,200,first.text);self.assertEqual(second.json(),first.json());self.assertEqual(len(calls),1)
        with db.connect() as c:
            text=json.dumps([dict(r) for r in c.execute('SELECT * FROM investment_relay_calls')])
        self.assertNotIn(CONFIG['api_key'],text)

    def test_failed_or_partial_call_is_not_retried_with_same_identity(self):
        calls=[]
        async def stream(messages,cfg):calls.append(1);yield {'text':'partial'};raise RuntimeError(CONFIG['api_key'])
        with patch('copilot.transport.qwen_stream',stream):
            first=self.send();second=self.send()
        self.assertEqual(first.status_code,502,first.text);self.assertEqual(second.status_code,409,second.text)
        self.assertEqual(len(calls),1);self.assertNotIn(CONFIG['api_key'],first.text)

    def test_consent_scope_and_destination_are_checked_before_calling(self):
        with patch('copilot.transport.qwen_stream',side_effect=AssertionError('must not call')):
            self.assertEqual(self.send({**self.body,'consent':False}).status_code,422)
            self.assertEqual(self.send({**self.body,'account_id':'another-account'}).status_code,404)
            for url in ('https://127.0.0.1/v1','https://unlisted.example/v1','http://model.example/v1'):
                reply=self.send({**self.body,'ai_config':{**CONFIG,'api_base_url':url}},'bad-'+str(len(url)))
                self.assertEqual(reply.status_code,422,reply.text)
