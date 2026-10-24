"""Dormant C3 cutover via real HTTP, two PG schemas and Node/Python restarts."""
from contextvars import copy_context
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from unittest.mock import patch
import httpx

from test_action_source_http import HTTPDeliveryContract
from test_action_p0_sources import CourseReceiptFixture
from test_legacy_cloud_api import CloudHTTPFixture
from tenancy import current_user
import action_plans as actions
from action_link import state,encoded
from action_handoff_coordinator import preflight_v2,stage_v2,finish_v2,revalidate_v2


class CutoverCases:
    start_zook=HTTPDeliveryContract.start_zook
    stop_zook=HTTPDeliveryContract.stop_zook
    cleanup_zook=HTTPDeliveryContract.cleanup_zook
    control=HTTPDeliveryContract.control

    def setUp(self):
        super().setUp()
        self.zook=Path(os.environ['TEST_ZOOK_WORKTREE']);self.zschema='source_http_'+uuid.uuid4().hex;self.control_token=uuid.uuid4().hex
        env=patch.dict(os.environ,{'GROW_ACTION_BRIDGE_SECRET':'TEST_ONLY_SOURCE_HTTP_SECRET_0123456789'})
        env.start();self.addCleanup(env.stop);self.addCleanup(self.cleanup_zook);self.start_zook()
        token=current_user.set({'id':'grow-fixture','schema_name':self.schema,'is_owner':1})
        self.addCleanup(current_user.reset,token)
        self.publisher=getattr(self,'s',None) or self.reader.documents

    def send(self,source,body):
        return signed_send(self.url,self.control_token,source,body)

    def test_cutover_lost_response_blocks_sources_then_recovers_after_both_process_restarts(self):
        # Confirmation before preflight must be in the package exactly once.
        self.assertEqual(self.confirm(key='cutover-before').status_code,200)
        p=preflight_v2('grow-fixture','binding-fixture',self.send)
        self.assertEqual(stage_v2('grow-fixture',p['preview_id'])['phase'],'pending')
        with actions.connection() as c:before=state(c);self.assertEqual(before[0]['phase'],'pending')
        # Source confirmation during pending is explicitly uncommitted, including private source SQL.
        with patch.object(self.publisher,'publish',side_effect=AssertionError('pending confirmation must not publish')):
            self.assertEqual(self.confirm(key='cutover-pending-new').status_code,503)
        self.control('control',{'drop':True})
        with self.assertRaises(httpx.HTTPError):finish_v2('grow-fixture',self.send)
        with actions.connection() as c:self.assertEqual(state(c),before)
        self.assertEqual(self.control('workspace')['data']['plans'][0]['status'],'completed')
        self.stop_zook();self.start_zook()
        result=subprocess.run([sys.executable,str(Path(__file__).with_name('retry_action_handoff_fixture.py'))],
            env={**os.environ,'TEST_GROW_SOURCE_SCHEMA':self.schema,'TEST_HANDOFF_URL':self.url,'TEST_HANDOFF_TOKEN':self.control_token},capture_output=True,text=True,timeout=25)
        self.assertEqual(result.returncode,0,result.stderr)
        with actions.connection() as c:
            final,backup=state(c);self.assertEqual(final['phase'],'active');self.assertEqual(backup,before[1])
            self.assertEqual(c.execute('SELECT count(*) FROM action_executions').fetchone()[0],1)
        remote=self.control('workspace')['data'];self.assertEqual(len(remote['records']),1)
        self.assertEqual(finish_v2('grow-fixture',self.send)['phase'],'active')
        # The blocked key can be confirmed after activation, with a new remote proof;
        # no local fallback write or second completed arrangement occurs.
        after=self.confirm(key='cutover-pending-new')
        self.assertEqual(after.status_code,200,after.text)
        self.assertEqual(len(self.control('workspace')['data']['records']),1)

    def test_source_change_invalidates_preflight_without_freeze_and_failed_remote_commit_is_retryable(self):
        p=preflight_v2('grow-fixture','binding-fixture',self.send)
        self.assertEqual(self.confirm(key='cutover-new-between-preview-and-stage').status_code,200)
        with self.assertRaises(actions.ActionError):stage_v2('grow-fixture',p['preview_id'])
        with actions.connection() as c:self.assertEqual(state(c)[0]['phase'],'local')
        p=preflight_v2('grow-fixture','binding-fixture',self.send);stage_v2('grow-fixture',p['preview_id'])
        self.control('control',{'failHandoffReceipt':True})
        with self.assertRaises(httpx.HTTPStatusError):finish_v2('grow-fixture',self.send)
        row=self.control('workspace');self.assertIsNone(row)
        with actions.connection() as c:original=state(c);self.assertEqual(original[0]['phase'],'pending')
        bad=lambda source,body:{'binding_id':'other'}
        with self.assertRaises(actions.ActionError):finish_v2('grow-fixture',bad)
        with actions.connection() as c:self.assertEqual(state(c),original)
        self.assertEqual(finish_v2('grow-fixture',self.send)['phase'],'active')

    def test_inflight_source_publication_finishes_before_cutover_lock_without_deadlock(self):
        p=preflight_v2('grow-fixture','binding-fixture',self.send)
        entered=threading.Event();release=threading.Event();publish=self.publisher.publish
        def delayed(*args,**kwargs):entered.set();self.assertTrue(release.wait(8));return publish(*args,**kwargs)
        context=copy_context()
        with patch.object(self.publisher,'publish',side_effect=delayed),ThreadPoolExecutor(2) as pool:
            source=pool.submit(context.run,self.confirm,'cutover-inflight')
            self.assertTrue(entered.wait(5))
            stage_context=copy_context();stage=pool.submit(stage_context.run,stage_v2,'grow-fixture',p['preview_id'])
            try:
                self.wait_for_cutover_lock()
                self.assertFalse(stage.done())
            finally:release.set()
            self.assertEqual(source.result(timeout=10).status_code,200)
            with self.assertRaises(actions.ActionError):stage.result(timeout=10)
        with actions.connection() as c:self.assertEqual(state(c)[0]['phase'],'local')
        p=preflight_v2('grow-fixture','binding-fixture',self.send);stage_v2('grow-fixture',p['preview_id'])
        self.assertEqual(finish_v2('grow-fixture',self.send)['phase'],'active')


    def wait_for_cutover_lock(self):
        for _ in range(200):
            with actions.connection() as c:
                row=c.execute("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND NOT granted AND classid=((hashtextextended(current_schema() || ':action-source-cutover',0)>>32)&4294967295)::oid AND objid=(hashtextextended(current_schema() || ':action-source-cutover',0)&4294967295)::oid").fetchone()
            if row[0]:return
            time.sleep(.01)
        self.fail('stage never waited on the owned source-cutover fence')

    def local_operation(self,action,**values):
        response=self.client.post('/api/action-plans/'+self.plan['id']+'/operations',headers=self.headers,
            json={'key':'cutover-local-'+action,'revision':self.plan['revision'],'action':action,**values})
        self.assertEqual(response.status_code,200,response.text);return response.json()

    def test_imported_pending_event_reconciles_via_durable_outbox_after_running_minutes_are_saved(self):
        started=self.local_operation('start')
        saved=self.confirm(key='cutover-running-confirm');self.assertEqual(saved.status_code,200,saved.text)
        self.assertIn('arrangement_sync_error',saved.json());event=saved.json()['source_event_id']
        p=preflight_v2('grow-fixture','binding-fixture',self.send);stage_v2('grow-fixture',p['preview_id']);finish_v2('grow-fixture',self.send)
        from action_source_delivery import retry_due
        retry_due(force=True)
        with actions.connection() as c:self.assertEqual(c.execute('SELECT state FROM action_source_outbox WHERE event_id=?',(event,)).fetchone()[0],'delivered')
        remote=self.control('workspace')['data'];running=remote['records'][0];plan=remote['plans'][0]
        self.control('action',{'path':'/'+plan['id']+'/operations','body':{'key':'cutover-remote-finish','action':'finish','revision':plan['revision'],'execution_id':running['id'],'actual_minutes':12}})
        retry_due(force=True);retry_due(force=True)
        remote=self.control('workspace')['data']
        self.assertEqual(len(remote['records']),2);self.assertEqual(sum(r['actual_minutes'] for r in remote['records']),12)
        self.assertEqual(remote['content_events'][0]['consumed_by'],self.plan['id'])
        replay=self.confirm(key='cutover-running-confirm')
        self.assertEqual(replay.json()['completed_arrangements'],[self.plan['id']]);self.assertEqual(replay.json()['source_event_id'],event)
        with actions.connection() as c:
            self.assertEqual(c.execute('SELECT state FROM action_source_outbox WHERE event_id=?',(event,)).fetchone()[0],'completed')
            self.assertEqual(c.execute('SELECT count(*) FROM action_executions').fetchone()[0],1)

    def test_local_stage_and_activation_failures_preserve_fence_backup_and_transactional_outbox(self):
        self.assertEqual(self.confirm(key='cutover-local-failure').status_code,200)
        p=preflight_v2('grow-fixture','binding-fixture',self.send)
        with actions.connection() as c:local=state(c)
        with patch('action_handoff_coordinator.put',side_effect=RuntimeError('stage storage failure')):
            with self.assertRaises(RuntimeError):stage_v2('grow-fixture',p['preview_id'])
        with actions.connection() as c:self.assertEqual(state(c),local)
        stage_v2('grow-fixture',p['preview_id'])
        with actions.connection() as c:frozen=state(c)
        with patch('action_handoff_coordinator.put',side_effect=RuntimeError('activation storage failure')):
            with self.assertRaises(RuntimeError):finish_v2('grow-fixture',self.send)
        with actions.connection() as c:
            self.assertEqual(state(c),frozen)
            self.assertEqual(c.execute('SELECT count(*) FROM action_source_outbox').fetchone()[0],0)
        self.assertEqual(finish_v2('grow-fixture',self.send)['phase'],'active')
        with actions.connection() as c:self.assertEqual(c.execute('SELECT count(*) FROM action_source_outbox').fetchone()[0],1)

    def test_stale_target_repreflight_never_unfreezes_source_or_changes_backup(self):
        p=preflight_v2('grow-fixture','binding-fixture',self.send);stage_v2('grow-fixture',p['preview_id'])
        with actions.connection() as c:before=state(c)
        self.control('action',{'body':{'key':'target-between-stage-and-import','title':'目标已有新事项','period':'day','completion_mode':'check'}})
        with self.assertRaises(httpx.HTTPStatusError):finish_v2('grow-fixture',self.send)
        self.assertEqual(self.confirm(key='cutover-stale-target-pending').status_code,503)
        revalidate_v2('grow-fixture',self.send)
        with actions.connection() as c:
            revised,backup=state(c);self.assertEqual(backup,before[1]);self.assertEqual(revised['phase'],'pending')
            self.assertGreater(revised['target_version'],before[0]['target_version'])
        self.assertEqual(finish_v2('grow-fixture',self.send)['phase'],'active')
        self.assertEqual(len(self.control('workspace')['data']['plans']),2)

    def test_invalid_receipts_and_mutated_backup_never_activate_or_import(self):
        for patch_receipt in ({'validated':False},{'imported_at':'2026-10-21T12:00:00Z'},{'unknown_receipt_field':True},{'target_user_id':'x'*161},{'target_user_id':''},{'target_version':False},{'source_counts':dict.fromkeys(('plans','records','reviews','reports','operations','claims','content_sources','content_events'),False)}):
            def bad(source,body):return {**self.send(source,body),**patch_receipt}
            with self.assertRaises(actions.ActionError):preflight_v2('grow-fixture','binding-fixture',bad)
            with actions.connection() as c:self.assertEqual(state(c)[0]['phase'],'local')
        p=preflight_v2('grow-fixture','binding-fixture',self.send);stage_v2('grow-fixture',p['preview_id'])
        with actions.connection() as c:original=state(c)
        for patch_receipt in ({'imported_at':{}},{'validated':True},{'unknown_receipt_field':True},{'binding_id':'another-binding'},{'source_counts':{}}):
            def bad(source,body):return {**self.send(source,body),**patch_receipt}
            with self.assertRaises(actions.ActionError):finish_v2('grow-fixture',bad)
            with actions.connection() as c:self.assertEqual(state(c),original)
        # Even a locally damaged immutable package is not sent to the target.
        with actions.connection(True,allow_link=True) as c:
            backup=original[1];backup['plans'][0]['title']='tampered'
            c.execute('UPDATE action_link_state SET backup=? WHERE id=1',(encoded(backup),))
        with self.assertRaises(actions.ActionError):finish_v2('grow-fixture',lambda *_:self.fail('damaged package was sent'))


    def test_crashed_source_journal_blocks_freeze_until_original_request_recovers(self):
        p=preflight_v2('grow-fixture','binding-fixture',self.send)
        with patch.object(self.publisher,'finish',side_effect=RuntimeError('source worker crashed before SQL commit')):
            with self.assertRaises(RuntimeError):self.confirm(key='cutover-durable-publication-crash')
        with self.assertRaises(actions.ActionError) as pending:stage_v2('grow-fixture',p['preview_id'])
        self.assertEqual(pending.exception.extra.get('reason'),'SOURCE_PUBLICATION_PENDING')
        with actions.connection() as c:
            self.assertEqual(state(c)[0]['phase'],'local')
            self.assertEqual(c.execute('SELECT count(*) FROM action_content_events').fetchone()[0],0)
        with self.assertRaises(actions.ActionError):preflight_v2('grow-fixture','binding-fixture',lambda *_:self.fail('pending publication must be detected before transport'))
        recovered=self.confirm(key='cutover-durable-publication-crash');self.assertEqual(recovered.status_code,200,recovered.text)
        p=preflight_v2('grow-fixture','binding-fixture',self.send);stage_v2('grow-fixture',p['preview_id']);finish_v2('grow-fixture',self.send)
        remote=self.control('workspace')['data'];self.assertEqual(len(remote['records']),1)
        self.assertEqual(remote['content_events'][0]['event_id'],recovered.json()['source_event_id'])


    def test_concurrent_finish_has_one_local_activation_and_public_writes_stay_closed(self):
        self.assertEqual(self.confirm(key='cutover-concurrent-finish').status_code,200)
        p=preflight_v2('grow-fixture','binding-fixture',self.send);stage_v2('grow-fixture',p['preview_id'])
        def write():return self.client.post('/api/action-plans',headers=self.headers,json={'key':'cutover-public-write-blocked','title':'不得新增','period':'day','completion_mode':'check'})
        self.assertEqual(write().status_code,503)
        with ThreadPoolExecutor(2) as pool:
            first=copy_context();second=copy_context()
            results=list(pool.map(lambda ctx:ctx.run(finish_v2,'grow-fixture',self.send),(first,second)))
        self.assertTrue(all(r['phase']=='active' for r in results))
        self.assertEqual(write().status_code,409)
        with actions.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM action_plans').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM action_source_outbox').fetchone()[0],1)
        remote=self.control('workspace')['data'];self.assertEqual(len(remote['records']),1);self.assertEqual(len(remote['content_events']),1)


class CourseCutoverTests(CutoverCases,CourseReceiptFixture):pass


class ArticleCutoverTests(CutoverCases,CloudHTTPFixture):
    def setUp(self):
        super().setUp()
        from datetime import datetime,timezone
        from fastapi.testclient import TestClient
        actions.register(self.app)
        timer=patch('action_plans.clock',return_value=datetime(2026,10,19,12,tzinfo=timezone.utc));timer.start();self.addCleanup(timer.stop)
        self.client=TestClient(self.app,base_url='http://localhost');self.addCleanup(self.client.close)
        self.headers={'X-Copilot-Request':'1','X-Grow-Action-Schema':'2'}
        self.target={'kind':'article','course':self.aid};self.publisher=self.reader.documents
        result=self.client.post('/api/action-plans/schedules',headers=self.headers,json={'key':'article-cutover-arrange','title':'文章切换验收','target':self.target,'date':'2026-10-19'})
        self.assertEqual(result.status_code,200,result.text);self.plan=result.json()['plan']

    def confirm(self,key,**updates):
        return self.client.post('/api/reading/articles/'+self.aid+'/personal',headers=self.headers,
            json={'data':{'read':True,'key':key,'origin_action_id':self.plan['id'],**updates}})


def signed_send(url,token,source,body):
    stamp=str(int(time.time()));nonce=str(uuid.uuid4());secret=os.environ['GROW_ACTION_BRIDGE_SECRET']
    signature=hmac.new(secret.encode(),'\n'.join([source,stamp,nonce,encoded(body)]).encode(),hashlib.sha256).hexdigest()
    response=httpx.post(url+'/fixture/handoff',headers={'X-Test-Token':token,'X-Grow-Account-Id':source,'X-Grow-Timestamp':stamp,'X-Grow-Nonce':nonce,'X-Grow-Signature':signature},json=body,timeout=20)
    response.raise_for_status();return response.json()
