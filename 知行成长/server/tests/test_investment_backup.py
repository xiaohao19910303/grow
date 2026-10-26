"""Dump and restore only the disposable test schema, including audit versions."""
import json
import subprocess
import tempfile
from pathlib import Path

import psycopg2
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
