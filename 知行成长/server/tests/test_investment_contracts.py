"""Exact financial boundaries and reproducible accounting, no external services."""
import unittest
from decimal import Decimal
from pydantic import ValidationError

from investments.contracts import AccountInput, FillInput
from investments.accounting import reconcile


class InvestmentContractsTests(unittest.TestCase):
    def test_rejects_binary_numbers_nonfinite_and_excess_precision(self):
        for value in (1.231, 1, 'NaN', 'Infinity', '0.12345678901', '-1'):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                AccountInput(name='账户', opening_cash=value, baseline_date='2026-10-26')

    def test_decimal_and_missing_fee_are_preserved(self):
        fill = FillInput(account_id='a', instrument_id='i', side='buy', price='1.231',
                         quantity='10000', executed_at='2026-10-26T10:00:00+08:00')
        self.assertEqual(fill.model_dump(mode='json')['price'], '1.231')
        self.assertIsNone(fill.fee)
        with self.assertRaises(ValidationError):
            FillInput(**{**fill.model_dump(mode='json'), 'executed_at':'2026-10-26T10:00:00'})


class InvestmentAccountingTests(unittest.TestCase):
    def fill(self, side, price, quantity, fee='1', **extra):
        return dict(id='f', instrument_id='i', side=side, price=price, quantity=quantity,
                    fee=fee, tax='0', **extra)

    def test_weighted_cost_partial_sale_cash_and_equity(self):
        result = reconcile('10000', [], [self.fill('buy','10','100'),
            self.fill('buy','12','100'), self.fill('sell','13','50')], marks={'i':'12'})
        self.assertEqual(Decimal(result['cash']), Decimal('8447'))
        position = result['positions'][0]
        for key, expected in [('quantity','150'),('cost','1651.50'),('realized','98.50'),('unrealized','148.50')]:
            self.assertEqual(Decimal(position[key]), Decimal(expected))
        self.assertEqual(Decimal(result['equity']), Decimal('10247'))

    def test_etf_subcent_precision(self):
        result = reconcile('20000', [], [self.fill('buy','1.231','10000','0'),
                                       self.fill('sell','1.234','10000','0')])
        self.assertEqual(Decimal(result['realized']), Decimal('30'))
        self.assertEqual(result['positions'][0]['quantity'], '0')

    def test_unknown_cost_does_not_become_verified_net_profit(self):
        result = reconcile('2000', [], [self.fill('buy','10','100',None),
                                       self.fill('sell','11','100','0')])
        self.assertFalse(result['fees_complete'])
        self.assertIsNone(result['net_realized'])

    def test_cashflow_is_not_profit_and_oversell_rejected(self):
        result = reconcile('100', [{'kind':'deposit','amount':'1000'}], [])
        self.assertEqual(result['cash'], '1100')
        self.assertEqual(result['realized'], '0')
        with self.assertRaises(ValueError):
            reconcile('100', [], [self.fill('sell','10','1')])

    def test_unknown_opening_cost_and_fractional_units(self):
        result = reconcile('0', [], [], opening_positions=[{'instrument_id':'fund',
            'quantity':'12.3456','cost':None}], marks={'fund':'1.2345'})
        self.assertIsNone(result['positions'][0]['unrealized'])
        self.assertEqual(result['positions'][0]['quantity'], '12.3456')


if __name__ == '__main__':
    unittest.main()
