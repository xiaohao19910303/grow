"""Private reflection records remain in PostgreSQL; legacy mirrors stay untouched."""
import copy
import json
import unittest
from contextlib import contextmanager, nullcontext
from unittest.mock import Mock, patch
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from cloud_fixtures import CloudFixture
from copilot.core import Problem,digest
from reflections.store import ReflectionsStore,render_markdown,entry_path
from reflections.api import register


class ReflectionBasisTests(unittest.IsolatedAsyncioTestCase):
    def adoption_store(self, sections, status='ready'):
        entry = {'id': 'ref-' + 'a' * 32, 'record_date': '2026-10-28',
                 'version': 1, 'raw_text': 'PRIVATE ORIGINAL', 'path': '执行复盘/日常记录/2026-10/ref-test.md'}
        attempt = {'kind': 'organize', 'status': status, 'version_at_request': 1, 'sections': sections}
        connection = Mock()
        connection.execute.return_value.fetchone.return_value = (json.dumps(attempt),)
        store = Mock(spec=ReflectionsStore)
        store.lock.return_value = nullcontext()
        store.conn.return_value = nullcontext(connection)
        store.replay.return_value = None
        store.get.return_value = entry
        return store, entry

    def test_adoption_rejects_legacy_ready_results_without_valid_classification(self):
        for sections in ([{'kind': 'event', 'text': '未标来源'}],
                         [{'kind': 'next_step', 'text': '未知来源', 'basis': 'unknown'}],
                         [{'kind': 'event', 'text': '原文整理', 'basis': 'statement'},
                          {'kind': 'next_step', 'text': '混入无分类建议'}]):
            with self.subTest(sections=sections):
                store, entry = self.adoption_store(sections)
                before = copy.deepcopy(entry)
                with self.assertRaises(Problem):
                    ReflectionsStore.adopt(store, entry['id'], 'ready-attempt', 'adopt-key')
                self.assertEqual(entry, before)
                store.publish.assert_not_called()

    def test_adoption_preserves_valid_classifications_and_original_text(self):
        sections = [{'kind': 'event', 'text': '今天开会', 'basis': 'statement'},
                    {'kind': 'next_step', 'text': '下次先写结论', 'basis': 'suggestion'}]
        store, entry = self.adoption_store(sections)
        ReflectionsStore.adopt(store, entry['id'], 'ready-attempt', 'adopt-key')
        self.assertEqual(entry['raw_text'], 'PRIVATE ORIGINAL')
        saved = json.loads(store.publish.call_args.args[3][0]['params'][1])
        self.assertEqual(saved['adopted_summary']['sections'], sections)

    def test_failed_organizing_attempt_cannot_be_adopted(self):
        store, entry = self.adoption_store([], status='failed')
        with self.assertRaises(Problem) as error:
            ReflectionsStore.adopt(store, entry['id'], 'failed-attempt', 'adopt-key')
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(entry['raw_text'], 'PRIVATE ORIGINAL')
        store.publish.assert_not_called()

    def test_invalid_or_missing_basis_is_rejected(self):
        from reflections.assist import _parse_assist
        for extra in ({}, {'basis': None}, {'basis': ''}, {'basis': 'unknown'}, {'basis': 1}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                _parse_assist('organize', json.dumps({'sections': [{'kind': 'event', 'text': '待核实', **extra}]}))

    def test_valid_statement_and_suggestion_remain_distinct(self):
        from reflections.assist import _parse_assist
        sections = [{'kind': 'event', 'text': '今天开会', 'basis': 'statement'},
                    {'kind': 'next_step', 'text': '下次先写结论', 'basis': 'suggestion'}]
        self.assertEqual(_parse_assist('organize', json.dumps({'sections': sections})), {'sections': sections})

    async def test_invalid_model_classification_cannot_become_an_adoptable_result(self):
        from reflections.assist import ReflectionAssistant
        attempt = {'id': 'attempt', 'kind': 'organize', 'status': 'queued', 'raw': '',
                   'sections': [], 'evidence_snapshot_id':'fixture', 'snapshot': {'text': 'PRIVATE ORIGINAL', 'answers': []}}
        saved = {}
        store = Mock()
        store.get.return_value = attempt
        store._put.side_effect = lambda table, key, value: saved.update(copy.deepcopy(value))
        store.generation_gate.return_value = nullcontext()
        async def model(messages, cfg):
            yield {'text': json.dumps({'sections': [{'kind': 'event', 'text': '无分类的AI推测'}]})}
            yield {'done': True}
        from reflections.assist import _assist_messages
        with patch('ai_evidence.messages', return_value=_assist_messages('organize',attempt['snapshot'])):
            result = await ReflectionAssistant(store, model)._run('attempt', {'model': 'fixture'})
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(saved['status'], 'failed')
        self.assertEqual(saved['sections'], [])
        self.assertEqual(saved['snapshot']['text'], 'PRIVATE ORIGINAL')


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
        self.s._put('reflection_ai_attempts','ready-attempt',{'id':'ready-attempt','entry_id':self.id,'kind':'organize','status':'ready','version_at_request':self.entry()['version'],'sections':[{'kind':'event','text':'PRIVATE ADOPTED','basis':'statement'}]})
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
