"""Plan routes; registration has no filesystem or database side effects."""
from tenancy import scoped, learning_root, runtime_root
import json
import uuid
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from copilot.core import fail, Problem, encoded, digest
from copilot.generation import availability
from copilot.ai_config import require_config
from .store import LEGACY, integer, text
from .generation import PlanGenerator
from .progress import projection
from .github_store import make_store


class Payload(BaseModel):
    model_config=ConfigDict(extra='forbid')
    data: dict


def key(data):
    return text(data.get('key'),'请求标识',160)


def register(app, root, db):
    store=scoped(app, lambda: make_store(learning_root(root),runtime_root(db)), initialize=True); generator=scoped(app, lambda: PlanGenerator(store))
    router=APIRouter(prefix='/api/plans')

    @app.middleware('http')
    async def protect(request: Request, call_next):
        if not getattr(store,'remote',False) and request.url.path.startswith('/api/') and (store.runtime/'restore-pending.json').exists():
            return JSONResponse({'message':'计划恢复未完成，请核对恢复日志后再启动。'},status_code=503)
        if request.url.path.startswith(('/api/plans','/api/plan-actions')):
            if store.startup_error:
                return JSONResponse({'message':getattr(store.startup_error,'message','计划模块初始化失败，请检查存储配置。')},status_code=503)
            if request.method not in ('GET','HEAD','OPTIONS'):
                if request.headers.get('x-copilot-request')!='1':return JSONResponse({'message':'缺少同源写入标识。'},status_code=403)
                if int(request.headers.get('content-length','0'))>400000:return JSONResponse({'message':'请求内容过长。'},status_code=413)
        response=await call_next(request)
        if request.url.path.startswith(('/api/plans','/api/plan-actions')):response.headers['Cache-Control']='no-store'
        return response

    @router.get('')
    def listing():
        plans=[]
        for p in store.rows('learning_plans'):
            plans.append({k:v for k,v in p.items() if k!='hashes'} | {'lessons':store.lessons(p['id'])})
        attempts=[{k:v for k,v in a.items() if k not in ('raw','context','request')} for a in store.rows('learning_ai_attempts')]
        pending=[{'id':r['id'],'state':json.loads(r['data'])['state']} for r in publication_rows() if json.loads(r['data'])['state']!='done']
        return {'plans':plans,'legacy':[dict(x,kind='legacy') for x in LEGACY], 'budget':store.budget(),
                'storage':'github' if getattr(store,'remote',False) else 'local', 'pending_publications':pending,
                'generation_unavailable':availability(store),'requires_own_config':True, 'attempts':attempts[-20:],
                'drafts':[{'id':d['id'],'kind':d['kind'],'state':d['state'],'created_at':d.get('created_at','')}
                          for d in store.rows('learning_drafts') if d['state']!='published'][-30:]}

    def publication_rows():
        with store.conn() as c:return c.execute('SELECT id,data FROM learning_publications').fetchall()

    @router.post('/budget')
    def budget(body:Payload):
        data=body.data
        for k in ('weekly','legacy_weekly'):
            if data.get(k) is not None:integer(data[k],0,10080,k)
        with store.lock():store.put('learning_settings','budget',{'id':'budget','weekly':data.get('weekly'),'legacy_weekly':data.get('legacy_weekly')})
        return store.budget()

    @router.post('/drafts')
    def create_draft(body:Payload):
        return store.draft(body.data)

    @router.get('/drafts/{did}')
    def read_draft(did:str):return store.read_draft(did)

    @router.get('/drafts/{did}/history')
    def history(did:str,offset:int=0):
        integer(offset,0,1000000,'分页位置')
        return store.draft_history(did,offset)

    @router.post('/drafts/{did}/adopt')
    def adopt(did:str,body:Payload,request:Request):
        from learning_actions import guard, after_save
        opt_in=body.data.get('link_actions',False)
        if type(opt_in) is not bool:fail('invalid','关联行动开关须为布尔值。',422)
        if opt_in:guard(request)
        result=store.adopt(did,key(body.data),body.data.get('accept_over') is True,text(body.data.get('expected_hash'),'草稿校验值',100))
        return after_save(store,result,key(body.data),opt_in,request)

    @router.post('/drafts/{did}/edit-course')
    def edit_course(did:str,body:Payload):
        d=store.get('learning_drafts',did)
        if d['kind']!='course':fail('invalid','请选择课程草稿。',422)
        return store.course_draft(d['context'],text(body.data.get('content'),'正文',100000),text(body.data.get('sources'),'资料',100000),
                                  parent_id=did,parent_hash=body.data.get('parent_hash'))

    @router.post('/drafts/{did}/redate')
    def redate(did:str,body:Payload):
        if body.data.get('confirm_date') is not True:fail('invalid','请确认将课程日期改为今天。',422)
        return store.redate_course(did,body.data.get('parent_hash'))

    @router.post('/drafts/{did}/refine')
    async def refine(did:str,body:Payload):
        key(body.data)
        require_config(body.data.get('ai_config'))
        d=store.get('learning_drafts',did)
        return generator.begin({**body.data,'operation':'refine','parent_draft_id':did,'kind':d['kind']})

    @router.post('/drafts/{did}/publish')
    def publish(did:str,body:Payload,request:Request):
        from learning_actions import after_save
        result=store.publish_course(did,key(body.data),text(body.data.get('expected_hash'),'草稿校验值',100))
        return after_save(store,result,key(body.data),request=request)

    @router.post('/generate')
    async def generate(body:Payload):
        key(body.data)
        require_config(body.data.get('ai_config'))
        return generator.begin(body.data)

    @router.get('/attempts/{aid}/progress')
    def progress(aid:str,after_revision:int|None=None):
        return projection(store.get('learning_ai_attempts',aid),after_revision)

    @router.get('/attempts/{aid}')
    def attempt(aid:str):return store.get('learning_ai_attempts',aid)

    @router.post('/attempts/{aid}/cancel')
    async def cancel(aid:str):return generator.cancel(aid)

    @router.post('/recover')
    def recover():
        with store.lock():store.recover_locked()
        return {'ok':True}

    @router.post('/backup')
    def backup(body:Payload):
        if getattr(store,'remote',False):fail('github_storage','GitHub 模式请分别备份内容仓库和 Supabase 数据库，本地整库备份不适用。',409)
        if body.data.get('writers_stopped') is not True:fail('conflict','请先停止旧自动任务和外部编辑写入，再确认安全备份。')
        from .backup import snapshot
        with store.lock():return snapshot(store)

    @router.get('/{pid}')
    def detail(pid:str):
        p=store.plan(pid); v=store.version(pid)
        with store.conn() as c:
            feedback=[{'lesson_no':r[0],**json.loads(r[1])} for r in c.execute('SELECT lesson_no,data FROM learning_feedback WHERE plan_id=?',(pid,))]
            versions=[{'version':r[0],**json.loads(r[1])} for r in c.execute('SELECT version,data FROM learning_plan_versions WHERE plan_id=? ORDER BY version',(pid,))]
        rel=store.base(pid)+'/学习规划.md'
        ref=store.content.head() if getattr(store,'remote',False) else None
        content=store.read_text(rel,ref) if ref else (store.read_text(rel) if store.exists(rel) else '')
        actual=digest(content) if content else None
        return {'plan':{k:v for k,v in p.items() if k!='hashes'},'current':v,'lessons':store.lessons(pid),
                'feedback':feedback,'versions':versions,'external':{'hash':actual,'changed':actual!=p['hashes'].get(rel),
                    'content':content},
                'github_url':store.content.url(rel,ref) if ref else None}

    @router.post('/{pid}/metadata')
    def metadata(pid:str,body:Payload):
        data=body.data
        with store.lock():
            request={'op':'metadata','pid':pid,**data}; k=key(data)
            old=store.replay(k,request)
            if old is not None:return old
            p=store.plan(pid);store.check_files(p)
            if 'name' in data:p['name']=text(data['name'],'显示名',200)
            if 'status' in data:
                if data['status'] not in ('active','paused','archived'):fail('invalid','状态无效。',422)
                p['status']=data['status']
            rel=store.base(pid)+'/计划信息.json'; mirror={k:v for k,v in p.items() if k!='hashes'}|{'schema_version':1}
            content=encoded(mirror);p['hashes'][rel]=digest(content)
            return store.publish(k,request,{rel:content},[('UPDATE learning_plans SET data=? WHERE id=?',[encoded(p),pid])],mirror)

    @router.post('/{pid}/sources')
    def save_sources(pid:str,body:Payload):return store.save_sources(pid,body.data.get('entries'))

    @router.get('/{pid}/sources')
    def get_sources(pid:str):
        store.plan(pid);n=len(store.lessons(pid))+1
        rel=f'{store.base(pid)}/备课资料/第{n:03d}课.json'
        return {'lesson_no':n,'entries':json.loads(store.read_text(rel)) if store.exists(rel) else []}

    @router.get('/{pid}/lessons/{number}')
    def read_course(pid:str,number:int):
        return store.read_course(pid,number)

    @router.post('/{pid}/lessons/{number}/feedback')
    def feedback(pid:str,number:int,body:Payload):
        if body.data.get('state') == 'completed':
            from action_content import confirm_source
            return confirm_source(store,{'kind':'plan','plan_id':pid,'lesson_no':number},body.data,
                lambda:store.feedback(pid,number,body.data,key(body.data)))
        return store.feedback(pid,number,body.data,key(body.data))

    @router.post('/{pid}/pause')
    def pause_plan(pid: str, body: Payload):
        """暂停学习计划"""
        from datetime import datetime
        data = body.data
        reason = data.get('reason', '')

        with store.lock():
            p = store.plan(pid)
            current_status = p.get('status', 'active')

            if current_status == 'paused':
                fail('invalid', '计划已处于暂停状态。', 422)
            if current_status == 'archived':
                fail('invalid', '已归档的计划不能暂停。', 422)

            # 更新状态
            p['status'] = 'paused'
            p['paused_at'] = datetime.now().isoformat()

            # 记录状态历史
            with store.conn() as c:
                c.execute(
                    """INSERT INTO plan_status_history (plan_id, from_status, to_status, changed_at, reason)
                       VALUES (?, ?, ?, ?, ?)""",
                    (pid, current_status, 'paused', p['paused_at'], reason)
                )

            # 保存计划
            rel = store.base(pid) + '/计划信息.json'
            mirror = {k: v for k, v in p.items() if k != 'hashes'} | {'schema_version': 1}
            content = encoded(mirror)
            p['hashes'][rel] = digest(content)
            k = key(data)
            return store.publish(k, {'op': 'pause', 'pid': pid}, {rel: content},
                               [('UPDATE learning_plans SET data=? WHERE id=?', [encoded(p), pid])], mirror)

    @router.post('/{pid}/resume')
    def resume_plan(pid: str, body: Payload):
        """恢复学习计划"""
        from datetime import datetime
        data = body.data
        reason = data.get('reason', '')

        with store.lock():
            p = store.plan(pid)
            current_status = p.get('status', 'active')

            if current_status != 'paused':
                fail('invalid', '只能恢复已暂停的计划。', 422)

            # 更新状态
            p['status'] = 'active'
            p['resumed_at'] = datetime.now().isoformat()

            # 记录状态历史
            with store.conn() as c:
                c.execute(
                    """INSERT INTO plan_status_history (plan_id, from_status, to_status, changed_at, reason)
                       VALUES (?, ?, ?, ?, ?)""",
                    (pid, current_status, 'active', p['resumed_at'], reason)
                )

            # 保存计划
            rel = store.base(pid) + '/计划信息.json'
            mirror = {k: v for k, v in p.items() if k != 'hashes'} | {'schema_version': 1}
            content = encoded(mirror)
            p['hashes'][rel] = digest(content)
            k = key(data)
            return store.publish(k, {'op': 'resume', 'pid': pid}, {rel: content},
                               [('UPDATE learning_plans SET data=? WHERE id=?', [encoded(p), pid])], mirror)

    @router.post('/{pid}/archive')
    def archive_plan(pid: str, body: Payload):
        """归档学习计划"""
        from datetime import datetime
        data = body.data
        reason = data.get('reason', '')

        with store.lock():
            p = store.plan(pid)
            current_status = p.get('status', 'active')

            if current_status == 'archived':
                fail('invalid', '计划已处于归档状态。', 422)

            # 更新状态
            p['status'] = 'archived'
            p['archived_at'] = datetime.now().isoformat()

            # 记录状态历史
            with store.conn() as c:
                c.execute(
                    """INSERT INTO plan_status_history (plan_id, from_status, to_status, changed_at, reason)
                       VALUES (?, ?, ?, ?, ?)""",
                    (pid, current_status, 'archived', p['archived_at'], reason)
                )

            # 保存计划
            rel = store.base(pid) + '/计划信息.json'
            mirror = {k: v for k, v in p.items() if k != 'hashes'} | {'schema_version': 1}
            content = encoded(mirror)
            p['hashes'][rel] = digest(content)
            k = key(data)
            return store.publish(k, {'op': 'archive', 'pid': pid}, {rel: content},
                               [('UPDATE learning_plans SET data=? WHERE id=?', [encoded(p), pid])], mirror)

    @router.get('/{pid}/status-history')
    def get_status_history(pid: str):
        """获取计划状态变更历史"""
        store.plan(pid)  # 验证计划存在
        with store.conn() as c:
            rows = c.execute(
                """SELECT from_status, to_status, changed_at, reason
                   FROM plan_status_history
                   WHERE plan_id = ?
                   ORDER BY changed_at DESC""",
                (pid,)
            ).fetchall()
            return {
                'plan_id': pid,
                'history': [dict(r) for r in rows]
            }

    from learning_actions import register as register_learning_actions
    register_learning_actions(app,router,store,Payload)
    app.include_router(router)
    return store,generator
