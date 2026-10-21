/* A slow module must not block other modules or duplicate navigation requests. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element{
  constructor(tag){this.tagName=tag;this.children=[];this.text='';this.dataset={};this.style={};this.classList={add:()=>{}};}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;this.text='';}
  set textContent(value){this.text=String(value);this.children=[];}
  get textContent(){return this.text+this.children.map(n=>n.textContent||'').join('');}
  querySelectorAll(){return [];}
  setAttribute(){}
}
const elements=new Map(),requests=[];
const element=id=>{if(!elements.has(id))elements.set(id,new Element('div'));return elements.get(id);};
let plans=[];
const actionPlans={snapshot:()=>({plans,execution:null}),day:()=> '2026-10-20'};
const context={window:{addEventListener:()=>{},ActionPlans:actionPlans},ActionPlans:actionPlans,document:{head:new Element('head'),getElementById:element,createElement:tag=>new Element(tag)},setTimeout,clearTimeout,setInterval,clearInterval,console,
  fetch:async url=>new Promise(resolve=>requests.push({url,resolve:data=>resolve({ok:true,json:async()=>data})}))};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/daily-agenda.js'),'utf8'),context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/daily-learning.js'),'utf8'),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const courseModule=(title)=>({id:'biaoda',name:title,duration:'15 分钟',lessons:[{lesson_no:1,filename:'Day 001.md',topic:'第一课',learning_state:'unknown',learning_label:'待本人反馈'}]});
(async()=>{
  assert.equal(requests.length,3);const shared=context.window.loadDailyLearning();assert.equal(requests.length,3,'navigation shares the pending request');
  requests[1].resolve({modules:[courseModule('结构化表达')]});await flush();
  assert(element('dailyLearning').textContent.includes('结构化表达'),'available courses render while plans are pending');
  assert(element('learningLibrary').textContent.includes('正在读取课程计划'));
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
    assert(!element('dailyLearning').textContent.includes('第一课'),'a dated course is excluded from optional learning');
    assert(element('learningLibrary').textContent.includes('第一课'),'the full library keeps scheduled courses');
  }
  plans=[scheduled];rerender();
  assert(element('agendaList').textContent.includes('第一课'),'today keeps the scheduled course');
  for(const replacement of [[],[{...scheduled,status:'archived'}],[{...scheduled,start_date:null}],[{...scheduled,target:{kind:'biaoda',course:'other.md'}}]]){
    plans=replacement;rerender();
    assert(element('dailyLearning').textContent.includes('第一课'),'cancelling or an unrelated arrangement restores optional learning');
  }
  console.log('Learning loading checks passed: partial modules, shared requests, mutation refresh and stale-response protection.');
  console.log('Optional learning checks passed: date filtering, cancellation, source identity, agenda and library visibility.');
})().catch(error=>{console.error(error);process.exitCode=1;});
