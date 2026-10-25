/* Read learning progress from formal lessons; never infer completion from action time. */
(() => {
  'use strict';
  const mounts=new Map();
  const node=(tag,text)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;return el;};
  async function api(path,data){
    const response=await fetch(path,{method:data===undefined?'GET':'POST',cache:'no-store',headers:{'Content-Type':'application/json','X-Copilot-Request':'1','X-Grow-Action-Schema':'2'},body:data===undefined?undefined:JSON.stringify({data})});
    const result=await response.json();
    if(!response.ok)throw Error(result.message||result.detail||'课程规划进度暂未读取，请重试。');
    return result;
  }
  function button(parent,label,action){
    const el=node('button',label);el.type='button';el.className='btn';
    el.onclick=async()=>{el.disabled=true;try{await action();}catch(error){parent.querySelector('[role="status"]').textContent=error.message;}finally{el.disabled=false;}};
    parent.append(el);return el;
  }
  function progress(parent,label,row){
    const wrap=node('div');wrap.className='learning-plan-progress';
    wrap.append(node('p',`${label} · 已学完 ${row.completed_lessons}/${row.total_lessons} 课 · 已发布 ${row.published_lessons} 课`));
    const bar=node('progress');bar.max=100;bar.value=row.percent;bar.setAttribute('aria-label',label+'学习进度');wrap.append(bar,node('span',` ${row.percent}%`));parent.append(wrap);
  }
  function card(parent,plan){
    const section=node('article');section.className='section learning-plan-card';section.dataset.learningPlan=plan.id;parent.append(section);
    section.append(node('h3',plan.name));
    const status=node('p','');status.setAttribute('role','status');section.append(status);
    progress(section,'整体',plan);
    for(const stage of plan.stages)progress(section,`阶段 ${stage.number}：${stage.title}`,stage);
    section.append(node('p','进度仅计入本人确认学完的正式课程；未发布课程也计入规划总课数。'));
    section.append(node('p','关联行动默认不指定日期。请在行动中安排今日并开始，学完后用课程里的“本人确认学完”回写；无日期行动不会自动补造执行记录。'));
    if(!plan.action_management_available){section.append(node('p','当前行动由其他端接管，或存储尚不支持关联；此处仅展示学习进度。'));}
    else {
      if(plan.status!=='active')section.append(node('p','规划已暂停或归档，暂不补入新行动；已有行动保留。'));
      const sync=async enabled=>{await api('/api/plans/'+encodeURIComponent(plan.id)+'/actions',{key:crypto.randomUUID(),expected_version:plan.version,enabled});await window.ActionPlans?.refresh();await refresh();};
      if(plan.status==='active')button(section,!plan.linked?'关联到行动':plan.enabled?'同步已发布课程到行动':'恢复自动补入',()=>sync(true));
      if(plan.linked&&plan.enabled)button(section,'停止自动补入',()=>sync(false));
      if(plan.linked&&!plan.enabled)section.append(node('p','已停止自动补入，已有行动保留。'));
      if(plan.missing_action_count)section.append(node('p',`有 ${plan.missing_action_count} 课尚未关联行动，可同步补入。`));
    }
    button(section,'查看课程规划',()=>window.openLearningPlan?.(plan.id));
    for(const lesson of plan.lessons){
      const row=node('div');row.className='learning-plan-lesson';section.append(row);
      const learned=lesson.published&&lesson.learning_state==='completed';
      const actionLabel={active:'待推进',paused:'已暂停',completed:'已完成',archived:'已归档'}[lesson.action_status];
      row.append(node('span',`第 ${lesson.number} 课 ${lesson.title} · ${learned?'已学完':lesson.published?'待本人反馈':'尚未发布'}${actionLabel?' · 行动'+actionLabel:''}${lesson.action_changed?' · 关联行动已变化，请核对':''}`));
      if(lesson.action_id&&plan.action_management_available)button(section,`查看第 ${lesson.number} 课行动`,()=>window.ActionPlans.openRecord(lesson.action_id));
    }
  }
  async function read(el,state){
    const turn=++state.turn;let account;
    try{
      await window.Account?.ready;account=window.Account?.user?.id;
      const result=await api(state.pid?'/api/plans/'+encodeURIComponent(state.pid)+'/actions':'/api/plan-actions');
      if(!el.isConnected||turn!==state.turn||account!==window.Account?.user?.id)return;
      el.replaceChildren(node('h2','课程规划进度'));
      const plans=state.pid?[result]:result.plans;
      if(!plans.length)el.append(node('p','尚未关联课程规划，可在课程规划详情中关联到行动。'));
      for(const plan of plans)card(el,plan);
    }catch(error){
      if(!el.isConnected||turn!==state.turn||account!==window.Account?.user?.id)return;
      el.replaceChildren(node('h2','课程规划进度'));
      const status=node('p',error.message);status.setAttribute('role','status');el.append(status);button(el,'重试读取课程进度',()=>read(el,state));
    }
  }
  function mount(parent,pid){
    for(const [el] of mounts)if(!el.isConnected)mounts.delete(el);
    const el=node('section');el.className='learning-plan-actions';el.append(node('p','正在读取课程规划进度…'));parent.append(el);
    const state={pid,turn:0};mounts.set(el,state);read(el,state);return el;
  }
  async function refresh(){
    const pending=[];
    for(const [el,state] of mounts){if(!el.isConnected)mounts.delete(el);else pending.push(read(el,state));}
    await Promise.all(pending);
  }
  window.PlanActions={mount,refresh};
  for(const event of ['plans:loaded','plans:changed'])window.EventBus?.on(event,()=>refresh());
})();
