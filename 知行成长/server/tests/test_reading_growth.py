import asyncio
import copy
import json
import unittest
from unittest.mock import patch

from copilot.core import Problem
from reading.sources import choose
from reading.store import DEFAULT
from reading.service import Reader
from test_legacy_cloud_content import CloudFixture, DATE
from test_legacy_cloud_api import CloudHTTPFixture
from fastapi.testclient import TestClient


class ReadingFeedbackAPITests(CloudHTTPFixture):
    def test_feedback_http_validation_conflict_and_search(self):
        with TestClient(self.app,base_url='http://localhost') as client:
            path='/api/reading/articles/'+self.aid+'/feedback'
            body={'data':{'version':0,'takeaway':'PRIVATE 查找应用机会','tags':['判断'],'mark_read':True}}
            self.assertEqual(client.post(path,json=body).status_code,403)
            headers={'X-Copilot-Request':'1'}
            result=client.post(path,json=body,headers=headers)
            self.assertEqual(result.status_code,200,result.text)
            self.assertTrue(result.json()['read'])
            self.assertEqual(client.post(path,json=body,headers=headers).status_code,409)
            found=client.get('/api/reading',params={'search':'查找应用机会'}).json()['articles']
            self.assertEqual([a['id'] for a in found],[self.aid])
            self.assertEqual(found[0]['feedback']['version'],1)
            body['data'].update(version=1,tags=['x'*33])
            self.assertEqual(client.post(path,json=body,headers=headers).status_code,422)
            result=client.get('/api/reading/articles/'+self.aid).json()
            self.assertEqual(result['article']['feedback']['takeaway'],'PRIVATE 查找应用机会')
            self.assertEqual(result['note']['text'],'PRIVATE READING NOTE')
            self.assertNotIn('PRIVATE',json.dumps(self.repository.commits[self.repository.head]['files']))


class ReadingGrowthTests(CloudFixture):
    def setUp(self):
        super().setUp();self.aid=self.source_article();self.migrate_files()

    def feedback(self, **changes):
        return {'version':0,'value':'insightful','difficulty':'right','takeaway':'PRIVATE 机会成本收获',
                'question':'PRIVATE 怎么核实证据','action':'PRIVATE 下次开会先说结论','tags':['机会成本','表达'],**changes}

    def test_feedback_persists_is_searchable_and_never_published(self):
        result=self.reader.save_feedback(self.aid,self.feedback())
        self.assertEqual(result['feedback']['version'],1)
        self.assertFalse(result['read'])
        self.assertEqual(self.reader.note(self.aid)['text'],'PRIVATE READING NOTE')
        for query in ('机会成本收获','核实证据','开会先说结论','表达'):
            self.assertEqual([a['id'] for a in self.reader.search_articles(query)],[self.aid])
        self.reader.initialize()
        self.assertEqual(self.reader.article(self.aid)['feedback']['value'],'insightful')
        self.assertNotIn('PRIVATE',json.dumps(self.repository.commits[self.repository.head]['files']))

    def test_feedback_conflict_preserves_newer_input_and_mark_read_is_explicit(self):
        saved=self.reader.save_feedback(self.aid,self.feedback(mark_read=True))
        self.assertTrue(saved['read'])
        with self.assertRaises(Problem):self.reader.save_feedback(self.aid,self.feedback(takeaway='stale'))
        self.assertEqual(self.reader.article(self.aid)['feedback']['takeaway'],'PRIVATE 机会成本收获')
        with self.assertRaises(Problem):self.reader.save_feedback(self.aid,self.feedback(version=1,value='invented'))
        saved=self.reader.save_feedback(self.aid,self.feedback(version=1,value='neutral',tags=[]))
        self.assertTrue(saved['read']);self.assertEqual(saved['feedback']['version'],2)

    def test_chinese_guide_has_key_points_uses_saved_source_and_preserves_private_feedback(self):
        self.reader.save_feedback(self.aid,self.feedback())
        self.reader.save_full_text(self.aid,'Verified English article about evidence and careful decisions. '*20)
        captured=[]
        guide='# 学会检查判断的证据\n\n## 中文导读\n这篇文章讨论如何检查判断的依据，区分观察与解释，并主动寻找能够推翻自己想法的证据。\n\n## 核心观点\n- 先提出可以核验的问题。\n- 区分事实和个人解释。\n- 寻找相反证据，避免过早下结论。\n\n## 证据与边界\n文章提供了示例，不能据此断言所有场景都适用，仍需检查观察条件。\n\n## 英文阅读提示\nevidence：证据；decision：判断。先识别主张，再找作者的限定词。\n\n## 联系实际\n下次做决定前，写下一个反例，并说清楚自己判断的依据。'
        async def model(messages,cfg):
            captured.append(messages);yield {'text':guide};yield {'done':True}
        async def run():
            service=Reader(self.reader,transport=model)
            job=service.begin({'key':'learning-guide','kind':'guide','article_id':self.aid,'guide_format':'reading-v2'})
            await asyncio.gather(*list(service.tasks.values()))
            self.assertEqual(self.reader.record(job['id'])['state'],'ready')
        asyncio.run(run())
        result=self.reader.article(self.aid)
        self.assertEqual(result['guide_version'],'reading-v2')
        self.assertEqual(result['zh_title'],'学会检查判断的证据')
        self.assertEqual(result['guide_basis'],'saved_text')
        self.assertIn('## 核心观点',result['guide'])
        self.assertIn('Verified English article',str(captured))
        self.assertNotIn('PRIVATE',str(captured))
        self.assertEqual(result['feedback']['takeaway'],'PRIVATE 机会成本收获')
        self.assertNotIn('PRIVATE',json.dumps(self.repository.commits[self.repository.head]['files']))

    def test_incomplete_chinese_guide_does_not_replace_existing_reading_material(self):
        old=self.reader.article(self.aid)['guide']
        async def model(messages,cfg):
            yield {'text':'# 随意的标题\n没有核心观点和边界。'};yield {'done':True}
        async def run():
            service=Reader(self.reader,transport=model)
            job=service.begin({'key':'bad-learning-guide','kind':'guide','article_id':self.aid,'guide_format':'reading-v2'})
            await asyncio.gather(*list(service.tasks.values()))
            self.assertEqual(self.reader.record(job['id'])['state'],'failed')
        asyncio.run(run())
        self.assertEqual(self.reader.article(self.aid)['guide'],old)


class DiverseReadingTests(unittest.TestCase):
    def candidates(self):
        return [{'id':str(i),'title':'Thinking and society','summary':'Psychology and technology',
                 'source':'source-'+str(i),'language':'en','topics':['心理','科技','社会学'],
                 'published_at':DATE[:10],'category':'recent'} for i in range(20)]

    def test_seeded_selection_varies_but_retries_are_stable_and_never_repeat_saved(self):
        p={**DEFAULT,'mode':'recent'};rows=self.candidates()
        first=choose(rows,p,set(),DATE[:10],seed='daily-1')
        self.assertEqual(first,choose(list(reversed(rows)),p,set(),DATE[:10],seed='daily-1'))
        choices={tuple(a['id'] for a in choose(rows,p,set(),DATE[:10],seed='day-'+str(i))) for i in range(10)}
        self.assertGreater(len(choices),1)
        seen={a['id'] for a in first}
        self.assertFalse(seen & {a['id'] for a in choose(rows,p,seen,DATE[:10],seed='daily-2')})

    def test_negative_feedback_does_not_hide_an_entire_selected_topic(self):
        p={**DEFAULT,'mode':'recent','topics':['心理','科技','社会学'],'count':3}
        rows=self.candidates()[:3]
        for row,topic in zip(rows,p['topics']):row['topics']=[topic]
        history=[{'id':'old','topics':['科技'],'feedback':{'value':'not_for_me'}}]
        result=choose(rows,p,set(),DATE[:10],seed='varied',history=history)
        self.assertEqual({t for a in result for t in a['topics']},set(p['topics']))
