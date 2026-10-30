"""Selected AKShare suppliers keep identity, units and error boundaries explicit."""
import unittest
from unittest.mock import patch
import pandas as pd
from investments.research_worker import fetch
from investments.research_sources import normalize_spot,worker
from copilot.core import Problem
import subprocess,json


class ResearchAKShareTests(unittest.TestCase):
    def test_tencent_market_calls_only_selected_supplier_and_preserves_raw_fields(self):
        frame=pd.DataFrame([{'code':'sz000001','name':'合成银行','zxj':'11.64','volume':'1864245','turnover':'215239','zsz':'2000','pe_ttm':'5.20','pn':'0.47'}])
        with patch('akshare.stock_zh_a_spot_tx',return_value=frame) as chosen,patch('akshare.stock_zh_a_spot_em',side_effect=AssertionError('unexpected supplier')):
            packet=fetch({'task':'market','source':'tencent'})
        chosen.assert_called_once();self.assertEqual(packet['upstream'],'tencent');self.assertEqual(packet['rows'][0]['pe_ttm'],'5.20')
        rows=normalize_spot(packet['rows'],'tencent');values=rows[0]['values']
        self.assertEqual(rows[0]['code'],'000001.SZ');self.assertEqual(values['volume_shares'],'186424500')
        self.assertEqual(values['turnover_cny'],'2152390000');self.assertEqual(values['market_cap_cny'],'200000000000')
        self.assertEqual(values['pe_ttm'],'5.20');self.assertIsNone(values.get('pe'))

    def test_tencent_daily_keeps_raw_decimal_amount_and_market_specific_volume(self):
        import requests
        for code,raw_volume,shares in [('000001','1864245','186424500'),('688001','7631034','7631034')]:
            symbol=('sh' if code.startswith('6') else 'sz')+code
            response=requests.Response();response.status_code=200
            response._content=json.dumps({'data':{symbol:{'day':[['2026-10-30','11','11.64','12','10',raw_volume,'','0.87','100000.04']]}}}).encode()
            with patch('requests.adapters.HTTPAdapter.send',return_value=response),patch('akshare.stock_zh_a_hist',side_effect=AssertionError('unexpected supplier')):
                packet=fetch({'task':'history','source':'tencent','kind':'stock','code':code,'interval':'day','start':'2026-10-28','end':'2026-10-30'})
            self.assertEqual(packet['rows'][0]['成交量'],shares);self.assertEqual(packet['volume_unit'],'shares')
            self.assertEqual(packet['rows'][0]['成交额'],'1000000400.00')

    def test_http_429_is_rate_limit_even_when_supplier_json_has_no_data(self):
        import requests
        response=requests.Response();response.status_code=429;response._content=b'{"code":429}'
        with patch('requests.adapters.HTTPAdapter.send',return_value=response):
            with self.assertRaises(requests.HTTPError) as raised:fetch({'task':'market','source':'tencent'})
        from investments.research_worker import error_packet
        self.assertEqual(error_packet(raised.exception)['error'],'upstream_rate_limit')

    def test_eastmoney_connection_failure_is_attempted_once_without_switching(self):
        import requests
        with patch('requests.Session.get',side_effect=requests.exceptions.ProxyError('controlled')) as get,patch('akshare.stock_zh_a_spot_tx',side_effect=AssertionError('unexpected fallback')):
            with self.assertRaises(requests.exceptions.ProxyError):fetch({'task':'market','source':'eastmoney'})
        self.assertEqual(get.call_count,1)

    def test_connection_errors_are_specific_and_never_leak_raw_exception_or_retry(self):
        from investments.research_worker import error_packet
        import requests
        packet=error_packet(requests.exceptions.ProxyError('PRIVATE_PROXY_CREDENTIAL_DO_NOT_EXPOSE'))
        self.assertEqual(packet['error'],'upstream_connection');self.assertNotIn('PRIVATE_PROXY',json.dumps(packet))
        completed=subprocess.CompletedProcess([],0,stdout=json.dumps(packet),stderr='')
        with patch('investments.research_sources.subprocess.run',return_value=completed) as run:
            with self.assertRaises(Problem) as raised:worker({'task':'market','source':'eastmoney'})
        self.assertEqual(raised.exception.code,'provider_connection');self.assertEqual(run.call_count,1)
        self.assertNotIn('PRIVATE_PROXY',raised.exception.message)
