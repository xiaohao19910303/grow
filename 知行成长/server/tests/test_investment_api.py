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

    def test_akshare_entry_requires_confirmation_and_never_requires_or_sends_tushare_token(self):
        from unittest.mock import patch
        instrument=self.store.create('instruments',{'name':'合成股票','code':'600000','market':'SSE','kind':'stock'},'ak-i')
        body={'instrument_id':instrument['id'],'start_date':'2026-10-23','end_date':'2026-10-27','use_confirmed':True}
        packet={'library_version':'test','rows':[{'日期':'2026-10-27','开盘':'10','最高':'12','最低':'9',
            '收盘':'11','成交量':'100','成交额':'110000'}]}
        with patch('investments.akshare_daily.load_rows',return_value=packet) as loader:
            response=self.client.post('/api/investments/provider/akshare/daily',json=body,headers=self.headers)
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['provider'],'akshare_eastmoney')
            self.assertEqual(response.headers['cache-control'],'no-store')
            self.assertEqual(loader.call_args.args,('stock','600000','2026-10-23','2026-10-27'))
            replay=self.client.post('/api/investments/provider/akshare/daily',json=body,headers=self.headers)
            self.assertEqual(replay.json(),response.json());self.assertEqual(loader.call_count,1)
        denied=self.client.post('/api/investments/provider/akshare/daily',json={**body,'use_confirmed':False},
            headers={**self.headers,'Idempotency-Key':'not-confirmed'})
        self.assertEqual(denied.status_code,422)
        self.assertEqual(self.client.post('/api/investments/provider/akshare/daily',json=body).status_code,403)
        sources=self.client.get('/api/investments/data-sources').json()['sources']
        self.assertEqual(next(s for s in sources if s['id']=='akshare')['status'],'adapter_ready')
        self.assertIn('/api/investments/provider/daily',self.client.get('/openapi.json').json()['paths'])

    def test_plan_conditions_are_checked_on_create_edit_and_legacy_confirmation(self):
        import db
        account=self.store.create('accounts',{'name':'校验账户','opening_cash':'0','baseline_date':'2026-10-28'},'condition-a')
        instrument=self.store.create('instruments',{'name':'合成股票','code':'600000','market':'SSE','kind':'stock'},'condition-i')
        body={'account_id':account['id'],'instrument_id':instrument['id'],'title':'公开资料研究',
            'entry_conditions':'核对截至复核日已公开公告；缺资料则等待','invalidation':'公开公告发生更正时重新研究',
            'valid_until':'2030-01-01T15:00:00+08:00'}
        bad={**body,'entry_conditions':'确认无未公开重大事项'}
        response=self.client.post('/api/investments/trade-plans',json=bad,headers=self.headers)
        self.assertEqual(response.status_code,422)
        self.assertEqual(response.json()['error'],'unverifiable_conditions')
        self.assertIn('已公开公告',response.json()['message'])
        self.assertEqual(self.store.listing('trade-plans')['total'],0)
        response=self.client.post('/api/investments/trade-plans',json=body,headers=self.headers)
        self.assertEqual(response.status_code,201,response.text);plan=response.json()
        response=self.client.put('/api/investments/trade-plans/'+plan['id'],json={'version':1,
            'data':{'invalidation':'核实内幕消息'}},headers={**self.headers,'Idempotency-Key':'bad-plan-edit'})
        self.assertEqual(response.status_code,422)
        self.assertEqual(response.json()['error'],'unverifiable_conditions')
        self.assertEqual(self.store.get('trade-plans',plan['id'])['version'],1)
        legacy={**plan,'version':2,'entry_conditions':bad['entry_conditions']}
        with db.connect() as c:self.store.save(c,'trade-plans',legacy)
        response=self.client.post('/api/investments/trade-plans/'+plan['id']+'/state',json={'version':2,'state':'confirmed'},
            headers={**self.headers,'Idempotency-Key':'bad-plan-confirm'})
        self.assertEqual(response.status_code,422)
        self.assertEqual(response.json()['error'],'unverifiable_conditions')
        self.assertEqual(self.store.get('trade-plans',plan['id']),legacy)
