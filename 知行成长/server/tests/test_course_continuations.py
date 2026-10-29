"""Real isolated PostgreSQL and GitHub journal; deterministic model streams only."""
import asyncio
import copy
import json
import uuid
from unittest.mock import patch
import db
import psycopg2
from cloud_fixtures import AsyncCloudFixture
from copilot.core import Problem, encoded
from copilot.generation import SEPARATOR
from plans.generation import PlanGenerator
from plans.continuation import extension_context
from course_continuations import Continuations
from course_continuation_store import connection,get,rows
from study_materials import Materials
import study_notes
import test_plans

AI={'api_base_url':'https://model.example/v1','api_key':'PRIVATE_TEST_KEY','model_name':'test'}
class ContinuationTests(AsyncCloudFixture):
    def setUp(self):
        self.raw_connect=db.connect
        super().setUp();self.calls=[]
        async def transport(messages,cfg):
            self.calls.append(copy.deepcopy(messages));ctx=json.loads(messages[1]['content'])
            if 'options' in messages[0]['content']:
                raw=json.dumps({'options':[{'mode':m,'title':m+'方向','goal':'继续应用','reason':'衔接已学主题','lesson_count':4} for m in ('consolidate','apply','advance')]})
            elif 'schema' in ctx:
                n=ctx['brief'].get('lesson_count',2);d=copy.deepcopy(test_plans.D)
                d['lessons']=[{**d['lessons'][0],'number':i,'minutes':15,'kind':'review' if i==n else 'lesson','requires':[]} for i in range(1,n+1)]
                raw=json.dumps(d)
            else:raw=test_plans.content(ctx)+SEPARATOR+'教学来源 https://example.org/lesson'
            yield {'text':raw};yield {'done':True}
        self.generator=PlanGenerator(self.s,transport=transport)
        self.service=Continuations(self.s,self.generator,Materials(self.root),None,transport=transport)
        d=self.s.draft({'brief':test_plans.B,'document':test_plans.D});self.pid=self.s.adopt(d['id'],'parent')['plan_id']
        self.publish(self.pid);self.s.feedback(self.pid,1,{'state':'completed','comment':'PRIVATE_FEEDBACK'},'complete-parent-one')
        self.key='plan:'+self.pid

    def publish(self,pid):
        self.s.save_sources(pid,test_plans.S);ctx=self.s.course_context(pid)
        d=self.s.course_draft(ctx,test_plans.content(ctx),'https://example.org/lesson')
        return self.s.publish_course(d['id'],str(uuid.uuid4()))

    def record(self):
        source=self.service.context(self.key)
        return self.service.save(self.key,{'id':uuid.uuid4().hex,'snapshot':source['snapshot'],
            'form':{'direction':'工作汇报表达','scenario':'项目汇报','minutes':15}})

    async def finish(self,generator,job):
        task=generator.tasks.get(job['id'])
        if task:await task
        return self.s.get('learning_ai_attempts',job['id'])

    async def test_changed_private_selection_is_rejected_and_snapshot_read_failure_is_terminal(self):
        r=self.record();choices=self.service.context(self.key)['private_choices'];choice=choices[0]
        with self.assertRaises(Problem):
            await self.service.suggest(r['id'],{'key':'stale-selection','selected_refs':[choice['ref']],
                'selected_versions':{choice['ref']:'old-version'},'ai_config':AI})
        self.assertEqual(self.calls,[])
        with patch('ai_evidence.messages',side_effect=RuntimeError('unreadable frozen input')):
            job=await self.service.suggest(r['id'],{'key':'snapshot-unreadable','ai_config':AI})
            await self.service.tasks[job['id']]
        self.assertEqual(self.service.get_job(job['id'])['state'],'failed')
        self.assertEqual(self.calls,[])

    async def test_advice_selection_is_private_and_plan_adoption_first_lesson_is_recoverable(self):
        study_notes.save('plan',self.pid+'/1',study_notes.Draft(notes='PRIVATE_NOTE_MARKER',answers={'q':'PRIVATE_ANSWER'},version='a'*64,revision=0,key='private-note-key'))
        r=self.record();choices=self.service.context(self.key)['private_choices'];self.assertEqual(len(choices),2)
        job=await self.service.suggest(r['id'],{'key':'advice-without-notes','ai_config':AI});await self.service.tasks[job['id']]
        self.assertNotIn('PRIVATE_NOTE_MARKER',str(self.calls[-1]));self.assertNotIn('PRIVATE_FEEDBACK',str(self.calls[-1]))
        ref=next(x['ref'] for x in choices if x['ref'].startswith('note:'))
        job=await self.service.suggest(r['id'],{'key':'advice-selected-notes','selected_refs':[ref],'ai_config':AI});await self.service.tasks[job['id']]
        self.assertIn('PRIVATE_NOTE_MARKER',str(self.calls[-1]));self.assertNotIn('PRIVATE_FEEDBACK',str(self.calls[-1]))
        self.assertEqual(len(self.service.get_job(job['id'])['options']),3)
        from ai_evidence import read
        with connection() as c:
            saved=read(c,job['evidence_snapshot_id'])
            self.assertEqual(saved['messages'],self.calls[-1])
            self.assertIn('PRIVATE_NOTE_MARKER',str(saved))
            self.assertNotIn('PRIVATE_FEEDBACK',str(saved))
        calls=len(self.calls)
        with patch.object(self.service.sources,'selected',side_effect=AssertionError('replay must not read sources')):
            replay=await self.service.suggest(r['id'],{'key':'advice-selected-notes','selected_refs':[ref],'ai_config':AI})
        self.assertEqual(replay['id'],job['id']);self.assertEqual(len(self.calls),calls)


        generated=await self.service.generate_plan(r['id'],{'key':'plan-after-advice','ai_config':AI});attempt=await self.finish(self.generator,generated)
        self.assertEqual(attempt['state'],'ready',attempt.get('error'));did=attempt['draft_id']
        self.assertNotIn('PRIVATE_NOTE_MARKER',str(self.calls[-1]));self.assertNotIn('PRIVATE_ANSWER',str(self.calls[-1]))
        result=self.service.adopt(r['id'],{'draft_id':did,'expected_hash':self.s.read_draft(did)['content_hash']})
        self.assertEqual(self.service.adopt(r['id'],{'draft_id':did}),result)
        child=result['plan_id'];self.assertNotEqual(child,self.pid)
        self.assertEqual(self.service.context('plan:'+child)['related'][0]['course_key'],self.key)
        self.assertEqual(len(self.s.lessons(self.pid)),1)
        first=await self.service.first_lesson(r['id'],{'key':'first-after-adopt','ai_config':AI});attempt=await self.finish(self.generator,first)
        self.assertEqual(attempt['state'],'ready',attempt.get('error'));self.assertEqual(self.s.lessons(child),[])
        retry=await self.service.first_lesson(r['id'],{'key':'retry-first-new-key','ai_config':AI})
        self.assertEqual(retry['draft_id'],attempt['draft_id'])
        self.s.publish_course(attempt['draft_id'],'publish-new-first')
        self.assertEqual(len(self.s.lessons(child)),1)
        self.assertEqual(self.s.lessons(child)[0]['learning_state'],'unknown')
        public=str(self.repo.commits[self.repo.head]['files'])
        self.assertNotIn('PRIVATE_NOTE_MARKER',public);self.assertNotIn('PRIVATE_ANSWER',public);self.assertNotIn('PRIVATE_TEST_KEY',public)
        with connection() as c:self.assertNotIn('PRIVATE_TEST_KEY',str(rows(c,'course_continuation_jobs'))+str(rows(c,'course_continuations')))

    async def test_same_day_completion_can_generate_and_atomically_publish_one_extension(self):
        self.publish(self.pid);self.s.feedback(self.pid,2,{'state':'completed'},'complete-parent-two')
        old=self.s.version(self.pid);ctx=extension_context(self.s,self.pid)
        self.assertEqual(len(self.s.version(self.pid)['document']['lessons']),2)
        d=self.s.course_draft(ctx,test_plans.content(ctx),'https://example.org/lesson')
        result=self.s.publish_course(d['id'],'extra-course')
        self.assertEqual(result,self.s.publish_course(d['id'],'extra-course'))
        current=self.s.version(self.pid)
        self.assertEqual(current['document']['lessons'][:2],old['document']['lessons'])
        self.assertEqual(current['brief']['lesson_count'],3)
        self.assertEqual([l['learning_state'] for l in self.s.lessons(self.pid)],['completed','completed','unknown'])

    async def test_snapshot_form_revision_and_private_reference_guards(self):
        r=self.record()
        with self.assertRaises(Problem):self.service.save(self.key,{'id':r['id'],'snapshot':r['snapshot'],'revision':0,'form':{'direction':'另一方向'}})
        with self.assertRaises(Problem):await self.service.suggest(r['id'],{'key':'foreign-note-key','selected_refs':['not-from-this-course'],'ai_config':AI})
        self.s.feedback(self.pid,1,{'state':'unknown'},'undo-parent')
        with self.assertRaises(Problem):await self.service.generate_plan(r['id'],{'key':'stale-source-key','ai_config':AI})

    async def test_lost_adoption_response_does_not_create_second_course(self):
        r=self.record();job=await self.service.generate_plan(r['id'],{'key':'adopt-loss-plan','ai_config':AI});a=await self.finish(self.generator,job)
        did=a['draft_id'];original=self.s.adopt
        def lose(*args,**kwargs):original(*args,**kwargs);raise OSError('response lost')
        with patch.object(self.s,'adopt',side_effect=lose):
            with self.assertRaises(OSError):self.service.adopt(r['id'],{'draft_id':did})
        before=len(self.s.rows('learning_plans'));result=self.service.adopt(r['id'],{'draft_id':did})
        self.assertEqual(len(self.s.rows('learning_plans')),before)
        self.assertEqual(self.service.record(r['id'])['new_plan_id'],result['plan_id'])

    async def test_cancel_and_restart_do_not_call_model_again(self):
        r=self.record();job,fresh=self.service.prepare_advice(r['id'],{'key':'queued-advice-key'})
        self.assertTrue(fresh);self.assertEqual(self.calls,[])
        other=Continuations(self.s,self.generator,Materials(self.root),None)
        self.assertEqual(other.get_job(job['id'])['state'],'interrupted');self.assertEqual(self.calls,[])
        job,fresh=self.service.prepare_advice(r['id'],{'key':'cancel-advice-key'})
        self.assertEqual((await self.service.cancel(job['id']))['state'],'cancelled')
        self.assertEqual(self.calls,[])

    async def test_four_source_types_and_paused_plan_keep_authoritative_state(self):
        from study_materials import initialize
        initialize();self.service.copilot=self.seed_courses();self.service.sources.copilot=self.service.copilot
        for name,folder,key in [('英文阅读','每日文章','yingyu'),('结构化表达','每日练习','biaoda')]:
            directory=self.root/name/folder;directory.mkdir(parents=True,exist_ok=True)
            (directory/'Day 001.md').write_text('# 合成课程\n\n教学内容。')
            context=self.service.context(key)
            self.assertEqual(context['next_lesson']['lesson_no'],1)
            self.assertEqual(context['status'],'active')
        cognitive=self.service.context('renzhi');self.assertTrue(cognitive['next_lesson'])
        p=self.s.plan(self.pid);p['status']='paused';self.s.put('learning_plans',self.pid,p)
        self.assertEqual(self.service.context(self.key)['status'],'paused')
        with self.assertRaises(Problem):self.record()

    async def test_missing_sources_keep_adopted_plan_and_allow_explicit_materials(self):
        d=self.s.draft({'brief':test_plans.B,'document':test_plans.D});source=self.s.adopt(d['id'],'empty-source')['plan_id']
        context=self.service.context('plan:'+source)
        r=self.service.save('plan:'+source,{'id':'empty-source-continuation','snapshot':context['snapshot'],'form':{'direction':'学习新方向'}})
        job=await self.service.generate_plan(r['id'],{'key':'empty-source-plan','ai_config':AI});a=await self.finish(self.generator,job)
        result=self.service.adopt(r['id'],{'draft_id':a['draft_id']})
        with self.assertRaises(Problem) as error:await self.service.first_lesson(r['id'],{'key':'missing-sources-first','ai_config':AI})
        self.assertEqual(error.exception.code,'sources');self.assertEqual(self.service.record(r['id'])['new_plan_id'],result['plan_id'])
        job=await self.service.first_lesson(r['id'],{'key':'missing-sources-first','entries':test_plans.S,'ai_config':AI})
        a=await self.finish(self.generator,job);self.assertEqual(a['state'],'ready',a.get('error'))

    async def test_http_same_origin_and_private_state_contract(self):
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        from fastapi.testclient import TestClient
        from course_continuations import register
        app=FastAPI();register(app,self.s,self.generator,Materials(self.root),None)
        @app.exception_handler(Problem)
        async def problem(request,error):return JSONResponse({'error':error.code,'message':error.message},status_code=error.status)
        with TestClient(app) as client:
            response=client.get('/api/course-continuations',params={'course_key':self.key})
            self.assertEqual(response.status_code,200);self.assertEqual(response.headers['cache-control'],'no-store')
            data={'id':'http-continuation','course_key':self.key,'snapshot':response.json()['snapshot'],'form':{'direction':'应用练习'}}
            for headers in ({},{'X-Copilot-Request':'1','Origin':'https://other.example'},{'X-Copilot-Request':'1','Sec-Fetch-Site':'cross-site'}):
                self.assertEqual(client.post('/api/course-continuations',json=data,headers=headers).status_code,403)
            self.assertEqual(client.post('/api/course-continuations',json=data,headers={'X-Copilot-Request':'1'}).status_code,200)
            invalid={**data,'id':'invalid-form-test','form':{'direction':42}}
            self.assertEqual(client.post('/api/course-continuations',json=invalid,headers={'X-Copilot-Request':'1'}).status_code,422)
            self.assertEqual(client.get('/api/course-continuations/jobs/not-in-this-account').status_code,404)

    async def test_strict_sources_reject_unprovided_links(self):
        d=self.s.draft({'brief':test_plans.B,'document':test_plans.D});pid=self.s.adopt(d['id'],'strict-source-plan')['plan_id']
        self.s.save_sources(pid,[{'title':'一本书','content':'只提供书名与教学摘要，没有链接。'}])
        ctx=self.s.course_context(pid);ctx['strict_sources']=True
        bad=self.s.course_draft(ctx,test_plans.content(ctx),'编造的来源 https://invented.example')
        self.assertEqual(bad['state'],'failed')
        good=self.s.course_draft(ctx,test_plans.content(ctx).replace('[来源](https://example.org/lesson)',''),'资料：一本书，教学摘要。')
        self.assertEqual(good['state'],'ready')

    async def test_records_are_tenant_scoped(self):
        r=self.record();raw=db.connect;schema='continuation_other_'+uuid.uuid4().hex
        with psycopg2.connect(self.dsn) as c:c.cursor().execute('CREATE SCHEMA '+schema)
        try:
            # Use the original adapter, not the fixture's already scoped wrapper.
            from test_legacy_cloud_schema import db as db_module
            with psycopg2.connect(self.dsn) as conn:
                conn.cursor().execute('SET search_path TO '+schema)
            with patch('course_continuation_store.db.connect',lambda:self.raw_connect(self.dsn+' options=-csearch_path='+schema,tenant=False)):
                with self.assertRaises(Problem):self.service.record(r['id'])
        finally:
            with psycopg2.connect(self.dsn) as c:c.cursor().execute('DROP SCHEMA '+schema+' CASCADE')
