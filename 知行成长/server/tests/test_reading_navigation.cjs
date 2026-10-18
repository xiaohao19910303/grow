/* Real navigation code with deferred responses: no browser, network or models. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element {
  constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.attributes={};this.style={};this.dataset={};this.value='';this.text='';this.className='';this.isConnected=true;
    this.classList={add:()=>{},remove:()=>{},toggle:()=>{}};}
  set textContent(value){this.text=String(value);this.children=[];}
  get textContent(){return this.text+this.children.map(n=>n.textContent).join('');}
  append(...items){for(const item of items){const n=typeof item==='string'?Object.assign(new Element('span'),{text:item}):item;n.parent=this;this.children.push(n);}}
  replaceChildren(...items){this.text='';this.children=[];this.append(...items);}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this);this.isConnected=false;}
  setAttribute(key,value){this.attributes[key]=String(value);}
  removeAttribute(key){delete this.attributes[key];}
  querySelectorAll(selector){const match=n=>selector==='button'?n.tagName==='BUTTON':selector==='input'?n.tagName==='INPUT':selector==='h2'?n.tagName==='H2':selector==='[role=status]'?n.attributes.role==='status':false;
    return this.children.flatMap(n=>[...(match(n)?[n]:[]),...n.querySelectorAll(selector)]);}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
}
const root=new Element('section'),requests=[];
const context={window:{Account:{user:{id:'first'}},addEventListener:()=>{}},document:{getElementById:()=>root,createElement:tag=>new Element(tag)},
  location:{hash:'',pathname:'/',search:''},history:{replaceState:()=>{}},toast:()=>{},confirm:()=>true,console,URLSearchParams,Intl,Date,setTimeout,clearTimeout,
  ReadingGrowth:{hasFeedback:()=>false},fetch:async(url,options)=>new Promise(resolve=>requests.push({url,options,resolve:data=>resolve({ok:true,json:async()=>data})}))};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/reading.js'),'utf8'),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const button=text=>{const found=root.querySelectorAll('button').find(n=>n.textContent===text);assert(found,'missing button '+text);return found;};
const page=(title,total=1)=>({articles:[{id:'article-test',title,category:'recent',language:'zh',source:'测试来源',author:'作者',access:'已保存'}],total,page:1,page_size:20});
(async()=>{
  await context.window.loadReading();assert.equal(requests.length,0,'opening reading must never query or collect articles');
  const first=button('查看历史文章').onclick();await flush();assert.equal(requests.length,1);
  assert(root.textContent.includes('正在读取历史文章'),'history must show immediate loading before response');
  assert(requests[0].url.includes('/library?'));requests[0].resolve(page('历史文章 A'));await first;
  assert(root.textContent.includes('历史文章 A'));
  await context.window.loadReading();await context.window.loadReadingHistory('articles');
  assert.equal(requests.length,1,'reopening history must reuse the saved list');
  const refreshing=button('刷新历史记录').onclick();await flush();requests[1].resolve(page('刷新后的文章'));await refreshing;
  assert(root.textContent.includes('刷新后的文章'));
  const input=root.querySelectorAll('input')[0];input.value='旧搜索';input.oninput();const old=input.onkeydown({key:'Enter',preventDefault:()=>{}});await flush();
  input.value='新搜索';input.oninput();input.onkeydown({key:'Enter',preventDefault:()=>{}});await flush();
  requests[3].resolve(page('新搜索结果'));await flush();requests[2].resolve(page('过期结果'));await flush();
  assert(root.textContent.includes('新搜索结果'));assert(!root.textContent.includes('过期结果'),'late search must not replace the latest query');
  const pending=context.window.loadReadingHistory('jobs');await flush();await context.window.loadReading();requests[4].resolve({jobs:[],total:0,page:1,page_size:20});await pending;
  assert(root.textContent.includes('发现新文章'));assert(!root.textContent.includes('共 0 次记录'),'late history must not overwrite another view');
  context.window.Account.user.id='second';const changed=context.window.loadReadingHistory('articles');await flush();
  assert.equal(requests.length,6,'account changes must not reuse another account history');requests[5].resolve({articles:[],total:0,page:1,page_size:20});await changed;
  context.location.hash='#reading/job/job-empty';const job=context.window.enterReading();await flush();
  requests[6].resolve({id:'job-empty',kind:'collect',state:'ready',saved_ids:[],candidates:[{id:'article-new',title:'尚未保存的搜集结果',url:'https://example.org/new'}],sources:[],warnings:[]});await job;
  button('保存选中的文章与资料');assert(!root.textContent.includes('undefined'),'an empty saved_ids array must still allow saving old collection results');
  console.log('Reading navigation checks passed: zero-request entry, cached history, explicit refresh, latest search, navigation and account isolation.');
})().catch(error=>{console.error(error);process.exitCode=1;});
