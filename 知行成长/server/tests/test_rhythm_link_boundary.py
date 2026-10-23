from unittest.mock import patch
import action_plans as actions
from test_rhythm_focus import RhythmFixture


class RhythmLinkTests(RhythmFixture):
    def test_nonlocal_new_endpoints_fail_before_reading_old_data(self):
        self.enable()
        for phase in ('pending','active','unknown'):
            with actions.connection(True,allow_link=True) as c:
                c.execute('INSERT INTO action_link_state VALUES (1,?,NULL) ON CONFLICT(id) DO UPDATE SET data=EXCLUDED.data', (actions.encoded({'phase':phase}),))
            with patch('rhythm.service.preferences',side_effect=AssertionError('old local data read')):
                cap=self.client.get('/api/action-plans/rhythm/capabilities').json()
                self.assertEqual(cap['reason'],'CONTRACT_UPGRADE_REQUIRED')
                for path in ('/today','/export','/trial','/weeks/2026-10-19','/executions/foreign'):
                    self.assertEqual(self.client.get('/api/action-plans/rhythm'+path).status_code,409)
                for path in ('/enrollment','/survey','/events','/reminder-claim','/executions/foreign/recap'):
                    self.assertEqual(self.post(path).status_code,409)

    def test_disable_preserves_read_export_and_existing_facts(self):
        self.enable();p=self.create(completion_mode='check');self.select(p);r=self.op(p,'complete').json()['execution']
        self.post('/preferences',expected_revision=1,enabled=False)
        exported=self.client.get('/api/action-plans/rhythm/export').json()
        self.assertEqual(exported['executions'][0]['id'],r['id'])
        self.assertEqual(self.post('/executions/'+r['id']+'/recap',expected_recap_revision=0,note='off').json()['code'],'FEATURE_DISABLED')
        self.assertEqual(self.post('/focus',expected_revision=1,date='2026-10-21',plan_id=p['id']).json()['code'],'FEATURE_DISABLED')
