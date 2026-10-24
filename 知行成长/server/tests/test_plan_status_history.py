"""Status history is installed by normal plan startup and remains private."""
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cloud_fixtures import CloudFixture
from copilot.core import encoded
from plans.api import register
from test_plans import B, D


class PlanStatusHistoryTests(CloudFixture):
    def setUp(self):
        super().setUp()
        draft = self.s.draft({'brief': B, 'document': D})
        self.pid = self.s.adopt(draft['id'], 'status-history-adopt')['plan_id']
        app = FastAPI()
        with patch('plans.api.make_store', return_value=self.s):
            register(app, self.root, self.runtime)
        self.client = TestClient(app, base_url='http://localhost', raise_server_exceptions=False)
        self.addCleanup(self.client.close)

    def history(self):
        response = self.client.get(f'/api/plans/{self.pid}/status-history')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['history']

    def test_fresh_github_plan_can_read_empty_status_history(self):
        self.assertEqual(self.history(), [])
        self.assertEqual(self.s.plan(self.pid)['status'], 'active')

    def test_status_changes_and_private_records_survive_repeated_startup(self):
        feedback = {'state': 'unknown', 'comment': 'PRIVATE LEARNING NOTE', 'date': '2026-10-21'}
        with self.s.conn() as connection:
            connection.execute('INSERT INTO learning_feedback VALUES (?,?,?)',
                               (self.pid, 1, encoded(feedback)))
        transitions = [('pause', 'active', 'paused'), ('resume', 'paused', 'active'),
                       ('archive', 'active', 'archived')]
        for action, before, after in transitions:
            response = self.client.post(f'/api/plans/{self.pid}/{action}',
                json={'data': {'key': 'status-history-' + action, 'reason': 'PRIVATE REASON ' + action}},
                headers={'X-Copilot-Request': '1'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['status'], after)
            self.assertEqual(self.s.plan(self.pid)['status'], after)
            entry = self.history()[0]
            self.assertEqual((entry['from_status'], entry['to_status']), (before, after))
            self.assertEqual(entry['reason'], 'PRIVATE REASON ' + action)
            self.assertTrue(entry['changed_at'])

        expected_history = self.history()
        self.assertEqual(len(expected_history), 3)
        expected_plan = self.s.plan(self.pid)
        head = self.repo.head
        for _ in range(2):
            fresh = self.new_plans()
            fresh.initialize()
            self.assertEqual(fresh.plan(self.pid), expected_plan)
        self.assertEqual(self.history(), expected_history)
        with self.s.conn() as connection:
            saved = connection.execute('SELECT data FROM learning_feedback WHERE plan_id=?',
                                       (self.pid,)).fetchone()[0]
        self.assertEqual(saved, encoded(feedback))
        self.assertEqual(self.repo.head, head)
        public_content = encoded(self.repo.commits[self.repo.head]['files'])
        self.assertNotIn('PRIVATE REASON', public_content)
        self.assertNotIn('PRIVATE LEARNING NOTE', public_content)
