"""Settings and provider connectivity work even when legacy storage cannot boot."""
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

OWN={'api_base_url':'https://ark.example/api/plan/v3','api_key':'PRIVATE_TEST_KEY','model_name':'model-a'}

class IndependentAI(unittest.TestCase):
    def test_standalone_connection_uses_selected_model_and_requires_complete_response(self):
        from copilot.ai_api import register
        app=FastAPI();register(app)
        calls=[]
        async def complete(messages,cfg):
            calls.append(cfg.copy());yield {'text':'连接成功'};yield {'done':True}
        with TestClient(app) as client,patch('copilot.transport.qwen_stream',complete):
            self.assertEqual(client.get('/api/ai/settings').json(),{'storage':'browser','requires_own_config':True})
            for model in ('model-a','model-b'):
                response=client.post('/api/ai/test',json={**OWN,'model_name':model},headers={'X-Copilot-Request':'1'})
                self.assertEqual(response.status_code,200,response.text)
                self.assertTrue(response.json()['ok'])
                self.assertEqual(calls[-1]['model'],model)
                self.assertEqual(calls[-1]['url'],OWN['api_base_url']+'/chat/completions')
                self.assertNotIn(OWN['api_key'],response.text)
            self.assertEqual(client.post('/api/ai/test',json=OWN).status_code,403)
        async def truncated(messages,cfg):yield {'text':'partial'}
        with TestClient(app) as client,patch('copilot.transport.qwen_stream',truncated):
            self.assertFalse(client.post('/api/ai/test',json=OWN,headers={'X-Copilot-Request':'1'}).json()['ok'])

    def test_pending_legacy_file_restore_does_not_block_ai_settings(self):
        import tempfile
        from pathlib import Path
        from copilot.api import register
        from copilot.core import Problem
        with tempfile.TemporaryDirectory() as tmp:
            app=FastAPI();store=register(app,tmp,Path(tmp)/'runtime')
            store.startup_error=Problem('legacy_storage','not ready',503)
            store.runtime.mkdir(parents=True);(store.runtime/'restore-pending.json').write_text('{}')
            async def complete(messages,cfg):yield {'text':'连接成功'};yield {'done':True}
            with TestClient(app,base_url='http://localhost') as client,patch('copilot.transport.qwen_stream',complete):
                self.assertEqual(client.get('/api/ai/settings').status_code,200)
                self.assertEqual(client.get('/api/copilot/settings').status_code,200)
                self.assertTrue(client.post('/api/ai/test',json=OWN,headers={'X-Copilot-Request':'1'}).json()['ok'])
