const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/index.html', 'utf8');
const block = source.slice(source.indexOf('async function loadFromServer()'), source.indexOf('function setStatus('));
const flush = () => new Promise(resolve => setImmediate(resolve));
function setup() {
  const calls = [], statuses = [], timers = new Map();
  const alert = {hidden:true}; let next = 0;
  const ctx = {
    state:{modules:[],checkins:{},habits:{},customFields:[],customRecords:[],decisions:[],predictions:[],reviews:[],insights:[],todos:[],_revision:'r0'},
    window:{}, dataLoaded:true, crypto:{randomUUID:()=> 'draft-' + (++next)},
    document:{getElementById:()=>alert},
    setTimeout:fn=>{const id=++next;timers.set(id,fn);return id},clearTimeout:id=>timers.delete(id),
    setStatus:msg=>statuses.push(msg),render:()=>{},refreshModuleNames:()=>{},
    exportJson:()=>{ctx.exported=JSON.stringify(ctx.state)},
    fetch:(url,options)=>new Promise((resolve,reject)=>calls.push({url,options,resolve,reject})),
  };
  vm.createContext(ctx);vm.runInContext(block,ctx);
  return {ctx,calls,statuses,alert};
}
(async()=>{
  const {ctx,calls,statuses,alert}=setup();
  ctx.state.reviews.push({thought:'draft'});ctx.persist();
  const first=ctx.saveToServer();await flush();
  const payload=JSON.parse(calls[0].options.body);
  assert.equal(calls[0].options.headers['X-Legacy-State-Protocol'],'1');
  assert.equal(payload._revision,'r0');assert.ok(payload.reviews[0]._client_id);
  ctx.state.reviews[0]={...ctx.state.reviews[0],thought:'edited during save'};ctx.persist();
  await ctx.saveToServer();assert.equal(calls.length,1);
  calls[0].resolve({ok:true,json:async()=>({state:{_revision:'r1'},assigned_ids:{reviews:{[payload.reviews[0]._client_id]:31}}})});
  await first;
  assert.equal(ctx.state.reviews[0].id,31);assert.equal(ctx.state.reviews[0].thought,'edited during save');
  assert.equal(ctx.state._revision,'r1');assert.doesNotMatch(statuses.at(-1),/^已保存/);
  const second=ctx.saveToServer();await flush();
  const payload2=JSON.parse(calls[1].options.body);
  assert.equal(payload2.reviews[0].id,31);assert.equal(payload2._revision,'r1');
  calls[1].resolve({ok:true,json:async()=>({state:{_revision:'r2'},assigned_ids:{}})});await second;
  assert.match(statuses.at(-1),/^已保存/);
  const local=JSON.stringify(ctx.state);const conflict=ctx.saveToServer();await flush();
  calls[2].resolve({ok:false,status:409,json:async()=>({code:'state_conflict',message:'conflict'})});await conflict;
  assert.equal(JSON.stringify(ctx.state),local);assert.equal(alert.hidden,false);
  ctx.persist();await ctx.saveToServer();assert.equal(calls.length,3);
  const reload=ctx.reloadLegacyState();await flush();assert.equal(ctx.exported,local);
  calls[3].resolve({ok:true,json:async()=>({...ctx.state,_revision:'r3',reviews:[]})});await reload;
  assert.equal(ctx.state._revision,'r3');assert.equal(alert.hidden,true);
  const failed=setup();failed.ctx.state.todos.push({id:'t',title:'unsaved'});
  const network=failed.ctx.saveToServer();await flush();failed.calls[0].reject(Error('offline'));await network;
  assert.equal(failed.ctx.state.todos[0].title,'unsaved');assert.match(failed.statuses.at(-1),/未保存|保存失败/);
  const changing=setup();
  const loading=changing.ctx.loadFromServer();await flush();
  changing.ctx.state.reviews.push({thought:'typed during reload'});changing.ctx.persist();
  changing.calls[0].resolve({ok:true,json:async()=>({...changing.ctx.state,reviews:[],_revision:'new'})});
  assert.equal(await loading,false);
  assert.equal(changing.ctx.state.reviews[0].thought,'typed during reload');
  console.log('Legacy client checks passed: IDs, serialized PUTs, edits during save, conflicts, export-before-reload and failure retention.');
})().catch(e=>{console.error(e);process.exitCode=1});
