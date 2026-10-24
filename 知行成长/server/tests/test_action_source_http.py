"""Real HTTP + two disposable PostgreSQL schemas, with process/fault recovery."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest
import uuid
from urllib.parse import quote
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit
import httpx
import psycopg2
from psycopg2.extensions import parse_dsn

import action_plans as actions
from action_link import call,put,state
from action_source_delivery import retry_due,prepare
from tenancy import current_user
from test_action_p0_sources import CourseReceiptFixture
from test_legacy_cloud_api import CloudHTTPFixture
from fastapi.testclient import TestClient


def source_database_url(dsn):
    """Pass the explicit disposable connection to pg without libpq defaults."""
    settings=parse_dsn(dsn)
    allowed={'host','port','user','password','dbname','sslmode','connect_timeout'}
    port=settings.get('port','')
    if (set(settings)-allowed or settings.get('host')!='127.0.0.1'
            or not port.isdecimal() or not 1<=int(port)<=65535 or int(port)==5432
            or not settings.get('user') or not settings.get('dbname')):
        raise RuntimeError('Source HTTP tests require an explicit disposable PostgreSQL DSN '
                           '(host=127.0.0.1, non-default port, user and dbname); port 5432 is forbidden')
    credentials=quote(settings['user'],safe='')
    if 'password' in settings:credentials+=':'+quote(settings['password'],safe='')
    url='postgresql://'+credentials+'@127.0.0.1:'+str(int(port))+'/'+quote(settings['dbname'],safe='')
    query=urlencode({key:settings[key] for key in ('sslmode','connect_timeout') if key in settings})
    return url+('?' + query if query else '')


def zook_worktree():
    configured=os.getenv('TEST_ZOOK_WORKTREE','').strip()
    if not configured:
        raise RuntimeError('Source HTTP integration tests require TEST_ZOOK_WORKTREE '
                           'pointing to a Zook checkout with test/support/lighttick-source-http-fixture.ts')
    root=Path(configured).resolve()
    if not (root/'test/support/lighttick-source-http-fixture.ts').is_file():
        raise RuntimeError('TEST_ZOOK_WORKTREE does not contain test/support/lighttick-source-http-fixture.ts')
    return root


class HTTPDeliveryContract:
    def start_zook(self):
        url=source_database_url(self.dsn)
        self.proc_stderr=tempfile.TemporaryFile(mode='w+')
        self.proc=None
        try:
            self.proc=subprocess.Popen(['node','--experimental-transform-types','test/support/lighttick-source-http-fixture.ts'],
                cwd=self.zook,env={**os.environ,'SOURCE_TEST_SCHEMA':self.zschema,'SOURCE_TEST_TOKEN':self.control_token,
                    'LIGHTTICK_ACTION_TEST_DATABASE_URL':url},stdout=subprocess.PIPE,stderr=self.proc_stderr,text=True)
            if not select.select([self.proc.stdout],[],[],15)[0]:raise RuntimeError('startup timed out after 15 seconds')
            message=self.proc.stdout.readline()
            if not message:raise RuntimeError('process exited before announcing its HTTP port')
            self.url='http://127.0.0.1:'+str(json.loads(message)['port'])
        except Exception as error:
            diagnostic=self.stop_zook()
            raise RuntimeError('Zook source HTTP fixture failed: '+str(error)+'\n'+diagnostic) from error
        os.environ['LIGHTTICK_BRIDGE_URL']=self.url

    def stop_zook(self):
        if getattr(self,'proc',None):
            if self.proc.poll() is None:
                self.proc.terminate()
                try:self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait(timeout=5)
            code=self.proc.returncode
            self.proc.stdout.close();self.proc=None
            self.proc_stderr.seek(0);diagnostic=self.proc_stderr.read();self.proc_stderr.close()
            return 'exit code '+str(code)+'\n'+diagnostic
        if getattr(self,'proc_stderr',None) and not self.proc_stderr.closed:self.proc_stderr.close()
        return ''

    def control(self,path,body=None):
        with httpx.Client(timeout=10) as client:r=client.post(self.url+'/fixture/'+path,headers={'X-Test-Token':self.control_token},json=body or {})
        self.assertEqual(r.status_code,200,r.text);return r.json()

    def setup_delivery(self):
        self.zook=zook_worktree()
        self.zschema='source_http_'+uuid.uuid4().hex;self.control_token=uuid.uuid4().hex
        env=patch.dict(os.environ,{'GROW_ACTION_BRIDGE_SECRET':'TEST_ONLY_SOURCE_HTTP_SECRET_0123456789'})
        env.start();self.addCleanup(env.stop)
        self.addCleanup(self.cleanup_zook)
        self.start_zook()
        self.token=current_user.set({'id':'grow-fixture','is_owner':1,'schema_name':self.schema})
        self.addCleanup(current_user.reset,self.token)
        self.plan=self.control('setup',{'target':self.target,'date':'2026-10-19'})['plan']
        with actions.connection(True,allow_link=True) as c:
            put(c,dict(phase='active',binding_id='binding-fixture',target_user_id='zook-fixture'))
            c.execute('CREATE TABLE auth_users (id TEXT,schema_name TEXT,is_owner INTEGER)')
            c.execute('INSERT INTO auth_users VALUES (?,?,?)',('grow-fixture',self.schema,1))

    def cleanup_zook(self):
        self.stop_zook()
        with psycopg2.connect(self.dsn) as c:c.cursor().execute('DROP SCHEMA IF EXISTS '+self.zschema+' CASCADE')

    def test_lost_response_real_restart_next_day_retries_same_event_once(self):
        self.control('control',{'drop':True})
        saved=self.confirm(key='source-http-lost-response');self.assertEqual(saved.status_code,200,saved.text)
        event=saved.json()['source_event_id'];self.assertEqual(saved.json()['source_delivery_state'],'pending')
        before=self.control('workspace')['data'];self.assertEqual(len(before['records']),1)
        self.stop_zook();self.start_zook();self.control('control',{'now':'2026-10-20T12:00:00Z'})
        fresh=subprocess.run([sys.executable,str(Path(__file__).with_name('retry_action_source_fixture.py'))],
            env={**os.environ,'TEST_GROW_SOURCE_SCHEMA':self.schema,'TEST_SOURCE_NOW':'2026-10-20T12:00:00+00:00',
                 'PYTHONPATH':os.pathsep.join([str(Path(__file__).resolve().parents[1]),*sys.path])},capture_output=True,text=True,timeout=20)
        self.assertEqual(fresh.returncode,0,'Grow retry subprocess failed:\n'+fresh.stdout+'\n'+fresh.stderr)
        with actions.connection() as c:self.assertEqual(c.execute('SELECT state FROM action_source_outbox').fetchone()[0],'completed')
        retry_due(force=True)
        replay=self.confirm(key='source-http-lost-response');self.assertEqual(replay.json()['source_event_id'],event)
        self.assertEqual(replay.json()['completed_arrangements'],[self.plan['id']])
        after=self.control('workspace')['data'];self.assertEqual(len(after['records']),1)
        self.assertEqual((after['records'][0]['business_date'],after['records'][0]['planned_date']),('2026-10-19','2026-10-19'))
        with actions.connection() as c:self.assertEqual(c.execute('SELECT count(*) FROM action_executions').fetchone()[0],0)
        receipt=call('grow-fixture',dict(action='source-receipt',binding_id='binding-fixture',action_schema_version=2,event_id=event))
        self.assertEqual(receipt['status'],'completed')

    def test_transaction_rollback_and_running_reconcile_preserve_minutes(self):
        self.control('control',{'failReceipt':True})
        saved=self.confirm(key='source-http-db-rollback');self.assertEqual(saved.status_code,200,saved.text)
        event=saved.json()['source_event_id']
        raw=self.control('workspace')['data'];self.assertEqual(raw.get('content_events',[]),[]);self.assertEqual(raw['records'],[])
        started=self.control('action',{'path':'/'+self.plan['id']+'/operations','body':dict(key='http-running-start',revision=1,action='start')})
        retry_due(force=True)
        raw=self.control('workspace')['data'];self.assertEqual(raw['records'][0]['outcome'],'running');self.assertEqual(len(raw['content_events']),1)
        self.control('action',{'path':'/'+self.plan['id']+'/operations','body':dict(key='http-running-finish',revision=started['plan']['revision'],action='finish',execution_id=started['execution']['id'],actual_minutes=12)})
        retry_due(force=True)
        raw=self.control('workspace')['data'];self.assertEqual(len(raw['records']),2)
        self.assertEqual(sum(r['actual_minutes'] for r in raw['records']),12)
        self.assertEqual(sum(r['completion_effect']=='complete' for r in raw['records']),1)
        self.assertEqual(raw['content_events'][0]['consumed_by'],self.plan['id'])
        self.assertEqual(call('grow-fixture',dict(action='source-receipt',binding_id='binding-fixture',action_schema_version=2,event_id=event))['status'],'completed')

    def test_cached_context_offline_and_spoofed_binding_event_conflict(self):
        delivery=prepare(self.target,self.plan['id']);self.assertIn('origin_context',delivery)
        self.stop_zook()
        saved=self.confirm(key='source-http-offline-cached');self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual(saved.json()['source_delivery_state'],'pending')
        self.start_zook();retry_due(force=True)
        with actions.connection() as c:payload=json.loads(c.execute('SELECT payload FROM action_source_outbox').fetchone()[0])
        self.assertNotIn('comment',json.dumps(payload));self.assertNotIn('PRIVATE',json.dumps(payload))
        with self.assertRaises(actions.ActionError) as conflict:call('grow-fixture',{**payload,'event':{**payload['event'],'confirmed_at':'2026-10-19T11:59:00Z'}})
        self.assertEqual((conflict.exception.status_code,conflict.exception.code),(409,'SOURCE_EVENT_CONFLICT'))
        with self.assertRaises(actions.ActionError) as foreign:call('grow-other',payload)
        self.assertEqual(foreign.exception.status_code,404)
        with self.assertRaises(actions.ActionError) as binding:call('grow-fixture',{**payload,'binding_id':'other-binding'})
        self.assertEqual(binding.exception.status_code,404)
        bad={**payload,'event':{**payload['event'],'event_id':'source-'+'b'*32,'origin_context':delivery['origin_context'][:-1]+'x'}}
        with self.assertRaises(actions.ActionError) as forged:call('grow-fixture',bad)
        self.assertEqual(forged.exception.status_code,403)
        self.assertEqual(len(self.control('workspace')['data']['records']),1)
        self.control('control',{'member':False})
        with self.assertRaises(actions.ActionError) as membership:call('grow-fixture',payload)
        self.assertEqual(membership.exception.status_code,403)


class CourseHTTPDelivery(HTTPDeliveryContract,CourseReceiptFixture):
    def setUp(self):super().setUp();self.setup_delivery()


# Inherit only the source fixture setup/confirm, not its independent closeout cases.
class ArticleHTTPDelivery(HTTPDeliveryContract,CloudHTTPFixture):
    def setUp(self):
        super().setUp();actions.register(self.app)
        timer=patch('action_plans.clock',return_value=datetime(2026,10,19,12,tzinfo=timezone.utc));timer.start();self.addCleanup(timer.stop)
        self.client=TestClient(self.app,base_url='http://localhost');self.addCleanup(self.client.close)
        self.headers={'X-Copilot-Request':'1','X-Grow-Action-Schema':'2'}
        self.target={'kind':'article','course':self.aid};self.setup_delivery()
    def confirm(self,key,**updates):
        return self.client.post('/api/reading/articles/'+self.aid+'/personal',headers=self.headers,
            json={'data':{'read':True,'key':key,'origin_action_id':self.plan['id'],**updates}})


class SourceHTTPConfigurationTests(unittest.TestCase):
    def test_dsn_preserves_explicit_test_connection(self):
        url=source_database_url('host=127.0.0.1 port=55468 user=grow_test dbname=postgres')
        parsed=urlsplit(url)
        self.assertEqual((parsed.hostname,parsed.port,parsed.username,parsed.path),
                         ('127.0.0.1',55468,'grow_test','/postgres'))

    def test_dsn_rejects_implicit_connections_and_redirects(self):
        for dsn in ('host=127.0.0.1 user=grow_test dbname=postgres',
                    'host=127.0.0.1 port=5432 user=grow_test dbname=postgres',
                    'host=remote.example port=55468 user=grow_test dbname=postgres',
                    'host=127.0.0.1 hostaddr=192.0.2.1 port=55468 user=grow_test dbname=postgres',
                    'host=127.0.0.1 port=55468 dbname=postgres',
                    'host=127.0.0.1 port=55468 user=grow_test'):
            with self.subTest(dsn=dsn),self.assertRaisesRegex(RuntimeError,'explicit disposable PostgreSQL DSN'):
                source_database_url(dsn)

    def test_fixture_startup_failure_reports_child_stderr(self):
        fixture=HTTPDeliveryContract()
        fixture.dsn='host=127.0.0.1 port=55468 user=grow_test dbname=postgres'
        fixture.zook=Path(tempfile.gettempdir())
        fixture.zschema='source_http_'+'a'*32;fixture.control_token='b'*32
        launch=subprocess.Popen
        def failing_child(*args,**kwargs):
            return launch([sys.executable,'-c',
                           'import sys;sys.stderr.write("TEST_ONLY_STARTUP_FAILURE\\n");sys.exit(17)'],**kwargs)
        with patch.object(subprocess,'Popen',side_effect=failing_child):
            with self.assertRaisesRegex(RuntimeError,'(?s)Zook source HTTP fixture failed:.*exit code 17.*TEST_ONLY_STARTUP_FAILURE'):
                fixture.start_zook()
        self.assertIsNone(fixture.proc)
        self.assertTrue(fixture.proc_stderr.closed)

    def test_missing_worktree_has_actionable_error(self):
        with patch.dict(os.environ,{'TEST_ZOOK_WORKTREE':''}):
            with self.assertRaisesRegex(RuntimeError,'require TEST_ZOOK_WORKTREE'):
                zook_worktree()

    def test_invalid_worktree_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{'TEST_ZOOK_WORKTREE':root}):
            with self.assertRaisesRegex(RuntimeError,'does not contain test/support'):
                zook_worktree()
