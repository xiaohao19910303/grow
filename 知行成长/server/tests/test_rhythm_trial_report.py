"""Fixed 14-day calendar windows, zero activity and late summaries stay honest."""
from datetime import datetime, timezone
from unittest.mock import patch
from test_rhythm_focus import RhythmFixture
from test_rhythm_metrics import record
from rhythm.trial import report, summarize


class RhythmTrialTests(RhythmFixture):
    def test_enrollment_idempotency_and_survey_due_and_export(self):
        self.enable()
        first=self.post('/enrollment', key='trial-enroll-key', experiment_key='trial-1')
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(self.post('/enrollment', key='trial-enroll-key', experiment_key='trial-1').json(), first.json())
        self.assertEqual(self.post('/enrollment', experiment_key='trial-1').json()['enrollment']['id'], first.json()['enrollment']['id'])
        body=dict(experiment_key='trial-1', day=7, clarity_score=4, progress_score=5)
        self.assertEqual(self.post('/survey', **body).status_code, 409)
        with patch('action_plans.clock',return_value=datetime(2026,10,27,12,tzinfo=timezone.utc)):
            self.assertEqual(self.post('/survey', **body).status_code, 200)
        trial=self.client.get('/api/action-plans/rhythm/trial?experiment_key=trial-1').json()
        self.assertIsNotNone(trial['trial_report']);self.assertNotIn('report',trial)
        export=self.client.get('/api/action-plans/rhythm/export').json()
        self.assertEqual(export['enrollments'][0]['day7_survey']['clarity_score'],4)
        self.assertNotIn('events', export)

    def test_zero_active_is_in_denominator_and_immature_not_churn(self):
        enrollment=dict(id='anon-1', enrolled_at='2026-10-21T12:00:00Z', timezone_snapshot='Asia/Shanghai',review_weekday=7,is_test=False)
        mature=report(enrollment,[],[],[],datetime(2026,11,6,tzinfo=timezone.utc))
        early=report(enrollment|{'id':'anon-2'},[],[],[],datetime(2026,10,24,tzinfo=timezone.utc))
        summary=summarize([mature,early])
        self.assertEqual(summary['first_day_activation'],{'numerator':0,'denominator':2})
        self.assertEqual(summary['w2_loop_retention'],{'numerator':0,'denominator':1})
        self.assertEqual(summary['not_yet_14_days'],1)
        self.assertEqual(summary['subjective_clarity']['denominator'],0)

    def test_d1_and_d14_cutoffs_do_not_count_late_summary(self):
        enrollment=dict(id='anon-1',enrolled_at='2026-10-21T11:00:00Z',timezone_snapshot='Asia/Shanghai',review_weekday=7)
        r=record(note='补写',recap_saved_at='2026-11-05T12:00:00Z',recap_history=[])
        result=report(enrollment,[r],[],[],datetime(2026,11,6,tzinfo=timezone.utc))
        self.assertFalse(result['d1_activated']);self.assertEqual(result['stats']['recap_units'],0)
        self.assertEqual(result['stats']['action_units'],1)
        self.assertFalse(result['is_test'])

    def test_synthetic_two_weeks_adjustment_attempt_and_mode_group(self):
        from datetime import timedelta
        begin=datetime(2026,10,21,11,tzinfo=timezone.utc)
        person=dict(id='synthetic',enrolled_at=begin.isoformat(),timezone_snapshot='Asia/Shanghai',review_weekday=7)
        facts=[]
        for i in (0,1,2,7,8,9):
            at=begin+timedelta(days=i,hours=1);pid='next-week' if i>=7 else 'first-week'
            facts.append(record(str(i),plan_id=pid,focus_plan_id_snapshot=pid,activity_at=at.isoformat(),
                activity_date=str(at.date()),focus_selected_at_snapshot=(at-timedelta(minutes=1)).isoformat(),
                recap_saved_at=at.isoformat(),rhythm_variant='minimum' if i%2 else 'standard'))
        cards=[dict(week_start='2026-10-19',week_end='2026-10-25',confirmed_at=(begin+timedelta(days=4)).isoformat(),
                    adjustment_text='先看证据',adjustment_target_plan_id='next-week')]
        result=report(person,facts,cards,[],begin+timedelta(days=15))
        self.assertTrue(result['d1_activated']);self.assertTrue(result['review_confirmed'])
        self.assertTrue(result['adjustment_tried']);self.assertEqual(result['w2_stats']['loop_days'],3)
        summary=summarize([result,result])
        self.assertEqual(summary['participants'],1)
        self.assertEqual(summary['adjustment_execution'],{'numerator':1,'denominator':1})
        self.assertEqual(summary['mode_groups']['minimum_used']['participants'],1)
        self.assertEqual(summarize([result|{'is_test':True}])['participants'],0)

    def test_report_cli_only_reads_exports_and_emits_aggregate_counts(self):
        import json
        from pathlib import Path
        import subprocess
        import sys
        import tempfile
        person=dict(id='cli-anon',experiment_key='trial-cli',enrolled_at='2026-10-21T12:00:00Z',timezone_snapshot='Asia/Shanghai')
        result=report(person,[],[],[],datetime(2026,11,6,tzinfo=timezone.utc))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'export.json'
            path.write_text(json.dumps(dict(format='grow-rhythm-v1',enrollments=[person],trial_reports=[result],private_note='PRIVATE PROSE')))
            original=path.read_bytes()
            completed=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'tools/rhythm_trial_report.py'),str(path)],capture_output=True,text=True,check=True)
            self.assertEqual(path.read_bytes(),original)
            self.assertEqual(json.loads(completed.stdout)['participants'],1)
            self.assertNotIn('PRIVATE',completed.stdout)
            self.assertNotIn('cli-anon',completed.stdout)
