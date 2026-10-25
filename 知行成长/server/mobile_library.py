"""Explicitly consented published-course mirror; never includes private answers."""
import hashlib
import json
from fastapi import Request
import action_plans as actions
from action_link import state,identity,call
import os
import uuid
from learning_actions import guard
from mobile_progress import source_url


def table(c):
    c.execute('CREATE TABLE IF NOT EXISTS action_mobile_reading (id INTEGER PRIMARY KEY,data TEXT NOT NULL)')
    row=c.execute('SELECT data FROM action_mobile_reading WHERE id=1').fetchone()
    return json.loads(row[0]) if row else {}


def put(c,value):
    c.execute('INSERT INTO action_mobile_reading VALUES (1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(actions.encoded(value),))


def binding(link,value):
    if link.get('phase')=='active' and link.get('snapshot_version')==2:return link
    return value.get('reading_binding',{})


def status():
    with actions.connection() as c:
        link,_=state(c);value=table(c);current=binding(link,value)
    return {'available':bool(source_url() and os.getenv('LIGHTTICK_BRIDGE_URL') and os.getenv('GROW_ACTION_BRIDGE_SECRET')),
            'connected':bool(current.get('binding_id')),
            'enabled':value.get('enabled',False) and value.get('binding_id')==current.get('binding_id'),
            'pending':bool(value.get('payload') and not value.get('delivered')),
            'private_enabled':private_status(current)}


def private_status(current):
    from mobile_private import state as private_state
    with actions.connection() as c:saved=private_state(c)
    return bool(saved.get('enabled') and saved.get('binding_id')==current.get('binding_id'))


def consent(enabled):
    if type(enabled) is not bool:actions.fail(422,'请明确选择是否允许课程阅读。')
    with actions.connection(True,allow_link=True) as c:
        link,_=state(c);value=table(c);current=binding(link,value)
        if not current.get('binding_id') or not source_url():actions.fail(409,'请先用连接码建立只读课程连接。')
        if value.get('enabled')==enabled and value.get('binding_id')==current['binding_id']:return
        value={**value,'enabled':enabled,'binding_id':current['binding_id'],'signature':None,'delivered':False}
        put(c,value)
        if not enabled:
            from mobile_private import state as private_state,put as private_put
            private_value=private_state(c);private_put(c,{**private_value,'enabled':False,'payload':None})


def preview(code):
    target=call(identity(),dict(action='preview',code=code))
    if target.get('action_schema_version')!=2 or target.get('v2_import_enabled') is not True:actions.fail(409,'连接服务尚未开放此版本，请保留现有课程。')
    proposed={'preview_id':str(uuid.uuid4()),'code_hash':hashlib.sha256(code.encode()).hexdigest(),'target_user_id':target['target_user_id'],'expires_at':target['expires_at']}
    with actions.connection(True,allow_link=True) as c:
        value=table(c);put(c,{**value,'reading_preview':proposed})
    return {k:v for k,v in proposed.items() if k!='code_hash'}


def connect(code,preview_id):
    if not source_url():actions.fail(409,'尚未配置可信 Grow 公开地址。')
    with actions.connection() as c:proposed=table(c).get('reading_preview',{})
    if proposed.get('preview_id')!=preview_id or proposed.get('code_hash')!=hashlib.sha256(code.encode()).hexdigest():actions.fail(409,'请重新验证连接码并核对目标账户。')
    source=identity();target=call(source,dict(action='preview',code=code))
    if target.get('target_user_id')!=proposed.get('target_user_id'):actions.fail(409,'目标账户已变化，请重新核对。')
    claimed=call(source,dict(action='claim',code=code))
    if claimed.get('userId')!=target.get('target_user_id'):actions.fail(409,'目标账户已变化，请重新核对。')
    with actions.connection(True,allow_link=True) as c:
        value=table(c);put(c,{**value,'reading_binding':{'binding_id':claimed['binding_id'],'target_user_id':claimed['userId']},'binding_id':claimed['binding_id'],'enabled':True,'signature':None,'delivered':False})
    # No action snapshot, freeze or import is performed for read-only learning.


def lessons(store,materials):
    result=[]
    def add(identity,collection,title,number,topic,content,references,state):
        lid='lesson-'+hashlib.sha256(actions.encoded(identity).encode()).hexdigest()[:40]
        result.append(dict(id=lid,collection_id=collection,collection_title=title,number=number,title=topic,
                           content=content,references=references,content_version=hashlib.sha256(actions.encoded(dict(content=content,references=references)).encode()).hexdigest(),
                           learning_state='completed' if state=='completed' else 'unknown',source_url=source_url()+'#mobile/learn/'+lid))
    if materials is not None:
        for item in materials.lessons('yingyu'):
            course=materials.lesson('yingyu',item['filename'])
            add({'module':'yingyu','filename':item['filename']},'yingyu','英文阅读',item['lesson_no'],item['topic'],course['content'],'',item['learning_state'])
    with store.lock():
        for p in sorted(store.rows('learning_plans'),key=lambda p:p['id']):
            for item in store.lessons(p['id']):
                course=store.read_course(p['id'],item['lesson_no'])
                add({'plan_id':p['id'],'lesson_no':item['lesson_no']},p['id'],p['name'],item['lesson_no'],item['topic'],course['content'],course['sources'],item.get('learning_state'))
    if len(result)>200 or any(len(x['content'])>100000 or len(x['references'])>100000 for x in result):raise ValueError('Published reading library exceeds current bounded capacity')
    return sorted(result,key=lambda l:(l['collection_id'],l['number'],l['id']))


def sync(store,materials=None):
    if not source_url():return
    with actions.connection() as c:
        link,_=state(c);value=table(c)
    link=binding(link,value)
    if not link.get('binding_id') or value.get('binding_id')!=link.get('binding_id'):return
    # Metadata changes select immutable publications. Avoid refetching GitHub bodies every sweep.
    metadata={'origin':source_url(),'english':materials.lessons('yingyu') if materials is not None and value.get('enabled') else [],
              'plans':[{**p,'published':store.lessons(p['id'])} for p in store.rows('learning_plans')] if value.get('enabled') else []}
    catalog_signature=hashlib.sha256(actions.encoded(metadata).encode()).hexdigest()
    cached=value.get('payload',{})
    same=value.get('catalog_signature')==catalog_signature and cached.get('consent_enabled')==value.get('enabled',False)
    data={'consent_enabled':value.get('enabled',False),'lessons':cached['lessons'] if same else lessons(store,materials) if value.get('enabled') else []}
    if len(actions.encoded(data).encode())>4*1024*1024:raise ValueError('Published reading library exceeds current byte capacity')
    signature=hashlib.sha256(actions.encoded(data).encode()).hexdigest()
    with actions.connection(True,allow_link=True) as c:
        current,_=state(c);latest=table(c);current=binding(current,latest)
        if current.get('binding_id')!=link['binding_id'] or latest.get('enabled')!=value.get('enabled'):return
        if latest.get('signature')==signature:
            if latest.get('delivered'):return
            pending=latest
        else:
            revision=latest.get('revision',0)+1
            payload=dict(action='learning-library',action_schema_version=2,binding_id=link['binding_id'],source_revision=revision,observed_at=actions.clock().isoformat(),**data)
            pending={**latest,'catalog_signature':catalog_signature,'signature':signature,'revision':revision,'payload':payload,'delivered':False};put(c,pending)
    receipt=call(identity(),pending['payload'])
    expected=hashlib.sha256(actions.encoded({k:v for k,v in pending['payload'].items() if k not in ('action','action_schema_version','binding_id')}).encode()).hexdigest()
    if receipt.get('accepted') is not True or receipt.get('binding_id')!=link['binding_id'] or receipt.get('target_user_id')!=link['target_user_id'] or receipt.get('source_revision')!=pending['revision'] or receipt.get('payload_hash')!=expected:raise ValueError('Reading receipt does not match source scope and version')
    with actions.connection(True,allow_link=True) as c:
        latest=table(c)
        if latest.get('revision')==pending['revision'] and latest.get('signature')==signature:
            latest['delivered']=True;put(c,latest)


def register(app,store,materials):
    from mobile_private import register as register_private
    register_private(app)
    @app.get('/api/mobile-learning')
    def read():return status()

    @app.post('/api/mobile-learning/preview')
    async def pairing_preview(request:Request):
        guard(request);body=await request.json()
        if not isinstance(body,dict) or set(body)!={'code'} or not isinstance(body.get('code'),str) or len(body['code'])>80:actions.fail(422,'请填写有效连接码。')
        return preview(body['code'])

    @app.post('/api/mobile-learning/connect')
    async def pairing(request:Request):
        guard(request);body=await request.json()
        if not isinstance(body,dict) or set(body)!={'code','preview_id','consent'} or body.get('consent') is not True or not isinstance(body.get('code'),str) or len(body['code'])>80:actions.fail(422,'请确认本人账号及课程阅读范围。')
        connect(body['code'],body.get('preview_id'));return status()

    @app.post('/api/mobile-learning/consent')
    async def write(request:Request):
        guard(request);body=await request.json()
        if not isinstance(body,dict) or set(body)!={'enabled','consent'} or body.get('consent') is not True:actions.fail(422,'请本人确认课程正文范围。')
        consent(body['enabled']);return status()

    @app.get('/api/mobile-learning/source/{lesson_id}')
    def source(lesson_id:str):
        if not status()['enabled']:actions.fail(403,'尚未允许手机阅读。')
        # Resolve current identity on the authenticated source; no private content in a URL.
        if materials is not None:
            for item in materials.lessons('yingyu'):
                identity={'module':'yingyu','filename':item['filename']}
                if 'lesson-'+hashlib.sha256(actions.encoded(identity).encode()).hexdigest()[:40]==lesson_id:return dict(kind='study',module_id='yingyu',filename=item['filename'])
        for p in store.rows('learning_plans'):
            for item in store.lessons(p['id']):
                identity={'plan_id':p['id'],'lesson_no':item['lesson_no']}
                if 'lesson-'+hashlib.sha256(actions.encoded(identity).encode()).hexdigest()[:40]==lesson_id:return dict(kind='plan',**identity)
        actions.fail(404,'当前账号中没有这节课程，请核对来源。')
