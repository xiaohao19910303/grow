"""Isolated checks for partial output, immutable branches and scoped publication."""
import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from copilot.core import Problem, now, encoded
from plans.store import Plans
from plans.progress import complete_items, preview, projection
from plans.refinement import merge, sections, validate_scope
from plans.generation import PlanGenerator
from plans.backup import snapshot, restore, preview as restore_preview
from test_plans import B, D, S, content

class ProgressTests(unittest.TestCase):
    def test_every_split_escaped_nested_reordered(self):
        doc=copy.deepcopy(D);doc['lessons'][0]['topic']='引号"、括号} [与换行\n'
        raw=encoded({'lessons':doc['lessons'],'unrelated':{'x':['}']},'stages':doc['stages']})
        for i in range(len(raw)+1):
            for k,values in complete_items(raw[:i],['stages','lessons']).items():self.assertEqual(values,doc[k][:len(values)])
        self.assertEqual(complete_items(raw,['stages','lessons']),{'stages':doc['stages'],'lessons':doc['lessons']})
        self.assertEqual(complete_items('not json',['lessons']),{'lessons':[]})
    def test_bad_structure_and_projection(self):
        a={'kind':'plan','raw':encoded({'stages':[{'title':[],'goal':'x'}],'lessons':[{'number':1,'topic':'x'}]})}
        self.assertEqual(preview(a)['lessons'],[]);self.assertEqual(preview(a)['stages'],[])
        a={'id':'id','kind':'course','state':'generating','phase':'receiving','created_at':now(),'revision':5,'raw':'正文\n<!-- COPILOT_SOUR'}
        self.assertEqual(preview(a)['content'],'正文')
        result=projection(a,5);self.assertNotIn('preview',result);self.assertNotIn('raw',result);self.assertNotIn('context',result)
        a['raw']='正文\n<!-- COPILOT_SOURCES -->\n资料';self.assertEqual(preview(a)['sources'],'资料')

class DraftTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name);(root/'server').mkdir();self.s=Plans(root,root/'server/data.db');self.s.initialize()
    def tearDown(self):self.temp.cleanup()
    def draft(self):return self.s.draft({'brief':B,'document':D})
    def child(self,d,topic):
        doc=copy.deepcopy(d['document']);doc['lessons'][0]['topic']=topic
        return self.s.draft({'brief':d['brief'],'document':doc,'parent_draft_id':d['id'],'parent_hash':d['content_hash']})
    def course(self):
        d=self.draft();pid=self.s.adopt(d['id'],'plan')['plan_id'];self.s.save_sources(pid,S);ctx=self.s.course_context(pid)
        return self.s.course_draft(ctx,content(ctx),'摘要 [来源](https://example.org/lesson)')
    def test_noop_branch_diff_pagination(self):
        d=self.draft();self.assertEqual(d['id'],self.child(d,D['lessons'][0]['topic'])['id'])
        a=self.child(d,'A');b=self.child(d,'B');self.assertEqual(a['family_id'],b['family_id']);self.assertEqual(b['parent_draft_id'],d['id'])
        self.assertEqual(b['diff'][0]['before'],D['lessons'][0]['topic']);self.assertEqual(b['diff'][0]['after'],'B');self.assertEqual(self.s.read_draft(d['id'])['document'],D)
        self.assertEqual(self.s.draft_history(d['id'],0,1)['next_offset'],1);self.assertEqual(self.s.draft_history(d['id'],2,1)['next_offset'],None)
    def test_concurrent_family_adoption_and_hash(self):
        d=self.draft();a=self.child(d,'A');b=self.child(d,'B')
        with self.assertRaises(Problem):self.s.adopt(a['id'],'wrong',expected_hash='wrong')
        def adopt(x):
            try:return self.s.adopt(x['id'],x['id'],expected_hash=x['content_hash'])
            except Problem:return None
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(adopt,[a,b]))
        self.assertEqual(sum(x is not None for x in results),1);self.assertEqual(len(self.s.rows('learning_plans')),1)
        with self.assertRaises(Problem):self.child(d,'too late')
    def test_migration_and_backup_family(self):
        d=self.draft();old=self.s.get('learning_drafts',d['id']);old.pop('family_id');old.pop('parent_draft_id');self.s.put('learning_drafts',d['id'],old)
        with self.s.conn() as c:c.execute('DROP TABLE learning_draft_families')
        self.s.initialize();self.assertEqual(self.s.read_draft(d['id'])['family_id'],d['id'])
        with self.s.lock():backup=snapshot(self.s)
        self.child(self.s.read_draft(d['id']),'A');token=restore_preview(self.s,backup['path'])['token'];restore(self.s,backup['path'],token)
        self.assertEqual(len(self.s.draft_history(d['id'])['items']),1)
    def test_scoped_plan_merge(self):
        d=self.draft();scope=validate_scope(d,{'mode':'selected','lessons':[2],'fields':['exercise']})
        result=merge(d,scope,{'updates':[{'number':2,'changes':{'exercise':'新练习'}}]})
        self.assertEqual(result['document']['lessons'][0],d['document']['lessons'][0]);self.assertEqual(result['brief'],d['brief'])
        for output in [{'updates':[{'number':1,'changes':{'exercise':'x'}}]}, {'updates':[{'number':2,'changes':{'topic':'x'}}]}, {'updates':[]}, {'updates':[{'number':2,'changes':{'exercise':'x'}}],'brief':B}]:
            with self.assertRaises(Problem):merge(d,scope,output)
        with self.assertRaises(Problem):validate_scope(d,{'mode':'selected','lessons':[1],'fields':['exercise']},[1])
    def test_course_merge_and_publication(self):
        d=self.course();part=next(x for x in sections(d['content']) if x['title']=='完整示范');scope=validate_scope(d,{'mode':'selected','sections':[part['id']]})
        result=merge(d,scope,{'sections':[{'id':part['id'],'text':'## 完整示范\n新示范\n'}]})
        self.assertEqual(result['sources'],d['sources']);self.assertEqual(result['context'],d['context'])
        self.assertEqual(result['content'][:part['start']],d['content'][:part['start']]);self.assertTrue(result['content'].endswith(d['content'][part['end']:]))
        child=self.s.course_draft(d['context'],result['content'],result['sources'],parent_id=d['id'],parent_hash=d['content_hash'])
        self.assertEqual(child['diff'][0]['path'],'课程/完整示范');self.s.publish_course(child['id'],'save',child['content_hash'])
        with self.assertRaises(Problem):self.s.publish_course(d['id'],'old',d['content_hash'])
    def test_invalid_section_and_edit_preserved(self):
        d=self.course();sid=d['sections'][0]['id'];scope={'mode':'selected','sections':[sid]}
        for value in ['## 另一个标题\nx','## 引导问题\nx\n## 新章节\ny']:
            with self.assertRaises(Problem):merge(d,scope,{'sections':[{'id':sid,'text':value}]})
        with self.assertRaises(Problem):self.s.course_draft(d['context'],'错误正文',d['sources'],parent_id=d['id'],parent_hash=d['content_hash'])
        self.assertEqual(len(self.s.draft_history(d['id'])['items']),1);self.assertEqual(sections('## 重复\na\n## 重复\nb'),[])
    def test_crossday_explicit_child_and_source_conflict(self):
        d=self.course();from datetime import datetime,timedelta
        later=(datetime.fromisoformat(now())+timedelta(days=1)).isoformat()
        with patch('plans.store.now',return_value=later):
            with self.assertRaises(Problem):self.s.publish_course(d['id'],'old-day')
            child=self.s.redate_course(d['id'],d['content_hash']);self.assertNotEqual(child['context']['date'],d['context']['date'])
            self.assertEqual(self.s.read_draft(d['id'])['context']['date'],d['context']['date'])
            self.s.save_sources(d['context']['plan_id'],[{'title':'新资料','content':'新内容'}])
            with self.assertRaises(Problem):self.s.publish_course(child['id'],'stale-sources')

class RefineGenerationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name);(root/'server').mkdir();self.s=Plans(root,root/'server/data.db');self.s.initialize()
    async def asyncTearDown(self):self.temp.cleanup()
    async def test_stream_refinement(self):
        d=self.s.draft({'brief':B,'document':D});calls=[]
        async def fake(messages,config):
            calls.append(messages);raw=encoded({'updates':[{'number':2,'changes':{'exercise':'明确练习'}}]})
            for i in range(0,len(raw),7):yield {'text':raw[i:i+7]}
            yield {'done':True}
        g=PlanGenerator(self.s,fake);body={'key':'refine','kind':'plan','operation':'refine','parent_draft_id':d['id'],'parent_hash':d['content_hash'],'instruction':'练习更明确','scope':{'mode':'selected','lessons':[2],'fields':['exercise']}}
        g.begin(body);g.begin(body);await asyncio.gather(*list(g.tasks.values()));a=self.s.get('learning_ai_attempts','refine')
        self.assertEqual(a['state'],'ready',a.get('error'));self.assertTrue(a['first_content_at']);self.assertGreater(a['revision'],3)
        child=self.s.read_draft(a['draft_id']);self.assertEqual(child['document']['lessons'][1]['exercise'],'明确练习');self.assertEqual(child['parent_draft_id'],d['id']);self.assertEqual(len(calls),1)
    async def test_timeout(self):
        async def slow(messages,config):await asyncio.sleep(1);yield {'done':True}
        g=PlanGenerator(self.s,slow)
        with patch.object(self.s,'get_setting',side_effect=lambda key,default='':.01 if key=='generation_total_timeout_seconds' else default):g.begin({'key':'timeout','kind':'plan','brief':B})
        await asyncio.gather(*list(g.tasks.values()));a=self.s.get('learning_ai_attempts','timeout');self.assertEqual(a['state'],'failed');self.assertIn('时限',a['error']);self.assertIsNone(a['draft_id'])
