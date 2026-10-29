"""Real web/native/Zook protocol with disposable PostgreSQL and synthetic lessons."""
from unittest.mock import patch
import action_link
import httpx
import action_plans as actions
import mobile_library
import study_materials
import test_mobile_execution_http as fixture


class LearningPracticeHTTPTests(fixture.MobileExecutionHTTPTests):
    def prepare_practice(self):
        study_materials.initialize()
        folder = self.root / '英文阅读' / '每日文章'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'Day001.md').write_text('# Day001\n\nApply one idea to a real report.')
        materials = study_materials.Materials(self.root)
        mobile_library.register(self.app, self.s, materials)
        ticket = self.native('POST', 'action-link-tickets', {})
        preview = self.web('action-link/preview', {'code': ticket['code']})
        self.web('action-link/confirm', {'code': ticket['code'], 'preview_id': preview['preview_id'], 'consent': True})
        self.web('mobile-learning/consent', {'enabled': True, 'consent': True})
        mobile_library.sync(self.s, materials)
        return materials, self.native('GET', 'learning-library')['lessons'][0]

    def test_practice_roundtrip_response_loss_feedback_and_source_withdrawal(self):
        materials, lesson = self.prepare_practice()
        source = self.client.get('/api/learning-practices/source', params={'module_id': 'yingyu', 'filename': 'Day001.md'})
        self.assertEqual(source.status_code, 200, source.text)
        self.assertEqual(source.headers['cache-control'], 'no-store')
        self.assertEqual(source.json()['source']['id'], lesson['id'])
        payload = {'key': 'web-practice-create-1', 'title': 'Rewrite a real report', 'source_kind': 'lesson',
                   'source_id': lesson['id'], 'source_version': lesson['content_version'], 'date': None, 'timezone': 'UTC'}
        send = action_link.call
        def lost_response(source, message):
            value = send(source, message)
            if message.get('method') == 'POST' and message.get('path') == '/practices':
                actions.fail(503, 'Synthetic response lost after target commit')
            return value
        with patch('action_link.call', side_effect=lost_response):
            lost = self.client.post('/api/action-plans/practices', json=payload, headers=self.headers)
        self.assertEqual(lost.status_code, 503)
        result = self.web('action-plans/practices', payload)
        p = result['plan']
        self.assertEqual(p['completion_mode'], 'check')
        self.assertIsNone(p['start_date'])
        self.assertEqual(self.web('action-plans/practices', payload), result)
        self.assertEqual(len(self.native('GET', 'action-plans/practices')['practices']), 1)
        self.assertEqual(self.native('GET', 'action-plans/records')['total'], 0)
        self.assertEqual(self.native('GET', 'action-plans/practices/' + p['id'] + '/source')['text'], self.native('GET', 'learning-library/' + lesson['id'])['lesson']['content'])

        body = {'key': 'native-practice-feedback-1', 'revision': p['revision'], 'action': 'practice-feedback',
                'feedback': {'outcome': 'unknown', 'result': 'Tried in a real meeting', 'evidence': 'Awaiting colleague response', 'next_step': 'Ask tomorrow'}}
        p = self.native('POST', 'action-plans/' + p['id'] + '/operations', body)['plan']
        web = self.client.get('/api/action-plans/practices')
        self.assertEqual(web.status_code, 200, web.text)
        self.assertEqual(web.json()['practices'][0]['practice_feedback'][0]['result'], body['feedback']['result'])
        self.assertEqual(self.native('GET', 'action-plans/records')['total'], 0)
        self.assertEqual(p['status'], 'active')
        stale = self.client.post('/api/action-plans/' + p['id'] + '/operations', json={**body, 'key': 'web-stale-feedback'}, headers=self.headers)
        self.assertEqual(stale.status_code, 409)
        foreign = httpx.get(self.url + '/api/v1/lighttick/action-plans/practices/' + p['id'] + '/source', headers={'Authorization': 'Bearer ' + self.owners[1]['token'], 'X-App-Id': 'lighttick'})
        self.assertEqual(foreign.status_code, 404)

        # A source revocation does not erase a committed request receipt or fabricate another action.
        mobile_library.consent(False)
        mobile_library.sync(self.s, materials)
        self.assertFalse(self.native('GET', 'action-plans/practices/' + p['id'] + '/source')['available'])
        self.assertEqual(self.web('action-plans/practices', payload), result)
        self.assertEqual(len(self.native('GET', 'action-plans/practices')['practices']), 1)

    def test_source_ui_keeps_reading_only_connection_out_of_action_authority(self):
        study_materials.initialize()
        folder = self.root / '英文阅读' / '每日文章'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'Day001.md').write_text('# Day001\n\nRead without adopting actions.')
        materials = study_materials.Materials(self.root)
        mobile_library.register(self.app, self.s, materials)
        ticket = self.native('POST', 'action-link-tickets', {})
        preview = self.web('mobile-learning/preview', {'code': ticket['code']})
        self.web('mobile-learning/connect', {'code': ticket['code'], 'preview_id': preview['preview_id'], 'consent': True})
        mobile_library.sync(self.s, materials)
        source = self.client.get('/api/learning-practices/source', params={'module_id': 'yingyu', 'filename': 'Day001.md'}).json()
        self.assertFalse(source['available'])
        self.assertEqual(len(self.native('GET', 'learning-library')['lessons']), 1)
        self.assertEqual(self.native('GET', 'action-plans/practices')['practices'], [])
