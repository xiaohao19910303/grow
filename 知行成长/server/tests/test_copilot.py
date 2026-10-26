"""Legacy course regression: PostgreSQL records and immutable GitHub documents."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from cloud_fixtures import CloudFixture
from copilot.core import MODULE,Problem,digest,encoded
from copilot.backup import snapshot,restore_preview,restore
from copilot.generation import Generator,SEPARATOR
from legacy_files import preview,apply

DATE='2026-10-14T10:00:00+08:00'

class CourseChecks(CloudFixture):
    def setUp(self):
        super().setUp();self.store=self.seed_courses()
        for target in ('copilot.core.now','copilot.cloud_store.now'):
            clock=patch(target,return_value=DATE);clock.start();self.addCleanup(clock.stop)
    def update_document(self,path,text):
        with self.store.lock():self.store.documents.publish('test-'+digest(path+text),{'text':text},{MODULE+'/'+path:text})
    def ready_draft(self):
        for lesson in self.store.scan()['lessons']:
            if lesson['learning_state']!='completed':self.store.learning(lesson['lesson_no'],'completed',lesson['version'],'fixture-complete-'+str(lesson['lesson_no']))
        from test_legacy_cloud_api import COURSE
        folder=self.root/MODULE/'备课资料';folder.mkdir(exist_ok=True)
        (folder/'第003课-摘要.md').write_text('已核验教学摘要。')
        (folder/'第003课.json').write_text(encoded([{'title':'测试资料','url':'https://example.org/source','verified_at':'2026-10-13','verification':'合成测试','claim':'示范','note_path':'备课资料/第003课-摘要.md'}]))
        report=preview(self.store.documents,self.root);apply(self.store.documents,self.root,report['token'])
        _,plan,sources,blockers=self.store.readiness();self.assertFalse(blockers)
        data={'lesson_no':3,'content':COURSE,'sources':'摘要 [来源](https://example.org/source)','source_snapshot':sources,'plan_snapshot':plan,'record_hash':self.store.file_hash('学习记录.md'),'stream_completed':True,'errors':[]}
        with self.store.conn() as c:c.execute('INSERT INTO copilot_drafts VALUES (?,?,1,?,?,?)',('draft',3,'ready',encoded(data),DATE))
        return data
    def publish(self):return self.store.publish('draft',1,'publish-key')
    def pending_operation(self):
        with self.store.conn() as c:return c.execute("SELECT id FROM copilot_operations WHERE status!='done'").fetchone()[0]
    def test_existing_import_and_read_only_content(self):
        head=self.repo.head;state=self.store.scan()
        self.assertEqual((state['generated_count'],state['completed_count']),(2,0));self.assertEqual(state['next_generation_lesson'],3)
        self.assertFalse(state['blockers']);self.assertEqual(self.repo.head,head);self.assertFalse(self.runtime.exists())
    def test_same_day_and_missing_volume(self):
        with patch('copilot.core.now',return_value='2026-10-13T20:00:00+08:00'),patch('copilot.cloud_store.now',return_value='2026-10-13T20:00:00+08:00'):self.assertNotIn('already_generated_today',[b['code'] for b in self.store.readiness()[3]]);self.assertIn('learning_pending',[b['code'] for b in self.store.readiness()[3]])
        (self.root/MODULE).rename(self.root/'unmounted-source');fresh=self.new_course();fresh.initialize()
        self.assertEqual(fresh.scan()['generated_count'],2)
    def test_duplicate_missing_sources_and_short_filename(self):
        text=self.store.path('每日课程/2026-10-13-第002课-什么样的证据更可信.md').read_text()
        self.update_document('每日课程/第002课.md',text);self.assertTrue(self.store.scan()['blockers'])
    def test_plan_confirmation_invalidation_and_missing_sources(self):
        self.assertIn('sources_required',[b['code'] for b in self.store.readiness()[3]])
        self.update_document('课程主题规划.md','| 008 | 注意力 | 解释注意力 |\n');plan=self.store.plan()
        self.assertFalse(plan['items'][0]['confirmed']);self.assertTrue(self.store.confirm_plan(plan['hash'],[8])['items'][0]['confirmed'])
        self.update_document('课程主题规划.md','| 008 | 记忆 | 解释记忆 |\n');self.assertFalse(self.store.plan()['items'][0]['confirmed'])
    def test_publish_idempotency_and_learning(self):
        self.ready_draft();original=self.store.path('学习记录.md').read_text().split('## 个人记录区',1)[1]
        self.assertEqual(self.publish(),self.publish());self.assertEqual(self.store.scan()['generated_count'],3)
        lesson=self.store.lesson(3);head=self.repo.head;self.store.learning(3,'completed',lesson['version'],'learning-key')
        self.assertEqual(self.store.scan()['completed_count'],3)
        self.store.learning(3,'unknown',self.store.lesson(3)['version'],'undo-key');self.assertEqual(self.store.scan()['completed_count'],2)
        self.assertEqual(self.repo.head,head);self.assertEqual(self.store.path('学习记录.md').read_text().split('## 个人记录区',1)[1],original)
        with self.assertRaises(Problem):self.store.publish('draft',2,'publish-key')
    def test_conflict_preserves_external_notes(self):
        self.ready_draft();path=MODULE+'/学习规划.md';self.external(path,'external edit')
        with self.assertRaises(Problem):self.publish()
        self.assertEqual(self.module_content.read_text(path,self.repo.head),'external edit');self.assertEqual(self.store.scan()['generated_count'],2)
    def test_recovery_after_second_file_failure(self):
        self.ready_draft();self.repo.fail_update=True
        with self.assertRaises(Problem):self.publish()
        operation=self.pending_operation();self.repo.fail_update=False
        self.assertEqual(self.store.recover(operation)['status'],'done');self.assertEqual(self.store.recover(operation)['status'],'done')
        self.assertEqual(self.store.scan()['generated_count'],3)
    def test_path_and_version_protection(self):
        for path in ('../outside.md','/etc/passwd'):
            with self.assertRaises(Problem):self.store.path(path)
        with self.assertRaises(Problem):self.store.learning(1,'completed','0'*64,'stale-version')
        with self.assertRaises(Problem):self.module_content.path(MODULE+'/学习记录.md')
    def test_backup_restore_preserves_learning_state(self):
        self.store.learning(1,'completed',self.store.lesson(1)['version'],'complete-key')
        for action in (lambda:snapshot(self.store),lambda:restore_preview(self.store,self.root/'archive'),lambda:restore(self.store,self.root/'archive','token')):
            with self.assertRaises(Problem) as error:action()
            self.assertEqual(error.exception.code,'remote_backup')
        fresh=self.new_course();fresh.initialize();self.assertEqual(fresh.scan()['completed_count'],1)
    def test_generation_simulated_events_and_cancel(self):
        data=self.ready_draft()
        with self.store.conn() as c:c.execute('DELETE FROM copilot_drafts')
        async def transport(messages,config):yield {'text':data['content']+SEPARATOR+data['sources']};yield {'done':True}
        g=Generator(self.store,transport);did,fresh=g.begin(3,'generation-key');self.assertEqual(g.begin(3,'generation-key'),(did,False))
        async def run():return [e async for e in g.stream(did,fresh)]
        self.assertTrue(any('event: completed' in e for e in asyncio.run(run())))
        g.cancel(did)
        did,_=g.begin(3,'generation-key-2');g.cancel(did);self.assertEqual(self.store.draft(did)['status'],'cancelled')
    def test_gap_unknown_date_and_round_end(self):
        text=self.store.path('每日课程/2026-10-13-第002课-什么样的证据更可信.md').read_text()
        self.update_document('每日课程/第004课.md',text.replace('第002课','第004课').replace('2026-10-13','未知日期'))
        self.assertTrue(any(b.get('lesson_no')==3 for b in self.store.scan()['blockers']))
        with patch.object(self.store,'_scan',return_value={'blockers':[],'next_generation_lesson':None,'today_lessons':[]}):self.assertIn('round_complete',[b['code'] for b in self.store.readiness()[3]])
    def test_generation_failure_and_unverified_citation(self):
        data=self.ready_draft();data['content']+='[未核验](https://unverified.example/source)';self.assertTrue(self.store.validate_draft(data))
        with self.store.conn() as c:c.execute('DELETE FROM copilot_drafts')
        async def transport(messages,config):yield {'text':'# 第003课：片段'};raise OSError('simulated interruption')
        g=Generator(self.store,transport);did,fresh=g.begin(3,'failed-generation')
        async def run():return [e async for e in g.stream(did,fresh)]
        self.assertTrue(any('event: failed' in e for e in asyncio.run(run())))
        self.assertEqual(self.store.edit_draft(did,1,data['content'],data['sources'])['status'],'failed')
    def test_recovery_preserves_unknown_hash(self):
        self.ready_draft();self.repo.fail_update=True
        with self.assertRaises(Problem):self.publish()
        operation=self.pending_operation();self.repo.fail_update=False;path=MODULE+'/课程目录.md';self.external(path,'personal edit')
        with self.assertRaises(Problem):self.store.recover(operation)
        self.assertEqual(self.module_content.read_text(path,self.repo.head),'personal edit')
    def test_old_state_sync_does_not_clear_copilot(self):
        import app
        app.init_db();app.save_state({'modules':app.DEFAULT_MODULES});app.save_state({'modules':[]})
        self.assertEqual(self.store.scan()['generated_count'],2)
    def test_backup_change_detection_and_stale_preview(self):
        self.update_document('学习记录.md',self.store.path('学习记录.md').read_text()+'\nPRIVATE NOTE\n')
        self.assertNotIn('PRIVATE NOTE',str(self.repo.commits))
        with self.assertRaises(Problem):restore_preview(self.store,self.root/'missing')
        self.assertIn('PRIVATE NOTE',self.store.path('学习记录.md').read_text())
    def test_full_168_lesson_boundary(self):
        from datetime import date,timedelta
        from test_legacy_cloud_api import COURSE
        with self.store.conn() as c:c.execute('DELETE FROM cloud_documents');c.execute("DELETE FROM copilot_meta WHERE key='cloud-scan'")
        head=self.repo.sha();self.repo.commits[head]={'files':{'README.md':'Synthetic full round'},'parents':[self.repo.head]};self.repo.head=head
        files={};rows=['# 学习记录\n\n| 课次 | 日期 | 课程 | 资料 | 状态 |\n|---|---|---|---|---|\n']
        for n in range(1,169):
            day=(date(2025,1,1)+timedelta(days=n)).isoformat();course=f'每日课程/{day}-第{n:03d}课-样本.md';source=f'参考资料/第{n:03d}课-参考资料.md'
            files[MODULE+'/'+course]=COURSE.replace('第003课',f'第{n:03d}课').replace('2026-10-17',day)+'\n## 复盘回顾与跨领域整合\n合成示范\n'
            files[MODULE+'/'+source]=f'# 参考资料\n[课程](../{course})';rows.append(f'| {n:03d} | {day} | [课程]({course}) | [资料]({source}) | 待本人记录 |\n')
        files[MODULE+'/学习记录.md']=''.join(rows);self.store.documents.publish('full-round',{},files)
        state=self.store.scan();self.assertEqual(state['generated_count'],168);self.assertIsNone(state['next_generation_lesson']);self.assertFalse(state['blockers'])
    def test_isolated_api_access_and_local_reading(self):
        from copilot.api import register
        api=FastAPI();register(api,self.root,self.runtime)
        with TestClient(api,base_url='http://localhost') as client:
            self.assertIn('核心',client.get('/api/copilot/lessons/1').json()['content'])
            self.assertEqual(client.post('/api/copilot/scan',json={}).status_code,403)
            self.assertEqual(client.get('/api/copilot/lessons',headers={'Host':'outside.example'}).status_code,403)
    def test_numbered_tables_in_personal_notes_are_not_catalog(self):
        text=self.store.path('学习记录.md').read_text()+'\n| 001 | PRIVATE EXERCISE ANSWER |\n';self.update_document('学习记录.md',text)
        self.assertEqual(self.store.scan()['generated_count'],2);self.store.learning(1,'completed',self.store.lesson(1)['version'],'notes-kept-key')
        self.assertEqual(self.store.path('学习记录.md').read_text(),text)
    def test_concurrent_publication_is_single(self):
        self.ready_draft()
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:self.publish(),range(2)))
        self.assertEqual(results[0],results[1]);self.assertEqual(self.store.scan()['generated_count'],3)
        self.assertEqual(sum(n==3 for _,n,_ in self.store.record_rows(self.store.path('学习记录.md').read_text())),1)
    def test_recovery_after_index_failure(self):
        self.ready_draft();self.repo.lose_response=True
        with self.assertRaises(Problem):self.publish()
        head=self.repo.head;fresh=self.new_course();fresh.initialize();self.assertEqual(fresh.scan()['generated_count'],3);self.assertEqual(self.repo.head,head)
    def test_recovery_after_database_finalize_failure(self):
        self.ready_draft();original=self.store.conn;triggered=False
        class Proxy:
            def __init__(self,c):self.c=c
            def execute(self,sql,params=None):
                nonlocal triggered
                if "UPDATE copilot_operations SET status='done'" in sql and not triggered:triggered=True;raise RuntimeError('simulated DB failure')
                return self.c.execute(sql,params)
            def __getattr__(self,name):return getattr(self.c,name)
        @contextmanager
        def conn():
            with original() as c:yield Proxy(c)
        with patch.object(self.store,'conn',conn),self.assertRaises(RuntimeError):self.publish()
        head=self.repo.head;fresh=self.new_course();fresh.initialize();self.assertEqual(fresh.scan()['generated_count'],3);self.assertEqual(self.repo.head,head)
    def test_unplanned_lesson_never_calls_transport(self):
        calls=[]
        async def transport(messages,config):calls.append(messages);yield {'done':True}
        with patch.object(self.store,'_scan',return_value={'blockers':[],'next_generation_lesson':8,'today_lessons':[]}):
            with self.assertRaises(Problem):Generator(self.store,transport).begin(8,'unplanned-key')
        self.assertFalse(calls)
    def test_different_writers_compete_for_same_lesson(self):
        self.ready_draft()
        def publish(key):
            try:return self.store.publish('draft',1,key)['status']
            except Problem as error:return error.code
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(publish,['writer-one','writer-two']))
        self.assertEqual(sorted(results),['conflict','done'])
