"""Bounded fixed-host provider protocol, exact units and honest freshness."""
import asyncio
import json

import httpx
from copilot.core import Problem
from investments.store import InvestmentStore
from investments.providers import DailyProvider
from test_legacy_cloud_schema import PostgreSQLFixture


class InvestmentProviderTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp();self.store=InvestmentStore();self.store.initialize()
        self.instrument=self.store.create('instruments',{'code':'510000','market':'SSE','kind':'etf','name':'ETF'},'i')
        self.calls=[]
        def dispatch(request):
            body=json.loads(request.content);self.calls.append(body)
            self.assertEqual(request.url.scheme,'https')
            self.assertEqual(request.url.host,'api.tushare.pro')
            if body['api_name']=='trade_cal':
                data={'fields':['exchange','cal_date','is_open','pretrade_date'],
                    'items':[['SSE','20261023',1,'20261022'],['SSE','20261024',0,'20261023'],
                             ['SSE','20261025',0,'20261023'],['SSE','20261026',1,'20261023']]}
            else:
                data={'fields':['ts_code','trade_date','open','high','low','close','vol','amount'],
                    'items':[['510000.SH','20261023',1.231,1.240,1.220,1.234,100,123.4]]}
            return httpx.Response(200,json={'code':0,'msg':None,'data':data})
        self.provider=DailyProvider(self.store,httpx.MockTransport(dispatch))

    def test_daily_units_are_normalized_and_not_claimed_realtime(self):
        result=asyncio.run(self.provider.fetch(self.instrument['id'],'2026-10-23','2026-10-26',
            'PROVIDER_TEST_ONLY',True,'daily-key'))
        bar=result['bars'][0]
        self.assertEqual(bar['close'],'1.234')
        self.assertEqual(bar['volume_shares'],'10000')
        self.assertEqual(bar['turnover_cny'],'123400')
        self.assertEqual(result['coverage'],'daily_only')
        self.assertFalse(result['realtime'])
        asyncio.run(self.provider.fetch(self.instrument['id'],'2026-10-23','2026-10-26',
            'PROVIDER_TEST_ONLY',True,'daily-key'))
        self.assertEqual(len(self.calls),2)
        self.assertNotIn('PROVIDER_TEST_ONLY',json.dumps(self.store.export()))

    def test_missing_permission_never_echoes_provider_message_or_token(self):
        def denied(request):
            return httpx.Response(200,json={'code':2002,'msg':'SECRET_PROVIDER_TOKEN','data':None})
        provider=DailyProvider(self.store,httpx.MockTransport(denied))
        with self.assertRaises(Problem) as error:
            asyncio.run(provider.fetch(self.instrument['id'],'2026-10-23','2026-10-26',
                'SECRET_PROVIDER_TOKEN',True,'denied'))
        self.assertNotIn('SECRET_PROVIDER_TOKEN',error.exception.message)
        self.assertEqual(self.store.listing('research')['total'],0)

    def test_use_confirmation_required_and_empty_data_not_zero(self):
        with self.assertRaises(Problem):
            asyncio.run(self.provider.fetch(self.instrument['id'],'2026-10-23','2026-10-26',
                'PROVIDER_TEST_ONLY',False,'no-license'))
