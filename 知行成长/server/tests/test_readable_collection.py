"""Only fetched, readable bodies may become new reading recommendations."""
import asyncio
import copy
from unittest.mock import patch
from cloud_fixtures import AsyncCloudFixture
from copilot.core import Problem, now
from reading.sources import identify, choose, DEFAULT_FEEDS
from reading.store import DEFAULT, TABLE
from reading.service import Reader

BODY='## Evidence and decisions\n\n'+('A reader considers the full argument, compares evidence and checks the limits before drawing a conclusion.\n\n'*12)

class ReadableCollectionTests(AsyncCloudFixture):
    async def asyncSetUp(self):
        self.store=self.new_reading();self.store.initialize()
        self.rows=[]
        for i in range(12):
            url=f'https://example.org/reading/{i}'
            self.rows.append({'id':identify(url),'title':f'Thinking with evidence {i}','url':url,'source':f'Source {i%3}',
                              'author':'A writer','language':'en','published_at':now()[:10],'category':'recent','topics':['认知'],
                              'summary':'Source summary. '*10,'access':'RSS only'})
        self.p={**DEFAULT,'mode':'recent','count':3,'topics':['认知'],'languages':['en']}
        self.source=patch.object(self.store,'all_sources',return_value=[DEFAULT_FEEDS[0]]);self.source.start();self.addCleanup(self.source.stop)

    async def run_collection(self,key,fetch,preferences=None,daily=False):
        async def feed(source):return copy.deepcopy(self.rows)
        service=Reader(self.store,fetcher=feed)
        with patch('reading.service.fetch_article_content',side_effect=fetch):
            job=service.begin({'key':key,'preferences':preferences or self.p},daily=daily)
            await asyncio.gather(*list(service.tasks.values()))
        return self.store.record(job['id'])

    async def test_failed_initial_choices_are_replaced_and_bodies_survive_save_and_restart(self):
        first=choose(self.rows,self.p,set(),now()[:10],seed='job-replace')
        bad={first[0]['url'],first[1]['url']};calls=[]
        async def fetch(url):calls.append(url);return None if url in bad else BODY+url
        job=await self.run_collection('replace',fetch)
        self.assertEqual(job['state'],'ready',job.get('error'));self.assertEqual(len(job['candidates']),3)
        self.assertTrue(all(a['url'] not in bad for a in job['candidates']))
        self.assertTrue(all(a.get('content_version')==2 and a['full_content'].startswith('## Evidence') for a in job['candidates']))
        self.assertEqual(len(calls),len(set(calls)));self.assertGreater(len(calls),3)
        ids=[a['id'] for a in job['candidates']];self.store.initialize()
        saved=self.store.save_selection(job['id'],ids);commits=len(self.repo.commits)
        self.assertEqual(self.store.save_selection(job['id'],ids),saved);self.assertEqual(len(self.repo.commits),commits)
        for aid in ids:
            self.assertIn('Evidence and decisions',self.module_content.read_text(f'认知阅读/文章资料/{aid}/原文.md',self.repo.head))
            self.assertFalse(self.store.article(aid)['read'])
        self.store.initialize();self.assertEqual({a['id'] for a in self.store.articles()},set(ids))

    async def test_all_unreadable_fail_without_recommending_or_saving_abstracts(self):
        async def fetch(url):return 'short teaser'
        job=await self.run_collection('no-bodies',fetch,daily=True)
        self.assertEqual(job['state'],'failed');self.assertFalse(job['candidates'])
        self.assertIn('正文',job['error']);self.assertFalse(self.store.articles())
        self.assertFalse(job.get('saved_ids'))

    async def test_shortage_returns_only_readable_articles_and_warns(self):
        good={r['url'] for r in self.rows[:2]}
        async def fetch(url):return BODY if url in good else None
        job=await self.run_collection('shortage',fetch,daily=True)
        self.assertEqual(job['state'],'ready',job.get('error'));self.assertEqual(len(job['candidates']),2)
        self.assertEqual(len(job['saved_ids']),2);self.assertTrue(any('2' in w and '正文' in w for w in job['warnings']))
        self.assertEqual(len(self.store.articles()),2)

    async def test_save_guard_rejects_an_unreadable_candidate_without_partial_publication(self):
        async def fetch(url):return BODY
        job=await self.run_collection('guard',fetch);job['candidates'][1]['full_content']=None
        self.store.put(TABLE,job['id'],job);commits=len(self.repo.commits)
        with self.assertRaises(Problem):self.store.save_selection(job['id'],[a['id'] for a in job['candidates']])
        self.assertFalse(self.store.articles());self.assertEqual(len(self.repo.commits),commits)

    async def test_failed_candidates_never_expose_cached_or_binary_bodies(self):
        for row in self.rows:row['full_content']='%PDF-LEGACY '+('cached garbage '*20)
        async def fetch(url):return None
        job=await self.run_collection('cached',fetch)
        self.assertEqual(job['state'],'failed');self.assertEqual(job['candidates'],[])

    async def test_attempt_limit_and_parallelism_are_bounded(self):
        calls=[];active=0;peak=0
        async def fetch(url):
            nonlocal active,peak
            calls.append(url);active+=1;peak=max(peak,active)
            try:await asyncio.sleep(.02);return None
            finally:active-=1
        with patch('reading.service.COLLECTION_BODY_ATTEMPTS',4):
            job=await self.run_collection('bounded',fetch)
        self.assertEqual(job['state'],'failed');self.assertEqual(len(calls),4)
        self.assertEqual(peak,3);self.assertEqual(active,0)

    async def test_replacements_preserve_recent_and_classic_slots(self):
        self.rows=self.rows[:4]
        classics=[{**r,'category':'classic','id':identify(r['url']+'-classic'),'url':r['url']+'-classic'} for r in self.rows[:3]]
        prefs={**self.p,'mode':'mixed'}
        first=choose(self.rows+classics,prefs,set(),now()[:10],seed='job-mixed')
        bad={first[0]['url'],next(a['url'] for a in first if a['category']=='classic')}
        async def fetch(url):return None if url in bad else BODY
        with patch('reading.service.CLASSICS',classics):job=await self.run_collection('mixed',fetch,prefs)
        self.assertEqual(job['state'],'ready',job.get('error'))
        self.assertEqual([a['category'] for a in job['candidates']].count('recent'),2)
        self.assertEqual([a['category'] for a in job['candidates']].count('classic'),1)

    async def test_timeout_does_not_leak_fetches_or_recommend_partial_results(self):
        active=0
        async def fetch(url):
            nonlocal active
            active+=1
            try:await asyncio.sleep(30);return BODY
            finally:active-=1
        with patch('reading.service.COLLECTION_BODY_SECONDS',.08):job=await self.run_collection('deadline',fetch)
        self.assertEqual(job['state'],'failed');self.assertEqual(active,0);self.assertFalse(job['candidates'])
