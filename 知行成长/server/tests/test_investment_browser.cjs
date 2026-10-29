const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {webcrypto}=require('node:crypto');
const events=new EventTarget();
const ctx={window:null,crypto:webcrypto,TextEncoder,TextDecoder,URL,AbortController,Event,setTimeout,clearTimeout,setInterval,clearInterval,
  addEventListener:events.addEventListener.bind(events),removeEventListener:events.removeEventListener.bind(events),dispatchEvent:events.dispatchEvent.bind(events),
  document:{querySelector:()=>null},Account:{user:{id:'alice'}}};ctx.window=ctx;
vm.createContext(ctx);
for(const file of ['investment-browser-core.js','investment-browser.js'])vm.runInContext(fs.readFileSync('static/'+file,'utf8'),ctx);
const core=ctx.InvestmentBrowserCore,runtime=ctx.InvestmentBrowser;
const clone=v=>JSON.parse(JSON.stringify(v));
const bundle={algorithm:core.algorithm,request:{as_of:'2026-10-26',conditions:[],combine:'all',sort_by:'turnover_cny',descending:true,limit:5},
 universe:[{instrument_id:'i',market:'SSE',kind:'etf',name:'Synthetic',bars:[{date:'2026-10-26',close:'11',turnover_cny:'1100',volume_shares:'100'}]}]};
const cfg=core.modelConfig({api_base_url:'https://model.example/v1',model_name:'test',api_key:'BROWSER_PRIVATE_KEY'});
async function fixture(){
 const cp={account:'alice',storage_key:'alice:cp',create_key:'stable-create',config_hash:await runtime.configHash(cfg),candidates:{},
   create:{executor:'test-executor-unique',model:'test'}};
 const calls=[],uploads=[],checkpoints=[];let stage='analysis',ready=false,cancelled=false,models=0,lose=false,loseFinal=false;
 const io={verify:async()=>{},save:async c=>{checkpoints.push(clone(c));},
  api:async(account,path,body,key)=>{
   assert.equal(account,'alice');calls.push({path,body:clone(body||null),key});
   if(path==='local-runs')return {id:'run',protocol_version:1,algorithm:core.algorithm};
   if(path==='local-runs/run')return {id:'run',state:cancelled?'cancelled':ready?'ready':'screened'};
   if(path.endsWith('/inputs'))return {input_hash:'screen-hash',bundle};
   if(path.endsWith('/screening'))return {id:'run',protocol_version:1,algorithm:core.algorithm,screening:body};
   if(path.includes('/candidates/'))return {id:'job',state:ready?'ready':'queued'};
   if(path.endsWith('/input'))return {stage,evidence:{model:'test',prompt_version:'investment-v5',input_hash:stage+'-hash',messages:[{role:'user',content:'frozen '+stage}]}};
   if(path.endsWith('/draft')){stage='countercheck';uploads.push(clone({body,key}));if(lose){lose=false;throw Error('lost response after commit');}return {id:'job',state:'running'};}
   if(path.endsWith('/result')){ready=true;uploads.push(clone({body,key}));if(loseFinal){loseFinal=false;throw Error('lost final receipt');}return {id:'job',state:'ready'};}
   throw Error('Unexpected API '+path);
  },model:async(messages,config)=>{models++;assert.equal(config.key,'BROWSER_PRIVATE_KEY');return JSON.stringify({text:messages[0].content});}};
 return {cp,io,calls,uploads,checkpoints,get models(){return models},lose:()=>{lose=true},loseFinal:()=>{loseFinal=true},cancel:()=>{cancelled=true}};
}
async function showPreview(f){await runtime.execute(f.cp,cfg,()=>{},{stopped:false,previewOnly:true},f.io);}
async function accountHarness(){
 const nodes=new Map(),notifications=[],requests=[],redirects=[],sessions=[],hub=new EventTarget();let identity='alice';
 const node=()=>({textContent:'',value:'',after(){},remove(){},append(){},focus(){},setAttribute(){},querySelector(){return node();}});
 const get=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id)};
 const page={window:null,URL,Headers,Request,Event,
  location:{href:'https://platform.example/',origin:'https://platform.example',hash:'',replace:v=>redirects.push(v)},
  document:{querySelector:get,getElementById:get,createElement:node,body:{append:n=>notifications.push(n)}},
  localStorage:{setItem:(key,value)=>sessions.push({key,value})},
  addEventListener:hub.addEventListener.bind(hub),dispatchEvent:hub.dispatchEvent.bind(hub),
  fetch:async(url,options={})=>{
   requests.push({url,options});
   if(url==='/api/auth/logout'){identity=null;return new Response('{}');}
   assert.equal(url,'/api/auth/me');
   if(!identity)return new Response('{}',{status:401});
   const expected=new Headers(options.headers).get('X-Account-Id');
   if(expected&&expected!==identity)return new Response('{}',{status:409,headers:{'X-Account-Changed':'1'}});
   return new Response(JSON.stringify({user:{id:identity,username:identity}}));
  }};page.window=page;vm.createContext(page);
 vm.runInContext(fs.readFileSync('static/account.js','utf8'),page);await page.Account.ready;
 return {page,requests,redirects,notifications,sessions,setIdentity:id=>{identity=id}};
}
(async()=>{
 const auth=await accountHarness();let sessionEvents=0;
 auth.page.addEventListener('account-session-changed',()=>sessionEvents++);
 await auth.page.Account.verify('alice');
 assert.equal(new Headers(auth.requests.at(-1).options.headers).get('X-Account-Id'),'alice');
 auth.setIdentity('bob');await assert.rejects(auth.page.Account.verify('alice'));
 assert.equal(auth.page.Account.isCurrent('alice'),false);assert.equal(sessionEvents,1);
 const tab=await accountHarness(),beforeStorage=tab.requests.length;
 const storageEvent=new Event('storage');storageEvent.key='grow-account-session';tab.page.dispatchEvent(storageEvent);
 assert.equal(tab.page.Account.isCurrent('alice'),false);
 await assert.rejects(tab.page.Account.verify('alice'));assert.equal(tab.requests.length,beforeStorage);
 const expired=await accountHarness();expired.setIdentity(null);
 await assert.rejects(expired.page.Account.verify('alice'));
 assert.equal(expired.page.Account.isCurrent('alice'),false);assert.deepEqual(expired.redirects,['/login']);
 const logout=await accountHarness();await logout.page.Account.logout();
 assert.equal(logout.sessions[0].key,'grow-account-session');assert.equal(logout.page.Account.isCurrent('alice'),false);
 const result=core.screen(bundle);assert.equal(result.total,1);assert.equal(result.items[0].values.close,'11');
 const precise=clone(bundle);precise.universe[0].bars[0].close='99999999999999999999.0000000001';
 precise.request.conditions=[{field:'close',op:'gt',value:'99999999999999999999'}];
 assert.equal(core.screen(precise).total,1,'large decimal comparisons must not lose precision');
 const unknown=clone(bundle);unknown.request.conditions=[{field:'price_above_ma20',op:'eq',value:'true'}];
 assert.equal(core.screen(unknown).unresolved,1);assert.equal(core.screen(unknown).total,0);
 const fractional=clone(bundle);fractional.universe[0].bars.unshift({date:'2026-10-25',close:'3',turnover_cny:'1',volume_shares:'100'});
 fractional.request.conditions=[{field:'close_change_pct',op:'gt',value:'266.666666666666666666666666666666666666666666666'}];
 assert.equal(core.screen(fractional).total,1,'comparison uses exact ratio, not rounded display');
 const future=clone(bundle);future.universe[0].bars.push({date:'2026-10-27',close:'999',turnover_cny:'9999',volume_shares:'100'});
 assert.equal(core.screen(future).items[0].data_date,'2026-10-26');
 const bars=Array.from({length:20},(_,i)=>({date:'2026-10-'+String(i+1).padStart(2,'0'),close:String(i+1),turnover_cny:'100',volume_shares:'100'}));
 assert.equal(core.metrics({...bundle.universe[0],bars},'2026-10-26').values.price_above_ma20,true);
 assert.equal(core.metrics({...bundle.universe[0],bars},'2026-10-26').values.volume_ratio_5,'1');
 for(const url of ['http://192.168.1.1/v1','https://user:pass@example.org/v1','https://example.org/v1?key=secret','https://example.org/v1\n']){
  assert.throws(()=>core.modelConfig({api_base_url:url,model_name:'x'}));
 }
 ctx.location={origin:'https://platform.example'};
 assert.throws(()=>core.modelConfig({api_base_url:'https://platform.example/api',model_name:'x'}));
 assert.equal(core.modelConfig({api_base_url:'http://127.0.0.1:11434/v1',model_name:'local'}).key,'');
 let modelRequest;
 const raw=await core.model([{role:'user',content:'frozen'}],cfg,undefined,async(url,options)=>{
  modelRequest={url,options};return new Response(JSON.stringify({choices:[{finish_reason:'stop',message:{content:'response'}}]}));
 });
 assert.equal(raw,'response');assert.equal(modelRequest.options.credentials,'omit');assert.equal(modelRequest.options.redirect,'error');
 assert.equal(modelRequest.options.headers['X-Account-Id'],undefined);assert.equal(modelRequest.options.headers['X-Copilot-Request'],undefined);
 assert.equal(JSON.parse(modelRequest.options.body).stream,false);
 const happy=await fixture();await showPreview(happy);await runtime.execute(happy.cp,cfg,()=>{},{stopped:false},happy.io);
 assert.equal(happy.models,2);assert.equal(happy.cp.candidates.i.job.state,'ready');
 assert.doesNotMatch(JSON.stringify(happy.calls)+JSON.stringify(happy.checkpoints),/BROWSER_PRIVATE_KEY/);
 const preview=await fixture(),shown=[];
 await runtime.execute(preview.cp,cfg,(_text,input)=>{if(input)shown.push(input);},{stopped:false,previewOnly:true},preview.io);
 assert.equal(preview.models,0);assert.equal(shown.length,1);
 await runtime.execute(preview.cp,cfg,()=>{},{stopped:false,previewOnly:false},preview.io);assert.equal(preview.models,2);
 const lost=await fixture();await showPreview(lost);lost.lose();await runtime.execute(lost.cp,cfg,()=>{},{stopped:false},lost.io);
 assert.equal(lost.models,1);assert.ok(lost.cp.candidates.i.pending);
 const frozenUpload=clone(lost.uploads[0]);await showPreview(lost);
 assert.equal(lost.models,1,'restoring an upload and preview does not call the counter model');assert.deepEqual(lost.uploads[1],frozenUpload);
 await runtime.execute(lost.cp,cfg,()=>{},{stopped:false},lost.io);assert.equal(lost.models,2);
 const lostFinal=await fixture();await showPreview(lostFinal);lostFinal.loseFinal();
 await runtime.execute(lostFinal.cp,cfg,()=>{},{stopped:false},lostFinal.io);
 assert.equal(lostFinal.models,2);assert.ok(lostFinal.cp.candidates.i.pending);
 const finalReceipt=clone(lostFinal.uploads.at(-1));await showPreview(lostFinal);
 assert.equal(lostFinal.models,2);assert.deepEqual(lostFinal.uploads.at(-1),finalReceipt);
 assert.equal(lostFinal.cp.candidates.i.job.state,'ready');
 const interrupted=await fixture();await showPreview(interrupted);interrupted.io.model=async()=>{throw Error('request outcome unknown')};
 await runtime.execute(interrupted.cp,cfg,()=>{},{stopped:false},interrupted.io);
 interrupted.io.model=async()=>{assert.fail('must not retry uncertain call')};
 await runtime.execute(interrupted.cp,cfg,()=>{},{stopped:false},interrupted.io);
 assert.ok(interrupted.cp.candidates.i.started);assert.match(interrupted.cp.candidates.i.error,/未确认/);
 const stale=await fixture();await showPreview(stale);const oldCard=clone(stale.cp);
 stale.io.model=async()=>{throw Error('call outcome unknown while platform offline')};
 await runtime.execute(stale.cp,cfg,()=>{},{stopped:false},stale.io);
 stale.io.read=async()=>clone(stale.cp);
 stale.io.model=async()=>{assert.fail('stale history card must not erase the latest call marker')};
 await runtime.execute(oldCard,cfg,()=>{},{stopped:false},stale.io);
 const noDisk=await fixture();await showPreview(noDisk);noDisk.io.save=async c=>{if(c.candidates.i?.started)throw Error('disk denied')};
 await assert.rejects(runtime.execute(noDisk.cp,cfg,()=>{},{stopped:false},noDisk.io));assert.equal(noDisk.models,0);
 const cancelled=await fixture();await showPreview(cancelled);cancelled.cancel();
 await assert.rejects(runtime.execute(cancelled.cp,cfg,()=>{},{stopped:false},cancelled.io));assert.equal(cancelled.models,0);
 const switched=await fixture();await showPreview(switched);switched.io.model=async()=>{ctx.Account.user={id:'bob'};return 'received before upload'};
 await assert.rejects(runtime.execute(switched.cp,cfg,()=>{},{stopped:false},switched.io));
 assert.equal(switched.uploads.length,0);ctx.Account.user={id:'alice'};
 const missingPreview=await fixture();
 await runtime.execute(missingPreview.cp,cfg,()=>{},{stopped:false},missingPreview.io);
 assert.equal(missingPreview.models,0);assert.match(missingPreview.cp.candidates.i.error,/尚未预览/);
 await showPreview(missingPreview);missingPreview.cp.candidates.i.preview_hash='different-input';
 await runtime.execute(missingPreview.cp,cfg,()=>{},{stopped:false},missingPreview.io);assert.equal(missingPreview.models,0);
 const cookieChanged=await fixture();await showPreview(cookieChanged);
 cookieChanged.io.verify=async()=>{throw Error('current cookie no longer matches alice')};
 await runtime.execute(cookieChanged.cp,cfg,()=>{},{stopped:false},cookieChanged.io);
 assert.equal(cookieChanged.models,0);assert.equal(cookieChanged.cp.candidates.i.started,undefined);
 const sessionChanged=await fixture();await showPreview(sessionChanged);let aborted=false;
 sessionChanged.io.model=async(_messages,_config,signal)=>{
  ctx.Account.isCurrent=()=>false;
  ctx.dispatchEvent(new Event('account-session-changed'));
  aborted=signal.aborted;throw Error('aborted on other-tab login');
 };
 await assert.rejects(runtime.execute(sessionChanged.cp,cfg,()=>{},{stopped:false},sessionChanged.io));
 assert.equal(aborted,true);assert.equal(sessionChanged.uploads.length,0);delete ctx.Account.isCurrent;
 const changed=await fixture();await assert.rejects(runtime.execute(changed.cp,{...cfg,model:'different'},()=>{},{stopped:false},changed.io));assert.equal(changed.calls.length,0);
 console.log('Browser investment passed: exact screening, bounded dates, direct credentials, frozen retries, checkpoints, uncertain calls, cancel and account switching.');
})().catch(e=>{console.error(e);process.exitCode=1});
