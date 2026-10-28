"""Public reference rules must fail closed outside their explicit scope."""
import unittest
from investments.rules import rule_context, calendar, compare_check, normalize_units, freshness

STAMP='2026-10-28T09:00:00+08:00'
class InvestmentRuleTests(unittest.TestCase):
    def instrument(self,market='SSE',code='600000',kind='stock'):
        return {'id':'i','market':market,'code':code,'kind':kind,'name':'资料标的'}

    def test_effective_scope_and_version_do_not_retroactively_apply_rules(self):
        current=rule_context(self.instrument(),'2026-10-28',STAMP)
        self.assertEqual(current['rules']['price_tick'],'0.01')
        self.assertEqual(current['rules']['sell_delay_sessions'],1)
        self.assertEqual(len(current['snapshot_hash']),64)
        self.assertFalse(current['executable']);self.assertIn('trading_status',current['unknown_fields'])
        self.assertEqual(rule_context(self.instrument(),'2026-07-05',STAMP)['status'],'historical_unknown')
        self.assertEqual(rule_context(self.instrument(),'2026-12-01','2026-12-01T09:00:00+08:00')['status'],'review_expired')
        self.assertEqual(rule_context(self.instrument(code='999999'),'2026-10-28',STAMP)['status'],'unsupported_identity')

    def test_star_and_chinext_quantity_rules_and_unknown_etf_mechanism(self):
        star=rule_context(self.instrument(code='688001'),'2026-10-28',STAMP)['rules']
        self.assertEqual((star['minimum_quantity'],star['quantity_step'],star['maximum_quantity']),('200','1','100000'))
        growth=rule_context(self.instrument('SZSE','300001'),'2026-10-28',STAMP)['rules']
        self.assertEqual(growth['maximum_quantity'],'300000')
        etf=rule_context(self.instrument(code='510000',kind='etf'),'2026-10-28',STAMP)
        self.assertIsNone(etf['rules']['sell_delay_sessions'])
        self.assertIn('etf_classification',etf['unknown_fields'])
        self.assertEqual(rule_context(self.instrument('FUND','000001','fund'),'2026-10-28',STAMP)['status'],'unsupported_identity')

    def test_exchange_calendar_weekend_holiday_and_out_of_coverage(self):
        days=calendar('SSE','2026-09-30','2026-10-12',STAMP)
        self.assertEqual(days['status'],'available')
        self.assertFalse(days['sessions']['2026-10-01']);self.assertTrue(days['sessions']['2026-10-08'])
        self.assertFalse(days['sessions']['2026-10-10'])
        self.assertEqual(calendar('SSE','2026-12-31','2027-01-04',STAMP)['status'],'coverage_unknown')
        self.assertEqual(calendar('BSE','2026-10-01','2026-10-08',STAMP)['status'],'coverage_unknown')

    def test_wrong_manual_t0_quantity_or_calendar_never_matches(self):
        check={'rules_valid_from':'2026-10-28','rules_valid_until':'2026-11-02','price_tick':'0.01',
            'minimum_quantity':'100','quantity_step':'100','sell_delay_sessions':0,
            'sessions':{'2026-10-10':True,'2026-10-28':True}}
        result=compare_check(self.instrument(),check,'2026-10-28',STAMP)
        self.assertIn('sell_delay_sessions',[x['field'] for x in result['mismatches']])
        self.assertIn('sessions.2026-10-10',[x['field'] for x in result['mismatches']])
        self.assertEqual(result['status'],'mismatch')

    def test_daily_and_minute_units_are_explicit_and_missing_is_not_zero(self):
        daily=normalize_units('12.5','3.2','lots100','thousand_cny')
        minute=normalize_units('1250','3200','shares','cny')
        self.assertEqual(daily['volume_shares'],minute['volume_shares'])
        self.assertEqual(daily['turnover_cny'],minute['turnover_cny'])
        self.assertEqual(daily['source_volume'],'12.5')
        with self.assertRaises(ValueError):normalize_units('1','1','guessed','cny')
        self.assertIsNone(normalize_units(None,None,'shares','cny')['volume_shares'])

    def test_freshness_distinguishes_missing_stale_future_and_intraday_claims(self):
        self.assertEqual(freshness('SSE',None,STAMP)['status'],'missing')
        self.assertEqual(freshness('SSE','2026-10-26',STAMP)['status'],'stale')
        daily=freshness('SSE','2026-10-27',STAMP)
        self.assertEqual(daily['status'],'latest_completed_session');self.assertFalse(daily['realtime'])
        self.assertEqual(freshness('SSE','2026-10-28',STAMP)['status'],'incomplete_or_future')
        self.assertEqual(freshness('SSE','2026-10-28','2026-10-28T15:10:00+08:00')['status'],'incomplete_or_future')
        self.assertEqual(freshness('SSE','2026-10-28','2026-10-28T15:31:00+08:00')['status'],'latest_completed_session')
        self.assertEqual(freshness('SSE','2026-09-30','2026-10-03T10:00:00+08:00')['status'],'latest_completed_session')

from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_legacy_cloud_schema import PostgreSQLFixture
from investments.api import register

class InvestmentRuleHTTPTests(PostgreSQLFixture):
    def test_context_calendar_and_missing_data_are_private_and_bounded(self):
        app=FastAPI();store=register(app);store.initialize()
        with TestClient(app) as client,patch('investments.rules.now',return_value=STAMP):
            instrument=store.create('instruments',{'code':'600000','market':'SSE','kind':'stock','name':'资料标的'},'i')
            base='/api/investments/instruments/'+instrument['id']
            result=client.get(base+'/rules?on=2026-10-28')
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.headers['cache-control'],'no-store')
            self.assertEqual(result.json()['rules']['quantity_step'],'100')
            self.assertEqual(client.get(base+'/data-status').json()['status'],'missing')
            self.assertEqual(client.get('/api/investments/calendar?market=SSE&start=2026-10-01&end=2026-10-08').json()['sessions']['2026-10-01'],False)
            self.assertEqual(client.get('/api/investments/calendar?market=SSE&start=2026-10-08&end=2026-10-01').status_code,422)
            self.assertEqual(client.get('/api/investments/instruments/not-mine/rules?on=2026-10-28').status_code,404)
            readiness=client.get('/api/investments/readiness').json()
            self.assertFalse(readiness['realtime']['enabled'])
            self.assertEqual(readiness['ai']['credentials'],['api_base_url','api_key','model_name'])
