"""HTTP boundary against private PostgreSQL; no business database or model calls."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_legacy_cloud_schema import PostgreSQLFixture
from investments.api import register


class InvestmentAPITests(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        self.app=FastAPI()
        self.store=register(self.app)
        self.store.initialize()
        self.client=TestClient(self.app)
        self.addCleanup(self.client.close)
        self.headers={'X-Copilot-Request':'1','Idempotency-Key':'account-http'}

    def test_account_creation_contract_openapi_and_replay(self):
        body={'name':'测试账户','baseline_date':'2026-10-26','opening_cash':'10000'}
        response=self.client.post('/api/investments/accounts',json=body,headers=self.headers)
        self.assertEqual(response.status_code,201,response.text)
        record=response.json()
        repeated=self.client.post('/api/investments/accounts',json=body,headers=self.headers)
        self.assertEqual(repeated.json(),record)
        self.assertEqual(self.client.get('/api/investments/accounts/'+record['id']+'/balance').json()['cash'],'10000')
        self.assertEqual(self.client.get('/api/investments/accounts').json()['total'],1)
        schema=self.client.get('/openapi.json').json()
        self.assertIn('AccountInput',schema['components']['schemas'])

    def test_write_header_and_invalid_decimal_rejected(self):
        body={'name':'bad','baseline_date':'2026-10-26','opening_cash':0.1}
        self.assertEqual(self.client.post('/api/investments/accounts',json=body).status_code,403)
        self.assertEqual(self.client.post('/api/investments/accounts',json=body,headers=self.headers).status_code,422)

    def test_private_responses_and_unknown_resource(self):
        response=self.client.get('/api/investments/accounts/not-mine')
        self.assertEqual(response.status_code,404)
        self.assertEqual(response.headers['cache-control'],'no-store')
        response=self.client.get('/api/investments/capabilities')
        self.assertFalse(response.json()['realtime']['enabled'])
        self.assertFalse(response.json()['provider']['verified'])

    def test_validation_does_not_echo_ai_credentials(self):
        response=self.client.post('/api/investments/analysis/jobs',json={
            'ai_config':{'api_key':'DO_NOT_ECHO_PRIVATE_KEY'}},headers=self.headers)
        self.assertEqual(response.status_code,422,response.text)
        self.assertNotIn('DO_NOT_ECHO_PRIVATE_KEY',response.text)

    def test_market_import_and_conditions_http_boundary(self):
        instrument=self.store.create('instruments',{'name':'测试ETF','code':'510000','market':'SSE','kind':'etf'},'i')
        body={'instrument_id':instrument['id'],'text':'date,open,high,low,close,volume,amount\n2026-10-26,1,2,1,1.5,100,150\n',
              'source_label':'本人导出','volume_unit':'shares','amount_unit':'cny','use_confirmed':True}
        response=self.client.post('/api/investments/market/import',json=body,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['freshness'],'manual_unverified')
        response=self.client.post('/api/investments/screen',json={'as_of':'2026-10-26',
            'conditions':[{'field':'close','op':'gte','value':'1.4'}]},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['total'],1)
        self.assertFalse(response.json()['full_market'])
        invalid=self.client.post('/api/investments/screen',json={'as_of':'2026-10-26',
            'conditions':[{'field':'script','op':'eq','value':'anything'}]},headers=self.headers)
        self.assertEqual(invalid.status_code,422)
        self.assertEqual(self.client.get('/api/investments/data-sources').headers['cache-control'],'no-store')
