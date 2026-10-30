const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const context={window:{},Intl,Date,Map,JSON,Error,encodeURIComponent};vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/action-plan-client.js'),'utf8'),context);
(async()=>{
 const values=new Map();let quota=true,sent=0,mode='unknown',number=0;
 const storage={getItem:k=>values.get(k),setItem:(k,v)=>{if(quota&&k.includes('.pending.'))throw Error('quota');values.set(k,v);},removeItem:k=>values.delete(k)};
 const client=context.window.ActionPlanClient.create({account:'alice',storage,random:()=>`durable-${++number}`,request:async()=>{sent++;if(mode==='unknown')throw Error('offline');return {ok:mode==='ok',status:mode==='conflict'?409:401,json:async()=>mode==='ok'?{saved:true}:{message:mode}};}});
 const d=client.newDraft({flow:'create-day',origin_key:'practice-followup:one',parent_context:null,entry_date:'2026-10-30'},{title:'Preserve my intent'}),identity='draft:'+d.draft_id;
 await assert.rejects(client.writeDurable(identity,'/practices/action-one/follow-up',{revision:2,title:'Preserve my intent'}));assert.equal(sent,0,'never send if immutable pending cannot be persisted');
 const original=client.pending(identity).key;quota=false;await assert.rejects(client.retryPendingDurable(identity,'/practices/action-one/follow-up'),/offline/);assert.equal(client.pending(identity).key,original);
 mode='conflict';await assert.rejects(client.retryPendingDurable(identity,'/practices/action-one/follow-up'),/conflict/);assert.equal(client.pending(identity),undefined,'terminal business conflict unlocks a draft');assert.equal(client.get('draft.'+d.draft_id).values.title,'Preserve my intent');
 mode='auth';await assert.rejects(client.writeDurable(identity,'/practices/action-one/follow-up',{revision:3,title:'Preserve my intent'}));assert(client.pending(identity),'authentication failure must preserve an earlier unknown request for reauthentication');
 console.log('Durable practice transport: no send before persistence; same retry key; conflict unlocks without losing draft; auth does not discard uncertain receipt.');
})().catch(e=>{console.error(e);process.exitCode=1;});
