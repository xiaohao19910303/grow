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
    def __init__(self):self.calls=0;self.release=asyncio.Event();self.first=asyncio.Event();self.fail=False;self.feedback=[];self.include_snapshot=True
    def generate(self,*args,**kwargs):return self.stream(False,json.loads(json.dumps(self.feedback)))
    def generate_advanced(self,*args,**kwargs):return self.stream(True)
    async def stream(self,advanced,feedback=None):
        self.calls+=1;yield event('content',{'text':'第一段'});self.first.set()
        await self.release.wait()
        if self.fail:yield event('error',{'message':'模拟中断'});return
        yield event('complete',{'content':'第一段\n完整结果',**({'lesson_no':9,'draft':{'content':'第一段\n完整结果','sources':'','errors':[]}} if advanced else {'feedback_snapshot':feedback} if self.include_snapshot else {})})

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
    async def test_summary_keeps_generation_feedback_when_records_change_and_request_replays(self):
        original=[{'lesson_no':1,'key_learnings':'生成前的反馈','feeling_tags':['有收获']}]
        self.model.feedback=json.loads(json.dumps(original))
        job=await self.jobs.submit('summary','snapshot-request',{'scope':'full_course'},AI)
        await self.model.first.wait()
        self.model.feedback[0]['key_learnings']='生成期间的新反馈'
        self.model.feedback[0]['feeling_tags'].append('修改')
        self.model.release.set();done=await self.finish(job['id'])
        replay=await self.jobs.submit('summary','snapshot-request',{'scope':'full_course'},AI)
        self.assertEqual(replay['result_id'],done['result_id']);self.assertEqual(self.model.calls,1)
        with self.store.conn() as c:
            rows=c.execute('SELECT feedback_snapshot FROM copilot_summaries').fetchall()
        self.assertEqual(len(rows),1)
        self.assertEqual(json.loads(rows[0][0]),original)
    async def test_missing_feedback_snapshot_fails_without_saving_a_report(self):
        self.model.include_snapshot=False;self.model.release.set()
        job=await self.jobs.submit('summary','missing-snapshot',{'scope':'full_course'},AI)
        self.assertEqual((await self.finish(job['id']))['state'],'failed')
        with self.store.conn() as c:self.assertEqual(c.execute('SELECT count(*) FROM copilot_summaries').fetchone()[0],0)
    async def test_actual_summary_generator_passes_its_frozen_feedback_through_the_worker(self):
        from copilot.summary import SummaryGenerator
        original={'lesson_no':1,'mastery_level':'fully_understood','value_rating':3,
                  'key_learnings':'生成前的收获','feeling_tags':['清晰']}
        feedback=[json.loads(json.dumps(original)),{**original,'lesson_no':2,'key_learnings':'未完成课次'}]
        self.store._scan=lambda:{'lessons':[{'lesson_no':1,'topic':'证据','learning_state':'completed'},
                                          {'lesson_no':2,'topic':'因果','learning_state':'pending'}]}
        self.store.list_feedback=lambda module,round_id:feedback
        captured=[];first=asyncio.Event();release=asyncio.Event()
        class Transport:
            async def stream(self,messages,cfg):
                captured.append(messages);yield {'text':'基于本人反馈的总结'};first.set()
                await release.wait();yield {'done':True}
        self.jobs=BackgroundGenerations(self.store,SummaryGenerator(self.store,Transport()))
        job=await self.jobs.submit('summary','real-generator-snapshot',{'scope':'full_course'},AI)
        await asyncio.wait_for(first.wait(),2)
        feedback[0]['key_learnings']='生成期间修改的收获';feedback[0]['feeling_tags'].append('修改')
        release.set();done=await self.finish(job['id'])
        self.assertEqual(done['state'],'ready')
        with self.store.conn() as c:
            saved=c.execute('SELECT content,feedback_snapshot FROM copilot_summaries').fetchone()
        self.assertEqual(saved['content'],'基于本人反馈的总结')
        self.assertEqual(json.loads(saved['feedback_snapshot']),[original])
        self.assertIn(original['key_learnings'],captured[0][-1]['content'])
        self.assertNotIn('未完成课次',captured[0][-1]['content'])
        self.assertEqual((await self.jobs.submit('summary','real-generator-snapshot',{'scope':'full_course'},AI))['result_id'],done['result_id'])
        self.assertEqual(len(captured),1)
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
