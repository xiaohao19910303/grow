"""R06 success events are atomic, deduplicated and contain no prose."""
import json
from unittest.mock import patch
import db
from test_rhythm_focus import RhythmFixture


class RhythmEventTests(RhythmFixture):
    def events(self):
        with db.connect() as c:
            return [(r[0], json.loads(r[1])) for r in c.execute('SELECT event_name,data FROM action_rhythm_events')]

    def test_success_and_replay_do_not_duplicate_and_never_include_prose(self):
        self.enable(); plan = self.create(); focus = self.select(plan).json()['focus']
        self.assertIn('focus_selected', [n for n, _ in self.events()])
        start = self.op(plan, 'start').json()
        fields = dict(execution_id=start['execution']['id'], actual_minutes=1, note='secret prose', next_step='secret next')
        self.op(start['plan'], 'finish', key='events-finish-replay', **fields)
        self.op(start['plan'], 'finish', key='events-finish-replay', **fields)
        events = self.events(); names = [n for n, _ in events]
        for name in ('execution_started', 'activity_confirmed', 'recap_saved'):
            self.assertEqual(names.count(name), 1)
        self.assertNotIn('secret', json.dumps(events))

    def test_business_rollback_removes_event_and_receipt(self):
        self.enable(); plan = self.create()
        with patch('action_plans.write', side_effect=RuntimeError('rollback')):
            with self.assertRaises(RuntimeError):
                self.op(plan, 'start', key='atomic-start-key')
        self.assertNotIn('execution_started', [n for n, _ in self.events()])
        self.assertFalse(self.client.get('/api/action-plans/requests/atomic-start-key').json()['found'])

    def test_ui_whitelist_and_limit_and_event_id_replay(self):
        self.enable()
        event = dict(event_id='ui-event-0001', event_name='form_finished', source='today', session_id='session-1',
                     form_kind='focus', result='cancel', active_duration_ms=123)
        self.assertEqual(self.post('/events', events=[event]).status_code, 200)
        self.assertEqual(self.post('/events', events=[event]).status_code, 200)
        self.assertEqual([n for n, _ in self.events()].count('form_finished'), 1)
        for changes in ({'note': 'never collect'}, {'event_name': 'activity_confirmed'}, {'active_duration_ms': -1}):
            self.assertEqual(self.post('/events', events=[event | changes]).status_code, 422)
        self.assertEqual(self.post('/events', events=[event] * 21).status_code, 422)

    def test_supplement_does_not_backfill_disabled_activity_event(self):
        plan = self.create(completion_mode='check')
        record = self.op(plan, 'complete').json()['execution']
        self.enable()
        self.assertEqual(self.post('/executions/'+record['id']+'/recap', expected_recap_revision=0, note='后补').status_code, 200)
        self.assertEqual([name for name, _ in self.events()], ['recap_saved'])
