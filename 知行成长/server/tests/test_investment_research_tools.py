"""Research tools freeze private source data and never mutate the trade ledger."""
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from investments.api import register
from test_legacy_cloud_schema import PostgreSQLFixture


class ResearchToolsTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp();app=FastAPI();self.store=register(app);self.store.initialize()
        self.client=TestClient(app);self.addCleanup(self.client.close)
        self.account=self.store.create('accounts',{'name':'研究账户','baseline_date':'2026-10-28','opening_cash':'10000'},'research-account')

    def post(self,path,body,key='research-request-key',status=200):
        response=self.client.post('/api/investments/research/'+path,json=body,headers={'X-Copilot-Request':'1','Idempotency-Key':key})
        self.assertEqual(response.status_code,status,response.text);return response.json()

    def dataset(self):
        return self.post('datasets',{'account_id':self.account['id'],'source_label':'合法合成CSV','use_confirmed':True,
            'market_date':'2026-10-28','coverage':'declared_universe','expected_count':3,
            'rows':[{'code':'000001','name':'合成甲','values':{'close':'10','turnover_rate_pct':'3','pe':'8'}},
                    {'code':'600000','name':'合成乙','values':{'close':'20','turnover_rate_pct':None,'pe':'12'}},
                    {'code':'300001','name':'合成丙','values':{'close':'30','turnover_rate_pct':'1','pe':'-1'}}]},'data-key',201)

    def test_screen_explains_unknown_and_paginates_without_changing_frozen_data(self):
        dataset=self.dataset();body={'account_id':self.account['id'],'dataset_id':dataset['id'],
            'conditions':[{'field':'turnover_rate_pct','op':'gte','value':'2'}],'combine':'all','sort_by':'close','descending':True}
        result=self.post('screens',body,'screen-key',201)
        self.assertEqual(result['data']['matched'],1);self.assertEqual(result['data']['unknown'],1)
        self.assertEqual(result['data']['evaluations'][0]['status'],'matched')
        saved=self.client.get('/api/investments/research/objects/'+dataset['id']).json()
        self.assertEqual(saved['input_hash'],dataset['input_hash'])
        self.assertEqual(self.store.balance(self.account['id'])['cash'],'10000')
        self.assertEqual(self.post('screens',body,'screen-key',201),result)

    def test_presets_are_versioned_and_account_scoped(self):
        dataset=self.dataset()
        preset=self.post('presets',{'account_id':self.account['id'],'name':'换手','conditions':[{'field':'pe','op':'gt','value':'0'}]},'preset-key',201)
        updated=self.post('presets/'+preset['id'],{'version':1,'name':'新版','enabled':False},'preset-update')
        self.assertEqual(updated['version'],2)
        self.post('presets/'+preset['id'],{'version':1,'name':'旧版本','enabled':True},'preset-conflict',409)
        other=self.store.create('accounts',{'name':'其他账户','baseline_date':'2026-10-28','opening_cash':'0'},'other-research-account')
        self.post('screens',{'account_id':other['id'],'dataset_id':dataset['id'],'conditions':[]},'wrong-account',422)

    def test_quote_age_cooldown_and_session_guards(self):
        alert=self.post('alerts',{'account_id':self.account['id'],'code':'000001','name':'合成甲','field':'price_above','threshold':'10','cooldown_seconds':300},'alert-key',201)
        quote={'code':'000001','price':'11','previous_close':'10','quoted_at':'2026-10-29T10:00:00+08:00'}
        body={'account_id':self.account['id'],'quotes':[quote],'use_confirmed':True,'source_label':'合成接口'}
        with patch('investments.research_tools.now',return_value='2026-10-29T10:00:01+08:00'):
            first=self.post('alerts/check',body,'check-first');second=self.post('alerts/check',body,'check-second')
        self.assertEqual(len(first['events']),1);self.assertEqual(second['events'],[])
        current=self.client.get('/api/investments/research/objects/'+alert['id']).json()
        self.post('alerts/'+alert['id'],{'version':current['version'],'threshold':'10'},'alert-same-threshold')
        with patch('investments.research_tools.now',return_value='2026-10-29T10:00:02+08:00'):
            self.assertEqual(self.post('alerts/check',body,'check-after-edit')['events'],[])
        with patch('investments.research_tools.now',return_value='2026-10-29T10:10:00+08:00'):
            stale=self.post('alerts/check',body,'check-stale')
        self.assertEqual(stale['events'],[]);self.assertIn('stale',str(stale['checks']))
        with patch('investments.research_tools.now',return_value='2026-10-29T12:00:00+08:00'):
            lunch=self.post('alerts/check',{**body,'quotes':[{**quote,'quoted_at':'2026-10-29T12:00:00+08:00'}]},'check-lunch')
        self.assertEqual(lunch['events'],[]);self.assertIn('closed',str(lunch['checks']))
