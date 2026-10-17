"""Actual PostgreSQL, GitHub HTTP simulator, legacy fixtures and model transports."""
import asyncio
import json
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import httpx
from copilot.core import MODULE, Problem, encoded
from copilot.cloud_store import CloudStore
from copilot.generation import Generator, SEPARATOR
from reading.cloud_store import CloudReadingStore
from reading.sources import identify
from cloud_content import ModuleContent
from legacy_files import preview, apply
from test_legacy_cloud_schema import PostgreSQLFixture
from test_github_plans import Repository

OWN={'api_base_url':'https://model.example/v1','api_key':'USER_TEST_ONLY','model_name':'own-model'}
DATE='2026-10-17T10:00:00+08:00'


class CloudFixture(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'materials';self.root.mkdir()
        shutil.copytree(Path(__file__).parent/'fixtures/renzhi',self.root/MODULE)
        notes=self.root/MODULE/'备课资料';notes.mkdir(exist_ok=True)
        (notes/'第003课-摘要.md').write_text('已核验的教学摘要。')
        (notes/'第003课.json').write_text(encoded([{'title':'教学资料','url':'https://example.org/source','verified_at':'2026-10-16',
            'verification':'测试夹具','claim':'示范','note_path':'备课资料/第003课-摘要.md'}]))
        with (self.root/MODULE/'学习记录.md').open('a') as f:f.write('\n## 个人记录区\n\nPRIVATE ORIGINAL NOTE\n')
        self.repository=Repository()
        self.content=ModuleContent('owner/courses','main','TEST_ONLY',transport=httpx.MockTransport(self.repository))
        self.course=CloudStore(self.root,Path(self.tmp.name)/'runtime',self.content);self.course.initialize()
        self.reader=CloudReadingStore(self.root,Path(self.tmp.name)/'runtime',self.content);self.reader.initialize()
        self.clock=patch('copilot.core.now',return_value=DATE);self.clock.start();self.addCleanup(self.clock.stop)
    def source_article(self):
        url='https://example.org/article';aid=identify(url)
        base=self.root/'认知阅读/文章资料'/aid;base.mkdir(parents=True)
        data={'id':aid,'type':'article','title':'Evidence','url':url,'source':'example.org','author':'测试作者','language':'en',
              'saved_at':'2026-10-16T10:00:00+08:00','summary':'A public teaching summary. '*10,'access':'测试摘要','published_at':'2026-10-16',
              'read':False,'bookmarked':False,'translation_drafts':{'p1':{'text':'PRIVATE TRANSLATION','version':1}}}
        (base/'文章信息.json').write_text(encoded(data));(base/'中文导读.md').write_text('# 导读\n\nPublic guide')
        notes=self.root/'认知阅读/阅读笔记';notes.mkdir(parents=True);(notes/(aid+'.md')).write_text('PRIVATE READING NOTE')
        return aid
    def migrate_files(self):
        report=preview(self.course.documents,self.root)
        self.assertFalse(report['conflicts'],report)
        result=apply(self.course.documents,self.root,report['token'])
        return result


class LegacyCloudContentTests(CloudFixture):
    def test_import_retains_originals_and_never_publishes_private_state(self):
        aid=self.source_article()
        (self.root/'认知阅读/文章资料'/aid/'我的笔记.md').write_text('PRIVATE INLINE NOTE')
        old={str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.migrate_files()
        self.assertEqual(old,{str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        files=self.repository.commits[self.repository.head]['files']
        for secret in ('PRIVATE ORIGINAL NOTE','PRIVATE READING NOTE','PRIVATE INLINE NOTE','PRIVATE TRANSLATION','USER_TEST_ONLY'):
            self.assertNotIn(secret,json.dumps(files))
        self.assertFalse(any(p.endswith(('学习记录.md','文章信息.json')) or '/阅读笔记/' in p for p in files))
        self.assertEqual(self.reader.note(aid)['text'],'PRIVATE READING NOTE')
        self.assertEqual(self.reader.article(aid)['translation_drafts']['p1']['text'],'PRIVATE TRANSLATION')
        self.assertEqual(len(self.course.scan()['lessons']),2)
        before=self.repository.ref_updates
        self.migrate_files()
        self.assertEqual(self.repository.ref_updates,before)
    def test_course_generation_publication_feedback_and_restart(self):
        self.migrate_files()
        body=('# 第003课：确认偏误\n\n日期：2026-10-17\n## 引导问题\n问题\n## 核心概念\n概念\n'
              '## 完整示范\n假设示范\n## 误区与边界\n边界\n## 练习\n问题\n\n---\n\n## 参考分析\n分析\n'
              '## 自查\n自查\n## 记忆提示\n提示\n[来源](https://example.org/source)')
        async def model(messages,cfg):
            self.assertEqual(cfg['key'],OWN['api_key'])
            yield {'text':body+SEPARATOR+'摘要 [来源](https://example.org/source)'};yield {'done':True}
        generator=Generator(self.course,model)
        async def run():
            did,fresh=generator.begin(3,'generate-test',OWN)
            packets=[packet async for packet in generator.stream(did,fresh,{'key':OWN['api_key'],'url':OWN['api_base_url'],'model':OWN['model_name'],'price_version':'','input_price':'','output_price':''})]
            return did,packets
        did,packets=asyncio.run(run())
        draft=self.course.draft(did);self.assertEqual(draft['status'],'ready',draft)
        result=self.course.publish(did,draft['version'],'publish-test')
        self.assertEqual(result['status'],'done')
        lesson=self.course.lesson(3);self.assertIn('核心概念',lesson['content'])
        before=self.repository.ref_updates
        self.course.submit_summary(3,'PRIVATE LEARNING SUMMARY',180,lesson['version'],'complete-test')
        self.assertEqual(self.repository.ref_updates,before)
        self.assertEqual(self.course.get_learning_record(3)['summary_text'],'PRIVATE LEARNING SUMMARY')
        fresh=CloudStore('/no-materials','/no-runtime',self.content);fresh.initialize()
        self.assertEqual(fresh.lesson(3)['learning_state'],'completed')
        self.assertIn('参考分析',fresh.lesson(3)['content'])
        self.assertNotIn('PRIVATE LEARNING SUMMARY',json.dumps(self.repository.commits[self.repository.head]['files']))
    def test_reading_import_notes_drafts_adoption_and_reload(self):
        aid=self.source_article();self.migrate_files()
        before=self.repository.ref_updates
        note=self.reader.note(aid)
        self.reader.update_personal(aid,{'read':True,'bookmarked':True,'note':'PRIVATE UPDATED NOTE','note_hash':note['hash']})
        self.reader.save_summary_draft(aid,'Public adopted summary')
        self.assertEqual(self.repository.ref_updates,before)
        self.reader.adopt_summary(aid)
        self.assertGreater(self.repository.ref_updates,before)
        fresh=CloudReadingStore('/missing','/no-runtime',self.content);fresh.initialize()
        self.assertTrue(fresh.article(aid)['bookmarked'])
        self.assertEqual(fresh.note(aid)['text'],'PRIVATE UPDATED NOTE')
        self.assertIn('Public adopted summary',fresh.path(f'认知阅读/文章资料/{aid}/详细总结.md').read_text())
        self.assertNotIn('PRIVATE UPDATED NOTE',json.dumps(self.repository.commits[self.repository.head]['files']))
    def test_lost_github_success_response_recovers_without_duplicate_publication(self):
        aid=self.source_article();self.migrate_files()
        self.reader.save_summary_draft(aid,'Recovered public summary')
        before=self.repository.ref_updates;self.repository.lose_response=True
        with self.assertRaises(Problem):self.reader.adopt_summary(aid)
        self.assertEqual(self.repository.ref_updates,before+1)
        self.assertFalse(self.reader.article(aid)['summary_draft']['adopted'])
        fresh=CloudReadingStore('/missing','/missing',self.content);fresh.initialize()
        self.assertTrue(fresh.article(aid)['summary_draft']['adopted'])
        self.assertEqual(self.repository.ref_updates,before+1)
        self.assertIn('Recovered public summary',fresh.path(f'认知阅读/文章资料/{aid}/详细总结.md').read_text())
    def test_database_interruption_after_github_commit_recovers_atomically(self):
        aid=self.source_article();self.migrate_files()
        self.reader.save_summary_draft(aid,'Atomic public summary')
        original=self.reader.conn
        class Interrupted:
            def __init__(self,wrapped):self.wrapped=wrapped
            def execute(self,sql,params=None):
                if sql.startswith('INSERT INTO cloud_documents '):raise RuntimeError('isolated DB interruption')
                return self.wrapped.execute(sql,params)
            def __getattr__(self,name):return getattr(self.wrapped,name)
        @contextmanager
        def broken():
            with original() as connection:yield Interrupted(connection)
        before=self.repository.ref_updates
        with patch.object(self.reader,'conn',broken),self.assertRaises(RuntimeError):self.reader.adopt_summary(aid)
        self.assertFalse(self.reader.article(aid)['summary_draft']['adopted'])
        self.assertEqual(self.repository.ref_updates,before+1)
        fresh=CloudReadingStore('/missing','/missing',self.content);fresh.initialize()
        self.assertTrue(fresh.article(aid)['summary_draft']['adopted'])
        self.assertEqual(self.repository.ref_updates,before+1)
    def test_external_edit_keeps_immutable_reading_and_blocks_overwrite(self):
        aid=self.source_article();self.migrate_files()
        path=f'认知阅读/文章资料/{aid}/中文导读.md'
        baseline=self.reader.path(path).read_text();old=self.repository.head;sha=self.repository.sha()
        files=dict(self.repository.commits[old]['files']);files[path]='EXTERNAL EDIT'
        self.repository.commits[sha]={'files':files,'parents':[old]};self.repository.head=sha
        article=self.reader.article(aid)
        with self.assertRaises(Problem):self.reader.save_guide(aid,'new guide',article['hashes'][path])
        fresh=CloudReadingStore('/missing','/missing',self.content);fresh.initialize()
        self.assertEqual(fresh.path(path).read_text(),baseline)
        self.assertEqual(self.repository.commits[self.repository.head]['files'][path],'EXTERNAL EDIT')
    def test_changed_source_rejects_old_preview_and_preserves_target(self):
        report=preview(self.course.documents,self.root)
        with (self.root/MODULE/'学习规划.md').open('a') as f:f.write('\nchanged')
        with self.assertRaises(Problem):apply(self.course.documents,self.root,report['token'])
        self.assertIsNone(self.course.documents.metadata(MODULE+'/学习规划.md'))
