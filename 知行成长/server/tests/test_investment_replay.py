"""Retrospective minute paths never borrow extremes outside actual exposure."""
from unittest.mock import patch
from copilot.core import Problem
from investments.store import InvestmentStore
from investments.replay import import_path, replay_campaign
from test_legacy_cloud_schema import PostgreSQLFixture

NOW='2026-10-28T09:00:00+08:00'
HEADER='start,open,high,low,close,volume,amount\n'

class InvestmentReplayTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp();self.store=InvestmentStore();self.store.initialize()
        clock=patch('investments.replay.now',return_value=NOW);clock.start();self.addCleanup(clock.stop)
        self.a=self.store.create('accounts',{'name':'路径验收','baseline_date':'2026-10-26','opening_cash':'10000'},'a')
        self.i=self.store.create('instruments',{'name':'合成股票','market':'SSE','kind':'stock','code':'600000'},'i')

    def fill(self,side,qty,price,at,key,fee='1'):
        return self.store.create('fills',{'account_id':self.a['id'],'instrument_id':self.i['id'],'side':side,
            'price':price,'quantity':qty,'fee':fee,'tax':'0','executed_at':'2026-10-27T'+at+':00+08:00'},key)

    def path(self,rows,key='path',**extra):
        return import_path(self.store,{'account_id':self.a['id'],'instrument_id':self.i['id'],
            'text':HEADER+rows,'source_label':'合成分钟CSV，仅验收','volume_unit':'shares','amount_unit':'cny',
            'price_basis':'unadjusted','use_confirmed':True,**extra},key)

    def replay(self,path,cutoff=NOW):
        campaign=self.store.campaigns(self.a['id'])[0]
        return replay_campaign(self.store,self.a['id'],campaign['id'],path['id'],cutoff)

    def test_complete_path_excludes_pre_entry_extreme_and_keeps_exact_fees(self):
        self.fill('buy','100','10','10:00','buy');self.fill('sell','100','11','10:02','sell')
        path=self.path('2026-10-27T09:59:00+08:00,10,999,1,10,1000,10000\n'
            '2026-10-27T10:00:00+08:00,10,10.5,9.5,10.2,1000,10000\n'
            '2026-10-27T10:01:00+08:00,10.2,11,10,11,1000,10000\n')
        result=self.replay(path)
        self.assertEqual(result['status'],'complete_declared_path')
        self.assertEqual(result['mae_cash'],'-51');self.assertEqual(result['mfe_cash'],'99')
        self.assertEqual(result['actual_net_realized'],'98')
        self.assertEqual(result['coverage']['expected_minutes'],2)
        self.assertEqual(len(result['rows']),2)
        self.assertFalse(result['realtime']);self.assertTrue(result['retrospective'])
        self.assertEqual(self.path('2026-10-27T09:59:00+08:00,10,999,1,10,1000,10000\n'
            '2026-10-27T10:00:00+08:00,10,10.5,9.5,10.2,1000,10000\n'
            '2026-10-27T10:01:00+08:00,10.2,11,10,11,1000,10000\n',key='retry')['id'],path['id'])

    def test_missing_or_inside_bar_fill_returns_observed_bounds_not_exact_extrema(self):
        self.fill('buy','100','10','10:00','buy');self.fill('sell','100','11','10:03','sell')
        path=self.path('2026-10-27T10:00:00+08:00,10,11,9,10,1000,10000\n')
        result=self.replay(path)
        self.assertIsNone(result['mae_cash']);self.assertEqual(result['coverage']['missing_minutes'],2)
        self.assertEqual(result['observed_mae_cash'],'-101')
        # At 10:01:30 the quantity changes within the bar, so that bar is unusable.
        self.store.create('fills',{'account_id':self.a['id'],'instrument_id':self.i['id'],'side':'buy','price':'10',
            'quantity':'100','fee':'1','tax':'0','executed_at':'2026-10-27T10:01:30+08:00'},'inside')
        second=self.path('2026-10-27T10:00:00+08:00,10,11,9,10,1000,10000\n'
            '2026-10-27T10:01:00+08:00,10,100,1,10,1000,10000\n'
            '2026-10-27T10:02:00+08:00,10,11,9,10,1000,10000\n',key='second')
        result=self.replay(second,cutoff='2026-10-27T10:03:00+08:00')
        self.assertEqual(result['coverage']['boundary_minutes'],1)
        self.assertIsNone(result['mfe_cash'])
        self.assertNotIn('100',[r['high'] for r in result['rows']])

    def test_partial_exit_and_reentry_use_remaining_quantity_and_cost(self):
        self.fill('buy','100','10','10:00','b1');self.fill('buy','100','12','10:01','b2')
        self.fill('sell','100','13','10:02','partial');self.fill('sell','100','12','10:03','last')
        path=self.path('2026-10-27T10:00:00+08:00,10,11,9,10,1000,10000\n'
            '2026-10-27T10:01:00+08:00,12,13,11,12,1000,12000\n'
            '2026-10-27T10:02:00+08:00,13,14,12,12,1000,12000\n')
        result=self.replay(path)
        self.assertEqual([r['quantity'] for r in result['rows']],['100','200','100'])
        self.assertEqual(result['rows'][-1]['cost'],'1101')
        self.assertEqual(result['rows'][-1]['upper_pnl'],'497')
        self.assertEqual(result['actual_net_realized'],'296')
        cutoff=self.replay(path,'2026-10-27T10:01:00+08:00')
        self.assertEqual(len(cutoff['rows']),1)
        self.assertEqual(cutoff['actual_fill_count'],2)
        self.assertTrue(cutoff['open_at_cutoff'])

    def test_wrong_scope_adjustment_holiday_future_and_unknown_fees_fail_closed(self):
        self.fill('buy','100','10','10:00','buy',fee=None);self.fill('sell','100','11','10:01','sell')
        path=self.path('2026-10-27T10:00:00+08:00,10,11,9,10,1000,10000\n')
        self.assertIsNone(self.replay(path)['mfe_cash'])
        for text in ('2026-10-29T10:00:00+08:00,10,11,9,10,1000,10000\n',
                     '2026-10-01T10:00:00+08:00,10,11,9,10,1000,10000\n',
                     '2026-10-27T12:00:00+08:00,10,11,9,10,1000,10000\n'):
            with self.assertRaises(Problem):self.path(text,key='invalid'+str(len(text)))
        with self.assertRaises(Problem):self.path('2026-10-27T10:00:00+08:00,10,11,9,10,1000,10000\n',price_basis='forward_adjusted')
        other=self.store.create('accounts',{'name':'其他','baseline_date':'2026-10-26','opening_cash':'1000'},'other')
        with self.assertRaises(Problem):
            replay_campaign(self.store,other['id'],self.store.campaigns(self.a['id'])[0]['id'],path['id'],NOW)

    def test_conflicting_path_never_overwrites_known_realized_ledger_result(self):
        self.fill('buy','100','10','10:00','buy');self.fill('sell','100','11','10:01','sell')
        path=self.path('2026-10-27T10:00:00+08:00,11,12,11,12,1000,10000\n')
        result=self.replay(path)
        self.assertEqual(result['fact_conflict_count'],1)
        self.assertIsNone(result['mae_cash']);self.assertIsNone(result['observed_mfe_cash'])
        self.assertEqual(result['actual_net_realized'],'98')
        self.assertEqual(result['rows'][0]['cost'],'1001')
