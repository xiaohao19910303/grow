"""Exercise the production whole-site backup/restore wrapper with private investment data."""
import json
import unittest
from unittest.mock import patch
import db
import test_standalone_backup as fixture
from investments.store import InvestmentStore
from investments.analysis import InvestmentAnalysis
from copilot.core import encoded, digest, now


class InvestmentFullBackupTests(unittest.TestCase):
    setUp=fixture.StandaloneBackupTests.setUp
    database=fixture.StandaloneBackupTests.database
    drop=fixture.StandaloneBackupTests.drop
    gitcmd=fixture.StandaloneBackupTests.gitcmd
    create=fixture.StandaloneBackupTests.create

    def test_whole_site_manifest_and_restore_include_investment_sources_versions_and_jobs(self):
        from standalone_backup import restore, verify
        # The fixture owns this revision; source archives need no surrounding .git.
        self.env['GROW_REVISION']=self.sha
        original=db.connect
        def connect_to(dsn):
            return patch('db.connect',lambda *a,**kw:original(dsn+' options=-csearch_path=tenant_fixture',tenant=False))
        with connect_to(self.source):
            store=InvestmentStore();store.initialize()
            a=store.create('accounts',{'name':'PRIVATE INVESTMENT','opening_cash':'10000.001','baseline_date':'2026-10-26'},'a')
            i=store.create('instruments',{'name':'ETF','code':'510000','market':'SSE','kind':'etf'},'i')
            store.create('fills',{'account_id':a['id'],'instrument_id':i['id'],'side':'buy','price':'1.231','quantity':'1000',
                'fee':'1','tax':'0','executed_at':'2026-10-26T10:00:00+08:00'},'f')
            e=store.create('research',{'account_id':a['id'],'title':'PRIVATE SOURCE','content':'私人核对原文',
                'available_at':'2026-10-26T09:00:00+08:00'},'e')
            from investments.replay import import_path
            from investments.experiments import create_experiment,register_experiment
            from datetime import datetime,timedelta
            original_path='start,open,high,low,close,volume,amount\n2026-10-26T10:00:00+08:00,1.231,1.24,1.22,1.23,1000,1230\n'
            path=import_path(store,{'account_id':a['id'],'instrument_id':i['id'],'text':original_path,
                'source_label':'PRIVATE PATH','volume_unit':'shares','amount_unit':'cny','price_basis':'unadjusted','use_confirmed':True},'path')
            from investments.conditions import run_drill
            check=store.create('plan-checks',{'instrument_id':i['id'],'quote_price':'1.23','quote_as_of':'2026-10-26T15:00:00+08:00',
                'sessions':{'2026-10-26':True},'rules_valid_from':'2026-10-26','rules_valid_until':'2026-10-26',
                'price_tick':'0.001','quantity_step':'100','minimum_quantity':'100','sell_delay_sessions':1,'trading_status':'normal',
                'source_url':'https://example.com/declared','source_note':'PRIVATE CHECK','acknowledged':True},'check')
            drill=run_drill(store,{'account_id':a['id'],'path_id':path['id'],'check_id':check['id'],'title':'PRIVATE DRILL',
                'op':'gte','threshold':'1.23','valid_from':'2026-10-26T09:30:00+08:00',
                'valid_until':'2026-10-26T15:00:00+08:00','acknowledged':True},'drill')
            from investments.execution_studies import run_study
            study=run_study(store,{'account_id':a['id'],'path_id':path['id'],'check_id':check['id'],
                'title':'PRIVATE STUDY','decision_at':'2026-10-26T09:59:00+08:00','evidence_available_at':'2026-10-26T09:58:00+08:00',
                'cash':'10000','quantity':'100','stop_price':'1','target_price':'2','commission_bps':'0',
                'minimum_commission':'1','sell_tax_bps':'0','slippage_bps':'0','participation_rate':'0.1',
                'constraints_text':'date,status,limit_down,limit_up,available_at,corporate_action\n2026-10-26,normal,0.5,2,2026-10-26T08:00:00+08:00,none_declared\n',
                'source_note':'PRIVATE DECLARED CONSTRAINTS','acknowledged':True},'study')
            strategy=store.create('strategies',{'title':'PRIVATE TRIAL','entry_conditions':'合成条件','exit_conditions':'反例','validation_scope':'合成观察'},'strategy')
            strategy=store.transition('strategies',strategy['id'],1,'confirmed','strategy-confirm')
            start=datetime.fromisoformat(now())+timedelta(days=1)
            trial=create_experiment(store,{'account_id':a['id'],'strategy_id':strategy['id'],'strategy_version':strategy['version'],
                'title':'PRIVATE PROTOCOL','hypothesis':'先登记','counter_case':'可能无效','stop_condition':'资料缺失',
                'parameters':{'sessions':'2'},'cost_assumptions':'按实际费用','start_at':start.isoformat(),
                'end_at':(start+timedelta(days=7)).isoformat(),'sample_target':10,'additional_roundtrip_costs':['0','1']},'trial')
            trial=register_experiment(store,trial['id'],1,'trial-register')
            review=store.create('reviews',{'account_id':a['id'],'date':'2026-10-26','text':'PRIVATE ORIGINAL'},'r')
            store.update('reviews',review['id'],1,{'text':'PRIVATE AUDITED'},'edit')
            analysis=InvestmentAnalysis(store);analysis.initialize()
            preview=analysis.preview({'kind':'research','account_id':a['id'],'question':'核对引用',
                'evidence_ids':[e['id']],'decision_at':'2030-01-01T09:00:00+08:00'})
            job={'id':'backup-job','state':'ready','created_at':now(),'updated_at':now(),'preview_id':preview['id'],
                'snapshot_hash':preview['snapshot_hash'],'report':{'summary':'PRIVATE REPORT','suggestions':[]}}
            with db.connect() as c:c.execute('INSERT INTO investment_analysis_jobs VALUES (?,?,?,?)',('backup-job','ready',digest('fixture'),encoded(job)))
            before=store.export();balance=store.balance(a['id'])
        self.create();manifest=verify(self.backup)
        for table in ('investment_objects','investment_versions','investment_requests','investment_fills','investment_analysis_jobs'):
            self.assertIn('tenant_fixture.'+table,manifest['tables'])
            self.assertIn('tenant_fixture.'+table,manifest['row_hashes'])
        for private in ('PRIVATE INVESTMENT','PRIVATE SOURCE','PRIVATE REPORT'):
            self.assertNotIn(private,json.dumps(manifest))
        restore(self.target,self.backup,self.root/'investment-restored',env=self.env,writers_stopped=True)
        with connect_to(self.target):
            after=store.export()
            for key in ('objects','versions','analysis_jobs'):self.assertEqual(after[key],before[key])
            self.assertEqual(store.balance(a['id']),balance)
            self.assertEqual(store.get('research',e['id'])['evidence_hash'],e['evidence_hash'])
            self.assertEqual(store.get('intraday-paths',path['id'])['raw_text'],original_path)
            self.assertEqual(store.get('experiments',trial['id'])['protocol_hash'],trial['protocol_hash'])

            self.assertEqual(store.get('condition-drills',drill['id']),drill)
            self.assertEqual(store.get('execution-studies',study['id']),study)
