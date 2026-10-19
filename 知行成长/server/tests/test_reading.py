import asyncio
import copy
import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
from copilot.core import Problem,now
from reading.sources import parse_feed,canonical,identify,choose,FEEDS,CLASSICS
from reading.store import ReadingStore,DEFAULT,TABLE
from reading.service import Reader
from plans.backup import snapshot
from cloud_fixtures import AsyncCloudFixture


class SourceTests(unittest.TestCase):
    def test_technology_preference_matches_science_and_chinese_articles(self):
        from reading.store import preferences
        from reading.sources import matches
        p=preferences({**DEFAULT,'topics':['科技']})
        for title in ('New science in space and physics','人工智能与科技进展'):
            self.assertTrue(matches({'title':title,'summary':'','language':'en','topics':[]},p))
        self.assertFalse(matches({'title':'Everyday habits','summary':'','language':'en','topics':[]},p))

    def test_selected_topics_are_not_crowded_out_by_newer_same_topic_articles(self):
        a={'id':'psychology-1','title':'Psychology in society','summary':'psychology',
           'source':'A','language':'en','topics':['心理','社会学'],'category':'recent','published_at':'2026-10-17'}
        b={**a,'id':'psychology-2','source':'B'}
        technology={**a,'id':'technology','title':'New space science','summary':'technology',
                    'source':'C','topics':['科技'],'published_at':'2026-10-16'}
        p={**DEFAULT,'mode':'recent','count':2,'topics':['心理','科技','社会学']}
        result=choose([a,b,technology],p,set(),'2026-10-17')
        self.assertIn('technology',[row['id'] for row in result])
        self.assertEqual(set().union(*(set(row['topics']) for row in result)),set(p['topics']))

    def test_atom_rss_and_unsafe_xml(self):
        src=FEEDS[0]
        raw=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Thinking</title><link href="https://aeon.co/essays/x?utm_source=a"/><published>2026-10-14T00:00:00Z</published><summary>&lt;script&gt;x&lt;/script&gt; Good evidence.</summary></entry></feed>'
        a=parse_feed(raw,src)[0];self.assertEqual(a['url'],'https://aeon.co/essays/x');self.assertEqual(a['summary'],'Good evidence.')
        for bad in [b'<!DOCTYPE feed><feed/>',b'<!ENTITY x "y"><feed/>']:
            with self.assertRaises(ValueError):parse_feed(bad,src)
        for url in ['https://127.0.0.1/x','file:///etc/passwd','https://aeon.co@127.0.0.1/x','https://aeon.co:999/x','javascript:alert(1)']:
            self.assertIsNone(canonical(url,src['domains']))
    def test_selection_date_dedup_and_no_repeat(self):
        a={'id':'a','title':'Thinking and society','summary':'psychology and learning','source':'A','language':'en','topics':['认知'],'category':'recent','published_at':'2026-10-14'}
        b={**a,'id':'b','published_at':None};c={**a,'id':'c','published_at':'2025-10-14'};d={**a,'id':'d','published_at':'2027-10-14'}
        result=choose([a,a,b,c,d],{**DEFAULT,'mode':'recent'},set(),'2026-10-14');self.assertEqual([x['id'] for x in result],['a'])
        self.assertEqual(choose([a],DEFAULT,{'a'},'2026-10-14'),[])
        self.assertEqual(choose([a],{**DEFAULT,'languages':['zh']},set(),'2026-10-14'),[])

class ReadingTests(AsyncCloudFixture):
    async def asyncSetUp(self):
        self.s=self.new_reading();self.s.initialize()
    async def collect(self):
        r=Reader(self.s);j=r.begin({'key':'test','preferences':{**DEFAULT,'mode':'classic'}});await asyncio.gather(*list(r.tasks.values()));return self.s.record(j['id'])
    async def test_local_save_note_and_idempotency(self):
        j=await self.collect();self.assertEqual(j['state'],'ready');ids=[a['id'] for a in j['candidates']]
        saved=self.s.save_selection(j['id'],ids);self.assertEqual(saved,self.s.save_selection(j['id'],ids));self.assertFalse(self.runtime.exists())
        aid=ids[0];self.assertFalse(self.s.article(aid)['read']);self.s.update_personal(aid,{'note':'个人笔记','note_hash':None,'bookmarked':True})
        with self.assertRaises(Problem):self.s.update_personal(aid,{'note':'冲突','note_hash':None})
        self.assertEqual(self.s.note(aid)['text'],'个人笔记');self.assertTrue(self.s.article(aid)['bookmarked']);self.assertFalse(self.s.article(aid)['read'])
        with self.assertRaises(Problem) as error:snapshot(self.s)
        self.assertEqual(error.exception.code,'remote_backup')
        self.assertFalse(any('/阅读笔记/' in p for p in self.repo.commits[self.repo.head]['files']))
    async def test_external_guide_not_overwritten(self):
        j=await self.collect();aid=j['candidates'][0]['id'];self.s.save_selection(j['id'],[aid]);a=self.s.article(aid);rel=f'认知阅读/文章资料/{aid}/中文导读.md';self.external(rel,'外部修改')
        with self.assertRaises(Problem):self.s.save_guide(aid,'新导读',a['hashes'][rel])
        self.assertEqual(self.module_content.read_text(rel,self.repo.head),'外部修改')
        self.assertEqual(self.s.path(rel).read_text(),a['guide'])
    async def test_daily_once_pause_restart(self):
        r=Reader(self.s);self.s.save_preferences({**DEFAULT,'mode':'classic'})
        dt=datetime.fromisoformat(now()).replace(hour=23);j=r.daily_tick(dt);self.assertIsNotNone(j);await asyncio.gather(*list(r.tasks.values()))
        self.assertIsNone(r.daily_tick(dt));self.assertTrue(self.s.record(j['id'])['saved_ids'])
        self.s.initialize();self.assertIsNone(r.daily_tick(dt));self.s.save_preferences({**DEFAULT,'enabled':False});self.assertIsNone(r.daily_tick(dt))
    async def test_cancel_and_no_model_on_reads(self):
        async def hanging(source):await asyncio.sleep(.1);return []
        r=Reader(self.s,fetcher=hanging);j=r.begin({'key':'cancel','preferences':DEFAULT});r.cancel(j['id']);await r.shutdown();self.assertEqual(self.s.record(j['id'])['state'],'cancelled')
        self.s.record(j['id']);self.assertEqual(len(r.tasks),0)
    async def test_explicit_guide_excludes_notes_and_needs_done(self):
        j=await self.collect();aid=j['candidates'][0]['id'];self.s.save_selection(j['id'],[aid]);self.s.update_personal(aid,{'note':'SECRET NOTE','note_hash':None});old=self.s.article(aid)['guide'];calls=[]
        async def truncated(messages,config):calls.append(messages);yield {'text':'没有结束信号'}
        r=Reader(self.s,transport=truncated);a=r.begin({'key':'guide','kind':'guide','article_id':aid});await asyncio.gather(*list(r.tasks.values()));self.assertEqual(self.s.record(a['id'])['state'],'failed');self.assertEqual(self.s.article(aid)['guide'],old);self.assertNotIn('SECRET NOTE',str(calls))
        async def complete(messages,config):yield {'text':'核心观点：先审视证据。边界：只读过摘要。思考：还有什么解释？'};yield {'done':True}
        r=Reader(self.s,transport=complete);a=r.begin({'key':'good','kind':'guide','article_id':aid});await asyncio.gather(*list(r.tasks.values()));self.assertEqual(self.s.record(a['id'])['state'],'ready');self.assertIn('核心观点：先审视证据',self.s.article(aid)['guide']);self.assertFalse(self.s.article(aid)['read'])

    async def test_export_recovery_and_no_overwrite(self):
        j=await self.collect();ids=[j['candidates'][0]['id']]
        self.repo.fail_update=True
        with self.assertRaises(Problem):self.s.save_selection(j['id'],ids)
        self.assertIsNone(self.s.optional(ids[0]))
        self.repo.fail_update=False
        self.s.initialize();self.assertIsNotNone(self.s.optional(ids[0]));self.assertEqual(self.s.record(j['id'])['saved_ids'],ids)

    async def test_api_authorization_and_personal_lifecycle(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from copilot.api import register as legacy
        from reading.api import register
        app=FastAPI();legacy(app,self.s.root,self.s.db);store,service=register(app,self.s.root,self.s.db)
        j=await self.collect();aid=j['candidates'][0]['id']
        with TestClient(app,base_url='http://localhost') as client:
            headers={'X-Copilot-Request':'1'}
            self.assertEqual(client.get('/api/reading').status_code,200)
            self.assertEqual(client.post('/api/reading/preferences',json={'data':DEFAULT}).status_code,403)
            self.assertEqual(client.post('/api/reading/preferences',json={'data':DEFAULT},headers={**headers,'Origin':'https://outside.example'}).status_code,403)
            response=client.post('/api/reading/jobs/'+j['id']+'/save',json={'data':{'ids':[aid]}},headers=headers);self.assertEqual(response.status_code,200,response.text)
            response=client.post('/api/reading/articles/'+aid+'/personal',json={'data':{'read':True,'note':'本人笔记','note_hash':None}},headers=headers);self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(client.get('/api/reading/articles/'+aid).json()['note']['text'],'本人笔记')
