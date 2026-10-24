"""C3 private export plus local/remote request receipt routing."""
import json
import os
from pathlib import Path
import subprocess
from unittest.mock import patch
from test_action_p0_sources import CourseReceiptFixture
from test_action_source_http import source_database_url
from tenancy import current_user
import action_plans as actions
import action_link
from action_handoff import snapshot_v2

class HandoffTests(CourseReceiptFixture):
    def setUp(self):
        super().setUp()
        self.token=current_user.set({'id':'grow-handoff','schema_name':self.schema,'is_owner':1})
        self.addCleanup(current_user.reset,self.token)

    def test_legacy_p0_graph_export_and_real_zook_postgres_recovery(self):
        self.assertEqual(self.confirm().status_code,200)
        # Real Grow facts: completed content, complete+reversal check, nullable check, running time.
        def create(key,**updates):
            result=self.client.post('/api/action-plans',headers=self.headers,json=dict(key=key,title='接管样本',period='day',completion_mode='check',start_date='2026-10-19',end_date='2026-10-19')|updates)
            self.assertEqual(result.status_code,200,result.text);return result.json()['plans'][0]
        def op(p,action,key):
            r=self.client.post('/api/action-plans/'+p['id']+'/operations',headers=self.headers,json={'key':key,'action':action,'revision':p['revision']})
            self.assertEqual(r.status_code,200,r.text);return r.json()['plan']
        check=create('handoff-check-create');check=op(check,'complete','handoff-complete');op(check,'reopen','handoff-reopen')
        create('handoff-nullable',start_date=None,end_date=None)
        op(create('handoff-running',completion_mode='time'),'start','handoff-start')
        # Model stored P0 history from before daily-rhythm facts existed. The
        # receiving P0 contract intentionally has no rhythm fields; production
        # exports must never strip those fields from current records.
        with actions.connection() as c:
            for table,fields in (
                ('action_plans', ('recurrence','until')),
                ('action_executions', ('activity_at','activity_confirmed','activity_date',
                 'activity_timezone','fact_version','focus_day_id','focus_plan_id_snapshot',
                 'focus_selected_at_snapshot','minimum_step_snapshot','rhythm_variant',
                 'next_step','recap_history','recap_kind','recap_revision','recap_saved_at'))):
                for row in c.execute('SELECT id,data FROM '+table).fetchall():
                    value=json.loads(row[1])
                    for field in fields:value.pop(field,None)
                    c.execute('UPDATE '+table+' SET data=? WHERE id=?',(actions.encoded(value),row[0]))
        exported=snapshot_v2('grow-handoff')
        self.assertEqual(exported,snapshot_v2('grow-handoff'))
        event=exported['content_events'][0]
        self.assertEqual(event['owner'],'grow-handoff');self.assertEqual(event['consumed_by'],self.plan['id'])
        self.assertNotIn(self.schema,json.dumps(exported));self.assertNotIn('只存私人反馈',json.dumps(exported))
        self.assertNotIn('source_result',event)
        with actions.connection() as c:self.assertEqual(action_link.state(c)[0]['phase'],'local')
        worktree=os.environ.get('TEST_ZOOK_WORKTREE')
        self.assertTrue(worktree,'Explicit TEST_ZOOK_WORKTREE required for C3 integration')
        result=subprocess.run(['node','--experimental-transform-types','test/support/lighttick-handoff-fixture.ts'],
            cwd=worktree,env={**os.environ,'LIGHTTICK_ACTION_TEST_DATABASE_URL':source_database_url(self.dsn)},input=actions.encoded(exported),text=True,capture_output=True,timeout=50)
        self.assertEqual(result.returncode,0,result.stderr+'\n'+result.stdout)
        self.assertIn('C3_POSTGRES_RECOVERY_OK',result.stdout)

    def test_export_preserves_current_rhythm_facts_without_loss(self):
        self.assertEqual(self.confirm().status_code,200)
        response=self.client.post('/api/action-plans',headers=self.headers,json={
            'key':'rhythm-export-check','title':'保留新版事实','period':'day',
            'completion_mode':'check','start_date':'2026-10-19','end_date':'2026-10-19'})
        self.assertEqual(response.status_code,200,response.text)
        plan=response.json()['plans'][0]
        response=self.client.post('/api/action-plans/'+plan['id']+'/operations',
            headers=self.headers,json={'key':'rhythm-export-complete','action':'complete','revision':plan['revision']})
        self.assertEqual(response.status_code,200,response.text)
        exported=snapshot_v2('grow-handoff')
        with actions.connection() as c:
            records=[json.loads(row[0]) for row in c.execute('SELECT data FROM action_executions ORDER BY id')]
            self.assertEqual(exported['records'],records)
            self.assertTrue(any(record.get('fact_version')==2 for record in records))
            self.assertEqual(action_link.state(c)[0]['phase'],'local')

    def test_export_rejects_foreign_owner_and_existing_binding_without_freeze(self):
        self.assertEqual(self.confirm().status_code,200)
        with actions.connection() as c:
            row=c.execute('SELECT id,data FROM action_content_events').fetchone();e=json.loads(row[1]);e['owner']='foreign'
            c.execute('UPDATE action_content_events SET data=? WHERE id=?',(actions.encoded(e),row[0]))
        with self.assertRaises(actions.ActionError):snapshot_v2('grow-handoff')
        with actions.connection() as c:
            self.assertEqual(action_link.state(c)[0]['phase'],'local')
            action_link.put(c,{'phase':'active'})
        with self.assertRaises(actions.ActionError):snapshot_v2('grow-handoff')

    def test_old_keys_read_locally_new_keys_route_to_zook_and_pending_unknown_stays_uncertain(self):
        # register() is already installed by actions.register.
        old='course-p0-arrange'
        with actions.connection() as c:action_link.put(c,{'phase':'active'})
        with patch('action_link.call',return_value={'found':True,'result':{'remote':'saved'}}) as bridge:
            self.assertTrue(self.client.get('/api/action-plans/requests/'+old).json()['found']);bridge.assert_not_called()
            r=self.client.get('/api/action-plans/requests/new-zook-key')
            self.assertEqual(r.json(),{'found':True,'result':{'remote':'saved'}})
            self.assertEqual(bridge.call_args.args[1]['path'],'/requests/new-zook-key')
            self.assertEqual(r.headers['cache-control'],'no-store')
        for bad in ({'plans':[]},{'found':True,'result':None},{'found':False,'result':{'unconfirmed':True}}):
            with patch('action_link.call',return_value=bad):
                self.assertEqual(self.client.get('/api/action-plans/requests/new-zook-key').status_code,503)
        with actions.connection() as c:action_link.put(c,{'phase':'pending'})
        with patch('action_link.call') as bridge:
            self.assertTrue(self.client.get('/api/action-plans/requests/'+old).json()['found'])
            self.assertEqual(self.client.get('/api/action-plans/requests/unknown-key').status_code,503);bridge.assert_not_called()

    def test_schema_number_alone_never_opens_connection_writes(self):
        with actions.connection() as c:action_link.put(c,{'phase':'active'})
        for caps in ({},{'connection_write_enabled':False},{'connection_write_enabled':True,'nullable_schedule':True,'actual_fact_dates':True,'completion_modes':[{}],'content_receipts':[{}]},
                     {'connection_write_enabled':True,'nullable_schedule':True,'actual_fact_dates':True,'completion_modes':['time','content','check'],'content_receipts':[]}):
            with patch('action_link.call',return_value={'action_schema_version':2,'capabilities':caps}) as bridge:
                r=self.client.post('/api/action-plans/'+self.plan['id']+'/operations',headers=self.headers,json={'key':'handoff-no-write','revision':1,'action':'cancel'})
                self.assertEqual(r.status_code,409,r.text);self.assertEqual(bridge.call_count,1)
        with actions.connection() as c:self.assertEqual(c.execute('SELECT count(*) FROM action_executions').fetchone()[0],0)
