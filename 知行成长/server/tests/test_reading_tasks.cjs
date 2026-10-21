/* Background completion, recovery and duplicate clicks without a model call. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element{
  constructor(tag){this.tagName=tag;this.children=[];this.text='';this.attributes={};}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;this.text='';}
  set textContent(value){this.text=String(value);this.children=[];}
  get textContent(){return this.text+this.children.map(n=>n.textContent).join('');}
  setAttribute(name,value){this.attributes[name]=value;}
}
const storage=new Map(),messages=[],opened=[];
function environment(account='owner'){
  const timers=new Map();let next=0;
  const body=new Element('body');
  const context={window:{Account:{ready:Promise.resolve(),user:{id:account}},toast:message=>messages.push(message)},
    document:{body,createElement:tag=>new Element(tag)},localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},
    setTimeout:fn=>{timers.set(++next,fn);return next;},clearTimeout:id=>timers.delete(id),console};
  vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/reading-tasks.js'),'utf8'),context);
  return {tasks:context.window.ReadingTasks,body,timers};
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  const env=environment();let posts=0,resolveStart,status='running',offline=false;
  const job=()=>({id:'job-1',kind:'summary',article_id:'article-1',state:status});
  async function api(url,data){
    if(url.startsWith('/library'))return {jobs:[]};
    if(data!==undefined){posts++;return new Promise(resolve=>{resolveStart=resolve;});}
    if(offline)throw new Error('offline');return job();
  }
  await env.tasks.initialize({api,open:async job=>{opened.push(job.id);}});
  const first=env.tasks.start('article-1','summary',{key:'one'},'测试文章');
  const second=env.tasks.start('article-1','summary',{key:'two'},'测试文章');
  assert.equal(posts,1,'double clicks share one server request');resolveStart(job());
  const [a,b]=await Promise.all([first,second]);assert.equal(a.id,b.id);
  const waiting=env.tasks.wait(a);assert(env.body.textContent.includes('测试文章'));
  offline=true;const timer=env.timers.values().next().value;env.timers.clear();await timer();await flush();
  assert(env.body.textContent.includes('正在重试'),'network loss remains recoverable');
  offline=false;status='ready';const retry=env.timers.values().next().value;env.timers.clear();await retry();await waiting;
  assert.equal(posts,1,'polling never restarts generation');
  assert(env.body.textContent.includes('已完成'),'completion stays visible after leaving a reader');
  assert.equal(messages.length,1,'completion notifies once');
  const recovered=environment();await recovered.tasks.initialize({api,open:async job=>opened.push(job.id)});
  assert(recovered.body.textContent.includes('测试文章'),'refresh restores completed result links');
  const all=el=>[el,...el.children.flatMap(all)];
  await all(recovered.body).find(el=>el.textContent==='查看结果').onclick();assert.deepEqual(opened,['job-1']);
  const other=environment('another');await other.tasks.initialize({api,open:()=>{}});
  assert(other.body.children[0].hidden,'another account cannot see saved task metadata');
  status='running';const resumed=environment('fresh');await resumed.tasks.initialize({api:async url=>url.startsWith('/library')?{jobs:[job()]}:job(),open:()=>{}});
  assert(resumed.tasks.find('article-1','summary'),'active server jobs recover without local history');
  const unified=environment('unified'),destinations=[];
  await unified.tasks.initialize({api:async()=>({jobs:[]}),open:()=>{}});
  const make=(source,state)=>unified.tasks.external(source,{id:'same-id',kind:'course',state,draft_id:source+'-draft'},{module:'yingyu',label:source==='plans'?'学习计划生成':'英文课程生成',title:'草稿'});
  for(const source of ['plans','study'])await unified.tasks.register(source,{
    read:async()=>make(source,'ready'),cancel:async()=>make(source,'cancelled'),open:async job=>destinations.push(job.draft_id)
  });
  unified.tasks.track(make('plans','generating'));unified.tasks.track(make('study','generating'));
  assert.equal(unified.timers.size,2,'different producers cannot collide on the same raw ID');
  const background=[...unified.timers.values()];unified.timers.clear();await Promise.all(background.map(run=>run()));await flush();
  assert.equal(destinations.length,0,'completion does not navigate away from the current page');
  const resultButtons=all(unified.body).filter(el=>el.textContent==='查看结果');
  assert.equal(resultButtons.length,2);for(const button of resultButtons)await button.onclick();
  assert.deepEqual(destinations.sort(),['plans-draft','study-draft'],'each result opens its own draft');
  const restoreUnified=environment('unified');await restoreUnified.tasks.initialize({api:async()=>({jobs:[]}),open:()=>{}});
  await restoreUnified.tasks.register('study',{open:job=>destinations.push(job.module)});
  assert(restoreUnified.body.textContent.includes('英文课程生成'),'non-reading metadata survives refresh');
  const planSource=fs.readFileSync(path.join(__dirname,'../static/plans.js'),'utf8');
  const apiSource=planSource.slice(planSource.indexOf('  async function api('),planSource.indexOf('  function button('));
  const tracked=[],forgotten=[];
  const planContext={window:{GenerationTasks:{external:(source,job,meta)=>({source,...job,...meta}),track:job=>tracked.push(job),forget:id=>forgotten.push(id)}},
    fetch:async url=>({ok:true,json:async()=>({id:url.includes('/drafts/')?'draft-id':'attempt-id',kind:'course',state:'ready'})})};
  vm.createContext(planContext);vm.runInContext(apiSource,planContext);
  await planContext.api('/attempts/attempt-id/progress');await planContext.api('/drafts/draft-id');
  assert.deepEqual(tracked.map(job=>job.id),['attempt-id'],'previewing a draft must not create another generation task');
  assert.deepEqual(forgotten,['plans:draft-id']);
  console.log('Unified generation checks passed: concurrent producers, terminal notifications, no automatic navigation, exact results and recovery.');
  console.log('Reading task checks passed: duplicate start, background completion, retry, refresh recovery, result link and account isolation.');
})().catch(error=>{console.error(error);process.exitCode=1;});
