"""Isolated behavior checks; no real database, network or model calls."""
import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from copilot.core import Problem,now,encoded,digest
from copilot.api import register as register_legacy
from plans.store import Plans,brief,document,sources
from plans.generation import PlanGenerator,messages
from plans.api import register
from plans.backup import snapshot,preview,restore
from cloud_fixtures import CloudFixture,AsyncCloudFixture

B={'title':'经济学','goal':'理解经济新闻','level':'零基础','weeks':2,'sessions':1,'minutes':20}
D={'prerequisites':'无需先修','stages':[{'title':'基础','goal':'解释概念'}],
   'lessons':[{'number':n,'topic':'主题'+str(n),'goal':'解释概念','exercise':'举例','assessment':'说明边界','stage':1,
               'kind':'review' if n==2 else 'lesson','minutes':20,'requires':[] if n==1 else [1]} for n in (1,2)]}
S=[{'title':'资料','content':'明确选择的教学摘要。 https://example.org/lesson'}]
def content(ctx):
    return f'# 第{ctx["lesson_no"]:03d}课：示范\n日期：{ctx["date"]}\n## 引导问题\n问题\n## 核心概念\n概念\n## 完整示范\n示范\n## 误区与边界\n边界\n## 练习\n练习\n\n---\n\n## 参考分析\n分析\n## 自查\n自查\n## 记忆提示\n提示\n[来源](https://example.org/lesson)'

class StoreTests(CloudFixture):
    def adopt(self):
        d=self.s.draft({'brief':B,'document':D});return self.s.adopt(d['id'],d['id'])['plan_id']
    def test_server_model_settings_are_rejected(self):
        from copilot.core import Store
        from copilot.generation import config
        legacy=Store(self.root,self.s.db)
        with legacy.conn() as c:
            c.execute('CREATE TABLE IF NOT EXISTS copilot_settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        values={'api_base_url':'https://example.org/v1/chat/completions',
                'api_key':'test-only-key','model_name':'test-model'}
        with self.assertRaises(Problem):legacy.update_settings(values)
        self.assertEqual(config(self.s)['key'],'')
        self.assertEqual(config(legacy)['model'],'')
    def course(self,pid):
        self.s.save_sources(pid,S);ctx=self.s.course_context(pid)
        d=self.s.course_draft(ctx,content(ctx),'摘要 [来源](https://example.org/lesson)')
        return self.s.publish_course(d['id'],d['id'])
    def test_identity_and_idempotency(self):
        d=self.s.draft({'brief':B,'document':D});a=self.s.adopt(d['id'],'key');self.assertEqual(a,self.s.adopt(d['id'],'key'))
        self.assertNotEqual(a['plan_id'],self.adopt());self.assertFalse(self.s.runtime.exists())
        self.assertIn('经济学',self.public(self.s.base(a['plan_id'])+'/规划历史/v001.md'))
    def test_validation(self):
        for field,value in [('number',9),('minutes',90),('requires',[2])]:
            doc=copy.deepcopy(D);doc['lessons'][0][field]=value
            with self.assertRaises(Problem):document(doc,B)
        with self.assertRaises(Problem):brief({**B,'weeks':False})
        with self.assertRaises(Problem):document({**D,'lessons':[]},B)
    def test_budget(self):
        self.assertIsNone(self.s.budget()['weekly']);self.s.put('learning_settings','budget',{'id':'budget','weekly':10,'legacy_weekly':0})
        d=self.s.draft({'brief':B,'document':D})
        with self.assertRaises(Problem):self.s.adopt(d['id'],'over')
        self.s.adopt(d['id'],'yes',True);self.assertEqual(self.s.budget()['over'],10)
    def test_path_protection(self):
        for path in ('学习计划/../secret','/etc/passwd','学习计划/a/学习记录.md'):
            with self.assertRaises(Problem):self.content.path(path)
        with self.assertRaises(Problem):self.s.path('学习计划/a/学习规划.md')

    def test_course_and_day_rules(self):
        pid=self.adopt();r=self.course(pid);self.assertTrue(r['commit_sha']);self.assertFalse(self.s.runtime.exists());self.assertEqual(self.s.lessons(pid)[0]['learning_state'],'unknown')
        with self.assertRaises(Problem):self.s.course_context(pid)
        self.course(self.adopt());self.assertEqual(len(self.s.lessons(pid)),1)
    def test_answer_separator_must_precede_analysis(self):
        pid=self.adopt();self.s.save_sources(pid,S);ctx=self.s.course_context(pid)
        misplaced=content(ctx).replace('\n---\n','').replace('## 自查','---\n\n## 自查')
        d=self.s.course_draft(ctx,misplaced,'摘要 https://example.org/lesson')
        self.assertEqual(d['state'],'failed')
        with self.assertRaises(Problem):self.s.publish_course(d['id'],'misplaced')
    def test_source_boundaries(self):
        with self.assertRaises(Problem):sources([{'title':'资料','content':''}])
        pid=self.adopt()
        with self.assertRaises(Problem):self.s.course_context(pid)
        self.s.save_sources(pid,S);ctx=self.s.course_context(pid);d=self.s.course_draft(ctx,content(ctx),'https://other.example/test')
        self.assertEqual(d['state'],'failed')
        with self.assertRaises(Problem):self.s.publish_course(d['id'],'bad')
    def test_revision_freezes_published(self):
        pid=self.adopt();self.course(pid);doc=copy.deepcopy(D);doc['lessons'][0]['goal']='替换'
        d=self.s.draft({'brief':B,'document':doc,'plan_id':pid,'base_version':1})
        with self.assertRaises(Problem):self.s.adopt(d['id'],'bad')
        doc=copy.deepcopy(D);doc['lessons'][1]['goal']='新目标'
        d=self.s.draft({'brief':B,'document':doc,'plan_id':pid,'base_version':1});stale=self.s.draft({'brief':B,'document':D,'plan_id':pid,'base_version':1})
        self.s.adopt(d['id'],'good')
        with self.assertRaises(Problem):self.s.adopt(stale['id'],'stale')
    def test_gap_keeps_continuous_numbering(self):
        from datetime import date,timedelta
        pid=self.adopt();self.course(pid)
        later=(date.fromisoformat(now()[:10])+timedelta(days=3)).isoformat()+'T10:00:00+08:00'
        with patch('plans.store.now',return_value=later):
            self.s.save_sources(pid,S);ctx=self.s.course_context(pid)
            self.assertEqual(ctx['lesson_no'],2)
            self.assertEqual(ctx['date'],later[:10])
        self.assertNotEqual(self.s.lessons(pid)[0]['date'],later[:10])

    def test_course_draft_version_conflict(self):
        pid=self.adopt();self.s.save_sources(pid,S);ctx=self.s.course_context(pid);course=self.s.course_draft(ctx,content(ctx),'https://example.org/lesson')
        d=self.s.draft({'brief':B,'document':D,'plan_id':pid,'base_version':1});self.s.adopt(d['id'],'rev')
        with self.assertRaises(Problem):self.s.publish_course(course['id'],'old')
    def test_notes_and_feedback_idempotency(self):
        pid=self.adopt();self.course(pid);head=self.repo.head
        for _ in range(2):self.s.feedback(pid,1,{'state':'completed','comment':'PRIVATE FEEDBACK'},'feedback')
        self.assertEqual(self.repo.head,head)
        self.assertEqual(self.s.lessons(pid)[0]['learning_state'],'completed')
        self.assertNotIn('PRIVATE FEEDBACK',str(self.repo.commits[head]['files']))

    def test_external_import(self):
        pid=self.adopt();path=self.s.base(pid)+'/学习规划.md';old=self.public(path)
        self.external(path,old+'\n手动补充\n')
        d=self.s.draft({'brief':B,'document':D,'plan_id':pid,'base_version':1})
        with self.assertRaises(Problem):self.s.adopt(d['id'],'conflict')
        d=self.s.draft({'brief':B,'document':D,'plan_id':pid,'base_version':1,'external_hash':digest(self.public(path))})
        self.s.adopt(d['id'],'import')
        self.assertIn('手动补充',self.public(self.s.base(pid)+'/规划历史/外部修改-v002.md'))

    def test_recovery_after_partial_write(self):
        pid=self.adopt();self.s.save_sources(pid,S);ctx=self.s.course_context(pid)
        draft=self.s.course_draft(ctx,content(ctx),'摘要 https://example.org/lesson')
        self.repo.lose_response=True
        with self.assertRaises(Problem):self.s.publish_course(draft['id'],'interrupted')
        head=self.repo.head;fresh=self.new_plans();fresh.initialize()
        self.assertIn('核心概念',fresh.read_course(pid,1)['content'])
        self.assertEqual(self.repo.head,head)

    def test_recovery_stops_unknown_hash(self):
        pid=self.adopt();self.s.save_sources(pid,S);ctx=self.s.course_context(pid)
        d=self.s.course_draft(ctx,content(ctx),'摘要 https://example.org/lesson');self.repo.fail_update=True
        with self.assertRaises(Problem):self.s.publish_course(d['id'],'pending')
        self.repo.fail_update=False;path=self.s.base(pid)+'/学习规划.md'
        self.external(path,'external personal content')
        with self.assertRaises(Problem):
            with self.s.lock():self.s.recover_locked()
        self.assertEqual(self.public(path),'external personal content')

    def test_backup_restore(self):
        pid=self.adopt();self.course(pid);head=self.repo.head
        with self.assertRaises(Problem) as error:snapshot(self.s)
        self.assertEqual(error.exception.code,'remote_backup')
        self.assertEqual(self.repo.head,head);self.assertFalse(self.s.runtime.exists())

    def test_legacy_sync_keeps_plans(self):
        import app
        pid=self.adopt()
        with patch.object(app,'DB_PATH',self.s.db):app.init_db();app.save_state({'modules':app.DEFAULT_MODULES});app.save_state({'modules':[]})
        self.assertEqual(self.s.plan(pid)['name'],B['title'])
    def test_api_metadata_and_auth(self):
        app=FastAPI();register_legacy(app,self.root,self.s.db);s,g=register(app,self.root,self.s.db);headers={'X-Copilot-Request':'1'}
        with TestClient(app,base_url='http://localhost') as c:
            self.assertEqual(c.get('/api/plans').status_code,200)
            self.assertEqual(c.post('/api/plans/drafts',json={'data':{'brief':B,'document':D}}).status_code,403)
            d=c.post('/api/plans/drafts',json={'data':{'brief':B,'document':D}},headers=headers).json()
            p=c.post('/api/plans/drafts/'+d['id']+'/adopt',json={'data':{'key':'adopt','expected_hash':d['content_hash']}},headers=headers).json();pid=p['plan_id'];path=s.base(pid)
            self.assertEqual(c.post('/api/plans/'+pid+'/metadata',json={'data':{'key':'rename','name':'新名字'}},headers=headers).status_code,200)
            self.assertEqual(s.plan(pid)['name'],'新名字');self.assertEqual(path,s.base(pid))
            self.assertEqual(c.post('/api/plans/budget',json={'data':{}},headers={**headers,'Origin':'https://evil.example'}).status_code,403)
            c.post('/api/plans/'+pid+'/metadata',json={'data':{'key':'pause','status':'paused'}},headers=headers)
            with self.assertRaises(Problem):s.course_context(pid)

    def test_missing_tracked_file_blocks_writes(self):
        pid=self.adopt();self.external(self.s.base(pid)+'/课程目录.md',None)
        with self.assertRaises(Problem):self.s.save_sources(pid,S)

    def test_concurrent_plan_ids(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as pool:
            ids=list(pool.map(lambda _:self.adopt(),range(3)))
        self.assertEqual(len(set(ids)),3)

    def test_backup_redacts_database_api_key(self):
        self.adopt()
        with self.s.conn() as c:c.execute('INSERT INTO copilot_settings VALUES (?,?)',('api_key',encoded('NEVER_EXPORT_THIS_KEY')))
        with self.assertRaises(Problem) as error:snapshot(self.s)
        self.assertEqual(error.exception.code,'remote_backup')
        self.assertNotIn('NEVER_EXPORT_THIS_KEY',str(self.repo.commits))

    def test_stale_backup_preview_and_offline_block(self):
        self.adopt()
        for action in (lambda:preview(self.s,self.root/'missing'),lambda:restore(self.s,self.root/'missing','bad')):
            with self.assertRaises(Problem) as error:action()
            self.assertEqual(error.exception.code,'remote_backup')
        self.s.initialize();self.assertFalse(self.s.runtime.exists())

    def test_full_api_lifecycle_with_simulated_model(self):
        import time
        app=FastAPI();register_legacy(app,self.root,self.s.db);store,g=register(app,self.root,self.s.db)
        async def fake(messages,config):
            ctx=json.loads(messages[1]['content'])
            if 'schema' in ctx:output=json.dumps(D)
            else:output=content(ctx)+'\n<!-- COPILOT_SOURCES -->\n资料摘要 [来源](https://example.org/lesson)'
            yield {'text':output};yield {'done':True}
        g.transport=fake
        headers={'X-Copilot-Request':'1'}
        with TestClient(app,base_url='http://localhost') as c:
            def post(path,data):
                if path.endswith(('/adopt','/publish')):
                    data={**data,'expected_hash':c.get('/api/plans'+path.rsplit('/',1)[0]).json()['content_hash']}
                r=c.post('/api/plans'+path,json={'data':data},headers=headers)
                self.assertEqual(r.status_code,200,r.text);return r.json()
            def generate(data):
                a=post('/generate',{**data,'ai_config':{'api_base_url':'https://model.example/v1','api_key':'TEST_ONLY_KEY','model_name':'test-model'}})
                for _ in range(100):
                    result=c.get('/api/plans/attempts/'+a['id']).json()
                    if result['state'] not in ('queued','generating'):break
                    time.sleep(.01)
                self.assertEqual(result['state'],'ready',result)
                return result['draft_id']
            did=generate({'key':'plan-ai','kind':'plan','brief':B})
            pid=post('/drafts/'+did+'/adopt',{'key':'adopt'})['plan_id']
            post('/'+pid+'/sources',{'entries':S})
            did=generate({'key':'course-ai','kind':'course','plan_id':pid})
            lesson=post('/drafts/'+did+'/publish',{'key':'publish'})
            self.assertEqual(lesson['lesson_no'],1)
            self.assertIn('核心概念',c.get('/api/plans/'+pid+'/lessons/1').json()['content'])
            post('/'+pid+'/lessons/1/feedback',{'key':'feedback','state':'completed','comment':'练习偏难'})
            did=generate({'key':'revision-ai','kind':'plan','brief':B,'plan_id':pid,'base_version':1,'feedback_lessons':[1]})
            self.assertEqual(post('/drafts/'+did+'/adopt',{'key':'rev'})['version'],2)
            result=c.get('/api/plans').json()['plans'][0]
            self.assertEqual(result['lessons'][0]['learning_state'],'completed')

class GenerationTests(AsyncCloudFixture):
    async def test_generation_only_once(self):
        calls=[]
        async def stream(messages,config):calls.append(messages);yield {'text':json.dumps(D)};yield {'done':True}
        g=PlanGenerator(self.s,stream);body={'key':'k1','kind':'plan','brief':B};g.begin(body);g.begin(body);await asyncio.gather(*list(g.tasks.values()))
        a=self.s.get('learning_ai_attempts','k1');self.assertEqual(a['state'],'ready');self.assertEqual(len(calls),1);self.assertIsNone(a['cost']);g.begin(body);self.assertEqual(len(calls),1)
        with self.assertRaises(Problem):g.begin({**body,'brief':{**B,'title':'other'}})
    async def test_cancel_and_incomplete(self):
        async def truncated(messages,config):yield {'text':'partial'}
        g=PlanGenerator(self.s,truncated);g.begin({'key':'t','kind':'plan','brief':B});await asyncio.gather(*list(g.tasks.values()));self.assertEqual(self.s.get('learning_ai_attempts','t')['state'],'failed')
        async def hanging(messages,config):yield {'text':'part'};await asyncio.sleep(30)
        g=PlanGenerator(self.s,hanging);g.begin({'key':'c','kind':'plan','brief':B});await asyncio.sleep(.01);g.cancel('c');await g.shutdown();self.assertEqual(self.s.get('learning_ai_attempts','c')['state'],'cancelled')
    async def test_no_private_notes_and_restarts(self):
        d=self.s.draft({'brief':B,'document':D});pid=self.s.adopt(d['id'],'a')['plan_id'];self.s.save_sources(pid,S)
        with self.s.conn() as c:c.execute('INSERT INTO learning_feedback VALUES (?,?,?)',(pid,1,encoded({'comment':'SECRET PERSONAL NOTE'})))
        payload=encoded(messages('course',self.s.course_context(pid)))
        self.assertNotIn('SECRET PERSONAL NOTE',payload);self.assertIn(S[0]['content'],payload)
        self.s.put('learning_ai_attempts','old',{'state':'generating','raw':'partial'});self.s.initialize();self.assertEqual(self.s.get('learning_ai_attempts','old')['state'],'failed')

class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_sse_completion_and_usage(self):
        import httpx
        from copilot.transport import qwen_stream
        original=httpx.AsyncClient
        chunks='data: '+json.dumps({'choices':[{'delta':{'content':'内容'},'finish_reason':None}]})+'\n\n'
        chunks+='data: '+json.dumps({'choices':[{'delta':{},'finish_reason':'stop'}]})+'\n\n'
        chunks+='data: '+json.dumps({'choices':[],'usage':{'prompt_tokens':1,'completion_tokens':2}})+'\n\ndata: [DONE]\n\n'
        transport=httpx.MockTransport(lambda req:httpx.Response(200,text=chunks))
        with patch('httpx.AsyncClient',side_effect=lambda **kw:original(transport=transport,**kw)):
            result=[x async for x in qwen_stream([],{'url':'https://example.org/chat/completions','key':'test','model':'test'})]
        self.assertEqual(result[-1],{'done':True});self.assertEqual(result[-2]['usage']['completion_tokens'],2)

    async def test_sse_rejects_truncation(self):
        import httpx
        from copilot.transport import qwen_stream
        original=httpx.AsyncClient
        for chunks in ['data: [DONE]\n\n','data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\ndata: [DONE]\n\n']:
            transport=httpx.MockTransport(lambda req:httpx.Response(200,text=chunks))
            with patch('httpx.AsyncClient',side_effect=lambda **kw:original(transport=transport,**kw)):
                with self.assertRaises(ValueError):
                    [x async for x in qwen_stream([],{'url':'https://example.org/chat','key':'test','model':'test'})]

if __name__=='__main__':unittest.main()
