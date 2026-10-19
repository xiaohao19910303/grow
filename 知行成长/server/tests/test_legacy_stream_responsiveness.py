"""Cloud streams remain cancellable without one PostgreSQL write per token."""
import asyncio
from unittest.mock import patch
from copilot.generation import Generator, SEPARATOR
from reading.service import Reader
from test_legacy_cloud_content import CloudFixture, OWN
from test_legacy_cloud_api import COURSE


class LegacyStreamResponsivenessTests(CloudFixture):
    def test_course_buffered_output_yields_and_bounds_checkpoint_writes(self):
        self.migrate_files();observed=[]
        async def model(messages,cfg):
            for index,char in enumerate(COURSE+SEPARATOR+'摘要 [来源](https://example.org/source)'):
                if index==5:asyncio.get_running_loop().call_soon(lambda:observed.append(self.course.draft(did)['status']))
                yield {'text':char}
            yield {'done':True}
        generator=Generator(self.course,model);did,fresh=generator.begin(3,'buffered-course',OWN)
        async def consume():
            async for _ in generator.stream(did,fresh):pass
        with patch.object(generator,'persist',wraps=generator.persist) as writes:asyncio.run(consume())
        draft=self.course.draft(did)
        self.assertEqual(observed,['generating'])
        self.assertEqual(draft['status'],'ready',draft['errors'])
        self.assertEqual(draft['content'],COURSE)
        self.assertLess(writes.call_count,10)

    def test_course_buffered_output_can_be_cancelled(self):
        self.migrate_files();produced=[]
        async def model(messages,cfg):
            for index in range(300):
                if index==5:asyncio.get_running_loop().call_soon(generator.cancel,did)
                produced.append(index);yield {'text':'x'}
            yield {'done':True}
        generator=Generator(self.course,model);did,fresh=generator.begin(3,'cancel-buffered-course',OWN)
        async def consume():
            try:
                async for _ in generator.stream(did,fresh):pass
            except asyncio.CancelledError:pass
        asyncio.run(consume())
        self.assertEqual(self.course.draft(did)['status'],'cancelled')
        self.assertLess(len(produced),300)

    def test_reading_buffered_output_yields_and_bounds_checkpoint_writes(self):
        aid=self.source_article();self.migrate_files();observed=[];raw='## 核心观点\n'+('教学示例。'*150)
        async def model(messages,cfg):
            for index,char in enumerate(raw):
                if index==5:asyncio.get_running_loop().call_soon(lambda:observed.append(self.reader.record('job-buffered-reading')['state']))
                yield {'text':char}
            yield {'done':True}
        service=Reader(self.reader,transport=model)
        async def consume():
            job=service.begin({'kind':'guide','key':'buffered-reading','article_id':aid,'ai_config':OWN})
            await service.tasks[job['id']]
        with patch.object(self.reader,'put',wraps=self.reader.put) as writes:asyncio.run(consume())
        self.assertEqual(observed,['running'])
        self.assertEqual(self.reader.record('job-buffered-reading')['state'],'ready')
        self.assertIn(raw,self.reader.documents.read('认知阅读/文章资料/'+aid+'/中文导读.md'))
        self.assertLess(writes.call_count,10)

    def test_reading_buffered_output_can_be_cancelled_without_publishing(self):
        aid=self.source_article();self.migrate_files();produced=[]
        path='认知阅读/文章资料/'+aid+'/中文导读.md';before=self.reader.documents.read(path)
        async def model(messages,cfg):
            for index in range(300):
                if index==5:asyncio.get_running_loop().call_soon(service.cancel,'job-cancel-buffered-reading')
                produced.append(index);yield {'text':'x'}
            yield {'done':True}
        service=Reader(self.reader,transport=model)
        async def consume():
            job=service.begin({'kind':'guide','key':'cancel-buffered-reading','article_id':aid,'ai_config':OWN})
            await service.tasks[job['id']]
        asyncio.run(consume())
        self.assertEqual(self.reader.record('job-cancel-buffered-reading')['state'],'cancelled')
        self.assertLess(len(produced),300)
        self.assertEqual(self.reader.documents.read(path),before)

    def test_markdown_line_break_spaces_around_source_marker_are_accepted(self):
        self.migrate_files()
        async def model(messages,cfg):
            yield {'text':COURSE+'\n<!-- COPILOT_SOURCES -->  \n摘要 [来源](https://example.org/source)'}
            yield {'done':True}
        generator=Generator(self.course,model);did,fresh=generator.begin(3,'markdown-source-marker',OWN)
        async def consume():
            async for _ in generator.stream(did,fresh):pass
        asyncio.run(consume())
        draft=self.course.draft(did)
        self.assertEqual(draft['status'],'ready',draft['errors'])
        self.assertEqual(draft['content'],COURSE)
        self.assertEqual(draft['sources'],'摘要 [来源](https://example.org/source)')
