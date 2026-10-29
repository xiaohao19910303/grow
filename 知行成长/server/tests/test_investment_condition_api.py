"""Private immutable drills retain failures and never call a provider or model."""
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_legacy_cloud_schema import PostgreSQLFixture
from investments.api import register
from investments.replay import import_path

class ConditionHTTPTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        for module in ('store','replay','conditions'):
            p=patch('investments.'+module+'.now',return_value='2026-10-28T09:00:00+08:00');p.start();self.addCleanup(p.stop)
        app=FastAPI();self.s=register(app);self.s.initialize();self.client=TestClient(app);self.addCleanup(self.client.close)
        self.a=self.s.create('accounts',{'name':'A','baseline_date':'2026-10-26','opening_cash':'10000'},'a')
        self.i=self.s.create('instruments',{'market':'SSE','code':'600000','kind':'stock','name':'合成股票'},'i')
        self.check=self.s.create('plan-checks',{'instrument_id':self.i['id'],'quote_price':'10','quote_as_of':'2026-10-26T15:00:00+08:00',
            'sessions':{'2026-10-26':True,'2026-10-27':True,'2026-10-28':True},'rules_valid_from':'2026-10-26','rules_valid_until':'2026-10-28',
            'price_tick':'0.01','quantity_step':'100','minimum_quantity':'100','sell_delay_sessions':1,'trading_status':'normal',
            'source_url':'https://example.com/declared','source_note':'本人合成核对资料','acknowledged':True},'c')
        self.path=import_path(self.s,{'account_id':self.a['id'],'instrument_id':self.i['id'],
            'text':'start,open,high,low,close,volume,amount\n2026-10-27T10:00:00+08:00,9,12,9,10,1000,10000\n2026-10-27T10:01:00+08:00,10,12,9,11,1000,10000\n',
            'source_label':'仅验收','volume_unit':'shares','amount_unit':'cny','price_basis':'unadjusted','use_confirmed':True},'p')
        self.body={'account_id':self.a['id'],'path_id':self.path['id'],'check_id':self.check['id'],'title':'价格条件演练',
            'op':'gte','threshold':'10','valid_from':'2026-10-27T09:30:00+08:00','valid_until':'2026-10-27T15:00:00+08:00',
            'max_age_seconds':60,'notification_scope':'page','probe_at':['2026-10-27T10:04:00+08:00','2026-10-27T12:00:00+08:00'],
            'acknowledged':True}
        self.headers={'X-Copilot-Request':'1','Idempotency-Key':'drill'}

    def submit(self,**changes):
        return self.client.post('/api/investments/condition-drills',json={**self.body,**changes},headers=self.headers)

    def test_saved_deduplicated_results_expose_stale_break_and_expiry_without_writing_fills(self):
        r=self.submit();self.assertEqual(r.status_code,200,r.text);result=r.json()
        self.assertEqual(result['status_counts'],{'duplicate_suppressed':1,'expired':1,'matched':1,'outside_session':1,'stale':1})
        self.assertEqual(result['page_candidate_count'],1);self.assertFalse(result['notification_sent']);self.assertFalse(result['realtime'])
        self.assertEqual(self.submit().json(),result)
        self.headers['Idempotency-Key']='same-content';self.assertEqual(self.submit().json()['id'],result['id'])
        self.assertEqual(self.client.get('/api/investments/condition-drills/'+result['id']).json(),result)
        listed=self.client.get('/api/investments/condition-drills',params={'account_id':self.a['id']})
        self.assertEqual(listed.headers['cache-control'],'no-store');self.assertEqual(listed.json()['total'],1)
        self.assertNotIn('rows',listed.json()['items'][0]);self.assertNotIn('check_snapshot',listed.json()['items'][0])
        self.assertEqual(self.s.listing('fills',account_id=self.a['id'])['total'],0)
        self.assertEqual(self.client.put('/api/investments/condition-drills/'+result['id'],json={},headers=self.headers).status_code,405)
        self.assertTrue(self.client.get('/api/investments/capabilities').json()['condition_drill']['enabled'])
        alerts=self.client.get('/api/investments/capabilities').json()['intraday_alerts'];self.assertTrue(alerts['enabled']);self.assertFalse(alerts['background'])

    def test_clock_delay_does_not_look_ahead_and_high_price_does_not_replace_close(self):
        r=self.submit(arrival_delay_seconds=120,probe_at=['2026-10-27T10:02:30+08:00'])
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['rows'][0]['status'],'missing_quote')
        self.assertEqual(r.json()['status_counts']['stale'],2);self.assertEqual(r.json()['matched_count'],0)
        self.headers['Idempotency-Key']='threshold'
        r=self.submit(threshold='12');self.assertEqual(r.json()['matched_count'],0)  # high was 12; close never was.

    def test_t_plus_one_unknown_status_conflicting_rules_and_scope_are_kept_unresolved(self):
        result=self.submit(intent='exit',assumed_bought_on='2026-10-27').json()
        self.assertEqual(result['matched_count'],0);self.assertEqual(result['status_counts']['sell_delay'],2)
        other=self.s.create('accounts',{'name':'B','baseline_date':'2026-10-26','opening_cash':'0'},'b')
        self.headers['Idempotency-Key']='scope';self.assertEqual(self.submit(account_id=other['id']).status_code,422)
        self.headers['Idempotency-Key']='future';self.assertEqual(self.submit(valid_until='2026-10-29T15:00:00+08:00').status_code,422)
        self.headers['Idempotency-Key']='invalid'
        for changes in ({'threshold':10},{'op':'eval'},{'notification_scope':'system'},{'max_age_seconds':True},{'acknowledged':False}):
            self.assertEqual(self.submit(**changes).status_code,422)
        self.assertEqual(self.client.post('/api/investments/condition-drills',json=self.body).status_code,403)
