"""Collection admission uses one PostgreSQL transaction, with durable idempotency."""
import asyncio
import copy
import threading
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from cloud_fixtures import AsyncCloudFixture
from copilot.core import Problem
from reading.service import Reader
from reading.store import DEFAULT


class ReadingStartupTests(AsyncCloudFixture):
    async def asyncSetUp(self):
        self.store=self.new_reading();self.store.initialize()

    async def test_supplied_preferences_need_one_connection_and_no_default_lookup(self):
        reader=Reader(self.store)
        try:
            with patch.object(self.store,'conn',wraps=self.store.conn) as connections, \
                 patch.object(self.store,'prefs',side_effect=AssertionError('unnecessary default read')):
                job=reader.begin({'key':'fast-start','preferences':{**DEFAULT,'enabled':False}})
            self.assertEqual(job['state'],'queued')
            self.assertEqual(connections.call_count,1)
            self.assertEqual(len(reader.tasks),1)
            replay=reader.begin({'key':'fast-start','preferences':{**DEFAULT,'enabled':False}})
            self.assertEqual(replay['id'],job['id'])
            self.assertEqual(len(reader.tasks),1)
            with self.assertRaises(Problem) as conflict:
                reader.begin({'key':'fast-start','preferences':{**DEFAULT,'count':1}})
            self.assertEqual(conflict.exception.code,'conflict')
            with self.assertRaises(Problem) as busy:
                reader.begin({'key':'another-start','preferences':DEFAULT})
            self.assertEqual(busy.exception.code,'busy')
        finally:await reader.shutdown()

    async def test_concurrent_collection_admission_still_allows_only_one_job(self):
        first={'id':'job-one','type':'job','kind':'collect','state':'queued','request':'one','preferences':DEFAULT}
        def enqueue(job):
            try:return self.new_reading().enqueue_collection(job)[1]
            except Problem as error:return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(enqueue,[first,{**copy.deepcopy(first),'id':'job-two','request':'two'}]))
        self.assertEqual(results.count(True),1)
        self.assertEqual(results.count('busy'),1)

    async def test_admission_does_not_treat_articles_or_finished_jobs_as_active(self):
        self.store.put('reading_records','article-test',{'id':'article-test','type':'article','state':'running'})
        self.store.put('reading_records','job-finished',{'id':'job-finished','type':'job','state':'ready'})
        job={'id':'job-new','type':'job','kind':'collect','state':'queued','request':'new','preferences':DEFAULT}
        saved,created=self.store.enqueue_collection(job)
        self.assertTrue(created)
        self.assertEqual(saved['id'],'job-new')

    async def test_legacy_pdf_content_is_preserved_during_admission(self):
        content='old PDF stream\x00data and a literal \\u0000 sequence'
        for key,kind,state in [('article-pdf','article','running'),('job-pdf','job','failed')]:
            self.store.put('reading_records',key,{'id':key,'type':kind,'state':state,'full_content':content})
        job={'id':'job-after-pdf','type':'job','kind':'collect','state':'queued','request':'after-pdf','preferences':DEFAULT}
        saved,created=self.store.enqueue_collection(job)
        self.assertTrue(created)
        self.assertEqual(saved['id'],job['id'])
        self.assertEqual(self.store.record('article-pdf')['full_content'],content)
        self.assertEqual(self.store.record('job-pdf')['full_content'],content)

    async def test_deferred_job_is_durable_before_launch_and_replays_do_not_relaunch(self):
        reader=Reader(self.store)
        data={'key':'deferred','preferences':{**DEFAULT,'enabled':False}}
        job,created=reader.begin(data,defer=True)
        self.assertTrue(created)
        self.assertFalse(reader.tasks)
        self.assertEqual(self.store.record(job['id'])['state'],'queued')
        replay,created=reader.begin(data,defer=True)
        self.assertFalse(created)
        self.assertEqual(replay['id'],job['id'])
        reader.launch(job['id']);reader.launch(job['id'])
        self.assertEqual(len(reader.tasks),1)
        await reader.shutdown()

    async def test_cancel_before_background_launch_cannot_restart_the_job(self):
        reader=Reader(self.store)
        job,created=reader.begin({'key':'cancel-before-launch','preferences':DEFAULT},defer=True)
        self.assertTrue(created)
        reader.cancel(job['id'])
        reader.launch(job['id'])
        await asyncio.gather(*list(reader.tasks.values()))
        self.assertEqual(self.store.record(job['id'])['state'],'cancelled')

    async def test_slow_worker_store_read_does_not_block_the_event_loop(self):
        entered=threading.Event();release=threading.Event()
        def record(jid):
            entered.set();release.wait(2)
            return {'state':'cancelled'}
        reader=Reader(SimpleNamespace(record=record))
        reader.launch('job-slow-read')
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait,1))
            self.assertFalse(reader.tasks['job-slow-read'].done())
        finally:
            release.set()
            await reader.shutdown()
