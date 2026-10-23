"""Opt-in trial, fixed local-calendar cutoffs and anonymous aggregate reporting."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import json
import uuid
import math
import action_plans as actions
from . import service
from .metrics import aggregate, effective, stamp


def enrollment(c, key):
    row=c.execute('SELECT data FROM action_rhythm_enrollments WHERE experiment_key=?',(key,)).fetchone()
    return json.loads(row[0]) if row else None


def enroll(body):
    with actions.connection(True) as c:
        service.bootstrap(c)
        def work():
            prefs=service.require_enabled(c)
            from tenancy import current_user
            user=current_user.get() or {}
            if user.get('is_test'):
                actions.fail(403,'测试账号不加入真实使用试验。')
            old=enrollment(c,body.experiment_key)
            if old:return {'enrollment':old}
            data=dict(id='participant-'+uuid.uuid4().hex,experiment_key=body.experiment_key,
                enrolled_at=actions.clock().isoformat(),timezone_snapshot=prefs['timezone'],
                weekly_target_days=prefs['weekly_target_days'],review_weekday=prefs['review_weekday'],
                eligible_reason='local_owner_opted_in',app_version='rhythm-v1',is_test=False,
                day7_survey=None,day14_survey=None)
            c.execute('INSERT INTO action_rhythm_enrollments VALUES (?,?,?)',(data['id'],body.experiment_key,actions.encoded(data)))
            from .events import emit
            emit(c,'rhythm_enrolled','enroll:'+data['id'],enrollment_id=data['id'],experiment_key=body.experiment_key)
            return {'enrollment':data}
        return actions.operation(c,body.key,{'op':'rhythm.enroll',**body.model_dump(mode='json')},work)


def bounds(person):
    zone=ZoneInfo(person['timezone_snapshot']);begin=stamp(person['enrolled_at']);day=begin.astimezone(zone).date()
    midnight=lambda offset:datetime.combine(day+timedelta(days=offset),time.min,zone)
    return begin,day,midnight


def survey(body):
    with actions.connection(True) as c:
        service.bootstrap(c)
        def work():
            service.require_enabled(c)
            person=enrollment(c,body.experiment_key)
            if not person:actions.fail(409,'请先自愿加入本轮试用。')
            _,_,midnight=bounds(person)
            if actions.clock()<midnight(body.day-1):actions.fail(409,'还未到本次问卷日期。')
            key='day'+str(body.day)+'_survey'
            value=dict(clarity_score=body.clarity_score,progress_score=body.progress_score,saved_at=actions.clock().isoformat())
            if person.get(key):value['history']=[*person[key].get('history',[]),{k:v for k,v in person[key].items() if k!='history'}]
            person[key]=value
            c.execute('UPDATE action_rhythm_enrollments SET data=? WHERE id=?',(actions.encoded(person),person['id']))
            from .events import emit
            emit(c,'rhythm_survey_saved','survey:'+person['id']+':'+str(body.day),enrollment_id=person['id'],day=body.day)
            return {'enrollment':person}
        return actions.operation(c,body.key,{'op':'rhythm.survey',**body.model_dump(mode='json')},work)


def report(person, records, cards, events, now):
    begin,day,midnight=bounds(person);end=midnight(14)-timedelta(microseconds=1);cutoff=min(now,end)
    stats=aggregate(records,zone=person['timezone_snapshot'],since=begin,cutoff=cutoff)
    first=aggregate(records,zone=person['timezone_snapshot'],since=begin,cutoff=min(cutoff,midnight(1)-timedelta(microseconds=1)))
    w2=aggregate(records,start=day+timedelta(days=7),end=day+timedelta(days=13),zone=person['timezone_snapshot'],since=begin,cutoff=cutoff)
    snapshots=[]
    for card in cards:
        for version in [*card.get('history',[]),card]:
            if (begin<=stamp(version['confirmed_at'])<=cutoff and version['week_start']<=str(day+timedelta(days=13))
                    and version['week_end']>=str(day)):
                snapshots.append(version)
    adjustments=[v for v in snapshots if stamp(v['confirmed_at'])<midnight(7) and v.get('adjustment_text','').strip()]
    linked=[v for v in adjustments if v.get('adjustment_target_plan_id')]
    w2_facts=[r for r in effective(records,since=max(begin,midnight(7)),cutoff=cutoff)]
    tried=any(r['plan_id']==v['adjustment_target_plan_id'] and stamp(r['activity_at'])>=stamp(v['confirmed_at']) for v in linked for r in w2_facts)
    survey=person.get('day14_survey') or {}
    eligible_surveys=[v for v in [*survey.get('history',[]),survey] if v.get('saved_at') and stamp(v['saved_at'])<=end]
    answer=max(eligible_surveys,key=lambda v:stamp(v['saved_at']),default={})
    review_day=day+timedelta(days=(person.get('review_weekday',7)-1-day.weekday())%7)
    observed=min(14,max(0,(cutoff.astimezone(ZoneInfo(person['timezone_snapshot'])).date()-day).days))
    if now>end:observed=14
    action_dates=set(stats['action_dates']);gap=None
    for offset in range(max(0,observed-1)):
        if all(str(day+timedelta(days=offset+i)) not in action_dates for i in (0,1)):
            gap=offset;break
    recovery_eligible=gap is not None and gap+5<=observed
    recovered=recovery_eligible and any(str(day+timedelta(days=gap+i)) in action_dates for i in (2,3,4))
    burdens=[]
    for event in events:
        if event.get('event_name')=='form_finished' and begin<=stamp(event['occurred_at'])<=cutoff:
            data=event['data'];burdens.append({k:data.get(k) for k in ('form_kind','result','active_duration_ms')})
    return dict(participant_id=person['id'],is_test=bool(person.get('is_test')),window_start=str(day),window_end=str(day+timedelta(days=13)),
        mature=now>=midnight(14),d1_activated=bool(first['loop_days']),stats=stats,w2_stats=w2,
        review_eligible=bool(stats['action_days']) and cutoff>=datetime.combine(review_day,time.min,ZoneInfo(person['timezone_snapshot'])),
        review_confirmed=bool(snapshots),adjustment_linked=bool(linked),adjustment_unlinked=bool(adjustments and not linked),adjustment_tried=tried,
        clarity_score=answer.get('clarity_score'),progress_score=answer.get('progress_score'),
        recovery_eligible=recovery_eligible,recovered=bool(recovered),burdens=burdens)


def summarize(reports):
    people=list({r['participant_id']:r for r in reports if not r.get('is_test')}.values())
    mature=[r for r in people if r['mature']]
    ratio=lambda rows,predicate:dict(numerator=sum(bool(predicate(r)) for r in rows),denominator=len(rows))
    result=dict(participants=len(people),sample_insufficient=len(people)<20,not_yet_14_days=len(people)-len(mature),
        first_day_activation=ratio(people,lambda r:r['d1_activated']),
        recap_completion=dict(numerator=sum(r['stats']['recap_units'] for r in people),denominator=sum(r['stats']['action_units'] for r in people)),
        w2_loop_retention=ratio(mature,lambda r:r['w2_stats']['loop_days']>=3),
        w2_action_retention=ratio(mature,lambda r:r['w2_stats']['action_days']>=3),
        weekly_review=ratio([r for r in people if r['review_eligible']],lambda r:r['review_confirmed']),
        adjustment_execution=ratio([r for r in mature if r['adjustment_linked']],lambda r:r['adjustment_tried']),
        adjustment_unlinked=sum(r['adjustment_unlinked'] for r in people),
        subjective_clarity=ratio([r for r in mature if r.get('clarity_score') is not None],lambda r:r['clarity_score']>=4),
        subjective_progress=ratio([r for r in mature if r.get('progress_score') is not None],lambda r:r['progress_score']>=4),
        survey_response=ratio(mature,lambda r:r.get('clarity_score') is not None and r.get('progress_score') is not None),
        missing_day14_surveys=sum(r.get('clarity_score') is None for r in mature),
        recovery=ratio([r for r in people if r['recovery_eligible']],lambda r:r['recovered']))
    result['mode_groups']={name:dict(participants=len(group),mature=sum(r['mature'] for r in group),
        w2_loop_retention=ratio([r for r in group if r['mature']],lambda r:r['w2_stats']['loop_days']>=3))
        for name,group in [('minimum_used',[r for r in people if r['stats']['minimum_days']]),('standard_only_or_inactive',[r for r in people if not r['stats']['minimum_days']])]}
    result['burden']={}
    for form in ('focus','recap','weekly'):
        rows=[b for r in people for b in r.get('burdens',[]) if b['form_kind']==form]
        durations=sorted(b['active_duration_ms'] for b in rows if isinstance(b.get('active_duration_ms'),int))
        percentile=lambda q:durations[max(0,math.ceil(len(durations)*q)-1)] if durations else None
        result['burden'][form]=dict(samples=len(rows),p50_ms=percentile(.5),p90_ms=percentile(.9),cancelled=sum(b['result']=='cancel' for b in rows),errors=sum(b['result']=='error' for b in rows))
    return result
