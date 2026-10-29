"""Hand-computed round trip, no lookahead, constraints and missing-data refusal."""
import copy
from unittest import TestCase

from investments.strategy_backtest import BacktestConfig,backtest


def series():
    prices=[('9','9'),('11','11'),('12','12'),('9','9'),('8','8')]
    return {'code':'000001.SZ','name':'合成股票','interval':'day','price_basis':'unadjusted',
        'sessions':['2026-10-'+str(n) for n in range(19,24)],'source_label':'合成完整输入',
        'bars':[{'time':f'2026-10-{19+i}T15:00:00+08:00','open_at':f'2026-10-{19+i}T09:30:00+08:00',
            'available_at':f'2026-10-{19+i}T15:01:00+08:00','open':a,'high':str(max(int(a),int(b))+1),
            'low':str(min(int(a),int(b))-1),'close':b,'volume_shares':'10000','suspended':False,
            'limit_up':'100','limit_down':'1','corporate_actions_known':True,'adj_factor':'1',
            'split_ratio':'1','cash_dividend':'0'} for i,(a,b) in enumerate(prices)]}


class StrategyBacktestTests(TestCase):
    def test_minute_backtest_requires_independently_declared_complete_timeline(self):
        source=series();source['interval']='minute'
        config=BacktestConfig(strategy='threshold',entry_above='10',exit_below='10')
        self.assertIn('minute_timeline_gaps_or_missing',backtest(source,config)['missing'])
        source['expected_bar_times']=[b['time'] for b in source['bars']]
        self.assertEqual(backtest(source,config)['status'],'complete')
        source['expected_bar_times'].append('2026-10-23T14:59:00+08:00')
        self.assertIn('minute_timeline_gaps_or_missing',backtest(source,config)['missing'])
    def test_delayed_history_and_mixed_offsets_do_not_bypass_time_boundaries(self):
        data=series()
        for bar,close in zip(data['bars'],('1','3','1','3','3')):
            bar.update(open=close,close=close,high=str(int(close)+1),low='1')
        data['bars'][2]['available_at']='2026-10-25T15:00:00+08:00'
        cfg=BacktestConfig(strategy='ma_cross',fast_window=1,slow_window=2,slippage_bps='0')
        self.assertEqual(backtest(data,cfg)['trades'],[])
        data=series();data['interval']='minute';data['sessions']=['2026-10-21']
        for i,bar in enumerate(data['bars']):
            bar.update(time=f'2026-10-21T09:{31+i:02d}:00+08:00',open_at=f'2026-10-21T09:{30+i:02d}:00+08:00',available_at=f'2026-10-21T09:{31+i:02d}:00+08:00')
        data['bars'][2]['open_at']='2026-10-20T23:32:00-02:00'
        data['expected_bar_times']=[b['time'] for b in data['bars']]
        result=backtest(data,self.config())
        self.assertEqual([t['side'] for t in result['trades']],['buy'])
        self.assertTrue(any(o['reason']=='t_plus_one' for o in result['orders']))

    def test_exact_budget_uses_actual_maximum_commission_and_none_time_is_incomplete(self):
        data=series();data['bars'][2].update(open='10',low='9')
        cfg=self.config().model_copy(update={'initial_cash':'1005','commission_rate':'0.0003'})
        result=backtest(data,cfg)
        self.assertEqual(result['trades'][0]['quantity'],'100');self.assertEqual(result['trades'][0]['cash_after'],'0')
        data['bars'][0]['time']=None
        self.assertEqual(backtest(data,self.config())['status'],'incomplete')

    def test_large_dividend_cannot_crash_internal_metric_parsing(self):
        data=series();data['bars'][3]['cash_dividend']='9999999999999999999'
        result=backtest(data,self.config())
        self.assertEqual(result['status'],'complete');self.assertIsNone(result['metrics']['annualized_return_pct'])

    def config(self,**values):
        return BacktestConfig(initial_cash='10000',quantity='100',strategy='threshold',entry_above='10',exit_below='10',
            commission_rate='0',minimum_commission='5',sell_tax_rate='0.0005',slippage_bps='0',max_participation='1',**values)

    def test_next_open_round_trip_matches_cash_fees_and_realized_result(self):
        result=backtest(series(),self.config())
        self.assertEqual(result['status'],'complete')
        self.assertEqual([t['side'] for t in result['trades']],['buy','sell'])
        self.assertEqual([t['price'] for t in result['trades']],['12','8'])
        self.assertEqual(result['final_cash'],'9589.6');self.assertEqual(result['metrics']['net_profit'],'-410.4')
        self.assertEqual(result['metrics']['closed_round_trips'],1)
        self.assertEqual(result['trades'][0]['signal_at'],'2026-10-20T15:01:00+08:00')

    def test_future_suffix_cannot_change_earlier_trades(self):
        data=series();before=backtest(data,self.config())
        data['bars'][-1].update(close='50',high='51')
        after=backtest(data,self.config())
        self.assertEqual(before['trades'][:1],after['trades'][:1])

    def test_missing_rules_and_calendar_do_not_produce_performance(self):
        for change in ('limit_up','corporate_actions_known','available_at'):
            data=series();data['bars'][2].pop(change)
            result=backtest(data,self.config());self.assertEqual(result['status'],'incomplete');self.assertIsNone(result['metrics'])
        data=series();data['bars'].pop(2)
        self.assertEqual(backtest(data,self.config())['status'],'incomplete')

    def test_limit_up_volume_and_late_signal_prevent_execution(self):
        for field,value,reason in [('limit_up','12','limit_up'),('volume_shares','0','no_volume'),('open_at','2026-10-20T15:00:00+08:00','signal_not_known')]:
            data=series();data['bars'][2][field]=value
            result=backtest(data,self.config())
            self.assertTrue(any(reason in r['reason'] for r in result['orders']),result)
            self.assertFalse(any(t['time']==data['bars'][2]['open_at'] for t in result['trades']))

    def test_same_day_sale_is_blocked_and_open_position_is_not_forced_closed(self):
        data=series();data['interval']='minute';data['sessions']=['2026-10-19']
        for i,bar in enumerate(data['bars']):
            bar.update(time=f'2026-10-19T10:{i+1:02d}:00+08:00',open_at=f'2026-10-19T10:{i:02d}:00+08:00',available_at=f'2026-10-19T10:{i+1:02d}:00+08:00')
        data['expected_bar_times']=[b['time'] for b in data['bars']]
        result=backtest(data,self.config())
        self.assertEqual([t['side'] for t in result['trades']],['buy'])
        self.assertTrue(any(r['reason']=='t_plus_one' for r in result['orders']))
        self.assertEqual(result['open_quantity'],'100')
