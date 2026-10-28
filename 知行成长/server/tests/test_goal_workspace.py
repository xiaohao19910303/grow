"""Goal compatibility and results against disposable PostgreSQL."""
from datetime import datetime, timezone
from unittest.mock import patch
import uuid
from fastapi import FastAPI
from fastapi.testclient import TestClient
import action_plans as a
from test_legacy_cloud_schema import PostgreSQLFixture


class GoalWorkspaceTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        app=FastAPI(); a.register(app); self.client=TestClient(app)
        self.addCleanup(self.client.close)
        fixed=patch('action_plans.clock',return_value=datetime(2026,10,26,8,tzinfo=timezone.utc))
        fixed.start(); self.addCleanup(fixed.stop)
        self.headers={'X-Copilot-Request':'1','X-Grow-Action-Schema':'2','X-Grow-Workspace-Version':'1'}

    def post(self,path,body,status=200):
        response=self.client.post('/api/action-plans'+path,json={'key':str(uuid.uuid4()),**body},headers=self.headers)
        self.assertEqual(response.status_code,status,response.text)
        return response.json()

    def create(self,**fields):
        values=dict(title='行动',period='day',completion_mode='check',start_date=None,end_date=None)
        values.update(fields)
        return self.post('',values)['plans'][0]

    def workspace(self):return self.client.get('/api/action-plans/workspace').json()['plans']

    def test_independent_short_plans_undated_children_and_cross_month_reschedule(self):
        month=self.create(title='本月',period='month',completion_mode='time',start_date='2026-10-01',end_date='2026-10-31')
        week=self.create(period='week',completion_mode='time',start_date='2026-10-26',end_date='2026-11-01',parent_id=month['id'])
        action=self.create(parent_id=week['id'])
        self.assertEqual(next(p for p in self.workspace() if p['id']==week['id'])['entity_type'],'plan')
        moved=self.post('/'+action['id']+'/operations',dict(action='reschedule',date='2026-11-04',revision=action['revision']))['plan']
        self.assertEqual(moved['parent_id'],week['id'])
        self.assertTrue(next(p for p in self.workspace() if p['id']==moved['id'])['outside_period'])

    def test_goal_results_reversal_and_legacy_identity(self):
        goal=self.create(title='旧年目标',period='year',start_date='2026-01-01',end_date='2026-12-31',completion_mode='time',target_count=2)
        action=self.create(parent_id=goal['id'],start_date='2026-10-26',end_date='2026-10-26')
        done=self.post('/'+action['id']+'/operations',dict(action='complete',revision=1))['plan']
        read=next(p for p in self.workspace() if p['id']==goal['id'])
        self.assertEqual((read['entity_type'],read['result']['percent'],read['status']),('goal',50,'active'))
        self.post('/'+action['id']+'/operations',dict(action='reopen',revision=done['revision']))
        self.assertEqual(next(p for p in self.workspace() if p['id']==goal['id'])['result']['current'],0)

    def test_manual_and_milestone_history_and_revision(self):
        goal=self.create(entity_type='goal',period='custom',completion_mode='time')
        out=self.post('/goals/'+goal['id']+'/result',dict(revision=1,metric={'mode':'manual','current':13,'target':12,'unit':'篇'}))
        metric=next(p for p in self.workspace() if p['id']==goal['id'])['result']
        self.assertEqual((metric['current'],metric['percent']),(13,100))
        self.post('/goals/'+goal['id']+'/result',dict(revision=1,metric={'mode':'manual','target':2}),409)
        out=self.post('/goals/'+goal['id']+'/result',dict(revision=out['plan']['revision'],metric={'mode':'milestones','milestones':[{'id':'one','title':'初稿','completed':True},{'id':'two','title':'发布'}]}))
        self.assertEqual(len(out['plan']['result_history']),2)
        self.assertEqual(next(p for p in self.workspace() if p['id']==goal['id'])['result']['percent'],50)

    def test_cycle_and_capability_protection(self):
        first=self.create(period='custom',entity_type='plan',completion_mode='time',start_date='2026-10-01',end_date='2026-11-20')
        child=self.create(period='week',completion_mode='time',start_date='2026-10-26',end_date='2026-11-01',parent_id=first['id'])
        fields={k:v for k,v in first.items() if k in a.PlanFields.model_fields};fields['parent_id']=child['id']
        self.post('/'+first['id']+'/operations',dict(revision=1,action='edit',fields=fields),422)
        response=self.client.post('/api/action-plans',json=dict(title='目标',period='custom',entity_type='goal',key=str(uuid.uuid4())),headers={'X-Copilot-Request':'1','X-Grow-Action-Schema':'2'})
        self.assertEqual(response.status_code,409)

    def test_personal_export_preserves_goal_metric_history_and_future_intentions(self):
        goal=self.create(entity_type='goal',period='custom',completion_mode='time',result_metric={'mode':'manual','target':12,'current':3})
        self.post('/week-plans/2026-11-02',dict(revision=0,priorities=[goal['id']],available_minutes=60))
        self.post('/goals/'+goal['id']+'/result',dict(revision=1,metric={'mode':'manual','target':12,'current':4}))
        data=self.client.get('/api/action-plans/rhythm/export').json()
        self.assertEqual(data['workspace_version'],1)
        self.assertEqual(data['week_plans'][0]['priorities'],[goal['id']])
        p=next(p for p in data['plans'] if p['id']==goal['id'])
        self.assertEqual(p['result_metric']['current'],4)
        self.assertEqual(p['result_history'][0]['metric']['current'],3)

    def test_workspace_data_cannot_be_silently_handed_off(self):
        import action_link
        self.create(entity_type='goal',period='custom',completion_mode='time')
        with a.connection() as c, self.assertRaises(a.ActionError) as error:
            action_link.snapshot(c,version=2)
        self.assertEqual(error.exception.code,'CONTRACT_UPGRADE_REQUIRED')

    def test_postgres_restore_preserves_workspace_results_weeks_and_drafts(self):
        import os
        from pathlib import Path
        import subprocess
        import tempfile
        import psycopg2
        import goal_planning
        goal=self.create(entity_type='goal',period='custom',completion_mode='time',result_metric={'mode':'manual','target':4,'current':1})
        self.post('/goals/'+goal['id']+'/result',dict(revision=1,metric={'mode':'manual','target':4,'current':2}))
        self.post('/week-plans/2026-11-02',dict(revision=0,priorities=[goal['id']],available_minutes=60))
        with a.connection(True) as c:
            goal_planning.store_draft(c,dict(id='draft-restore',state='ready',revision=1,root_id=goal['id'],snapshot={},items=[],worker=goal_planning.WORKER,created_at=a.clock().isoformat()))
        before=self.client.get('/api/action-plans/rhythm/export').json()
        with tempfile.TemporaryDirectory(prefix='grow-goal-restore-') as temp:
            archive=Path(temp)/'private.dump'
            subprocess.run(['pg_dump','--dbname',self.dsn,'--schema',self.schema,'--format=custom','--no-owner','--no-acl','--file',str(archive)],check=True,capture_output=True)
            with psycopg2.connect(self.dsn) as c:c.cursor().execute('DROP SCHEMA '+self.schema+' CASCADE')
            subprocess.run(['pg_restore','--dbname',self.dsn,'--no-owner','--no-acl','--exit-on-error',str(archive)],check=True,capture_output=True)
        after=self.client.get('/api/action-plans/rhythm/export').json()
        self.assertEqual(before,after)
        self.assertEqual(after['planning_drafts'][0]['id'],'draft-restore')
        self.assertNotIn('worker',after['planning_drafts'][0])

    def test_goal_completion_is_explicit_and_goal_operation_checks_type(self):
        goal=self.create(entity_type='goal',period='custom',completion_mode='time',result_metric={'mode':'manual','current':3,'target':3})
        current=next(p for p in self.workspace() if p['id']==goal['id'])
        self.assertTrue(current['result']['ready']);self.assertEqual(current['status'],'active')
        completed=self.post('/goals/'+goal['id']+'/operations',dict(action='complete',revision=goal['revision']))['plan']
        self.assertEqual(completed['status'],'completed')
        action=self.create()
        self.post('/goals/'+action['id']+'/operations',dict(action='archive',revision=action['revision']),422)

    def test_template_request_replay_is_idempotent_and_keeps_nullable_time(self):
        body=dict(key=str(uuid.uuid4()),name='小步行动',period='day',completion_mode='check',at=None,minimum_minutes=None)
        one=self.post('/templates',body);two=self.post('/templates',body)
        self.assertEqual(one['id'],two['id'])
        self.assertEqual(len(self.client.get('/api/action-plans/templates').json()['templates']),1)
        self.assertIsNone(one['at'])
