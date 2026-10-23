/* Rhythm namespaces the existing action transport; request keys and recovery stay shared. */
(() => {
  function create(options){
    const base=window.ActionPlanClient.create(options),name=k=>'rhythm.'+k;
    const get=k=>base.get(name(k)),put=(k,v)=>base.put(name(k),v),remove=k=>base.remove(name(k));
    function queue(event){const stamp=Date.now(),items=(get('events.queue')||[]).filter(e=>stamp-e.queued_at<86400000);items.push({...event,queued_at:stamp});put('events.queue',items.slice(-20));}
    let flushing=false;
    async function flush(){if(flushing)return;flushing=true;try{
      const pending=base.pending(name('events')),items=pending?.events||(get('events.queue')||[]).map(({queued_at,...event})=>event);
      if(!items.length)return;
      await base.write(name('events'),'/rhythm/events',{events:items});const ids=new Set(items.map(e=>e.event_id));put('events.queue',(get('events.queue')||[]).filter(e=>!ids.has(e.event_id)));
    }catch{}finally{flushing=false;}}
    return {get,put,remove,queue,flush,device:base.device,
      read:path=>base.read('/rhythm'+path),write:(id,path,body)=>base.write(name(id),'/rhythm'+path,body),
      actionWrite:(id,path,body)=>base.write(name(id),path,body),pending:id=>base.pending(name(id)),
      actionRetry:(id,path)=>base.retryPending(name(id),path),resolve:id=>base.resolvePending(name(id)),retry:(id,path)=>base.retryPending(name(id),'/rhythm'+path)};
  }
  window.RhythmClient={create};
})();
