"""Shared trusted-fact aggregation for today, weeks and fixed trial windows."""
from datetime import datetime
from .contracts import is_effective_activity, activity_date


def stamp(value):
    return datetime.fromisoformat(value) if value else None


def recap_at(record, cutoff=None):
    if cutoff is None:
        return record
    versions = [*record.get('recap_history', []), record]
    eligible = [v for v in versions if v.get('recap_saved_at') and stamp(v['recap_saved_at']) <= cutoff]
    return max(eligible, key=lambda v: v.get('recap_revision', 0), default={})


def effective(records, *, since=None, cutoff=None):
    # recorded_at distinguishes delayed source reconciliation from confirmation time.
    available = [r for r in records if not cutoff or not r.get('recorded_at') or stamp(r['recorded_at']) <= cutoff]
    reversed_ids = {r.get('reverses_record_id') for r in available if r.get('completion_effect') == 'reopen'
                    and (not cutoff or r.get('ended_at') and stamp(r['ended_at']) <= cutoff)}
    return [r for r in available if r.get('id') not in reversed_ids and is_effective_activity(r)
            and (not since or stamp(r['activity_at']) >= since)
            and (not cutoff or stamp(r['activity_at']) <= cutoff)]


def aggregate(records, *, start=None, end=None, zone=None, since=None, cutoff=None):
    chosen = []
    units = {}
    days, loops, minimum, standard = set(), set(), set(), set()
    for r in effective(records, since=since, cutoff=cutoff):
        day = str(activity_date(stamp(r['activity_at']), zone)) if zone else r['activity_date']
        if start and day < str(start) or end and day > str(end):
            continue
        chosen.append(r); days.add(day)
        (minimum if r.get('rhythm_variant') == 'minimum' else standard).add(day)
        unit = units.setdefault((r['plan_id'], day), {'recap': False, 'focus': False})
        recap = recap_at(r, cutoff)
        has_note = bool(recap.get('note', '').strip())
        unit['recap'] |= has_note
        focused = bool(r.get('focus_day_id') and r.get('focus_plan_id_snapshot') == r['plan_id']
                       and r.get('focus_selected_at_snapshot')
                       and stamp(r['focus_selected_at_snapshot']) <= stamp(r['started_at'] if r.get('record_kind') == 'session' and r.get('started_at') else r['activity_at']))
        unit['focus'] |= focused
    for (_, day), unit in units.items():
        if unit['focus'] and unit['recap']:
            loops.add(day)
    return dict(action_days=len(days), loop_days=len(loops), action_dates=sorted(days), loop_dates=sorted(loops),
                minimum_days=len(minimum), standard_days=len(standard), minimum_dates=sorted(minimum),
                action_units=len(units), recap_units=sum(u['recap'] for u in units.values()),
                source_fact_ids=sorted(r['id'] for r in chosen),
                source_recap_revisions={r['id']: recap_at(r, cutoff).get('recap_revision', 0) for r in chosen})
