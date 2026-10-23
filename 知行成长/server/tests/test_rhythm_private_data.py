"""New summary/export/trial endpoints use the real authenticated tenant context."""
import unittest
import test_rhythm_accounts as fixture


class RhythmPrivateDataTests(unittest.TestCase):
    setUp=fixture.RhythmAccountTests.setUp
    cleanup_database=fixture.RhythmAccountTests.cleanup_database
    register=fixture.RhythmAccountTests.register
    invite=fixture.RhythmAccountTests.invite
    login=fixture.RhythmAccountTests.login
    enable=fixture.RhythmAccountTests.enable

    def test_summary_event_export_and_enrollment_do_not_cross_accounts(self):
        self.register('rhythm-private-alice');self.enable()
        def post(path,body):
            r=self.client.post('/api/action-plans'+path,headers=self.headers,json=body)
            self.assertEqual(r.status_code,200,r.text);return r.json()
        p=post('',dict(key='private-check-task',title='PRIVATE ALICE BODY',period='day',completion_mode='check',start_date='2026-10-21',end_date='2026-10-21'))['plans'][0]
        r=post('/'+p['id']+'/operations',dict(key='private-check-complete',revision=p['revision'],action='complete'))['execution']
        post('/rhythm/executions/'+r['id']+'/recap',dict(key='private-recap-save',expected_recap_revision=0,note='PRIVATE SUMMARY'))
        post('/rhythm/enrollment',dict(key='private-enrollment',experiment_key='private-trial'))
        self.register('rhythm-private-bob');self.enable()
        exported=self.client.get('/api/action-plans/rhythm/export?include_events=true')
        self.assertNotIn('PRIVATE',exported.text)
        self.assertEqual(exported.json()['enrollments'],[])
        self.assertEqual(exported.json()['executions'],[])
        self.assertEqual(self.client.get('/api/action-plans/rhythm/executions/'+r['id']).status_code,404)
        attempt=self.client.post('/api/action-plans/rhythm/executions/'+r['id']+'/recap',headers=self.headers,json=dict(key='foreign-recap-write',expected_recap_revision=1,note='other'))
        self.assertEqual(attempt.status_code,404)
