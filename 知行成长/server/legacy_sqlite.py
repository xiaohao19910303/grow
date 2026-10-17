"""Read-only SQLite snapshot import into PostgreSQL, retaining every source row."""
import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import db
from copilot.core import digest, encoded, fail, now
from copilot.ai_config import SERVER_AI_KEYS
from legacy_schema import columns, migrate, SERIAL

KEYS={
 'modules':('id',),'checkins':('date','module_id'),'habits':('date',),'custom_fields':('key',),
 'custom_records':('id',),'todos':('id',),'decisions':('id',),'predictions':('id',),'reviews':('id',),'insights':('id',),'knowledge':('id',),
 'copilot_settings':('key',),'copilot_meta':('key',),'copilot_lessons':('module_id','round_id','lesson_no'),
 'copilot_learning_records':('module_id','round_id','lesson_no'),'copilot_drafts':('id',),
 'copilot_generation_attempts':('id',),'copilot_operations':('id',),'reading_records':('id',),
 'reading_vocabulary':('id',),'reading_reviews':('id',),'reflection_entries':('id',),'reflection_versions':('key',),
 'reflection_ai_attempts':('id',),'reflection_operations':('id',),'stock_records':('id',),
 'behavior_applications':('id',),'error_records':('id',),'error_types':('id',),'behavior_reports':('id',),'knowledge_links':('id',),
}
TABLES='''
CREATE TABLE IF NOT EXISTS sqlite_imports (id TEXT PRIMARY KEY,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sqlite_source_rows (
 source_id TEXT, source_table TEXT, source_key TEXT, state TEXT, raw TEXT NOT NULL,
 PRIMARY KEY(source_id,source_table,source_key));
'''


def snapshot(path):
    path=Path(path).absolute()
    if path.is_symlink() or not path.is_file():fail('migration_source','SQLite 来源必须是已有的普通文件。')
    result={}
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as c:
        c.row_factory=sqlite3.Row;c.execute('BEGIN')
        found={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in KEYS:
            if table not in found:continue
            rows=[dict(row) for row in c.execute(f'SELECT * FROM {table}')]
            if table=='copilot_settings':rows=[r for r in rows if r.get('key',r.get('id')) not in SERVER_AI_KEYS]
            result[table]=sorted(rows,key=encoded)
    return result


def equivalent(left,right):
    if isinstance(left,str) and isinstance(right,str):
        try:return json.loads(left)==json.loads(right)
        except ValueError:pass
    return left==right


def inspect(c,source,path):
    actions=[];counts={'missing':0,'same':0,'retained_remote':0,'archived_only':0};hashes={};node_ids={};planned={}
    link_ids={r[0] for r in c.execute('SELECT id FROM knowledge_links')};next_link=max(link_ids|{0})
    # Scanner-assigned knowledge IDs are not stable identities. Match their source,
    # kind and name, preserving both distinct nodes and existing graph references.
    used={r[0] for r in c.execute('SELECT id FROM knowledge')};next_id=max(used|{0})
    for row in source.get('knowledge',[]):
        match=c.execute("SELECT id FROM knowledge WHERE name=? AND COALESCE(source,'')=? AND COALESCE(kind,'')=? ORDER BY id LIMIT 1",(row.get('name'),row.get('source') or '',row.get('kind') or '')).fetchone()
        if match:value=match[0]
        elif row['id'] not in used:value=row['id']
        else:value=next_id+1
        node_ids[row['id']]=value;used.add(value);next_id=max(next_id,value)
    for table,rows in source.items():
        target_columns=columns(c,table)
        keys=KEYS[table]
        for row in rows:
            identity=encoded({k:row.get(k) for k in keys});candidate=dict(row)
            if table=='knowledge':candidate['id']=node_ids[row['id']]
            if table=='knowledge_links':
                candidate['source_id']=node_ids.get(row.get('source_id'),row.get('source_id'))
                candidate['target_id']=node_ids.get(row.get('target_id'),row.get('target_id'))
                edge=c.execute('SELECT id FROM knowledge_links WHERE source_id=? AND target_id=? AND link_type=?',(candidate['source_id'],candidate['target_id'],candidate.get('link_type','related'))).fetchone()
                if edge:candidate['id']=edge[0]
                elif candidate['id'] in link_ids:candidate['id']=next_link+1
                link_ids.add(candidate['id']);next_link=max(next_link,candidate['id'])
            if not target_columns or not all(k in candidate for k in keys):
                state='archived_only';target=None
            else:
                target=c.execute(f"SELECT * FROM {table} WHERE "+' AND '.join(k+'=?' for k in keys),[candidate[k] for k in keys]).fetchone()
                target=dict(target) if target else None
                if target is None:state='missing'
                elif all(equivalent(target.get(k),value) for k,value in candidate.items() if k in target_columns):state='same'
                else:state='retained_remote'
            counts[state]+=1;hashes[table+':'+identity]=digest(encoded(target)) if target is not None else None
            planned[table+':'+identity]=digest(encoded(candidate))
            actions.append((table,identity,row,state,candidate))
    material={'source_root':str(Path(path).resolve()),'source':source,'target':hashes,'knowledge_id_map':node_ids,'planned':planned}
    return {'token':digest(encoded(material)),'source_rows':len(actions),'counts':counts,'source_preserved':True,'knowledge_id_map':{str(k):v for k,v in node_ids.items()}},actions


def preview(path):
    source=snapshot(path)
    with closing(db.connect()) as c,c:return inspect(c,source,path)[0]


def apply(path,token):
    source=snapshot(path)
    with closing(db.connect()) as c,c:
        schema=c.execute('SELECT current_schema()').fetchone()[0]
        for identity in sorted({int(digest(name)[:15],16) for name in ('learning-plan-publications',schema+':learning-plan-publications')}):
            c.execute('SELECT pg_advisory_xact_lock(?)',(identity,))
        c.executescript(TABLES)
        old=c.execute('SELECT data FROM sqlite_imports WHERE id=?',(token,)).fetchone()
        if old:return json.loads(old[0])
        target_columns={table:columns(c,table) for table in source}
        present=[table for table in source if target_columns[table]]
        if present:c.execute('LOCK TABLE '+','.join(present)+' IN SHARE ROW EXCLUSIVE MODE')
        report,actions=inspect(c,source,path)
        if report['token']!=token:fail('migration_changed','预览后 SQLite 或远端记录已变化，请重新预览。')
        report.update(id=token,created_at=now(),imported=0,archived=0,needs_review=0)
        for table,identity,row,state,candidate in actions:
            if state=='missing':
                data={k:v for k,v in candidate.items() if k in target_columns[table]}
                # Interruptions are retained as history, never resumed as model calls.
                if table=='copilot_drafts' and data.get('status')=='generating':data['status']='failed'
                if table=='copilot_generation_attempts' and data.get('status')=='generating':data['status']='failed'
                if table in ('reading_records','reflection_ai_attempts'):
                    try:
                        obj=json.loads(data['data'])
                        field='state' if table=='reading_records' else 'status'
                        if obj.get(field) in ('queued','running','generating'):
                            obj.update({field:'failed','error':'从 SQLite 迁移的未完成任务，不会自动调用模型。'})
                            data['data']=encoded(obj)
                        if obj.get('type')=='export' and obj.get('state')=='pending':state='archived_only'
                    except (ValueError,TypeError):state='archived_only'
                if table in ('copilot_operations','reflection_operations'):
                    pending = data.get('status') not in (None,'done')
                    try:pending = pending or json.loads(data.get('data','{}')).get('state')=='pending'
                    except ValueError:pending=True
                    if pending:state='archived_only'
                if state=='missing':
                    c.execute('SAVEPOINT sqlite_row')
                    try:
                        names=list(data)
                        c.execute(f"INSERT INTO {table} ({','.join(names)}) VALUES ({','.join('?' for _ in names)})",[data[k] for k in names])
                        report['imported']+=1;state='imported'
                    except db.psycopg2.Error:
                        c.execute('ROLLBACK TO SAVEPOINT sqlite_row');state='archived_only'
                    finally:c.execute('RELEASE SAVEPOINT sqlite_row')
            c.execute('INSERT INTO sqlite_source_rows VALUES (?,?,?,?,?)',(token,table,identity,state,encoded(row)))
            report['archived']+=1
            if state=='archived_only':report['needs_review']+=1
        for table in SERIAL|{'decisions','reviews','insights','custom_records'}:
            if not columns(c,table):continue
            seq=c.execute('SELECT pg_get_serial_sequence(?,?)',(table,'id')).fetchone()[0]
            if seq:
                maximum=c.execute(f'SELECT COALESCE(MAX(id),0) FROM {table}').fetchone()[0]
                c.execute('SELECT setval(?,GREATEST(?,nextval(?)),true)',(seq,maximum,seq))
        c.execute('INSERT INTO sqlite_imports VALUES (?,?)',(token,encoded(report)))
        return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('source',type=Path);parser.add_argument('--apply-token')
    args=parser.parse_args();migrate()
    result=apply(args.source,args.apply_token) if args.apply_token else preview(args.source)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
