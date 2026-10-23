"""R01: additive rhythm contracts, separate from the action P0 schema version.

Rhythm request models and trusted activity predicates. The action P0 schema
version remains independent; UI events never substitute for confirmed facts.
"""
import re
from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator, AwareDatetime, BaseModel, BeforeValidator, ConfigDict,
    Field, StrictBool, ValidationError, model_validator,
)

CONTRACT_VERSION = 1
ERROR_STATUS = {
    'VALIDATION_ERROR': 422, 'REVISION_CONFLICT': 409, 'STATE_CONFLICT': 409,
    'RUNNING_CONFLICT': 409, 'DUPLICATE_SCHEDULE': 409, 'FUTURE_ACTION': 422,
    'UNSCHEDULED_ACTION': 422, 'COMPLETION_EVIDENCE_MISSING': 409,
    'CONTRACT_UPGRADE_REQUIRED': 409, 'SNAPSHOT_CONFLICT': 409,
    'NOT_FOUND': 404, 'FORBIDDEN': 403, 'FEATURE_DISABLED': 409,
    'RHYTHM_SCHEMA_INCOMPLETE': 503,
}


def local_date(value):
    if type(value) is date:
        return value
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('请使用 YYYY-MM-DD 本地日期。')
    return date.fromisoformat(value)


def valid_zone(value):
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError('时区无效。') from None
    return value


LocalDate = Annotated[date, BeforeValidator(local_date)]
ZoneName = Annotated[str, Field(min_length=1, max_length=80), AfterValidator(valid_zone)]
Revision = Annotated[int, Field(strict=True, ge=0)]
Minutes = Annotated[int, Field(strict=True, ge=0, le=1440)]


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    key: str = Field(min_length=8, max_length=160)


class PreferencesInput(Input):
    expected_revision: Revision
    enabled: StrictBool = False
    timezone: ZoneName = 'Asia/Shanghai'
    weekly_target_days: int = Field(default=3, strict=True, ge=1, le=7)
    review_weekday: int = Field(default=7, strict=True, ge=1, le=7)
    reminder_enabled: StrictBool = False
    reminder_time: str | None = Field(default=None, pattern=r'^([01]\d|2[0-3]):[0-5]\d$')

    @model_validator(mode='after')
    def explicit_reminder(self):
        if self.reminder_enabled and self.reminder_time is None:
            raise ValueError('开启提醒时请选择具体时间。')
        return self


class FocusInput(Input):
    expected_revision: Revision
    date: LocalDate
    plan_id: str = Field(min_length=1, max_length=80)
    success_criterion: str = Field(default='', max_length=500)
    first_step: str = Field(default='', max_length=500)


class ModeInput(Input):
    expected_revision: int = Field(strict=True, ge=1)
    mode: Literal['standard', 'minimum', 'rest']
    minimum_step: str = Field(default='', max_length=500)

    @model_validator(mode='after')
    def concrete_minimum(self):
        if self.mode == 'minimum' and not self.minimum_step:
            raise ValueError('请确认这次准备做的最小一步。')
        return self


class RecapInput(Input):
    expected_recap_revision: Revision
    note: str = Field(min_length=1, max_length=2000)
    next_step: str = Field(default='', max_length=500)
    recap_kind: Literal['gain', 'blocker', 'result'] = 'gain'


class StepInput(Input):
    plan_id: str = Field(min_length=1, max_length=80)
    plan_revision: int = Field(strict=True, ge=1)
    focus_day_id: str = Field(min_length=1, max_length=80)
    minimum_step: str = Field(min_length=1, max_length=500)
    did_act: StrictBool
    note: str = Field(default='', max_length=2000)
    next_step: str = Field(default='', max_length=500)

    @model_validator(mode='after')
    def actual_step(self):
        if not self.did_act:
            raise ValueError('只有实际尝试后才能确认这一步。')
        return self


def rhythm_capability(link_phase, *, enabled=False):
    """Fail closed for unknown owners; this does not enable a runtime route."""
    reason = ('CONTRACT_UPGRADE_REQUIRED' if link_phase != 'local'
              else None if enabled else 'FEATURE_DISABLED')
    return {'contract_version': CONTRACT_VERSION, 'supported': reason is None, 'reason': reason}


def activity_date(stamp: datetime, zone: str) -> date:
    """Confirmation date, deliberately independent of planned/business_date."""
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError('确认时间必须包含时区。')
    return stamp.astimezone(ZoneInfo(valid_zone(zone))).date()


def preferences_effective_from(stamp: datetime, zone: str, *, first: bool) -> date:
    day = activity_date(stamp, zone)
    return day if first else day + timedelta(days=7 - day.weekday())


class ActivityEvidence(BaseModel):
    """Read projection of a confirmed fact; unrelated legacy fields are retained by callers."""
    model_config = ConfigDict(extra='ignore')
    fact_version: Literal[2]
    activity_confirmed: StrictBool
    activity_at: AwareDatetime
    activity_date: LocalDate
    activity_timezone: ZoneName
    completion_mode: Literal['time', 'content', 'check']
    actual_minutes: Minutes
    outcome: Literal['running', 'completed', 'minimum', 'partial', 'interrupted', 'recorded', 'reopened']
    completion_effect: Literal['none', 'complete', 'reopen'] = 'none'
    reversed: StrictBool = False
    source_event_id: str = Field(default='', max_length=160)
    minimum_step_snapshot: str = Field(default='', max_length=500)


def is_effective_activity(record: dict) -> bool:
    """No backfill: old notes, wall-clock timers and UI events are not evidence.

    Reversal resolution must be applied by the aggregation service before
    calling this predicate. This function never alters a stored execution.
    """
    try:
        fact = ActivityEvidence.model_validate(record)
    except ValidationError:
        return False
    if (not fact.activity_confirmed or fact.reversed or fact.completion_effect == 'reopen'
            or fact.outcome in ('running', 'reopened')
            or fact.completion_mode == 'check' and fact.actual_minutes != 0
            or activity_date(fact.activity_at, fact.activity_timezone) != fact.activity_date):
        return False
    if fact.completion_mode in ('time', 'content') and fact.actual_minutes > 0:
        return True
    if fact.outcome == 'completed':
        return (fact.completion_mode == 'check'
                or fact.completion_mode == 'content' and bool(fact.source_event_id.strip()))
    return (fact.completion_mode == 'check' and fact.outcome == 'partial'
            and bool(fact.minimum_step_snapshot.strip()))


class UIEvent(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    event_id: str = Field(min_length=8, max_length=160)
    event_name: Literal['weekly_card_viewed', 'form_finished']
    source: Literal['today', 'reader', 'records', 'weekly', 'settings']
    session_id: str = Field(min_length=1, max_length=80)
    week_start: LocalDate | None = None
    form_kind: Literal['focus', 'recap', 'weekly'] | None = None
    result: Literal['save', 'cancel', 'error'] | None = None
    active_duration_ms: int | None = Field(default=None, strict=True, ge=0, le=3600000)

    @model_validator(mode='after')
    def complete_event(self):
        if self.event_name == 'weekly_card_viewed' and (not self.week_start or self.week_start.weekday() != 0):
            raise ValueError('周卡事件需要周一日期。')
        if self.event_name == 'form_finished' and any(v is None for v in (self.form_kind, self.result, self.active_duration_ms)):
            raise ValueError('表单事件缺少类型、结果或操作时长。')
        return self


class UIEventsInput(Input):
    events: list[UIEvent] = Field(max_length=20)


class WeeklyInput(Input):
    expected_revision: Revision
    snapshot_hash: str = Field(min_length=64, max_length=64, pattern=r'^[a-f0-9]+$')
    selected_execution_ids: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(default_factory=list, max_length=3)
    adjustment_text: str = Field(default='', max_length=500)
    adjustment_target_plan_id: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode='after')
    def linked_adjustment(self):
        if len(set(self.selected_execution_ids)) != len(self.selected_execution_ids):
            raise ValueError('成果不能重复选择。')
        if self.adjustment_target_plan_id and not self.adjustment_text:
            raise ValueError('关联行动时请填写这次调整。')
        return self


class EnrollmentInput(Input):
    experiment_key: str = Field(default='daily-rhythm-v1', min_length=1, max_length=80, pattern=r'^[a-zA-Z0-9_-]+$')


class SurveyInput(Input):
    experiment_key: str = Field(default='daily-rhythm-v1', min_length=1, max_length=80, pattern=r'^[a-zA-Z0-9_-]+$')
    day: Literal[7, 14]
    clarity_score: int = Field(strict=True, ge=1, le=5)
    progress_score: int = Field(strict=True, ge=1, le=5)
