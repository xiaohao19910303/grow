"""Real login sessions, tenant schemas and investment object references."""
import os
import unittest

import test_accounts as account_fixture


@unittest.skipUnless(os.getenv('TEST_ACCOUNTS_PG_DSN'),'Requires disposable localhost PostgreSQL')
class InvestmentIsolationTests(unittest.TestCase):
    setUp=account_fixture.AccountIntegrationTests.setUp
    cleanup_database=account_fixture.AccountIntegrationTests.cleanup_database
    register=account_fixture.AccountIntegrationTests.register
    invite=account_fixture.AccountIntegrationTests.invite
    login=account_fixture.AccountIntegrationTests.login

    def test_authenticated_workspace_isolates_accounts_and_legacy_records(self):
        self.register('alice')
        response=self.client.post('/api/investments/accounts',json={'name':'ALICE PRIVATE',
            'baseline_date':'2026-10-26','opening_cash':'10000'},
            headers={**self.headers,'Idempotency-Key':'alice-account'})
        self.assertEqual(response.status_code,201,response.text)
        account=response.json()
        instrument=self.client.post('/api/investments/instruments',json={'name':'ALICE SECURITY','code':'600000',
            'market':'SSE','kind':'stock'},headers={**self.headers,'Idempotency-Key':'alice-instrument'}).json()
        minute_path=self.client.post('/api/investments/paths/import',json={'account_id':account['id'],'instrument_id':instrument['id'],
            'text':'start,open,high,low,close,volume,amount\n2026-10-26T10:00:00+08:00,10,11,9,10,1,10\n',
            'source_label':'ALICE PATH','volume_unit':'shares','amount_unit':'cny','price_basis':'unadjusted','use_confirmed':True},
            headers={**self.headers,'Idempotency-Key':'alice-path'}).json()
        check=self.client.post('/api/investments/plan-checks',json={'instrument_id':instrument['id'],
            'quote_price':'10','quote_as_of':'2026-10-26T15:00:00+08:00','sessions':{'2026-10-26':True},
            'rules_valid_from':'2026-10-26','rules_valid_until':'2026-10-26','price_tick':'0.01',
            'quantity_step':'100','minimum_quantity':'100','sell_delay_sessions':1,'trading_status':'normal',
            'source_url':'https://example.com/declared','source_note':'ALICE CHECK','acknowledged':True},
            headers={**self.headers,'Idempotency-Key':'alice-check'}).json()
        drill_response=self.client.post('/api/investments/condition-drills',json={'account_id':account['id'],
            'path_id':minute_path['id'],'check_id':check['id'],'title':'ALICE DRILL','op':'gte','threshold':'10',
            'valid_from':'2026-10-26T09:30:00+08:00','valid_until':'2026-10-26T15:00:00+08:00','acknowledged':True},
            headers={**self.headers,'Idempotency-Key':'alice-drill'})
        self.assertEqual(drill_response.status_code,200,drill_response.text);drill=drill_response.json()
        study_payload={'account_id':account['id'],'path_id':minute_path['id'],'check_id':check['id'],
            'title':'ALICE STUDY','decision_at':'2026-10-26T09:59:00+08:00','evidence_available_at':'2026-10-26T09:58:00+08:00',
            'cash':'10000','quantity':'100','stop_price':'9','target_price':'11','commission_bps':'0',
            'minimum_commission':'1','sell_tax_bps':'0','slippage_bps':'0','participation_rate':'0.1',
            'constraints_text':'date,status,limit_down,limit_up,available_at,corporate_action\n2026-10-26,normal,8,13,2026-10-26T08:00:00+08:00,none_declared\n',
            'source_note':'ALICE DECLARED CONSTRAINTS','acknowledged':True}
        study_response=self.client.post('/api/investments/execution-studies',json=study_payload,
            headers={**self.headers,'Idempotency-Key':'alice-study'})
        self.assertEqual(study_response.status_code,200,study_response.text);study=study_response.json()
        strategy=self.client.post('/api/investments/strategies',json={'title':'ALICE METHOD','entry_conditions':'合成条件',
            'exit_conditions':'反证','validation_scope':'合成观察'},headers={**self.headers,'Idempotency-Key':'alice-strategy'}).json()
        confirmed=self.client.post('/api/investments/strategies/'+strategy['id']+'/state',json={'version':1,'state':'confirmed'},
            headers={**self.headers,'Idempotency-Key':'alice-strategy-confirm'}).json()
        trial=self.client.post('/api/investments/experiments',json={'account_id':account['id'],'strategy_id':strategy['id'],
            'strategy_version':confirmed['version'],'title':'ALICE TRIAL','hypothesis':'先登记','counter_case':'可能无效','stop_condition':'资料缺失',
            'parameters':{'sessions':'2'},'cost_assumptions':'实际费用','start_at':'2030-01-01T10:00:00+08:00',
            'end_at':'2030-01-02T15:00:00+08:00','sample_target':10,'additional_roundtrip_costs':['0']},
            headers={**self.headers,'Idempotency-Key':'alice-trial'}).json()
        old=self.client.post('/api/stocks',json={'stock_code':'123','stock_name':'ALICE OLD',
            'action':'buy','date':'2026-10-26','price':1},headers=self.headers)
        self.assertEqual(old.status_code,200,old.text)
        self.client.post('/api/auth/logout',headers=self.headers)
        self.register('bob')
        self.assertEqual(self.client.get('/api/investments/accounts').json()['total'],0)
        for path in ('/api/investments/accounts/'+account['id'],
                     '/api/investments/paths/'+minute_path['id'],
                     '/api/investments/paths?account_id='+account['id'],
                     '/api/investments/execution-studies/'+study['id'],
                     '/api/investments/execution-studies?account_id='+account['id'],
                     '/api/investments/condition-drills/'+drill['id'],
                     '/api/investments/condition-drills?account_id='+account['id'],
                     '/api/investments/experiments/'+trial['id'],
                     '/api/investments/experiments/'+trial['id']+'/history',
                     '/api/investments/experiments?account_id='+account['id'],
                     '/api/investments/instruments/'+instrument['id']+'/rules?on=2026-10-28',
                     '/api/investments/instruments/'+instrument['id']+'/data-status',
                     '/api/investments/accounts/'+account['id']+'/balance',
                     '/api/investments/accounts/'+account['id']+'/policy-status?as_of=2026-10-28',
                     '/api/investments/accounts/'+account['id']+'/summary?start=2026-10-26&end=2026-10-28',
                     '/api/investments/accounts/'+account['id']+'/campaigns/not-mine/review',
                     '/api/investments/accounts/'+account['id']+'/history'):
            response=self.client.get(path)
            self.assertEqual(response.status_code,404,response.text)
            self.assertNotIn('ALICE PRIVATE',response.text)
        cross_drill=self.client.post('/api/investments/condition-drills',json={'account_id':account['id'],
            'path_id':minute_path['id'],'check_id':check['id'],'title':'cross','op':'gte','threshold':'10',
            'valid_from':'2026-10-26T09:30:00+08:00','valid_until':'2026-10-26T15:00:00+08:00','acknowledged':True},
            headers={**self.headers,'Idempotency-Key':'cross-drill'})
        self.assertEqual(cross_drill.status_code,404,cross_drill.text)
        cross_study=self.client.post('/api/investments/execution-studies',json=study_payload,
            headers={**self.headers,'Idempotency-Key':'cross-study'})
        self.assertEqual(cross_study.status_code,404,cross_study.text)
        self.assertEqual(self.client.get('/api/stocks').json()['records'],[])
        forbidden=self.client.post('/api/investments/cash-events',json={
            'account_id':account['id'],'kind':'deposit','amount':'1',
            'occurred_at':'2026-10-26T11:00:00+08:00'},
            headers={**self.headers,'Idempotency-Key':'cross-account'})
        self.assertEqual(forbidden.status_code,404,forbidden.text)
