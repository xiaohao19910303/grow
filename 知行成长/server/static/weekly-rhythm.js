/* Natural-week facts stay separate from the legacy habits-based report. */
(() => {
  let chosenWeek=null,request=0;
  const root=document.getElementById('weeklyRhythm'),view=document.getElementById('view-report'),seen=new Set();
  function monday(day){const d=new Date(day+'T12:00:00Z');d.setUTCDate(d.getUTCDate()-(d.getUTCDay()+6)%7);return d.toISOString().slice(0,10);}
  async function load(){const turn=++request;const ui=window.DailyRhythm,client=ui?.client(),state=ui?.state();if(!client||!state||!state.preferences.enabled){root.hidden=true;return;}
    const {node,button,field}=ui;root.hidden=false;root.replaceChildren(node('h2','本周行动成果'),node('p','正在读取本人确认的行动…'));
    try{const week=chosenWeek||monday(window.ActionPlans.day(state.preferences.timezone)),data=await client.read('/weeks/'+week);if(turn!==request)return;
      root.replaceChildren(node('h2','行动成果 · '+data.week_start+' 至 '+data.week_end),node('p',data.is_partial?'截至 '+data.as_of+'，本周尚未结束。':'完整自然周；与下方习惯周报分别统计。','desc'));
      root.append(node('p',`已行动 ${data.stats.action_days} / ${data.target_days} 天 · 完整闭环 ${data.stats.loop_days} 天`,'rhythm-progress'),node('p',`标准版本 ${data.stats.standard_days} 天 · 最低版本 ${data.stats.minimum_days} 天（同日可同时出现）`,'desc'));
      const weekInput=field(root,'回看周（选择周一）',data.week_start,'date');weekInput.onchange=()=>{if(!weekInput.value)return;chosenWeek=monday(weekInput.value);load();};
      if(data.changed)root.append(node('p','确认后有新的行动或总结，可以重新回看；旧确认版本仍然保留。','desc'));
      if(!data.records.length)root.append(node('p','本周还没有确认的行动，随时可以从一小步开始。'));
      for(const r of data.records.slice(0,3)){const box=node('article',undefined,'rhythm-record');box.append(node('strong',r.title),node('p',r.note||'已保存实际行动，暂无总结。'));root.append(box);}
      if(data.card){root.append(node('p','本人选择的调整：'+(data.card.adjustment_text||'本次未填写调整。')));
        const history=node('details');history.append(node('summary',`已确认版本 ${data.card.revision} · 查看历史`));
        for(const c of [...data.card.history,data.card]){const box=node('article',undefined,'rhythm-record');box.append(node('p',`版本 ${c.revision} · ${c.confirmed_at}`),node('p',c.adjustment_text||'未填写调整'));
          for(const id of c.selected_execution_ids){const r=c.records.find(r=>r.id===id);if(r)box.append(node('p',r.title+'：'+(r.note||'实际行动已保存。')));}history.append(box);}root.append(history);}
      button(root,data.card?'重新确认本周成果':'选择成果与一项调整',()=>edit(data),true);
      if(!seen.has(week)&&view.style.display!=='none'&&!document.hidden){seen.add(week);ui.event({event_name:'weekly_card_viewed',week_start:week,source:'weekly'});}
    }catch(e){if(turn!==request)return;root.replaceChildren(node('p','周成果暂未读取：'+e.message));button(root,'重试周成果',load);}}
  function edit(data){const ui=window.DailyRhythm,{node,button,field,option,modal}=ui,client=ui.client(),draftKey='weekly.'+data.week_start,draft=client.get(draftKey)||{},d=modal('选择本周成果'),form=node('form');d.append(form);const done=ui.burden('weekly','weekly');d.addEventListener('close',()=>done('cancel'));
    form.append(node('p','最多选择三条实际成果，下一周只尝试一项调整。','desc'));const list=node('div',undefined,'rhythm-week-facts'),checks=[];form.append(list);
    for(const r of data.records){const label=node('label'),check=node('input');check.type='checkbox';check.value=r.id;check.checked=(draft.selected_execution_ids||data.card?.selected_execution_ids||[]).includes(r.id);label.append(check,node('span',r.title+' · '+r.activity_date+' · '+(r.note||'实际行动已保存')));list.append(label);checks.push(check);}
    const adjustment=field(form,'下一周的一项调整（可选）',draft.adjustment_text??data.card?.adjustment_text??'','textarea',500),target=field(form,'关联今天或未来的行动（可选）','','select');option(target,'','暂不关联');for(const p of window.ActionPlans.snapshot().plans.filter(p=>p.period==='day'&&p.status==='active'&&!p.blocked&&p.start_date>=window.ActionPlans.day(p.timezone)))option(target,p.id,p.start_date+' · '+p.title);target.value='adjustment_target_plan_id' in draft?(draft.adjustment_target_plan_id||''):(data.card?.adjustment_target_plan_id||'');
    const payload=()=>({expected_revision:data.card?.revision||0,snapshot_hash:data.snapshot_hash,selected_execution_ids:checks.filter(c=>c.checked).map(c=>c.value),adjustment_text:adjustment.value,adjustment_target_plan_id:target.value||null});form.addEventListener('input',()=>client.put(draftKey,payload()));
    const error=node('p','','action-error');error.setAttribute('role','alert');form.append(error);const save=node('button','确认本周成果','btn primary');save.type='submit';form.append(save);button(form,'稍后回看',()=>d.close());
    form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{client.put(draftKey,payload());await client.write('weekly:'+data.week_start,'/weeks/'+data.week_start+'/confirm',payload());client.remove(draftKey);done('save');d.close();toast('本周成果已确认，下一步按自己的节奏尝试。');await load();}catch(e){done('error');error.textContent=e.message;ui.recoverPending(error,'weekly:'+data.week_start,'/weeks/'+data.week_start+'/confirm',async()=>{client.put(draftKey,payload());d.close();await load();});if(e.code==='SNAPSHOT_CONFLICT'||e.code==='REVISION_CONFLICT')button(error,'保留草稿并重新回看',async()=>{d.close();await load();});}finally{save.disabled=false;}};
  }
  window.WeeklyRhythm={load,open:async()=>{goTab('report');await load();}};
  window.EventBus?.on('rhythm:saved',()=>{if(view.style.display!=='none')load();});
  window.EventBus?.on('plans:loaded',()=>{if(view.style.display!=='none')load();});
})();
