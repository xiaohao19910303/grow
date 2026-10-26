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
        old=self.client.post('/api/stocks',json={'stock_code':'123','stock_name':'ALICE OLD',
            'action':'buy','date':'2026-10-26','price':1},headers=self.headers)
        self.assertEqual(old.status_code,200,old.text)
        self.client.post('/api/auth/logout',headers=self.headers)
        self.register('bob')
        self.assertEqual(self.client.get('/api/investments/accounts').json()['total'],0)
        for path in ('/api/investments/accounts/'+account['id'],
                     '/api/investments/accounts/'+account['id']+'/balance',
                     '/api/investments/accounts/'+account['id']+'/history'):
            response=self.client.get(path)
            self.assertEqual(response.status_code,404,response.text)
            self.assertNotIn('ALICE PRIVATE',response.text)
        self.assertEqual(self.client.get('/api/stocks').json()['records'],[])
        forbidden=self.client.post('/api/investments/cash-events',json={
            'account_id':account['id'],'kind':'deposit','amount':'1',
            'occurred_at':'2026-10-26T11:00:00+08:00'},
            headers={**self.headers,'Idempotency-Key':'cross-account'})
        self.assertEqual(forbidden.status_code,404,forbidden.text)
