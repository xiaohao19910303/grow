"""Execution scenario snapshots are private, auditable and separate from actual fills."""
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_legacy_cloud_schema import PostgreSQLFixture
from investments.api import register
from investments.replay import import_path

class ExecutionStudyHTTPTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        for module in ('store','replay','execution_studies'):
            p=patch('investments.'+module+'.now',return_value='2026-10-28T16:00:00+08:00');p.start();self.addCleanup(p.stop)
        app=FastAPI();self.s=register(app);self.s.initialize();self.client=TestClient(app);self.addCleanup(self.client.close)
        self.a=self.s.create('accounts',{'name':'A','baseline_date':'2026-10-26','opening_cash':'10000'},'a')
        self.i=self.s.create('instruments',{'market':'SSE','code':'600000','kind':'stock','name':'合成股票'},'i')
        self.check=self.s.create('plan-checks',{'instrument_id':self.i['id'],'quote_price':'10','quote_as_of':'2026-10-26T15:00:00+08:00',
            'sessions':{'2026-10-27':True,'2026-10-28':True},'rules_valid_from':'2026-10-27','rules_valid_until':'2026-10-28',
            'price_tick':'0.01','quantity_step':'100','minimum_quantity':'100','sell_delay_sessions':1,'trading_status':'normal',
            'source_url':'https://example.com/declared','source_note':'合成核对','acknowledged':True},'c')
        self.path=import_path(self.s,{'account_id':self.a['id'],'instrument_id':self.i['id'],
            'text':'start,open,high,low,close,volume,amount\n2026-10-27T14:59:00+08:00,10,10.5,9.5,10,10000,100000\n2026-10-28T09:30:00+08:00,11,12,10.5,11,10000,110000\n',
            'source_label':'合成跨日路径','volume_unit':'shares','amount_unit':'cny','price_basis':'unadjusted','use_confirmed':True},'p')
        self.body={'account_id':self.a['id'],'path_id':self.path['id'],'check_id':self.check['id'],'title':'假设撮合',
            'decision_at':'2026-10-27T14:58:00+08:00','evidence_available_at':'2026-10-27T14:57:00+08:00',
            'cash':'10000','quantity':'100','stop_price':'9','target_price':'11','commission_bps':'0','minimum_commission':'1',
            'sell_tax_bps':'0','slippage_bps':'0','participation_rate':'0.1','source_note':'仅合成样例，非历史证据',
            'constraints_text':'date,status,limit_down,limit_up,available_at,corporate_action\n2026-10-27,normal,8,13,2026-10-27T08:00:00+08:00,none_declared\n2026-10-28,normal,8,13,2026-10-28T08:00:00+08:00,none_declared\n',
            'acknowledged':True}
        self.headers={'X-Copilot-Request':'1','Idempotency-Key':'study'}

    def submit(self,**changes):
        return self.client.post('/api/investments/execution-studies',json={**self.body,**changes},headers=self.headers)

    def test_immutable_private_study_deduplicates_and_does_not_change_actual_cash(self):
        r=self.submit();self.assertEqual(r.status_code,200,r.text);saved=r.json()
        self.assertEqual(saved['result']['net_realized'],'98');self.assertFalse(saved['production_backtest'])
        self.assertEqual(saved['input_snapshot']['constraints_text'],self.body['constraints_text'])
        self.assertEqual(self.submit().json(),saved);self.headers['Idempotency-Key']='retry'
        self.assertEqual(self.submit().json()['id'],saved['id'])
        self.assertEqual(self.client.get('/api/investments/execution-studies/'+saved['id']).json(),saved)
        listing=self.client.get('/api/investments/execution-studies',params={'account_id':self.a['id']})
        self.assertEqual(listing.headers['cache-control'],'no-store');self.assertEqual(listing.json()['total'],1)
        self.assertNotIn('result',listing.json()['items'][0]);self.assertNotIn('input_snapshot',listing.json()['items'][0])
        self.assertEqual(self.s.listing('fills',account_id=self.a['id'])['total'],0)
        self.assertEqual(self.s.balance(self.a['id'])['cash'],'10000')
        self.assertEqual(self.client.put('/api/investments/execution-studies/'+saved['id'],json={},headers=self.headers).status_code,405)
        gates=self.client.get('/api/investments/capabilities').json();self.assertTrue(gates['execution_study']['enabled']);self.assertFalse(gates['backtest']['enabled'])

    def test_future_evidence_and_missing_limits_are_saved_as_failed_or_unresolved(self):
        r=self.submit(evidence_available_at='2026-10-28T10:00:00+08:00');self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['result']['status'],'future_information');self.assertIsNone(r.json()['result']['net_realized'])
        self.headers['Idempotency-Key']='unknown'
        r=self.submit(constraints_text=self.body['constraints_text'].replace('normal,8,13','normal,,13'))
        self.assertEqual(r.json()['result']['status'],'unresolved');self.assertIsNone(r.json()['result']['net_realized'])
        self.assertEqual(self.client.get('/api/investments/execution-studies',params={'account_id':self.a['id']}).json()['total'],2)

    def test_invalid_units_scripts_scope_and_unconfirmed_parameters_are_rejected(self):
        for change in ({'cash':10000},{'slippage_bps':'1001'},{'participation_rate':'1.1'},{'acknowledged':False},
            {'constraints_text':'eval()'},{'decision_at':'2026-10-27T14:58:00'},{'stop_price':'9.001'}):
            self.assertEqual(self.submit(**change).status_code,422)
        other=self.s.create('accounts',{'name':'B','baseline_date':'2026-10-26','opening_cash':'0'},'b')
        self.assertEqual(self.submit(account_id=other['id']).status_code,422)
        self.assertEqual(self.client.post('/api/investments/execution-studies',json=self.body).status_code,403)
