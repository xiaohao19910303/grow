"""Consented private-state mirror and restart-safe phone command delivery to Grow."""
import hashlib
import json
from fastapi import Request, HTTPException
import action_plans as actions
import mobile_library as library
import study_notes
from mobile_learning_questions import questions
from learning_actions import guard


def state(c):
    c.execute('CREATE TABLE IF NOT EXISTS action_mobile_private (id INTEGER PRIMARY KEY,data TEXT NOT NULL)')
    row=c.execute('SELECT data FROM action_mobile_private WHERE id=1').fetchone()
    return json.loads(row[0]) if row else {}


def put(c,value):
    c.execute('INSERT INTO action_mobile_private VALUES (1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(actions.encoded(value),))


def consent(enabled):
    if type(enabled) is not bool:actions.fail(422,'请明确私人学习授权范围。')
    with actions.connection(True,allow_link=True) as c:
        link,_=library.state(c);reading=library.table(c);bound=library.binding(link,reading)
        if not reading.get('enabled') or not bound.get('binding_id'):actions.fail(409,'请先连接并允许课程阅读。')
        old=state(c)
        if old.get('enabled')==enabled and old.get('binding_id')==bound['binding_id']:return
        put(c,{**old,'enabled':enabled,'binding_id':bound['binding_id'],'payload':None})


def catalog(store,materials):
    """Resolve trusted source identities, never accept filenames or users from phones."""
    with actions.connection() as c:published={l['id']:l for l in library.table(c).get('payload',{}).get('lessons',[])}
    result={}
    def add(identity,kind,course,body,refs,completed,completed_at,record=None):
        lid='lesson-'+hashlib.sha256(actions.encoded(identity).encode()).hexdigest()[:40]
        result[lid]=dict(id=lid,identity=identity,kind=kind,course=course,content=body,raw_version=hashlib.sha256(body.encode()).hexdigest(),content_version=hashlib.sha256(actions.encoded(dict(content=body,references=refs)).encode()).hexdigest(),completed=completed,completed_at=completed_at,record=record)
    if materials is not None:
        for item in materials.lessons('yingyu'):
            identity=dict(module='yingyu',filename=item['filename']);lid='lesson-'+hashlib.sha256(actions.encoded(identity).encode()).hexdigest()[:40];course=published.get(lid)
            if not course:continue
            record=materials.record('yingyu',item['filename'])
            add(identity,'yingyu',item['filename'],course['content'],'',item['learning_state']=='completed',record.get('completed_at') if record else None,record)
    for p in store.rows('learning_plans'):
        for item in store.lessons(p['id']):
            identity=dict(plan_id=p['id'],lesson_no=item['lesson_no']);lid='lesson-'+hashlib.sha256(actions.encoded(identity).encode()).hexdigest()[:40];c=published.get(lid)
            if not c:continue
            with store.conn() as db:
                feedback=db.execute('SELECT data FROM learning_feedback WHERE plan_id=? AND lesson_no=?',(p['id'],item['lesson_no'])).fetchone()
            feedback=json.loads(feedback[0]) if feedback else {}
            add(dict(plan_id=p['id'],lesson_no=item['lesson_no']),'plan',p['id']+'/'+str(item['lesson_no']),c['content'],c['references'],item.get('learning_state')=='completed',feedback.get('date') if feedback.get('state')=='completed' else None,feedback)
    return result


def snapshots(courses):
    study_notes.initialize()
    with actions.connection(True,allow_link=True) as c:
        saved=state(c);previous=saved.get('states',{});positions=saved.get('positions',{});output=[]
        for lid,course in courses.items():
            row=c.execute('SELECT * FROM course_study_notes WHERE kind=? AND course_id=?',(course['kind'],course['course'])).fetchone()
            notes=study_notes.public(row) or {};answers=notes.get('answers',{});fields=questions(course['content']);known={x['id'] for x in fields}
            for f in fields:f['answer']=answers.get(f['id'],'') if notes.get('version')==course['raw_version'] else ''
            fields.extend(dict(id=k,prompt='旧版或其他题目 · '+k[:300],answer=v) for k,v in answers.items() if k not in known or notes.get('version')!=course['raw_version'])
            # Do not duplicate an old answer under a current-version question ID.
            if notes.get('version') and notes['version']!=course['raw_version']:fields=[dict(id=k,prompt='旧版答案 · '+k[:300],answer=v) for k,v in answers.items()]
            if len(fields)>100:
                stored=[f for f in fields if f['id'] in answers];fields=stored+[f for f in fields if f['id'] not in answers][:max(0,100-len(stored))]
            pos=positions.get(lid,{})
            data=dict(id=lid,content_version=course['content_version'],draft_version=course['content_version'] if not notes or notes.get('version')==course['raw_version'] else notes['version'],questions=questions(course['content']),notes=notes.get('notes',course.get('record',{}).get('summary_text',course.get('record',{}).get('comment','')) if course.get('record') else ''),answers=fields,completed=course['completed'],completed_at=course['completed_at'],position=pos.get('position',0) if pos.get('version')==course['content_version'] else 0)
            fingerprint=hashlib.sha256(actions.encoded(data).encode()).hexdigest();old=previous.get(lid,{})
            value=old if old.get('fingerprint')==fingerprint else dict(**data,revision=old.get('revision',0)+1,updated_at=actions.clock().isoformat(),fingerprint=fingerprint)
            previous[lid]=value;output.append({k:v for k,v in value.items() if k!='fingerprint'})
        put(c,{**saved,'states':previous});return output


def apply(store,materials,command):
    if getattr(store,'remote',False):
        from action_handoff_coordinator import source_fence
        with source_fence(),store.lock():
            library.sync(store,materials)
            return _apply(store,materials,command,fenced=True)
    library.sync(store,materials)
    return _apply(store,materials,command)


def _apply(store,materials,command,fenced=False):
    key=command['id'];signature=hashlib.sha256(actions.encoded(command).encode()).hexdigest()
    with actions.connection(True,allow_link=True) as c:
        saved=state(c);journal=saved.setdefault('journal',{});old=journal.get(key)
        if old:
            if old['hash']!=signature:raise ValueError('Private command identity changed')
            if old.get('result'):return old['result']
        else:journal[key]={'hash':signature};put(c,saved)
    try:
        courses=catalog(store,materials);course=courses.get(command['lesson_id'])
        if not course or course['content_version']!=command['content_version']:raise HTTPException(409,'课程内容已更新，请保留输入并重新核对。')
        current=next(s for s in snapshots(courses) if s['id']==course['id'])
        with study_notes.connection() as c:note=c.execute('SELECT * FROM course_study_notes WHERE kind=? AND course_id=?',(course['kind'],course['course'])).fetchone()
        source_key='mobile-'+hashlib.sha256(key.encode()).hexdigest()
        own_save=note and note['request_key']==source_key
        own_finish=False
        if command['action']=='complete':
            if course['kind']=='yingyu':
                with study_notes.connection() as c:r=c.execute('SELECT request_key FROM study_learning_records WHERE module_id=? AND filename=?',('yingyu',course['course'])).fetchone()
                own_finish=bool(r and r[0]==source_key)
            else:
                with store.conn() as c:own_finish=bool(c.execute('SELECT 1 FROM action_content_events WHERE request_key=?',(source_key,)).fetchone())
        if current['revision']!=command['revision'] and not (own_save and command['action']=='save' or own_finish):raise HTTPException(409,'网页或另一设备已更新，请核对来源版本；手机输入已保留。')
        if command['action']=='save':
            study_notes.save(course['kind'],course['course'],study_notes.Draft(notes=command['notes'],answers={a['id']:a['answer'] for a in command['answers']},version=course['raw_version'],revision=note['revision'] if note and not own_save else max(0,(note['revision']-1) if note else 0),key=source_key))
        elif command['action']=='complete' and not own_finish and not course['completed']:
            if course['kind']=='yingyu':
                from study_materials import Completion
                record=course.get('record')
                actions.with_content_completion(materials.save('yingyu',course['course'],Completion(summary_text=record.get('summary_text','') if record else '',time_spent_seconds=0,version=course['raw_version'],revision=record.get('revision',0) if record else 0,key=source_key)),dict(kind='yingyu',course=course['course']))
            else:
                from action_content import confirm_source,_confirm_source
                target=dict(kind='plan',**course['identity']);data=dict(key=source_key,state='completed',comment=(course.get('record') or {}).get('comment',''))
                # The outer shared fence is already held; reacquiring on another DB session
                # can deadlock behind a queued exclusive handoff lock.
                confirm=_confirm_source if fenced else confirm_source
                confirm(store,target,data,lambda:store.feedback(course['identity']['plan_id'],course['identity']['lesson_no'],data,source_key))
        if command['action'] in ('save','position'):
            with actions.connection(True,allow_link=True) as c:
                saved=state(c);saved.setdefault('positions',{})[course['id']]=dict(version=course['content_version'],position=command['position']);put(c,saved)
        result=dict(id=key,status='applied',error='')
    except HTTPException as e:result=dict(id=key,status='conflict' if e.status_code==409 else 'unavailable',error=str(e.detail)[:500])
    except Exception as e:
        if getattr(e,'status',None) in (404,409,422):result=dict(id=key,status='conflict',error=str(getattr(e,'message','课程或学习状态已变化，请保留输入后核对。'))[:500])
        else:raise
    with actions.connection(True,allow_link=True) as c:
        saved=state(c);saved['journal'][key]['result']=result;put(c,saved)
    return result


def sync(store,materials=None):
    import db
    with db.connect() as c:
        if not c.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(current_schema() || ':mobile-private-sweep',0))").fetchone()[0]:return
        return _sync(store,materials)


def _sync(store,materials=None):
    with actions.connection() as c:
        saved=state(c);link,_=library.state(c);reading=library.table(c);bound=library.binding(link,reading)
    if saved.get('binding_id')!=bound.get('binding_id') or not saved.get('binding_id') or not reading.get('enabled'):return
    enabled=saved.get('enabled',False)
    if enabled:library.sync(store,materials)
    # Replay persisted exchange verbatim after response loss before preparing a new revision.
    def exchange(lessons,results):
        with actions.connection(True,allow_link=True) as c:
            latest=state(c)
            if latest.get('enabled',False)!=enabled or latest.get('binding_id')!=bound['binding_id']:return None
            payload=latest.get('payload')
            if not payload:
                payload=dict(action='learning-private',action_schema_version=2,binding_id=bound['binding_id'],source_revision=latest.get('source_revision',0)+1,enabled=enabled,lessons=lessons,results=results)
                latest.update(source_revision=payload['source_revision'],payload=payload);put(c,latest)
        receipt=library.call(library.identity(),payload)
        if receipt.get('accepted') is not True or receipt.get('binding_id')!=bound['binding_id'] or receipt.get('source_revision')!=payload['source_revision']:raise ValueError('Private receipt scope mismatch')
        with actions.connection(True,allow_link=True) as c:
            latest=state(c)
            if latest.get('payload')==payload:latest['payload']=None;put(c,latest)
        return receipt
    receipt=exchange(snapshots(catalog(store,materials)) if enabled else [],[])
    if not receipt or not enabled:return
    results=[]
    for command in receipt.get('requests',[]):
        with actions.connection() as c:current=state(c)
        if not current.get('enabled') or current.get('binding_id')!=bound['binding_id']:break
        results.append(apply(store,materials,command))
    if results:
        library.sync(store,materials)
        exchange(snapshots(catalog(store,materials)),results)


def register(app):
    @app.post('/api/mobile-learning/private-consent')
    async def authorize(request:Request):
        guard(request);body=await request.json()
        if not isinstance(body,dict) or set(body)!={'enabled','consent'} or body.get('consent') is not True:actions.fail(422,'请本人确认私人笔记、答案和显式学完范围。')
        consent(body['enabled']);return {'saved':True}
