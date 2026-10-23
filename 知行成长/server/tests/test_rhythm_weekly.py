"""Weekly reads are pure, all facts are included, confirmed history is immutable."""
from test_rhythm_focus import RhythmFixture


class RhythmWeeklyTests(RhythmFixture):
    def setup_week(self):
        self.enable(); p = self.create(completion_mode='check'); self.select(p)
        return self.op(p, 'complete').json()['execution']

    def week(self):
        result = self.client.get('/api/action-plans/rhythm/weeks/2026-10-19')
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def confirm(self, week, **values):
        return self.post('/weeks/2026-10-19/confirm', expected_revision=(week['card'] or {}).get('revision', 0),
                         snapshot_hash=week['snapshot_hash'], **values)

    def test_confirmation_history_stale_snapshot_and_revision(self):
        r = self.setup_week(); week = self.week()
        self.assertIsNone(week['card']); self.assertIsNone(self.week()['card'])
        saved = self.confirm(week, selected_execution_ids=[r['id']], adjustment_text='先做一步')
        self.assertEqual(saved.status_code, 200, saved.text)
        card = saved.json()['card']
        self.post('/executions/'+r['id']+'/recap', expected_recap_revision=0, note='有成果')
        newer = self.week()
        self.assertTrue(newer['changed'])
        self.assertEqual(newer['card'], card)
        self.assertEqual(self.confirm(week).status_code, 409)
        self.assertEqual(self.confirm(newer, selected_execution_ids=['foreign']).status_code, 422)
        updated = self.confirm(newer).json()['card']
        self.assertEqual(updated['history'][0], {k: v for k, v in card.items() if k != 'history'})

    def test_all_facts_not_only_first_page_and_target_validation(self):
        self.enable()
        for i in range(32):
            p = self.create(title='item '+str(i), completion_mode='check')
            self.op(p, 'complete')
        week = self.week()
        self.assertEqual(week['stats']['action_units'], 32)
        self.assertEqual(len(week['records']), 32)
        self.assertEqual(self.confirm(week, adjustment_text='调整', adjustment_target_plan_id='foreign').status_code, 404)
        self.assertEqual(self.client.get('/api/action-plans/rhythm/weeks/2026-10-20').status_code, 422)
