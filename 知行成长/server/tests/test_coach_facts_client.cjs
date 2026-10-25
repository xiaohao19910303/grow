/* Foreground facts: no AI, no new timer, safe text and account/day scoping. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element{
  constructor(tag='section'){this.tagName=tag;this.children=[];this.hidden=false;this.dataset={};this.attributes={};this.text='';}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=[];this.text='';this.append(...nodes);}
  set textContent(value){this.text=String(value);this.children=[];}
  get textContent(){return this.text+this.children.map(n=>n.textContent).join('');}
  set innerHTML(_){throw Error('Personal facts must use textContent');}
  setAttribute(key,value){this.attributes[key]=value;}
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const all=node=>[node,...node.children.flatMap(all)];
function environment(storage=new Map()){
  const sections={coachFactToday:new Element(),coachFactOverview:new Element()},requests=[],routes=[],listeners={};
  let date='2026-10-25',now=1000,mode='success',resolvePending,denied=false;
  const result=()=>({date,timezone:'Asia/Shanghai',account_id:'alice',uses_model:false,fact:{kind:'activity',message:'已记录 <img src=x onerror=bad()>',basis:'未记录不代表没有学习',source:'学习分类',start:'2026-10-19',end:date,evidence:{active_days:1}}});
  const window={Account:{user:{id:'alice'},ready:Promise.resolve({id:'alice'})},ActionPlans:{day:()=>date},goTab:tab=>routes.push(tab),
    addEventListener:(name,fn)=>{listeners[name]=fn;},fetch:async(url,options)=>{requests.push({url,options});if(mode==='pending')return new Promise(resolve=>{resolvePending=resolve;});return {ok:mode==='success',json:async()=>mode==='success'?result():{detail:'PRIVATE ERROR'}};}};
  Object.defineProperty(window,'localStorage',{get:()=>{if(denied)throw Error('denied');return {getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)};}});
  const context={window,document:{hidden:false,getElementById:id=>sections[id],createElement:tag=>new Element(tag)},Date:class extends Date{static now(){return now;}},Intl,AbortController,setTimeout,clearTimeout,
    setInterval:()=>{throw Error('Reuse the existing reminder loop');},console};
  vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/coach-facts.js'),'utf8'),context);
  return {window,sections,requests,routes,storage,context,setMode:value=>mode=value,setDenied:()=>{denied=true;},setDate:value=>{date=value;},advance:ms=>{now+=ms;},resolve:()=>resolvePending({ok:true,json:async()=>result()}),result,listeners};
}
(async()=>{
  let env=environment();await flush();
  assert.equal(env.requests.length,1);assert.equal(env.requests[0].url,'/api/coach-facts');assert.equal(env.requests[0].options.cache,'no-store');
  assert(env.sections.coachFactToday.textContent.includes('<img src=x onerror=bad()>'));assert(env.sections.coachFactOverview.textContent.includes('依据'));
  assert(env.sections.coachFactToday.textContent.includes('北京时间'));assert.equal(env.sections.coachFactToday.hidden,false);
  await Promise.all([env.window.CoachFacts.refresh(),env.window.CoachFacts.tick(false),env.window.CoachFacts.refresh()]);assert.equal(env.requests.length,1);
  await env.window.CoachFacts.tick(true);assert.equal(env.sections.coachFactToday.hidden,true);assert.equal(env.sections.coachFactOverview.hidden,true);
  await env.window.CoachFacts.tick(false);assert.equal(env.sections.coachFactToday.hidden,false);assert.equal(env.requests.length,1);
  env.advance(300001);await env.window.CoachFacts.tick(false);assert.equal(env.requests.length,2);
  await env.window.CoachFacts.tick(true);await env.window.CoachFacts.refresh(true);assert.equal(env.requests.length,2);
  await env.window.CoachFacts.tick(false);assert.equal(env.requests.length,3,'A save during action priority invalidates the old snapshot');
  env.context.document.hidden=true;await env.window.CoachFacts.refresh(true);assert.equal(env.requests.length,3);
  env.context.document.hidden=false;await env.window.CoachFacts.tick(false);assert.equal(env.requests.length,4,'Foreground resume refreshes a saved record');
  for(let i=0;i<10;i++)env.window.CoachFacts.invalidate();
  assert.equal(env.requests.length,4,'Autosaves invalidate without issuing a request per keystroke');
  await env.window.CoachFacts.refresh();assert.equal(env.requests.length,5,'Navigation reads the invalidated snapshot');
  await all(env.sections.coachFactToday).find(n=>n.textContent==='查看记录').onclick();assert.deepEqual(env.routes,['learning-history']);

  env=environment();await flush();await all(env.sections.coachFactToday).find(n=>n.textContent==='今天先不显示').onclick();
  assert(env.sections.coachFactToday.hidden&&env.sections.coachFactOverview.hidden);assert.equal([...env.storage.values()][0],'2026-10-25');
  const reloaded=environment(env.storage);await flush();assert(reloaded.sections.coachFactToday.hidden);
  reloaded.setDate('2026-10-26');await reloaded.window.CoachFacts.tick(false);assert.equal(reloaded.sections.coachFactToday.hidden,false);
  reloaded.storage.set('zhixing-coach-facts-v1:alice','2026-10-26');reloaded.listeners.storage({key:'zhixing-coach-facts-v1:alice',newValue:'2026-10-26'});
  assert(reloaded.sections.coachFactToday.hidden,'Same-account dismissal syncs across tabs');

  env=environment();await flush();env.setMode('failure');await env.window.CoachFacts.refresh(true);
  assert(env.sections.coachFactToday.textContent.includes('暂未读取'));assert(!env.sections.coachFactToday.textContent.includes('已记录'));
  assert(!env.sections.coachFactToday.textContent.includes('PRIVATE ERROR'));env.setMode('success');await all(env.sections.coachFactToday).find(n=>n.textContent==='重试').onclick();assert(env.sections.coachFactToday.textContent.includes('已记录'));

  env=environment();env.setMode('pending');await flush();const requests=env.requests.length;
  const repeat=env.window.CoachFacts.refresh();env.window.Account.user.id='bob';env.resolve();await repeat;
  assert.equal(env.requests.length,requests);assert(env.sections.coachFactToday.hidden);assert(env.sections.coachFactOverview.hidden);

  env=environment();env.setDenied();await flush();await all(env.sections.coachFactToday).find(n=>n.textContent==='今天先不显示').onclick();assert(env.sections.coachFactToday.hidden);

  env=environment();env.setMode('pending');await flush();const first=env.window.CoachFacts.refresh(true);env.setMode('success');env.resolve();await first;
  assert.equal(env.requests.length,2,'A confirmed save during a request queues one fresh read');
  assert(env.sections.coachFactToday.textContent.includes('已记录'));
  console.log('Coach fact client checks passed: automatic read, safe text, coalescing, TTL, action priority, account/day dismissal, errors, storage denial and save invalidation.');
})().catch(error=>{console.error(error);process.exitCode=1;});
