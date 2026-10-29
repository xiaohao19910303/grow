"""选股v2的窗口、精度、原文边界与私有交接；不调用真实服务。"""
import copy
import json
import subprocess
from datetime import date,timedelta
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from investments.rule_screening import ALGORITHM,FIELDS,RuleScreen,RuleCondition,screen_v2,turnover_value
from investments.rules import calendar
from investments.api import register
from investments.market_import import import_history
from test_legacy_cloud_schema import PostgreSQLFixture


def fixture():
    cal=calendar('SSE','2026-08-01','2026-10-28','2026-10-29T17:00:00+08:00')
    days=[d for d,o in cal['sessions'].items() if o][-35:]
    bars=[{'date':d,'open':str(10+i),'close':str(10+i),'high':str(11+i),'low':str(9+i),'volume_shares':str(100+i),'turnover_cny':str(100000000+i),'turnover_rate_pct':'0' if i==0 else '3.5'} for i,d in enumerate(days)]
    item={'instrument_id':'i','code':'600001','market':'SSE','name':'合成股票','kind':'stock','price_basis':'unadjusted','calendar':cal,'bars':bars}
    return {'algorithm':ALGORITHM,'catalog':FIELDS,'universe':[item],'request':RuleScreen(as_of='2026-10-28').model_dump(mode='json')}


class RuleReferenceTests(TestCase):
    def test_parser_safety_javascript(self):
        server=Path(__file__).resolve().parents[1]
        result=subprocess.run(['node','tests/test_investment_rules_v2.cjs'],cwd=server,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_windows_missing_unused_fields_and_atomic_ranges(self):
        b=fixture();b['request']['conditions']=[{'field':'return_5d_pct','op':'between','value':'12','upper_value':'13'}]
        r=screen_v2(b);self.assertEqual(r['total'],1)
        self.assertEqual(r['items'][0]['values']['avg_turnover_5d_pct'],'3.5')
        b['universe'][0]['bars'][-3]['turnover_rate_pct']=None
        self.assertEqual(screen_v2(b)['total'],1)
        b['request']['conditions']=[{'field':'avg_turnover_5d_pct','op':'gte','value':'2'}]
        self.assertEqual(screen_v2(b)['unresolved'],1)
        b['request']['conditions']=[{'field':'return_5d_pct','op':'between','value':'90','upper_value':'100'}]
        b['request']['combine']='any';self.assertEqual(screen_v2(b)['total'],0)
        b['universe'][0]['bars'].pop(-2);self.assertEqual(screen_v2(b)['unresolved'],1)

    def test_unknown_rules_staleness_and_precision(self):
        b=fixture();b['universe'][0]['bars'].pop();self.assertEqual(screen_v2(b)['unresolved'],1)
        b=fixture();b['universe'][0]['calendar']['status']='coverage_unknown';self.assertEqual(screen_v2(b)['unresolved'],1)
        self.assertEqual(turnover_value('0'),'0');self.assertEqual(turnover_value('150'),'150');self.assertIsNone(turnover_value('nan'))
        for bad in ('-1','3%','abc'):
            with self.assertRaises(ValueError):turnover_value(bad)
        for body in ({'field':'eval','op':'gte','value':'1'},{'field':'close','op':'between','value':'2','upper_value':'1'}):
            with self.assertRaises(ValidationError):RuleCondition(**body)

    def test_python_browser_exact_parity_and_parser_contract(self):
        b=fixture();other=copy.deepcopy(b['universe'][0]);other.update(instrument_id='j',code='600000');b['universe'].append(other)
        b['request'].update(sort_by='return_5d_pct',secondary_sort_by='avg_turnover_5d_pct')
        server=Path(__file__).resolve().parents[1]
        script="""const fs=require('fs'),vm=require('vm');for(const f of ['investment-browser-core.js','investment-screening-v2.js'])vm.runInThisContext(fs.readFileSync('static/'+f,'utf8'));const b=JSON.parse(fs.readFileSync(0,'utf8'));console.log(JSON.stringify(InvestmentScreenV2.screen(b)));"""
        out=subprocess.run(['node','-e',script],input=json.dumps(b),text=True,capture_output=True,cwd=server,check=True)
        self.assertEqual(json.loads(out.stdout),screen_v2(b))
        self.assertEqual(json.loads(out.stdout)['items'][0]['code'],'600000')


class RuleHTTPTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp();app=FastAPI();self.store=register(app);self.store.initialize();self.client=TestClient(app);self.addCleanup(self.client.close)
        self.account=self.store.create('accounts',{'name':'规则账户','baseline_date':'2026-10-28','opening_cash':'0'},'account')
        self.stock=self.store.create('instruments',{'name':'合成股票','code':'600001','kind':'stock','market':'SSE'},'stock')
        self.b=fixture();text='date,open,high,low,close,volume,amount,换手率\n'+''.join(','.join(str(bar[k]) for k in ('date','open','high','low','close','volume_shares','turnover_cny','turnover_rate_pct'))+'\n' for bar in self.b['universe'][0]['bars'])
        self.market=import_history(self.store,self.stock['id'],text,'shares','cny','合成数据',True,'csv',self.account['id'])
        self.owner='test-rule-executor-unique';self.base={'protocol_version':2,'account_id':self.account['id'],'instrument_ids':[self.stock['id']],'screen':self.b['request'],'executor':self.owner}
        patcher=patch('copilot.transport.qwen_stream',side_effect=AssertionError('No server models'));patcher.start();self.addCleanup(patcher.stop)

    def post(self,path,body,key='run',status=200):
        r=self.client.post('/api/investments/'+path,json=body,headers={'X-Copilot-Request':'1','Idempotency-Key':key})
        self.assertEqual(r.status_code,status,r.text);return r.json()

    def test_pure_screen_template_version_selection_and_cancel(self):
        t=self.post('screening-templates',{'account_id':self.account['id'],'name':'规则','instrument_ids':[self.stock['id']],'screen':self.base['screen']},'template',201)
        body={**self.base,'template_id':t['id'],'template_version':t['version']}
        run=self.post('local-runs',body);self.assertIsNone(run['model'])
        frozen=self.client.get('/api/investments/local-runs/'+run['id']+'/inputs').json();result=screen_v2(frozen['bundle'])
        result.update(input_hash=frozen['input_hash'],executor=self.owner)
        saved=self.post('local-runs/'+run['id']+'/screening',result,'screen')
        self.assertEqual(saved['state'],'screened');self.assertEqual(saved['analysis_state'],'not_started')
        self.assertEqual(self.post('local-runs/'+run['id']+'/screening',result,'screen'),saved)
        self.post('local-runs/'+run['id']+'/candidates/'+self.stock['id'],{'executor':self.owner},'unselected',422)
        selection={'executor':self.owner,'model':'test-local','question':'研究','instrument_ids':[self.stock['id']]}
        self.post('local-runs/'+run['id']+'/analysis-selection',selection,'selection')
        job=self.post('local-runs/'+run['id']+'/candidates/'+self.stock['id'],{'executor':self.owner},'candidate')
        self.assertEqual(job['execution_location'],'browser')
        r=self.client.put('/api/investments/screening-templates/'+t['id'],json={'version':1,'data':{'name':'新版'}},headers={'X-Copilot-Request':'1','Idempotency-Key':'edit'})
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['version'],2)
        self.assertEqual(self.client.get('/api/investments/local-runs/'+run['id']+'/inputs').json()['bundle']['template_snapshot']['version'],1)
        other=self.store.create('accounts',{'name':'另一账户','baseline_date':'2026-10-28','opening_cash':'0'},'other-account')
        self.assertEqual(self.client.get('/api/investments/screening-templates',params={'account_id':other['id']}).json()['items'],[])
        self.post('local-runs',{**body,'account_id':other['id'],'template_version':2},'other-template',409)
        moved=self.client.put('/api/investments/screening-templates/'+t['id'],json={'version':2,'data':{'account_id':other['id']}},headers={'X-Copilot-Request':'1','Idempotency-Key':'move-template'})
        self.assertEqual(moved.status_code,422)

        self.post('local-runs/'+run['id']+'/cancel',{},'cancel')
        self.post('local-runs/'+run['id']+'/analysis-selection',selection,'late',409)

    def test_unknown_legacy_turnover_and_malicious_result(self):
        run=self.post('local-runs',self.base);frozen=self.client.get('/api/investments/local-runs/'+run['id']+'/inputs').json()
        result=screen_v2(frozen['bundle']);result.update(input_hash=frozen['input_hash'],executor=self.owner)
        bad=copy.deepcopy(result);bad['evaluations'][0]['name']='伪造';self.post('local-runs/'+run['id']+'/screening',bad,'bad',422)
        self.post('local-runs/'+run['id']+'/screening',{**result,'executor':'another-browser-owner'},'wrong-owner',409)
        self.assertEqual(len(result['evaluations']),1)
