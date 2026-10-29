"""Browser execution handoff on disposable PostgreSQL; never call a real model."""
import copy
import json
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import db
from fastapi import FastAPI
from fastapi.testclient import TestClient
from investments.api import register
from investments.analysis import InvestmentAnalysis
from investments.market_import import import_history
from test_legacy_cloud_schema import PostgreSQLFixture


class InvestmentBrowserTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        self.app = FastAPI();self.store = register(self.app);self.store.initialize()
        self.client = TestClient(self.app);self.addCleanup(self.client.close)
        self.account = self.store.create('accounts', {'name':'private','baseline_date':'2026-10-26','opening_cash':'1000'}, 'account')
        self.instrument = self.store.create('instruments', {'name':'Synthetic ETF','code':'510000','market':'SSE','kind':'etf'}, 'instrument')
        text = 'date,open,high,low,close,volume,amount\n2026-10-26,10,12,9,11,100,1100\n'
        self.market = import_history(self.store, self.instrument['id'], text, 'shares', 'cny', 'Synthetic', True, 'market', self.account['id'])
        self.owner = 'browser-executor-owner'
        self.body = {'account_id':self.account['id'], 'instrument_ids':[self.instrument['id']], 'model':'browser-test',
                     'question':'只核对所选资料', 'executor':self.owner,
                     'screen':{'as_of':'2026-10-26','conditions':[],'limit':1}}
        self.mock = patch('copilot.transport.qwen_stream', side_effect=AssertionError('Remote model must never be called'))
        self.mock.start();self.addCleanup(self.mock.stop)

    def post(self, path, body, key='browser-create-key', expected=200):
        response = self.client.post('/api/investments/'+path, json=body,
                                    headers={'X-Copilot-Request':'1','Idempotency-Key':key})
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def get(self, path):
        response = self.client.get('/api/investments/'+path, headers={'X-Local-Executor':self.owner})
        self.assertEqual(response.status_code, 200, response.text);return response.json()

    def create(self):return self.post('local-runs', self.body)

    def screening(self, run):
        return {'algorithm':'browser-screen-rational-v1','executor':self.owner,'input_hash':run['input_hash'],
                'total':1,'unresolved':0,'items':[{'instrument_id':self.instrument['id'],'data_date':'2026-10-26',
                    'condition_results':[], 'values':{'market':'SSE','kind':'etf','name':'Synthetic ETF',
                        'close':'11','turnover_cny':'1100','close_change_pct':None,'volume_ratio_5':None,'price_above_ma20':None}}]}

    def started(self):
        run = self.create();self.post('local-runs/'+run['id']+'/screening', self.screening(run), 'screen-key')
        job = self.post('local-runs/'+run['id']+'/candidates/'+self.instrument['id'], {'executor':self.owner}, 'candidate-key')
        return run, job

    def output(self, input, quote=None):
        snapshot = json.loads(input['evidence']['messages'][1]['content'])['snapshot']
        evidence = snapshot['evidence'][0]
        raw = json.dumps({'summary':'Only a synthetic review','facts':[{'evidence_id':evidence['id'],
            'quote':quote or evidence['content'][:40]}], 'counterarguments':['Missing fundamentals'], 'suggestions':[]})
        return {'executor':self.owner,'input_hash':input['evidence']['input_hash'],'raw':raw}

    def test_full_browser_two_pass_and_existing_report_without_remote_model(self):
        with (patch('investments.screening.filter_snapshots',side_effect=AssertionError('No remote screening')),
              patch('investments.providers.indicators',side_effect=AssertionError('No remote indicators'))):
            run, job = self.started()
            first = self.get('local-jobs/'+job['id']+'/input')
            self.assertEqual(first['stage'], 'analysis')
            self.assertEqual(first['evidence']['model'], 'browser-test')
            draft = self.output(first)
            self.post('local-jobs/'+job['id']+'/draft', draft, 'draft-key')
            second = self.get('local-jobs/'+job['id']+'/input')
            self.assertEqual(second['stage'], 'countercheck')
            self.assertEqual(second['evidence']['parent_id'], first['evidence']['id'])
            report = self.post('local-jobs/'+job['id']+'/result', self.output(second), 'result-key')
        self.assertEqual(report['state'], 'ready')
        self.assertEqual(report['execution_location'], 'browser')
        self.assertEqual(self.get('analysis/jobs/'+job['id'])['report'], report['report'])
        self.assertEqual(self.get('local-runs/'+run['id'])['state'], 'ready')
        self.assertNotIn('owner_hash', json.dumps(report))
        self.assertFalse(self.get('local-runs/'+run['id'])['full_market'])

    def test_create_replay_concurrency_scope_and_no_credentials(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            runs = list(pool.map(lambda _: self.create(), range(2)))
        self.assertEqual(runs[0]['id'], runs[1]['id'])
        self.assertEqual(self.get('local-runs')['total'], 1)
        bad = copy.deepcopy(self.body);bad['question'] = 'changed'
        self.post('local-runs',bad,expected=409)
        bad = copy.deepcopy(self.body);bad['api_key'] = 'PRIVATE_KEY_NEVER_SAVE'
        result = self.post('local-runs',bad,'bad-secret',422)
        self.assertNotIn('PRIVATE_KEY_NEVER_SAVE', json.dumps(result))
        bad = copy.deepcopy(self.body);bad['instrument_ids'] = ['not-this-account']
        self.post('local-runs',bad,'bad-scope',404)

    def test_input_is_immutable_after_source_edit_and_delete(self):
        run = self.create();before = self.get('local-runs/'+run['id']+'/inputs')
        with db.connect() as c:
            c.execute("DELETE FROM investment_versions WHERE object_id=?", (self.market['snapshot_id'],))
            c.execute("DELETE FROM investment_objects WHERE id=?", (self.market['snapshot_id'],))
            changed = {**self.instrument, 'name':'changed externally', 'version':2}
            c.execute('UPDATE investment_objects SET data=?,version=2 WHERE id=?', (json.dumps(changed),self.instrument['id']))
        self.assertEqual(self.get('local-runs/'+run['id']+'/inputs')['bundle'], before['bundle'])
        self.post('local-runs/'+run['id']+'/screening', self.screening(run), 'after-delete')

    def test_invalid_screening_rolls_back_and_owner_cannot_be_replaced(self):
        run = self.create();body = self.screening(run)
        body['items'][0]['values']['close'] = '999'
        self.post('local-runs/'+run['id']+'/screening',body,'bad-screen',422)
        self.assertEqual(self.get('local-runs/'+run['id'])['state'], 'awaiting_browser')
        body = self.screening(run);body['executor'] = 'another-browser-owner'
        self.post('local-runs/'+run['id']+'/screening',body,'wrong-owner',409)
        self.post('local-runs/'+run['id']+'/screening',self.screening(run),'bad-screen')

    def test_stage_replay_wrong_hash_and_literal_validation(self):
        run, job = self.started();first = self.get('local-jobs/'+job['id']+'/input');body = self.output(first)
        draft = self.post('local-jobs/'+job['id']+'/draft',body,'draft-once')
        self.assertEqual(self.post('local-jobs/'+job['id']+'/draft',body,'draft-once'),draft)
        second = self.get('local-jobs/'+job['id']+'/input')
        wrong = self.output(second);wrong['input_hash'] = first['evidence']['input_hash']
        self.post('local-jobs/'+job['id']+'/result',wrong,'wrong-hash',409)
        self.post('local-jobs/'+job['id']+'/result',self.output(second,'invented evidence'),'invalid-citation',422)
        final = self.output(second);saved = self.post('local-jobs/'+job['id']+'/result',final,'saved-once')
        self.assertEqual(self.post('local-jobs/'+job['id']+'/result',final,'saved-once'),saved)
        final['raw'] += ' '
        self.post('local-jobs/'+job['id']+'/result',final,'saved-once',409)

    def test_cancel_and_server_restart_never_restart_local_jobs(self):
        run, job = self.started()
        first = self.get('local-jobs/'+job['id']+'/input')
        another = InvestmentAnalysis(self.store);another.initialize()
        self.assertEqual(another.get(job['id'])['state'], 'queued')
        self.post('local-runs/'+run['id']+'/cancel',{},'cancel')
        self.post('local-jobs/'+job['id']+'/draft',self.output(first),'late-output',409)
        self.assertEqual(another.get(job['id'])['state'], 'cancelled')

    def test_report_and_receipt_failure_roll_back_together(self):
        run, job = self.started();first = self.get('local-jobs/'+job['id']+'/input')
        with db.connect() as c:
            c.execute("ALTER TABLE investment_requests ADD CONSTRAINT reject_browser_receipt CHECK(request_key!='reject-output')")
        body = self.output(first)
        self.post('local-jobs/'+job['id']+'/draft',body,'reject-output',503)
        self.assertEqual(self.get('local-jobs/'+job['id']+'/input')['stage'], 'analysis')
        with db.connect() as c:c.execute('ALTER TABLE investment_requests DROP CONSTRAINT reject_browser_receipt')
        self.post('local-jobs/'+job['id']+'/draft',body,'reject-output')

    def test_cancel_races_with_final_commit_without_resurrecting_cancelled_job(self):
        run,job=self.started();first=self.get('local-jobs/'+job['id']+'/input')
        self.post('local-jobs/'+job['id']+'/draft',self.output(first),'race-draft')
        second=self.get('local-jobs/'+job['id']+'/input');body=self.output(second)
        def finish():return self.client.post('/api/investments/local-jobs/'+job['id']+'/result',json=body,
            headers={'X-Copilot-Request':'1','Idempotency-Key':'race-result'}).status_code
        def cancel():return self.client.post('/api/investments/local-runs/'+run['id']+'/cancel',json={},headers={'X-Copilot-Request':'1'}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda f:f(),(finish,cancel)))
        self.assertIn(results[0],(200,409));self.assertEqual(results[1],200)
        final=self.get('analysis/jobs/'+job['id'])
        self.assertEqual(final['state'],'ready' if results[0]==200 else 'cancelled')

    def test_browser_screen_matches_existing_contract_on_regular_and_missing_inputs(self):
        from investments.screening import filter_snapshots, ScreenInput
        universe=[]
        for index in range(3):
            universe.append({'instrument_id':str(index),'name':'Synthetic '+str(index),'code':'51000'+str(index),'kind':'etf','market':'SSE',
                'bars':[{'date':'2026-10-'+str(day).zfill(2),'close':str(10+day+index),
                         'turnover_cny':str((index+1)*1000),'volume_shares':str(100+day+index)} for day in range(1,22 if index<2 else 3)]})
        script="const fs=require('node:fs');eval(fs.readFileSync('static/investment-browser-core.js','utf8'));process.stdout.write(JSON.stringify(InvestmentBrowserCore.screen(JSON.parse(fs.readFileSync(0,'utf8')))));"
        for condition in ({'field':'volume_ratio_5','op':'gte','value':'1.02'}, {'field':'price_above_ma20','op':'eq','value':'true'},
                          {'field':'close_change_pct','op':'lt','value':'4'}):
            for combine in ('all','any'):
                request=ScreenInput(as_of='2026-10-26',conditions=[condition],combine=combine,limit=5)
                packet={'algorithm':'browser-screen-rational-v1','universe':universe,'request':request.model_dump(mode='json')}
                browser=json.loads(subprocess.run(['node','-e',script],input=json.dumps(packet),text=True,capture_output=True,check=True,cwd=Path(__file__).resolve().parents[1]).stdout)
                existing=filter_snapshots(universe,request)
                for field in ('total','unresolved'):self.assertEqual(browser[field],existing[field])
                self.assertEqual([i['instrument_id'] for i in browser['items']],[i['instrument_id'] for i in existing['items']])

    def test_uncertain_browser_call_is_visible_and_never_automatically_restarted(self):
        run,job=self.started()
        self.post('local-jobs/'+job['id']+'/pause',{'executor':self.owner,'status':'call_uncertain'},'pause')
        self.assertEqual(self.get('analysis/jobs/'+job['id'])['state'],'interrupted')
        self.assertEqual(self.get('local-runs/'+run['id'])['state'],'partial')
        response=self.client.get('/api/investments/local-jobs/'+job['id']+'/input',headers={'X-Local-Executor':self.owner})
        self.assertEqual(response.status_code,409)

    def test_browser_preview_cannot_be_submitted_to_remote_model_and_does_not_block_old_flow(self):
        from copilot.core import Problem
        run,job=self.started();analysis=InvestmentAnalysis(self.store)
        config={'model':'browser-test','url':'https://model.invalid/v1','key':'test-only'}
        with self.assertRaises(Problem) as rejected:
            analysis._prepare(job['preview_id'],job['snapshot_hash'],config,'forbid-remote-browser')
        self.assertEqual(rejected.exception.code,'browser_execution_only')
        preview=analysis.preview({'kind':'research','question':'Original manual research',
            'account_id':self.account['id'],'instrument_id':self.instrument['id'],
            'decision_at':'2099-01-01T00:00:00+08:00'})
        old,snapshot=analysis._prepare(preview['id'],preview['snapshot_hash'],config,'old-flow-with-browser')
        self.assertIsNotNone(snapshot);self.assertEqual(old['state'],'queued')
        self.assertNotEqual(old['id'],job['id'])
        self.assertEqual(self.get('local-jobs/'+job['id']+'/input')['stage'],'analysis')

    def test_task_center_cancel_is_reflected_in_batch_listing(self):
        run,job=self.started()
        self.post('analysis/jobs/'+job['id']+'/cancel',{},'task-center-cancel')
        listed=next(r for r in self.get('local-runs')['items'] if r['id']==run['id'])
        self.assertEqual(listed['state'],'partial')
        self.assertEqual(listed['job_states'][self.instrument['id']],'cancelled')
        self.assertEqual(listed['state'],self.get('local-runs/'+run['id'])['state'])

    def test_batch_and_snapshot_failure_do_not_leave_partial_creation(self):
        with db.connect() as c:
            c.execute("ALTER TABLE investment_requests ADD CONSTRAINT reject_browser_create CHECK(request_key!='reject-create')")
        self.post('local-runs',self.body,'reject-create',503)
        self.assertEqual(self.get('local-runs')['total'],0)
        with db.connect() as c:c.execute('ALTER TABLE investment_requests DROP CONSTRAINT reject_browser_create')
        self.post('local-runs',self.body,'reject-create')
        self.assertEqual(self.get('local-runs')['total'],1)

    def test_truncation_source_links_and_deleted_source_keep_model_input_unchanged(self):
        from history_sources import availability
        source=self.store.get('market-snapshots',self.market['snapshot_id'])
        bar=source['bars'][0]
        source['bars']=[{**bar,'date':'2026-10-'+str(day).zfill(2)} for day in range(6,27)]
        with db.connect() as c:c.execute('UPDATE investment_objects SET data=? WHERE id=?',(json.dumps(source),source['id']))
        run=self.create();result=self.screening(run)
        result['items'][0]['values'].update(close_change_pct='0',volume_ratio_5='1',price_above_ma20=False)
        self.post('local-runs/'+run['id']+'/screening',result,'clip-screen')
        job=self.post('local-runs/'+run['id']+'/candidates/'+self.instrument['id'],{'executor':self.owner},'clip-candidate')
        first=self.get('local-jobs/'+job['id']+'/input')
        origin=next(s for s in first['evidence']['sources'] if (s.get('origin') or {}).get('keys')==[source['id']])
        self.assertTrue(origin['truncated']);self.assertEqual(origin['target']['resource'],'market-snapshots')
        self.assertEqual(self.get('market-snapshots/'+source['id'])['id'],source['id'])
        with db.connect() as c:
            self.assertEqual(availability(c,origin),'unchanged')
            c.execute('DELETE FROM investment_versions WHERE object_id=?',(source['id'],))
            c.execute('DELETE FROM investment_objects WHERE id=?',(source['id'],))
            self.assertEqual(availability(c,origin),'deleted')
        self.assertEqual(self.get('local-jobs/'+job['id']+'/input')['evidence']['messages'],first['evidence']['messages'])
