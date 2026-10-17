"""Recover imported article indexes without trusting local runtime files."""
import asyncio
import copy
from datetime import datetime
from cloud_fixtures import CloudFixture
from copilot.core import Problem,encoded,now
from legacy_files import preview,apply
from reading.sources import CLASSICS,identify,choose
from reading.store import DEFAULT,TABLE
from reading.service import Reader


class ReadingMigrationTests(CloudFixture):
    def setUp(self):
        super().setUp();self.store=self.new_reading();self.store.initialize()
        self.article={**copy.deepcopy(CLASSICS[0]),'id':identify(CLASSICS[0]['url']),'type':'article','saved_at':now(),'read':True,'bookmarked':True,'read_later':False}
        aid=self.article['id'];folder=self.root/'认知阅读/文章资料'/aid;folder.mkdir(parents=True)
        for name,text in {'文章信息.json':encoded(self.article),'中文导读.md':'保留的中文导读','原文.md':'Preserved article content','详细总结.md':'保留的总结'}.items():(folder/name).write_text(text)
        notes=self.root/'认知阅读/阅读笔记';notes.mkdir();(notes/(aid+'.md')).write_text('PRIVATE PRESERVED NOTE')
        self.original={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        report=preview(self.store.documents,self.root);apply(self.store.documents,self.root,report['token'])

    def test_missing_index_recovers_full_text_notes_states_and_deduplication(self):
        aid=self.article['id']
        self.assertEqual(self.store.article(aid)['full_content'],'Preserved article content')
        with self.store.conn() as c:c.execute('DELETE FROM reading_records WHERE id=?',(aid,))
        head=self.repo.head;self.store.initialize();recovered=self.store.article(aid)
        self.assertEqual(self.repo.head,head)
        self.assertTrue(recovered['read']);self.assertTrue(recovered['bookmarked'])
        self.assertEqual(recovered['full_content'],'Preserved article content');self.assertEqual(recovered['guide'],'保留的中文导读')
        self.assertEqual(self.store.note(aid)['text'],'PRIVATE PRESERVED NOTE')
        self.assertEqual({p:p.read_bytes() for p in self.original},self.original)
        self.assertEqual(choose([self.article],DEFAULT,{x['id'] for x in self.store.articles()},now()[:10]),[])
        self.assertNotIn('PRIVATE PRESERVED NOTE',str(self.repo.commits))

    def test_existing_personal_state_and_immutable_guide_win_over_external_edits(self):
        aid=self.article['id'];self.store.update_personal(aid,{'read_later':True})
        self.external(f'认知阅读/文章资料/{aid}/中文导读.md','external edit')
        self.store.restore_article_index();self.assertTrue(self.store.article(aid)['read_later'])
        self.assertEqual(self.store.article(aid)['guide'],'保留的中文导读')

    def test_invalid_article_url_is_preserved_without_importing(self):
        bad={**self.article,'id':'article-'+'0'*20,'url':'javascript:alert(1)'}
        folder=self.root/'认知阅读/文章资料'/bad['id'];folder.mkdir();source=folder/'文章信息.json';source.write_text(encoded(bad))
        report=preview(self.store.documents,self.root)
        with self.assertRaises(Problem) as error:apply(self.store.documents,self.root,report['token'])
        self.assertEqual(error.exception.code,'migration_invalid');self.assertEqual(source.read_text(),encoded(bad))
        self.assertIsNone(self.store.optional(bad['id']))

    def test_daily_collection_after_recovery_does_not_overwrite_saved_articles(self):
        aid=self.article['id'];self.store.restore_article_index();before=self.store.article(aid)
        self.store.save_preferences({**DEFAULT,'mode':'classic'})
        async def run():
            reader=Reader(self.store);job=reader.daily_tick(datetime.fromisoformat(now()).replace(hour=23))
            await asyncio.gather(*list(reader.tasks.values()));return self.store.record(job['id'])
        result=asyncio.run(run());self.assertEqual(result['state'],'ready',result.get('error'))
        self.assertNotIn(aid,result['saved_ids']);self.assertTrue(result['saved_ids'])
        self.assertEqual(self.store.article(aid),before);self.assertEqual({p:p.read_bytes() for p in self.original},self.original)
