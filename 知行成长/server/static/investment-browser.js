/* 浏览器投资闭环：账号内检查点、原样回执重试、直接模型请求；平台不代发模型调用。 */
(() => {
  'use strict';
  const core=window.InvestmentBrowserCore,uuid=()=>crypto.randomUUID();
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const scope=()=>window.Account?.user?.id;
  function guard(account){if(scope()!==account||window.Account?.isCurrent?.(account)===false||document.querySelector('.account-switch-notice'))throw Error('账号已变更，已停止本地执行。');}
  async function api(account,path,body,key,extra={}){
    guard(account);
    const r=await fetch('/api/investments/'+path,{credentials:'same-origin',cache:'no-store',method:body?'POST':'GET',
      headers:{'Content-Type':'application/json','X-Copilot-Request':'1',...(key?{'Idempotency-Key':key}:{}),...extra},
      ...(body?{body:JSON.stringify(body)}:{})});
    guard(account);const data=await r.json();
    if(!r.ok)throw Error(data.message||'远端保存未确认，请保留本机记录后重试。');return data;
  }
  let database;
  function openDB(){
    if(!database)database=new Promise((resolve,reject)=>{
      const request=indexedDB.open('grow-investment-browser-v1',1);
      request.onupgradeneeded=()=>request.result.createObjectStore('runs',{keyPath:'storage_key'});
      request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(Error('浏览器不允许保存本机执行检查点，尚未调用模型。'));
    });return database;
  }
  async function save(checkpoint){
    const db=await openDB();
    return new Promise((resolve,reject)=>{
      const transaction=db.transaction('runs','readwrite');
      transaction.objectStore('runs').put(checkpoint);
      transaction.oncomplete=resolve;transaction.onerror=transaction.onabort=()=>reject(Error('本机检查点未保存，请勿关闭页面；模型不会自动重试。'));
    });
  }
  async function checkpoints(account){
    const db=await openDB();return new Promise((resolve,reject)=>{
      const request=db.transaction('runs').objectStore('runs').getAll(IDBKeyRange.bound(account+':',account+':\uffff'));
      request.onsuccess=()=>resolve(request.result);request.onerror=reject;
    });
  }
  async function readCheckpoint(key){
    const db=await openDB();return new Promise((resolve,reject)=>{
      const request=db.transaction('runs').objectStore('runs').get(key);
      request.onsuccess=()=>resolve(request.result);request.onerror=reject;
    });
  }
  async function removeCheckpoint(key){
    const db=await openDB();return new Promise((resolve,reject)=>{
      const transaction=db.transaction('runs','readwrite');transaction.objectStore('runs').delete(key);
      transaction.oncomplete=resolve;transaction.onerror=transaction.onabort=reject;
    });
  }
  async function configHash(config){
    const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify({url:config.url,model:config.model})));
    return [...new Uint8Array(bytes)].map(v=>v.toString(16).padStart(2,'0')).join('');
  }
  // 开始调用先落盘；拿到输出先落盘再上传。刷新后不会把 call_started 当成可自动重试。
  async function execute(checkpoint,config,notify,control,io={api,save,read:readCheckpoint,model:core.model,verify:(account,signal)=>window.Account.verify(account,signal)}){
    // 取得跨页面执行锁后重读检查点；旧历史卡片不能覆盖另一页的调用开始标记。
    const cp=io.read?await io.read(checkpoint.storage_key):checkpoint;
    if(!cp||cp.account!==checkpoint.account||cp.storage_key!==checkpoint.storage_key)throw Error('本机检查点已变化，请刷新批次列表。');
    if(cp.config_hash!==await configHash(config))throw Error('模型地址或名称与原批次不同，请恢复原配置或新建批次。');
    const account=cp.account;
    const check=()=>{guard(account);if(control.stopped)throw Error('执行已暂停；关闭页面不会继续运行。');};
    check();await io.save(cp);
    if(!cp.run){cp.run=await io.api(account,'local-runs',cp.create,cp.create_key);await io.save(cp);}
    if(cp.run.protocol_version!==1||cp.run.algorithm!==core.algorithm)throw Error('本地执行协议不兼容，请刷新后核对原批次。');
    control.runId=cp.run.id;
    check();const remote=await io.api(account,'local-runs/'+cp.run.id);
    if(remote.state==='cancelled')throw Error('远端批次已取消，未再次调用模型。');
    if(!cp.screened){
      notify('读取冻结行情，在浏览器执行筛选…');
      if(!cp.screen_body){
        const frozen=await io.api(account,'local-runs/'+cp.run.id+'/inputs');
        cp.screen_body={...core.screen(frozen.bundle),input_hash:frozen.input_hash,executor:cp.create.executor};
        cp.screen_key=uuid();await io.save(cp);
      }
      check();cp.run=await io.api(account,'local-runs/'+cp.run.id+'/screening',cp.screen_body,cp.screen_key);
      cp.screened=true;await io.save(cp);
    }
    for(const item of cp.run.screening.items){
      check();const iid=item.instrument_id;
      const entry=cp.candidates[iid]||(cp.candidates[iid]={create_key:uuid()});await io.save(cp);
      try{
        if(!entry.job){entry.job=await io.api(account,`local-runs/${cp.run.id}/candidates/${encodeURIComponent(iid)}`,{executor:cp.create.executor},entry.create_key);await io.save(cp);}
        if(entry.job.state==='ready')continue;
        for(let pass=0;pass<2&&entry.job.state!=='ready';pass++){
          check();
          if(entry.pending){
            notify('上传本机已收到的输出；不会再次调用模型…');
            entry.job=await io.api(account,`local-jobs/${entry.job.id}/${entry.pending.stage}`,entry.pending.body,entry.pending.key);
            entry.pending=null;entry.started=null;await io.save(cp);
            if(entry.job.state==='ready')break;
          }
          if(entry.started)throw Error('上次模型调用结果未确认，已停止自动重发。请核对后取消并新建尝试。');
          check();const input=await io.api(account,'local-jobs/'+entry.job.id+'/input',null,null,{'X-Local-Executor':cp.create.executor});
          if(!['analysis','countercheck'].includes(input.stage)||input.evidence.prompt_version!=='investment-v5')throw Error('模型阶段或提示词协议不兼容，尚未调用模型。');
          if(input.evidence.model!==config.model)throw Error('模型与冻结输入不匹配。');
          if(control.previewOnly){
            entry.preview_hash=input.evidence.input_hash;await io.save(cp);
            notify('已冻结实际发送内容，尚未调用模型。',input);break;
          }
          if(input.stage==='analysis'&&entry.preview_hash!==input.evidence.input_hash)throw Error('此候选的发送内容尚未预览，请先查看发送预览。');
          const controller=new AbortController();control.controller=controller;
          const sessionChanged=()=>controller.abort();
          window.addEventListener('account-session-changed',sessionChanged);
          const timeout=setTimeout(()=>controller.abort(),180000);
          const watch=setInterval(()=>{try{guard(account);if(control.stopped)controller.abort();}catch{controller.abort();}},500);
          let raw;
          try{
            // Cookie 可能已在别页变化；每次模型调用前重新核对当前登录身份。
            await io.verify(account,controller.signal);check();
            entry.started={stage:input.stage,input_hash:input.evidence.input_hash};await io.save(cp);check();
            if(controller.signal.aborted)throw Error('执行已暂停，尚未调用模型。');
            notify((input.stage==='analysis'?'浏览器正在直接请求主分析':'浏览器正在直接请求同模型反证')+'；关闭页面会中断…');
            raw=await io.model(input.evidence.messages,config,controller.signal);
          }
          finally{clearTimeout(timeout);clearInterval(watch);window.removeEventListener('account-session-changed',sessionChanged);control.controller=null;}
          entry.pending={stage:input.stage==='analysis'?'draft':'result',key:uuid(),
            body:{raw,input_hash:input.evidence.input_hash,executor:cp.create.executor}};
          await io.save(cp);check();
          entry.job=await io.api(account,`local-jobs/${entry.job.id}/${entry.pending.stage}`,entry.pending.body,entry.pending.key);
          entry.pending=null;entry.started=null;await io.save(cp);
        }
        entry.error='';await io.save(cp);
      }catch(error){
        entry.error=entry.started&&!entry.pending?'模型调用结果未确认；可能是连接、跨域、权限或中断问题。不会自动重发。':error.message;
        await io.save(cp);notify(entry.error);
        if(entry.job&&entry.job.state!=='ready'){
          try{await io.api(account,'local-jobs/'+entry.job.id+'/pause',
            {executor:cp.create.executor,status:entry.started&&!entry.pending?'call_uncertain':'waiting_upload'});}catch{}
        }
        check();
      }
    }
    notify(control.previewOnly?'请展开核对实际发送内容，再确认本批次评估；当前未发起新的模型调用。':'本轮已停止执行。已保存结果可查看；失败项保留本机输出，可继续尝试上传。');
    return io.api(account,'local-runs/'+cp.run.id);
  }
  function open(context){
    if(!context.accountId)throw Error('请先选择投资账户。');
    if(location.protocol==='file:')throw Error('请从实际平台 HTTP(S) 地址打开页面后使用本地执行。');
    const account=scope();if(!account)throw Error('请先登录。');
    const d=document.createElement('dialog');d.className='inv-dialog';
    const control={stopped:false,controller:null};let active=false,creating=false,page=1;
    d.innerHTML=`<h3>浏览器筛选与评估</h3><p>本页计算并直接调用本人模型 API；远端仅保存数据和校验引用。只发送所选缓存日线及本地筛选摘要，不读取持仓金额或私人笔记。</p>
      <p>最多20个标的，评估命中后的前5个。每个候选有主分析和反证两次请求，本人API可能计费。模型运行在所填服务地址；接口须允许网页直接访问，失败不改由平台转发。</p>
      <fieldset><legend>本浏览器模型配置</legend><label>模型服务地址（Base URL）<input data-url type="url" placeholder="HTTPS API 或 http://localhost:11434/v1"></label><label>模型名称<input data-model maxlength="100"></label><label>模型密钥<input data-key type="password" autocomplete="off"></label><button type="button" class="btn" data-config>仅保存到本浏览器</button></fieldset>
      <form class="inv-form"><fieldset><legend>明确选择缓存标的</legend>${context.instruments.filter(i=>i.kind!=='fund').map(i=>`<label class="inv-choice"><input type="checkbox" data-instrument value="${esc(i.id)}">${esc(i.name)} · ${esc(i.code)}</label>`).join('')||'<p>请先添加标的及盘后行情。</p>'}</fieldset>
      <label>行情截至日期<input type="date" name="as_of" required value="${new Date(Date.now()+28800000).toISOString().slice(0,10)}"></label>
      <label>筛选字段<select name="field"><option value="turnover_cny">成交额（元）</option><option value="close_change_pct">相邻有效记录收盘变化%</option><option value="volume_ratio_5">成交量 / 前5条均量</option><option value="close">收盘价</option></select></label>
      <label>比较关系<select name="op"><option value="gte">大于等于</option><option value="lte">小于等于</option></select></label><label>阈值（留空不限制）<input name="threshold" maxlength="100"></label>
      <label><input type="checkbox" name="above">同时要求收盘高于MA20</label>
      <label>排序<select name="sort_by"><option value="turnover_cny">成交额从高到低</option><option value="close_change_pct">收盘变化从高到低</option><option value="volume_ratio_5">量比从高到低</option><option value="close">收盘价从高到低</option></select></label>
      <label>最多评估<input type="number" name="limit" min="1" max="5" value="3" required></label>
      <label>评估问题<textarea name="question" maxlength="2000" required>基于盘后量价资料评估候选理由、风险、反例和缺少资料，仅作研究。</textarea></label>
      <label><input type="checkbox" name="confirmed" required>我同意向本机配置的模型发送上述范围，并将输入、筛选摘要和两次模型结果保存到本人远端账号；本机也保存恢复检查点。</label>
      <button class="btn" type="submit">浏览器筛选并查看发送预览</button></form>
      <div data-preview></div><button type="button" class="btn" data-confirm disabled>确认上述范围并在浏览器评估</button>
      <p role="status" data-status></p><p role="alert" data-error></p><button type="button" class="btn" data-history>刷新本机及远端批次</button><div data-history-list></div><button type="button" class="btn" data-close>暂停并关闭</button>`;
    document.body.append(d);d.showModal();
    const configurationKey='grow-investment-browser-config:'+account;
    let initial=window.AIConfig?.read()||{};
    try{initial=JSON.parse(localStorage.getItem(configurationKey)||'null')||initial;}catch{}
    d.querySelector('[data-url]').value=initial.api_base_url||'';
    d.querySelector('[data-model]').value=initial.model_name||'';
    d.querySelector('[data-key]').value=initial.api_key||'';
    const value=()=>({api_base_url:d.querySelector('[data-url]').value,model_name:d.querySelector('[data-model]').value,api_key:d.querySelector('[data-key]').value});
    const config=()=>core.modelConfig(value());
    let confirmationCp=null;
    const notify=(text,input)=>{
      if(!d.isConnected)return;d.querySelector('[data-status]').textContent=text;
      if(input){
        const details=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');
        summary.textContent=(input.stage==='analysis'?'主分析':'反证')+' · 完整发送内容';
        pre.textContent=JSON.stringify(input.evidence.messages,null,2);pre.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;max-height:24rem;overflow:auto';
        details.append(summary,pre);d.querySelector('[data-preview]').append(details);d.querySelector('[data-confirm]').disabled=false;
      }
    };
    const error=e=>{if(d.isConnected)d.querySelector('[data-error]').textContent=e.message;};
    async function launch(cp,previewOnly=true){
      if(active)return;active=true;control.stopped=false;
      control.previewOnly=previewOnly;
      if(previewOnly){confirmationCp=cp;d.querySelector('[data-preview]').replaceChildren();d.querySelector('[data-confirm]').disabled=true;}
      else d.querySelector('[data-confirm]').disabled=true;
      d.querySelector('[data-error]').textContent='';
      try{
        if(!navigator.locks)throw Error('当前浏览器不支持安全的多页面执行锁，请使用支持 Web Locks 的浏览器。');
        const cfg=config();
        await navigator.locks.request('grow-investment:'+account+':'+cp.storage_key,{ifAvailable:true},async lock=>{
          if(!lock)throw Error('此批次正在另一个标签页执行。');
          await execute(cp,cfg,notify,control);
        });
      }catch(e){error(e);}finally{active=false;await history().catch(error);}
    }
    async function history(){
      const [local,remote]=await Promise.all([checkpoints(account),api(account,'local-runs?page='+page)]);
      if(!d.isConnected)return;
      const root=d.querySelector('[data-history-list]');root.replaceChildren();
      for(const cp of local){
        const row=document.createElement('article');row.className='inv-record';
        const title=document.createElement('p');title.textContent=cp.run?'本机执行记录 · '+cp.run.created_at:'创建结果未确认 · 本机记录已保留';row.append(title);
        for(const entry of Object.values(cp.candidates)){if(entry.error){const message=document.createElement('p');message.textContent=entry.error;row.append(message);}}
        const resume=document.createElement('button');resume.type='button';resume.className='btn';resume.textContent='查看发送预览 / 重试上传';resume.onclick=()=>launch(cp);row.append(resume);root.append(row);
        const saved=cp.screened&&cp.run.screening.items.length===Object.values(cp.candidates).filter(e=>e.job?.state==='ready').length;
        if(saved||remote.items.some(r=>r.id===cp.run?.id&&r.state==='cancelled')){
          const clear=document.createElement('button');clear.type='button';clear.className='btn';clear.textContent='清理本机检查点（远端保留）';
          clear.onclick=async()=>{try{if(active)throw Error('请先暂停当前执行。');guard(account);await removeCheckpoint(cp.storage_key);await history();}catch(e){error(e);}};row.append(clear);
        }
      }
      for(const run of remote.items){
        const row=document.createElement('article');row.className='inv-record';
        const states={awaiting_browser:'等待浏览器筛选',screened:'筛选已保存，待评估',running:'等待浏览器执行',ready:'处理完成',partial:'部分完成，需核对',cancelled:'已取消'};
        const title=document.createElement('p');title.textContent=run.created_at+' · 浏览器执行 · '+(states[run.state]||'等待核对');row.append(title);
        if(run.screening){const summary=document.createElement('p');summary.textContent=`候选 ${run.screening.total} 个；数据不足 ${run.screening.unresolved} 个；非全市场。`;row.append(summary);}
        for(const item of run.screening?.items||[]){const line=document.createElement('p');line.textContent=`${item.values.name} · ${item.code||''} · 收盘 ${item.values.close} · 数据日 ${item.data_date}`;row.append(line);}
        window.AIEvidence?.mount(row,'investments',run.id);
        for(const [iid,jobId] of Object.entries(run.jobs)){const button=document.createElement('button');button.type='button';button.className='btn';button.textContent=(run.screening?.items.find(i=>i.instrument_id===iid)?.values.name||'候选')+' · 查看报告与依据';button.onclick=()=>window.InvestmentAI?.showJob(jobId);row.append(button);}
        const cancel=document.createElement('button');cancel.type='button';cancel.className='btn';cancel.textContent='取消此批次';
        cancel.onclick=async()=>{try{if(control.runId===run.id){control.stopped=true;control.controller?.abort();}await api(account,'local-runs/'+run.id+'/cancel',{});await history();}catch(e){error(e);}};
        row.append(cancel);root.append(row);
      }
      const pages=document.createElement('p');pages.textContent=`远端批次第 ${page} 页 · 共 ${remote.total} 条`;root.append(pages);
      for(const [label,step,disabled] of [['上一页',-1,page===1],['下一页',1,page*20>=remote.total]]){
        const button=document.createElement('button');button.type='button';button.className='btn';button.textContent=label;button.disabled=disabled;
        button.onclick=()=>{page+=step;history().catch(error);};root.append(button);
      }
    }
    d.querySelector('[data-config]').onclick=()=>{try{config();localStorage.setItem(configurationKey,JSON.stringify(value()));notify('模型配置仅保存在本浏览器当前账号。');}catch(e){error(e);}};
    d.querySelector('[data-history]').onclick=()=>history().catch(error);
    d.querySelector('[data-confirm]').onclick=()=>{if(confirmationCp)launch(confirmationCp,false);};
    d.addEventListener('input',()=>{confirmationCp=null;d.querySelector('[data-confirm]').disabled=true;});
    d.querySelector('form').onsubmit=async event=>{
      event.preventDefault();if(active||creating)return;
      creating=true;const submit=event.target.querySelector('[type=submit]');submit.disabled=true;
      try{
        guard(account);const cfg=config(),form=new FormData(event.target);
        const ids=[...d.querySelectorAll('[data-instrument]:checked')].map(i=>i.value);
        if(!ids.length||ids.length>20)throw Error('请明确选择1至20个已有行情标的。');
        const conditions=[];
        if(form.get('threshold').trim()){core.decimal(form.get('threshold'));conditions.push({field:form.get('field'),op:form.get('op'),value:form.get('threshold').trim()});}
        if(form.get('above'))conditions.push({field:'price_above_ma20',op:'eq',value:'true'});
        const key=uuid(),cp={storage_key:account+':'+key,account,create_key:key,config_hash:await configHash(cfg),candidates:{},
          create:{account_id:context.accountId,instrument_ids:ids,model:cfg.model,question:form.get('question'),executor:uuid(),
            screen:{as_of:form.get('as_of'),conditions,combine:'all',sort_by:form.get('sort_by'),descending:true,limit:Number(form.get('limit'))}}};
        await save(cp);await launch(cp);
      }catch(e){error(e);}finally{creating=false;submit.disabled=false;}
    };
    const stop=()=>{control.stopped=true;control.controller?.abort();};
    d.querySelector('[data-close]').onclick=()=>d.close();
    d.addEventListener('close',()=>{stop();d.remove();},{once:true});
    history().catch(error);
  }
  window.InvestmentBrowser={open,execute,configHash};
})();
