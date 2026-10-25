const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element{
  constructor(tag){this.tagName=tag;this.children=[];this.dataset={};this.attributes={};this.text='';this.isConnected=true;}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=[];this.text='';this.append(...nodes);}
  set textContent(value){this.text=String(value);this.children=[];}
  get textContent(){return this.text+this.children.map(n=>n.textContent).join('');}
  set innerHTML(_){throw Error('Private course content must use text nodes');}
  setAttribute(key,value){this.attributes[key]=value;}
  querySelector(){return all(this).find(n=>n.attributes.role==='status');}
}
const all=n=>[n,...n.children.flatMap(all)],flush=()=>new Promise(resolve=>setImmediate(resolve));
const plan=()=>({id:'plan-20261025-001',name:'<img src=x onerror=bad()>',version:1,status:'active',linked:true,enabled:true,
  action_management_available:true,total_lessons:2,published_lessons:1,completed_lessons:1,percent:50,missing_action_count:0,
  stages:[{number:1,title:'基础',total_lessons:1,published_lessons:1,completed_lessons:1,percent:100}],
  lessons:[{number:1,title:'已学课程',published:true,learning_state:'completed',action_id:'action-one',action_status:'active',action_changed:true}]});
function environment(){
  let mode='success',resolvePending;const requests=[],events={},opened=[];
  const fetch=async(url,options)=>{requests.push({url,options});if(mode==='pending')return new Promise(resolve=>{resolvePending=resolve;});return {ok:mode!=='error',json:async()=>mode==='error'?{message:'合成错误'}:(options.method==='POST'?plan():{plans:[plan()]})};};
  const window={Account:{user:{id:'alice'},ready:Promise.resolve()},ActionPlans:{refresh:async()=>{},openRecord:async id=>opened.push(id)},EventBus:{on:(name,fn)=>events[name]=fn},openLearningPlan:async id=>opened.push(id)};
  const context={window,fetch,crypto:{randomUUID:()=> 'client-link-key'},document:{createElement:tag=>new Element(tag)},setInterval:()=>{throw Error('No progress polling loop');}};
  vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/learning-plan-actions.js'),'utf8'),context);
  return {window,requests,events,opened,setMode:v=>mode=v,resolve:()=>resolvePending({ok:true,json:async()=>({plans:[plan()]})})};
}
(async()=>{
  let e=environment(),parent=new Element('main');e.window.PlanActions.mount(parent);await flush();
  assert(parent.textContent.includes('<img src=x onerror=bad()>'));assert(parent.textContent.includes('已学完 1/2 课'));
  assert(parent.textContent.includes('关联行动已变化'));assert(parent.textContent.includes('行动待推进'));assert(!parent.textContent.includes('行动已完成'));
  assert.equal(e.requests[0].options.cache,'no-store');
  await all(parent).find(n=>n.tagName==='button'&&n.textContent==='查看第 1 课行动').onclick();assert.deepEqual(e.opened,['action-one']);
  await all(parent).find(n=>n.tagName==='button'&&n.textContent==='同步已发布课程到行动').onclick();
  const write=e.requests.find(r=>r.options.method==='POST');assert.equal(write.options.headers['X-Grow-Action-Schema'],'2');
  assert.deepEqual(JSON.parse(write.options.body).data,{key:'client-link-key',expected_version:1,enabled:true});
  e.setMode('error');await e.window.PlanActions.refresh();assert(parent.textContent.includes('合成错误'));assert(!parent.textContent.includes('50%'));
  e.setMode('success');await all(parent).find(n=>n.tagName==='button'&&n.textContent==='重试读取课程进度').onclick();assert(parent.textContent.includes('50%'));
  e=environment();parent=new Element('main');e.setMode('pending');e.window.PlanActions.mount(parent);await flush();e.window.Account.user.id='bob';e.resolve();await flush();assert(!parent.textContent.includes('<img'));
  e=environment();parent=new Element('main');e.setMode('pending');const section=e.window.PlanActions.mount(parent);await flush();section.isConnected=false;e.resolve();await flush();assert(!parent.textContent.includes('<img'));
  assert(!e.requests.some(r=>r.url.includes('generate')));
  console.log('Learning action client checks passed: safe text, progress, schema/version writes, retry, account and navigation races.');
})().catch(error=>{console.error(error);process.exitCode=1;});
