"""Detached workers with real transactions and a blocked, counted model stub."""
import asyncio
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from copilot.core import Problem
from copilot.generation import event
from copilot.background import BackgroundGenerations

AI={'api_base_url':'https://model.example/v1','api_key':'PRIVATE_TEST_KEY','model_name':'fixture'}

class Store:
    def __init__(self,path):
        self.db=path;self.mutex=threading.RLock()
        with self.conn() as c:
            c.executescript('''CREATE TABLE copilot_summaries(id INTEGER PRIMARY KEY AUTOINCREMENT,module_id TEXT,round_id INTEGER,scope TEXT,content TEXT,feedback_snapshot TEXT,created_at TEXT);
                CREATE TABLE copilot_drafts(id TEXT PRIMARY KEY,lesson_no INTEGER,version INTEGER,status TEXT,data TEXT,updated_at TEXT);''')
    @contextmanager
    def conn(self):
        c=sqlite3.connect(self.db);c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()
    @contextmanager
    def lock(self):
        with self.mutex:yield

class Model:
    def __init__(self):self.calls=0;self.release=asyncio.Event();self.first=asyncio.Event();self.fail=False
    def generate(self,*args,**kwargs):return self.stream(False)
    def generate_advanced(self,*args,**kwargs):return self.stream(True)
    async def stream(self,advanced):
        self.calls+=1;yield event('content',{'text':'第一段'});self.first.set()
        await self.release.wait()
        if self.fail:yield event('error',{'message':'模拟中断'});return
        yield event('complete',{'content':'第一段\n完整结果',**({'lesson_no':9,'draft':{'content':'第一段\n完整结果','sources':'','errors':[]}} if advanced else {})})

class BackgroundTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'tasks.db');self.model=Model()
        self.jobs=BackgroundGenerations(self.store,self.model)
    async def asyncTearDown(self):await self.jobs.shutdown()
    async def finish(self,id):
        for _ in range(100):
            job=self.jobs.get(id)
            if job['state'] not in ('queued','generating'):return job
            await asyncio.sleep(.01)
        self.fail('worker did not finish')
    async def test_reload_and_lost_response_replay_do_not_restart_model(self):
        job=await self.jobs.submit('summary','same-request',{'scope':'full_course'},AI)
        await self.model.first.wait()
        self.assertEqual(self.jobs.get(job['id'])['raw'],'第一段')
        replay=await self.jobs.submit('summary','same-request',{'scope':'full_course'},AI)
        self.assertEqual(replay['id'],job['id']);self.assertEqual(self.model.calls,1)
        alias=await self.jobs.submit('summary','different-tab-request',{'scope':'full_course'},AI)
        self.assertEqual(alias['id'],job['id'])
        self.model.release.set();done=await self.finish(job['id'])
        self.assertEqual(done['state'],'ready');self.assertIsNotNone(done['result_id'])
        again=await self.jobs.submit('summary','same-request',{'scope':'full_course'},AI)
        self.assertEqual(again['result_id'],done['result_id']);self.assertEqual(self.model.calls,1)
        self.assertEqual((await self.jobs.submit('summary','different-tab-request',{'scope':'full_course'},AI))['id'],job['id'])
        with self.store.conn() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM copilot_summaries').fetchone()[0],1)
            self.assertNotIn(AI['api_key'],str([tuple(r) for r in c.execute('SELECT * FROM copilot_background_jobs')]))
    async def test_cancel_is_explicit_and_replay_never_regenerates(self):
        job=await self.jobs.submit('summary','cancel-request',{'scope':'full_course'},AI);await self.model.first.wait()
        await self.jobs.cancel(job['id']);done=await self.finish(job['id'])
        self.assertEqual(done['state'],'cancelled');self.assertEqual(done['raw'],'第一段')
        self.assertEqual((await self.jobs.submit('summary','cancel-request',{'scope':'full_course'},AI))['state'],'cancelled')
        self.assertEqual(self.model.calls,1)
        with self.assertRaises(Problem):await self.jobs.submit('advanced','cancel-request',{'summary_content':'different'},AI)
    async def test_advanced_result_and_incomplete_output(self):
        job=await self.jobs.submit('advanced','advanced-request',{'summary_content':'已有总结'},AI)
        await self.model.first.wait();self.model.release.set();done=await self.finish(job['id'])
        with self.store.conn() as c:self.assertEqual(c.execute('SELECT id FROM copilot_drafts').fetchone()[0],done['draft_id'])
        self.model.fail=True
        failed=await self.jobs.submit('summary','failed-request',{'scope':'full_course'},AI)
        self.assertEqual((await self.finish(failed['id']))['state'],'failed')
        with self.store.conn() as c:self.assertEqual(c.execute('SELECT count(*) FROM copilot_summaries').fetchone()[0],0)
    async def test_cancellation_during_result_commit_keeps_successful_result(self):
        started=threading.Event();release=threading.Event();original=self.jobs.complete
        def slow_commit(job,payload):
            started.set();release.wait(3);return original(job,payload)
        with patch.object(self.jobs,'complete',slow_commit):
            job=await self.jobs.submit('summary','commit-race-key',{'scope':'full_course'},AI)
            await self.model.first.wait();self.model.release.set()
            self.assertTrue(await asyncio.to_thread(started.wait,2))
            cancel=asyncio.create_task(self.jobs.cancel(job['id']));await asyncio.sleep(.01);release.set()
            self.assertEqual((await cancel)['state'],'ready')
            with self.store.conn() as c:self.assertEqual(c.execute('SELECT count(*) FROM copilot_summaries').fetchone()[0],1)
    async def test_task_lookup_is_scoped_to_its_account_store(self):
        job=await self.jobs.submit('summary','private-request',{'scope':'full_course'},AI)
        other=BackgroundGenerations(Store(Path(self.tmp.name)/'other-account.db'),Model())
        with self.assertRaises(Problem):other.get(job['id'])
