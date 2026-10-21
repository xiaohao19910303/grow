"""Real HTTP routes and disposable PostgreSQL for course archive and summaries."""
from fastapi.testclient import TestClient
from copilot.cloud_store import CloudStore
from test_legacy_cloud_api import CloudHTTPFixture, OWN


class CourseReviewCloudAPITests(CloudHTTPFixture):
    def complete(self):
        lesson = self.course.lesson(1)
        self.course.quick_complete(1, 60, lesson['version'], 'review-test-completion')

    def test_archive_literal_route_and_feedback_survive_unarchive(self):
        self.complete()
        with TestClient(self.app, base_url='http://localhost', raise_server_exceptions=False) as client:
            response = client.get('/api/copilot/lessons/archived')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['items'], [])
            h = {'X-Copilot-Request': '1'}
            response = client.post('/api/copilot/lessons/1/feedback', headers=h, json={
                'key': 'review-test-feedback', 'mastery_level': 'fully_understood',
                'value_rating': 3, 'key_learnings': 'PRIVATE PRESERVED FEEDBACK'})
            self.assertEqual(response.status_code, 200, response.text)
            response = client.post('/api/copilot/lessons/1/archive', headers=h, json={'key': 'review-test-archive'})
            self.assertEqual(response.status_code, 200, response.text)
            items = client.get('/api/copilot/lessons/archived').json()['items']
            self.assertEqual(items[0]['key_learnings'], 'PRIVATE PRESERVED FEEDBACK')
            response = client.post('/api/copilot/lessons/1/unarchive', headers=h, json={'key': 'review-test-unarchive'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(client.get('/api/copilot/lessons/archived').json()['items'], [])
            self.assertEqual(client.get('/api/copilot/lessons/1/feedback').json()['key_learnings'], 'PRIVATE PRESERVED FEEDBACK')
            self.assertEqual(client.get('/api/copilot/lessons/1/learning-record').status_code, 200)

    def test_summary_table_upgrade_preserves_history_and_stays_private(self):
        with self.course.conn() as c:
            # Simulate a schema whose legacy migration ran before review tables existed.
            c.execute('DROP TABLE IF EXISTS copilot_feedback')
            c.execute('DROP TABLE IF EXISTS copilot_summaries')
        self.course.initialize()
        with TestClient(self.app, base_url='http://localhost', raise_server_exceptions=False) as client:
            response = client.get('/api/copilot/summaries')
            self.assertEqual(response.status_code, 200, response.text)
            before = self.repository.ref_updates
            self.course.save_summary('renzhi', 1, 'full_course', 'PRIVATE COURSE SUMMARY', [])
            fresh = CloudStore('/no-materials', '/no-runtime', self.content)
            fresh.initialize()
            items = fresh.list_summaries()
            self.assertEqual(items[0]['content'], 'PRIVATE COURSE SUMMARY')
            response = client.get('/api/copilot/summaries/' + str(items[0]['id']))
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['content'], 'PRIVATE COURSE SUMMARY')
            self.assertEqual(self.repository.ref_updates, before)

    def test_summary_generation_uses_browser_config_and_saves_to_database(self):
        self.complete()
        before = self.repository.ref_updates
        with TestClient(self.app, base_url='http://localhost', raise_server_exceptions=False) as client:
            h = {'X-Copilot-Request': '1'}
            payload = {'module': 'renzhi', 'scope': 'full_course', 'key': 'review-summary-key'}
            self.assertEqual(client.post('/api/copilot/summaries/generate', headers=h, json=payload).status_code, 422)
            response = client.post('/api/copilot/summaries/generate', headers=h, json={**payload, 'ai_config': OWN})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn('event: complete', response.text)
            items = client.get('/api/copilot/summaries').json()['items']
            self.assertEqual(len(items), 1)
            self.assertNotIn(OWN['api_key'], str(items))
            self.assertEqual(self.repository.ref_updates, before)
