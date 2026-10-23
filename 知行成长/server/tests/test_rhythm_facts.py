"""R04: immutable start context, confirmation dates and zero-minute small steps."""
from datetime import datetime, timezone
import json
import uuid
from unittest.mock import patch

import action_plans as actions
import db
from rhythm.contracts import is_effective_activity
from test_rhythm_focus import RhythmFixture


class RhythmFactTests(RhythmFixture):
    def minimum(self, plan, step='只做一小步'):
        focus = self.select(plan).json()['focus']
        result = self.post('/focus/' + focus['id'] + '/mode', expected_revision=focus['revision'],
                           mode='minimum', minimum_step=step)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()['focus']

    def step(self, plan, focus, **updates):
        return self.post('/steps', plan_id=plan['id'], plan_revision=plan['revision'],
                         focus_day_id=focus['id'], minimum_step=focus['minimum_step'], did_act=True, **updates)

    def content(self):
        target = {'kind': 'article', 'course': 'article-rhythm-fact'}
        with db.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS reading_records(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
            c.execute('INSERT INTO reading_records VALUES (?,?)', (target['course'], actions.encoded({'id': target['course']})))
        response = self.client.post('/api/action-plans/schedules', headers=self.headers,
                                    json=dict(title='读文章', target=target, date='2026-10-21', key=str(uuid.uuid4())))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['plan'], target

    def source_event(self, plan, target, snapshot=None):
        event = dict(event_id='source-' + uuid.uuid4().hex, request_key=str(uuid.uuid4()),
                     normalized_target=target, confirmed_at=actions.clock().isoformat(), origin_action_id=plan['id'],
                     planned_date_at_confirmation=plan['start_date'], timezone_at_confirmation=plan['timezone'])
        if snapshot is not None:
            event['rhythm_snapshot'] = snapshot
        with actions.connection(True) as c:
            c.execute('INSERT INTO action_content_events VALUES (?,?,?)',
                      (event['event_id'], event['request_key'], actions.encoded(event)))
        return event

    def test_start_snapshot_survives_focus_and_mode_changes(self):
        self.enable(); first, second = self.create(), self.create(title='另一个任务')
        focus = self.minimum(first)
        start = self.op(first, 'start', variant='minimum').json()
        self.assertFalse(start['execution']['activity_confirmed'])
        self.assertEqual(start['execution']['focus_day_id'], focus['id'])
        self.assertEqual(start['execution']['focus_plan_id_snapshot'], first['id'])
        self.post('/focus', expected_revision=focus['revision'], date='2026-10-21', plan_id=second['id'])
        finish = self.op(start['plan'], 'finish', execution_id=start['execution']['id'], actual_minutes=2)
        self.assertEqual(finish.status_code, 200, finish.text)
        record = finish.json()['execution']
        self.assertEqual(record['minimum_step_snapshot'], '只做一小步')
        self.assertEqual(record['rhythm_variant'], 'minimum')
        self.assertEqual(record['focus_plan_id_snapshot'], first['id'])
        self.assertTrue(is_effective_activity(record))
        self.assertEqual(finish.json()['plan']['status'], 'active')

    def test_cross_midnight_keeps_p0_start_date_and_adds_confirmation_date(self):
        self.enable(); plan = self.create(); self.select(plan)
        with patch('action_plans.clock', return_value=datetime(2026, 10, 21, 15, 59, tzinfo=timezone.utc)):
            start = self.op(plan, 'start').json()
        with patch('action_plans.clock', return_value=datetime(2026, 10, 21, 16, 3, tzinfo=timezone.utc)):
            finish = self.op(start['plan'], 'finish', execution_id=start['execution']['id'], actual_minutes=4).json()
        record = finish['execution']
        self.assertEqual(record['business_date'], '2026-10-21')
        self.assertEqual(record['planned_date'], '2026-10-21')
        self.assertEqual(record['activity_date'], '2026-10-22')
        self.assertTrue(is_effective_activity(record))

    def test_selecting_focus_after_start_cannot_attach_to_existing_execution(self):
        self.enable(); plan = self.create()
        started = self.op(plan, 'start').json()
        self.select(started['plan'])
        record = self.op(started['plan'], 'finish', execution_id=started['execution']['id'], actual_minutes=1).json()['execution']
        self.assertIsNone(record['focus_day_id'])
        self.assertIsNone(record['focus_plan_id_snapshot'])

    def test_step_is_idempotent_and_does_not_complete_task_or_invent_minutes(self):
        self.enable(); plan = self.create(completion_mode='check'); focus = self.minimum(plan)
        result = self.step(plan, focus, key='same-minimum-step', note='留下一个问题')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.step(plan, focus, key='same-minimum-step', note='留下一个问题').json(), result.json())
        record = result.json()['execution']
        self.assertEqual((record['record_kind'], record['outcome'], record['actual_minutes']), ('step', 'partial', 0))
        self.assertEqual(record['completion_effect'], 'none')
        self.assertEqual(result.json()['plan']['status'], 'active')
        self.assertTrue(is_effective_activity(record))
        self.assertEqual(self.step(plan, focus).status_code, 409)
        with db.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM action_executions').fetchone()[0], 1)

    def test_step_rejects_no_confirmation_wrong_context_and_global_running(self):
        self.enable(); plan = self.create(completion_mode='check'); focus = self.minimum(plan)
        body = dict(plan_id=plan['id'], plan_revision=plan['revision'], focus_day_id=focus['id'],
                    minimum_step=focus['minimum_step'], did_act=False)
        self.assertEqual(self.post('/steps', **body).status_code, 422)
        self.assertEqual(self.post('/steps', **(body | {'did_act': 1})).status_code, 422)
        self.assertEqual(self.post('/steps', **(body | {'did_act': True, 'minimum_step': '另一个步骤'})).status_code, 409)
        other = self.create(); self.op(other, 'start')
        self.assertEqual(self.step(plan, focus).json()['code'], 'RUNNING_CONFLICT')
        with db.connect() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM action_executions WHERE state='partial'").fetchone()[0], 0)

    def test_step_fact_plan_and_operation_receipt_roll_back_together(self):
        self.enable(); plan = self.create(completion_mode='check'); focus = self.minimum(plan)
        with patch('action_plans.write', side_effect=RuntimeError('injected failure')):
            with self.assertRaises(RuntimeError):
                self.step(plan, focus, key='rollback-small-step')
        self.assertFalse(self.client.get('/api/action-plans/requests/rollback-small-step').json()['found'])
        with db.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM action_executions').fetchone()[0], 0)
        self.assertEqual(self.step(plan, focus, key='rollback-small-step').status_code, 200)

    def test_rest_cannot_hide_running_and_does_not_remove_saved_work(self):
        self.enable(); plan = self.create(); focus = self.select(plan).json()['focus']
        start = self.op(plan, 'start').json()
        self.assertEqual(self.post('/focus/' + focus['id'] + '/mode', expected_revision=1, mode='rest').status_code, 409)
        self.op(start['plan'], 'finish', execution_id=start['execution']['id'], actual_minutes=1)
        self.assertEqual(self.post('/focus/' + focus['id'] + '/mode', expected_revision=1, mode='rest').status_code, 200)
        self.assertEqual(len(self.today()['records']), 1)

    def test_check_reversal_preserves_original_and_is_not_new_activity(self):
        self.enable(); plan = self.create(completion_mode='check'); self.select(plan)
        done = self.op(plan, 'complete').json()
        with db.connect() as c:
            original = c.execute('SELECT data FROM action_executions WHERE id=?', (done['execution']['id'],)).fetchone()[0]
        self.assertTrue(is_effective_activity(done['execution']))
        reopened = self.op(done['plan'], 'reopen').json()['execution']
        self.assertFalse(reopened['activity_confirmed'])
        self.assertFalse(is_effective_activity(reopened))
        self.assertEqual(reopened['reverses_record_id'], done['execution']['id'])
        with db.connect() as c:
            self.assertEqual(c.execute('SELECT data FROM action_executions WHERE id=?', (done['execution']['id'],)).fetchone()[0], original)
        self.assertEqual({r['record_kind'] for r in self.today()['records']}, {'completion', 'reversal'})

    def test_content_minimum_saves_effort_but_not_content_completion(self):
        self.enable(); plan, _ = self.content(); self.minimum(plan, '只读一段')
        started = self.op(plan, 'start', variant='minimum')
        self.assertEqual(started.status_code, 200, started.text)
        started = started.json()
        finished = self.op(started['plan'], 'finish', execution_id=started['execution']['id'], actual_minutes=1).json()
        self.assertEqual(finished['execution']['outcome'], 'recorded')
        self.assertTrue(is_effective_activity(finished['execution']))
        self.assertEqual(finished['plan']['status'], 'active')
        with db.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM action_content_events').fetchone()[0], 0)

    def test_source_replay_and_read_receipt_return_one_original_fact(self):
        self.enable(); plan, target = self.content(); focus = self.select(plan).json()['focus']
        event = self.source_event(plan, target, dict(focus_day_id=focus['id'], focus_plan_id_snapshot=plan['id'],
                    focus_selected_at_snapshot=focus['selected_at'], rhythm_variant='standard', minimum_step_snapshot=''))
        first = actions.with_content_completion({'saved': True}, target, event['event_id'])
        second = actions.with_content_completion({'saved': True}, target, event['event_id'])
        self.assertEqual(first['action_completion_receipts'], second['action_completion_receipts'])
        receipt = first['action_completion_receipts'][0]
        path = '/api/action-plans/rhythm/source-receipts/' + event['event_id']
        self.assertEqual(self.client.get(path).json()['action_completion_receipts'], [receipt])
        self.assertEqual(self.client.get(path).json()['action_completion_receipts'], [receipt])
        self.assertEqual(self.client.get('/api/action-plans/records').json()['total'], 1)
        self.assertEqual(self.client.get('/api/action-plans/rhythm/source-receipts/source-foreign').status_code, 404)

    def test_delayed_source_uses_captured_context_and_source_confirmation_date(self):
        self.enable(); plan, target = self.content(); focus = self.minimum(plan, '只读一段')
        event = self.source_event(plan, target, dict(focus_day_id=focus['id'], focus_plan_id_snapshot=plan['id'],
            focus_selected_at_snapshot=focus['selected_at'], rhythm_variant='minimum', minimum_step_snapshot='只读一段'))
        with patch('action_plans.clock', return_value=datetime(2026, 10, 22, 12, tzinfo=timezone.utc)):
            actions.with_content_completion({}, target, event['event_id'])
        record = self.client.get('/api/action-plans/records').json()['records'][0]
        self.assertEqual(record['activity_date'], '2026-10-21')
        self.assertEqual(record['minimum_step_snapshot'], '只读一段')
        self.assertEqual(record['focus_plan_id_snapshot'], plan['id'])
        self.assertTrue(is_effective_activity(record))

    def test_legacy_notes_are_not_backfilled_when_reading_records(self):
        plan = self.create()
        original = dict(id='execution-legacy', plan_id=plan['id'], outcome='partial', actual_minutes=2,
                        note='历史总结', started_at='2026-10-20T12:00:00Z', business_date='2026-10-20')
        raw = actions.encoded(original)
        with db.connect() as c:
            c.execute('INSERT INTO action_executions VALUES (?,?,?,?)', (original['id'], plan['id'], 'partial', raw))
        record = self.client.get('/api/action-plans/records').json()['records'][0]
        self.assertNotIn('fact_version', record)
        self.assertFalse(is_effective_activity(record))
        with db.connect() as c:
            self.assertEqual(c.execute('SELECT data FROM action_executions').fetchone()[0], raw)

    def test_source_context_during_handoff_does_not_read_old_local_focus(self):
        self.enable(); plan, target = self.content(); self.select(plan)
        with actions.connection(True, allow_link=True) as c:
            c.execute('INSERT INTO action_link_state VALUES (1,?,NULL)', (actions.encoded({'phase': 'pending'}),))
        from rhythm.facts import source_context
        with actions.connection() as c, patch('rhythm.service.preferences', side_effect=AssertionError('old local read')):
            snapshot = source_context(c, target, plan['id'], actions.clock())
        self.assertIsNone(snapshot['focus_day_id'])
