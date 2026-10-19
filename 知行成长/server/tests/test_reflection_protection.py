"""Private reflection records remain in PostgreSQL; legacy mirrors stay untouched."""
import copy
from contextlib import contextmanager
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from cloud_fixtures import CloudFixture
from copilot.core import Problem,digest
from reflections.store import ReflectionsStore,render_markdown,entry_path
from reflections.api import register

class ReflectionProtectionTests(CloudFixture):
    def setUp(self):
        super().setUp();self.s=ReflectionsStore(self.root,self.runtime);self.s.initialize()
        self.data={'record_date':'2026-10-16','raw_text':'PRIVATE ORIGINAL','prompt_kind':'自由记录','guided_answers':{},'tags':['keep']}
        self.id=self.s.create(self.data,'create-key')['id']
    def entry(self):return self.s.entry(self.id)
    def update(self,key='update-key',**changes):return self.s.update(self.id,{**self.data,'base_version':self.entry()['version'],**changes},key)
    def mirror(self):
        path=self.root/self.entry()['path'];path.parent.mkdir(parents=True,exist_ok=True);return path
    def organize(self):
        self.s._put('reflection_ai_attempts','ready-attempt',{'id':'ready-attempt','entry_id':self.id,'kind':'organize','status':'ready','version_at_request':self.entry()['version'],'sections':[{'kind':'event','text':'PRIVATE ADOPTED'}]})
    def assert_private(self):
        self.assertEqual(self.repo.commits[self.repo.head]['files'],{'README.md':'Content repository'})
    def test_mutations_preserve_legacy_mirrors_and_private_records(self):
        path=self.mirror();path.write_text('OLD SOURCE CONTENT');self.update(raw_text='PRIVATE UPDATED')
        self.organize();self.s.adopt(self.id,'ready-attempt','adopt-key');self.s.archive(self.id,'archive-key');self.s.restore(self.id,'restore-key')
        self.assertEqual(path.read_text(),'OLD SOURCE CONTENT');self.assertEqual(self.entry()['raw_text'],'PRIVATE UPDATED');self.assert_private()
    def test_legacy_without_mirror_hash_updates_in_database(self):
        entry=self.entry();entry.pop('mirror_hash');self.s._put('reflection_entries',self.id,entry)
        self.update();self.assertEqual(self.entry()['version'],2);self.assertEqual(self.entry()['mirror_hash'],digest(render_markdown(self.entry())))
        self.assertFalse((self.root/self.entry()['path']).exists())
    def test_no_local_file_is_required_after_restart(self):
        self.update(raw_text='PRIVATE VERSION TWO');fresh=ReflectionsStore('/no-source-directory','/no-runtime-directory');fresh.initialize()
        self.assertEqual(fresh.entry(self.id)['raw_text'],'PRIVATE VERSION TWO');self.assertEqual(len(fresh.versions(self.id)),2)
    def test_stale_editor_keeps_latest_record_and_history(self):
        self.update();before=self.entry()
        with self.assertRaises(Problem):self.s.update(self.id,{**self.data,'base_version':1,'raw_text':'stale'},'stale-key')
        self.assertEqual(self.entry(),before);self.assertEqual(len(self.s.versions(self.id)),2)
    def interrupt(self,needle):
        original=self.s.conn
        class Proxy:
            def __init__(self,c):self.c=c
            def execute(self,sql,params=None):
                if needle in sql:raise RuntimeError('simulated transaction interruption')
                return self.c.execute(sql,params)
            def __getattr__(self,name):return getattr(self.c,name)
        @contextmanager
        def conn():
            with original() as c:yield Proxy(c)
        return patch.object(self.s,'conn',conn)
    def test_record_and_version_roll_back_together_then_retry(self):
        with self.interrupt('INSERT INTO reflection_versions'),self.assertRaises(RuntimeError):self.update()
        self.assertEqual(self.entry()['version'],1);self.assertEqual(len(self.s.versions(self.id)),1)
        self.update();self.assertEqual(self.entry()['version'],2)
    def test_legacy_pending_file_operation_is_preserved_without_replay(self):
        operation={'id':'legacy-pending','state':'pending','files':{'执行复盘/old.md':{'content':'PRIVATE OLD'}},'records':[]}
        self.s._put('reflection_operations','legacy-pending',operation)
        with self.assertRaises(Problem) as error:self.s.initialize()
        self.assertEqual(error.exception.code,'migration_pending');self.assertEqual(self.s.get('reflection_operations','legacy-pending'),operation)
        self.assertFalse((self.root/'执行复盘/old.md').exists())
    def test_inspection_is_read_only_and_renders_saved_database_text(self):
        self.mirror().write_text('untrusted local source');before=copy.deepcopy(self.entry());head=self.repo.head
        report=self.s.mirror_status(self.id)
        self.assertEqual(report['storage'],'database');self.assertIsNone(report['path']);self.assertIsNone(report['file_markdown'])
        self.assertFalse(report['conflict']);self.assertIn('PRIVATE ORIGINAL',report['saved_markdown']);self.assertEqual(self.entry(),before);self.assertEqual(self.repo.head,head)
    def test_journal_and_records_commit_atomically_and_replay_once(self):
        with self.interrupt('INSERT INTO reflection_operations'),self.assertRaises(RuntimeError):self.update()
        self.assertEqual(self.entry()['version'],1);first=self.update()
        self.assertEqual(first,self.s.update(self.id,{**self.data,'base_version':1},'update-key'));self.assertEqual(len(self.s.versions(self.id)),2)
    def test_create_keeps_preexisting_legacy_file(self):
        import uuid
        identity='ref-'+'a'*32;path=self.root/entry_path(identity,'2026-10-16');path.parent.mkdir(parents=True);path.write_text('LEGACY COLLISION')
        with patch('reflections.store.uuid.uuid4',return_value=uuid.UUID('a'*32)):self.s.create(self.data,'another-create')
        self.assertEqual(path.read_text(),'LEGACY COLLISION');self.assertEqual(self.s.entry(identity)['raw_text'],'PRIVATE ORIGINAL')
    def test_crlf_in_legacy_source_does_not_change_database(self):
        path=self.mirror();raw=b'old\r\nsource\r\n';path.write_bytes(raw);self.update()
        self.assertEqual(path.read_bytes(),raw);self.assertFalse(self.s.mirror_status(self.id)['conflict'])
    def test_binary_and_large_legacy_sources_are_never_read_or_overwritten(self):
        path=self.mirror()
        for n,raw in enumerate((b'\xff\xfe',b'x'*200001)):
            path.write_bytes(raw);self.update('update-'+str(n));self.assertEqual(path.read_bytes(),raw)
        self.assert_private()
    def test_api_status_and_stale_update_use_database_only(self):
        api=FastAPI();register(api,self.root,self.runtime)
        @api.exception_handler(Problem)
        async def problem(request,error):return JSONResponse({'error':error.code},status_code=error.status)
        self.update()
        with TestClient(api) as client:
            status=client.get('/api/reflections/'+self.id+'/file-status');self.assertEqual(status.status_code,200);self.assertEqual(status.json()['storage'],'database')
            result=client.put('/api/reflections/'+self.id,json={**self.data,'base_version':1,'key':'stale-api-key'},headers={'X-Copilot-Request':'1'})
            self.assertEqual(result.status_code,409)
        self.assertEqual(self.entry()['version'],2);self.assert_private()
