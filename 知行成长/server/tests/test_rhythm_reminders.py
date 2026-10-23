from concurrent.futures import ThreadPoolExecutor
from test_rhythm_focus import RhythmFixture


class RhythmReminderTests(RhythmFixture):
    def test_default_off_due_time_and_one_claim_across_clients(self):
        self.enable()
        self.assertFalse(self.post('/reminder-claim').json()['notify'])
        self.post('/preferences', expected_revision=1, enabled=True, reminder_enabled=True, reminder_time='20:01')
        self.assertFalse(self.post('/reminder-claim').json()['notify'])
        self.post('/preferences', expected_revision=2, enabled=True, reminder_enabled=True, reminder_time='19:59')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _: self.post('/reminder-claim').json()['notify'], range(2)))
        self.assertEqual(sorted(results), [False, True])
        self.assertFalse(self.post('/reminder-claim').json()['notify'])

    def test_existing_task_notification_claim_yields_rhythm(self):
        self.enable(); self.post('/preferences', expected_revision=1, enabled=True, reminder_enabled=True, reminder_time='19:00')
        p=self.create(reminder=True, at='19:00')
        claim=self.client.post('/api/action-plans/'+p['id']+'/reminder-claim',headers=self.headers,
                               json=dict(device_id='test-device',reminder_at=p['reminder_at']))
        self.assertTrue(claim.json()['notify'])
        self.assertFalse(self.post('/reminder-claim').json()['notify'])
