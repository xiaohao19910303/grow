/* Private, retry-safe browser transport. No credentials or personal content go to another origin. */
(() => {
  function create({request, storage, account, random = () => crypto.randomUUID()}) {
    const prefix = 'grow.actions.' + account + '.';
    const memory = new Map();
    function get(name) { try { const value=storage.getItem(prefix+name);return value ? JSON.parse(value) : memory.get(name)||null; } catch { return memory.get(name) || null; } }
    function put(name, value) { memory.set(name, value);try { storage.setItem(prefix + name, JSON.stringify(value)); } catch {} }
    function remove(name) { memory.delete(name);try { storage.removeItem(prefix + name); } catch {} }
    async function send(path, body) {
      const response = await request('/api/action-plans' + path, {cache:'no-store', method:body ? 'POST' : 'GET',
        headers:body ? {'Content-Type':'application/json', 'X-Copilot-Request':'1'} : {}, body:body ? JSON.stringify(body) : undefined});
      let result;try { result = await response.json(); } catch { throw new Error('服务连接未完成，请重试；当前输入会保留。'); }
      if (!response.ok) {
        const detail = typeof result.detail === 'string' ? result.detail : typeof result.message === 'string' ? result.message : '请检查填写内容，或刷新计划后重试。';
        const error = new Error(detail);error.status=response.status;throw error;
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
    let device = get('device');if(!device){device=random();put('device',device);}
    return {read:send,write,device,get,put,remove,pending:identity=>get('pending.'+identity)?.body};
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
