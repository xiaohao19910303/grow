"""Private rhythm endpoints; existing action middleware provides CSRF/schema guards."""
from fastapi import Query

import action_plans as actions
from . import service
from .contracts import Input, EnrollmentInput, SurveyInput, FocusInput, LocalDate, ModeInput, PreferencesInput, RecapInput, StepInput, UIEventsInput, WeeklyInput, rhythm_capability


def register(router):
    @router.get('/rhythm/capabilities')
    def capabilities():
        with actions.connection() as c:
            return rhythm_capability('local', enabled=service.preferences(c)['preferences']['enabled'])

    @router.get('/rhythm/today')
    def today(date: LocalDate | None = Query(default=None)):
        return service.today(date)

    @router.post('/rhythm/preferences')
    def preferences(body: PreferencesInput):
        return service.save_preferences(body)

    @router.post('/rhythm/focus')
    def focus(body: FocusInput):
        return service.select_focus(body)

    @router.post('/rhythm/focus/{focus_id}/mode')
    def mode(focus_id: str, body: ModeInput):
        return service.change_mode(focus_id, body)

    @router.get('/rhythm/executions/{execution_id}')
    def execution(execution_id: str):
        import json
        from .metrics import effective
        with actions.connection() as c:
            row = c.execute('SELECT data FROM action_executions WHERE id=?', (execution_id,)).fetchone()
            if not row:
                actions.fail(404, '执行记录不存在。')
            record = json.loads(row[0])
            related = next((r for r in effective(actions.facts(c)) if r['id'] != execution_id
                and r['plan_id'] == record['plan_id'] and r.get('activity_date') == record.get('activity_date')
                and r.get('note', '').strip()), None) if not record.get('note', '').strip() else None
            return {'execution': record, 'related_recap': related}

    @router.post('/rhythm/executions/{execution_id}/recap')
    def recap(execution_id: str, body: RecapInput):
        from .recap import save
        return save(execution_id, body)

    @router.get('/rhythm/weeks/{week_start}')
    def week(week_start: LocalDate):
        from .weekly import view
        with actions.connection() as c:
            service.bootstrap(c)
            return view(c, week_start)

    @router.post('/rhythm/weeks/{week_start}/confirm')
    def confirm_week(week_start: LocalDate, body: WeeklyInput):
        from .weekly import confirm
        return confirm(week_start, body)

    @router.post('/rhythm/reminder-claim')
    def reminder(body: Input):
        from .reminders import claim
        return claim(body)

    @router.post('/rhythm/enrollment')
    def enrollment(body: EnrollmentInput):
        from .trial import enroll
        return enroll(body)

    @router.post('/rhythm/survey')
    def survey(body: SurveyInput):
        from .trial import survey
        return survey(body)

    @router.get('/rhythm/export')
    def export(include_events: bool = False):
        from .export import personal
        with actions.connection(True) as c:
            return personal(c, include_events)

    @router.get('/rhythm/trial')
    def trial(experiment_key: str = Query(default='daily-rhythm-v1', min_length=1, max_length=80)):
        from .trial import enrollment, report
        import json
        with actions.connection() as c:
            service.bootstrap(c)
            person = enrollment(c, experiment_key)
            cards = [json.loads(r[0]) for r in c.execute('SELECT data FROM action_weekly_cards')]
            events = [dict(event_name=r[0],occurred_at=r[1].isoformat(),data=json.loads(r[2]))
                for r in c.execute('SELECT event_name,occurred_at,data FROM action_rhythm_events')]
            return {'enrollment': person, 'trial_report': report(person, actions.facts(c), cards, events, actions.clock()) if person else None}

    @router.post('/rhythm/events')
    def events(body: UIEventsInput):
        from .events import ingest
        return ingest(body)

    @router.post('/rhythm/steps')
    def step(body: StepInput):
        from .facts import save_step
        return save_step(body)

    @router.get('/rhythm/source-receipts/{event_id}')
    def source_receipt(event_id: str):
        from .facts import completion_receipts
        with actions.connection() as c:
            return {'source_event_id': event_id, 'action_completion_receipts': completion_receipts(c, event_id)}
