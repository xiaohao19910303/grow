/* 行为报告按账号恢复后台任务；浏览器只保存请求身份，不保存凭证或分析正文。 */
(() => {
  'use strict';
  let current=null,submitting=false;
  const panels=new Map();
  const active=job=>['queued','generating'].includes(job?.state);
  const owner=()=>window.Account?.user?.id||'';
  const pendingKey=()=> 'grow.behavior-report.request:'+owner();
  const terminal={ready:'报告已生成，可查看结果。',failed:'生成未完成，请核对后重试。',cancelled:'已取消生成，收到的进度保留。',interrupted:'调用已中断，进度保留；不会自动重新调用模型。'};
  const task=job=>window.GenerationTasks.external('behavior-report',job,{kind:'behavior-report',label:'行为分析报告生成',title:`最近 ${job.period_days} 天行为分析`});
  async function api(path,body,expectedAccount){
    await window.Account?.ready;const account=owner();
    if(expectedAccount!==undefined&&expectedAccount!==account)throw Error('账号已变化，请重新读取。');
    const response=await fetch('/api/behavior-report'+path,{method:body===undefined?'GET':'POST',cache:'no-store',
      headers:body===undefined?{}:{'Content-Type':'application/json','X-Copilot-Request':'1'},body:body===undefined?undefined:JSON.stringify(body)});
    const data=await response.json().catch(()=>({}));
    if(account!==owner())throw Error('账号已变化，请重新读取。');
    if(!response.ok){const error=Error(data.message||data.detail||'报告请求暂未完成，请重试。');error.status=response.status;throw error;}
    return data;
  }
  function action(panel,text,run){const b=document.createElement('button');b.type='button';b.className='btn';b.textContent=text;b.onclick=()=>Promise.resolve(run()).catch(e=>display(current,e.message));panel.append(b);}
  function display(job,message,settings=false){
    for(const button of document.querySelectorAll('[onclick^="generateNewReport"]')){
      button.disabled=submitting||active(current);button.textContent=submitting?'正在提交…':active(current)?'正在生成…':'生成新报告';
      if(!panels.has(button)){const panel=document.createElement('div');panel.className='reading-task-notice';panel.setAttribute('role','status');panel.setAttribute('aria-live','polite');button.parentNode.insertBefore(panel,button.nextSibling);panels.set(button,panel);}
      const panel=panels.get(button);panel.replaceChildren();const text=document.createElement('p');text.textContent=message||job?.error||job?.phase||terminal[job?.state]||'';panel.append(text);
      if(active(job))action(panel,'取消生成',()=>cancel(task(job)));
      if(settings)action(panel,'前往设置',()=>window.goTab('settings'));
      if(job&&['failed','cancelled','interrupted'].includes(job.state)){
        action(panel,'重试原输入',()=>start(job.period_days,job.id));
        action(panel,'按最新记录重新生成',()=>start(job.period_days));
      }
      if(job)window.AIEvidence?.mount(panel,'behavior-report',job.id);
    }
  }
  function update(job){
    current=job;display(job);window.GenerationTasks?.track(task(job));
    if(job.state==='ready'){window.renderAIReportLatest?.();window.renderAIReports?.();}
    return job;
  }
  async function observe(job){
    update(job);
    try{await window.GenerationTasks.wait(task(job));}
    catch{} // The task center owns retrying observation; a read never starts the model.
  }
  async function start(periodDays=30,retryOf){
    if(submitting||active(current)){display(current);return;}
    const account=owner(),storageKey=pendingKey();
    let config;
    try{config=window.AIConfig.require();}catch(error){display(current,error.message,true);return;}
    let pending;
    try{pending=JSON.parse(localStorage.getItem(storageKey)||'null');}catch{}
    if(pending&&(pending.period_days!==periodDays||pending.retry_of!==(retryOf||null))){
      display(current,'上一次提交结果尚未核对，请先重试原请求。');return;
    }
    pending=pending||{key:crypto.randomUUID(),period_days:periodDays,retry_of:retryOf||null};
    try{localStorage.setItem(storageKey,JSON.stringify(pending));}
    catch{display(current,'无法保存请求编号，请检查浏览器存储后重试。');return;}
    submitting=true;display(current,'正在提交报告任务…');
    try{
      const job=await api('/jobs',{...pending,ai_config:config},account);
      submitting=false;localStorage.removeItem(storageKey);await observe(job);
    }catch(error){
      submitting=false;
      if(account!==owner())return;
      display(current,error.message+' 原请求编号已保留，重试会核对原任务。');
      for(const panel of panels.values())action(panel,'重试原请求',()=>start(pending.period_days,pending.retry_of||undefined));
    }finally{submitting=false;}
  }
  async function read(job){const value=await api('/jobs/'+encodeURIComponent(job.ref));if(!current||current.id===value.id)update(value);return task(value);}
  async function cancel(job){const value=await api('/jobs/'+encodeURIComponent(job.ref)+'/cancel',{});update(value);return task(value);}
  window.generateNewReport=(button,periodDays=30)=>start(periodDays);
  window.GenerationTasks?.register('behavior-report',{
    read,cancel,
    recover:async()=>{
      await window.Account?.ready;const account=owner(),storageKey=pendingKey();
      const recovered=[];let page=1,data;
      do{data=await api('/jobs?page='+page+'&page_size=20',undefined,account);recovered.push(...data.items);page++;}
      while(recovered.filter(active).length===recovered.length&&recovered.length<data.total);
      current=recovered.find(active)||recovered[0]||null;display(current);
      let pending;try{pending=JSON.parse(localStorage.getItem(storageKey)||'null');}catch{}
      if(pending){try{const found=await api('/jobs/by-request/'+encodeURIComponent(pending.key),undefined,account);localStorage.removeItem(storageKey);if(!recovered.some(j=>j.id===found.id))recovered.push(found);current=recovered.find(active)||found;display(current);}catch(error){if(error.status!==404)throw error;display(current,'上一次提交结果未知，请重试原请求。');for(const panel of panels.values())action(panel,'重试原请求',()=>start(pending.period_days,pending.retry_of||undefined));}}
      return recovered.map(task);
    },
    open:async job=>{const value=await api('/jobs/'+encodeURIComponent(job.ref));if(window.goTab('ai-report')===false)return false;update(value);if(value.result_id)return window.viewAIReport(value.result_id);display(value,value.result_deleted?'报告已删除。':undefined);}
  });
})();
