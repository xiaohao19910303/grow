"""Declarative local filtering never executes model code or claims full-market coverage."""
import unittest

from pydantic import ValidationError
from investments.screening import ScreenInput, filter_snapshots


class InvestmentScreenTests(unittest.TestCase):
    def test_numeric_conditions_and_missing_metrics(self):
        universe=[{'instrument_id':'a','name':'A','market':'SSE','kind':'stock','bars':[
            {'date':'2026-10-23','close':'10','volume_shares':'100','turnover_cny':'1000'},
            {'date':'2026-10-26','close':'11','volume_shares':'200','turnover_cny':'2200'}]},
            {'instrument_id':'b','name':'B','market':'SZSE','kind':'etf','bars':[]}]
        request=ScreenInput.model_validate({'as_of':'2026-10-26','conditions':[
            {'field':'close_change_pct','op':'gte','value':'5'}]})
        result=filter_snapshots(universe,request)
        self.assertEqual([r['instrument_id'] for r in result['items']],['a'])
        self.assertEqual(result['unresolved'],1)
        self.assertEqual(result['scope'],'private_cached_universe')
        self.assertFalse(result['full_market'])

    def test_model_generated_code_and_unknown_fields_are_rejected(self):
        for field in ('__import__','sql','main_money_intent'):
            with self.assertRaises(ValidationError):
                ScreenInput.model_validate({'as_of':'2026-10-26','conditions':[{'field':field,'op':'gte','value':'0'}]})

    def test_historical_filter_does_not_use_later_prices(self):
        request=ScreenInput.model_validate({'as_of':'2026-10-23','conditions':[{'field':'close','op':'gt','value':'20'}]})
        data=[{'instrument_id':'a','name':'A','market':'SSE','kind':'stock','bars':[
            {'date':'2026-10-23','close':'10','volume_shares':'100','turnover_cny':'1000'},
            {'date':'2026-10-26','close':'100','volume_shares':'100','turnover_cny':'10000'}]}]
        self.assertEqual(filter_snapshots(data,request)['items'],[])
