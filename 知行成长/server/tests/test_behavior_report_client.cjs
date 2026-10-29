/* Durable report tasks: pending keys, explicit retries and backend-only recovery. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element{
  constructor(tag){this.tagName=tag;this.children=[];this.attributes={};this.disabled=false;this.text='';}
  append(...nodes){for(const n of nodes){n.parentNode=this;this.children.push(n);}}
  insertBefore(node,next){node.parentNode=this;this.children.splice(next?this.children.indexOf(next):this.children.length,0,node);}
  replaceChildren(...nodes){this.children=[];this.text='';this.append(...nodes);}
  set textContent(t){this.text=String(t);this.children=[];}get textContent(){return this.text+this.children.map(n=>n.textContent).join('');}
  setAttribute(k,v){this.attributes[k]=v;}
}
const all=n=>[n,...n.children.flatMap(all)],flush=()=>new Promise(r=>setImmediate(r));
function backend(){return{jobs:new Map(),keys:new Map(),calls:0};}
function environment(server=backend(),storage=new Map()){
  const body=new Element('body'),button=new Element('button');body.append(button);
  const tracked=[],requests=[],routes=[],providers={};let missing=false,lost=false,hold=null,seq=0;
  const config={api_base_url:'https://provider.example/v1',api_key:'LOCAL_ONLY_SECRET',model_name:'fixture'};
  const external=(source,j,meta={})=>({...j,id:source+':'+j.id,ref:j.id,source,...meta});
  const window={Account:{user:{id:'owner'}},AIConfig:{require(){if(missing)throw Error('请先保存自己的 AI 配置');return config;}},
    GenerationTasks:{external,track:j=>tracked.push({...j}),wait:async j=>j,register:(source,p)=>providers[source]=p},
    goTab:tab=>routes.push(tab),viewAIReport:id=>routes.push(id),renderAIReportLatest(){},renderAIReports(){}};
  const response=(value,ok=true,status=200)=>({ok,status,json:async()=>JSON.parse(JSON.stringify(value))});
  const context={window,document:{createElement:t=>new Element(t),querySelectorAll:()=>[button]},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},crypto:{randomUUID:()=>`request-${++seq}`},URLSearchParams,console,
    fetch:async(url,options={})=>{requests.push({url,options});const p=new URL(url,'https://local').pathname;
      if(p.endsWith('/jobs')&&options.method==='POST'){
        const input=JSON.parse(options.body);let id=server.keys.get(input.key);
        if(!id){id='job-'+(++server.calls);server.keys.set(input.key,id);server.jobs.set(id,{id,state:'queued',kind:'behavior-report',phase:'等待开始',period_days:input.period_days,retry_of:input.retry_of,result_id:null});}
        if(hold)await hold;
        if(lost){lost=false;throw Error('response lost');}
        return response(server.jobs.get(id),true,202);
      }
      if(p.includes('/by-request/')){const id=server.keys.get(decodeURIComponent(p.split('/').at(-1)));return id?response(server.jobs.get(id)):response({},false,404);}
      if(p.endsWith('/jobs'))return response({items:[...server.jobs.values()],total:server.jobs.size});
      const parts=p.split('/'),id=parts.at(-1)==='cancel'?parts.at(-2):parts.at(-1),job=server.jobs.get(id);
      if(!job)return response({},false,404);
      if(parts.at(-1)==='cancel')Object.assign(job,{state:'cancelled',error:'本人取消'});
      return response(job);
    }};
  vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/behavior-report.js'),'utf8'),context);
  return{window,body,button,providers,tracked,requests,routes,server,storage,setMissing:v=>missing=v,setLost:()=>lost=true,setHold:p=>hold=p};
}
(async()=>{
  let env=environment();env.setMissing(true);await env.window.generateNewReport(env.button,90);assert.equal(env.requests.length,0);assert(env.body.textContent.includes('AI 配置'));
  env.setMissing(false);await env.window.generateNewReport(env.button,90);const running=env.tracked.at(-1);
  assert.equal(JSON.parse(env.requests[0].options.body).ai_config.api_key,'LOCAL_ONLY_SECRET');assert.equal(JSON.parse(env.requests[0].options.body).period_days,90);
  assert.equal(env.requests[0].options.headers['X-Copilot-Request'],'1');assert(![...env.storage.values()].join('').includes('LOCAL_ONLY_SECRET'));
  await env.window.generateNewReport(env.button,90);assert.equal(env.server.calls,1,'active task prevents a new generation');
  await env.providers['behavior-report'].cancel(running);assert.equal(env.tracked.at(-1).state,'cancelled');
  await all(env.body).find(n=>n.textContent==='重试原输入').onclick();assert.equal(env.server.calls,2);assert.equal(JSON.parse(env.requests.filter(r=>r.options.method==='POST').at(-1).options.body).retry_of,running.ref);
  const recovered=environment(env.server);recovered.setMissing(true);const jobs=await recovered.providers['behavior-report'].recover();assert.equal(jobs.length,2);assert(recovered.requests.every(r=>!r.options.method||r.options.method==='GET'));assert.equal(env.server.calls,2,'recovery never calls the model');
  const ready=env.server.jobs.get(jobs.at(-1).ref);Object.assign(ready,{state:'ready',result_id:42});await recovered.providers['behavior-report'].open(jobs.at(-1));assert.deepEqual(recovered.routes,['ai-report',42]);
  env=environment();env.setLost();await env.window.generateNewReport(env.button,30);assert.equal(env.server.calls,1);const key=JSON.parse([...env.storage.values()][0]).key;
  assert(env.body.textContent.includes('重试原请求'));await all(env.body).find(n=>n.textContent==='重试原请求').onclick();assert.equal(env.server.calls,1,'unknown outcome reuses the original request key');assert.equal(JSON.parse(env.requests.filter(r=>r.options.method==='POST').at(-1).options.body).key,key);
  const pendingStorage=new Map([['grow.behavior-report.request:owner',JSON.stringify({key,period_days:30,retry_of:null})]]);
  const reload=environment(env.server,pendingStorage);reload.setMissing(true);await reload.providers['behavior-report'].recover();assert.equal(pendingStorage.size,0);assert(reload.requests.some(r=>r.url.includes('/by-request/')));
  const unknownStorage=new Map([['grow.behavior-report.request:owner',JSON.stringify({key:'unknown-original',period_days:90,retry_of:null})]]);
  const older={jobs:new Map([['old',{id:'old',state:'ready',period_days:30,result_id:1}]]),keys:new Map(),calls:0};
  const unknown=environment(older,unknownStorage);await unknown.providers['behavior-report'].recover();
  assert(unknown.body.textContent.includes('重试原请求'),'old completed reports must not hide an unresolved request');
  await all(unknown.body).find(n=>n.textContent==='重试原请求').onclick();assert.equal(JSON.parse(unknown.requests.filter(r=>r.options.method==='POST').at(-1).options.body).key,'unknown-original');
  env=environment();let release;env.setHold(new Promise(resolve=>release=resolve));const first=env.window.generateNewReport(env.button,30);await flush();assert.equal(env.button.disabled,true);await env.window.generateNewReport(env.button,30);assert.equal(env.server.calls,1);release();await first;
  env=environment();let finish;env.setHold(new Promise(resolve=>finish=resolve));const switching=env.window.generateNewReport(env.button,30);await flush();env.window.Account.user.id='other';finish();await switching;assert.equal(env.tracked.length,0,'old account response cannot become a new account task');assert(env.storage.has('grow.behavior-report.request:owner'));
  console.log('Durable AI report client passed: credentials, duplicate submit, cancel, frozen retry, recovery, lost responses and account switch.');
})().catch(e=>{console.error(e);process.exitCode=1;});
