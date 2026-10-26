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
