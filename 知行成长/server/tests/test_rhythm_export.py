"""Real pg_dump/pg_restore only against the disposable test schema."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import psycopg2
from test_rhythm_focus import RhythmFixture


class RhythmExportTests(RhythmFixture):
    def test_personal_export_and_postgres_restore_preserve_versions_and_references(self):
        self.enable();p=self.create(completion_mode='check');self.select(p)
        r=self.op(p,'complete').json()['execution']
        self.post('/executions/'+r['id']+'/recap',expected_recap_revision=0,note='原总结',next_step='继续')
        self.post('/executions/'+r['id']+'/recap',expected_recap_revision=1,note='修改总结')
        week=self.client.get('/api/action-plans/rhythm/weeks/2026-10-19').json()
        self.post('/weeks/2026-10-19/confirm',expected_revision=0,snapshot_hash=week['snapshot_hash'],selected_execution_ids=[r['id']])
        self.post('/enrollment',experiment_key='restore-test')
        before=self.client.get('/api/action-plans/rhythm/export?include_events=true').json()
        self.assertEqual(before['executions'][0]['recap_history'][0]['note'],'')
        self.assertTrue(before['events'])
        self.assertEqual(before['weekly_cards'][0]['selected_execution_ids'],[r['id']])
        dsn=os.environ['TEST_POSTGRES_DSN']
        self.assertIn('host=127.0.0.1',dsn)
        for tool in ('pg_dump','pg_restore'):self.assertIsNotNone(shutil.which(tool))
        with tempfile.TemporaryDirectory(prefix='rhythm-pg-restore-') as tmp:
            archive=Path(tmp)/'private.dump'
            subprocess.run(['pg_dump','--dbname',dsn,'--schema',self.schema,'--format=custom','--no-owner','--no-acl','--file',str(archive)],check=True,capture_output=True)
            self.assertTrue(archive.stat().st_size)
            with psycopg2.connect(dsn) as c:c.cursor().execute('DROP SCHEMA '+self.schema+' CASCADE')
            subprocess.run(['pg_restore','--dbname',dsn,'--no-owner','--no-acl','--exit-on-error',str(archive)],check=True,capture_output=True)
        after=self.client.get('/api/action-plans/rhythm/export?include_events=true').json()
        self.assertEqual(before,after)
        self.assertEqual(self.client.get('/api/action-plans/rhythm/weeks/2026-10-19').json()['stats'],week['stats'])
        self.assertNotIn('events',self.client.get('/api/action-plans/rhythm/export').json())
