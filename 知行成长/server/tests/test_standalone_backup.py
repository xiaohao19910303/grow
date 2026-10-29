"""Real pg_dump/restore and Git bundles, against disposable whole databases only."""
import json, os, shutil, subprocess, tempfile, unittest, uuid
from pathlib import Path
from unittest.mock import patch
import psycopg2
from psycopg2 import sql
from psycopg2.extensions import parse_dsn, make_dsn
from cryptography.fernet import Fernet

class StandaloneBackupTests(unittest.TestCase):
    def setUp(self):
        self.admin=os.environ['TEST_POSTGRES_DSN'];assert 'host=127.0.0.1' in self.admin
        self.names=[];self.source=self.database();self.target=self.database()
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.key=Fernet.generate_key().decode();self.env={'ACCOUNT_ENCRYPTION_KEY':self.key,'GITHUB_CONTENT_REPO':'other-owner/content','GITHUB_CONTENT_BRANCH':'main'}
        self.git=self.root/'mirror.git';self.gitcmd('init','--bare',str(self.git))
        work=self.root/'work';self.gitcmd('init','-b','main',str(work));(work/'lesson.md').write_text('Public synthetic lesson')
        self.gitcmd('-C',str(work),'add','.');self.gitcmd('-C',str(work),'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','fixture')
        self.sha=self.gitcmd('-C',str(work),'rev-parse','HEAD').strip();self.gitcmd('-C',str(work),'push',str(self.git),'main')
        self.gitcmd('--git-dir',str(self.git),'symbolic-ref','HEAD','refs/heads/main')
        with psycopg2.connect(self.source) as c:
            cur=c.cursor();cur.execute('CREATE TABLE auth_users(id TEXT PRIMARY KEY,schema_name TEXT,github_config TEXT)')
            cur.execute('INSERT INTO auth_users VALUES (%s,%s,%s)',('owner','public','{}'))
            cur.execute('CREATE SCHEMA tenant_fixture');cur.execute('INSERT INTO auth_users VALUES (%s,%s,%s)',('alice','tenant_fixture',json.dumps({'mode':'custom','repository':'other-owner/content','branch':'main','token':Fernet(self.key.encode()).encrypt(b'PRIVATE_TOKEN').decode()})))
            for schema in ('public','tenant_fixture'):
                cur.execute(sql.SQL('CREATE TABLE {}.cloud_content_settings(id TEXT PRIMARY KEY,data TEXT)').format(sql.Identifier(schema)))
                cur.execute(sql.SQL('INSERT INTO {}.cloud_content_settings VALUES (%s,%s)').format(sql.Identifier(schema)),('binding',json.dumps({'repository':'other-owner/content','branch':'main'})))
                cur.execute(sql.SQL('CREATE TABLE {}.cloud_documents(path TEXT PRIMARY KEY,data TEXT)').format(sql.Identifier(schema)))
                cur.execute(sql.SQL('INSERT INTO {}.cloud_documents VALUES (%s,%s)').format(sql.Identifier(schema)),('lesson',json.dumps({'storage':'github','commit_sha':self.sha,'hash':'hash','text':'PRIVATE_NOTE'})))
                cur.execute(sql.SQL('CREATE TABLE {}.action_facts(id TEXT PRIMARY KEY, minutes INTEGER)').format(sql.Identifier(schema)))
                cur.execute(sql.SQL('INSERT INTO {}.action_facts VALUES (%s,20)').format(sql.Identifier(schema)),('fact-1',))
                import db, ai_evidence
                cur.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
                snapshot=ai_evidence.freeze(db.CompatConnection(c),'behavior-report','backup-task',
                    [{'role':'user','content':'PRIVATE_EVIDENCE_FIXTURE'}],'fixture')
                ai_evidence.bind(db.CompatConnection(c),'behavior-result','backup-result',snapshot['id'])
            cur.execute('SET LOCAL search_path TO public')

        self.backup=self.root/'backup'
    def database(self):
        name='web_backup_'+uuid.uuid4().hex;self.names.append(name)
        c=psycopg2.connect(self.admin);c.autocommit=True;c.cursor().execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)));c.close()
        self.addCleanup(self.drop,name)
        settings=parse_dsn(self.admin);settings['dbname']=name;return make_dsn(**settings)
    def drop(self,name):
        c=psycopg2.connect(self.admin);c.autocommit=True;c.cursor().execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(name)));c.close()
    def gitcmd(self,*args):
        return subprocess.run(['git',*args],check=True,capture_output=True,text=True).stdout
    def create(self):
        from standalone_backup import create
        return create(self.source,self.backup,{'other-owner/content':self.git},env=self.env,writers_stopped=True)
    def test_real_snapshot_bundle_restore_and_repeat_refusal(self):
        from standalone_backup import restore, verify, BackupError
        result=self.create();self.assertEqual(result['version'],1);self.assertEqual(verify(self.backup)['tables']['tenant_fixture.action_facts'],1)
        manifest=(self.backup/'manifest.json').read_text();self.assertNotIn('PRIVATE_NOTE',manifest);self.assertNotIn(self.key,manifest);self.assertNotIn('PRIVATE_TOKEN',manifest)
        restored=self.root/'restored';restore(self.target,self.backup,restored,env=self.env,writers_stopped=True)
        with psycopg2.connect(self.target) as c:
            cur=c.cursor();cur.execute('SELECT sum(minutes) FROM tenant_fixture.action_facts');self.assertEqual(cur.fetchone()[0],20)
            cur.execute('SELECT data FROM tenant_fixture.cloud_documents');self.assertEqual(json.loads(cur.fetchone()[0])['text'],'PRIVATE_NOTE')
            cur.execute('SELECT count(*) FROM tenant_fixture.ai_evidence_links');self.assertEqual(cur.fetchone()[0],2)
            cur.execute('SELECT data FROM tenant_fixture.ai_evidence_snapshots');self.assertEqual(json.loads(cur.fetchone()[0])['messages'][0]['content'],'PRIVATE_EVIDENCE_FIXTURE')
            cur.execute('SELECT version FROM tenant_fixture.ai_evidence_migrations');self.assertEqual(cur.fetchone()[0],1)

            cur.execute("SELECT github_config FROM auth_users WHERE id='alice'");self.assertEqual(Fernet(self.key.encode()).decrypt(json.loads(cur.fetchone()[0])['token'].encode()),b'PRIVATE_TOKEN')
        self.assertEqual(self.gitcmd('--git-dir',str(restored/'content-0.git'),'show',self.sha+':lesson.md').strip(),'Public synthetic lesson')
        with self.assertRaises(BackupError):restore(self.target,self.backup,self.root/'again',env=self.env,writers_stopped=True)
    def test_corruption_wrong_key_and_nonempty_target_do_not_modify_database(self):
        from standalone_backup import restore, BackupError
        self.create()
        with self.assertRaises(BackupError):restore(self.target,self.backup,self.root/'wrong-key',env={**self.env,'ACCOUNT_ENCRYPTION_KEY':Fernet.generate_key().decode()},writers_stopped=True)
        dump=self.backup/'database.dump';dump.write_bytes(dump.read_bytes()+b'bad')
        with self.assertRaises(BackupError):restore(self.target,self.backup,self.root/'corrupt',env=self.env,writers_stopped=True)
        with psycopg2.connect(self.target) as c:c.cursor().execute('CREATE TABLE keep_me(value TEXT)')
        with self.assertRaises(BackupError):restore(self.target,self.backup,self.root/'nonempty',env=self.env,writers_stopped=True)
        with psycopg2.connect(self.target) as c:
            cur=c.cursor();cur.execute("SELECT to_regclass('keep_me')");self.assertEqual(cur.fetchone()[0],'keep_me')
    def test_missing_content_or_writer_stop_refuses_incomplete_backup(self):
        from standalone_backup import create, BackupError
        with self.assertRaises(BackupError):create(self.source,self.backup,{},env=self.env,writers_stopped=True)
        self.assertFalse(self.backup.exists())
        with self.assertRaises(BackupError):create(self.source,self.backup,{'other-owner/content':self.git},env=self.env,writers_stopped=False)
        with psycopg2.connect(self.source) as c:
            cur=c.cursor();cur.execute('SELECT count(*) FROM auth_users');self.assertEqual(cur.fetchone()[0],2)
    def test_incomplete_manifest_is_rejected_before_target_mutation(self):
        from standalone_backup import restore,BackupError
        self.create();path=self.backup/'manifest.json';manifest=json.loads(path.read_text());del manifest['row_hashes'];path.write_text(json.dumps(manifest))
        with self.assertRaises(BackupError):restore(self.target,self.backup,self.root/'invalid-manifest',env=self.env,writers_stopped=True)
        self.assertFalse((self.root/'invalid-manifest').exists())
        with psycopg2.connect(self.target) as c:
            cur=c.cursor();cur.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public'");self.assertEqual(cur.fetchone()[0],0)

    def test_unavailable_historical_commit_refuses_incomplete_backup(self):
        from standalone_backup import BackupError
        with psycopg2.connect(self.source) as c:
            c.cursor().execute("UPDATE cloud_documents SET data=jsonb_set(data::jsonb,'{commit_sha}',to_jsonb(%s::text))::text",('f'*40,))
        with self.assertRaises(BackupError):self.create()
        self.assertFalse(self.backup.exists())

    def test_failed_upgrade_transaction_then_restore_to_new_database(self):
        from standalone_backup import restore
        self.create()
        with self.assertRaises(psycopg2.Error):
            with psycopg2.connect(self.source) as c:
                c.cursor().execute('ALTER TABLE action_facts ADD COLUMN upgrade_marker TEXT');c.cursor().execute('SELECT missing_upgrade_function()')
        with psycopg2.connect(self.source) as c:
            cur=c.cursor();cur.execute("SELECT count(*) FROM information_schema.columns WHERE table_name='action_facts' AND column_name='upgrade_marker'");self.assertEqual(cur.fetchone()[0],0)
        restore(self.target,self.backup,self.root/'rollback',env=self.env,writers_stopped=True)
        with psycopg2.connect(self.target) as c:
            cur=c.cursor();cur.execute('SELECT sum(minutes) FROM action_facts');self.assertEqual(cur.fetchone()[0],20)
