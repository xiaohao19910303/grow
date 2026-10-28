"""Declared offline observations must degrade before producing simulated reminders."""
import unittest
from investments.conditions import ConditionInput, evaluate_tick

class ConditionTickTests(unittest.TestCase):
    def setUp(self):
        self.rule=ConditionInput.model_validate({'account_id':'a','path_id':'p','check_id':'c','title':'核对',
            'op':'gte','threshold':'10','intent':'observe','valid_from':'2026-10-27T09:30:00+08:00',
            'valid_until':'2026-10-28T15:00:00+08:00','max_age_seconds':60,'arrival_delay_seconds':0,
            'notification_scope':'page','acknowledged':True}).model_dump(mode='json')
        self.check={'sessions':{'2026-10-26':True,'2026-10-27':True,'2026-10-28':True},
            'rules_valid_from':'2026-10-26','rules_valid_until':'2026-10-28',
            'trading_status':'normal','sell_delay_sessions':1}
        self.seen=set()

    def tick(self,at='2026-10-27T10:01:00+08:00',quote_at='2026-10-27T10:01:00+08:00',price='10',**kw):
        return evaluate_tick(self.rule,self.check,{'rules_available':True,'conflicts':False},
            at,{'as_of':quote_at,'price':price,'volume':'1000'},self.seen,**kw)

    def test_only_first_match_per_session_is_a_simulated_page_candidate(self):
        self.assertEqual(self.tick(price='9')['status'],'not_met')
        first=self.tick();self.assertEqual(first['status'],'matched');self.assertTrue(first['page_candidate'])
        self.assertFalse(first['realtime']);self.assertFalse(first['executable'])
        self.assertEqual(self.tick()['status'],'duplicate_suppressed')
        self.tick(price='9');self.assertEqual(self.tick()['status'],'duplicate_suppressed')
        self.assertEqual(self.tick(at='2026-10-28T10:01:00+08:00',quote_at='2026-10-28T10:01:00+08:00')['status'],'matched')

    def test_stale_future_break_closed_expired_and_unknown_do_not_consume_dedup(self):
        for at,quote,status in [('2026-10-27T10:02:01+08:00','2026-10-27T10:01:00+08:00','stale'),
            ('2026-10-27T10:00:59+08:00','2026-10-27T10:01:00+08:00','future_quote'),
            ('2026-10-27T12:00:00+08:00','2026-10-27T11:29:00+08:00','outside_session'),
            ('2026-10-29T10:01:00+08:00','2026-10-29T10:01:00+08:00','expired')]:
            self.assertEqual(self.tick(at=at,quote_at=quote)['status'],status)
        self.check['sessions']['2026-10-27']=False;self.assertEqual(self.tick()['status'],'closed_session')
        del self.check['sessions']['2026-10-27'];self.assertEqual(self.tick()['status'],'calendar_unknown')
        self.check['sessions']['2026-10-27']=True;self.check['trading_status']='unknown'
        self.assertEqual(self.tick()['status'],'trading_status_unknown')
        self.assertEqual(self.seen,set())

    def test_declared_t_plus_one_and_unverified_etf_mechanism(self):
        self.rule.update(intent='exit',assumed_bought_on='2026-10-27')
        self.assertEqual(self.tick()['status'],'sell_delay')
        self.assertEqual(self.tick(at='2026-10-28T10:01:00+08:00',quote_at='2026-10-28T10:01:00+08:00')['status'],'matched')
        self.seen.clear();self.check['sell_delay_sessions']=None
        self.assertEqual(self.tick()['status'],'sell_rule_unknown')
        self.check['sell_delay_sessions']=0;self.assertEqual(self.tick()['status'],'matched')
        # This is only an explicit hypothetical T+0; no actual sellable quantity is asserted.
        self.assertFalse(self.tick()['executable'])

    def test_no_notification_scope_still_records_match_and_gates_are_fail_closed(self):
        self.rule['notification_scope']='none';self.assertFalse(self.tick()['page_candidate'])
        self.assertEqual(evaluate_tick(self.rule,self.check,{'rules_available':False,'conflicts':False},
            '2026-10-27T10:01:00+08:00',None,set())['status'],'rules_unknown')
        self.assertEqual(evaluate_tick(self.rule,self.check,{'rules_available':True,'conflicts':True},
            '2026-10-27T10:01:00+08:00',None,set())['status'],'rule_conflict')

    def test_zero_volume_and_reference_expiry_do_not_generate_candidates(self):
        at='2026-10-27T10:01:00+08:00'
        quote={'as_of':at,'price':'10','volume':'0'}
        reference={'rules_available':True,'conflicts':False,'valid_until':'2026-10-26'}
        self.assertEqual(evaluate_tick(self.rule,self.check,reference,at,quote,self.seen)['status'],'rules_expired')
        reference['valid_until']='2026-10-28'
        self.assertEqual(evaluate_tick(self.rule,self.check,reference,at,quote,self.seen)['status'],'no_trades')
        self.assertEqual(self.seen,set())
