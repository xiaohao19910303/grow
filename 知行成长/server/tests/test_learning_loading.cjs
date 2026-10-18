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
const context={window:{addEventListener:()=>{}},document:{getElementById:element,createElement:tag=>new Element(tag)},setTimeout,clearTimeout,setInterval,clearInterval,console,
  fetch:async url=>new Promise(resolve=>requests.push({url,resolve:data=>resolve({ok:true,json:async()=>data})}))};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/daily-learning.js'),'utf8'),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const courseModule=(title)=>({id:'biaoda',name:title,duration:'15 分钟',lessons:[{lesson_no:1,filename:'Day 001.md',topic:'第一课',learning_state:'unknown',learning_label:'待本人反馈'}]});
(async()=>{
  assert.equal(requests.length,3);const shared=context.window.loadDailyLearning();assert.equal(requests.length,3,'navigation shares the pending request');
  requests[1].resolve({modules:[courseModule('结构化表达')]});await flush();
  assert(element('dailyLearning').textContent.includes('结构化表达'),'available courses render while plans are pending');
  assert(element('dailyLearning').textContent.includes('正在读取学习计划'));
  const newer=context.window.loadDailyLearning({force:true});assert.equal(requests.length,6);
  requests[4].resolve({modules:[courseModule('更新后的课程')]});await flush();
  requests[0].resolve({lessons:[]});requests[2].resolve({plans:[]});await shared;
  assert(element('dailyLearning').textContent.includes('更新后的课程'),'an old refresh cannot replace the new module list');
  requests[3].resolve({lessons:[]});requests[5].resolve({plans:[]});await newer;
  assert(!element('dailyLearning').textContent.includes('正在读取'));
  console.log('Learning loading checks passed: partial modules, shared requests, mutation refresh and stale-response protection.');
})().catch(error=>{console.error(error);process.exitCode=1;});
