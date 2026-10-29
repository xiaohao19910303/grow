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
const sections=['modules','checkins','habits','customFields','customRecords','decisions','predictions','reviews','insights','todos'];
const initialVersions=()=>Object.fromEntries(sections.map(k=>[k,'initial-'+k]));
async function incrementalSetup(){
  const fixture=setup(),loaded=fixture.ctx.loadFromServer();await flush();
  const snapshot=JSON.parse(JSON.stringify(fixture.ctx.state));snapshot._section_revisions=initialVersions();
  fixture.calls[0].resolve({ok:true,json:async()=>snapshot});assert.equal(await loaded,true);
  fixture.calls.length=0;return fixture;
}
function receipt(changes,revision,ids={},previous=initialVersions()){
  return {ok:true,_revision:revision,_section_revisions:{...previous,...Object.fromEntries(Object.keys(changes).map(k=>[k,revision+'-'+k]))},assigned_ids:ids};
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
  const incremental=await incrementalSetup(),f=incremental.ctx;
  assert.equal(await f.saveToServer(),true);assert.equal(incremental.calls.length,0);
  f.state.reviews.push({thought:'original'});f.persist();
  let saving=f.saveToServer();await flush();
  const frozen=incremental.calls[0].options.body,req=JSON.parse(frozen),draft=req.changes.reviews[0]._client_id;
  assert.equal(incremental.calls[0].options.method,'PATCH');
  assert.equal(incremental.calls[0].options.headers['X-Legacy-State-Protocol'],'2');
  assert.deepEqual(Object.keys(req.changes),['reviews']);assert.equal(req.base_revisions.reviews,'initial-reviews');
  assert.equal(req.changes.insights,undefined);
  f.state.reviews[0].thought='edited after uncertain save';f.state.habits['2026-10-29']={minutes:10};f.persist();
  incremental.calls[0].reject(Error('response lost after commit'));await saving;
  saving=f.saveToServer();await flush();assert.equal(incremental.calls[1].options.body,frozen);
  const firstReceipt=receipt(req.changes,'r1',{reviews:{[draft]:41}});
  incremental.calls[1].resolve({ok:true,json:async()=>firstReceipt});
  assert.equal(await saving,false,'retrying an old request must not allow logout with newer unsaved edits');
  assert.equal(f.state.reviews[0].id,41);assert.equal(f.state.reviews[0].thought,'edited after uncertain save');
  assert.equal(f.state.reviews[0]._client_id,undefined);
  saving=f.saveToServer();await flush();const queued=JSON.parse(incremental.calls[2].options.body);
  assert.notEqual(queued.key,req.key);assert.deepEqual(Object.keys(queued.changes).sort(),['habits','reviews']);
  assert.equal(queued.changes.reviews[0].id,41);assert.equal(queued.base_revisions.reviews,'r1-reviews');
  incremental.calls[2].resolve({ok:true,json:async()=>receipt(queued.changes,'r2',{},firstReceipt._section_revisions)});await saving;
  assert.equal(await f.saveToServer(),true);assert.equal(incremental.calls.length,3);
  // A disjoint server edit must not grant permission to clear unread records.
  f.state.todos.push({id:'todo',title:'mine'});f.persist();saving=f.saveToServer();await flush();
  const disjoint=receipt({todos:[]},'r3',{},f.state._section_revisions);disjoint._section_revisions.insights='external-insight';
  incremental.calls[3].resolve({ok:true,json:async()=>disjoint});await saving;
  assert.equal(f.state._revision,'r2');assert.equal(vm.runInContext('legacyWholeCurrent',f),false);
  f.state.todos[0].title='stale same module';f.persist();saving=f.saveToServer();await flush();
  const beforeConflict=JSON.stringify(f.state);
  incremental.calls[4].resolve({ok:false,status:409,json:async()=>({message:'changed'})});await saving;
  assert.equal(JSON.stringify(f.state),beforeConflict);assert.equal(incremental.alert.hidden,false);
  // Delete a new row while its first acknowledgement is pending.
  const removing=await incrementalSetup(),r=removing.ctx;
  r.state.customRecords.push({note:'draft'});r.persist();saving=r.saveToServer();await flush();
  const add=JSON.parse(removing.calls[0].options.body),cid=add.changes.customRecords[0]._client_id;
  r.state.customRecords=[];r.persist();
  const added=receipt(add.changes,'added',{customRecords:{[cid]:52}});
  removing.calls[0].resolve({ok:true,json:async()=>added});await saving;
  assert.equal(r.state.customRecords.length,0);
  saving=r.saveToServer();await flush();const deleted=JSON.parse(removing.calls[1].options.body);
  assert.deepEqual(deleted.changes.customRecords,[]);assert.equal(deleted.base_revisions.customRecords,'added-customRecords');
  removing.calls[1].resolve({ok:true,json:async()=>receipt(deleted.changes,'deleted',{},added._section_revisions)});await saving;
  const invalid=await incrementalSetup(),i=invalid.ctx;
  i.state.reviews.push({thought:'draft'});i.persist();saving=i.saveToServer();await flush();
  const original=invalid.calls[0].options.body;
  invalid.calls[0].resolve({ok:true,json:async()=>receipt({reviews:[]},'bad',{})});
  assert.equal(await saving,false);assert.equal(i.state.reviews[0].id,undefined);
  saving=i.saveToServer();await flush();assert.equal(invalid.calls[1].options.body,original);
  invalid.calls[1].resolve({ok:false,status:422,json:async()=>({message:'invalid field'})});await saving;
  i.state.reviews[0].thought='corrected';i.persist();saving=i.saveToServer();await flush();
  assert.notEqual(JSON.parse(invalid.calls[2].options.body).key,JSON.parse(original).key);
  const fixed=JSON.parse(invalid.calls[2].options.body);
  invalid.calls[2].resolve({ok:true,json:async()=>receipt(fixed.changes,'fixed',{reviews:{[fixed.changes.reviews[0]._client_id]:61}})});await saving;
  assert.equal(i.state.reviews[0].thought,'corrected');assert.equal(i.state.reviews[0].id,61);
  console.log('Legacy client checks passed: IDs, serialized PUTs, edits during save, conflicts, export-before-reload and failure retention.');
  console.log('Incremental client checks passed: scope, no-op, frozen retries, queued edits, IDs, delete races, conflicts and corrected validation failures.');
})().catch(e=>{console.error(e);process.exitCode=1});
