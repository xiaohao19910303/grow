/* A selected feedback is a basis for review, never an automatic new commitment. */
(() => {
 const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
 function input(parent,label,value,type='text'){const wrap=el('label',label),field=el('input');field.type=type;field.value=value;field.maxLength=type==='date'?10:160;field.setAttribute('aria-label',label);wrap.className='action-field';wrap.append(field);parent.append(wrap);return field;}
 async function open(id,feedbackId){
  if(!/^action-[a-zA-Z0-9-]+$/.test(id)||!/^feedback-[a-zA-Z0-9-]+$/.test(feedbackId))throw Error('后续安排来源无效。');
  const owner=(await Account.ready).id,c=await ActionPlans.practiceClient(),path='/practices/'+id+'/follow-up';
  if(!Account.isCurrent(owner))return;
  const dialog=el('dialog'),body=el('div'),close=el('button','关闭');dialog.className='action-dialog';close.className='btn';close.onclick=()=>{dialog.close();dialog.remove();};dialog.append(el('h3','审阅下一次实践'),close,body);document.body.append(dialog);dialog.showModal();dialog.addEventListener('cancel',()=>dialog.remove());
  const current=()=>dialog.isConnected&&Account.isCurrent(owner);
  const originKey='practice-followup:'+id+':'+feedbackId;
  function draft(seed){return (c.get('draft.index')||[]).map(key=>c.get('draft.'+key)).filter(d=>d?.context.flow==='create-day'&&d.context.origin_key===originKey).sort((a,b)=>b.updated_at.localeCompare(a.updated_at))[0]||c.newDraft({flow:'create-day',origin_key:originKey,parent_context:null,entry_date:ActionPlans.day()},seed);}
  async function saved(d,result){c.deleteDraft(d.draft_id);if(!current())return;body.replaceChildren(el('p','后续实践已保存，原反馈与完成状态保持不变。'));try{await ActionPlans.refresh();}catch{body.append(el('p','已保存，暂时无法刷新。请重新读取，勿重复创建。'));}if(result?.plan){const view=el('button','查看后续实践');view.className='btn';view.onclick=()=>{close.click();LearningPractices.open(result.plan.id);};body.append(view);}}
  async function load(){
   if(!current())return;
   body.replaceChildren(el('p','正在核对反馈、来源和当前计划…'));
   const existing=(c.get('draft.index')||[]).map(key=>c.get('draft.'+key)).find(d=>d?.context.flow==='create-day'&&d.context.origin_key===originKey);
   if(existing&&c.pending('draft:'+existing.draft_id)){
    body.replaceChildren(el('p','原提交结果待核对。来源变化不影响已提交请求的回执，请先重试原提交。'));
    const title=input(body,'下次准备实践什么',existing.values.title||''),date=input(body,'后续实践日期（留空暂不安排）',existing.values.date||'','date');title.disabled=date.disabled=true;
    const retry=el('button','重试原后续提交'),refresh=el('button','读取最新来源并保留输入'),status=el('p');status.setAttribute('role','status');retry.className=refresh.className='btn';
    retry.onclick=async()=>{retry.disabled=true;try{const result=await c.retryPendingDurable('draft:'+existing.draft_id,path);await saved(existing,result);}catch(error){status.textContent=error.message+' 输入已保留；确认未保存后可读取最新来源。';}finally{retry.disabled=false;}};
    refresh.onclick=()=>load();body.append(retry,refresh,status);return;
   }
   let ctx;try{ctx=await c.read(path+'?feedback_id='+encodeURIComponent(feedbackId));}catch(error){if(current()){body.replaceChildren(el('p',error.message));const login=el('a','使用已关联的LightTick账号登录');login.href='/login#mobile/practice/'+id+'/'+feedbackId;body.append(login);}return;}
   if(!current())return;body.replaceChildren(el('p','依据：'+(ctx.feedback.result||ctx.feedback.evidence||'这次应用反馈')),el('p','课程学完、原实践完成和这次新安排分别保存。保存前请核对内容、日期和当前上级计划。'));
   if(!ctx.available){body.append(el('p','来源已变化、撤回或暂不可用。反馈与原有草稿保留，联网核对来源后可重试。'));return;}
   let d=draft({title:ctx.feedback.next_step||'',date:'',parent:''});const key='draft:'+d.draft_id;
   const title=input(body,'下次准备实践什么',d.values.title||''),date=input(body,'后续实践日期（留空暂不安排）',d.values.date||'','date');
   const parent=el('select'),label=el('label','关联当前计划（可选）');parent.setAttribute('aria-label','后续实践上级计划');const none=el('option','独立行动');none.value='';parent.append(none);
   for(const p of ctx.parents){const o=el('option',p.title+' · '+p.start_date+' 至 '+p.end_date);o.value=p.id;parent.append(o);}parent.value=d.values.parent||'';label.append(parent);body.append(label);
   const description=el('p'),status=el('p'),save=el('button','确认后续安排'),retry=el('button','重试原后续提交'),refresh=el('button','读取最新来源并保留输入');status.setAttribute('role','status');for(const b of [save,retry,refresh])b.className='btn';
   function persist(){if(c.pending(key))return;d=c.saveDraft(d,{title:title.value,date:date.value,parent:parent.value});}
   function lock(){const pending=!!c.pending(key);for(const f of [title,date,parent])f.disabled=pending;retry.hidden=!pending;save.disabled=pending;}
   function describe(){const p=ctx.parents.find(p=>p.id===parent.value);description.textContent=p?'使用该计划当前日期、时区与约束；其目标'+(p.target_minutes==null?'未设置':p.target_minutes+'分钟')+'保持原值。整体预算或阶段重排请在原计划中审阅。':'不创建新的上级周期，也不复制旧预算。未安排日期的实践不会进入今日承诺。';}
   title.oninput=date.oninput=persist;parent.onchange=()=>{persist();describe();};describe();
   save.onclick=async()=>{if(save.disabled)return;save.disabled=true;try{
    if(!title.value.trim())throw Error('请确认下一次实际准备做什么。');persist();if(!c.retryStorage().durable)throw Error('草稿尚未可靠保存在本机，请保留输入后重试。');for(const f of [title,date,parent])f.disabled=true;
    const p=ctx.parents.find(p=>p.id===parent.value);const result=await c.writeDurable(key,path,{revision:ctx.revision,feedback_id:feedbackId,source_version:ctx.source_version,title:title.value,date:date.value||null,timezone:p?.timezone||Intl.DateTimeFormat().resolvedOptions().timeZone||'Asia/Shanghai',parent_id:p?.id||null,parent_revision:p?.revision||null});await saved(d,result);
   }catch(error){status.textContent=error.message+' 输入已保留。';}finally{lock();}};
   retry.onclick=async()=>{retry.disabled=true;try{const result=await c.retryPendingDurable(key,path);await saved(d,result);}catch(error){status.textContent=error.message;}finally{retry.disabled=false;lock();}};
   refresh.onclick=()=>load();body.append(description,save,retry,refresh,status);lock();
  }
  await load();
 }
 window.PracticeFollowUp={open};
 function route(){const m=location.hash.match(/^#mobile\/practice\/(action-[a-zA-Z0-9-]+)\/(feedback-[a-zA-Z0-9-]+)$/);if(m)open(m[1],m[2]).catch(e=>window.toast?.(e.message));}
 window.addEventListener('hashchange',route);window.addEventListener('load',route);
})();
