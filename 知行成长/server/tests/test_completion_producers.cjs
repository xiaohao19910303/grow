/* Exercise real producer handlers, not a second implementation of completion. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=name=>fs.readFileSync(path.join(__dirname,'../static',name),'utf8');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.text='';this.dataset={};this.style={};this.attributes={};this.value='';this.hidden=false;this.isConnected=true;this.classList={add(){},remove(){},contains(){return false;}};}
  append(...items){this.children.push(...items);}
  prepend(...items){this.children.unshift(...items);}
  replaceChildren(...items){this.children=items;this.text='';}
  insertBefore(item,before){const i=this.children.indexOf(before);this.children.splice(i<0?0:i,0,item);}
  set textContent(value){this.text=String(value);this.children=[];}
  get textContent(){return this.text+this.children.map(n=>n.textContent||'').join('');}
  querySelectorAll(selector){return descendants(this).filter(n=>n!==this&&(selector==='button'?n.tagName==='button':false));}
  querySelector(selector){if(selector==='.confetti-container'){const n=new Element('div');this.append(n);return n;}return this.querySelectorAll(selector)[0]||null;}
  setAttribute(name,value){this.attributes[name]=value;}
  scrollIntoView(){}
  addEventListener(){}
  remove(){this.isConnected=false;}
}
const descendants=el=>[el,...el.children.flatMap(descendants)];
const findButton=(el,label)=>descendants(el).find(n=>n.tagName==='button'&&n.textContent===label);
async function dailyEnvironment({serverWarning='',refreshFailure=false,renzhi=false,lostResponse=false}={}){
  const elements=new Map(),requests=[],intervals=new Map(),messages=[];let timer=0,completed=false,refreshes=0,postGate;
  const element=id=>{if(!elements.has(id))elements.set(id,new Element('div'));return elements.get(id);};
  element('view-action-schedule').style.display='none';
  const lesson={lesson_no:1,filename:'Day 001.md',topic:'合成练习',learning_state:renzhi?'completed':'unknown',learning_label:'待本人反馈',version:'v-one'};
  const course=()=>({id:'biaoda',name:'结构化表达',duration:'15 分钟',lessons:[{...lesson,learning_state:completed?'completed':'unknown'}]});
  const plan={id:'scheduled',period:'day',title:'合成练习',start_date:'2026-10-21',at:'09:00',timezone:'Asia/Shanghai',completion_mode:'content',status:'active',target_minutes:15,target:{kind:'biaoda',course:lesson.filename},progress:{minutes:0}};
  let snapshot={plans:[plan],execution:{id:'running-one',plan_id:plan.id}};
  const actionPlans={day:()=> '2026-10-21',snapshot:()=>snapshot,refresh:async()=>{
    refreshes++;if(refreshFailure)throw Error('状态读取离线');
    snapshot={plans:[{...plan,status:completed?'completed':'active'}],execution:completed?null:snapshot.execution};
    window.DailyAgenda.render();element('actionExecution').hidden=!snapshot.execution;
  }};
  const window={ActionPlans:actionPlans,addEventListener(){},studyReaderRequest:0,
    refreshAutoCheckins:async()=>{},renderLearningMarkdown:(el,text)=>el.textContent=text,
    lessonReturnLabel:()=> '返回今日安排',StudyNotes:{mount:()=>{
      const form=new Element('form'),input=new Element('textarea'),status=new Element('p'),actions=new Element('div');
      input.value='保存的学习笔记';form.append(input,status,actions);
      return {form,input,status,actions,safe:true,flush:async()=>{}};
    },beforeLeave:()=>true}};
  const context={window,ActionPlans:actionPlans,console,document:{body:new Element('body'),head:new Element('head'),getElementById:element,createElement:tag=>new Element(tag)},
    crypto:require('node:crypto').webcrypto,Date,alert:message=>messages.push(message),toast:message=>messages.push(message),
    setInterval:fn=>{intervals.set(++timer,fn);return timer;},clearInterval:id=>intervals.delete(id),setTimeout:()=>++timer,clearTimeout(){},
    rememberLearningOrigin(){},goTab:()=>true,returnFromLesson:()=>{assert(window.beforeStudyLeave());element('dailyReader').hidden=true;window.DailyAgenda.render();},
    fetch:async(url,options={})=>{
      requests.push({url,...options});
      if(options.method==='POST'){
        completed=true;if(postGate)await postGate;
        if(lostResponse){lostResponse=false;throw Error('响应丢失');}
        return {ok:true,status:200,json:async()=>({lesson_no:1,revision:1,completed_at:'2026-10-21T10:00:00+08:00',time_spent_seconds:0,summary_text:'保存的学习笔记',arrangement_sync_error:serverWarning})};
      }
      let data;
      if(url==='/api/copilot/today-task')data={lessons:renzhi?[lesson]:[]};
      else if(url==='/api/study-materials')data={modules:renzhi?[]:[course()]};
      else if(url==='/api/plans')data={plans:[]};
      else if(url.startsWith('/api/study-materials/biaoda/'))data={content:'# 合成练习',lesson,record:null};
      else throw Error('Unexpected request: '+url);
      return {ok:true,json:async()=>data};
    }};
  vm.createContext(context);
  for(const file of ['daily-agenda.js','learning-completion.js','daily-learning.js'])vm.runInContext(source(file),context,{filename:file});
  await window.loadDailyLearning();
  window.DailyAgenda.render();
  return {window,context,element,requests,intervals,messages,get refreshes(){return refreshes;},get snapshot(){return snapshot;},setRefreshFailure:value=>refreshFailure=value,
    gatePost:()=>{let resolve;postGate=new Promise(r=>resolve=r);return resolve;}};
}
async function studyCompletion({serverWarning='',refreshFailure=false}={}){
  const env=await dailyEnvironment({serverWarning,refreshFailure});
  assert(env.element('agendaList').textContent.includes('正在进行'));
  await env.window.openStudyCourse('biaoda','Day 001.md');
  assert.equal(env.intervals.size,1,'the real reader starts its learning timer');
  const save=findButton(env.element('dailyReader'),'标记学完并保存');assert(save,'real reader exposes the completion action');
  const release=env.gatePost(),saving=save.onclick();await flush();
  await save.onclick();assert.equal(env.requests.filter(r=>r.method==='POST').length,1,'double clicks during a pending save cannot duplicate the completion POST');
  release();await saving;
  assert(env.refreshes>0,'the actual producer must refresh dependent action state after saving');
  assert(env.element('dailyReader').textContent.includes('学习记录已保存'),'an arrangement warning must not turn a durable course save into failure');
  assert(!env.element('dailyReader').textContent.includes('保存未完成'));
  assert.equal(env.requests.filter(r=>r.method==='POST').length,1);
  if(serverWarning||refreshFailure){assert.equal(env.element('learningSyncStatus').hidden,false);assert(env.element('learningSyncMessage').textContent.includes('已保存'));}
  if(refreshFailure){env.setRefreshFailure(false);await env.window.retryLearningCompletion();assert.equal(env.element('learningSyncStatus').hidden,true,'state refresh failure can recover without resubmitting completion');}
  assert.equal(env.snapshot.execution,null,'successful refresh clears the old running execution');
  assert(env.element('agendaList').textContent.includes('已完成'),'the real agenda immediately renders completion');
  assert(!env.element('agendaList').textContent.includes('正在进行'));
  assert.equal(env.element('actionExecution').hidden,true);
  await findButton(env.element('dailyReader'),'返回今日安排').onclick();
  assert.equal(env.intervals.size,0,'leaving after save clears the reader timer');
  assert(!env.element('agendaList').textContent.includes('正在进行'),'returning to today must retain the completed state');
  assert.equal(env.requests.filter(r=>r.method==='POST').length,1,'returning or retrying state refresh never reposts completion');
}
async function lostCompletionResponse(){
  const env=await dailyEnvironment({lostResponse:true});
  await env.window.openStudyCourse('biaoda','Day 001.md');
  const save=findButton(env.element('dailyReader'),'标记学完并保存');
  await save.onclick();
  assert(env.element('dailyReader').textContent.includes('保存未完成，笔记仍保留'));
  assert.equal(env.refreshes,0,'an uncertain save cannot claim confirmed synchronization');
  await save.onclick();
  const posts=env.requests.filter(r=>r.method==='POST');
  assert.equal(posts.length,2,'a lost response permits one explicit transport retry');
  assert.equal(posts[0].body,posts[1].body,'retry preserves the original idempotency key, revision, time and content');
  assert.equal(env.snapshot.execution,null,'the confirmed retry clears the stale execution');
  assert(env.element('dailyReader').textContent.includes('学习记录已保存'));
}
async function transportProducers(){
  const cases=[
    ['copilot.js','  async function request(', '  function button(', 'request',[
      ['/lessons/7/complete','POST',{}],['/lessons/7/review','POST',{answers:{}}],['/lessons/7/summary','POST',{summary_text:'完成总结'}],['/lessons/7/learning-state','PATCH',{state:'unknown'}]],
      [['/lessons/7','GET'],['/settings','PUT',{}]]],
    ['plans.js','  async function api(', '  function button(', 'api',[
      ['/plan-one/lessons/7/feedback',{state:'completed'}],['/plan-one/lessons/7/feedback',{state:'unknown'}]],
      [['/plan-one/lessons/7'],['/plan-one/settings',{}]]],
    ['reading.js','  async function api(', '  function button(', 'api',[
      ['/articles/article-one/personal',{read:true}],['/articles/article-one/personal',{read:false}],['/articles/article-one/feedback',{mark_read:true}]],
      [['/articles/article-one'],['/articles/article-one/personal',{bookmarked:true}],['/articles/article-one/feedback',{mark_read:false}]]]
  ];
  for(const [file,start,end,name,completions,unrelated] of cases){
    const calls=[],posts=[];let ok=true;
    const result={arrangement_sync_error:'完成记录已保存，日期安排暂未同步。'};
    const context={crypto:require('node:crypto').webcrypto,window:{refreshLearningCompletion:async value=>{calls.push(value);return result.arrangement_sync_error;}},invalidateLibrary(){},
      fetch:async(url,options)=>{posts.push({url,options});return{ok,status:ok?200:409,json:async()=>result};}};
    vm.createContext(context);const code=source(file);vm.runInContext(code.slice(code.indexOf(start),code.indexOf(end)),context,{filename:file});
    for(const args of completions){const previous=calls.length;assert.equal(await context[name](...args),result,file+' returns the durable save result even with a sync warning');assert.equal(calls.length,previous+1,file+' completion/retraction refreshes dependent views');}
    for(const args of unrelated){const previous=calls.length;await context[name](...args);assert.equal(calls.length,previous,file+' reads and unrelated writes must not claim a new completion');}
    ok=false;const previous=calls.length;await assert.rejects(context[name](...completions[0]));assert.equal(calls.length,previous,file+' rejected saves do not refresh a nonexistent completion');
    assert.equal(posts.length,completions.length+unrelated.length+1,file+' uses one transport request per user action');
  }
}
async function legacyQuickCompletion(){
  const env=await dailyEnvironment({renzhi:true});
  const module=env.window.DailyLearning.snapshot().modules.find(m=>m.id==='renzhi');
  // Course cards delegate lesson controls to the actual course-detail row producer.
  env.window.DailyLearning.lessonRow(env.element('view-course'),module,module.lessons[0]);
  const quick=findButton(env.element('view-course'),'标记完成');assert(quick,'historical completion without a durable timestamp retains its confirmation entrance');
  await quick.onclick();
  assert.equal(env.requests.filter(r=>r.method==='POST').length,1);
  assert.equal(env.refreshes,1,'the historical quick-complete entrance must synchronize actions as other completion entrances do');
  assert.equal(env.snapshot.execution,null);
}
(async()=>{
  await studyCompletion();
  await studyCompletion({serverWarning:'课程完成记录已保存，日期安排暂未同步。'});
  await studyCompletion({refreshFailure:true});
  await lostCompletionResponse();
  await transportProducers();
  await legacyQuickCompletion();
  console.log('Completion producers passed: actual course-save handler, double click, sync warnings/recovery, return navigation and copilot/plan/article/legacy completion producers.');
})().catch(error=>{console.error(error);process.exitCode=1;});
