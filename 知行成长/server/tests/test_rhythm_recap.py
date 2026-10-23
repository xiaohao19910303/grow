"""R05 summary updates preserve facts, originals, revision and retry receipts."""
import json
from unittest.mock import patch
import db
from test_rhythm_focus import RhythmFixture


class RhythmRecapTests(RhythmFixture):
    def finished(self, **fields):
        self.enable(); plan = self.create(); self.select(plan)
        started = self.op(plan, 'start').json()
        return self.op(started['plan'], 'finish', execution_id=started['execution']['id'],
                       actual_minutes=2, **fields).json()['execution']

    def recap(self, record, **fields):
        return self.post('/executions/' + record['id'] + '/recap',
                         expected_recap_revision=record.get('recap_revision', 0), note='有收获', **fields)

    def test_finish_and_supplement_share_revision_and_preserve_original(self):
        record = self.finished(note='原文', next_step='下一步', recap_kind='result')
        self.assertEqual(record['recap_revision'], 1)
        result = self.recap(record, key='same-recap-request').json()['execution']
        self.assertEqual(result['recap_revision'], 2)
        self.assertEqual(result['recap_history'][0]['note'], '原文')
        self.assertEqual(result['recap_history'][0]['next_step'], '下一步')
        self.assertEqual(result['recap_history'][0]['recap_kind'], 'result')
        for field in ('activity_at', 'activity_date', 'actual_minutes', 'completion_effect', 'focus_day_id'):
            self.assertEqual(record[field], result[field])
        self.assertEqual(self.recap(record, key='same-recap-request').json()['execution'], result)
        self.assertEqual(self.recap(record).status_code, 409)
        with db.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM action_executions').fetchone()[0], 1)

    def test_blank_running_reversal_and_foreign_are_rejected(self):
        record = self.finished()
        self.assertEqual(self.post('/executions/'+record['id']+'/recap', expected_recap_revision=0, note='   ').status_code, 422)
        self.assertEqual(self.post('/executions/foreign/recap', expected_recap_revision=0, note='x').status_code, 404)
        p = self.create(); running = self.op(p, 'start').json()['execution']
        self.assertEqual(self.recap(running).status_code, 409)

    def test_legacy_edit_keeps_original_without_creating_new_activity(self):
        self.enable()
        plan = self.create()
        original = dict(id='legacy', plan_id=plan['id'], outcome='partial', actual_minutes=2,
                        note='旧正文', ended_at='2026-10-20T12:00:00Z')
        with db.connect() as c:
            c.execute('INSERT INTO action_executions VALUES (?,?,?,?)', ('legacy', plan['id'], 'partial', json.dumps(original)))
        edited = self.recap(original).json()['execution']
        self.assertEqual(edited['recap_history'][0]['note'], '旧正文')
        self.assertNotIn('activity_confirmed', edited)

    def test_failed_summary_preserves_saved_action_and_allows_same_key_retry(self):
        record = self.finished()
        with patch('rhythm.recap.persist', side_effect=RuntimeError('write failed')):
            with self.assertRaises(RuntimeError):
                self.recap(record, key='recap-failure-key')
        with db.connect() as c:
            saved = json.loads(c.execute('SELECT data FROM action_executions WHERE id=?', (record['id'],)).fetchone()[0])
            self.assertEqual(saved, record)
        self.assertEqual(self.recap(record, key='recap-failure-key').status_code, 200)
