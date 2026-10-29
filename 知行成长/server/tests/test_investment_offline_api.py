"""Private HTTP contracts for offline paths, protocols and unavailable capabilities."""
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_legacy_cloud_schema import PostgreSQLFixture
from investments.api import register

class InvestmentOfflineHTTPTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        for name in ('store','planning','experiments','replay'):
            p=patch('investments.'+name+'.now',return_value='2026-10-28T09:00:00+08:00');p.start();self.addCleanup(p.stop)
        app=FastAPI();self.s=register(app);self.s.initialize();self.client=TestClient(app);self.addCleanup(self.client.close)
        self.a=self.s.create('accounts',{'name':'A','baseline_date':'2026-10-26','opening_cash':'10000'},'a')
        self.i=self.s.create('instruments',{'market':'SSE','code':'600000','kind':'stock','name':'合成股票'},'i')
        strategy=self.s.create('strategies',{'title':'合成策略','entry_conditions':'条件','exit_conditions':'失效','validation_scope':'前向观察'},'s')
        self.strategy=self.s.transition('strategies',strategy['id'],1,'confirmed','sc')
        self.headers={'X-Copilot-Request':'1','Idempotency-Key':'operation'}

    def test_paths_are_bounded_auditable_and_no_write_header_is_rejected(self):
        body={'account_id':self.a['id'],'instrument_id':self.i['id'],
            'text':'start,open,high,low,close,volume,amount\n2026-10-27T10:00:00+08:00,10,11,9,10,1,10\n',
            'source_label':'私人CSV','volume_unit':'shares','amount_unit':'cny','price_basis':'unadjusted','use_confirmed':True}
        self.assertEqual(self.client.post('/api/investments/paths/import',json=body).status_code,403)
        saved=self.client.post('/api/investments/paths/import',json=body,headers=self.headers)
        self.assertEqual(saved.status_code,200,saved.text);self.assertEqual(saved.headers['cache-control'],'no-store')
        path=saved.json();self.assertEqual(self.client.post('/api/investments/paths/import',json=body,headers=self.headers).json()['id'],path['id'])
        listed=self.client.get('/api/investments/paths',params={'account_id':self.a['id']}).json()
        self.assertNotIn('bars',listed['items'][0]);self.assertNotIn('raw_text',listed['items'][0])
        self.assertEqual(self.client.get('/api/investments/paths/'+path['id']).json()['raw_text'],body['text'])
        body['text']=body['text'].replace('+08:00','')
        self.assertEqual(self.client.post('/api/investments/paths/import',json=body,headers={**self.headers,'Idempotency-Key':'invalid'}).status_code,422)
        self.assertEqual(self.client.put('/api/investments/paths/'+path['id'],json={},headers=self.headers).status_code,405)

    def test_protocol_registration_finishing_and_disabled_modes_are_explicit(self):
        body={'account_id':self.a['id'],'strategy_id':self.strategy['id'],'strategy_version':2,'title':'协议',
            'hypothesis':'先登记','counter_case':'可能无效','stop_condition':'资料缺失','parameters':{'sessions':'2'},
            'cost_assumptions':'核对实际费用','start_at':'2026-10-28T10:00:00+08:00','end_at':'2026-10-29T15:00:00+08:00',
            'sample_target':10,'additional_roundtrip_costs':['0','1']}
        draft=self.client.post('/api/investments/experiments',json=body,headers=self.headers)
        self.assertEqual(draft.status_code,201,draft.text);eid=draft.json()['id'];base='/api/investments/experiments/'+eid
        registered=self.client.post(base+'/register',json={'version':1,'state':'confirmed'},headers={**self.headers,'Idempotency-Key':'register'})
        self.assertEqual(registered.status_code,200,registered.text)
        edit=self.client.put(base,json={'version':2,'data':{'parameters':{'sessions':'5'}}},headers={**self.headers,'Idempotency-Key':'edit'})
        self.assertEqual(edit.status_code,409)
        result=self.client.get(base+'/evaluation').json();self.assertIsNone(result['net_realized']);self.assertEqual(result['closed_count'],0)
        finish=self.client.post(base+'/finish',json={'version':2,'decision':'stopped','reason':'停止合成观察','evaluation_hash':result['evaluation_hash']},headers={**self.headers,'Idempotency-Key':'stop'})
        self.assertEqual(finish.status_code,200,finish.text);self.assertEqual(finish.json()['state'],'finished')
        self.assertEqual(len(self.client.get(base+'/history').json()['items']),3)
        gates=self.client.get('/api/investments/readiness').json()
        self.assertTrue(gates['offline_replay']['enabled']);self.assertFalse(gates['realtime']['enabled'])
        self.assertTrue(gates['backtest']['enabled']);self.assertTrue(gates['intraday_alerts']['enabled']);self.assertFalse(gates['intraday_alerts']['background'])
        self.assertEqual(self.client.post('/api/investments/backtests',json={},headers=self.headers).status_code,404)
