"""真实 PostgreSQL 事务与受控模型：恢复、幂等、取消及原输入重试。"""
import asyncio
from datetime import date
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

import db
import ai_evidence
from behavior_report.store import BehaviorReportStore
from copilot.core import Problem
from test_legacy_cloud_schema import PostgreSQLFixture

AI={'api_base_url':'https://provider.example/v1','api_key':'SECRET_TEST_CREDENTIAL','model_name':'fixture'}
SUMMARY={'period':'近7天（2026-10-15 ~ 2026-10-21）','checkins':{'total_days':2},'predictions':{'resolved':0,'accuracy':0}}


class ReportJobsTests(PostgreSQLFixture,unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp();self.store=BehaviorReportStore(Path('/unused'));self.store.initialize()
        self.first=asyncio.Event();self.release=asyncio.Event();self.calls=[]
        self.collect=patch('behavior_report.analyzer.collect_data_summary',return_value=json.loads(json.dumps(SUMMARY))).start()
        self.addCleanup(patch.stopall)
        patch('growth_statistics.shanghai_today',return_value=date(2026,10,21)).start()
        async def model(messages,cfg):
            self.calls.append((messages,dict(cfg)));self.first.set();yield {'text':'已收到的统计分析'}
            await self.release.wait();yield {'text':'；完整报告'};yield {'done':True}
        patch('copilot.transport.qwen_stream',model).start()

    async def asyncTearDown(self):await self.store.shutdown()

    async def finish(self,jid):
        for _ in range(150):
            job=await asyncio.to_thread(self.store.jobs.get,jid)
            if job['state'] not in ('queued','generating'):return job
            await asyncio.sleep(.02)
        self.fail('worker did not finish')

    async def test_key_alias_dedup_reads_and_atomic_result_reference(self):
        job=await self.store.jobs.submit('request-one',7,AI);await asyncio.wait_for(self.first.wait(),3)
        self.assertEqual((await self.store.jobs.submit('request-one',7,None))['id'],job['id'])
        self.assertEqual((await self.store.jobs.submit('request-alias',7,AI))['id'],job['id'])
        self.store.jobs.listing();self.store.jobs.get(job['id']);self.assertEqual(len(self.calls),1)
        with self.assertRaises(Problem):await self.store.jobs.submit('request-one',30,AI)
        with self.assertRaises(Problem):await self.store.jobs.submit('request-one',7,{**AI,'model_name':'changed-model'})
        self.release.set();done=await self.finish(job['id']);self.assertEqual(done['state'],'ready')
        with db.connect() as c:
            saved=ai_evidence.linked(c,'behavior-result',done['result_id'])[0]
            self.assertEqual(saved['messages'],self.calls[0][0])
            self.assertNotIn(AI['api_key'],str([dict(r) for r in c.execute('SELECT * FROM behavior_report_jobs')]))
            self.assertNotIn(AI['api_key'],str(saved))
            self.assertEqual(c.execute('SELECT count(*) FROM behavior_reports').fetchone()[0],1)

    async def test_restart_retains_progress_and_only_explicit_retry_calls_model(self):
        job=await self.store.jobs.submit('restart-one',7,AI);await asyncio.wait_for(self.first.wait(),3)
        other=BehaviorReportStore(Path('/unused'));other.initialize()
        interrupted=other.jobs.get(job['id']);self.assertEqual(interrupted['state'],'interrupted')
        self.assertEqual(len(self.calls),1);self.release.set()
        self.collect.return_value={'period':'NEW INPUT','checkins':{'total_days':99}}
        retry=await other.jobs.submit('restart-retry',7,AI,retry_of=job['id'])
        try:
            for _ in range(150):
                done=other.jobs.get(retry['id'])
                if done['state'] not in ('queued','generating'):break
                await asyncio.sleep(.02)
            self.assertEqual(done['state'],'ready');self.assertEqual(self.collect.call_count,1)
            self.assertEqual(self.calls[-1][0],self.calls[0][0])
            with db.connect() as c:self.assertEqual(ai_evidence.read(c,retry['evidence_snapshot_id'])['parent_id'],job['evidence_snapshot_id'])
        finally:await other.shutdown()

    async def test_cancel_before_commit_does_not_save_or_repeat(self):
        job=await self.store.jobs.submit('cancel-one',7,AI);await asyncio.wait_for(self.first.wait(),3)
        cancelled=await self.store.jobs.cancel(job['id']);self.assertEqual(cancelled['state'],'cancelled')
        self.assertEqual((await self.store.jobs.submit('cancel-one',7,AI))['state'],'cancelled')
        with db.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM behavior_reports').fetchone()[0],0)
        self.assertEqual(len(self.calls),1)

    async def test_snapshot_failure_rolls_back_before_starting_the_model(self):
        original=ai_evidence.freeze
        def failure(*args,**kwargs):original(*args,**kwargs);raise RuntimeError('interrupted snapshot commit')
        with patch('behavior_report.jobs.freeze',side_effect=failure),self.assertRaises(RuntimeError):
            await self.store.jobs.submit('snapshot-failure',7,AI)
        self.assertEqual(self.calls,[])
        with db.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM ai_evidence_snapshots').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM behavior_report_jobs').fetchone()[0],0)

    async def test_result_link_failure_rolls_back_report_but_keeps_input_and_progress(self):
        self.release.set()
        with patch('behavior_report.jobs.bind',side_effect=RuntimeError('commit interruption')):
            job=await self.store.jobs.submit('save-failure',7,AI);done=await self.finish(job['id'])
        self.assertEqual(done['state'],'failed');self.assertIn('统计分析',done['raw'])
        with db.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM behavior_reports').fetchone()[0],0)
            self.assertEqual(ai_evidence.read(c,job['evidence_snapshot_id'])['messages'],self.calls[0][0])

    async def test_delete_report_cleans_task_and_result_snapshot_references(self):
        self.release.set();job=await self.store.jobs.submit('delete-one',7,AI);done=await self.finish(job['id'])
        self.assertTrue(self.store.delete_report(done['result_id']))
        self.assertTrue(self.store.jobs.get(job['id'])['result_deleted'])
        with db.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM ai_evidence_snapshots').fetchone()[0],0)

    async def test_cross_day_completion_keeps_frozen_analysis_window(self):
        job=await self.store.jobs.submit('cross-day',7,AI);await asyncio.wait_for(self.first.wait(),3)
        with patch('growth_statistics.shanghai_today',return_value=date(2026,10,22)):
            self.release.set();done=await self.finish(job['id'])
        self.assertEqual(self.store.get_report(done['result_id'])['date'],'2026-10-22')
        self.assertEqual(done['data_summary'],SUMMARY)
        self.assertEqual(done['scope_day'],'2026-10-21')

    async def test_concurrent_pages_share_one_capture_and_model_call(self):
        jobs=await asyncio.gather(*(self.store.jobs.submit('parallel-'+str(i),7,AI) for i in range(4)))
        await asyncio.wait_for(self.first.wait(),3)
        self.assertEqual(len({j['id'] for j in jobs}),1)
        self.assertEqual(self.collect.call_count,1);self.assertEqual(len(self.calls),1)
        self.release.set();done=await self.finish(jobs[0]['id'])
        self.assertEqual(done['state'],'ready')
        with db.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM behavior_reports').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM behavior_report_requests').fetchone()[0],4)

    async def test_cancel_racing_with_locked_result_commit_preserves_atomic_ready_state(self):
        locked=threading.Event();release=threading.Event();original=ai_evidence.bind
        def during_commit(*args,**kwargs):
            locked.set()
            if not release.wait(5):raise RuntimeError('test result gate timed out')
            return original(*args,**kwargs)
        self.release.set()
        with patch('behavior_report.jobs.bind',side_effect=during_commit):
            job=await self.store.jobs.submit('commit-race',7,AI)
            self.assertTrue(await asyncio.to_thread(locked.wait,3))
            cancellation=asyncio.create_task(self.store.jobs.cancel(job['id']))
            await asyncio.sleep(.05);release.set()
            current=await asyncio.wait_for(cancellation,5)
        self.assertEqual(current['state'],'ready')
        done=await self.finish(job['id']);self.assertEqual(done['result_id'],current['result_id'])
        with db.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM behavior_reports').fetchone()[0],1)
            self.assertEqual(ai_evidence.linked(c,'behavior-result',done['result_id'])[0]['id'],job['evidence_snapshot_id'])

    async def test_cancel_preserves_chunks_received_since_last_throttled_checkpoint(self):
        received=asyncio.Event()
        async def burst(messages,cfg):
            yield {'text':'第一段'}
            yield {'text':'第二段'}
            received.set();await self.release.wait();yield {'done':True}
        with patch('copilot.transport.qwen_stream',burst):
            job=await self.store.jobs.submit('cancel-last-chunk',7,AI)
            await asyncio.wait_for(received.wait(),3)
            cancelled=await self.store.jobs.cancel(job['id'])
        self.assertEqual(cancelled['state'],'cancelled')
        self.assertEqual(self.store.jobs.get(job['id'])['raw'],'第一段第二段')
