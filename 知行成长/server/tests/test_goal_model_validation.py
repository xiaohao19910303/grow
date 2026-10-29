"""Model output is inert structured data, not executable instructions."""
import asyncio
import json
import unittest
from unittest.mock import patch
import goal_planning as planning


class GoalModelValidation(unittest.TestCase):
    snapshot={'today':'2026-10-27','days':7}

    def generate(self,items):
        async def stream(_messages,_cfg):yield {'text':json.dumps({'items':items},ensure_ascii=False)}
        with patch('copilot.transport.qwen_stream',side_effect=stream),patch('ai_evidence.capture',return_value={'id':'validation-fixture'}),patch('ai_evidence.messages',return_value=planning.proposal_messages(self.snapshot)):
            return asyncio.run(planning.generate_items(self.snapshot,{}))

    def test_output_whitelist_never_imports_commands_credentials_or_completions(self):
        items=self.generate([{'ref':'a','title':'写一个论点','entity_type':'action','period':'day','completion_mode':'made-up','status':'completed','target':{'kind':'article','course':'invented'},'command':'delete data','ai_config':{'api_key':'PRIVATE'}}])
        self.assertEqual(items[0]['entity_type'],'action')
        for field in ('completion_mode','status','target','command','ai_config'):self.assertNotIn(field,items[0])

    def test_output_limit_dates_and_cycles(self):
        invalid=[[],[{'ref':str(i),'title':'任务'} for i in range(31)],
                 [{'ref':'a','title':'任务','start_date':'2027-01-01'}],
                 [{'ref':'a','title':'任务','parent_ref':'a'}],
                 [{'ref':'a','title':'任务'},{'ref':'a','title':'重复'}]]
        for items in invalid:
            with self.subTest(items=items),self.assertRaises(Exception):self.generate(items)
