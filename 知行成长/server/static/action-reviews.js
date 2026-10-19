/* Account-private review drafts; provider credentials stay out of operation journals. */
(() => {
  'use strict';
  const node=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;};
  function field(parent,label,type,value){const wrap=node('label',label,'action-field'),el=node(type==='textarea'?'textarea':'input');el.setAttribute('aria-label',label);if(type!=='textarea')el.type=type;if(type==='checkbox')el.checked=!!value;else el.value=value||'';wrap.append(el);parent.append(wrap);return el;}
  function button(parent,label,run,primary=false){const b=node('button',label,'btn'+(primary?' primary':''));b.type='button';b.onclick=async()=>{b.disabled=true;try{await run();}finally{b.disabled=false;}};parent.append(b);return b;}
  function statsText(s){return `累计 ${s.minutes} 分钟 · ${s.completed} 次达标 · ${s.minimum} 次起步 · ${s.partial||0} 次部分执行 · ${s.interrupted} 次中断 · 日行动 ${s.completed_days} / ${s.planned_days} 项达标`;}
  function open({client,plan,dialog,edit}){
    const d=dialog('进度复盘与 AI 建议'),draftKey='review.'+plan.id,draft=client.get(draftKey)||{},form=node('form');d.append(node('h3',plan.title),node('p','所选计划及其下级行动按执行时的业务日期统计。统计包含全部记录；AI 明细取最近 30 条，长文本截取后会在预览标明。每次保存形成独立历史记录。','desc'),form);
    const dates=node('div',undefined,'action-form-grid');form.append(dates);
    const begin=field(dates,'复盘开始日期','date',draft.start_date||plan.start_date||ActionPlans.day(plan.timezone)),end=field(dates,'复盘结束日期','date',draft.end_date||plan.end_date||ActionPlans.day(plan.timezone));
    for(const el of [begin,end]){el.required=true;}
    const preview=node('section',undefined,'action-review-preview'),error=node('p','','action-error');error.setAttribute('role','alert');form.append(preview,error);
    const worked=field(form,'做得好的地方','textarea',draft.worked),obstacles=field(form,'阻碍或分心的原因','textarea',draft.obstacles),next=field(form,'下一步准备怎么做','textarea',draft.next_action);
    for(const el of [worked,obstacles,next])el.maxLength=2000;
    const actions=node('div',undefined,'action-buttons');form.append(actions);const save=node('button','保存本次复盘','btn primary');save.type='submit';actions.append(save);
    const ai=node('section',undefined,'action-ai-review');d.append(ai);ai.append(node('h3','AI 总结与建议'),node('p','生成前先查看下方数据预览。只发送所选计划、范围内执行事实，以及你勾选的内容到设置中的 AI 服务；不读取学习笔记，不会自动调整计划。','desc'));
    const notes=field(ai,'包含执行记录中的收获和中断原因','checkbox',draft.include_notes),reviews=field(ai,'包含此范围内最近 5 次已保存复盘','checkbox',draft.include_review),consent=field(ai,'同意将预览的数据发送到我配置的 AI 服务','checkbox',false);
    const aiActions=node('div',undefined,'action-buttons');ai.append(aiActions);
    const history=node('section',undefined,'action-review-history');d.append(history);let generation=0,historyPage=1,pollTimer=null,previewSignature='',snapshotHash='';
    const scope=()=>({plan_id:plan.id,start_date:begin.value,end_date:end.value,include_notes:notes.checked,include_review:reviews.checked});
    function remember(){client.put(draftKey,{...scope(),worked:worked.value,obstacles:obstacles.value,next_action:next.value});}
    function dirty(){remember();previewSignature='';consent.checked=false;generate.disabled=true;preview.replaceChildren(node('p','数据范围已变更，请刷新数据预览。'));}
    for(const el of [begin,end,notes,reviews])el.addEventListener('change',dirty);
    for(const el of [worked,obstacles,next])el.addEventListener('input',remember);
    async function loadPreview(){consent.checked=false;const turn=++generation;preview.replaceChildren(node('p','正在统计所选范围…'));error.textContent='';generate.disabled=true;try{const data=await client.read('/reviews/preview',scope());if(!d.isConnected||turn!==generation)return;previewSignature=JSON.stringify(scope());snapshotHash=data.snapshot_hash;preview.replaceChildren(node('h4','将用于复盘的数据'),node('p',`${data.start_date} 至 ${data.end_date} · ${data.plan.title}`),node('p',statsText(data.stats)));
        const details=node('details');details.append(node('summary','查看将发送的完整数据'),node('pre',JSON.stringify(data,null,2),'action-context'));preview.append(details);generate.disabled=false;
      }catch(e){error.textContent=e.message;}}
    button(aiActions,'刷新数据预览',loadPreview);
    const generate=button(aiActions,'生成 AI 总结与建议',async()=>{error.textContent='';remember();if(!consent.checked){error.textContent='请先确认发送预览的数据。';return;}if(previewSignature!==JSON.stringify(scope())){error.textContent='范围已变化，请刷新数据预览后再生成。';return;}
      try{const config=window.AIConfig.require();await client.write('summary:'+plan.id,'/reviews/generate',{...scope(),consent:true,snapshot_hash:snapshotHash},{ai_config:config});consent.checked=false;await loadHistory();}catch(e){error.textContent=e.message;}
    },true);generate.disabled=true;
    form.onsubmit=async event=>{event.preventDefault();save.disabled=true;remember();error.textContent='正在保存复盘…';try{await client.write('review:'+plan.id,'/reviews',{plan_id:plan.id,start_date:begin.value,end_date:end.value,worked:worked.value,obstacles:obstacles.value,next_action:next.value});worked.value='';obstacles.value='';next.value='';remember();error.textContent='复盘已保存。';await loadHistory();await loadPreview();consent.checked=false;}catch(e){error.textContent=e.message;}finally{save.disabled=false;}};
    async function loadHistory(){if(!d.isConnected)return;clearTimeout(pollTimer);try{const data=await client.read('/reviews?plan_id='+encodeURIComponent(plan.id)+'&page='+historyPage);if(!d.isConnected)return;history.replaceChildren(node('h3','历史复盘与建议'));for(const r of data.reviews){const row=node('article',undefined,'action-history-row');row.append(node('strong',r.start_date+' 至 '+r.end_date+' · 手动复盘'),node('p','保存于 '+new Date(r.created_at).toLocaleString()));for(const [name,key] of [['做得好的地方','worked'],['阻碍','obstacles'],['下一步','next_action']])if(r[key])row.append(node('p',name+'：'+r[key]));history.append(row);}
        for(const r of data.reports){const row=node('article',undefined,'action-history-row');row.append(node('strong',r.start_date+' 至 '+r.end_date+' · AI 建议'),node('p','生成于 '+new Date(r.created_at).toLocaleString()+' · '+r.model));if(r.state==='ready')row.append(node('p',r.text,'action-ai-text'));else row.append(node('p',r.state==='generating'?'正在生成，可以关闭后再回来查看。':r.error));history.append(row);}
        if(!data.reviews.length&&!data.reports.length)history.append(node('p','还没有保存复盘。可以先写下一件做得好的事。'));
        const pages=node('div',undefined,'action-buttons');history.append(pages);button(pages,'较新的复盘',async()=>{historyPage--;await loadHistory();}).disabled=historyPage===1;pages.append(node('span','第 '+historyPage+' 页'));button(pages,'更早的复盘',async()=>{historyPage++;await loadHistory();}).disabled=historyPage*20>=Math.max(data.review_total,data.report_total);
        if(data.reports.some(r=>r.state==='generating'))pollTimer=setTimeout(loadHistory,2500);
      }catch(e){error.textContent=e.message;}}
    const bottom=node('div',undefined,'action-buttons');d.append(bottom);if(!['completed','archived'].includes(plan.status))button(bottom,'参考建议，手动调整计划',()=>{remember();d.close();edit();});button(bottom,'关闭并保留草稿',()=>{remember();d.close();});button(bottom,'刷新历史结果',loadHistory);
    d.addEventListener('close',()=>{clearTimeout(pollTimer);generation++;},{once:true});loadPreview();loadHistory();
  }
  window.ActionReviews={open};
})();
