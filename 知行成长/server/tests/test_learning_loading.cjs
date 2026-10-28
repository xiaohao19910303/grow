/* A slow module must not block other modules or duplicate navigation requests. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element{
  constructor(tag){this.tagName=tag;this.children=[];this.text='';this.dataset={};this.style={};this.classList={add:()=>{}};}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;this.text='';}
  set textContent(value){this.text=String(value);this.children=[];}
  get textContent(){return this.text+this.children.map(n=>n.textContent||'').join('');}
  querySelectorAll(){return [];}
  querySelector(){return null;}
  setAttribute(){}
}
const elements=new Map(),requests=[];
const element=id=>{if(!elements.has(id))elements.set(id,new Element('div'));return elements.get(id);};
let plans=[];
const actionPlans={snapshot:()=>({plans,execution:null}),day:()=> '2026-10-20'};
const context={window:{addEventListener:()=>{},ActionPlans:actionPlans},ActionPlans:actionPlans,document:{head:new Element('head'),getElementById:element,createElement:tag=>new Element(tag)},setTimeout,clearTimeout,setInterval,clearInterval,console,
  fetch:async url=>new Promise(resolve=>requests.push({url,resolve:data=>resolve({ok:true,json:async()=>data})}))};
const librarySnapshots=[];
context.window.CourseLibrary={render:()=>{const snapshot=context.window.DailyLearning?.snapshot();if(snapshot)librarySnapshots.push(snapshot);}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/daily-agenda.js'),'utf8'),context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/daily-learning.js'),'utf8'),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const courseModule=(title)=>({id:'biaoda',name:title,duration:'15 分钟',lessons:[{lesson_no:1,filename:'Day 001.md',topic:'第一课',learning_state:'unknown',learning_label:'待本人反馈'}]});
(async()=>{
  assert.equal(requests.length,3);const shared=context.window.loadDailyLearning();assert.equal(requests.length,3,'navigation shares the pending request');
  requests[1].resolve({modules:[courseModule('结构化表达')]});await flush();
  assert(element('dailyLearning').textContent.includes('结构化表达'),'available courses render while plans are pending');
  assert(librarySnapshots.at(-1).pending.includes('课程规划'),'the course renderer receives pending sources');
  const newer=context.window.loadDailyLearning({force:true});assert.equal(requests.length,6);
  requests[4].resolve({modules:[courseModule('更新后的课程')]});await flush();
  requests[0].resolve({lessons:[]});requests[2].resolve({plans:[]});await shared;
  assert(element('dailyLearning').textContent.includes('更新后的课程'),'an old refresh cannot replace the new module list');
  requests[3].resolve({lessons:[]});requests[5].resolve({plans:[]});await newer;
  assert(!element('dailyLearning').textContent.includes('正在读取'));
  element('view-action-schedule').style.display='none';
  const target={kind:'biaoda',course:'Day 001.md'};
  const scheduled={id:'scheduled',period:'day',completion_mode:'content',status:'active',start_date:'2026-10-20',target,title:'第一课',progress:{minutes:0}};
  const rerender=()=>context.window.DailyAgenda.render();
  for(const date of ['2026-10-19','2026-10-20','2026-10-21']){
    plans=[{...scheduled,start_date:date}];rerender();
    assert.equal(element('dailyLearning').textContent.includes('第一课'),date!=='2026-10-20','only the displayed date excludes an arranged course');
    if(date==='2026-10-19')assert(element('dailyLearning').textContent.includes('过去安排待处理'));
    if(date==='2026-10-21')assert(element('dailyLearning').textContent.includes('已安排明日'));
    assert(librarySnapshots.at(-1).modules.some(module=>module.lessons.some(lesson=>lesson.topic==='第一课')),'the course renderer receives scheduled lessons even when the home candidate is filtered');
  }
  plans=[scheduled];rerender();
  assert(element('agendaList').textContent.includes('第一课'),'today keeps the scheduled course');
  plans=[{...scheduled,completion_mode:'time'}];rerender();
  assert(!element('dailyLearning').textContent.includes('第一课'),'a timed course scheduled today also stays in the agenda');
  for(const status of ['paused','completed']){
    plans=[{...scheduled,status}];rerender();
    assert(!element('dailyLearning').textContent.includes('第一课'),'paused and completed same-date arrangements remain in the upper agenda');
  }
  element('personalDate').value='2026-10-21';rerender();
  assert(element('dailyLearning').textContent.includes('第一课'),'viewing another date retains the other-date course as a candidate');
  plans=[{...scheduled,start_date:'2026-10-21'}];rerender();
  assert(!element('dailyLearning').textContent.includes('第一课'),'the selected date is used rather than always hiding today');
  element('personalDate').value='';
  for(const replacement of [[],[{...scheduled,status:'archived'}],[{...scheduled,start_date:null}],[{...scheduled,target:{kind:'biaoda',course:'other.md'}}]]){
    plans=replacement;rerender();
    assert(element('dailyLearning').textContent.includes('第一课'),'cancelling or an unrelated arrangement restores optional learning');
  }
  console.log('Learning loading checks passed: partial modules, shared requests, mutation refresh and stale-response protection.');
  console.log('Optional learning checks passed: date filtering, cancellation, source identity, agenda and library visibility.');
})().catch(error=>{console.error(error);process.exitCode=1;});
