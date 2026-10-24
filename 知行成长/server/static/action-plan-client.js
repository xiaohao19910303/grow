/* Private, retry-safe browser transport. No credentials or personal content go to another origin. */
(() => {
  function create({request, storage, account, random = () => crypto.randomUUID()}) {
    const prefix = 'grow.actions.' + account + '.';
    const memory = new Map(), deleted = new Set(), dirty = new Set(), listeners = new Set();
    let failure = null;
    const recoveryKey = name => name === 'draft.index' || /^draft\.[\w.:-]{1,160}$/.test(name) || /^pending\.[\w.:-]{1,240}$/.test(name);
    function failed(error) { const reason = ['QuotaExceededError','NS_ERROR_DOM_QUOTA_REACHED'].includes(error?.name) ? 'quota' : 'unavailable';if(failure!==reason){failure=reason;notify();} }
    function notify() { for (const listener of listeners) listener(); }
    function get(name) {
      if (dirty.has(name)) return deleted.has(name) ? null : memory.get(name) ?? null;
      try { const value = storage.getItem(prefix + name);if (!value) { memory.delete(name);return null; }const parsed = JSON.parse(value);memory.set(name, parsed);return parsed; }
      catch(error) { failed(error);return memory.get(name) ?? null; }
    }
    function persist(name) {
      try { if (deleted.has(name)) {storage.removeItem(prefix + name);deleted.delete(name);}else storage.setItem(prefix + name, JSON.stringify(memory.get(name)));dirty.delete(name); }
      catch(error) { dirty.add(name);failed(error); }
    }
    function put(name, value) { deleted.delete(name);memory.set(name, value);persist(name);notify(); }
    function remove(name) { memory.delete(name);deleted.add(name);persist(name);notify(); }
    function storageStatus() { return {durable:failure === null,reason:failure,unsaved:[...dirty].some(name=>name!=='device')}; }
    function retryStorage() { for (const name of [...dirty]) persist(name);if (!dirty.size && storage) failure=null;notify();return storageStatus(); }
    function recoveryEntries() {
      const names = new Set(memory.keys());
      try { for(let i=0;i<storage.length;i++){const key=storage.key(i);if(key?.startsWith(prefix))names.add(key.slice(prefix.length));} }
      catch(error) { failed(error); }
      for(const id of get('draft.index') || []) names.add('draft.' + id);
      const entries = {};
      for(const name of names) if(recoveryKey(name) && !deleted.has(name)){const value=get(name);if(value!==null)entries[name]=value;}
      return entries;
    }
    function exportRecovery() { return JSON.parse(JSON.stringify({version:1,account,entries:recoveryEntries()})); }
    function importRecovery(bundle) {
      const invalid = () => { throw Error('行动恢复副本格式或版本无效，请使用本网页下载的副本。'); };
      const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
      const exact = (value, allowed) => object(value) && Object.keys(value).every(key => allowed.includes(key));
      let raw;try { raw=JSON.stringify(bundle); } catch { invalid(); }
      if(!raw || raw.length>1048576)invalid();
      let bytes=0;for(const char of raw){const code=char.codePointAt(0);bytes+=code<128?1:code<2048?2:code<65536?3:4;}if(bytes>1048576)invalid();
      if(!exact(bundle,['version','account','entries']) || bundle.version!==1 || !object(bundle.entries))invalid();
      if(bundle.account!==account)throw Error('恢复副本属于其他账号，不能导入当前账号。');
      const names=Object.keys(bundle.entries);if(names.length>500)invalid();
      function safe(value,depth=0){
        if(depth>12)invalid();
        if(value===null || typeof value==='boolean')return;
        if(typeof value==='string'){if(value.length>100000)invalid();return;}
        if(typeof value==='number'){if(!Number.isFinite(value))invalid();return;}
        if(Array.isArray(value)){if(value.length>500)invalid();for(const item of value)safe(item,depth+1);return;}
        if(!object(value)||Object.keys(value).length>100)invalid();
        for(const [key,item] of Object.entries(value)){if(['__proto__','prototype','constructor','ai_config','api_key','access_token','password','authorization'].includes(key))invalid();safe(item,depth+1);}
      }
      const entries=JSON.parse(raw).entries;
      for(const name of names){
        if(!recoveryKey(name))invalid();const value=entries[name];safe(value);
        if(name==='draft.index'){
          if(!Array.isArray(value)||value.length>200||new Set(value).size!==value.length||value.some(id=>typeof id!=='string'||!/^([\w.:-]){1,160}$/.test(id)))invalid();
        }else if(name.startsWith('draft.')){
          if(!exact(value,['draft_id','context','values','base_revision','updated_at']) || value.draft_id!==name.slice(6) || !exact(value.context,['flow','origin_key','parent_context','entry_date']) || !object(value.values) || typeof value.updated_at!=='string' || !Number.isFinite(Date.parse(value.updated_at)))invalid();
          const c=value.context;if(!['edit','create-day'].includes(c.flow)||typeof c.origin_key!=='string'||c.origin_key.length>1000||!(c.parent_context===null||typeof c.parent_context==='string')||typeof c.entry_date!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(c.entry_date))invalid();
          if(value.base_revision!==undefined&&(!Number.isInteger(value.base_revision)||value.base_revision<1))invalid();
        }else{
          if(!exact(value,['signature','body'])||typeof value.signature!=='string'||!object(value.body)||typeof value.body.key!=='string'||!value.body.key||value.body.key.length>160)invalid();
          const body={...value.body};delete body.key;if(JSON.stringify(body)!==value.signature)invalid();
        }
        const current=get(name);if(current!==null&&JSON.stringify(current)!==JSON.stringify(value))throw Error('恢复副本与现有草稿或待确认请求冲突，未覆盖任何内容。请先下载当前副本。');
      }
      const index=entries['draft.index'] || [];
      for(const id of index)if(!entries['draft.'+id]&&!get('draft.'+id))invalid();
      for(const name of names)if(name.startsWith('draft.')&&name!=='draft.index'&&!index.includes(name.slice(6)))invalid();
      // Validate the entire package before touching any durable or in-memory value.
      for(const name of names){deleted.delete(name);memory.set(name,entries[name]);}
      for(const name of names)persist(name);
      notify();return {imported:names.length,durable:storageStatus().durable};
    }
    async function send(path, body) {
      const response = await request('/api/action-plans' + path, {cache:'no-store', method:body ? 'POST' : 'GET',
        headers:body ? {'Content-Type':'application/json', 'X-Copilot-Request':'1','X-Grow-Action-Schema':'2'} : {}, body:body ? JSON.stringify(body) : undefined});
      let result;try { result = await response.json(); } catch { throw new Error('服务连接未完成，请重试；当前输入会保留。'); }
      if (!response.ok) {
        const detail = typeof result.detail === 'string' ? result.detail : typeof result.message === 'string' ? result.message : '请检查填写内容，或刷新计划后重试。';
        const error = new Error(detail);error.status=response.status;error.code=result.code;error.fields=result.errors;error.existing_plan_id=result.existing_plan_id;throw error;
      }
      if(window.GenerationTasks){const reports=result.reports||[result.report].filter(Boolean);for(const report of reports)window.GenerationTasks.track(window.GenerationTasks.external('action-review',report,{kind:'action-review',label:'行动复盘建议生成',title:report.plan_title||'行动计划复盘',plan_id:report.plan_id}));}
      return result;
    }
    async function write(identity, path, payload, ephemeral = {}) {
      const name = 'pending.' + identity;
      let pending = get(name);
      const signature = JSON.stringify(payload);
      if (pending && pending.signature !== signature) {
        const saved = await send('/requests/' + encodeURIComponent(pending.body.key));
        if (saved.found) { remove(name);throw new Error('上次提交已保存，请刷新计划后继续修改；当前填写内容仍保留。'); }
        throw new Error('上次提交结果尚未确认，请先恢复上次内容并重试，避免重复创建。');
      }
      if (!pending) { pending={signature,body:{...payload,key:random()}};put(name,pending); }
      try { const result=await send(path,{...pending.body,...ephemeral});remove(name);return result; }
      catch(error) { if(error.status && error.status<500)remove(name);throw error; }
    }
    function listDrafts(context) {
      const key=JSON.stringify(context);
      return (get('draft.index')||[]).map(id=>get('draft.'+id)).filter(d=>d&&JSON.stringify(d.context)===key);
    }
    function newDraft(context,values={}) {
      const draft={draft_id:random(),context,values,base_revision:values.revision,updated_at:new Date().toISOString()};
      put('draft.'+draft.draft_id,draft);put('draft.index',[...(get('draft.index')||[]),draft.draft_id]);return draft;
    }
    function saveDraft(draft,values) {
      if(get('pending.draft:'+draft.draft_id)&&JSON.stringify(draft.values)!==JSON.stringify(values)){const base=draft.base_revision;draft=newDraft(draft.context,values);draft.base_revision=base;}
      draft={...draft,values,updated_at:new Date().toISOString()};put('draft.'+draft.draft_id,draft);return draft;
    }
    function pendingDrafts(context) {return listDrafts(context).filter(d=>get('pending.draft:'+d.draft_id));}
    function deleteDraft(id) {remove('draft.'+id);put('draft.index',(get('draft.index')||[]).filter(value=>value!==id));}
    async function resolvePending(identity) {
      const item=get('pending.'+identity);if(!item)return {found:false};
      const receipt=await send('/requests/'+encodeURIComponent(item.body.key));
      if(receipt.found)remove('pending.'+identity);return receipt;
    }
    async function retryPending(identity,path) {
      const item=get('pending.'+identity);if(!item)throw Error('没有待确认请求。');
      const result=await send(path,item.body);remove('pending.'+identity);return result;
    }
    let device = get('device');if(!device){device=random();put('device',device);}
    return {read:send,write,device,get,put,remove,listDrafts,newDraft,saveDraft,pendingDrafts,deleteDraft,resolvePending,retryPending,storageStatus,retryStorage,exportRecovery,importRecovery,
      subscribe:listener=>{listeners.add(listener);return ()=>listeners.delete(listener);},pending:identity=>get('pending.'+identity)?.body};
  }
  function day(now, zone='Asia/Shanghai') {
    const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(now).map(p=>[p.type,p.value]));
    return `${parts.year}-${parts.month}-${parts.day}`;
  }
  function pending(plans, now, execution) {
    return plans.filter(p=>p.period==='day'&&p.status==='active'&&!p.blocked&&p.start_date===day(now,p.timezone))
      .sort((a,b)=>(a.id===execution?.plan_id?-1:b.id===execution?.plan_id?1:0)||new Date(a.reminder_at)-new Date(b.reminder_at)||a.id.localeCompare(b.id));
  }
  window.ActionPlanClient={create,day,pending};
})();
