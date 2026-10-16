"""Legacy dashboard state: stable row identities and transactional snapshot checks."""
import json
import sqlite3
from contextlib import closing

from copilot.core import digest, encoded, fail

ROW_FIELDS = {
    'decisions': ('date', 'title', 'context', 'options', 'reason', 'expected', 'probability', 'emotion', 'actual', 'bias'),
    'predictions': ('date', 'statement', 'probability', 'result', 'deviation'),
    'reviews': ('date', 'thought', 'actual', 'gap', 'action'),
    'insights': ('date', 'insight', 'source'),
}
REQUIRED = {'modules', 'checkins', 'habits', 'customFields', 'customRecords',
            'decisions', 'predictions', 'reviews', 'insights', 'todos'}


def read_state(conn):
    """The caller holds one read/write transaction for this entire snapshot."""
    state = {'modules': [], 'checkins': {}, 'habits': {}, 'customFields': [],
             'customRecords': [], 'todos': []}
    for r in conn.execute('SELECT id,name,color,ord FROM modules ORDER BY ord,id'):
        state['modules'].append({'id': r['id'], 'name': r['name'], 'color': r['color'], 'order': r['ord']})
    for r in conn.execute('SELECT date,module_id,level FROM checkins ORDER BY date,module_id'):
        state['checkins'].setdefault(r['date'], {})[r['module_id']] = r['level']
    for r in conn.execute('SELECT date,minutes,note FROM habits ORDER BY date'):
        state['habits'][r['date']] = {'minutes': r['minutes'], 'note': r['note'] or ''}
    state['customFields'] = [dict(r) for r in conn.execute('SELECT key,label,type FROM custom_fields ORDER BY rowid')]
    for r in conn.execute('SELECT id,data FROM custom_records ORDER BY id'):
        data = json.loads(r['data'])
        if any(k in data for k in ('_record_id', '_client_id')):
            fail('state_conflict', '旧自定义记录含身份保留字段，请先核对，系统未覆盖原文。')
        state['customRecords'].append({**data, '_record_id': r['id']})
    state['todos'] = [dict(r) for r in conn.execute('SELECT id,date,title,done FROM todos ORDER BY rowid')]
    for table in ROW_FIELDS:
        state[table] = [dict(r) for r in conn.execute(f'SELECT * FROM {table} ORDER BY id')]
    state['_revision'] = digest(encoded(state))
    return state


def load_state(connect):
    with closing(connect()) as conn, conn:
        conn.execute('BEGIN')
        return read_state(conn)


def replace_rows(conn, table, rows, fields, strict):
    existing = {r[0] for r in conn.execute(f'SELECT id FROM {table}')}
    seen, assigned = set(), {}
    id_field = '_record_id' if table == 'custom_records' else 'id'
    # Validate IDs before allocating new ones, so a supplied ID cannot refer to
    # a row allocated earlier in this same request.
    for row in rows:
        identity = row.get(id_field)
        if identity is not None:
            if type(identity) is not int or not 0 < identity < 2**63 or identity in seen:
                fail('invalid', '记录编号无效或重复。', 422)
            if strict and identity not in existing:
                fail('state_conflict', '记录编号已失效，请保留本地修改后载入最新记录。')
            seen.add(identity)
    conn.executemany(f'DELETE FROM {table} WHERE id=?', ((identity,) for identity in existing - seen))
    for row in rows:
        identity = row.get(id_field)
        if table == 'custom_records':
            values = [encoded({k: v for k, v in row.items() if k not in ('_record_id', '_client_id')})]
        else:
            values = [row.get(k, None if k == 'probability' else '') for k in fields]
        columns = list(fields)
        if identity is not None:
            columns.insert(0, 'id')
            values.insert(0, identity)
        sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' * len(columns))})"
        if identity is not None:
            sql += ' ON CONFLICT(id) DO UPDATE SET ' + ','.join(f'{k}=excluded.{k}' for k in fields)
        cur = conn.execute(sql, values)
        client_id = row.get('_client_id')
        if client_id:
            if not isinstance(client_id, str) or len(client_id) > 100 or client_id in assigned:
                fail('invalid', '临时记录编号无效或重复。', 422)
            assigned[client_id] = identity if identity is not None else cur.lastrowid
    return assigned


def save_state(connect, state, *, require_revision=False):
    if not isinstance(state, dict):
        fail('invalid', '记录格式无效。', 422)
    if require_revision and not isinstance(state.get('_revision'), str):
        fail('state_conflict', '页面版本过旧，请先导出本地修改，再载入最新记录。')
    if require_revision and not REQUIRED.issubset(state):
        fail('invalid', '记录快照不完整，未保存。', 422)
    for key in REQUIRED - {'checkins', 'habits'}:
        if key in state and (not isinstance(state[key], list) or any(not isinstance(r, dict) for r in state[key])):
            fail('invalid', '记录列表格式无效，未保存。', 422)
    for key in ('checkins', 'habits'):
        if key in state and (not isinstance(state[key], dict) or any(not isinstance(v, dict) for v in state[key].values())):
            fail('invalid', '按日记录格式无效，未保存。', 422)
    try:
        with closing(connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            current = read_state(conn)
            if '_revision' in state and state['_revision'] != current['_revision']:
                fail('state_conflict', '其他页面或同步已更新记录；本地修改已保留，请核对后载入最新记录。')
            # Text/composite primary keys already carry stable identities.
            for table in ('modules', 'checkins', 'habits', 'custom_fields'):
                conn.execute(f'DELETE FROM {table}')
            for m in state.get('modules', []):
                conn.execute('INSERT INTO modules VALUES (?,?,?,?)',
                             (m['id'], m['name'], m.get('color', '#4F6EF7'), m.get('order', 0)))
            for date, modules in state.get('checkins', {}).items():
                for mid, level in modules.items():
                    conn.execute('INSERT INTO checkins VALUES (?,?,?)', (date, mid, int(level)))
            for date, habit in state.get('habits', {}).items():
                conn.execute('INSERT INTO habits VALUES (?,?,?)',
                             (date, int(habit.get('minutes', 0) or 0), habit.get('note', '')))
            for f in state.get('customFields', []):
                if f['key'] in ('_record_id', '_client_id'):
                    fail('invalid', '该字段名保留用于记录身份，请选择其他名称。', 422)
                conn.execute('INSERT INTO custom_fields VALUES (?,?,?)', (f['key'], f['label'], f['type']))
            if 'todos' in state:
                conn.execute('DELETE FROM todos')
                for todo in state['todos']:
                    conn.execute('INSERT INTO todos VALUES (?,?,?,?)',
                                 (todo['id'], todo['date'], todo['title'], int(bool(todo.get('done', False)))))
            assigned = {}
            for table, fields in ROW_FIELDS.items():
                assigned[table] = replace_rows(conn, table, state.get(table, []), fields, require_revision)
            assigned['customRecords'] = replace_rows(conn, 'custom_records', state.get('customRecords', []), ('data',), require_revision)
            return {'ok': True, 'state': read_state(conn), 'assigned_ids': assigned}
    except (KeyError, TypeError, ValueError, sqlite3.IntegrityError, sqlite3.ProgrammingError, sqlite3.DataError) as exc:
        fail('invalid', '记录快照字段无效，未保存：' + type(exc).__name__, 422)
