"""R01 contracts do not enable rhythm or mutate existing execution facts."""
import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from rhythm.contracts import (
    CONTRACT_VERSION, ERROR_STATUS, FocusInput, ModeInput, PreferencesInput,
    RecapInput, activity_date, is_effective_activity, preferences_effective_from,
    rhythm_capability,
)


class RhythmContractTests(unittest.TestCase):
    def test_feature_is_disabled_by_default_and_link_cannot_fall_back_to_local(self):
        self.assertEqual(CONTRACT_VERSION, 1)
        self.assertFalse(rhythm_capability('local')['supported'])
        self.assertTrue(rhythm_capability('local', enabled=True)['supported'])
        for phase in ('pending', 'active', 'unknown'):
            result = rhythm_capability(phase, enabled=True)
            self.assertFalse(result['supported'])
            self.assertEqual(result['reason'], 'CONTRACT_UPGRADE_REQUIRED')
        self.assertEqual(ERROR_STATUS['REVISION_CONFLICT'], 409)
        self.assertEqual(ERROR_STATUS['VALIDATION_ERROR'], 422)
        self.assertEqual(ERROR_STATUS['NOT_FOUND'], 404)

    def test_preferences_have_low_burden_defaults_and_explicit_reminders(self):
        value = PreferencesInput(key='preferences-key', expected_revision=0)
        self.assertEqual(value.weekly_target_days, 3)
        self.assertEqual(value.review_weekday, 7)
        self.assertFalse(value.enabled)
        self.assertFalse(value.reminder_enabled)
        self.assertIsNone(value.reminder_time)
        for update in ({'weekly_target_days': 0}, {'weekly_target_days': True},
                       {'weekly_target_days': '3'}, {'review_weekday': 8},
                       {'reminder_enabled': True}, {'reminder_time': '25:00'},
                       {'timezone': 'Invalid/Zone'}, {'enabled': 'true'}):
            with self.subTest(update=update), self.assertRaises(ValidationError):
                PreferencesInput(key='preferences-key', expected_revision=0, **update)

    def test_dates_are_real_local_dates_and_not_timestamps(self):
        base = dict(key='focus-request', expected_revision=0, plan_id='action-test')
        self.assertEqual(str(FocusInput(date='2026-10-21', **base).date), '2026-10-21')
        for value in ('2026-02-30', '2026-1-1', '2026-10-21T00:00:00Z', 1792540800):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                FocusInput(date=value, **base)

    def test_focus_rejects_identity_injection_and_revision_coercion(self):
        base = dict(key='focus-request', expected_revision=0, plan_id='action-test', date='2026-10-21')
        for update in ({'schema_name': 'another_account'}, {'user_id': 'someone'},
                       {'expected_revision': True}, {'expected_revision': -1},
                       {'first_step': 'x' * 501}, {'plan_id': ' '}):
            with self.subTest(update=update), self.assertRaises(ValidationError):
                FocusInput(**(base | update))

    def test_minimum_requires_a_concrete_step_but_rest_does_not(self):
        base = dict(key='minimum-request', expected_revision=1)
        self.assertEqual(ModeInput(mode='minimum', minimum_step='  读一段  ', **base).minimum_step, '读一段')
        self.assertEqual(ModeInput(mode='rest', **base).mode, 'rest')
        with self.assertRaises(ValidationError):
            ModeInput(mode='minimum', minimum_step=' ', **base)

    def test_recap_is_versioned_metadata_and_cannot_modify_activity(self):
        base = dict(key='recap-request', expected_recap_revision=0, note='一个疑问', recap_kind='blocker')
        self.assertEqual(RecapInput(**base).next_step, '')
        for update in ({'note': ' '}, {'note': 'x' * 2001},
                       {'expected_recap_revision': True}, {'actual_minutes': 100},
                       {'activity_date': '2026-10-20'}, {'recap_kind': 'mastered'}):
            with self.subTest(update=update), self.assertRaises(ValidationError):
                RecapInput(**(base | update))

    def test_confirmation_date_is_local_and_rejects_naive_clock(self):
        stamp = datetime(2026, 10, 20, 16, 1, tzinfo=timezone.utc)
        self.assertEqual(str(activity_date(stamp, 'Asia/Shanghai')), '2026-10-21')
        self.assertEqual(str(activity_date(stamp, 'UTC')), '2026-10-20')
        with self.assertRaises(ValueError):
            activity_date(stamp.replace(tzinfo=None), 'Asia/Shanghai')

    def test_preferences_change_next_week_without_changing_history(self):
        stamp = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
        self.assertEqual(str(preferences_effective_from(stamp, 'Asia/Shanghai', first=True)), '2026-10-21')
        self.assertEqual(str(preferences_effective_from(stamp, 'Asia/Shanghai', first=False)), '2026-10-26')
        monday = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
        self.assertEqual(str(preferences_effective_from(monday, 'UTC', first=False)), '2026-11-02')

    def fact(self, **updates):
        return dict(fact_version=2, activity_confirmed=True, completion_mode='time',
                    actual_minutes=2, outcome='partial', activity_at='2026-10-20T16:01:00Z',
                    activity_date='2026-10-21', activity_timezone='Asia/Shanghai') | updates

    def test_positive_minimum_and_interrupted_work_count_without_claiming_completion(self):
        for outcome in ('completed', 'minimum', 'partial', 'interrupted', 'recorded'):
            fact = self.fact(outcome=outcome, note='question', business_date='2026-10-19')
            original = dict(fact)
            self.assertTrue(is_effective_activity(fact))
            self.assertEqual(fact, original)

    def test_no_work_legacy_reversed_and_wrong_dates_are_not_new_activity(self):
        for updates in ({'fact_version': 1}, {'activity_confirmed': False},
                        {'actual_minutes': 0}, {'actual_minutes': True},
                        {'outcome': 'running'}, {'outcome': 'reopened'},
                        {'completion_effect': 'reopen'}, {'reversed': True},
                        {'activity_date': '2026-10-20'}, {'activity_at': '2026-10-20T16:01:00'},
                        {'activity_timezone': 'Invalid/Zone'}):
            with self.subTest(updates=updates):
                self.assertFalse(is_effective_activity(self.fact(**updates)))
        self.assertFalse(is_effective_activity({'note': '补写历史总结', 'business_date': '2026-10-21'}))

    def test_zero_minute_content_needs_receipt_and_check_needs_explicit_completion(self):
        content = self.fact(completion_mode='content', outcome='completed', actual_minutes=0)
        self.assertFalse(is_effective_activity(content))
        self.assertTrue(is_effective_activity(content | {'source_event_id': 'source-confirmation'}))
        self.assertTrue(is_effective_activity(self.fact(completion_mode='check', outcome='completed', actual_minutes=0)))

    def test_zero_minute_check_minimum_is_a_step_not_original_completion(self):
        fact = self.fact(completion_mode='check', outcome='partial', actual_minutes=0)
        self.assertFalse(is_effective_activity(fact))
        self.assertTrue(is_effective_activity(fact | {'minimum_step_snapshot': '尝试一个例子'}))

    def test_check_completion_cannot_invent_focus_minutes(self):
        self.assertFalse(is_effective_activity(self.fact(completion_mode='check', outcome='completed')))


if __name__ == '__main__':
    unittest.main()
