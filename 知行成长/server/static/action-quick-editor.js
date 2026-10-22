/* P0 day actions: conditional fields and account/context-scoped durable drafts. */
(() => {
  'use strict';
  const node=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
  window.ActionQuickEditor={open({openFull,client,snapshot,dialog,field,button,option,day,refresh,change,existing=null,parent=null,date=day(),target=null,draftId=null,fresh=false,seedValues=null}){
    if(snapshot.action_schema_version!==2){toast('行动服务尚未支持P0，请等待升级。');return;}
    const origin=document.activeElement;
    const restoreFocus=()=>{const target=origin?.isConnected?origin:[...document.querySelectorAll('button')].find(b=>b.textContent===origin?.textContent&&b.getClientRects().length);target?.focus();};
    const context={flow:existing?'edit':'create-day',origin_key:existing?.id||(target?JSON.stringify(target):'general'),parent_context:parent?.id||null,entry_date:date};
    const candidates=client.listDrafts(context);
    if(!draftId&&!fresh&&candidates.length>1){
      const choose=dialog('选择未提交的行动');
      for(const draft of candidates)button(choose,(draft.values.title||'未命名行动')+' · '+(draft.values.start_date||'未安排')+' · '+new Date(draft.updated_at).toLocaleString(),()=>{
        choose.close();ActionQuickEditor.open({openFull,client,snapshot,dialog,field,button,option,day,refresh,change,existing,parent,date,target,draftId:draft.draft_id});
      });
      button(choose,'新建另一份',()=>{choose.close();ActionQuickEditor.open({openFull,client,snapshot,dialog,field,button,option,day,refresh,change,existing,parent,date,target,fresh:true});});return;
    }
    const base={title:'',period:'day',start_date:date,end_date:date,completion_mode:target?'content':'check',target,
      timezone:parent?.timezone||window.Account?.user?.timezone||'Asia/Shanghai',parent_id:parent?.id||null,target_count:1,
      target_minutes:20,minimum_minutes:5,at:null,reminder:false,reason:'',if_then:'',horizon:'short',...seedValues,...existing};
    let draft=(!fresh&&(draftId?candidates.find(d=>d.draft_id===draftId):candidates[0]))||client.newDraft(context,base);
    const seed={...base,...draft.values},d=dialog(existing?'编辑行动':'新建行动'),form=node('form');d.append(form);
    window.ActionRecovery?.attach(client,form);
    if(candidates.length)form.append(node('p','已恢复未提交的填写。'));
    const name=field(form,'做什么','text',seed.title);name.required=true;name.maxLength=160;
    const dateInput=field(form,'行动日期（可暂不安排）','date',seed.start_date||'');
    const mode=field(form,'怎样算完成','select');for(const [key,text] of [['check','直接勾选'],['time','投入一段时间'],['content','读完文章或学完课程']])option(mode,key,text);mode.value=seed.completion_mode;
    const minutes=field(form,'标准分钟','number',seed.target_minutes||20);minutes.min=1;minutes.max=1440;minutes.step=1;
    const targetBox=node('section');form.append(targetBox);
    let targets=[null,{kind:'library'},{kind:'book'}];if(seed.target&&!['library','book'].includes(seed.target.kind))targets.push(seed.target);
    const content=field(targetBox,'对应内容','select');
    function fillTargets(){content.replaceChildren();targets.forEach((t,i)=>option(content,String(i),!t?'不关联内容':t.kind==='library'?'进入课程库选择':t.kind==='book'?'纸质书或其他行动':t.display||'已关联的文章/课程'));}
    fillTargets();content.value=String(Math.max(0,targets.findIndex(t=>JSON.stringify(t)===JSON.stringify(seed.target))));
    const message=node('p');message.className='action-error';message.id='action-errors-'+draft.draft_id;message.setAttribute('role','alert');
    button(targetBox,'选择已有文章或课程',async()=>{
      message.textContent='正在读取内容…';const result=await Promise.allSettled([fetch('/api/reading/library?page_size=50').then(r=>r.json()),fetch('/api/plans').then(r=>r.json())]);
      const selected=targets[Number(content.value)];
      if(result[0].status==='fulfilled')for(const a of result[0].value.articles||[])targets.push({kind:'article',course:a.id,display:a.zh_title||a.title});
      if(result[1].status==='fulfilled')for(const p of result[1].value.plans||[])for(const l of p.lessons||[])targets.push({kind:'plan',plan_id:p.id,lesson_no:l.lesson_no,display:p.name+' · '+l.topic});
      fillTargets();content.value=String(Math.max(0,targets.indexOf(selected)));message.textContent=result.some(r=>r.status==='rejected')?'部分内容未读到，可重试。':'';content.focus();
    });
    const more=node('details');more.append(node('summary','更多设置'));form.append(more);
    if(!existing&&openFull)button(more,'使用模板或重复安排',()=>{remember();d.close();openFull();});
    const at=field(more,'具体时间（可选）','time',seed.at||''),reminder=field(more,'到时提醒（网页打开时）','checkbox',seed.reminder);
    const timezone=field(more,'计划时区','text',seed.timezone);timezone.required=true;
    const minimum=field(more,'起步分钟（留空关闭）','number',seed.minimum_minutes??'');minimum.min=1;minimum.max=1440;
    const estimate=field(more,'预计分钟（可选，不决定完成）','number',seed.estimated_minutes??'');estimate.min=1;estimate.max=1440;
    const parentInput=field(more,'关联上级（可选）','select');option(parentInput,'','独立行动');
    for(const p of snapshot.plans.filter(p=>p.period!=='day'&&p.status==='active'))option(parentInput,p.id,p.title);parentInput.value=seed.parent_id||'';
    const reason=field(more,'为什么想做（可选）','textarea',seed.reason),intention=field(more,'分心时的约定（可选）','textarea',seed.if_then);reason.maxLength=intention.maxLength=1000;
    form.append(message);const controls=node('div');controls.className='action-buttons';form.append(controls);
    const submit=node('button');submit.type='submit';submit.className='btn primary';controls.append(submit);
    if(existing)dateInput.disabled=true;
    const locked=existing&&((existing.progress?.minutes||0)+(existing.progress?.completed||0)+(existing.progress?.minimum||0)+(existing.progress?.partial||0)+(existing.progress?.interrupted||0)>0);
    if(locked){mode.disabled=minutes.disabled=minimum.disabled=content.disabled=true;}
    function conditional(){
      const timed=mode.value==='time';minutes.parentElement.hidden=minimum.parentElement.hidden=!timed;minutes.required=timed;
      targetBox.hidden=mode.value==='check';estimate.parentElement.hidden=mode.value!=='content';
      content.setCustomValidity(mode.value==='content'&&!['article','plan'].includes(targets[Number(content.value)]?.kind)?'请选择具体文章或课程。':'');
      submit.textContent=existing?'保存修改':!dateInput.value?'保存行动':dateInput.value===day()?'加入今日':dateInput.value===DailyAgenda.shift(day(),1)?'加入明日':'保存安排';
    }
    function values(){
      const selected=targets[Number(content.value)],clean=selected?Object.fromEntries(Object.entries(selected).filter(([key])=>key!=='display')):null;
      return {period:'day',title:name.value,start_date:dateInput.value||null,end_date:dateInput.value||null,completion_mode:mode.value,
        target:mode.value==='check'?null:clean,target_minutes:mode.value==='time'?Number(minutes.value):null,
        minimum_minutes:mode.value==='time'&&minimum.value?Number(minimum.value):null,estimated_minutes:mode.value==='content'&&estimate.value?Number(estimate.value):null,
        timezone:timezone.value,parent_id:parentInput.value||null,horizon:seed.horizon||'short',target_count:1,
        at:at.value||null,reminder:reminder.checked,reason:reason.value,if_then:intention.value};
    }
    function remember(){draft=client.saveDraft(draft,values());}
    function update(){conditional();remember();}
    form.addEventListener('input',update);form.addEventListener('change',update);
    minutes.addEventListener('input',()=>{if(minimum.value&&Number(minimum.value)>Number(minutes.value))minimum.value=String(Math.max(1,Math.min(5,Number(minutes.value)||1)));minimum.max=minutes.value||1440;remember();});
    mode.addEventListener('change',()=>{if(mode.value==='check')content.value='0';conditional();remember();});
    dateInput.addEventListener('change',()=>{if(!dateInput.value){at.value='';reminder.checked=false;}update();});
    if(!existing)button(controls,'暂不安排',()=>{dateInput.value='';at.value='';reminder.checked=false;update();});
    button(controls,'稍后继续',()=>{remember();d.close();});
    const recoveryIds=new Set();
    function renderRecovery(){for(const pendingDraft of client.pendingDrafts(context)){
      const pendingId=pendingDraft.draft_id;if(recoveryIds.has(pendingId))continue;recoveryIds.add(pendingId);
      button(controls,'核对上次提交',async()=>{const result=await client.resolvePending('draft:'+pendingId);if(result.found){client.deleteDraft(pendingId);d.close();await refresh();toast('上次提交已保存；后续输入仍在独立草稿中，可核对后编辑。');}else message.textContent='结果仍未确认，请重试原提交；当前输入保留。';});
      button(controls,'重试原提交',async()=>{await client.retryPending('draft:'+pendingId,existing?'/'+existing.id+'/operations':'');client.deleteDraft(pendingId);d.close();await refresh();});
    }}
    renderRecovery();
    form.onsubmit=async event=>{event.preventDefault();submit.disabled=true;remember();message.textContent='正在保存…';
      try{
        if(client.pendingDrafts(context).some(p=>p.draft_id!==draft.draft_id))throw Error('上次提交尚未确认，请先核对或重试原提交；当前输入已另存草稿。');
        const payload=existing?{revision:draft.base_revision||existing.revision,action:'edit',fields:values()}:values();
        const result=await client.write('draft:'+draft.draft_id,existing?'/'+existing.id+'/operations':'',payload);
        if(!existing)snapshot.plans.push(...result.plans.map(p=>({...p,progress:{minutes:0,completed:0,minimum:0,partial:0,interrupted:0}})));
        else snapshot.plans=snapshot.plans.map(p=>p.id===existing.id?{...p,...result.plan}:p);
        client.deleteDraft(draft.draft_id);d.close();toast('行动已保存。');
        try{await refresh();}catch{DailyAgenda.render();toast('已保存，列表暂未刷新，请稍后重试。');}restoreFocus();
      }catch(error){message.textContent=error.message;renderRecovery();if(error.existing_plan_id)button(controls,'查看已有安排',()=>{d.close();goTab('action-schedule');});}
      finally{submit.disabled=false;}
    };
    for(const input of form.querySelectorAll('input,select,textarea'))input.setAttribute('aria-describedby',message.id);
    d.addEventListener('cancel',remember);conditional();name.focus();
  }};
})();
