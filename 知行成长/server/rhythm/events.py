"""Success events share the caller's transaction; no personal prose is collected."""
import uuid
import action_plans as actions
from .contracts import is_effective_activity

ATTRIBUTES = frozenset(('execution_id', 'plan_id', 'focus_day_id', 'mode', 'completion_mode',
    'activity_date', 'recap_revision', 'has_note', 'has_next_step', 'kind', 'week_start',
    'revision', 'enrollment_id', 'day', 'source', 'session_id', 'form_kind', 'result',
    'active_duration_ms', 'feature_version', 'experiment_key', 'schema_version', 'reverses_record_id'))


def emit(c, name, dedupe, **data):
    from .service import preferences
    if not preferences(c)['preferences']['enabled']:
        return
    clean = {k: v for k, v in data.items() if k in ATTRIBUTES}
    clean['schema_version'] = 1
    c.execute('''INSERT INTO action_rhythm_events VALUES (?,?,?,?,?)
        ON CONFLICT(dedupe_key) DO NOTHING''', ('rhythm-event-' + uuid.uuid4().hex, dedupe,
        name, actions.clock().isoformat(), actions.encoded(clean)))


def execution_events(c, record, *, recap_only=False):
    eid = record['id']
    common = {k: record.get(k) for k in ('plan_id', 'focus_day_id', 'completion_mode', 'activity_date')}
    common.update(execution_id=eid, mode=record.get('rhythm_variant', 'standard'))
    if not recap_only and record.get('outcome') == 'running':
        emit(c, 'execution_started', 'start:' + eid, **common)
    elif not recap_only and record.get('record_kind') == 'reversal':
        emit(c, 'activity_reversed', 'reverse:' + eid, reverses_record_id=record.get('reverses_record_id'), **common)
    elif not recap_only and is_effective_activity(record):
        emit(c, 'activity_confirmed', 'activity:' + eid, **common)
    if record.get('note', '').strip() and record.get('recap_revision', 0):
        emit(c, 'recap_saved', 'recap:' + eid + ':' + str(record['recap_revision']),
             recap_revision=record['recap_revision'], has_note=True,
             has_next_step=bool(record.get('next_step', '').strip()), kind=record.get('recap_kind', 'gain'), **common)


def ingest(body):
    from .service import bootstrap, require_enabled
    with actions.connection(True) as c:
        bootstrap(c)
        def work():
            require_enabled(c)
            for event in body.events:
                data = event.model_dump(mode='json', exclude={'event_id', 'event_name'}, exclude_none=True)
                emit(c, event.event_name, 'ui:' + event.event_id, **data)
            return {'accepted': len(body.events)}
        return actions.operation(c, body.key, {'op': 'rhythm.events', **body.model_dump(mode='json')}, work)
