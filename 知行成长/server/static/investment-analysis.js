/* Selected-input AI analysis. This component never stores credentials or financial data locally. */
(() => {
  'use strict';
  const esc=value=>String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const stamp=()=>new Date(Date.now()+8*3600000).toISOString().slice(0,19);
  let dialog=null,timer=null;
  async function api(path,options={}) {
    const response=await fetch('/api/investments/'+path,{credentials:'same-origin',...options,
      headers:{'Content-Type':'application/json','X-Copilot-Request':'1',...(options.headers || {})}});
    const value=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(value.message || '投资分析请求未完成，请核对后重试。');
    return value;
  }
  function close() {clearTimeout(timer);if(dialog){dialog.close();dialog.remove();dialog=null;}}
  function mount(title) {
    close();dialog=document.createElement('dialog');dialog.className='inv-dialog';
    dialog.setAttribute('aria-labelledby','inv-ai-title');
    dialog.innerHTML=`<h3 id="inv-ai-title">${esc(title)}</h3><div data-inv-ai-body></div><p role="alert" data-inv-ai-error></p><button type="button" class="btn" data-inv-ai-close>关闭</button>`;
    document.body.append(dialog);dialog.showModal();dialog.querySelector('[data-inv-ai-close]').onclick=close;
    const current=dialog;
    current.addEventListener('close',()=>{current.remove();if(dialog===current){clearTimeout(timer);dialog=null;}});return dialog;
  }
  function error(d,e) {if(d.isConnected)d.querySelector('[data-inv-ai-error]').textContent=e.message;}
  function metadata(job) {
    return {id:job.id,kind:'investment_analysis',source:'investments',label:'投资研究与复盘',
      title:'本人选定资料分析',state:job.state,phase:job.phase};
  }
  function track(job) {window.GenerationTasks?.track(metadata(job));}
  function checkboxes(items,type,title) {
    return `<fieldset><legend>${esc(title)}</legend>${items.length?items.map(item=>`<label class="inv-ai-choice"><input type="checkbox" data-inv-source="${type}" value="${esc(item.id)}">${esc(item.title || (item.text ? item.date+' '+item.text.slice(0,80) : item.period_start+' 至 '+item.period_end+' · '+item.purpose.slice(0,60)))}</label>`).join(''):'<p>没有可选记录。</p>'}</fieldset>`;
  }
  function open(context) {
    if(!context.accountId)throw new Error('请先选择投资账户。');
    const d=mount('AI研究与建议'),body=d.querySelector('[data-inv-ai-body]');
    body.innerHTML=`<form><label>分析目的<select name="kind" aria-label="分析目的"><option value="research">股票／ETF研究</option><option value="capital">理财与资金情景</option><option value="plan">交易计划检查</option><option value="review">复盘与规则试验</option></select></label>
      <label>分析标的<select name="instrument_id" aria-label="分析标的"><option value="">不限定标的</option>${context.instruments.map(i=>`<option value="${esc(i.id)}">${esc(i.name)} · ${esc(i.code)}</option>`).join('')}</select></label>
      <label>想分析的问题<textarea name="question" rows="3" required maxlength="4000"></textarea></label>
      <label>资料截止时间<input name="decision_at" type="datetime-local" step="1" value="${stamp()}" required></label>
      ${checkboxes(context.evidence,'evidence_ids','选定研究资料')}${checkboxes(context.plans,'plan_ids','选定交易计划')}${checkboxes(context.reviews,'review_ids','选定复盘')}${checkboxes(context.policies || [],'policy_ids','选定本人资金政策')}${checkboxes(context.dossiers || [],'dossier_ids','选定结构化研究')}${checkboxes((context.campaigns || []).map(c=>({id:c.id,title:'完整交易 · '+(context.instruments.find(i=>i.id===c.instrument_id)?.name || '标的未载入')+' · '+c.opened_at})),'campaign_ids','选定完整交易链')}
      <label class="inv-ai-choice"><input type="checkbox" name="include_amounts">同时发送余额、持仓、所选计划与交易链的价格、数量、费用和风险数据</label>
      <p>不勾选金额时，交易链仅发送方向、时间、原计划文字与原话。正文仍可能包含金额，请在下一步逐项核对。仅使用所选资料，不声称实时行情。</p>
      <button type="submit" class="btn">预览将发送的资料</button></form>
      <section data-inv-ai-preview hidden></section>`;
    const form=body.querySelector('form'),previewBox=body.querySelector('[data-inv-ai-preview]');
    let preview=null,requestKey=crypto.randomUUID(),busy=false;
    const invalidate=()=>{preview=null;previewBox.hidden=true;previewBox.replaceChildren();};
    form.addEventListener('input',invalidate);
    form.onsubmit=async event=>{
      event.preventDefault();if(busy)return;busy=true;
      const button=form.querySelector('button');button.disabled=true;
      try {
        const fields=new FormData(form);
        const payload={account_id:context.accountId,instrument_id:fields.get('instrument_id') || null,
          kind:fields.get('kind'),question:fields.get('question'),decision_at:fields.get('decision_at')+'+08:00',
          include_amounts:fields.get('include_amounts')==='on'};
        for(const type of ['evidence_ids','plan_ids','review_ids','policy_ids','dossier_ids','campaign_ids'])payload[type]=[...form.querySelectorAll(`[data-inv-source="${type}"]:checked`)].map(i=>i.value);
        const selected=await api('analysis/preview',{method:'POST',body:JSON.stringify(payload)});
        if(!d.isConnected)return;
        preview=selected;requestKey=crypto.randomUUID();previewBox.hidden=false;
        let destination='尚未配置个人模型';
        try {const cfg=window.AIConfig?.require();if(cfg)destination=`${cfg.api_base_url} · ${cfg.model_name}`;}catch{}
        previewBox.innerHTML=`<h4>核对发送范围</h4><p>目的地：${esc(destination)}</p><p>研究 ${selected.snapshot.evidence.length} 条 · 计划 ${selected.snapshot.plans.length} 条 · 复盘 ${selected.snapshot.reviews.length} 条 · ${payload.include_amounts?'包含账户金额':'排除结构化账户金额'}</p>${selected.snapshot.limitations.map(t=>`<p>${esc(t)}</p>`).join('')}<p>将进行主分析与同模型反证两次调用，可能产生服务商费用。</p><details><summary>查看完整发送内容</summary><pre data-inv-ai-json></pre></details><div class="inv-actions"><button type="button" class="btn" data-inv-ai-submit>确认发送并分析</button><button type="button" class="btn" data-inv-ai-config>配置个人模型</button></div>`;
        previewBox.querySelector('pre').textContent=JSON.stringify(selected.snapshot,null,2);
        previewBox.querySelector('[data-inv-ai-config]').onclick=()=>{close();window.AISetup?.open();};
        previewBox.querySelector('[data-inv-ai-submit]').onclick=async submitEvent=>{
          if(!preview || busy)return;busy=true;submitEvent.target.disabled=true;button.disabled=true;
          try {
            if(!window.AIConfig)throw new Error('请先在设置中配置个人模型。');
            const cfg=window.AIConfig.require();
            const job=await api('analysis/jobs',{method:'POST',headers:{'Idempotency-Key':requestKey},
              body:JSON.stringify({preview_id:preview.id,snapshot_hash:preview.snapshot_hash,ai_config:cfg})});
            track(job);await showJob(job.id);
          }catch(e){error(d,e);submitEvent.target.disabled=false;button.disabled=false;}
          finally{busy=false;}
        };
      }catch(e){error(d,e);}
      finally{busy=false;button.disabled=false;}
    };
    form.querySelector('textarea').focus();
  }

  function reportHTML(job) {
    const r=job.report;
    return `<p>${esc(job.validation_note)}</p><p class="inv-notice">以下为AI研究与推断，未经独立核验。反证由同一模型完成，建议仍需本人核对。</p>
      ${job.current_input_status==='outdated'?'<p class="inv-notice">所依据记录已更新，本报告保留为历史分析，采用前需重新核对。</p>':''}${job.expired_suggestion_count?`<p>已有 ${job.expired_suggestion_count} 项建议到期。</p>`:''}<h4>理财情景（假设与草稿）</h4>${(r.scenarios || []).map((s,scenarioIndex)=>`<article class="inv-record"><h4>${esc(s.name)} · ${s.mode==='education'?'教育情景':'本人资料下的条件草案'}</h4><p>假设：${esc(s.assumptions.join('；'))}</p><p>约束：${esc(s.constraints.join('；'))}</p>${Object.entries(s.allocation).map(([t,a])=>`<p>${esc(t)}：${esc(a)}</p>`).join('')}<p>缺项：${esc(s.missing_inputs.join('；') || '仍需本人核对')}</p><p>${esc(s.next_step)}</p>${s.mode==='personal_draft'?`<p>生成草稿沿用本人原政策金额与风险约束，不自动采用模型分配数字。</p><button class="btn" type="button" data-inv-capital="${scenarioIndex}" ${job.current_input_status==='outdated'?'disabled':''}>形成资金政策修改草稿</button><p data-capital-status></p>`:''}</article>`).join('')}<h4>分析摘要</h4><p class="inv-preserve">${esc(r.summary)}</p>
      <h4>程序计算引用</h4>${(r.calculations || []).map(c=>`<p>${esc(c.field)}：${esc(c.value)} · 原计划 ${esc(c.plan_id)}</p>`).join('') || '<p>没有绑定的程序计算，不将模型数值当作核验结果。</p>'}<h4>选定原文摘录</h4>${r.facts.map(f=>{const source=(job.evidence_sources || []).find(e=>e.id===f.evidence_id) || {};return `<blockquote>${esc(f.quote)}<small> · ${esc(source.title || f.evidence_id)} · 可获知 ${esc(source.available_at || '未标注')}</small>${source.source_url?`<p><a href="${esc(source.source_url)}" target="_blank" rel="noopener noreferrer">核对原始链接</a></p>`:''}<button class="btn" type="button" data-inv-evidence="${esc(f.evidence_id)}">查看保留原文</button></blockquote>`;}).join('') || '<p>没有可匹配的事实摘录。</p>'}
      <h4>选定账本字段引用</h4>${(r.trade_citations || []).map(c=>`<p>${esc(({side:'方向',executed_at:'成交时间',price:'价格',quantity:'数量',fee:'手续费',tax:'税费',settlement_amount:'基金实际净额',net_realized:'已实现净结果',risk_basis:'冻结风险基数',realized_r:'实际R'})[c.field])}：${esc(c.value==='buy'?'买入':c.value==='sell'?'卖出':c.value)}</p>`).join('') || '<p>未引用账本数值；不得用AI猜测替代实际成交。</p>'}<h4>推断与假设</h4>${r.inferences.map(t=>`<p>${esc(t)}</p>`).join('')}
      <h4>反对理由</h4>${r.counterarguments.map(t=>`<p>${esc(t)}</p>`).join('')}
      <h4>尚缺资料</h4>${r.missing_inputs.map(t=>`<p>${esc(t)}</p>`).join('')}
      <h4>可选下一步</h4>${r.suggestions.map((s,index)=>`<article class="inv-record"><h4>${esc(s.title)}</h4><p>${esc(s.reason)}</p><p>触发：${esc(s.trigger)}<br>失效：${esc(s.invalidation)}</p><p>有效截至 ${esc(s.valid_until)}</p><div class="inv-actions"><button type="button" class="btn" data-inv-decision="adopted" data-index="${index}" ${job.current_input_status==='outdated' || Date.parse(s.valid_until)<=Date.now()?'disabled':''}>${['conditional_entry','check_exit'].includes(s.action)?'采用为计划草稿':'保存为思考'}</button><button type="button" class="btn" data-inv-decision="rejected" data-index="${index}">不采用</button><button type="button" class="btn" data-inv-decision="retained" data-index="${index}">稍后核对</button><button type="button" class="btn" data-inv-decision="untriggered" data-index="${index}">记录未触发</button><button type="button" class="btn" data-inv-decision="unfilled" data-index="${index}">记录未成交</button><button type="button" class="btn" data-inv-decision="modified" data-index="${index}">记录已另行修改</button></div><p data-inv-decision-status></p></article>`).join('')}`;
  }
  async function showJob(id) {
    const d=mount('投资AI分析'),body=d.querySelector('[data-inv-ai-body]');
    async function refresh() {
      if(!d.isConnected)return;
      try {
        const job=await api('analysis/jobs/'+encodeURIComponent(id));
        if(!d.isConnected)return;track(job);
        body.innerHTML=`<p role="status">${esc(job.phase)}</p><small>模型 ${esc(job.model || '')} · ${esc(job.updated_at)}</small>`;
        if(job.state==='ready') {
          body.insertAdjacentHTML('beforeend',reportHTML(job));
          body.querySelectorAll('[data-inv-evidence]').forEach(button=>button.onclick=async()=>{try{await window.Investments.openRecord({resource:'research',id:button.dataset.invEvidence});}catch(e){error(d,e);}});
          body.querySelectorAll('[data-inv-capital]').forEach(button=>button.onclick=async()=>{
            button.disabled=true;
            try {
              await api(`analysis/jobs/${encodeURIComponent(id)}/scenarios/${button.dataset.invCapital}/policy-draft`,{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()}});
              button.closest('article').querySelector('[data-capital-status]').textContent='已生成资金政策修改草稿，原生效版本保留，仍需本人另行确认。';
              await window.Investments?.refresh();
            }catch(e){error(d,e);button.disabled=false;}
          });
          body.querySelectorAll('[data-inv-decision]').forEach(button=>button.onclick=async()=>{
            button.disabled=true;
            try {
              const result=await api(`analysis/jobs/${encodeURIComponent(id)}/suggestions/${button.dataset.index}/decision`,
                {method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify({state:button.dataset.invDecision,note:''})});
              button.closest('article').querySelector('[data-inv-decision-status]').textContent=result.state!=='adopted'?'已记录你的选择。':result.linked_kind==='trade-plans'?'已关联计划，请查看当前版本与状态；不会下单。':result.linked_kind==='reviews'?'已保存为投资思考。':'已记录你的选择。';
              await window.Investments?.refresh();
            }catch(e){error(d,e);button.disabled=false;}
          });
        } else if(['queued','running'].includes(job.state)) {
          const cancel=document.createElement('button');cancel.type='button';cancel.className='btn';cancel.textContent='取消分析';
          cancel.onclick=async()=>{cancel.disabled=true;try {track(await api(`analysis/jobs/${encodeURIComponent(id)}/cancel`,{method:'POST'}));await refresh();}catch(e){error(d,e);cancel.disabled=false;}};
          body.append(cancel);timer=setTimeout(refresh,2000);
        } else body.insertAdjacentHTML('beforeend','<p>保留已有进度。重试需返回选定资料并重新确认，不会自动再次调用模型。</p>');
      }catch(e){error(d,e);if(d.isConnected)timer=setTimeout(refresh,8000);}
    }
    await refresh();
  }
  async function reports() {
    const d=mount('历史AI报告与建议'),body=d.querySelector('[data-inv-ai-body]');
    try {
      const [jobs,decisions]=await Promise.all([api('analysis/jobs'),api('recommendations')]);
      if(!d.isConnected)return;
      body.innerHTML=`<p>未采用、未触发和无法判定的建议保留；模拟结果不计入实盘资金。</p>${jobs.items.map(job=>`<article class="inv-record"><h4>${esc(job.phase)}</h4><small>${esc(job.created_at)}</small><button type="button" class="btn" data-inv-open-job="${esc(job.id)}">查看${job.state==='ready'?'结果':'进度'}</button></article>`).join('') || '<p>尚无AI报告。</p>'}<h4>已记录的建议选择</h4>${decisions.items.map(item=>`<p>${esc(item.suggestion_snapshot.title)} · ${esc(({adopted:'已采用',rejected:'不采用',retained:'稍后核对',untriggered:'未触发',unfilled:'未成交',modified:'已修改'})[item.state])} · 资金结果尚未判定</p>`).join('') || '<p>尚未处理建议。</p>'}`;
      body.querySelectorAll('[data-inv-open-job]').forEach(button=>button.onclick=()=>showJob(button.dataset.invOpenJob));
    }catch(e){error(d,e);}
  }
  window.InvestmentAI={open,reports,showJob};
  window.GenerationTasks?.register('investments',{
    read:async job=>metadata(await api('analysis/jobs/'+encodeURIComponent(job.id))),
    open:job=>{window.goTab?.('stocks');return showJob(job.id);},
    cancel:async job=>metadata(await api('analysis/jobs/'+encodeURIComponent(job.id)+'/cancel',{method:'POST'})),
    recover:async()=> (await api('analysis/jobs')).items.map(metadata)
  }).catch(()=>{});
})();
