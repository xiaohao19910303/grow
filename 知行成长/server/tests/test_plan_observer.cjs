/* Execute the actual observer with deterministic network/timers; no browser or model calls. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/plans.js'),'utf8');
const observer=source.slice(source.indexOf('  function observe('),source.indexOf('  async function watch('));
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  const timers=[],views=[],previews=[],notices=[];const status={textContent:''};let calls=0,foreground=true;
  const context={observers:new Map(),root:{querySelector:()=>status},foreground:()=>foreground,hasDirty:()=>false,
    api:async()=>{calls++;if(calls===1)throw Error('offline');return {id:'a',revision:calls,state:calls===2?'generating':'ready',draft_id:'draft-a',preview:{type:'plan',lessons:[]}};},
    setTimeout:(fn,ms)=>timers.push({fn,ms}),previewDraft:async id=>previews.push(id),notifyResult:a=>notices.push(a.id)};
  vm.createContext(context);vm.runInContext(observer,context);
  const current=context.observe('a',a=>views.push(a.state),true);await flush();
  assert.match(status.textContent,/重新连接/);assert.equal(timers[0].ms,3000);
  await timers.shift().fn();await flush();assert.deepEqual(views,['generating']);assert.equal(timers[0].ms,1500);
  const count=calls;context.observe('a',a=>views.push(a.state),true);await flush();assert.equal(calls,count,'rebinding must not start another network poll');
  await timers.shift().fn();await flush();assert.deepEqual(previews,['draft-a']);assert.equal(timers.length,0,'terminal jobs stop polling');
  foreground=false;context.api=async()=>({id:'b',revision:1,state:'ready',draft_id:'draft-b'});
  context.observe('b',null,true);await flush();assert.deepEqual(notices,['b']);assert.deepEqual(previews,['draft-a'],'background completion must not navigate');
  current.left=true;context.observe('a',()=>{},true);assert.equal(current.auto,false,'returning after leaving must not restore automatic navigation');
  console.log('Observer checks passed: reconnect, deduplication, terminal stop, foreground-only preview and background notification.');
})().catch(e=>{console.error(e);process.exitCode=1;});
