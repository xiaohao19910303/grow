"""旧模块数据流转：兼容全量读取/PUT，模块级增量保存只更新实际变化的记录。"""
import json
import db
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
    state['customFields'] = [dict(r) for r in conn.execute('SELECT key,label,type FROM custom_fields ORDER BY key')]
    for r in conn.execute('SELECT id,data FROM custom_records ORDER BY id'):
        data = json.loads(r['data'])
        if any(k in data for k in ('_record_id', '_client_id')):
            fail('state_conflict', '旧自定义记录含身份保留字段，请先核对，系统未覆盖原文。')
        state['customRecords'].append({**data, '_record_id': r['id']})
    state['todos'] = [dict(r) for r in conn.execute('SELECT id,date,title,done FROM todos ORDER BY date,id')]
    for table in ROW_FIELDS:
        state[table] = [dict(r) for r in conn.execute(f'SELECT * FROM {table} ORDER BY id')]
    state['_revision'] = digest(encoded(state))
    # 全量修订保持旧算法；模块修订用于独立保存，不把新模块纳入旧写入范围。
    state['_section_revisions'] = {key: digest(encoded(state[key])) for key in REQUIRED}
    return state


def load_state(connect):
    with closing(connect()) as conn, conn:
        conn.execute('BEGIN' if isinstance(conn, sqlite3.Connection) else 'BEGIN ISOLATION LEVEL REPEATABLE READ')
        return read_state(conn)


def replace_rows(conn, table, rows, fields, strict):
    stored = {r['id']: tuple(r[k] for k in fields) for r in conn.execute(f"SELECT id,{','.join(fields)} FROM {table}")}
    existing = set(stored)
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
        changed = stored.get(identity) != tuple(values)
        if table == 'custom_records' and identity in stored:
            changed = json.loads(stored[identity][0]) != json.loads(values[0])
        columns = list(fields)
        if identity is not None:
            columns.insert(0, 'id')
            values.insert(0, identity)
        sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' * len(columns))})"
        if identity is not None:
            sql += ' ON CONFLICT(id) DO UPDATE SET ' + ','.join(f'{k}=excluded.{k}' for k in fields)
        cur = conn.execute(sql, values) if identity not in existing or changed else None
        client_id = row.get('_client_id')
        if client_id:
            if not isinstance(client_id, str) or len(client_id) > 100 or client_id in assigned:
                fail('invalid', '临时记录编号无效或重复。', 422)
            assigned[client_id] = identity if identity is not None else cur.lastrowid
    return assigned


def validate_sections(state, keys):
    for key in keys:
        value = state[key]
        if key in ('checkins', 'habits'):
            valid = isinstance(value, dict) and all(isinstance(v, dict) for v in value.values())
        else:
            valid = isinstance(value, list) and all(isinstance(v, dict) for v in value)
        if not valid: fail('invalid', '记录格式无效，未保存。', 422)


def lock_state(conn):
    if isinstance(conn, sqlite3.Connection): conn.execute('BEGIN IMMEDIATE')
    else:
        # 与旧 PUT 及直接 SQL 写入共用锁次序，校验和差异写入在同一事务内。
        conn.execute('LOCK TABLE modules,checkins,habits,custom_fields,custom_records,todos,decisions,predictions,reviews,insights IN EXCLUSIVE MODE')


def replace_keyed(conn, table, rows, keys, fields):
    """自然主键记录不再清表重建；未变化的行不执行更新。"""
    stored = {tuple(r[k] for k in keys): tuple(r[k] for k in fields)
              for r in conn.execute(f"SELECT {','.join(keys + fields)} FROM {table}")}
    desired = {}
    for row in rows:
        # 兼容旧导入对 TEXT 主键传入数字的方式，避免差异比较误判成删除再新增。
        identity = tuple(str(row[k]) if type(row[k]) in (int, float) else row[k] for k in keys)
        if any(not isinstance(v, str) for v in identity) or identity in desired:
            fail('invalid', '记录身份无效或重复，未保存。', 422)
        desired[identity] = tuple(row[k] for k in fields)
    where = ' AND '.join(k + '=?' for k in keys)
    for identity in stored.keys() - desired.keys():
        conn.execute(f'DELETE FROM {table} WHERE {where}', identity)
    for identity, values in desired.items():
        if identity not in stored:
            columns = keys + fields
            conn.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", identity + values)
        elif values != stored[identity]:
            conn.execute(f"UPDATE {table} SET {','.join(k+'=?' for k in fields)} WHERE {where}", values + identity)


def save_section(conn, key, value, strict):
    if key in ROW_FIELDS:
        return replace_rows(conn, key, value, ROW_FIELDS[key], strict)
    if key == 'customRecords':
        return replace_rows(conn, 'custom_records', value, ('data',), strict)
    if key == 'modules':
        rows = [{'id': r['id'], 'name': r['name'], 'color': r.get('color', '#4F6EF7'), 'ord': r.get('order', 0)} for r in value]
        replace_keyed(conn, 'modules', rows, ('id',), ('name', 'color', 'ord'))
    elif key == 'checkins':
        rows = [{'date': day, 'module_id': mid, 'level': int(level)} for day, modules in value.items() for mid, level in modules.items()]
        replace_keyed(conn, 'checkins', rows, ('date', 'module_id'), ('level',))
    elif key == 'habits':
        rows = [{'date': day, 'minutes': int(r.get('minutes', 0) or 0), 'note': r.get('note', '')} for day, r in value.items()]
        replace_keyed(conn, 'habits', rows, ('date',), ('minutes', 'note'))
    elif key == 'customFields':
        if any(r['key'] in ('_record_id', '_client_id') for r in value):
            fail('invalid', '该字段名保留用于记录身份，请选择其他名称。', 422)
        replace_keyed(conn, 'custom_fields', value, ('key',), ('label', 'type'))
    elif key == 'todos':
        rows = [{**r, 'done': int(bool(r.get('done', False)))} for r in value]
        replace_keyed(conn, 'todos', rows, ('id',), ('date', 'title', 'done'))
    return {}


INVALID_FIELDS = (KeyError, TypeError, ValueError, sqlite3.IntegrityError,
                  db.IntegrityError, db.ProgrammingError, db.DataError,
                  db.psycopg2.IntegrityError, db.psycopg2.ProgrammingError, db.psycopg2.DataError)


def save_state(connect, state, *, require_revision=False):
    """旧 PUT 保留全量修订保护及显式清空语义，数据库同样使用差异写入。"""
    if not isinstance(state, dict): fail('invalid', '记录格式无效。', 422)
    if require_revision and not isinstance(state.get('_revision'), str):
        fail('state_conflict', '页面版本过旧，请先导出本地修改，再载入最新记录。')
    if require_revision and not REQUIRED.issubset(state):
        fail('invalid', '记录快照不完整，未保存。', 422)
    validate_sections(state, REQUIRED.intersection(state))
    try:
        with closing(connect()) as conn, conn:
            lock_state(conn)
            current = read_state(conn)
            if '_revision' in state and state['_revision'] != current['_revision']:
                fail('state_conflict', '其他页面或同步已更新记录；本地修改已保留，请核对后载入最新记录。')
            assigned = {}
            for key in sorted(REQUIRED):
                if key == 'todos' and key not in state: continue
                value = state.get(key, {} if key in ('checkins', 'habits') else [])
                identities = save_section(conn, key, value, require_revision)
                if key in ROW_FIELDS or key == 'customRecords': assigned[key] = identities
            return {'ok': True, 'state': read_state(conn), 'assigned_ids': assigned}
    except INVALID_FIELDS as exc:
        fail('invalid', '记录快照字段无效，未保存：' + type(exc).__name__, 422)


def initialize_requests(conn):
    if isinstance(conn, sqlite3.Connection):
        present = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='legacy_state_requests'").fetchone()
    else:
        present = conn.execute("SELECT to_regclass('legacy_state_requests')").fetchone()[0]
    if not present:
        # 调用方已取得旧模块写锁；账号内加法建表，完整数据库备份会自动覆盖。
        conn.execute('CREATE TABLE legacy_state_requests (key TEXT PRIMARY KEY, request_hash TEXT NOT NULL, response TEXT NOT NULL)')


def patch_state(connect, request):
    """模块增量保存：范围显式、模块版本匹配、同请求重放只返回原回执。"""
    if not isinstance(request, dict) or set(request) != {'key', 'changes', 'base_revisions'}:
        fail('invalid', '增量保存格式无效，未保存。', 422)
    key, changes, versions = (request[k] for k in ('key', 'changes', 'base_revisions'))
    if not isinstance(key, str) or not 8 <= len(key) <= 160 or any(ord(c) < 32 for c in key):
        fail('invalid', '保存请求编号无效。', 422)
    if not isinstance(changes, dict) or not changes or not set(changes).issubset(REQUIRED):
        fail('invalid', '保存范围无效，未保存。', 422)
    if not isinstance(versions, dict) or set(versions) != set(changes) or any(not isinstance(v, str) for v in versions.values()):
        fail('invalid', '模块版本缺失，未保存。', 422)
    validate_sections(changes, changes)
    fingerprint = digest(encoded(request))
    try:
        with closing(connect()) as conn, conn:
            lock_state(conn)
            initialize_requests(conn)
            old = conn.execute('SELECT request_hash,response FROM legacy_state_requests WHERE key=?', (key,)).fetchone()
            if old:
                if old[0] != fingerprint: fail('request_conflict', '相同请求编号不能替换保存内容。')
                return json.loads(old[1])
            current = read_state(conn)
            if any(current['_section_revisions'][k] != versions[k] for k in changes):
                fail('state_conflict', '本次修改的模块已被其他页面或同步更新；本地修改保留，请核对后重新读取。')
            assigned = {}
            for name in sorted(changes):
                if name in ROW_FIELDS or name == 'customRecords':
                    field = '_record_id' if name == 'customRecords' else 'id'
                    if any(r.get(field) is None and not r.get('_client_id') for r in changes[name]):
                        fail('invalid', '新增记录缺少临时身份，未保存。', 422)
                identities = save_section(conn, name, changes[name], True)
                if name in ROW_FIELDS or name == 'customRecords': assigned[name] = identities
            saved = read_state(conn)
            # 回执只保留修订和身份映射，不再为每次自动保存复制全部私人原文。
            result = {'ok': True, '_revision': saved['_revision'],
                      '_section_revisions': saved['_section_revisions'], 'assigned_ids': assigned}
            conn.execute('INSERT INTO legacy_state_requests VALUES (?,?,?)', (key, fingerprint, encoded(result)))
            return result
    except INVALID_FIELDS as exc:
        fail('invalid', '记录快照字段无效，未保存：' + type(exc).__name__, 422)
