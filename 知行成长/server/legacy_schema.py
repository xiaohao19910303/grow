"""Transactional PostgreSQL migration of early id/data tables. Never drops originals."""
import json
import re
from contextlib import closing

import db
from copilot.core import digest, encoded, fail, now

VERSION = 'legacy-cloud-v3'
LEDGER = '''
CREATE TABLE IF NOT EXISTS platform_migrations (id TEXT PRIMARY KEY,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS legacy_original_rows (source_table TEXT,source_key TEXT,raw TEXT NOT NULL,PRIMARY KEY(source_table,source_key));
CREATE TABLE IF NOT EXISTS legacy_row_map (
    source_table TEXT, source_key TEXT, target_table TEXT, target_key TEXT,
    state TEXT NOT NULL, raw TEXT NOT NULL, reason TEXT,
    PRIMARY KEY(source_table,source_key));
'''

# Required business columns distinguish the erroneous bootstrap schemas from real tables.
REQUIRED = {
 'copilot_settings':'key value', 'copilot_meta':'key value',
 'copilot_lessons':'module_id round_id lesson_no data',
 'copilot_learning_records':'id module_id round_id lesson_no completion_type review_answers summary_text time_spent_seconds scroll_depth completed_at idempotency_key',
 'copilot_drafts':'id lesson_no version status data updated_at',
 'copilot_generation_attempts':'id request_key request_hash draft_id status data',
 'copilot_operations':'id request_key request_hash status data created_at',
 'reading_records':'id data',
 'reading_vocabulary':'id word normalized article_id source_version context_sentence contextual_meaning part_of_speech pronunciation step next_review paused archived created_at updated_at data',
 'reading_reviews':'id vocab_id feedback step_before step_after reviewed_at',
 'reflection_versions':'key data',
 'behavior_applications':'id date module_id concept scenario effectiveness created_at',
 'error_records':'id date module_id error_type description severity context improvement_action is_repeat related_error_id created_at',
 'error_types':'id name description created_at',
 'behavior_reports':'id date period_days content data_summary created_at',
 'knowledge_links':'id source_id target_id link_type weight',
}
SERIAL = {'copilot_learning_records','reading_reviews','behavior_applications','error_records','error_types','behavior_reports','knowledge_links','knowledge','predictions'}
EXTRA = '''
CREATE TABLE IF NOT EXISTS knowledge (id BIGSERIAL PRIMARY KEY,name TEXT,category TEXT,summary TEXT,source TEXT,kind TEXT,date TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS predictions (id BIGSERIAL PRIMARY KEY,date TEXT,statement TEXT,probability INTEGER,result TEXT,deviation TEXT);
'''


def columns(c, table):
    return {r[0]:r[1] for r in c.execute("SELECT column_name,data_type FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=?",(table,))}


def schemas():
    from platform_schema import TABLES as dashboard
    from plans.store import TABLES as plans
    from copilot.schema import TABLES as copilot
    from reading.schema import TABLES as reading
    from reflections.store import TABLES as reflections
    from behavior.store import TABLE_SQL as behavior
    from errors.store import TABLE_SQL as errors
    from behavior_report.store import TABLE_SQL as reports
    from knowledge.store import TABLE_SQL as links
    from stocks.store import TABLES as stocks
    return [dashboard,EXTRA,plans,copilot,reading,reflections,stocks,behavior,errors,reports,links]


def payload(row):
    raw = row.get('data')
    if raw is None:return dict(row)
    value = json.loads(raw) if isinstance(raw,str) else raw
    if not isinstance(value,dict):raise ValueError('not_object')
    return {**value, **{k:v for k,v in row.items() if k!='data'}}


def converted(table, row, ids):
    if table in ('copilot_meta','copilot_settings'):
        key = row.get('key',row.get('id'))
        return {'key':key, 'value':row.get('value',row.get('data'))}
    d = payload(row)
    if table == 'reflection_versions':
        return {'key':f"{d['entry_id']}#{d['version']}", 'data':row['data']}
    if table == 'copilot_lessons':
        return {'module_id':d.get('module_id','renzhi'),'round_id':d.get('round_id',1),'lesson_no':int(d['lesson_no']),'data':row['data']}
    if table == 'copilot_learning_records':
        if not d.get('completed_at'):raise ValueError('missing_completion_evidence')
        d.setdefault('completion_type','manual');d.setdefault('module_id','renzhi');d.setdefault('round_id',1)
        d.setdefault('time_spent_seconds',0);d.setdefault('idempotency_key','legacy-'+digest(encoded(row)))
    if table == 'copilot_drafts':
        d.setdefault('version',1);d.setdefault('status','failed');d.setdefault('updated_at',now())
        if d['status']=='generating':d['status']='failed'
    if table in ('copilot_generation_attempts','copilot_operations'):
        d.setdefault('request_key',str(d['id']));d.setdefault('request_hash',digest(encoded(row)))
        d.setdefault('status','failed' if table=='copilot_generation_attempts' else 'prepared')
        if table=='copilot_generation_attempts':
            d.setdefault('draft_id',d['id'])
            if d['status']=='generating':d['status']='failed'
        else:d.setdefault('created_at',now())
    if table == 'reading_vocabulary':
        d['normalized'] = d.get('normalized') or d['word'].strip().lower()
        for key,value in {'source_version':1,'step':0,'paused':0,'archived':0,'created_at':now(),'updated_at':now()}.items():d.setdefault(key,value)
    if table == 'reading_reviews':
        d.setdefault('reviewed_at',now())
    if table in ('behavior_applications','error_records'):
        d['date'] = d.get('date') or d.get('dt')
        d.setdefault('module_id','renzhi')
    if table in ('behavior_applications','error_records','error_types','behavior_reports'):
        d.setdefault('created_at',now())
    if table == 'error_records' and d.get('related_error_id') is not None:
        d['related_error_id'] = ids['error_records'].get(str(d['related_error_id']))
        if d['related_error_id'] is None:raise ValueError('missing_related_error')
    if table == 'knowledge_links':
        for key in ('source_id','target_id'):
            value=str(d[key]);d[key]=ids.get('knowledge_nodes',{}).get(value,d[key])
    if table in SERIAL:d['id'] = ids[table][str(row.get('id',row.get('lesson_no')))]
    # JSON envelope columns retain the entire original payload as well as business fields.
    if 'data' in REQUIRED.get(table,'').split():d['data']=row.get('data',encoded(d))
    return d


def migrate(connection=None):
    """One schema, one transaction. Unsupported rows remain archived and reportable."""
    if connection is None:
        with closing(db.connect()) as c, c:return migrate(c)
    c=connection
    schema=c.execute('SELECT current_schema()').fetchone()[0]
    c.execute('SELECT pg_advisory_xact_lock(?)',(int(digest(schema+':'+VERSION)[:15],16),))
    c.executescript(LEDGER)
    old=c.execute('SELECT data FROM platform_migrations WHERE id=?',(VERSION,)).fetchone()
    if old:return json.loads(old[0])
    # Credentials are not migration records, and must not be copied to the archive.
    from copilot.ai_config import remove_server_config
    remove_server_config(c)
    original_tables=sorted(set(REQUIRED)|set('modules checkins habits custom_fields custom_records todos decisions predictions reviews insights knowledge knowledge_nodes prediction_records reflection_entries reflection_ai_attempts reflection_operations stock_records'.split()))
    original_tables=[table for table in original_tables if columns(c,table)]
    if original_tables:c.execute('LOCK TABLE '+','.join(original_tables)+' IN SHARE ROW EXCLUSIVE MODE')
    original_count=0
    for table in original_tables:
        for index,row in enumerate(c.execute(f'SELECT * FROM {table}').fetchall()):
            raw=json.dumps(dict(row),ensure_ascii=False,sort_keys=True,default=str)
            c.execute('INSERT INTO legacy_original_rows VALUES (?,?,?)',(table,digest(raw)+':'+str(index),raw))
            original_count+=1
    archives={}
    for table,required in REQUIRED.items():
        found=columns(c,table)
        if found and (not set(required.split())<=set(found) or (table in SERIAL and found.get('id') not in ('integer','bigint'))):
            archive=table+'__legacy_v3'
            if columns(c,archive):fail('migration_conflict','发现已有旧表归档，请核对迁移日志：'+table)
            c.execute(f'ALTER TABLE {table} RENAME TO {archive}')
            archives[table]=archive
    for ddl in schemas():
        c.executescript(re.sub(r'\bSERIAL\b','BIGSERIAL',ddl))
    for source,target in (('knowledge_nodes','knowledge'),('prediction_records','predictions')):
        if columns(c,source):archives[source]=source
    rows={table:[dict(r) for r in c.execute(f'SELECT * FROM {archive}')] for table,archive in archives.items()}
    ids={}
    for source,items in rows.items():
        target={'knowledge_nodes':'knowledge','prediction_records':'predictions'}.get(source,source)
        if target not in SERIAL:continue
        used={r[0] for r in c.execute(f'SELECT id FROM {target}')}
        numeric={int(str(r.get('id',r.get('lesson_no')))) for r in items if str(r.get('id',r.get('lesson_no'))).isdigit() and 0<int(str(r.get('id',r.get('lesson_no'))))<2**63}
        last=max(used|numeric|{0});mapping={}
        for row in items:
            key=str(row.get('id',row.get('lesson_no')))
            value=int(key) if key.isdigit() and 0<int(key)<2**63 and int(key) not in used else last+1
            last=max(last,value);used.add(value);mapping[key]=value
        ids[source]=mapping
        ids.setdefault(target,mapping)
    deferred=[]
    report={'id':VERSION,'created_at':now(),'archives':archives,'imported':0,'needs_review':0,'tables':{},'original_rows_preserved':original_count}
    order=sorted(rows,key=lambda t:({'error_types':0,'error_records':1,'knowledge_nodes':0,'knowledge_links':2,'reading_vocabulary':0,'reading_reviews':1}.get(t,0),t))
    for source in order:
        target={'knowledge_nodes':'knowledge','prediction_records':'predictions'}.get(source,source)
        target_columns=columns(c,target)
        imported=0
        for row in rows[source]:
            identity=str(row.get('id',row.get('lesson_no',encoded({k:v for k,v in row.items() if k!='data'}))))
            raw=encoded(row);state='imported';reason=None;new_key=None
            c.execute('SAVEPOINT legacy_row')
            try:
                data=converted(target,row,ids)
                if source in ('knowledge_nodes','prediction_records'):
                    data=payload(row);data['id']=ids[source][str(row['id'])]
                data={k:v for k,v in data.items() if k in target_columns}
                # None does not override canonical defaults.
                data={k:(encoded(v) if isinstance(v,(dict,list)) else v) for k,v in data.items() if v is not None}
                related=data.pop('related_error_id',None) if target=='error_records' else None
                names=list(data)
                c.execute(f"INSERT INTO {target} ({','.join(names)}) VALUES ({','.join('?' for _ in names)})",[data[k] for k in names])
                new_key=str(data.get('id',data.get('key',data.get('lesson_no'))));imported+=1
                if related is not None:deferred.append((source,identity,int(new_key),related))
            except (ValueError,KeyError,TypeError,db.psycopg2.Error):
                c.execute('ROLLBACK TO SAVEPOINT legacy_row')
                state='needs_review';reason='原行缺少必填字段、关联或与现有记录冲突；原文已保留。'
            finally:c.execute('RELEASE SAVEPOINT legacy_row')
            c.execute('INSERT INTO legacy_row_map VALUES (?,?,?,?,?,?,?)',(source,identity,target,new_key,state,raw,reason))
            report['imported' if state=='imported' else 'needs_review']+=1
        report['tables'][source]={'total':len(rows[source]),'imported':imported,'needs_review':len(rows[source])-imported}
    for source,identity,child,parent in deferred:
        if c.execute('SELECT 1 FROM error_records WHERE id=?',(parent,)).fetchone():
            c.execute('UPDATE error_records SET related_error_id=? WHERE id=?',(parent,child))
        else:
            c.execute("UPDATE legacy_row_map SET state='needs_review',reason=? WHERE source_table=? AND source_key=?",('关联原行无法导入，原关系保存在归档中。',source,identity))
            report['needs_review']+=1;report['imported']-=1
            report['tables'][source]['needs_review']+=1;report['tables'][source]['imported']-=1
    # Explicit imported IDs must advance, rather than reset, each serial sequence.
    for table in SERIAL:
        if not columns(c,table):continue
        seq=c.execute('SELECT pg_get_serial_sequence(?,?)',(table,'id')).fetchone()[0]
        if not seq and columns(c,table).get('id') in ('integer','bigint'):
            c.execute(f'ALTER TABLE {table} ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY')
            seq=c.execute('SELECT pg_get_serial_sequence(?,?)',(table,'id')).fetchone()[0]
        if seq:
            maximum=c.execute(f'SELECT COALESCE(MAX(id),0) FROM {table}').fetchone()[0]
            c.execute('SELECT setval(?, GREATEST(?,nextval(?)), true)',(seq,maximum,seq))
    c.execute('INSERT INTO platform_migrations VALUES (?,?)',(VERSION,encoded(report)))
    return report
