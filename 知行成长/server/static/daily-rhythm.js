/* Optional daily rhythm: one focus, factual progress and recoverable summary drafts. */
(() => {
  'use strict';
  const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
  const card=document.getElementById('dailyRhythm'),settingsRoot=document.getElementById('rhythmSettings');
  let client,state,capability,turn=0,ready,dialogOpen=null,accountId,settingsInitialized=false;
  card.hidden=false;card.append(node('h2','今日一件事'),node('p','正在读取日常节奏…'));
  const snap=()=>window.ActionPlans?.snapshot()||{plans:[]};
  const activeAccount=()=>!window.Account?.user?.id||window.Account.user.id===accountId;
  function button(parent,text,run,primary=false){const b=node('button',text,'btn'+(primary?' primary':''));b.type='button';b.onclick=async()=>{b.disabled=true;try{await run();}catch(e){toast(e.message);}finally{b.disabled=false;}};parent.append(b);return b;}
  function recoverPending(parent,id,path,after,action=false){if(!client.pending(id)||parent.querySelector('[data-pending-recovery]'))return;const b=button(parent,'恢复上次提交',async()=>{const result=await (action?client.actionRetry(id,path):client.retry(id,path));await after(result);});b.dataset.pendingRecovery='true';}
  function field(parent,label,value='',type='text',limit){const wrap=node('label',label,'action-field'),input=node(type==='textarea'?'textarea':type==='select'?'select':'input');input.setAttribute('aria-label',label);if(!['textarea','select'].includes(type))input.type=type;input.value=value;if(limit)input.maxLength=limit;wrap.append(input);parent.append(wrap);return input;}
  function option(parent,value,text){const o=node('option',text);o.value=value;parent.append(o);}
  function modal(title){dialogOpen?.close();const origin=document.activeElement,d=node('dialog',undefined,'action-dialog rhythm-dialog');dialogOpen=d;d.setAttribute('aria-label',title);d.append(node('h2',title));document.body.append(d);d.addEventListener('close',()=>{d.remove();if(dialogOpen===d)dialogOpen=null;if(origin?.isConnected)origin.focus();});d.showModal();return d;}
  function burden(formKind,source){let total=0,last=performance.now(),active=!document.hidden&&document.hasFocus(),done=false;
    const update=()=>{const t=performance.now();if(active)total+=t-last;last=t;active=!document.hidden&&document.hasFocus();};
    document.addEventListener('visibilitychange',update);window.addEventListener('focus',update);window.addEventListener('blur',update);
    return result=>{if(done)return;update();if(result!=='error'){done=true;document.removeEventListener('visibilitychange',update);window.removeEventListener('focus',update);window.removeEventListener('blur',update);}
      event({event_name:'form_finished',source,form_kind:formKind,result,active_duration_ms:Math.min(3600000,Math.round(total))});};
  }
  function event(data){if(!state?.preferences.enabled||!activeAccount())return;client.queue({event_id:crypto.randomUUID(),session_id:session,...data});client.flush();}
  const session=crypto.randomUUID();
  async function refresh(date){await ready;if(!activeAccount())return;const current=++turn;
    try{const cap=await client.read('/capabilities');if(current!==turn)return;capability=cap;
      if(cap.contract_version!==1||typeof cap.supported!=='boolean'){state=null;render();return;}
      if(cap.reason&&cap.reason!=='FEATURE_DISABLED'){state=null;render();return;}
      const selected=date||document.getElementById('personalDate')?.value;
      const next=await client.read('/today'+(selected?'?date='+encodeURIComponent(selected):''));if(current!==turn)return;state=next;render();
      // The first startup read may be superseded; initialize from the winning read.
      // Later background reads must leave unsaved settings input in place.
      if(!settingsInitialized)settings();client.flush();
    }catch(e){if(current!==turn)return;card.replaceChildren(node('p','日常节奏暂未读取：'+e.message));button(card,'重试日常节奏',()=>refresh(date));}
  }
  function render(){card.replaceChildren(node('h2','今日一件事'));card.hidden=false;
    if(!state){settingsInitialized=false;card.append(node('p','当前连接端尚未支持日常节奏，已有行动仍可使用。','desc'));settingsRoot.replaceChildren(node('h2','日常节奏'),node('p','当前连接端暂不支持此功能。'));return;}
    if(!state.preferences.enabled){card.append(node('p','选一件事、做一点、留一句收获。可在设置中开启，随时可以关闭。','desc'));button(card,'设置日常节奏',()=>{goTab('settings');settings();});return;}
    const progress=state.progress||{},focus=state.focus,plan=snap().plans.find(p=>p.id===focus?.plan_id);
    card.append(node('p',`本周已行动 ${progress.action_days||0} / ${state.preferences.weekly_target_days} 天 · 闭环 ${progress.loop_days||0} 天`,'rhythm-progress'));
    if(state.read_only)card.append(node('p',state.date+' · 主任务历史只读','desc'));
    if(focus){card.append(node('h3',plan?.title||'已选行动'),node('p',focus.rest?'今天休息，已保存的行动仍然保留。':focus.mode==='minimum'?'今天轻一点：'+focus.minimum_step:focus.success_criterion||'按行动原标准推进。'));
      if(focus.first_step)card.append(node('p','第一步：'+focus.first_step,'desc'));
      if(!state.read_only&&!focus.rest&&plan){if(state.execution)button(card,'回到正在执行的行动',()=>window.ActionPlans.resumeExecution());
        else if(plan.status==='active'&&!plan.blocked){if(plan.completion_mode==='check')button(card,focus.mode==='minimum'?'确认做过最小一步':'完成这件事',()=>focus.mode==='minimum'?smallStep(plan,focus):window.ActionPlans.change(plan,'complete'),true);
          else button(card,'开始这次行动',()=>window.ActionPlans.start(plan,focus.mode),true);}}
      for(const r of state.records.filter(r=>r.ended_at&&r.record_kind!=='reversal'&&r.activity_confirmed)){const row=node('div',undefined,'rhythm-record');row.append(node('p',r.note||'行动已保存，可以稍后留一句总结。'));if(r.next_step)row.append(node('p','下一步：'+r.next_step,'desc'));button(row,r.note?'查看或修改总结':'补一句总结',()=>recap(r.id));card.append(row);}
    }else card.append(node('p','从今天的安排中选一件想推进的事。','desc'));
    if(!state.read_only){button(card,focus?'更换或编辑今日一件事':'选择今日一件事',focusForm);if(focus){button(card,'今天轻一点',()=>mode('minimum'));button(card,'按标准推进',()=>mode('standard'));button(card,'今天休息',()=>mode('rest'));}
      if(state.continuation)button(card,'查看上次下一步',()=>{const d=modal('沿用下一步');d.append(node('p',state.continuation.next_step),node('p','请新建或选择今天的行动，旧安排不会自动改期。','desc'));button(d,'选择今日行动',()=>{d.close();focusForm(state.continuation.next_step);});button(d,'暂不沿用',()=>d.close());});}
    button(card,'回看本周成果',()=>window.WeeklyRhythm?.open());
  }
  function settings(draft=null){if(!state)return;settingsInitialized=true;const p={...(state.pending_preferences||state.preferences),...draft};settingsRoot.replaceChildren(node('h2','日常节奏'));const form=node('form');settingsRoot.append(form);
    const enabled=field(form,'开启日常节奏',null,'checkbox');enabled.checked=draft?.enabled??state.preferences.enabled;
    const zone=field(form,'时区',p.timezone),target=field(form,'每周行动目标天数',p.weekly_target_days,'number');target.min=1;target.max=7;
    const review=field(form,'周回顾星期（1周一至7周日）',p.review_weekday,'number');review.min=1;review.max=7;
    const reminder=field(form,'网页打开时提醒',null,'checkbox');reminder.checked=draft?.reminder_enabled??state.preferences.reminder_enabled;
    const when=field(form,'提醒时间',p.reminder_time||'20:00','time');form.append(node('p','首次设置立即生效；以后目标、时区和回顾星期从下周生效。提醒默认关闭，关网页后不送达。','desc'));
    if(state.pending_preferences)form.append(node('p','待生效：'+p.effective_from,'desc'));
    const err=node('p','','action-error');err.setAttribute('role','alert');form.append(err);const save=node('button','保存节奏设置','btn primary');save.type='submit';form.append(save);
    const base=state.preferences.revision,values=()=>({enabled:enabled.checked,timezone:zone.value,weekly_target_days:Number(target.value),review_weekday:Number(review.value),reminder_enabled:reminder.checked,reminder_time:reminder.checked?when.value:null});
    form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{await client.write('preferences','/preferences',{expected_revision:base,...values()});await refresh();settings();toast('节奏设置已保存。');}catch(e){err.textContent=e.message;recoverPending(err,'preferences','/preferences',async()=>{const draft=values();await refresh();settings(draft);});button(err,'重新读取设置',async()=>{await refresh();settings();});}finally{save.disabled=false;}};
    button(settingsRoot,'导出节奏数据',async()=>{const data=await client.read('/export'),url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})),a=node('a');a.href=url;a.download='grow-rhythm.json';a.click();URL.revokeObjectURL(url);});
    button(settingsRoot,'两周试用与问卷',()=>trial());
  }
  function focusForm(firstStep=''){const d=modal('选择今日一件事'),form=node('form'),draftKey='focus.draft.'+state.date,draft=client.get(draftKey)||{};d.append(form);const done=burden('focus','today');d.addEventListener('close',()=>done('cancel'));
    const choose=field(form,'今日行动','','select');option(choose,'','请选择');for(const p of snap().plans.filter(p=>p.period==='day'&&p.start_date===state.date&&p.status==='active'&&!p.blocked))option(choose,p.id,p.title);option(choose,'new','新建一项待办');
    const title=field(form,'新待办名称',draft.title||'','text',160),criterion=field(form,'完成标准（可选）',draft.success_criterion??state.focus?.success_criterion??'','textarea',500),first=field(form,'第一步（可选）',firstStep||(draft.first_step??state.focus?.first_step??''),'textarea',500);
    choose.value=draft.plan_id??state.focus?.plan_id??'';const created=draft.created_plan_id;let createdId=created||null;
    form.append(node('p','计时或学习行动可先从今日安排中新建，再在这里选择。','desc'));button(form,'打开完整新建行动',()=>{d.close();window.ActionPlans.newDay({date:state.date});});
    const error=node('p','','action-error');error.setAttribute('role','alert');form.append(error);const save=node('button','设为今日一件事','btn primary');save.type='submit';form.append(save);button(form,'暂不选择',()=>d.close());
    const date=state.date,revision=client.pending('focus:'+state.date)?.expected_revision??draft.expected_revision??state.focus?.revision??0;const values=()=>({plan_id:choose.value,title:title.value,success_criterion:criterion.value,first_step:first.value,created_plan_id:createdId,expected_revision:revision});
    form.addEventListener('input',()=>client.put(draftKey,values()));
    form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{let pid=choose.value;
      if(pid==='new'){if(!title.value.trim())throw Error('请填写新待办名称。');if(!createdId){const result=await client.actionWrite('create-focus:'+date,'',{title:title.value.trim(),period:'day',start_date:date,end_date:date,completion_mode:'check',target:{kind:'book'}});createdId=result.plans[0].id;client.put(draftKey,values());}pid=createdId;}
      if(!pid)throw Error('请选择今日行动。');await client.write('focus:'+date,'/focus',{date,plan_id:pid,expected_revision:revision,success_criterion:criterion.value,first_step:first.value});client.remove(draftKey);done('save');d.close();await window.ActionPlans.refresh();await refresh();
    }catch(e){done('error');error.textContent=(createdId?'行动已创建，尚未设为今日一件事。重试只补选择。':'')+e.message;recoverPending(error,'focus:'+date,'/focus',async result=>{client.put(draftKey,{...values(),expected_revision:result.focus.revision});d.close();await window.ActionPlans.refresh();await refresh();focusForm();});recoverPending(error,'create-focus:'+date,'',async result=>{client.put(draftKey,{...values(),created_plan_id:result.plans[0].id});d.close();await window.ActionPlans.refresh();await refresh();focusForm();},true);if(e.code==='REVISION_CONFLICT')button(error,'保留填写并重新核对',async()=>{d.close();await refresh();client.put(draftKey,{...values(),expected_revision:state.focus?.revision||0});focusForm();});}finally{save.disabled=false;}};
  }
  async function mode(value,draftStep){const d=modal(value==='minimum'?'今天轻一点':value==='rest'?'今天休息':'按标准推进');const step=value==='minimum'?field(d,'这次的最小一步',draftStep??(state.focus.minimum_step||state.focus.first_step||''),'textarea',500):null;
    button(d,'确认',async()=>{const id='mode:'+state.focus.id,path='/focus/'+encodeURIComponent(state.focus.id)+'/mode';try{await client.write(id,path,{expected_revision:state.focus.revision,mode:value,minimum_step:step?.value||''});d.close();await refresh();}catch(e){const error=d.querySelector('.action-error')||node('p','','action-error');error.textContent=e.message;d.append(error);recoverPending(error,id,path,async()=>{const draft=step?.value;d.close();await refresh();await mode(value,draft);});}},true);button(d,'取消',()=>d.close());}
  function smallStep(plan,focus){const d=modal('确认实际尝试');d.append(node('p',focus.minimum_step),node('p','只记录这一步的实际尝试，完整待办仍保持未完成。','desc'));
    button(d,'我已做过这一步',async()=>{const result=await client.write('step:'+focus.id,'/steps',{plan_id:plan.id,plan_revision:plan.revision,focus_day_id:focus.id,minimum_step:focus.minimum_step,did_act:true});d.close();toast('这一步已保存，今天已有行动。');await window.ActionPlans.refresh();await refresh();await recap(result.execution.id);},true);button(d,'还没尝试',()=>d.close());}
  async function recap(eid){await ready;if(!activeAccount())return;const cap=await client.read('/capabilities');if(cap.contract_version!==1||cap.reason==='CONTRACT_UPGRADE_REQUIRED')throw Error('连接端暂不支持总结。');
    const data=await client.read('/executions/'+encodeURIComponent(eid));const record=data.related_recap||data.execution;
    const draftKey='recap.'+record.id,draft=client.get(draftKey)||{},d=modal(record.note?'查看或修改总结':'补一句总结'),form=node('form');d.append(form);const done=burden('recap','records');d.addEventListener('close',()=>done('cancel'));
    form.append(node('p','行动已保存；总结不会再次结束执行或改变课程完成。','desc'));if(data.related_recap)form.append(node('p','同一行动当天已有总结，直接查看或修改这一条。','desc'));
    if(draft.note!==undefined&&record.note&&draft.note!==record.note)form.append(node('p','已保存的最新总结：'+record.note,'desc'));
    const note=field(form,'一句收获、卡点或结果',draft.note??record.note??'','textarea',2000),next=field(form,'下一步（可选）',draft.next_step??record.next_step??'','textarea',500),kind=field(form,'总结类型','','select');note.required=true;
    for(const [v,t] of [['gain','收获'],['blocker','卡点'],['result','结果']])option(kind,v,t);kind.value=draft.recap_kind||record.recap_kind||'gain';
    const version=draft.expected_recap_revision??record.recap_revision??0;const payload=()=>({expected_recap_revision:version,note:note.value,next_step:next.value,recap_kind:kind.value});form.addEventListener('input',()=>client.put(draftKey,payload()));
    const error=node('p','','action-error');error.setAttribute('role','alert');form.append(error);const save=node('button','保存一句总结','btn primary');save.type='submit';form.append(save);button(form,'稍后再写',()=>{client.put(draftKey,payload());d.close();});
    form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{client.put(draftKey,payload());const result=await client.write('recap:'+record.id,'/executions/'+encodeURIComponent(record.id)+'/recap',payload());client.remove(draftKey);done('save');d.close();toast('总结已保存：'+result.execution.note);await refresh();window.EventBus?.emit('rhythm:saved',result);}catch(e){done('error');error.textContent='行动已保存，总结待补。'+e.message;recoverPending(error,'recap:'+record.id,'/executions/'+encodeURIComponent(record.id)+'/recap',async result=>{client.put(draftKey,{...payload(),expected_recap_revision:result.execution.recap_revision||0});d.close();await recap(record.id);});if(e.code==='REVISION_CONFLICT')button(error,'读取最新版本并保留草稿',async()=>{const latest=await client.read('/executions/'+encodeURIComponent(record.id));client.put(draftKey,{...payload(),expected_recap_revision:latest.execution.recap_revision||0});d.close();await recap(record.id);});}finally{save.disabled=false;}};
  }
  async function sourceSaved(result){if(!client||!state?.preferences.enabled||!activeAccount())return;const receipts=result.action_completion_receipts||[];if(!receipts.length)return;
    const d=modal('本次完成已保存');d.append(node('p','可为已关联的行动留一句收获，稍后也能在执行记录中补写。'));for(const item of receipts)button(d,'为这次完成留一句总结',()=>recap(item.execution_id));button(d,'稍后再写',()=>d.close());}
  async function claimReminder(taskDue){if(taskDue){document.getElementById('rhythmReminder')?.remove();return;}if(!state?.preferences.enabled||!state.preferences.reminder_enabled||document.hidden||dialogOpen)return;
    const result=await client.write('reminder:'+state.date,'/reminder-claim',{});if(result.notify){const banner=node('aside',undefined,'section daily-rhythm');banner.id='rhythmReminder';banner.setAttribute('role','status');banner.append(node('p','留一点时间给今天，做一点也可以。'));button(banner,'回到今日',()=>{banner.remove();goTab('personal');});button(banner,'稍后自己安排',()=>banner.remove());document.getElementById('actionReminder').after(banner);}}
  async function trial(){await window.RhythmTrial?.open(client);}
  window.DailyRhythm={refresh,settings:()=>{settings();},recap,sourceSaved,claimReminder,event,burden,
    client:()=>client,state:()=>state,node,button,field,option,modal,recoverPending};
  ready=(window.Account?.ready||Promise.resolve({id:'local'})).then(user=>{accountId=user.id;let storage;try{storage=window.localStorage;}catch{/* Browser storage can be unavailable. */}client=window.RhythmClient.create({account:user.id,storage,request:(...args)=>{if(!activeAccount())throw Error('账号已切换，请刷新页面。');return window.fetch(...args);}});});
  ready.then(()=>refresh()).catch(()=>{});
  window.EventBus?.on('plans:changed',()=>refresh());window.EventBus?.on('plans:loaded',()=>refresh());
})();
