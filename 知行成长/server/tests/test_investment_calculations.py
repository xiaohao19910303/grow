import unittest
from decimal import Decimal,localcontext
from investments.providers import indicators


class InvestmentIndicatorTests(unittest.TestCase):
    def test_exact_volatility_and_true_range_do_not_invent_missing_samples(self):
        bars=[{'date':f'2026-10-{n:02d}','open':'10','high':'12','low':'8','close':'10','volume_shares':'100'} for n in range(1,22)]
        result=indicators(bars)
        self.assertEqual(result['atr14'],'4');self.assertEqual(result['record_return_std20'],'0')
        self.assertEqual(result['return_sample_count'],20)
        missing=indicators(bars[:3])
        self.assertIsNone(missing['atr14']);self.assertIsNone(missing['record_return_std20'])
        for index,bar in enumerate(bars):bar['close']='10' if index%2==0 else '11'
        varying=indicators(bars)
        with localcontext() as ctx:
            ctx.prec=60
            expected=(Decimal('0.1')+Decimal(1)/11)*(Decimal(5)/19).sqrt()
            self.assertLess(abs(Decimal(varying['record_return_std20'])-expected),Decimal('1e-50'))
        self.assertEqual(varying['ma20'],'10.5')
        self.assertEqual(varying['ma5'],'10.4')
