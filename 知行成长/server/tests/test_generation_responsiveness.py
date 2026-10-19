"""Buffered model streams must leave the server responsive and bound DB writes."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from plans.generation import PlanGenerator
from plans.github import GitHubContent
from test_github_plans import B, D
from cloud_fixtures import AsyncCloudFixture


class GenerationResponsivenessTests(AsyncCloudFixture):
    async def asyncSetUp(self):self.store=self.s

    async def test_buffered_stream_yields_and_limits_progress_writes(self):
        observed = []
        raw = json.dumps(D)

        async def model(messages, config):
            for i, char in enumerate(raw):
                if i == 5:
                    asyncio.get_running_loop().call_soon(
                        lambda: observed.append(self.store.get('learning_ai_attempts', 'buffered')['state']))
                yield {'text': char}
            yield {'done': True}

        generator = PlanGenerator(self.store, model)
        with patch.object(generator, 'persist', wraps=generator.persist) as writes:
            generator.begin({'key': 'buffered', 'kind': 'plan', 'brief': B})
            await asyncio.gather(*list(generator.tasks.values()))
        result = self.store.get('learning_ai_attempts', 'buffered')
        self.assertEqual(observed, ['generating'])
        self.assertEqual(result['state'], 'ready', result.get('error'))
        self.assertEqual(result['raw'], raw)
        self.assertLess(writes.call_count, 10)
        self.assertEqual(self.store.read_draft(result['draft_id'])['document']['lessons'], D['lessons'])

    async def test_buffered_stream_can_be_cancelled_before_completion(self):
        produced = []

        async def model(messages, config):
            for i in range(100):
                if i == 5:
                    asyncio.get_running_loop().call_soon(generator.cancel, 'cancel-buffered')
                produced.append(i)
                yield {'text': 'x'}
            yield {'done': True}

        generator = PlanGenerator(self.store, model)
        generator.begin({'key': 'cancel-buffered', 'kind': 'plan', 'brief': B})
        await asyncio.gather(*list(generator.tasks.values()))
        result = self.store.get('learning_ai_attempts', 'cancel-buffered')
        self.assertEqual(result['state'], 'cancelled')
        self.assertLess(len(produced), 100)
        self.assertIsNone(result['draft_id'])


if __name__ == '__main__':
    unittest.main()
