/* AI report configuration, terminal states, explicit retries and task recovery. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.attributes={};this.disabled=false;this.text='';}
  append(...nodes){for(const n of nodes){n.parentNode=this;this.children.push(n);}}
  insertBefore(node,next){node.parentNode=this;this.children.splice(next?this.children.indexOf(next):this.children.length,0,node);}
  replaceChildren(...nodes){this.children=[];this.text='';this.append(...nodes);}
  set textContent(t){this.text=String(t);this.children=[];}
  get textContent(){return this.text+this.children.map(n=>n.textContent).join('');}
  setAttribute(k,v){this.attributes[k]=v;}
}
const all=node=>[node,...node.children.flatMap(all)];
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function environment(){
  const body=new Element('body'),button=new Element('button');button.textContent='生成新报告';body.append(button);
  const tracked=[],messages=[],requests=[],routes=[],providers={};let mode='success',missing=false,resolvePending;
  const config={api_base_url:'https://provider.example/v1',api_key:'LOCAL_KEY',model_name:'model'};
  const window={Account:{user:{id:'owner'}},AIConfig:{require(){if(missing)throw new Error('请先保存自己的 AI 配置');return config;}},
    GenerationTasks:{track:job=>tracked.push({...job}),register:(source,provider)=>providers[source]=provider},
    toast:message=>messages.push(message),goTab:tab=>routes.push(tab),renderAIReportLatest:()=>{},renderAIReports:()=>{},viewAIReport:id=>routes.push(id)};
  const context={window,document:{createElement:tag=>new Element(tag),querySelectorAll:()=>[button]},crypto:{randomUUID:()=>String(requests.length+1)},AbortController,console,
    fetch:async(url,options)=>{requests.push({url,options});if(mode==='pending')return new Promise((resolve,reject)=>{resolvePending=resolve;options.signal.addEventListener('abort',()=>reject(Object.assign(new Error('aborted'),{name:'AbortError'})));});
      return {ok:mode==='success',json:async()=>mode==='success'?{id:42,content:'## 报告'}:{detail:'服务商暂不可用'}};}};
  vm.createContext(context);const file=path.join(__dirname,'../static/behavior-report.js');vm.runInContext(fs.existsSync(file)?fs.readFileSync(file,'utf8'):'',context);
  return {body,button,window,tracked,messages,requests,routes,providers,setMode:value=>mode=value,setMissing:value=>missing=value,resolve:result=>resolvePending(result),config};
}
(async()=>{
  let env=environment();assert.equal(typeof env.window.generateNewReport,'function','report module exposes the existing entry point');
  env.setMissing(true);await env.window.generateNewReport(env.button,90);
  assert.equal(env.requests.length,0);assert(env.body.textContent.includes('AI 配置'));await all(env.body).find(n=>n.textContent==='前往设置').onclick();assert.deepEqual(env.routes,['settings']);
  env.setMissing(false);await env.window.generateNewReport(env.button,90);
  assert.equal(JSON.parse(env.requests[0].options.body).ai_config.api_key,env.config.api_key);assert.equal(env.requests[0].options.headers['X-Copilot-Request'],'1');
  assert(env.requests[0].url.endsWith('period_days=90'));assert.equal(env.tracked.at(-1).state,'ready');assert.equal(env.button.disabled,false);
  env=environment();env.setMode('pending');const first=env.window.generateNewReport(env.button,90);await flush();await env.window.generateNewReport(env.button,90);assert.equal(env.requests.length,1,'duplicate clicks do not call the model twice');
  const running=env.tracked.at(-1);await env.providers['behavior-report'].cancel(running);await first;assert.equal(env.tracked.at(-1).state,'cancelled');assert(!env.messages.includes('报告已生成'));
  assert(env.body.textContent.includes('重新生成'));env.setMode('error');await all(env.body).find(n=>n.textContent==='重新生成').onclick();assert.equal(env.tracked.at(-1).state,'failed');assert.equal(env.requests.length,2);assert(env.requests[1].url.endsWith('period_days=90'),'retry preserves the period');
  env.setMode('success');await all(env.body).find(n=>n.textContent==='重新生成').onclick();assert.equal(env.tracked.at(-1).state,'ready');assert.equal(env.requests.length,3,'retry requires a user action');
  const restored=environment();const job=await restored.providers['behavior-report'].read({...running,id:'prior-page',ref:'90'});assert.equal(job.state,'interrupted');assert.equal(restored.requests.length,0,'refresh never restarts the model');await restored.providers['behavior-report'].open(job);assert(restored.body.textContent.includes('历史'));
  console.log('AI report checks passed: browser config, same-origin header, duplicate start, cancel, explicit retry, period preservation and refresh recovery.');
})().catch(e=>{console.error(e);process.exitCode=1;});
