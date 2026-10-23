"""Shared day/unit predicates exclude reversals and legacy/summary-only activity."""
from datetime import datetime, timezone
import unittest
from rhythm.metrics import aggregate, recap_at


def record(eid='a', **updates):
    return dict(id=eid, plan_id='p', fact_version=2, activity_confirmed=True,
                activity_at='2026-10-21T12:00:00+00:00', activity_date='2026-10-21', activity_timezone='Asia/Shanghai',
                completion_mode='time', actual_minutes=1, outcome='partial', completion_effect='none',
                focus_day_id='f', focus_plan_id_snapshot='p', focus_selected_at_snapshot='2026-10-21T11:00:00+00:00',
                note='收获', recap_revision=1, recap_saved_at='2026-10-21T12:00:00+00:00', rhythm_variant='minimum') | updates


class RhythmMetricTests(unittest.TestCase):
    def test_same_plan_day_unit_and_days_are_deduplicated(self):
        result = aggregate([record(), record('b', note='', completion_mode='content', actual_minutes=0,
                            outcome='completed', source_event_id='source')])
        self.assertEqual((result['action_days'], result['loop_days'], result['action_units'], result['recap_units']), (1, 1, 1, 1))
        self.assertEqual(result['minimum_days'], 1)

    def test_reversal_excludes_original_and_does_not_cancel_other_effort(self):
        result = aggregate([record(), record('b', completion_mode='check', actual_minutes=0, outcome='completed'),
                            dict(id='r', completion_effect='reopen', reverses_record_id='b', ended_at='2026-10-21T13:00:00Z')])
        self.assertEqual(result['source_fact_ids'], ['a'])
        self.assertEqual(aggregate([record(fact_version=1)])['action_days'], 0)

    def test_posthoc_focus_cannot_make_loop(self):
        self.assertEqual(aggregate([record(focus_selected_at_snapshot='2026-10-21T13:00:00Z')])['loop_days'], 0)
        self.assertEqual(aggregate([record(focus_plan_id_snapshot='other')])['loop_days'], 0)

    def test_cutoff_selects_old_recap_and_excludes_later_reversal(self):
        cutoff = datetime(2026, 10, 21, 13, tzinfo=timezone.utc)
        r = record(note='后来', recap_revision=2, recap_saved_at='2026-10-22T12:00:00Z',
                   recap_history=[dict(note='当天', recap_revision=1, recap_saved_at='2026-10-21T12:00:00Z')])
        self.assertEqual(recap_at(r, cutoff)['note'], '当天')
        self.assertEqual(aggregate([r, dict(completion_effect='reopen', reverses_record_id='a', ended_at='2026-10-22T12:00:00Z')], cutoff=cutoff)['action_days'], 1)
