"""C1/C3 association and live progress against disposable PG and simulated GitHub."""
from concurrent.futures import ThreadPoolExecutor
import copy
from datetime import timedelta
from zoneinfo import ZoneInfo
import json
import uuid
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import db
import action_plans as actions
from cloud_fixtures import CloudFixture
from plans.api import register
from test_plans import B, D, S, content


class LearningActionTests(CloudFixture):
    def setUp(self):
        super().setUp()
        self.app=FastAPI()
        with patch('plans.api.make_store',return_value=self.s):register(self.app,self.root,self.runtime)
        actions.register(self.app)
        self.client=TestClient(self.app,base_url='http://localhost',raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        self.headers={'X-Copilot-Request':'1','X-Grow-Action-Schema':'2'}
        doc=copy.deepcopy(D);doc['stages'].append({'title':'应用','goal':'用于现实'});doc['lessons'][1]['stage']=2
        self.draft=self.s.draft({'brief':B,'document':doc})
        self.pid=self.s.adopt(self.draft['id'],'setup-adopt')['plan_id']

    def post(self,path,**data):
        return self.client.post('/api/plans'+path,json={'data':data},headers=self.headers)

    def link(self,**updates):
        return self.post('/'+self.pid+'/actions',key=str(uuid.uuid4()),expected_version=self.s.plan(self.pid)['version'],**updates)

    def projection(self):
        response=self.client.get('/api/plans/'+self.pid+'/actions')
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def course(self):
        self.s.save_sources(self.pid,S);ctx=self.s.course_context(self.pid)
        draft=self.s.course_draft(ctx,content(ctx),'摘要 [来源](https://example.org/lesson)')
        response=self.post('/drafts/'+draft['id']+'/publish',key='publish-'+draft['id'],expected_hash=draft['content_hash'])
        self.assertEqual(response.status_code,200,response.text)
        return response,draft

    def test_link_without_published_lessons_tracks_full_plan_without_fake_actions(self):
        response=self.link();self.assertEqual(response.status_code,200,response.text)
        progress=self.projection()
        self.assertTrue(progress['linked']);self.assertEqual(progress['total_lessons'],2)
        self.assertEqual(progress['published_lessons'],0)
        self.assertEqual(actions.listing()['plans'],[])
        self.assertEqual([s['total_lessons'] for s in progress['stages']],[1,1])

    def test_published_course_creates_one_undated_content_action_and_reuses_on_repeat(self):
        self.course();first=self.link();self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(self.link().status_code,200)
        plans=actions.listing()['plans'];self.assertEqual(len(plans),1)
        p=plans[0];self.assertEqual(p['completion_mode'],'content')
        self.assertIsNone(p['start_date']);self.assertIsNone(p['target_minutes']);self.assertFalse(p['reminder'])
        self.assertEqual(p['target'],{'kind':'plan','course':'','plan_id':self.pid,'lesson_no':1})
        self.assertEqual(self.projection()['completed_lessons'],0)

    def test_concurrent_different_keys_link_only_once(self):
        self.course()
        with ThreadPoolExecutor(3) as pool:results=list(pool.map(lambda _:self.link(),range(3)))
        self.assertEqual([r.status_code for r in results],[200]*3)
        self.assertEqual(len(actions.listing()['plans']),1)

    def test_existing_dated_action_is_reused_without_rescheduling_or_rewriting(self):
        self.course()
        prior=actions.schedule(actions.Schedule(title='本人安排',date='2026-10-30',target={'kind':'plan','plan_id':self.pid,'lesson_no':1},key='existing-course-schedule'))['plan']
        self.assertEqual(self.link().status_code,200)
        self.assertEqual(len(actions.listing()['plans']),1)
        kept=actions.listing()['plans'][0];self.assertEqual(kept['id'],prior['id'])
        self.assertEqual(kept['title'],'本人安排');self.assertEqual(kept['start_date'],'2026-10-30')

    def test_cancelled_linked_action_is_not_resurrected_or_recreated(self):
        self.course();self.assertEqual(self.link().status_code,200)
        p=actions.listing()['plans'][0]
        actions.mutate(p['id'],actions.Mutation(key='cancel-linked-course',revision=p['revision'],action='cancel'))
        self.assertEqual(self.link().status_code,200)
        self.assertEqual(len(actions.listing()['plans']),1)
        self.assertEqual(actions.listing()['plans'][0]['status'],'archived')

    def test_adoption_opt_in_and_publication_auto_supplement(self):
        draft=self.s.draft({'brief':B,'document':D})
        result=self.post('/drafts/'+draft['id']+'/adopt',key='adopt-opt-in',expected_hash=draft['content_hash'],link_actions=True)
        self.assertEqual(result.status_code,200,result.text);self.pid=result.json()['plan_id']
        self.assertTrue(self.projection()['linked'])
        response,draft=self.course();self.assertIn('learning_actions',response.json())
        self.assertEqual(len(actions.listing()['plans']),1)
        replay=self.post('/drafts/'+draft['id']+'/publish',key='publish-'+draft['id'],expected_hash=draft['content_hash'])
        self.assertEqual(replay.status_code,200);self.assertEqual(len(actions.listing()['plans']),1)

    def test_formal_save_survives_sync_failure_and_explicit_retry_recovers(self):
        self.assertEqual(self.link().status_code,200)
        with patch('learning_actions.link',side_effect=RuntimeError('PRIVATE SYNC ERROR')):
            response,_=self.course()
        self.assertIn('learning_action_sync_error',response.json())
        self.assertNotIn('PRIVATE SYNC ERROR',response.text)
        self.assertEqual(len(self.s.lessons(self.pid)),1)
        head=self.repo.head
        self.assertEqual(self.link().status_code,200)
        self.assertEqual(self.repo.head,head);self.assertEqual(len(actions.listing()['plans']),1)

    def test_completed_before_link_does_not_create_redundant_action(self):
        self.course();self.s.feedback(self.pid,1,{'state':'completed','comment':'PRIVATE NOTE'},'done-before-link')
        self.assertEqual(self.link().status_code,200)
        self.assertEqual(actions.listing()['plans'],[])
        progress=self.projection();self.assertEqual(progress['completed_lessons'],1)
        self.assertEqual(progress['percent'],50);self.assertEqual(progress['stages'][0]['percent'],100)
        self.assertNotIn('PRIVATE NOTE',json.dumps(progress))

    def test_source_completion_updates_stage_without_manufacturing_undated_execution(self):
        self.course();self.link();p=actions.listing()['plans'][0]
        response=self.post('/'+self.pid+'/lessons/1/feedback',key='source-confirm-for-progress',state='completed',comment='只作本人反馈')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.projection()['completed_lessons'],1)
        self.assertEqual(actions.listing()['plans'][0]['status'],'active')
        self.assertEqual(self.client.get('/api/action-plans/records').json()['total'],0)

    def test_arranged_course_completion_reuses_existing_c2_receipt(self):
        self.course();self.link();p=actions.listing()['plans'][0]
        day=actions.clock().astimezone(ZoneInfo('Asia/Shanghai')).date()
        changed=actions.mutate(p['id'],actions.Mutation(key='arrange-linked-today',revision=p['revision'],action='reschedule',date=day))['plan']
        response=self.post('/'+self.pid+'/lessons/1/feedback',key='linked-course-completed',state='completed',comment='',origin_action_id=changed['id'])
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(actions.listing()['plans'][0]['status'],'completed')
        self.assertEqual(self.projection()['stages'][0]['completed_lessons'],1)
        self.assertEqual(self.client.get('/api/action-plans/records').json()['total'],1)

    def test_stale_version_rejects_without_ledger_or_actions(self):
        response=self.post('/'+self.pid+'/actions',key='stale-learning-version',expected_version=99)
        self.assertEqual(response.status_code,409,response.text)
        self.assertFalse(self.projection()['linked']);self.assertEqual(actions.listing()['plans'],[])

    def test_disabled_and_paused_plans_do_not_supplement_or_delete_actions(self):
        self.link();self.assertEqual(self.link(enabled=False).status_code,200)
        self.course();self.assertEqual(actions.listing()['plans'],[])
        self.assertEqual(self.link(enabled=True).status_code,200)
        prior=actions.listing()['plans'][0]
        self.assertEqual(self.post('/'+self.pid+'/metadata',key='pause-learning-plan',status='paused').status_code,200)
        self.assertEqual(self.link().status_code,409)
        self.assertEqual(actions.listing()['plans'][0]['revision'],prior['revision'])

    def test_external_ownership_never_falls_back_to_local_actions(self):
        self.course()
        with actions.connection() as c:c.execute('INSERT INTO action_link_state VALUES (1,?,NULL)',(json.dumps({'phase':'active'}),))
        self.assertEqual(self.link().status_code,409)
        with db.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM action_plans').fetchone()[0],0)

    def test_wrong_origin_contract_and_guessed_plan_are_rejected(self):
        body={'data':{'key':'guard-learning-link','expected_version':1}}
        path='/api/plans/'+self.pid+'/actions'
        self.assertEqual(self.client.post(path,json=body,headers={**self.headers,'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.post(path,json=body,headers={'X-Copilot-Request':'1'}).status_code,409)
        self.assertEqual(self.post('/plan-20990101-999/actions',key='unknown-plan-id-key',expected_version=1).status_code,404)

    def test_live_progress_get_does_not_create_or_change_action_records(self):
        self.course();self.link()
        with db.connect() as c:before=[dict(r) for r in c.execute('SELECT * FROM action_plans')]
        for _ in range(3):self.projection()
        with db.connect() as c:self.assertEqual([dict(r) for r in c.execute('SELECT * FROM action_plans')],before)

    def test_all_stages_reach_100_only_after_both_published_courses_confirmed(self):
        self.link();self.course()
        self.s.feedback(self.pid,1,{'state':'completed','comment':''},'first-stage-done')
        tomorrow=(actions.clock().astimezone(ZoneInfo('Asia/Shanghai'))+timedelta(days=1)).isoformat()
        with patch('plans.store.now',return_value=tomorrow):self.course()
        self.assertEqual(self.projection()['percent'],50)
        self.s.feedback(self.pid,2,{'state':'completed','comment':''},'second-stage-done')
        result=self.projection();self.assertEqual(result['percent'],100)
        self.assertEqual([s['percent'] for s in result['stages']],[100,100])
        self.assertEqual(len(actions.listing()['plans']),2)

    def test_capacity_failure_rolls_back_link_and_partial_actions(self):
        self.course()
        original=actions.schedule_in_connection
        def fail_after_insert(c,fields):
            original(c,fields)
            actions.fail(422,'合成容量不足')
        with patch('action_plans.schedule_in_connection',side_effect=fail_after_insert):
            self.assertEqual(self.link().status_code,422)
        self.assertEqual(actions.listing()['plans'],[]);self.assertFalse(self.projection()['linked'])

    def test_same_key_replays_but_cannot_change_enable_flag(self):
        data={'key':'same-learning-request-key','expected_version':1,'enabled':True}
        path='/'+self.pid+'/actions'
        self.assertEqual(self.post(path,**data).status_code,200)
        self.assertEqual(self.post(path,**data).status_code,200)
        self.assertEqual(self.post(path,**{**data,'enabled':False}).status_code,409)

    def test_old_publication_client_saves_source_but_cannot_mutate_actions(self):
        self.link();self.s.save_sources(self.pid,S);ctx=self.s.course_context(self.pid)
        draft=self.s.course_draft(ctx,content(ctx),'摘要 [来源](https://example.org/lesson)')
        response=self.client.post('/api/plans/drafts/'+draft['id']+'/publish',json={'data':{'key':'old-client-publish','expected_hash':draft['content_hash']}},headers={'X-Copilot-Request':'1'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertIn('learning_action_sync_error',response.json())
        self.assertEqual(len(self.s.lessons(self.pid)),1);self.assertEqual(actions.listing()['plans'],[])
        self.assertEqual(self.link().status_code,200);self.assertEqual(len(actions.listing()['plans']),1)
