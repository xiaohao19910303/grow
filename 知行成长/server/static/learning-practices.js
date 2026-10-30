/* Learning and practice share references; feedback never implies completion. */
(() => {
 'use strict';
 const n=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
 const labels={applied:'已应用',not_applied:'未应用',unknown:'暂不确定'};
 function button(parent,text,action){const b=n('button',text);b.type='button';b.className='btn';parent.append(b);b.onclick=async()=>{b.disabled=true;try{await action();}catch(e){window.toast?.(e.message);}finally{b.disabled=false;}};return b;}
 function field(parent,label,value='',max=2000,type='textarea'){const wrap=n('label',label),input=n(type==='textarea'?'textarea':'input');if(type!=='textarea')input.type=type;input.value=value;input.maxLength=max;input.setAttribute('aria-label',label);wrap.className='action-field';wrap.append(input);parent.append(wrap);return input;}
 async function client(){return window.ActionPlans.practiceClient();}
 function draft(c,flow,id,seed={}){
  const context={flow,origin_key:id,parent_context:null,entry_date:window.ActionPlans.day()};
  return (c.get('draft.index')||[]).map(key=>c.get('draft.'+key)).filter(d=>d?.context.flow===flow&&d.context.origin_key===id).sort((a,b)=>b.updated_at.localeCompare(a.updated_at))[0]||c.newDraft(context,seed);
 }
 async function write(c,d,path,body){
  if(!c.retryStorage().durable)throw Error('输入尚未持久保存，请先下载恢复副本或恢复浏览器存储后重试。');
  const result=await c.writeDurable('draft:'+d.draft_id,path,body);c.deleteDraft(d.draft_id);return result;
 }
 async function finish(box,onSaved,message){
  box.replaceChildren(n('p',message));
  try{await window.ActionPlans.refresh();await onSaved();}
  catch{box.append(n('p','已保存，暂时无法刷新。可重新读取，切勿再次创建。'));button(box,'重新读取已保存实践',onSaved);}
 }
 function form(parent,c,source,onSaved){
  let d=draft(c,'create-day','practice:'+source.id),values=d.values;
  const box=n('section'),status=n('p');parent.append(box);box.append(n('h4','用于一次实践'),n('p','来源：'+source.title),n('p','课程学完、行动完成和实际应用分别记录。留空日期可暂不安排。'));
  const title=field(box,'实践准备做什么',values.title||'',160,'text'),date=field(box,'实践日期（留空暂不安排）',values.date||'',10,'date');
  let retry;const lock=()=>{title.disabled=date.disabled=!!c.pending('draft:'+d.draft_id);if(retry)retry.hidden=!c.pending('draft:'+d.draft_id);};lock();
  const save=()=>{if(c.pending('draft:'+d.draft_id))return;d=c.saveDraft(d,{title:title.value,date:date.value});status.textContent=c.storageStatus().durable?'输入已保存在本机，尚未提交。':'本机存储不可用，请保留页面并下载恢复副本。';};title.oninput=date.oninput=save;
  button(box,'确认创建实践',async()=>{try{if(!title.value.trim())throw Error('请写下一件准备实践的事情。');save();title.disabled=date.disabled=true;await write(c,d,'/practices',{title:title.value,source_kind:source.kind,source_id:source.id,source_version:source.version,date:date.value||null,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone||'Asia/Shanghai'});await finish(box,onSaved,'实践已保存，课程学习状态未改变。');}catch(e){status.textContent=e.message+' 输入已保留。';}finally{lock();}});
  retry=button(box,'重试原实践提交',async()=>{await c.retryPendingDurable('draft:'+d.draft_id,'/practices');c.deleteDraft(d.draft_id);await finish(box,onSaved,'原实践已保存。');});
  lock();box.append(status);
 }
 async function feedback(parent,c,p,onSaved){
  const box=n('section');parent.append(box);let d=draft(c,'edit','practice-feedback:'+p.id,{outcome:'unknown'});box.append(n('h4','记录应用结果'),n('p','保存反馈不会完成行动或课程，也不会自动创建下一步。'));
  const label=n('label','实际应用情况'),outcome=n('select');outcome.setAttribute('aria-label','实际应用情况');for(const [key,value]of Object.entries(labels)){const option=n('option',value);option.value=key;outcome.append(option);}outcome.value=d.values.outcome||'unknown';label.append(outcome);box.append(label);
  const result=field(box,'实际结果',d.values.result||''),evidence=field(box,'作品或反馈依据',d.values.evidence||''),next=field(box,'下一步想法（不会自动建任务）',d.values.next_step||'',1000),status=n('p');
  let retry;const lock=()=>{for(const input of [outcome,result,evidence,next])input.disabled=!!c.pending('draft:'+d.draft_id);if(retry)retry.hidden=!c.pending('draft:'+d.draft_id);};lock();
  const save=()=>{if(c.pending('draft:'+d.draft_id))return;d=c.saveDraft(d,{outcome:outcome.value,result:result.value,evidence:evidence.value,next_step:next.value});};for(const input of [outcome,result,evidence,next])input.oninput=save;
  button(box,'保存应用反馈',async()=>{try{save();for(const input of [outcome,result,evidence,next])input.disabled=true;await write(c,d,'/'+p.id+'/operations',{revision:p.revision,action:'practice-feedback',feedback:d.values});await finish(box,onSaved,'应用反馈已保存，完成事实未改变。');}catch(e){status.textContent=e.message+' 输入已保留，可核对最新版本后继续。';}finally{lock();}});
  button(box,'读取最新行动并保留输入',onSaved);
  retry=button(box,'重试原反馈提交',async()=>{await c.retryPendingDurable('draft:'+d.draft_id,'/'+p.id+'/operations');c.deleteDraft(d.draft_id);await finish(box,onSaved,'原反馈已保存。');});lock();box.append(status);
 }
 async function render(parent,source=null,selected=null){
  const c=await client(),owner=window.Account?.user?.id,data=await c.read('/practices',undefined);if(!window.Account?.isCurrent(owner)||!parent.isConnected)return;
  parent.replaceChildren();const refresh=()=>render(parent,source,selected);if(source)form(parent,c,source,refresh);
  const practices=data.practices.filter(p=>(!source||p.practice_source.kind===source.kind&&p.practice_source.id===source.id)&&(!selected||p.id===selected));
  if(!practices.length)parent.append(n('p','还没有相关实践。可以先选择一次真实应用。'));
  for(const p of practices){const row=n('article');row.dataset.practiceId=p.id;parent.append(row);row.append(n('h4',p.title),n('p',(p.start_date||'暂不安排')+' · '+({active:'待推进',paused:'已暂停',completed:'行动已完成',archived:'已归档'}[p.status]||p.status)));
   button(row,'查看当前来源',async()=>{const value=await c.read('/practices/'+p.id+'/source');if(!window.Account?.isCurrent(owner)||!row.isConnected)return;const text=n('p',value.available?value.title+'\n'+value.text:'来源已变化、撤回或暂不可用；实践与反馈保留。');row.append(text);});
   if(p.status!=='archived')button(row,'记录应用结果',async()=>{await feedback(row,c,p,refresh);});
   for(const f of p.practice_feedback||[]){const item=n('section');item.append(n('strong',labels[f.outcome]||f.outcome),n('p',f.result),n('p',f.evidence?'依据：'+f.evidence:''),n('p',f.next_step?'下次考虑：'+f.next_step:''),n('small',f.created_at));if(data.follow_up_enabled&&p.status!=='archived')button(item,'审阅下一次安排',()=>window.PracticeFollowUp.open(p.id,f.id));row.append(item);}
   button(row,'查看同一行动安排',()=>window.ActionPlans.openRecord(p.id));
  }
 }
 window.LearningPractices={
  mount(parent,descriptor){const details=n('details'),body=n('div');details.className='section';details.append(n('summary','学后用 · 实践与反馈'),body);parent.append(details);let loaded=false;
   details.addEventListener('toggle',async()=>{if(!details.open||loaded)return;loaded=true;const owner=window.Account?.user?.id;body.append(n('p','正在核对来源和行动连接…'));try{const r=await fetch('/api/learning-practices/source?'+new URLSearchParams(descriptor),{cache:'no-store'}),value=await r.json();if(!window.Account?.isCurrent(owner)||!body.isConnected)return;if(!r.ok)throw Error(typeof value.detail==='string'?value.detail:'来源暂不可用。');if(!value.available||!value.source){body.replaceChildren(n('p',value.message));return;}await render(body,value.source);}catch(e){loaded=false;body.replaceChildren(n('p',e.message+' 可收起后重新打开。'));}});
  },
  async open(id=null){const dialog=n('dialog'),body=n('div');dialog.className='action-dialog';dialog.append(n('h3','学习用于实践'),body);button(dialog,'关闭',()=>{dialog.close();dialog.remove();});document.body.append(dialog);dialog.addEventListener('cancel',()=>dialog.remove());dialog.showModal();try{await render(body,null,id);}catch(e){body.append(n('p',e.message));}}
 };
})();
