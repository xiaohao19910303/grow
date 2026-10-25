/* Startup requests may supersede one another before the settings form exists. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');

class Element{
  constructor(tag,text){this.tag=tag;this.textContent=text;this.children=[];this.attributes={};this.value='';}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;}
  setAttribute(name,value){this.attributes[name]=value;}
  addEventListener(){}
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const find=(root,label)=>root.attributes['aria-label']===label?root:root.children.map(child=>find(child,label)).find(Boolean);

(async()=>{
  const card=new Element('section'),settings=new Element('section'),date=new Element('input');date.value='2026-10-24';
  const pending=[];
  const state={date:date.value,preferences:{enabled:false,timezone:'Asia/Shanghai',weekly_target_days:3,review_weekday:7,reminder_enabled:false,reminder_time:null,revision:0}};
  const client={read:async url=>url==='/capabilities'?new Promise((resolve,reject)=>pending.push({resolve,reject})):structuredClone(state),flush(){}};
  const window={Account:{user:{id:'alice'},ready:Promise.resolve({id:'alice'})},RhythmClient:{create:()=>client},EventBus:{on(){}},ActionPlans:{snapshot:()=>({plans:[]})}};
  const context={window,document:{createElement:tag=>new Element(tag),getElementById:id=>({dailyRhythm:card,rhythmSettings:settings,personalDate:date})[id]},crypto:require('node:crypto').webcrypto};
  vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/daily-rhythm.js'),'utf8'),context);
  await tick();assert.equal(pending.length,1);
  const latest=window.DailyRhythm.refresh();await tick();assert.equal(pending.length,2);
  pending[0].resolve({contract_version:1,supported:false,reason:'FEATURE_DISABLED'});await tick();
  assert.equal(find(settings,'开启日常节奏'),undefined);
  pending[1].resolve({contract_version:1,supported:false,reason:'FEATURE_DISABLED'});await latest;
  assert.ok(find(settings,'开启日常节奏'),'The latest successful startup request must make the settings form available.');

  const zone=find(settings,'时区');zone.value='Europe/London';
  const background=window.DailyRhythm.refresh();await tick();
  pending[2].resolve({contract_version:1,supported:false,reason:'FEATURE_DISABLED'});await background;
  assert.equal(find(settings,'时区'),zone,'Background refresh must preserve the current form.');
  assert.equal(zone.value,'Europe/London','Background refresh must preserve unsaved edits.');
  console.log('Rhythm settings: superseded startup response and unsaved-edit protection passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
