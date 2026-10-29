"""A hypothetical bracket cannot bypass timing, liquidity or selling restrictions."""
import unittest
from investments.execution import execute_scenario


def bar(start,open='10',high='10.5',low='9.5',close='10',volume='10000'):
    from investments.replay import stamp
    from datetime import timedelta
    return {'start':start,'end':(stamp(start)+timedelta(minutes=1)).isoformat(),
        'open':open,'high':high,'low':low,'close':close,'volume_shares':volume}

class ExecutionModelTests(unittest.TestCase):
    def setUp(self):
        self.bars=[bar('2026-10-27T14:59:00+08:00'),bar('2026-10-28T09:30:00+08:00',open='11',high='12',low='10.5',close='11')]
        self.check={'price_tick':'0.01','quantity_step':'100','minimum_quantity':'100','sell_delay_sessions':1,
            'rules_valid_from':'2026-10-27','rules_valid_until':'2026-10-28','sessions':{'2026-10-27':True,'2026-10-28':True}}
        self.rules={day:{'status':'normal','limit_down':'8','limit_up':'13','corporate_action':'none_declared',
            'available_at':day+'T08:00:00+08:00'} for day in self.check['sessions']}
        self.params={'decision_at':'2026-10-27T14:58:00+08:00','evidence_available_at':'2026-10-27T14:57:00+08:00',
            'cash':'10000','quantity':'100','stop_price':'9','target_price':'11','commission_bps':'0','minimum_commission':'1',
            'sell_tax_bps':'0','slippage_bps':'0','participation_rate':'0.1'}

    def run_model(self):return execute_scenario(self.bars,self.check,self.rules,self.params)

    def test_cross_day_exact_costs_and_adverse_tick_slippage(self):
        r=self.run_model();self.assertEqual(r['status'],'closed');self.assertEqual(r['net_realized'],'98')
        self.assertEqual(r['cash'],'10098');self.assertEqual(r['remaining_quantity'],'0')
        self.params.update(slippage_bps='1',sell_tax_bps='10')
        r=self.run_model();self.assertEqual(r['fills'][0]['price'],'10.01');self.assertEqual(r['fills'][1]['price'],'10.99')
        self.assertEqual(r['net_realized'],'94.9')  # 1099 -1 -1.10 -1001 -1

    def test_same_bar_double_touch_chooses_stop_and_t_plus_one_is_not_assumed_for_etf(self):
        self.bars=[bar('2026-10-27T14:59:00+08:00',high='12',low='8.5')];self.check['sell_delay_sessions']=0
        r=self.run_model();self.assertEqual(r['net_realized'],'-102');self.assertIn('same_bar_stop_first',[e['reason'] for e in r['events']])
        self.check['sell_delay_sessions']=1;r=self.run_model();self.assertEqual(r['status'],'open');self.assertIsNone(r['net_realized'])
        self.assertEqual(len(r['fills']),1)
        self.check['sell_delay_sessions']=None;r=self.run_model();self.assertEqual(r['status'],'unresolved');self.assertIsNone(r['net_realized'])

    def test_down_limit_and_halt_do_not_invent_exit_and_delisting_is_unresolved(self):
        self.bars[1]=bar('2026-10-28T09:30:00+08:00',open='8',high='8',low='8',close='8')
        r=self.run_model();self.assertEqual(r['status'],'open');self.assertEqual(len(r['fills']),1)
        self.assertIn('limit_queue_unknown',[e['reason'] for e in r['events']])
        self.rules['2026-10-28']['status']='halted';r=self.run_model();self.assertEqual(len(r['fills']),1)
        self.rules['2026-10-28']['status']='delisted';r=self.run_model();self.assertEqual(r['status'],'unresolved')
        self.assertEqual(r['remaining_quantity'],'100');self.assertIsNone(r['net_realized'])

    def test_unknown_action_late_evidence_and_missing_minutes_do_not_generate_profit(self):
        self.params['evidence_available_at']='2026-10-27T14:59:00+08:00'
        self.assertEqual(self.run_model()['status'],'future_information')
        self.params['evidence_available_at']='2026-10-27T14:57:00+08:00'
        self.rules['2026-10-28']['corporate_action']='unknown'
        self.assertEqual(self.run_model()['status'],'unresolved')
        self.rules['2026-10-28']['corporate_action']='none_declared'
        self.bars[1]=bar('2026-10-28T09:31:00+08:00',open='11',high='12',low='10.5',close='11')
        r=self.run_model();self.assertEqual(r['status'],'unresolved');self.assertIsNone(r['net_realized'])
        self.assertIn('missing_held_minutes',[e['reason'] for e in r['events']])

    def test_participation_partial_exit_and_minimum_fee_are_applied_per_fill(self):
        self.bars[1]['volume_shares']='1000';self.params['quantity']='200'
        self.bars.append(bar('2026-10-28T09:31:00+08:00',open='11',high='12',low='10.5',close='11'))
        r=self.run_model();self.assertEqual([f['quantity'] for f in r['fills']],['200','100','100'])
        self.assertEqual(r['net_realized'],'197');self.assertEqual(r['commission_total'],'3')
        self.params['cash']='999';r=self.run_model();self.assertEqual(r['status'],'entry_unfilled');self.assertEqual(r['fills'],[])

    def test_next_bar_only_known_limits_rules_and_no_same_instant_decision_fill(self):
        self.params['decision_at']=self.bars[0]['start'];r=self.run_model()
        self.assertEqual(r['fills'][0]['at'],self.bars[1]['start'])
        self.rules['2026-10-28']['available_at']='2026-10-28T10:00:00+08:00'
        self.assertEqual(self.run_model()['status'],'unresolved')

    def test_t_plus_one_stop_intent_survives_and_same_bar_volume_is_shared(self):
        self.bars[0].update(high='12',low='8.5')
        self.bars[1]=bar('2026-10-28T09:30:00+08:00',open='8.5',high='9',low='8.5',close='9')
        r=self.run_model();self.assertEqual(r['net_realized'],'-152')
        self.assertEqual(r['fills'][1]['reason'],'pending_stop')
        self.check['sell_delay_sessions']=0;self.bars=self.bars[:1];self.bars[0]['volume_shares']='1000'
        r=self.run_model();self.assertEqual(len(r['fills']),1);self.assertEqual(r['status'],'open')
        self.assertIn('volume_unfilled',[e['reason'] for e in r['events']])

    def test_halt_gap_needs_timely_declaration_and_target_touch_is_not_a_fill(self):
        self.bars[1]['high']='11'
        self.assertEqual(self.run_model()['status'],'open')
        self.check['sessions']['2026-10-29']=True;self.check['rules_valid_until']='2026-10-29'
        self.rules['2026-10-28']['status']='halted'
        self.rules['2026-10-29']={**self.rules['2026-10-27'],'available_at':'2026-10-29T08:00:00+08:00'}
        self.bars[1]=bar('2026-10-29T09:30:00+08:00',open='11',high='12',low='10.5',close='11')
        self.assertEqual(self.run_model()['net_realized'],'98')
        self.rules['2026-10-28']['available_at']='2026-10-29T08:00:00+08:00'
        self.assertEqual(self.run_model()['status'],'unresolved')

    def test_missing_next_entry_minute_cannot_skip_forward_to_a_later_winner(self):
        self.params['decision_at']='2026-10-27T14:57:00+08:00'
        self.params['evidence_available_at']='2026-10-27T14:56:00+08:00'
        r=self.run_model();self.assertEqual(r['status'],'unresolved');self.assertEqual(r['fills'],[])
        self.assertIn('missing_entry_minute',[e['reason'] for e in r['events']])

    def test_order_maximum_is_applied_before_fees_and_quantity_is_not_expanded(self):
        self.check['maximum_quantity']='100';self.params['quantity']='200'
        r=self.run_model();self.assertEqual(r['fills'][0]['quantity'],'100');self.assertEqual(r['net_realized'],'98')
