"""One summary body on the execution, with immutable revision snapshots."""
import json
import action_plans as actions

FIELDS = ('note', 'next_step', 'recap_kind', 'recap_revision', 'recap_saved_at')


def initial(record):
    if record.get('outcome') == 'running':
        return
    record.setdefault('next_step', '')
    record.setdefault('recap_kind', 'gain')
    record.setdefault('recap_revision', 1 if record.get('note', '').strip() else 0)
    record.setdefault('recap_saved_at', actions.clock().isoformat() if record['recap_revision'] else None)
    record.setdefault('recap_history', [])


def persist(c, record):
    c.execute('UPDATE action_executions SET data=? WHERE id=?', (actions.encoded(record), record['id']))


def save(eid, body):
    with actions.connection(True) as c:
        from .service import bootstrap, require_enabled
        bootstrap(c)
        def work():
            require_enabled(c)
            row = c.execute('SELECT data FROM action_executions WHERE id=?', (eid,)).fetchone()
            if not row:
                actions.fail(404, '执行记录不存在。')
            record = json.loads(row[0])
            if not record.get('ended_at') or record.get('outcome') == 'running' or record.get('record_kind') == 'reversal':
                actions.fail(409, '请先保存执行；撤销记录不能填写总结。')
            if record.get('recap_revision', 0) != body.expected_recap_revision:
                actions.fail(409, '总结已在其他页面更新，当前输入已保留。', 'REVISION_CONFLICT')
            original = {k: record.get(k) for k in FIELDS}
            original['recap_revision'] = record.get('recap_revision', 0)
            record['recap_history'] = [*record.get('recap_history', []), original]
            record.update(note=body.note, next_step=body.next_step, recap_kind=body.recap_kind,
                          recap_revision=body.expected_recap_revision + 1, recap_saved_at=actions.clock().isoformat())
            persist(c, record)
            from .events import execution_events
            execution_events(c, record, recap_only=True)
            return {'execution': record}
        return actions.operation(c, body.key, {'op': 'rhythm.recap', 'execution_id': eid, **body.model_dump(mode='json')}, work)
