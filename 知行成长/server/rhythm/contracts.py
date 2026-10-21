"""R01: additive rhythm contracts, separate from the action P0 schema version.

These models describe future rhythm writes. No existing action payload is
changed, and activity predicates accept trusted server records, never UI events.
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

    Reversal resolution must be applied by the future aggregation service before
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
