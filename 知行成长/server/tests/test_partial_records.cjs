const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('static/index.html','utf8');
function fixture(response){
 const statuses=[],toasts=[],calls=[],nodes={legacyConflict:{hidden:true},resetResult:{textContent:''}};
 const state={_revision:'v1',modules:[{id:'m'}],checkins:{},habits:{},customFields:[],customRecords:[],decisions:[],predictions:[],reviews:[{id:7,thought:'keep me'}],insights:[],todos:[]};
 const c={state,dataLoaded:true,saveInFlight:false,legacyConflict:false,editGeneration:0,saveTimer:null,
  document:{getElementById:id=>nodes[id],querySelectorAll:()=>[]},clearTimeout:()=>{},setStatus:s=>statuses.push(s),toast:s=>toasts.push(s),render:()=>{},refreshModuleNames:()=>{},closeModal:()=>{c.closed=true},
  fetch:async(url,options)=>{calls.push({url,options});return response(c)},openModal:s=>{c.modal=s}};
 vm.createContext(c);vm.runInContext(html.slice(html.indexOf('function resetData(){'),html.indexOf('function apiSettingsValue(){')),c);
 return {c,statuses,toasts,calls};
}
(async()=>{
 for(const response of [async()=>({ok:false,status:503,json:async()=>({message:'unavailable'})}),async()=>{throw Error('lost response')}]){
  const f=fixture(response),before=JSON.stringify(f.c.state);assert.equal(await f.c.doReset(),false);
  assert.equal(JSON.stringify(f.c.state),before);assert.equal(f.c.closed,undefined);assert.equal(f.toasts.length,0);assert.match(f.statuses.at(-1),/失败|未确认/);
 }
 const conflict=fixture(async()=>({ok:false,status:409,json:async()=>({})}));assert.equal(await conflict.c.doReset(),false);assert.equal(conflict.c.legacyConflict,true);assert.equal(conflict.c.state.reviews.length,1);
 const f=fixture(async()=>({ok:true,json:async()=>({state:{_revision:'v2',modules:[],checkins:{},habits:{},customFields:[],customRecords:[],decisions:[],predictions:[],reviews:[],insights:[],todos:[]}})}));
 f.c.resetData();assert.match(f.c.modal,/行动|笔记/);assert.match(f.c.modal,/局部/);
 assert.equal(await f.c.doReset(),true);assert.equal(f.c.state.reviews.length,0);assert.equal(f.c.state._revision,'v2');assert.equal(f.c.closed,true);assert.match(f.toasts[0],/局部/);
 assert.equal(f.calls[0].url,'/api/data');assert.equal(f.calls[0].options.headers['X-Legacy-State-Protocol'],'1');
 const during=fixture(async c=>{c.state.reviews[0].thought='typed';c.editGeneration++;return {ok:true,json:async()=>({state:{_revision:'v2'}})}});
 assert.equal(await during.c.doReset(),false);assert.equal(during.c.state.reviews[0].thought,'typed');assert.equal(during.c.legacyConflict,true);
 assert.match(html,/局部记录副本/);assert.match(html,/不包含.*行动/);console.log('5 partial record cases passed: failure, lost response, conflict, acknowledged reset, edits during reset.');
})().catch(e=>{console.error(e);process.exitCode=1});
