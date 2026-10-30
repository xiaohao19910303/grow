"""Archive state is independent of immutable business receipts and tenant/account scope."""
import json,os,tempfile,zipfile,io
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from investments.api import register
from test_legacy_cloud_schema import PostgreSQLFixture

class ResearchArchiveTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp();self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{'INVESTMENT_RESEARCH_ARCHIVE_ROOT':str(Path(self.tmp.name)/'archive')});self.env.start();self.addCleanup(self.env.stop)
        app=FastAPI();self.store=register(app);self.store.initialize();self.client=TestClient(app);self.addCleanup(self.client.close)
        self.account=self.store.create('accounts',{'name':'归档测试','baseline_date':'2026-10-28','opening_cash':'1234'},'archive-account')
    def post(self,path,body,key,status=201):
        r=self.client.post('/api/investments/research/'+path,json=body,headers={'X-Copilot-Request':'1','Idempotency-Key':key});self.assertEqual(r.status_code,status,r.text[:500]);return r.json()
    def dataset(self):
        return self.post('datasets',{'account_id':self.account['id'],'source_label':'合成CSV','market_date':'2026-10-28','use_confirmed':True,'rows':[{'code':'000001','name':'合成','values':{'close':'1.2300000001','pe':None}}]},'archive-dataset')
    def test_auto_archive_verified_download_and_replay_do_not_change_business_receipt(self):
        record=self.dataset();status=self.client.get('/api/investments/research/archives',params={'account_id':self.account['id']}).json();self.assertTrue(status['enabled']);self.assertEqual(status['items'][0]['state'],'ready')
        verified=self.post('archives/verify',{'account_id':self.account['id'],'object_id':record['id'],'version':1},'archive-verify',200);self.assertEqual(verified['state'],'ready')
        response=self.client.get('/api/investments/research/archives/'+record['id']+'/download',params={'account_id':self.account['id'],'version':1});self.assertEqual(response.status_code,200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            self.assertIn('bundle.json',z.namelist());self.assertTrue(any(n.endswith('rows.jsonl.gz') for n in z.namelist()))
        self.assertEqual(self.dataset(),record);self.assertEqual(self.store.balance(self.account['id'])['cash'],'1234')
    def test_write_failure_is_recorded_after_business_commit_then_retry_uses_saved_data(self):
        with patch('investments.research_files.ArchiveFiles.write',side_effect=OSError('PRIVATE DISK ERROR')):record=self.dataset()
        listing=self.client.get('/api/investments/research/archives',params={'account_id':self.account['id']}).json();self.assertEqual(listing['items'][0]['state'],'failed');self.assertNotIn('PRIVATE',json.dumps(listing))
        saved=self.post('archives',{'account_id':self.account['id'],'object_id':record['id'],'version':1},'retry-archive',200);self.assertEqual(saved['state'],'ready')
        self.assertEqual(self.client.get('/api/investments/research/objects/'+record['id']).json(),record)
    def test_tamper_blocks_download_and_wrong_account_has_no_access(self):
        record=self.dataset();path=next(Path(os.environ['INVESTMENT_RESEARCH_ARCHIVE_ROOT']).rglob('rows.jsonl.gz'));path.write_bytes(b'corrupted')
        response=self.client.get('/api/investments/research/archives/'+record['id']+'/download',params={'account_id':self.account['id'],'version':1});self.assertEqual(response.status_code,409)
        other=self.store.create('accounts',{'name':'其他','baseline_date':'2026-10-28','opening_cash':'0'},'archive-other')
        self.post('archives',{'account_id':other['id'],'object_id':record['id'],'version':1},'archive-wrong-account',422)
    def test_archive_run_includes_immutable_parent_and_roundtrip_exact_values(self):
        from investments.research_archive import ResearchArchive
        dataset=self.dataset();run=self.post('screens',{'account_id':self.account['id'],'dataset_id':dataset['id'],'conditions':[]},'archive-screen')
        archive=ResearchArchive(__import__('investments.research_tools',fromlist=['ResearchTools']).ResearchTools(self.store))
        self.assertEqual(archive.read_record(run['id'],1,self.account['id']),run)
        self.assertEqual(archive.read_record(dataset['id'],1,self.account['id']),dataset)
        response=self.client.get('/api/investments/research/archives/'+run['id']+'/download',params={'account_id':self.account['id'],'version':1})
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:self.assertEqual(len(json.loads(z.read('bundle.json'))['records']),2)
