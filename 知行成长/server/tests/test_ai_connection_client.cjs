/* Control delayed and aborted responses without calling a provider or waiting on real time. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../static/index.html'),'utf8');
const source=html.slice(html.indexOf('function apiSettingsValue(){'),html.indexOf('/* ================= 个人日程'));
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function environment(){
 const ids={};for(const id of ['apiBaseUrl','apiKey','modelName','apiStatus','apiCancelTest','apiSettingsForm'])ids[id]={value:'',textContent:'',hidden:false,addEventListener:(name,fn)=>ids[id][name]=fn};
 ids.apiBaseUrl.value='https://model.example/v1';ids.apiKey.value='TEST_SETUP_PRIVATE_KEY';ids.modelName.value='model-a';
 const buttons=[{disabled:false}],requests=[],timers=new Map(),events={},saved=new Map();
 const window={Account:{user:{id:'alice'}},addEventListener:(event,fn)=>events[event]=fn};
 const context={window,document:{getElementById:id=>ids[id],querySelectorAll:()=>buttons},URL,Event,AbortController,
  localStorage:{getItem:k=>saved.get(k)||null,setItem:(k,v)=>saved.set(k,v),removeItem:k=>saved.delete(k)},toast:()=>{},
  setTimeout:fn=>{const id=timers.size+1;timers.set(id,fn);return id;},clearTimeout:id=>timers.delete(id),
  fetch:(url,options)=>new Promise(resolve=>requests.push({url,options,resolve}))};
 vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/ai-config.js'),'utf8'),context);context.AIConfig=window.AIConfig;vm.runInContext(source,context);
 return {context,window,ids,buttons,requests,timers,saved,events,resolve:(ok=true,status=true)=>requests.at(-1).resolve({ok:status,json:async()=>({ok,message:'PRIVATE PROVIDER ECHO'})})};
}
(async()=>{
 let e=environment();const first=e.context.testApiConnection();await e.context.testApiConnection();assert.equal(e.requests.length,1);assert.equal(e.buttons[0].disabled,true);e.resolve();await first;assert(e.ids.apiStatus.textContent.includes('连接成功'));assert(!e.ids.apiStatus.textContent.includes('PRIVATE'));assert.equal(e.saved.size,0);
 let pending=e.context.testApiConnection();e.ids.modelName.value='model-b';e.ids.apiSettingsForm.input();const changed=e.ids.apiStatus.textContent;e.resolve();await pending;assert.equal(e.ids.apiStatus.textContent,changed);assert(!changed.includes('连接成功'));
 pending=e.context.testApiConnection();e.window.Account.user.id='bob';e.resolve();await pending;assert(!e.ids.apiStatus.textContent.includes('连接成功'));assert(!e.ids.apiStatus.textContent.includes('正在测试'),'Account changes must not leave a completed test labelled running');
 e=environment();pending=e.context.testApiConnection();[...e.timers.values()][0]();e.resolve();await pending;assert(e.ids.apiStatus.textContent.includes('超时'));assert(!e.ids.apiStatus.textContent.includes('连接成功'));
 e=environment();pending=e.context.testApiConnection();e.context.cancelApiTest('测试已取消');e.resolve();await pending;assert.equal(e.ids.apiStatus.textContent,'测试已取消');assert.equal(e.buttons[0].disabled,false);
 e=environment();pending=e.context.testApiConnection();e.resolve(true,false);await pending;assert(e.ids.apiStatus.textContent.includes('连接失败'));
 e=environment();e.ids.apiBaseUrl.value='http://invalid.example';await e.context.testApiConnection();assert.equal(e.requests.length,0);assert(e.ids.apiStatus.textContent.includes('HTTPS'));
 e=environment();e.saved.set('zhixing-ai-config-v1:alice',JSON.stringify({api_base_url:'https://model.example/v1',api_key:'TEST_SETUP_KEY',model_name:'saved-model'}));e.window.Account.user=null;
 let ready;e.window.Account.ready=new Promise(resolve=>ready=resolve);e.context.loadApiSettings();e.window.Account.user={id:'alice'};ready();await flush();assert.equal(e.ids.modelName.value,'saved-model','Reading before identity resolves must restore that account after login readiness');
 console.log('AI connection client passed: no automatic calls, duplicate suppression, stale/account/timeout/cancel safety and sanitized failures.');
})().catch(error=>{console.error(error);process.exitCode=1;});
