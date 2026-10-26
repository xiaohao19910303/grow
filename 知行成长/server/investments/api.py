"""Authenticated-account investment HTTP contracts; execution remains user-owned."""
from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from copilot.core import Problem
from tenancy import scoped
from .contracts import Contract, RESOURCE_MODELS, StateCommand
from .store import InvestmentStore


class UpdateInput(Contract):
    version: int = Field(ge=1)
    data: dict


def register(app):
    store=scoped(app,InvestmentStore,initialize=True)
    router=APIRouter(prefix='/api/investments',tags=['investments'])

    @app.middleware('http')
    async def boundary(request: Request,call_next):
        if not (request.url.path=='/api/investments' or request.url.path.startswith('/api/investments/')):
            return await call_next(request)
        headers={'Cache-Control':'no-store'}
        try:
            if request.method not in ('GET','HEAD','OPTIONS'):
                if request.headers.get('x-copilot-request')!='1':
                    return JSONResponse({'error':'same_origin_required','message':'缺少同源写入标识。'},403,headers=headers)
                if len(await request.body())>400000:
                    return JSONResponse({'error':'too_large','message':'投资请求超过大小限制。'},413,headers=headers)
            if store.startup_error:
                return JSONResponse({'error':'storage_unavailable','message':'投资工作台暂不可用，原记录保留。'},503,headers=headers)
            response=await call_next(request)
        except Problem as exc:
            return JSONResponse({'error':exc.code,'message':exc.message},exc.status,headers=headers)
        response.headers.update(headers)
        return response

    @router.get('/capabilities')
    def capabilities():
        return {'storage':'private_postgresql','currency':'CNY','accounting':'moving_weighted_average',
            'provider':{'verified':False,'mode':'manual','reason':'尚未核验本账号行情权限和使用许可。'},
            'realtime':{'enabled':False,'reason':'实时权限、时效和规则尚未验收。'},
            'ai':{'requires_own_config':True,'unattended':False}}

    @router.get('/accounts/{object_id}/balance')
    def balance(object_id: str):
        return store.balance(object_id)

    @router.get('/accounts/{object_id}/campaigns')
    def campaigns(object_id: str):
        return {'items':store.campaigns(object_id)}

    def creators(kind,model):
        def create(payload, idempotency_key: str=Header(min_length=1,max_length=160)):
            return store.create(kind,payload.model_dump(mode='json'),idempotency_key)
        create.__annotations__['payload']=model
        create.__name__='create_investment_'+kind.replace('-','_')
        return create

    def listers(kind):
        def listing(page: int=Query(1,ge=1),page_size: int=Query(50,ge=1,le=100),account_id: str | None=None):
            return store.listing(kind,page=page,page_size=page_size,account_id=account_id)
        return listing

    def getters(kind):
        def get(object_id: str):
            return store.get(kind,object_id)
        return get

    def histories(kind):
        def history(object_id: str):
            return {'items':store.history(kind,object_id)}
        return history

    def editors(kind):
        def edit(object_id: str,payload: UpdateInput,idempotency_key: str=Header(min_length=1,max_length=160)):
            return store.update(kind,object_id,payload.version,payload.data,idempotency_key)
        return edit

    def transitions(kind):
        def change(object_id: str,payload: StateCommand,idempotency_key: str=Header(min_length=1,max_length=160)):
            return store.transition(kind,object_id,payload.version,payload.state,idempotency_key)
        return change

    for kind,model in RESOURCE_MODELS.items():
        router.add_api_route('/'+kind,creators(kind,model),methods=['POST'],status_code=201)
        router.add_api_route('/'+kind,listers(kind),methods=['GET'])
        router.add_api_route('/'+kind+'/{object_id}',getters(kind),methods=['GET'])
        router.add_api_route('/'+kind+'/{object_id}/history',histories(kind),methods=['GET'])
        if kind in ('policies','strategies','trade-plans','reviews'):
            router.add_api_route('/'+kind+'/{object_id}',editors(kind),methods=['PUT'])
        if kind in ('policies','strategies','trade-plans'):
            router.add_api_route('/'+kind+'/{object_id}/state',transitions(kind),methods=['POST'])
    app.include_router(router)
    return store
