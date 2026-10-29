/* 个人规则选股工作台：本机草稿/检查点不含密钥，网络重试不重跑模型。 */
(() => {
  'use strict';
  const core=window.InvestmentScreenV2,runtime=window.InvestmentBrowser,base=window.InvestmentBrowserCore;
  const uuid=()=>crypto.randomUUID(),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const shown=v=>v==null?'未知':typeof v==='boolean'?(v?'是':'否'):/^-?\d+\.\d{5,}$/.test(String(v))?'约'+String(v).replace(/(\.\d{4})\d+$/,'$1'):String(v);
  let database;
  function db(){return database||(database=new Promise((resolve,reject)=>{const r=indexedDB.open('grow-rule-screen-v2',1);r.onupgradeneeded=()=>r.result.createObjectStore('workspaces',{keyPath:'key'});r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(Error('本机草稿存储不可用，未调用模型。'));}));}
  async function read(key){const d=await db();return new Promise((resolve,reject)=>{const r=d.transaction('workspaces').objectStore('workspaces').get(key);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(Error('本机草稿读取失败。'));});}
  async function put(state,expected){const d=await db();return new Promise((resolve,reject)=>{const t=d.transaction('workspaces','readwrite'),store=t.objectStore('workspaces');let conflict=false;
    if(expected==null)store.put(state);
    else{const r=store.get(state.key);r.onsuccess=()=>{if((r.result?.revision||0)!==expected){conflict=true;t.abort();return;}store.put({...state,revision:expected+1});};}
    t.oncomplete=()=>{if(expected!=null)state.revision=expected+1;resolve();};t.onabort=t.onerror=()=>reject(Error(conflict?'另一个页面已修改本机草稿，请重新打开；未重复调用模型。':'本机检查点保存失败，请勿重复调用模型。'));});}
  const date=()=>new Date(Date.now()+28800000).toISOString().slice(0,10);
  async function open(context){
    if(!context.accountId)throw Error('请先选择投资账户。');
    const user=window.Account?.user?.id;if(!user)throw Error('请先登录。');
    const key=user+':'+context.accountId+':rule-v2',control={stopped:false,controller:null};let closed=false,busy=false;
    const guard=()=>{if(closed||control.stopped||window.Account?.user?.id!==user||window.Account?.isCurrent?.(user)===false||document.querySelector('.account-switch-notice'))throw Error('页面暂停或账号已变化，已停止执行。');};
    const api=(path,body,id,extra)=>runtime.api(user,path,body,id,extra);
    await window.Account.verify(user);const catalog=await api('screening-catalog');
    const defaults={as_of:date(),conditions:[],combine:'all',sort_by:'turnover_cny',descending:true,secondary_sort_by:null,secondary_descending:true,limit:20};
    let state=await read(key)||{key,account:user,account_id:context.accountId,screen:defaults,ids:[],text:'',name:'',description:'',accepted:false,resolved:false};
    const d=document.createElement('dialog');d.className='inv-dialog';d.setAttribute('aria-label','规则选股');
    d.style.cssText='width:min(920px,calc(100vw - 24px));max-width:calc(100vw - 24px);max-height:90vh;overflow:auto;box-sizing:border-box';
    const stocks=context.instruments.filter(i=>i.kind==='stock'&&['SSE','SZSE'].includes(i.market));
    const fields=Object.entries(catalog.fields).map(([k,v])=>`<option value="${k}">${esc(v.label)}（${esc(v.unit)}）</option>`).join('');
    d.innerHTML=`<h3>规则选股 · 指定股票池</h3><p>最多20只沪深股票；未复权价格变化未校正公司行动，不是投资总回报。交易活跃度不等于平台人气。筛选在本浏览器运行，远端仅校验归档。</p><button class="btn" data-legacy>查看旧版执行与远端历史</button><label>本机归档<select data-history></select></label><button class="btn" data-restore>恢复所选本机批次</button>
      <div class="inv-form"><label>选择模板<select data-template><option value="">新模板</option></select></label><div><button class="btn" data-load>载入模板</button><button class="btn" data-disable>停用模板</button></div>
      <fieldset><legend>指定股票池</legend>${stocks.map(i=>`<label class="inv-choice"><input type="checkbox" data-iid="${esc(i.id)}">${esc(i.name)} · ${esc(i.code)}</label>`).join('')||'<p>请先添加沪深股票及盘后行情。</p>'}</fieldset>
      <label>筛选截至日期<input type="date" data-date required></label><label><input type="checkbox" data-use>确认合法来源及本人用途，接受未复权口径</label><button class="btn" data-update>更新所选股票行情（AKShare）</button><div data-update-log role="status"></div>
      <details><summary>模型配置（仅生成条件或研究候选时需要）</summary><label>模型地址<input data-url autocomplete="off" maxlength="2048"></label><label>模型名称<input data-model maxlength="100"></label><label>API Key<input data-secret type="password" autocomplete="off"></label><p>配置不进入本页草稿、批次或平台请求；跨域失败不通过平台代理。</p></details>
      <label>自然语言选股描述<textarea data-text maxlength="2000" placeholder="例如：近5日涨幅3%到10%，换手率2%到8%，按量比排序"></textarea></label><button class="btn" data-generate>AI生成条件草稿</button><div data-draft></div>
      <label>组合方式<select data-combine><option value="all">全部满足</option><option value="any">任一满足</option></select></label><div data-conditions></div><button class="btn" data-add>添加手工条件</button>
      <label>主排序<select data-sort>${fields}</select></label><label><input data-desc type="checkbox">主排序从高到低</label><label>次排序<select data-secondary><option value="">不设置</option>${fields}</select></label><label><input data-second-desc type="checkbox">次排序从高到低</label>
      <label>模板名称<input data-name maxlength="100"></label><label>说明<textarea data-description maxlength="2000"></textarea></label><div><button class="btn" data-save-template>保存模板新版本</button><button class="btn" data-run>执行筛选（不调用模型）</button><button class="btn" data-retry>恢复原批次／重试保存</button></div>
      <p data-status role="status"></p><p data-error role="alert"></p><div data-results></div>
      <label>候选研究问题<textarea data-question maxlength="2000">解释入选理由、风险、反例和缺少资料，仅作研究，不发送金额。</textarea></label><button class="btn" data-preview>选择候选并预览AI发送内容</button><div data-ai-preview></div><button class="btn" data-analyze>确认已预览内容并继续AI研究</button>
      <button class="btn" data-new>保留归档并新建筛选</button><button class="btn" data-cancel>取消当前批次</button><button class="btn" data-close>暂停并关闭</button></div>`;
    document.body.append(d);d.showModal();const q=s=>d.querySelector(s),all=s=>[...d.querySelectorAll(s)];
    const notify=s=>{q('[data-status]').textContent=s;},error=e=>{q('[data-error]').textContent=e.message||String(e);};
    const cfg=window.AIConfig?.read()||{};q('[data-url]').value=cfg.api_base_url||'';q('[data-model]').value=cfg.model_name||'';q('[data-secret]').value=cfg.api_key||'';
    const config=()=>base.modelConfig({api_base_url:q('[data-url]').value,model_name:q('[data-model]').value,api_key:q('[data-secret]').value});
    let saving=Promise.resolve();
    async function save(){guard();const current=state;const work=saving.then(()=>put(current,current.revision||0));saving=work.catch(()=>{});await work;guard();}
    const ops={gte:'至少／≥',gt:'超过／>',lte:'不超过／≤',lt:'低于／<',eq:'等于',ne:'不等于',between:'区间（含上下界）'};
    function addRow(c={field:'return_5d_pct',op:'between',value:'',upper_value:''}){
      const row=document.createElement('fieldset');row.className='inv-form';row.innerHTML=`<legend>筛选条件</legend><label>指标<select data-field>${fields}</select></label><label>关系<select data-op>${Object.entries(ops).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label><label>阈值（百分比直接填3.5，成交额填元；布尔填true/false）<input data-value maxlength="100"></label><label data-upper-label>区间上界<input data-upper maxlength="100"></label><button class="btn" type="button" data-remove>删除此条件</button>`;
      row.querySelector('[data-field]').value=c.field;row.querySelector('[data-op]').value=c.op;row.querySelector('[data-value]').value=c.value;row.querySelector('[data-upper]').value=c.upper_value??'';
      const boolean=document.createElement('label');boolean.innerHTML='是否满足<select data-bool><option value="true">是</option><option value="false">否</option></select>';row.querySelector('[data-value]').parentElement.after(boolean);boolean.querySelector('select').value=c.value==='false'?'false':'true';
      const toggle=()=>{const isBool=row.querySelector('[data-field]').value==='price_above_ma20';row.querySelector('[data-upper-label]').hidden=isBool||row.querySelector('[data-op]').value!=='between';boolean.hidden=!isBool;row.querySelector('[data-value]').parentElement.hidden=isBool;if(isBool&&!['eq','ne'].includes(row.querySelector('[data-op]').value))row.querySelector('[data-op]').value='eq';};toggle();
      row.querySelector('[data-field]').onchange=toggle;
      row.querySelector('[data-op]').onchange=toggle;row.querySelector('[data-remove]').onclick=()=>{if(!busy){row.remove();persistForm();}};q('[data-conditions]').append(row);
    }
    function collect(){
      state.ids=all('[data-iid]:checked').map(n=>n.dataset.iid);
      state.form_draft={as_of:q('[data-date]').value,conditions:all('[data-conditions] fieldset').map(row=>({field:row.querySelector('[data-field]').value,op:row.querySelector('[data-op]').value,value:row.querySelector('[data-field]').value==='price_above_ma20'?row.querySelector('[data-bool]').value:row.querySelector('[data-value]').value,upper_value:row.querySelector('[data-op]').value==='between'?row.querySelector('[data-upper]').value:null})),
        combine:q('[data-combine]').value,sort_by:q('[data-sort]').value,descending:q('[data-desc]').checked,secondary_sort_by:q('[data-secondary]').value||null,secondary_descending:q('[data-second-desc]').checked,limit:20};
      state.text=q('[data-text]').value;state.name=q('[data-name]').value;state.description=q('[data-description]').value;
      state.accepted=q('[data-accept]')?.checked??state.accepted;state.resolved=q('[data-resolve]')?.checked??state.resolved;
      if(!state.ids.length||state.ids.length>20)throw Error('请选择1至20只沪深股票。');
      state.screen=core.validateScreen(state.form_draft,catalog.fields);state.form_draft=null;
    }
    function persistForm(){try{collect();}catch{}save().catch(error);}
    function checkDraft(){
      if(state.parse_started)throw Error('生成结果尚未确认，请恢复原输出或明确改用手工条件。');
      if(!state.generation)return;
      if(state.text!==state.generation.source_text)throw Error('原文已变化，请重新生成，或明确清除AI草稿后使用手工条件。');
      const draft=state.generation.draft;
      if([...draft.mappings,draft.sort_mapping].some(m=>m.source==='suggested')&&!state.accepted)throw Error('请接受AI建议或修改后确认。');
      if((draft.ambiguities.length||draft.unsupported.length)&&!state.resolved)throw Error('请先处理歧义和不支持项。');
    }
    function drawDraft(){
      const root=q('[data-draft]');root.replaceChildren();
      if(state.generation){
        const g=state.generation;
        root.innerHTML=`<h4>原始AI条件草稿 · 尚不代表有效策略</h4><p>请对照下方表单；手工修改会独立保存，不改写模型原文。</p>${g.draft.mappings.map((m,i)=>`<article class="inv-record"><p>${esc(({explicit:'原文明确',default:'页面默认',suggested:'AI建议'})[m.source])}：${esc(m.quote||'原文未明确')} → ${esc(catalog.fields[g.draft.screen.conditions[i].field]?.label)} ${esc(ops[g.draft.screen.conditions[i].op])} ${esc(g.draft.screen.conditions[i].value)} ${esc(g.draft.screen.conditions[i].upper_value||'')} ${esc(catalog.fields[g.draft.screen.conditions[i].field]?.unit)}</p><p>${esc(m.reason)}</p></article>`).join('')}
          <p>排序来源：${esc(g.draft.sort_mapping.quote||'页面默认／建议')} · ${esc(g.draft.sort_mapping.reason)}</p>
          ${[...g.draft.ambiguities,...g.draft.unsupported].map(s=>`<p role="alert">${esc(s)}</p>`).join('')}
          <label><input type="checkbox" data-accept ${state.accepted?'checked':''}>我已核对、接受或在表单修改AI建议</label>
          <label><input type="checkbox" data-resolve ${state.resolved?'checked':''}>我已在表单修正或明确移除上述不支持／歧义要求，仅执行当前表单</label><button class="btn" data-clear>清除AI草稿，改用手工规则</button>`;
        q('[data-clear]').onclick=()=>{if(!busy){state.generation=null;state.parse_started=false;state.parse_raw=null;drawDraft();save().catch(error);}};
      }
      if(state.parse_started){const p=document.createElement('p');p.textContent='上次生成结果未确认；不会自动重发。可主动重新生成。';root.append(p);}
      if(state.parse_started){const b=document.createElement('button');b.className='btn';b.textContent='放弃本次解析，改用手工条件';b.onclick=()=>action(async()=>{state.parse_started=false;state.parse_raw=null;state.generation=null;state.accepted=false;state.resolved=false;await save();drawDraft();});root.append(b);}
      if(state.parse_started&&state.parse_raw){const b=document.createElement('button');b.className='btn';b.textContent='恢复已收到的解析输出（不调用模型）';b.onclick=()=>action(async()=>{
        const draft=core.parse(state.parse_raw,state.parse_text,state.parse_context,catalog);state.screen=draft.screen;state.form_draft=null;state.text=state.parse_text;
        state.generation={source_text:state.parse_text,model:state.parse_model,parser_version:core.parser,raw:state.parse_raw,draft};state.accepted=false;state.resolved=false;state.parse_started=false;await save();fill();
      });root.append(b);const pre=document.createElement('pre');pre.textContent=state.parse_raw;pre.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere';root.append(pre);}
    }
    function fill(){
      const form=state.form_draft||state.screen;
      all('[data-iid]').forEach(n=>n.checked=state.ids.includes(n.dataset.iid));q('[data-date]').value=form.as_of;q('[data-text]').value=state.text||'';q('[data-name]').value=state.name||'';q('[data-description]').value=state.description||'';
      q('[data-combine]').value=form.combine;q('[data-sort]').value=form.sort_by;q('[data-desc]').checked=form.descending;q('[data-secondary]').value=form.secondary_sort_by||'';q('[data-second-desc]').checked=form.secondary_descending??true;
      q('[data-conditions]').replaceChildren();form.conditions.forEach(addRow);drawDraft();drawResults();
    }
    function drawResults(){
      const run=state.cp?.run,root=q('[data-results]');root.replaceChildren();
      if(!run)return;
      root.innerHTML=`<h4>本次选股记录</h4><p>输入已冻结；由此浏览器计算，资料真实性仍需核对。</p><details><summary>查看版本与保存记录</summary><p>${esc(run.id)} · ${esc(run.input_hash)} · ${esc(run.state)}</p></details>`;
      if(run.screening){
        root.insertAdjacentHTML('beforeend',`<p>入选 ${run.screening.total}；未知 ${run.screening.unresolved}；仅本股票池</p>`);
        for(const e of run.screening.evaluations||[]){
          const article=document.createElement('article');article.className='inv-record';article.style.overflowWrap='anywhere';
          article.innerHTML=`<h4>${esc(e.name)} · ${esc(e.code)} · ${esc(({matched:'入选',excluded:'排除',unknown:'未知'})[e.status])}</h4><p>数据日 ${esc(e.data_date||'无目标日数据')} · 收盘 ${esc(shown(e.values.close))} · 换手 ${esc(shown(e.values.turnover_rate_pct))}%</p>${e.details.map((v,i)=>`<p title="原始值 ${esc(v.actual??'未知')}">${esc(catalog.fields[v.field]?.label)}：${esc(shown(v.actual))} ${esc(v.unit)}；条件 ${esc(ops[state.cp.frozen?.request.conditions[i]?.op]||'')} ${esc(state.cp.frozen?.request.conditions[i]?.value||'')} ${esc(state.cp.frozen?.request.conditions[i]?.upper_value||'')} → ${v.result===null?'未知':v.result?'满足':'不满足'} ${esc(v.reason||'')}</p>`).join('')}`;
          if(e.status==='matched'){const label=document.createElement('label');label.innerHTML=`<input type="checkbox" data-candidate="${esc(e.instrument_id)}">选择此候选进行AI研究`;article.append(label);}
          root.append(article);
        }
        for(const [iid,jid] of Object.entries(run.jobs||{})){const b=document.createElement('button');b.className='btn';b.textContent='查看候选报告 · '+(run.screening.items.find(i=>i.instrument_id===iid)?.name||iid);b.onclick=()=>window.InvestmentAI.showJob(jid);root.append(b);}
      }
      window.AIEvidence?.mount(root,'investments',run.id);
    }
    let templates=[];
    async function refreshTemplates(){const response=await api('screening-templates?account_id='+encodeURIComponent(context.accountId));templates=response.items;
      q('[data-template]').innerHTML='<option value="">新模板</option>'+templates.map(t=>`<option value="${esc(t.id)}">${esc(t.name)} · v${t.version}${t.enabled?'':' · 已停用'}</option>`).join('');q('[data-template]').value=state.template_id||'';
    }
    async function action(fn){
      if(busy)return;busy=true;q('[data-error]').textContent='';all('button,input,select,textarea').filter(b=>!b.matches('[data-close]')).forEach(b=>b.disabled=true);
      try{guard();await window.Account.verify(user);if(!navigator.locks)throw Error('浏览器不支持执行锁，请使用受支持浏览器。');await navigator.locks.request('rule-screen:'+key,{ifAvailable:true},async lock=>{if(!lock)throw Error('另一个页面正在执行，请在原页面恢复。');guard();await fn();});}
      catch(e){error(e);}finally{busy=false;all('button,input,select,textarea').forEach(b=>b.disabled=false);}
    }
    q('[data-add]').onclick=()=>{if(!busy){if(all('[data-conditions] fieldset').length>=10)return error(Error('最多10个条件。'));addRow();persistForm();}};
    q('[data-generate]').onclick=()=>action(async()=>{
      state.text=q('[data-text]').value;state.ids=all('[data-iid]:checked').map(n=>n.dataset.iid);const text=state.text,contextForModel={as_of:q('[data-date]').value,selected_instrument_count:state.ids.length};
      if(!state.ids.length||state.ids.length>20)throw Error('请先选择1至20只股票。');
      const configuration=config(),messages=core.messages(text,contextForModel,catalog);
      state.parse_started=true;state.parse_raw=null;state.generation=null;state.accepted=false;state.resolved=false;state.parse_text=text;state.parse_context=contextForModel;state.parse_model=configuration.model;await save();drawDraft();
      const controller=new AbortController();control.controller=controller;const timer=setTimeout(()=>controller.abort(),180000);
      notify('浏览器直接生成条件草稿；尚不执行筛选。');
      try{
        const raw=await base.model(messages,configuration,controller.signal);guard();state.parse_raw=raw;state.parse_model=configuration.model;state.parse_context=contextForModel;await save();
        const draft=core.parse(raw,text,contextForModel,catalog);state.screen=draft.screen;state.form_draft=null;state.generation={source_text:text,model:configuration.model,parser_version:core.parser,raw,draft};
        state.accepted=false;state.resolved=false;state.parse_started=false;await save();fill();notify('草稿已生成，请核对原文、建议和问题，再执行表单。');
      }finally{clearTimeout(timer);control.controller=null;if(!closed&&state.parse_started)drawDraft();}
    });
    q('[data-save-template]').onclick=()=>action(async()=>{
      collect();checkDraft();if(!state.name.trim())throw Error('请填写模板名称。');
      const data={account_id:context.accountId,name:state.name,description:state.description,instrument_ids:state.ids,screen:state.screen,enabled:true,
        generation:state.generation?{...state.generation,accepted_suggestions:true,issues_resolved:true}:null};
      const pending=JSON.stringify(data);if(state.template_pending?.fingerprint!==pending)state.template_pending={fingerprint:pending,key:uuid()};await save();
      let result;
      if(state.template_id){const r=await fetch('/api/investments/screening-templates/'+encodeURIComponent(state.template_id),{method:'PUT',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Copilot-Request':'1','X-Account-Id':user,'Idempotency-Key':state.template_pending.key},body:JSON.stringify({version:state.template_version,data})});guard();result=await r.json();if(!r.ok)throw Error(result.message||'模板保存未确认。');}
      else result=await api('screening-templates',data,state.template_pending.key);
      state.template_id=result.id;state.template_version=result.version;state.template_pending=null;await save();await refreshTemplates();notify('模板已保存为版本 '+result.version+'，历史批次保持原样。');
    });
    q('[data-load]').onclick=()=>action(async()=>{
      const t=templates.find(t=>t.id===q('[data-template]').value);if(!t)throw Error('请选择模板。');if(!t.enabled)throw Error('模板已停用。');
      state={...state,form_draft:null,screen:{...t.screen,as_of:date()},ids:t.instrument_ids,name:t.name,description:t.description,template_id:t.id,template_version:t.version,
        generation:t.generation?{source_text:t.generation.source_text,model:t.generation.model,parser_version:t.generation.parser_version,raw:t.generation.raw,draft:t.generation.draft}:null,
        text:t.generation?.source_text||'',accepted:!!t.generation,resolved:!!t.generation,parse_started:false};await save();fill();
    });
    q('[data-disable]').onclick=()=>action(async()=>{
      const t=templates.find(t=>t.id===q('[data-template]').value);if(!t)throw Error('请选择模板。');
      const r=await fetch('/api/investments/screening-templates/'+encodeURIComponent(t.id),{method:'PUT',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Copilot-Request':'1','X-Account-Id':user,'Idempotency-Key':uuid()},body:JSON.stringify({version:t.version,data:{enabled:false}})});guard();const result=await r.json();if(!r.ok)throw Error(result.message);await refreshTemplates();notify('模板已停用，旧批次保留。');
    });
    async function performScreen(){
      const cp=state.cp;
      if(!cp)throw Error('没有可恢复批次。');
      if(!cp.run){cp.run=await api('local-runs',cp.create,cp.create_key);await save();}
      const remote=await api('local-runs/'+cp.run.id);if(remote.state==='cancelled')throw Error('批次已取消。');
      if(remote.screening){cp.run=remote;cp.screened=true;await save();drawResults();return;}
      if(!cp.screen_body){const input=await api('local-runs/'+cp.run.id+'/inputs');cp.frozen=input.bundle;cp.screen_body={...core.screen(input.bundle),input_hash:input.input_hash,executor:cp.create.executor};cp.screen_key=uuid();await save();}
      guard();cp.run=await api('local-runs/'+cp.run.id+'/screening',cp.screen_body,cp.screen_key);cp.screened=true;await save();drawResults();notify('筛选已归档；指标为本地自报计算，尚未调用模型。');
    }
    q('[data-run]').onclick=()=>action(async()=>{
      collect();checkDraft();if(state.cp)throw Error('当前已有冻结批次，请恢复或点击新建筛选。');
      state.cp={account:user,storage_key:key,create_key:uuid(),candidates:{},create:{protocol_version:2,account_id:context.accountId,instrument_ids:state.ids,screen:state.screen,executor:uuid()}};
      // 编辑后的表单独立冻结，不把它错误声明为未编辑的模板快照。
      if(state.template_id){state.cp.create.template_id=state.template_id;state.cp.create.template_version=state.template_version;}
      await save();await performScreen();
    });
    q('[data-retry]').onclick=()=>action(async()=>{await performScreen();});
    q('[data-update]').onclick=()=>action(async()=>{
      const ids=all('[data-iid]:checked').map(n=>n.dataset.iid);if(!q('[data-use]').checked||!ids.length||ids.length>20)throw Error('请选择股票并确认来源用途。');
      let end=q('[data-date]').value;const instant=new Date(Date.now()+28800000);
      if(end===date()&&instant.getUTCHours()*60+instant.getUTCMinutes()<930){const prev=new Date(end+'T00:00:00Z');prev.setUTCDate(prev.getUTCDate()-1);end=prev.toISOString().slice(0,10);}
      const start=new Date(end+'T00:00:00Z');if(Number.isNaN(start.getTime()))throw Error('请选择日期。');start.setUTCDate(start.getUTCDate()-89);
      if(!state.update||state.update.end!==end||JSON.stringify(state.update.ids)!==JSON.stringify(ids))state.update={end,ids,keys:{},results:{}};
      for(const iid of ids){guard();if(state.update.results[iid]?.ok)continue;state.update.keys[iid]||=uuid();await save();
        notify('更新 '+(stocks.find(i=>i.id===iid)?.name||iid)+'；只更新所选来源，不自动换源。');
        try{const result=await api('provider/akshare/daily',{instrument_id:iid,account_id:context.accountId,start_date:start.toISOString().slice(0,10),end_date:end,use_confirmed:true},state.update.keys[iid]);state.update.results[iid]={ok:true,text:'已更新至 '+result.latest_session};}
        catch(e){state.update.results[iid]={ok:false,text:e.message};}await save();
        q('[data-update-log]').textContent=ids.map(i=>(stocks.find(s=>s.id===i)?.name||i)+'：'+(state.update.results[i]?.text||'等待')).join('\n');
      }
      notify('本轮更新结束；失败项保留旧快照，主动再次点击可重试，筛选不静默改用旧日期。');
    });
    const aiIO={api:runtime.api,save:async cp=>{state.cp=cp;await save();},read:async()=>{guard();return (await read(key))?.cp;},model:base.model,verify:(account,signal)=>window.Account.verify(account,signal)};
    async function analyze(preview){
      const cp=state.cp;if(!cp?.screened)throw Error('请先完成筛选。');const configuration=config();
      if(!cp.run.analysis_selection?.length){
        const ids=all('[data-candidate]:checked').map(n=>n.dataset.candidate);if(!ids.length||ids.length>5)throw Error('请选择1至5个已入选候选。');
        cp.selection||={key:uuid(),body:{executor:cp.create.executor,instrument_ids:ids,model:configuration.model,question:q('[data-question]').value}};cp.config_hash=await runtime.configHash(configuration);await save();
        cp.run=await api('local-runs/'+cp.run.id+'/analysis-selection',cp.selection.body,cp.selection.key);await save();
      }
      control.previewOnly=preview;
      const notifyAI=(text,input)=>{notify(text);if(input){const box=document.createElement('details'),title=document.createElement('summary'),pre=document.createElement('pre');title.textContent=(input.stage==='analysis'?'主分析':'反证')+' · 实际发送内容';pre.textContent=JSON.stringify(input.evidence.messages,null,2);pre.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;max-height:20rem;overflow:auto';box.append(title,pre);q('[data-ai-preview]').append(box);}};
      const latestRun=await runtime.execute(cp,configuration,notifyAI,control,aiIO);state.cp.run=latestRun;await save();drawResults();
    }
    q('[data-preview]').onclick=()=>action(()=>analyze(true));q('[data-analyze]').onclick=()=>action(()=>analyze(false));
    async function localHistory(){
      const database=await db();const entries=await new Promise((resolve,reject)=>{const r=database.transaction('workspaces').objectStore('workspaces').getAll(IDBKeyRange.bound(key+':run:',key+':run:\uffff'));r.onsuccess=()=>resolve(r.result);r.onerror=reject;});
      q('[data-history]').innerHTML='<option value="">请选择本机归档批次</option>'+entries.map(e=>`<option value="${esc(e.key)}">${esc(e.cp.run?.created_at||'未确认保存')} · ${esc(e.cp.run?.id||e.cp.create_key)}</option>`).join('');
    }
    q('[data-new]').onclick=()=>action(async()=>{if(state.cp){await put({key:key+':run:'+(state.cp.run?.id||state.cp.create_key),account:user,account_id:context.accountId,cp:state.cp});}state.cp=null;state.update=null;await save();await localHistory();drawResults();notify('原检查点及远端归档保留，可选择本机归档恢复。');});
    q('[data-restore]').onclick=()=>action(async()=>{const selected=q('[data-history]').value;if(!selected.startsWith(key+':run:'))throw Error('请选择本机批次。');const entry=await read(selected);if(!entry||entry.account!==user||entry.account_id!==context.accountId)throw Error('归档账号不匹配。');
      if(state.cp)await put({key:key+':run:'+(state.cp.run?.id||state.cp.create_key),account:user,account_id:context.accountId,cp:state.cp});state.cp=entry.cp;await save();drawResults();notify('仅恢复检查点，未调用模型。');});
    q('[data-legacy]').onclick=()=>{if(!busy){d.close();runtime.open(context);}};
    q('[data-template]').onchange=()=>{if(!q('[data-template]').value){state.template_id=null;state.template_version=null;save().catch(error);}};
    q('[data-cancel]').onclick=()=>action(async()=>{if(!state.cp?.run)throw Error('尚无远端批次。');state.cp.run=await api('local-runs/'+state.cp.run.id+'/cancel',{});await save();drawResults();});
    const stop=()=>{control.stopped=true;control.controller?.abort();};
    const onSession=()=>{stop();q('[data-secret]').value='';};window.addEventListener('account-session-changed',onSession);
    q('[data-close]').onclick=()=>d.close();d.addEventListener('close',()=>{closed=true;stop();window.removeEventListener('account-session-changed',onSession);d.remove();},{once:true});
    // 无效的未填写条件也保存草稿，但不会绕过执行前校验；密钥字段从不纳入状态。
    d.addEventListener('change',event=>{if(busy||event.target.matches('[data-url],[data-model],[data-secret],[data-candidate],[data-template]'))return;
      persistForm();});
    fill();await refreshTemplates();await localHistory();if(state.cp?.run){try{state.cp.run=await api('local-runs/'+state.cp.run.id);await save();drawResults();}catch(e){error(e);}}
  }
  window.InvestmentRuleScreen={open,read,put};
})();
