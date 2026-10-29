/* 私人依据面板：延迟读取、安全展示、原记录跳转及账号切换隔离。 */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element{
  constructor(tag){this.tagName=tag;this.children=[];this.text='';this.style={};this.isConnected=true;this.open=false;this.listeners={};}
  append(...nodes){this.children.push(...nodes);for(const node of nodes)node.parent=this;}
  replaceChildren(...nodes){this.children=[];this.text='';this.append(...nodes);}
  set textContent(value){this.text=String(value);this.children=[];}get textContent(){return this.text+this.children.map(n=>n.textContent).join('');}
  addEventListener(type,fn){this.listeners[type]=fn;}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(c=>c!==this);this.isConnected=false;}
}
function environment(){
  const root=new Element('div'),requests=[],opened=[];let reply;
  const window={Account:{user:{id:'one'}},RecordDiscovery:{open:value=>opened.push(value)}};
  const context={window,document:{createElement:tag=>new Element(tag)},URLSearchParams,
    fetch:async(url,options)=>{requests.push({url,options});return {ok:true,json:async()=>reply()};}};
  vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/ai-evidence.js'),'utf8'),context);
  return {root,window,requests,opened,reply:value=>{reply=typeof value==='function'?value:()=>value;}};
}
const all=el=>[el,...el.children.flatMap(all)];
const data={items:[{captured_at:'2026-10-28',timezone:'Asia/Shanghai',model:'fixture',prompt_version:'v1',input_hash:'HASH',selection:{scope:'仅选定正文'},
  sources:[{label:'选定原文',scope:'前12000字符',availability:'changed',truncated:true,target:{kind:'reflection',id:'one'}},{label:'已删除原文',scope:'本次片段',availability:'deleted',truncated:false}],
  messages:[{role:'system',content:'SYSTEM_ONLY'},{role:'user',content:'<img src=x onerror=STEAL()> PRIVATE INPUT'}]}]};
(async()=>{
  let env=environment();env.reply(data);const panel=env.window.AIEvidence.mount(env.root,'reflection','task-one');
  assert.equal(env.requests.length,0,'collapsed evidence does not read private inputs');panel.open=true;await panel.listeners.toggle();
  assert.equal(env.requests.length,1);assert.equal(env.requests[0].options.cache,'no-store');
  assert(env.root.textContent.includes('原记录已变化'));assert(env.root.textContent.includes('原记录已删除'));assert(env.root.textContent.includes('已截取'));
  const pre=all(panel).find(el=>el.tagName==='pre');assert.equal(pre.textContent,'<img src=x onerror=STEAL()> PRIVATE INPUT');assert.equal(pre.children.length,0,'model inputs remain literal text');
  assert(!env.root.textContent.includes('SYSTEM_ONLY'));await all(panel).find(el=>el.tagName==='button').onclick();assert.equal(env.opened[0].target.id,'one');
  await panel.listeners.toggle();assert.equal(env.requests.length,1,'expanded panel does not repeatedly reload');
  env=environment();env.reply({legacy:true,message:'此历史结果未记录完整证据快照。',items:[]});const old=env.window.AIEvidence.mount(env.root,'reading-result','old');old.open=true;await old.listeners.toggle();assert(env.root.textContent.includes('未记录完整证据快照'));
  env=environment();let finish;env.reply(()=>new Promise(resolve=>finish=resolve));const switching=env.window.AIEvidence.mount(env.root,'reflection','task-one');switching.open=true;const waiting=switching.listeners.toggle();await new Promise(resolve=>setImmediate(resolve));env.window.Account.user.id='two';finish(data);await waiting;assert(!env.root.textContent.includes('PRIVATE INPUT'),'late private response cannot display under another account');
  console.log('AI evidence panel passed: lazy reads, changed/deleted sources, safe text, links, legacy compatibility and account switching.');
})().catch(error=>{console.error(error);process.exitCode=1;});
