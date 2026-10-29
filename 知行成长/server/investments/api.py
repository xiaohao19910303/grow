"""Authenticated-account investment HTTP contracts; execution remains user-owned."""
import json
from datetime import date
from typing import Literal

import db
from fastapi import APIRouter, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import AwareDatetime, Field

from copilot.core import Problem
from tenancy import scoped
from .contracts import AnalysisInput, Contract, FundConfirmation, RESOURCE_MODELS, StateCommand
from .analysis import InvestmentAnalysis
from .screening import ScreenInput
from .store import InvestmentStore
from .replay import PathInput
from .experiments import ExperimentInput
from .conditions import ConditionInput
from .execution_studies import ExecutionInput
from .browser_execution import BrowserExecution, BrowserRunInput, BrowserScreenResult, BrowserOwner, BrowserOutput, BrowserPause
from .browser_screening_v2 import ExecutionV2,RunInputV2,ResultV2,AnalysisSelection
from .rule_screening import FIELDS,RuleDraft,PARSER


class UpdateInput(Contract):
    version: int = Field(ge=1)
    data: dict


class CSVInput(Contract):
    account_id: str = Field(min_length=1,max_length=100)
    text: str = Field(max_length=250000)
    token: str | None = Field(default=None,max_length=100)


class CorrectionInput(UpdateInput):
    reason: str = Field(min_length=1,max_length=2000)


class FundConfirmInput(FundConfirmation):
    version: int = Field(ge=1)


class FundSettleInput(Contract):
    version: int = Field(ge=1)
    received_at: AwareDatetime


class AnalysisSubmit(Contract):
    preview_id: str = Field(min_length=1,max_length=100)
    snapshot_hash: str = Field(min_length=64,max_length=64)
    ai_config: dict = Field(repr=False)


class RecommendationInput(Contract):
    state: str = Field(max_length=30)
    note: str = Field(default='',max_length=4000)


class LegacyLinkInput(Contract):
    legacy_id: str = Field(min_length=1,max_length=100)
    target_kind: str = Field(max_length=30)
    target_id: str = Field(min_length=1,max_length=100)
    note: str = Field(min_length=1,max_length=2000)
    reconciled: bool


class ReviewActionInput(Contract):
    source_version: int = Field(ge=1)
    title: str = Field(min_length=1,max_length=160)
    date: date


class ExperimentFinishInput(Contract):
    version: int = Field(ge=1)
    decision: Literal['retain','reject','inconclusive','stopped']
    reason: str = Field(min_length=1,max_length=3000)
    evaluation_hash: str = Field(min_length=64,max_length=64)


class DailyFetchInput(Contract):
    instrument_id: str = Field(min_length=1,max_length=100)
    account_id: str | None = Field(default=None,max_length=100)
    start_date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    end_date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    token: str = Field(min_length=8,max_length=4096,repr=False)
    licensed_use_confirmed: bool
    calendar_mode: Literal['provider','public_reference'] = 'public_reference'


class HistoryCSVInput(Contract):
    instrument_id: str = Field(min_length=1,max_length=100)
    account_id: str | None = Field(default=None,max_length=100)
    text: str = Field(max_length=250000)
    volume_unit: str = Field(max_length=30)
    amount_unit: str = Field(max_length=30)
    source_label: str = Field(min_length=1,max_length=100)
    use_confirmed: bool


class AKShareDailyInput(Contract):
    instrument_id: str = Field(min_length=1,max_length=100)
    account_id: str | None = Field(default=None,max_length=100)
    start_date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    end_date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    use_confirmed: bool


class PrivateRoute(APIRoute):
    def get_route_handler(self):
        original=super().get_route_handler()
        async def safe_handler(request):
            try:
                return await original(request)
            except RequestValidationError as exc:
                from .observable_conditions import UnverifiableCondition
                for error in exc.errors():
                    cause=error.get('ctx',{}).get('error')
                    if isinstance(cause,UnverifiableCondition):
                        return JSONResponse({'error':'unverifiable_conditions','message':str(cause)},422,
                                            headers={'Cache-Control':'no-store'})
                # Default validation details can echo an entire input containing AI credentials.
                return JSONResponse({'error':'validation_error','message':'请核对输入字段、数值精度与时间格式。'},422,
                                    headers={'Cache-Control':'no-store'})
        return safe_handler


def register(app):
    store=scoped(app,InvestmentStore,initialize=True)
    analysis=scoped(app,lambda:InvestmentAnalysis(store))
    browser=scoped(app,lambda:ExecutionV2(store,analysis))
    router=APIRouter(prefix='/api/investments',tags=['investments'],route_class=PrivateRoute)

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
        from .readiness import requirements
        offline=requirements()
        return {'storage':'private_postgresql','currency':'CNY','accounting':'moving_weighted_average',
            'automatic_reference':{'enabled':True,'scope':'沪深公开日历与竞价限价买入参考子集；动态状态仍未知'},
            'provider':{'verified':False,'mode':'explicit_source','adapters':['manual_csv','akshare_eastmoney','tushare'],
                'reason':'手工选择来源；免费公开接口与账号权限不等于完整数据及许可验收。'},
            'realtime':{'enabled':False,'reason':'实时权限、时效和规则尚未验收。'},
            'ai':{'requires_own_config':True,'unattended':False},
            **{k:offline[k] for k in ('offline_replay','forward_observation','condition_drill','execution_study','backtest','intraday_alerts')}}

    @router.get('/overview')
    def today_overview(as_of: date):
        from .integration import overview
        return overview(store,as_of.isoformat())

    @router.post('/paths/import')
    def import_minute_path(payload: PathInput,idempotency_key: str=Header(min_length=1,max_length=160)):
        from .replay import import_path
        return import_path(store,payload.model_dump(mode='json'),idempotency_key)

    @router.get('/paths')
    def minute_paths(account_id: str,instrument_id: str | None=None,page: int=Query(1,ge=1,le=10000)):
        from .replay import paths
        return paths(store,account_id,instrument_id,page)

    @router.get('/paths/{object_id}')
    def original_minute_path(object_id: str):return store.get('intraday-paths',object_id)

    @router.get('/accounts/{account_id}/campaigns/{campaign_id}/replay')
    def holding_path(account_id: str,campaign_id: str,path_id: str,cutoff: AwareDatetime | None=None):
        from .replay import replay_campaign
        return replay_campaign(store,account_id,campaign_id,path_id,cutoff.isoformat() if cutoff else None)

    @router.post('/experiments',status_code=201)
    def new_experiment(payload: ExperimentInput,idempotency_key: str=Header(min_length=1,max_length=160)):
        from .experiments import create_experiment
        return create_experiment(store,payload.model_dump(mode='json'),idempotency_key)

    @router.post('/condition-drills')
    def condition_drill(payload: ConditionInput,idempotency_key: str=Header(min_length=1,max_length=160)):
        from .conditions import run_drill
        return run_drill(store,payload.model_dump(mode='json'),idempotency_key)

    @router.get('/condition-drills')
    def condition_drills(account_id: str,page: int=Query(1,ge=1,le=10000)):
        from .conditions import list_drills
        return list_drills(store,account_id,page)

    @router.get('/condition-drills/{object_id}')
    def saved_condition_drill(object_id: str):return store.get('condition-drills',object_id)

    @router.post('/execution-studies')
    def execution_study(payload: ExecutionInput,idempotency_key: str=Header(min_length=1,max_length=160)):
        from .execution_studies import run_study
        return run_study(store,payload.model_dump(mode='json'),idempotency_key)

    @router.get('/execution-studies')
    def execution_studies(account_id: str,page: int=Query(1,ge=1,le=10000)):
        from .execution_studies import list_studies
        return list_studies(store,account_id,page)

    @router.get('/execution-studies/{object_id}')
    def saved_execution_study(object_id: str):return store.get('execution-studies',object_id)

    @router.get('/experiments')
    def experiments(account_id: str,page: int=Query(1,ge=1,le=10000)):
        from .experiments import list_experiments
        return list_experiments(store,account_id,page)

    @router.get('/experiments/{object_id}')
    def experiment(object_id: str):return store.get('experiments',object_id)

    @router.get('/experiments/{object_id}/history')
    def experiment_history(object_id: str):return {'items':store.history('experiments',object_id)}

    @router.put('/experiments/{object_id}')
    def edit_experiment(object_id: str,payload: UpdateInput,idempotency_key: str=Header(min_length=1,max_length=160)):
        from .experiments import update_experiment
        return update_experiment(store,object_id,payload.version,payload.data,idempotency_key)

    @router.post('/experiments/{object_id}/register')
    def register_forward_experiment(object_id: str,payload: StateCommand,idempotency_key: str=Header(min_length=1,max_length=160)):
        from .experiments import register_experiment
        if payload.state!='confirmed':
            from copilot.core import fail
            fail('invalid_experiment_state','请使用confirmed显式登记当前版本。',422)
        return register_experiment(store,object_id,payload.version,idempotency_key)

    @router.get('/experiments/{object_id}/evaluation')
    def experiment_evaluation(object_id: str):
        from .experiments import evaluate_experiment
        return evaluate_experiment(store,object_id)

    @router.post('/experiments/{object_id}/finish')
    def finish_forward_experiment(object_id: str,payload: ExperimentFinishInput,idempotency_key: str=Header(min_length=1,max_length=160)):
        from .experiments import finish_experiment
        return finish_experiment(store,object_id,payload.version,payload.decision,payload.reason,payload.evaluation_hash,idempotency_key)

    @router.get('/readiness')
    def investment_requirements():
        from .readiness import requirements
        return requirements()

    @router.get('/calendar')
    def public_calendar(start: date,end: date,market: str=Query(max_length=10)):
        from .rules import calendar, now
        try:return calendar(market,start.isoformat(),end.isoformat(),now())
        except ValueError:
            from copilot.core import fail
            fail('invalid_calendar_range','日历范围须为顺序连续且不超过370日。',422)

    @router.get('/instruments/{object_id}/rules')
    def public_rules(object_id: str,on: date):
        from .rules import rule_context, now
        return rule_context(store.get('instruments',object_id),on.isoformat(),now())

    @router.get('/instruments/{object_id}/data-status')
    def instrument_freshness(object_id: str):
        from .rules import data_status
        return data_status(store,object_id)

    @router.get('/search')
    def private_investment_search(account_id: str,q: str=Query(min_length=1,max_length=200),page: int=Query(1,ge=1,le=10000)):
        from .integration import private_search
        return private_search(store,account_id,q,page)

    @router.get('/reviews/{object_id}/actions')
    def review_actions(object_id: str):
        from .integration import references
        return references(store,object_id)

    @router.post('/reviews/{object_id}/actions')
    def create_review_action(object_id: str,payload: ReviewActionInput,idempotency_key: str=Header(min_length=1,max_length=160)):
        from .integration import create_action
        return create_action(store,object_id,payload.model_dump(mode='json'),idempotency_key)

    @router.post('/provider/daily')
    async def daily_fetch(payload: DailyFetchInput,idempotency_key: str=Header(min_length=1,max_length=160)):
        from .providers import DailyProvider
        return await DailyProvider(store).fetch(payload.instrument_id,payload.start_date,payload.end_date,
            payload.token,payload.licensed_use_confirmed,idempotency_key,payload.account_id,calendar_mode=payload.calendar_mode)

    @router.get('/data-sources')
    def data_sources():
        return {'sources':[
            {'id':'tushare','name':'Tushare Pro','status':'adapter_ready','scope':'沪深股票/ETF盘后行情与日历适配；账号权限待核验，北交所日历未开放','url':'https://tushare.pro/document/2'},
            {'id':'akshare','name':'AKShare / 东方财富','status':'adapter_ready','scope':'沪深股票及ETF未复权盘后日线，无需Token；公开接口可限流/变更，使用范围需本人核对','url':'https://akshare.akfamily.xyz/'},
            {'id':'baostock','name':'BaoStock','status':'planned','scope':'历史行情候选；当前服务和具体品种覆盖待实测','url':'https://baostock.com/api/'},
            {'id':'ifind','name':'同花顺iFinD','status':'planned','scope':'授权数据接口候选；账号、额度与用途需配置','url':'https://quantapi.51ifind.com/'},
            {'id':'cninfo','name':'巨潮资讯','status':'external','scope':'公告与财报原文核对；非实时行情承诺','url':'https://www.cninfo.com.cn/'},
            {'id':'iwencai','name':'同花顺问财','status':'external','scope':'在官网进行条件查询；未接入其私有接口','url':'https://www.iwencai.com/'},
            {'id':'eastmoney','name':'东方财富条件选股','status':'external','scope':'官网查看/筛选；未接入其私有接口','url':'https://xuangu.eastmoney.com/'}]}

    @router.get('/legacy-records')
    def legacy_records():
        from .legacy import list_legacy
        return list_legacy(store)

    @router.post('/legacy-links')
    def legacy_link(payload: LegacyLinkInput,idempotency_key: str=Header(min_length=1,max_length=160)):
        from .legacy import link_record
        return link_record(store,payload.legacy_id,payload.target_kind,payload.target_id,payload.note,payload.reconciled,idempotency_key)

    @router.post('/local-runs')
    def browser_run(payload: BrowserRunInput | RunInputV2, idempotency_key: str=Header(min_length=1,max_length=160)):
        return browser.create(payload,idempotency_key)

    @router.get('/market-snapshots/{object_id}')
    def captured_market_snapshot(object_id: str):return store.get('market-snapshots',object_id)

    @router.get('/local-runs')
    def browser_runs(page: int=Query(1,ge=1,le=10000)):
        return browser.listing(page)

    @router.get('/local-runs/{run_id}')
    def browser_run_detail(run_id: str):return browser.get(run_id)

    @router.get('/local-runs/{run_id}/inputs')
    def browser_run_inputs(run_id: str):return browser.get(run_id,include_input=True)

    @router.post('/local-runs/{run_id}/screening')
    def browser_screen_result(run_id: str,payload: BrowserScreenResult | ResultV2,idempotency_key: str=Header(min_length=1,max_length=160)):
        return browser.screen_result(run_id,payload,idempotency_key)

    @router.get('/screening-catalog')
    def screening_catalog():return {'fields':FIELDS,'parser_version':PARSER,'draft_schema':RuleDraft.model_json_schema()}

    @router.post('/local-runs/{run_id}/analysis-selection')
    def analysis_selection(run_id: str,payload: AnalysisSelection,idempotency_key: str=Header(min_length=1,max_length=160)):
        return browser.select_analysis(run_id,payload,idempotency_key)

    @router.post('/local-runs/{run_id}/candidates/{instrument_id}')
    def browser_candidate(run_id: str,instrument_id: str,payload: BrowserOwner,idempotency_key: str=Header(min_length=1,max_length=160)):
        return browser.start_candidate(run_id,instrument_id,payload,idempotency_key)

    @router.post('/local-runs/{run_id}/cancel')
    def browser_cancel(run_id: str):return browser.cancel(run_id)

    @router.get('/local-jobs/{job_id}/input')
    def browser_input(job_id: str,x_local_executor: str=Header(min_length=16,max_length=100)):
        return browser.job_input(job_id,x_local_executor)

    @router.post('/local-jobs/{job_id}/pause')
    def browser_pause(job_id: str,payload: BrowserPause):return browser.pause(job_id,payload)

    @router.post('/local-jobs/{job_id}/{stage}')
    def browser_output(job_id: str,stage: Literal['draft','result'],payload: BrowserOutput,
                       idempotency_key: str=Header(min_length=1,max_length=160)):
        return browser.output(job_id,stage,payload,idempotency_key)

    @router.post('/screen')
    def screening(payload: ScreenInput):
        from .screening import screen
        return screen(store,payload)

    @router.post('/market/import')
    def history_import(payload: HistoryCSVInput,idempotency_key: str=Header(min_length=1,max_length=160)):
        from .market_import import import_history
        return import_history(store,payload.instrument_id,payload.text,payload.volume_unit,
            payload.amount_unit,payload.source_label,payload.use_confirmed,idempotency_key,payload.account_id)

    @router.post('/provider/akshare/daily')
    def akshare_daily_fetch(payload: AKShareDailyInput,idempotency_key: str=Header(min_length=1,max_length=160)):
        from .akshare_daily import AKShareDailyProvider
        return AKShareDailyProvider(store).fetch(payload.instrument_id,payload.start_date,payload.end_date,
            payload.use_confirmed,idempotency_key,payload.account_id)

    @router.post('/analysis/preview')
    def analysis_preview(payload: AnalysisInput):
        return analysis.preview(payload.model_dump(mode='json'))

    @router.post('/analysis/jobs',status_code=202)
    async def analysis_submit(payload: AnalysisSubmit,idempotency_key: str=Header(min_length=1,max_length=160)):
        return await analysis.submit(payload.preview_id,payload.snapshot_hash,payload.ai_config,idempotency_key)

    @router.get('/analysis/jobs')
    def analysis_listing():
        return analysis.listing()

    @router.get('/analysis/jobs/{object_id}')
    def analysis_get(object_id: str):
        return analysis.get(object_id)

    @router.post('/analysis/jobs/{object_id}/cancel')
    async def analysis_cancel(object_id: str):
        return await analysis.cancel(object_id)

    @router.get('/analysis/previews/{object_id}')
    def analysis_preview_get(object_id: str):
        return store.get('analysis-previews',object_id)

    @router.post('/analysis/jobs/{object_id}/suggestions/{index}/decision')
    def recommendation_decision(object_id: str,index: int,payload: RecommendationInput,
                                idempotency_key: str=Header(min_length=1,max_length=160)):
        return analysis.decide(object_id,index,payload.state,payload.note,idempotency_key)

    @router.post('/analysis/jobs/{object_id}/scenarios/{index}/policy-draft')
    def adopt_capital_scenario(object_id: str,index: int,idempotency_key: str=Header(min_length=1,max_length=160)):
        return analysis.capital_draft(object_id,index,idempotency_key)

    @router.get('/recommendations')
    def recommendations():
        with db.connect() as c:
            rows=c.execute("SELECT data FROM investment_objects WHERE kind='recommendations' ORDER BY created_at DESC LIMIT 100")
            return {'items':[json.loads(row[0]) for row in rows]}

    @router.get('/accounts/{object_id}/balance')
    def balance(object_id: str):
        return store.balance(object_id)

    @router.get('/accounts/{object_id}/policy-status')
    def capital_status(object_id: str,as_of: date,plan_id: str | None=None):
        from .planning import policy_status
        return policy_status(store,object_id,as_of.isoformat(),plan_id)

    @router.get('/accounts/{object_id}/campaigns')
    def campaigns(object_id: str):
        return {'items':store.campaigns(object_id)}

    @router.get('/accounts/{object_id}/campaigns/{campaign_id}/review')
    def campaign_review(object_id: str,campaign_id: str):
        from .reviews import campaign_detail
        return campaign_detail(store,object_id,campaign_id)

    @router.get('/accounts/{object_id}/summary')
    def period_review(object_id: str,start: date,end: date):
        from .reviews import period_summary
        return period_summary(store,object_id,start.isoformat(),end.isoformat())

    @router.get('/trade-plans/{object_id}/assessment')
    def plan_assessment(object_id: str):
        from .plan_checks import assess_plan
        return assess_plan(store,object_id)

    @router.get('/export')
    def export():
        return JSONResponse(store.export(),headers={
            'Content-Disposition':'attachment; filename="grow-investments.json"'})

    @router.post('/imports/preview')
    def preview(payload: CSVInput):
        from .operations import preview_csv
        return preview_csv(store,payload.account_id,payload.text)

    @router.post('/imports/commit')
    def commit(payload: CSVInput,idempotency_key: str=Header(min_length=1,max_length=160)):
        from .operations import commit_csv
        return commit_csv(store,payload.account_id,payload.text,payload.token,idempotency_key)

    @router.post('/fills/{object_id}/corrections')
    def correct(object_id: str,payload: CorrectionInput,idempotency_key: str=Header(min_length=1,max_length=160)):
        from .operations import correct_fill
        return correct_fill(store,object_id,payload.version,payload.data,payload.reason,idempotency_key)

    @router.post('/fund-orders/{object_id}/confirm')
    def confirm_fund_order(object_id: str,payload: FundConfirmInput,idempotency_key: str=Header(min_length=1,max_length=160)):
        from .operations import confirm_fund
        return confirm_fund(store,object_id,payload.version,payload.model_dump(mode='json',exclude={'version'}),idempotency_key)

    @router.post('/fund-orders/{object_id}/settle')
    def settle_fund_order(object_id: str,payload: FundSettleInput,idempotency_key: str=Header(min_length=1,max_length=160)):
        from .operations import settle_fund
        return settle_fund(store,object_id,payload.version,payload.received_at.isoformat(),idempotency_key)

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
            return store.transition(kind,object_id,payload.version,payload.state,idempotency_key,payload.reason)
        return change

    for kind,model in RESOURCE_MODELS.items():
        router.add_api_route('/'+kind,creators(kind,model),methods=['POST'],status_code=201)
        router.add_api_route('/'+kind,listers(kind),methods=['GET'])
        router.add_api_route('/'+kind+'/{object_id}',getters(kind),methods=['GET'])
        router.add_api_route('/'+kind+'/{object_id}/history',histories(kind),methods=['GET'])
        if kind in ('screening-templates','policies','strategies','trade-plans','reviews','period-plans','watchlist','dossiers','principles','ledger-notices'):
            router.add_api_route('/'+kind+'/{object_id}',editors(kind),methods=['PUT'])
        if kind in ('policies','strategies','trade-plans','period-plans','principles'):
            router.add_api_route('/'+kind+'/{object_id}/state',transitions(kind),methods=['POST'])
    app.include_router(router)
    return store
