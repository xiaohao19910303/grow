"""Explicit personal export; does not use or mutate legacy /api/data snapshots."""
import json
import action_plans as actions
from . import service
from .trial import report


def personal(c, include_events=False):
    service.bootstrap(c)
    def table(name):return [json.loads(r[0]) for r in c.execute('SELECT data FROM '+name+' ORDER BY id')]
    result=dict(format='grow-rhythm-v1',contract_version=1,exported_at=actions.clock().isoformat(),
        preferences=table('action_rhythm_preferences'),focus_days=table('action_focus_days'),
        weekly_cards=table('action_weekly_cards'),enrollments=table('action_rhythm_enrollments'),
        workspace_version=1,week_plans=table('action_week_plans'),planning_drafts=[{k:v for k,v in d.items() if k!='worker'} for d in table('action_plan_drafts')],
        plans=[actions.public(r) for r in c.execute('SELECT * FROM action_plans ORDER BY id')],executions=actions.facts(c))
    events=[dict(event_name=r[0],occurred_at=r[1].isoformat(),data=json.loads(r[2]))
            for r in c.execute('SELECT event_name,occurred_at,data FROM action_rhythm_events ORDER BY occurred_at,id')]
    result['trial_reports']=[report(p,result['executions'],result['weekly_cards'],events,actions.clock()) for p in result['enrollments']]
    if include_events:result['events']=events
    return result
