"""Dump and restore only the disposable test schema, including audit versions."""
import json
import subprocess
import tempfile
from pathlib import Path

import psycopg2
import db
from investments.analysis import InvestmentAnalysis
from copilot.core import digest, encoded, now
from psycopg2 import sql
from test_legacy_cloud_schema import PostgreSQLFixture
from investments.store import InvestmentStore


class InvestmentBackupTests(PostgreSQLFixture):
    def test_private_export_and_pg_restore_preserve_exact_records(self):
        store=InvestmentStore();store.initialize()
        account=store.create('accounts',{'name':'PRIVATE ACCOUNT','baseline_date':'2026-10-26',
            'opening_cash':'1234.56789'},'account')
        review=store.create('reviews',{'account_id':account['id'],'date':'2026-10-26',
            'text':'PRIVATE REVIEW'},'review')
        store.update('reviews',review['id'],1,{'text':'PRIVATE UPDATED'},'edit')
        snapshot=store.export()
        self.assertEqual(len(snapshot['objects']),2)
        self.assertEqual(len(snapshot['versions']),3)
        self.assertNotIn('api_key',json.dumps(snapshot))
        instrument=store.create('instruments',{'name':'恢复标的','code':'510000','market':'SSE','kind':'etf'},'i')
        store.create('fills',{'account_id':account['id'],'instrument_id':instrument['id'],'side':'buy',
            'price':'1.231','quantity':'100','fee':'0.1','tax':'0','executed_at':'2026-10-26T10:00:00+08:00'},'fill')
        evidence=store.create('research',{'account_id':account['id'],'title':'PRIVATE SOURCE','content':'待核对原文',
            'available_at':'2026-10-26T08:00:00+08:00'},'source')
        analysis=InvestmentAnalysis(store);analysis.initialize()
        preview=analysis.preview({'kind':'review','account_id':account['id'],'question':'核对来源',
            'evidence_ids':[evidence['id']],'decision_at':'2030-01-01T08:00:00+08:00'})
        job={'id':'restore-job','state':'ready','created_at':now(),'updated_at':now(),'preview_id':preview['id'],
            'snapshot_hash':preview['snapshot_hash'],'report':{'summary':'PRIVATE RESULT','suggestions':[]}}
        with db.connect() as c:c.execute('INSERT INTO investment_analysis_jobs VALUES (?,?,?,?)',
            (job['id'],'ready',digest('test-only'),encoded(job)))
        snapshot=store.export()
        before=store.balance(account['id'])
        with tempfile.TemporaryDirectory(prefix='investment-backup-') as tmp:
            archive=Path(tmp)/'schema.dump'
            subprocess.run(['pg_dump','--dbname',self.dsn,'--schema',self.schema,
                '--format=custom','--file',str(archive)],check=True,capture_output=True)
            with psycopg2.connect(self.dsn) as c:
                c.cursor().execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))
            subprocess.run(['pg_restore','--dbname',self.dsn,'--no-owner','--no-acl',
                '--single-transaction',str(archive)],check=True,capture_output=True)
        self.assertEqual(store.balance(account['id']),before)
        self.assertEqual(store.export()['objects'],snapshot['objects'])
        self.assertEqual(store.export()['versions'],snapshot['versions'])
        self.assertEqual(store.export()['analysis_jobs'],snapshot['analysis_jobs'])
        self.assertEqual(analysis.get('restore-job')['snapshot_hash'],preview['snapshot_hash'])
