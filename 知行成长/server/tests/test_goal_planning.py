from datetime import datetime, timezone
import json
from unittest.mock import patch
import uuid
import action_plans as a
import goal_planning as planning
import test_goal_workspace as workspace_tests


class GoalPlanningTests(workspace_tests.GoalWorkspaceTests):
    def test_week_intentions_capacity_and_atomic_conflict(self):
        one=self.create(title='写作',estimated_minutes=30)
        two=self.create(title='阅读')
        body=dict(revision=0,available_minutes=20,assignments=[{'plan_id':one['id'],'revision':1,'date':'2026-10-26'},{'plan_id':two['id'],'revision':1,'date':None}])
        result=self.post('/week-plans/2026-10-26',body)['week']
        self.assertEqual(result['workload']['estimated_minutes'],30)
        self.assertEqual(result['workload']['unknown_count'],1)
        self.assertTrue(result['workload']['overloaded'])
        self.assertEqual(self.client.get('/api/action-plans/records').json()['total'],0)
        moved=next(p for p in self.workspace() if p['id']==one['id'])
        self.post('/week-plans/2026-11-02',dict(revision=0,assignments=[{'plan_id':one['id'],'revision':moved['revision'],'date':'2026-11-02'},{'plan_id':two['id'],'revision':99,'date':'2026-11-03'}]),409)
        self.assertEqual(next(p for p in self.workspace() if p['id']==one['id'])['start_date'],'2026-10-26')
        self.assertIsNone(self.client.get('/api/action-plans/week-plans/2026-11-02').json()['week']['workload']['remaining_minutes'])

    def draft(self,goal,items):
        brief=dict(root_id=goal['id'],root_revision=goal['revision'],baseline='刚开始',focus='先做小步',days=7)
        response=self.client.post('/api/action-plans/planning-drafts/preview',json=brief,headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        preview=response.json()
        cfg={'provider':'openai','api_key':'PRIVATE-SECRET','url':'https://example.invalid/v1/chat/completions','model':'fixture'}
        async def generate(snapshot,cfg,evidence_snapshot_id=None):return items
        with patch('goal_planning.require_config',return_value=cfg),patch('goal_planning.generate_items',side_effect=generate):
            generated=self.post('/planning-drafts/generate',{**brief,'consent':True,'snapshot_hash':preview['snapshot_hash'],'ai_config':cfg},202)['draft']
        return self.client.get('/api/action-plans/planning-drafts/'+generated['id']).json()['draft']

    def test_generation_uses_frozen_preview_and_queries_do_not_call_model(self):
        from ai_evidence import read
        goal=self.create(title='表达能力',entity_type='goal',period='custom',completion_mode='time')
        brief=dict(root_id=goal['id'],root_revision=goal['revision'],baseline='PRIVATE_BASELINE',focus='小步练习',days=7)
        preview=self.client.post('/api/action-plans/planning-drafts/preview',json=brief,headers=self.headers).json()
        calls=[]
        async def model(messages,cfg):
            calls.append(messages)
            yield {'text':json.dumps({'items':[{'ref':'a','title':'写出论点','entity_type':'action','period':'day'}]})}
            yield {'done':True}
        cfg={'model':'fixture','key':'NOT_PERSISTED','url':'https://example.invalid/v1/chat/completions'}
        with patch('goal_planning.require_config',return_value=cfg),patch('copilot.transport.qwen_stream',model):
            draft=self.post('/planning-drafts/generate',{**brief,'consent':True,'snapshot_hash':preview['snapshot_hash'],'ai_config':{}},202)['draft']
            done=self.client.get('/api/action-plans/planning-drafts/'+draft['id']).json()['draft']
            self.assertEqual(done['state'],'ready')
            self.client.get('/api/action-plans/planning-drafts?root_id='+goal['id'])
        self.assertEqual(len(calls),1)
        with a.connection() as c:
            evidence=read(c,draft['evidence_snapshot_id'])
            self.assertEqual(evidence['messages'],calls[0]);self.assertNotIn('NOT_PERSISTED',str(evidence))
            self.assertIn('PRIVATE_BASELINE',str(evidence))

    def test_draft_edit_partial_adoption_idempotent_and_no_credentials(self):
        goal=self.create(title='表达能力',entity_type='goal',period='custom',completion_mode='time')
        draft=self.draft(goal,[dict(ref='p',parent_ref=None,title='本周初稿',entity_type='plan',period='week',start_date='2026-10-26',end_date='2026-11-01',selected=False),dict(ref='a',parent_ref='p',title='写出论点',entity_type='action',period='day',start_date=None,end_date=None,selected=True)])
        self.assertEqual(draft['state'],'ready')
        edited=self.post('/planning-drafts/'+draft['id']+'/edit',dict(revision=draft['revision'],items=draft['items']))['draft']
        adopted=self.post('/planning-drafts/'+draft['id']+'/adopt',dict(revision=edited['revision']))
        self.assertEqual(len(adopted['plans']),1)
        self.assertEqual(adopted['plans'][0]['parent_id'],goal['id'])
        again=self.post('/planning-drafts/'+draft['id']+'/adopt',dict(revision=edited['revision']))
        self.assertEqual(adopted['plans'],again['plans'])
        with a.connection() as c:
            self.assertNotIn('PRIVATE-SECRET',str(c.execute('SELECT data FROM action_plan_drafts').fetchall()))
            self.assertNotIn('PRIVATE-SECRET',str(c.execute('SELECT result,hash FROM action_operations').fetchall()))

    def test_root_conflict_preserves_draft_and_adopt_rolls_back_invalid_tree(self):
        goal=self.create(entity_type='goal',period='custom',completion_mode='time')
        draft=self.draft(goal,[dict(ref='a',title='任务',entity_type='action',period='day')])
        self.post('/goals/'+goal['id']+'/result',dict(revision=1,metric={'mode':'manual','target':12}))
        self.post('/planning-drafts/'+draft['id']+'/adopt',dict(revision=draft['revision']),409)
        self.assertEqual(len(self.workspace()),1)
        self.assertEqual(self.client.get('/api/action-plans/planning-drafts/'+draft['id']).json()['draft']['state'],'ready')

    def test_interruption_and_invalid_items(self):
        goal=self.create(entity_type='goal',period='custom',completion_mode='time')
        draft=self.draft(goal,[dict(ref='a',title='任务',entity_type='action',period='day')])
        self.post('/planning-drafts/'+draft['id']+'/edit',dict(revision=draft['revision'],items=[dict(ref='a',title='任务',parent_ref='a')]),422)
        with a.connection(True) as c:
            row=planning.get_draft(c,draft['id']);row.update(state='generating',worker='old-worker');planning.store_draft(c,row)
        self.assertEqual(self.client.get('/api/action-plans/planning-drafts/'+draft['id']).json()['draft']['state'],'failed')

    def test_partial_adoption_rolls_back_all_created_rows_and_receipts(self):
        goal=self.create(entity_type='goal',period='custom',completion_mode='time')
        draft=self.draft(goal,[dict(ref='one',title='第一步',entity_type='action',period='day'),dict(ref='two',title='第二步',entity_type='action',period='day')])
        original=a.create_in;calls=[]
        def create_in(c,body):
            calls.append(body.title)
            if len(calls)==2:a.fail(503,'模拟事务中断')
            return original(c,body)
        with patch('action_plans.create_in',side_effect=create_in):
            self.post('/planning-drafts/'+draft['id']+'/adopt',dict(revision=draft['revision']),503)
        self.assertEqual(len(self.workspace()),1)
        current=self.client.get('/api/action-plans/planning-drafts/'+draft['id']).json()['draft']
        self.assertEqual(current['state'],'ready')
        result=self.post('/planning-drafts/'+draft['id']+'/adopt',dict(revision=draft['revision']))
        self.assertEqual(len(result['plans']),2)
