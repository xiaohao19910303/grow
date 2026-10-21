"""Actual FastAPI + disposable PostgreSQL + counted model, across HTTP reconnects."""
import asyncio
from unittest.mock import patch
import httpx

from test_legacy_cloud_api import CloudHTTPFixture, COURSE
from test_legacy_cloud_content import OWN

class BackgroundHTTPTests(CloudHTTPFixture):
    def test_course_survives_http_client_replacement(self):
        async def run():
            release=asyncio.Event();first=asyncio.Event();calls=[]
            async def model(messages,cfg):
                calls.append(cfg['key']);yield {'text':COURSE[:100]};first.set();await release.wait()
                yield {'text':COURSE[100:]+'\n<!-- COPILOT_SOURCES -->\n摘要 [来源](https://example.org/source)'};yield {'done':True}
            transport=httpx.ASGITransport(self.app,client=('127.0.0.1',1234));headers={'X-Copilot-Request':'1','Accept':'application/json'}
            with patch('copilot.transport.qwen_stream',model):
                async with httpx.AsyncClient(transport=transport,base_url='http://localhost') as client:
                    response=await client.post('/api/copilot/generations',json={'lesson_no':3,'key':'durable-course','ai_config':OWN},headers=headers)
                    self.assertEqual(response.status_code,202,response.text);id=response.json()['id'];await first.wait()
                async with httpx.AsyncClient(transport=transport,base_url='http://localhost') as refreshed:
                    progress=await refreshed.get('/api/copilot/drafts/'+id)
                    self.assertEqual(progress.json()['status'],'generating');self.assertTrue(progress.json()['raw'])
                    replay=await refreshed.post('/api/copilot/generations',json={'lesson_no':3,'key':'durable-course','ai_config':OWN},headers=headers)
                    self.assertEqual(replay.json()['id'],id);self.assertEqual(len(calls),1)
                    release.set()
                    for _ in range(150):
                        final=(await refreshed.get('/api/copilot/drafts/'+id)).json()
                        if final['status']!='generating':break
                        await asyncio.sleep(.01)
                    self.assertEqual(final['status'],'ready',final.get('errors'));self.assertEqual(len(calls),1)
        asyncio.run(run())

    def test_summary_reconnect_alias_replay_and_atomic_result(self):
        lesson=self.course.lesson(1);self.course.learning(1,'completed',lesson['version'],'complete-for-summary')
        async def run():
            release=asyncio.Event();first=asyncio.Event();calls=[]
            async def model(messages,cfg):
                calls.append(cfg['key']);yield {'text':'已生成的第一段'};first.set();await release.wait();yield {'text':'\n完整总结'};yield {'done':True}
            transport=httpx.ASGITransport(self.app,client=('127.0.0.1',1234));headers={'X-Copilot-Request':'1','Accept':'application/json'}
            head=self.repository.head
            with patch('copilot.transport.qwen_stream',model):
                async with httpx.AsyncClient(transport=transport,base_url='http://localhost') as client:
                    response=await client.post('/api/copilot/summaries/generate',json={'key':'durable-summary','ai_config':OWN},headers=headers)
                    self.assertEqual(response.status_code,202,response.text);id=response.json()['id'];await first.wait()
                async with httpx.AsyncClient(transport=transport,base_url='http://localhost') as refreshed:
                    progress=(await refreshed.get('/api/copilot/background-jobs/'+id)).json()
                    self.assertEqual(progress['raw'],'已生成的第一段');self.assertNotIn(OWN['api_key'],str(progress))
                    listing=(await refreshed.get('/api/copilot/background-jobs')).json()['items']
                    self.assertEqual(listing[0]['id'],id);self.assertNotIn('raw',listing[0])
                    replay=await refreshed.post('/api/copilot/summaries/generate',json={'key':'another-tab-key','ai_config':OWN},headers=headers)
                    self.assertEqual(replay.json()['id'],id)
                    release.set()
                    for _ in range(150):
                        final=(await refreshed.get('/api/copilot/background-jobs/'+id)).json()
                        if final['state'] not in ('queued','generating'):break
                        await asyncio.sleep(.01)
                    self.assertEqual(final['state'],'ready',final)
                    result=await refreshed.get('/api/copilot/summaries/'+str(final['result_id']))
                    self.assertEqual(result.json()['content'],'已生成的第一段\n完整总结')
                    again=await refreshed.post('/api/copilot/summaries/generate',json={'key':'another-tab-key','ai_config':OWN},headers=headers)
                    self.assertEqual(again.json()['id'],id);self.assertEqual(len(calls),1)
                    self.assertEqual(self.repository.head,head,'private feedback-derived summaries must stay in the account database')
        asyncio.run(run())
    def test_advanced_course_reconnect_opens_the_same_persisted_draft(self):
        async def run():
            release=asyncio.Event();first=asyncio.Event();calls=[]
            async def model(messages,cfg):
                calls.append(cfg['key']);yield {'text':'## 进阶课程\n第一部分'};first.set();await release.wait();yield {'text':'\n完整草稿'};yield {'done':True}
            transport=httpx.ASGITransport(self.app,client=('127.0.0.1',1234));headers={'X-Copilot-Request':'1','Accept':'application/json'}
            with patch('copilot.transport.qwen_stream',model):
                async with httpx.AsyncClient(transport=transport,base_url='http://localhost') as client:
                    self.assertEqual((await client.get('/api/copilot/background-jobs')).status_code,200)
                    lesson=self.course.lesson(1);self.course.quick_complete(1,0,lesson['version'],'advanced-completion')
                    self.course.save_feedback(1,{'mastery_level':'partially_understood','value_rating':2,'feeling_tags':[],'key_learnings':'练习','questions':'','next_direction':'迁移'},'advanced-feedback')
                    body={'key':'durable-advanced','summary_content':'已有总结','ai_config':OWN}
                    response=await client.post('/api/copilot/summaries/generate-advanced',json=body,headers=headers)
                    self.assertEqual(response.status_code,202,response.text);id=response.json()['id'];await first.wait()
                async with httpx.AsyncClient(transport=transport,base_url='http://localhost') as refreshed:
                    self.assertTrue((await refreshed.get('/api/copilot/background-jobs/'+id)).json()['raw'])
                    self.assertEqual((await refreshed.post('/api/copilot/summaries/generate-advanced',json=body,headers=headers)).json()['id'],id)
                    release.set()
                    for _ in range(150):
                        final=(await refreshed.get('/api/copilot/background-jobs/'+id)).json()
                        if final['state'] not in ('queued','generating'):break
                        await asyncio.sleep(.01)
                    self.assertEqual(final['state'],'ready',final)
                    draft=(await refreshed.get('/api/copilot/drafts/'+final['draft_id'])).json()
                    self.assertEqual(draft['content'],'## 进阶课程\n第一部分\n完整草稿');self.assertEqual(len(calls),1)
        asyncio.run(run())
