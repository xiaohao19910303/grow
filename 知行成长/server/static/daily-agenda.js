/* One date arrangement references one existing article/course/action. */
(() => {
  'use strict';
  const mounts=new Set();
  let scope='today',page=1,lastDay=null;
  const node=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;};
  const day=()=>window.ActionPlans?.day()||ActionPlanClient.day(new Date());
  function shift(date,amount){const value=new Date(date+'T12:00:00Z');value.setUTCDate(value.getUTCDate()+amount);return value.toISOString().slice(0,10);}
  function same(a,b){return a.kind===b.kind&&(a.course||'')===(b.course||'')&&(a.plan_id||'')===(b.plan_id||'')&&(a.lesson_no||1)===(b.lesson_no||1);}
  function button(parent,text,run,primary=false){const b=node('button',text,'btn'+(primary?' primary':''));b.type='button';b.onclick=async()=>{b.disabled=true;try{await run();}catch(error){toast(error.message);}finally{b.disabled=false;}};parent.append(b);return b;}
  const data=()=>window.ActionPlans?.snapshot()||{plans:[],execution:null};
  function matching(target){return data().plans.filter(p=>p.period==='day'&&p.completion_mode==='content'&&p.status!=='archived'&&same(p.target,target));}
  function dateDialog(title,initial,run){
    const d=node('dialog',undefined,'action-dialog'),form=node('form'),heading=node('h2',title),label=node('label','安排日期','action-field');
    const input=node('input');input.type='date';input.required=true;input.value=initial;label.append(input);
    const error=node('p','','action-error');error.setAttribute('role','alert');
    const controls=node('div',undefined,'action-buttons'),save=node('button','保存安排','btn primary');save.type='submit';controls.append(save);button(controls,'取消',()=>d.close());
    form.append(label,error,controls);d.append(heading,form);document.body.append(d);const origin=document.activeElement;
    d.addEventListener('close',()=>{d.remove();if(origin?.isConnected)origin.focus();},{once:true});d.showModal();input.focus();
    form.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{await run(input.value);d.close();}catch(e){error.textContent=e.message;}finally{save.disabled=false;}};
  }
  async function arrange(target,title,date,minutes){
    const result=await ActionPlans.schedule({target,title:title.slice(0,160),date,target_minutes:minutes||20});
    toast(result.existing?(result.plan.status==='completed'?'该日期的安排已完成。':'该日期已有安排，可改期或取消。'):'已安排 '+date+'，可在今日的日期视图或明日预览查看。');
    refreshControls();
  }
  function drawControls(entry){
    const {parent,target,title,minutes}=entry;parent.replaceChildren();parent.className='agenda-content-controls';
    const controls=node('div',undefined,'action-buttons');parent.append(controls);
    const current=matching(target).sort((a,b)=>a.start_date.localeCompare(b.start_date));
    const today=current.find(p=>p.start_date===day()),tomorrow=current.find(p=>p.start_date===shift(day(),1));
    if(today)controls.append(node('span','已在今日安排','desc'));
    else button(controls,'安排到今日',()=>arrange(target,title,day(),minutes));
    if(tomorrow)controls.append(node('span','已在明日安排','desc'));
    else button(controls,'安排到明日',()=>arrange(target,title,shift(day(),1),minutes));
    button(controls,'选择日期',()=>dateDialog('安排学习日期',shift(day(),1),date=>arrange(target,title,date,minutes)));
    for(const p of current.filter(p=>p.status!=='completed').slice(0,4)){
      const row=node('div',undefined,'agenda-scheduled');row.append(node('span','已安排 '+p.start_date+(p.status==='paused'?' · 已暂停':''),'desc'));
      button(row,'改期',()=>reschedule(p));button(row,'取消安排',()=>cancel(p));parent.append(row);
    }
  }
  function mount(parent,target,title,minutes=20){const entry={parent,target,title,minutes};mounts.add(entry);drawControls(entry);}
  function refreshControls(){for(const entry of mounts){if(!entry.parent.isConnected)mounts.delete(entry);else drawControls(entry);}}
  function reschedule(p){dateDialog('改期 · '+p.title,p.start_date,date=>ActionPlans.change(p,'reschedule',{date}));}
  async function cancel(p){await ActionPlans.change(p,'cancel');toast('已取消日期安排，原内容和笔记仍保留。');}
  function row(parent,p){
    const running=data().execution?.plan_id===p.id,mode=p.completion_mode||'time',done=p.status==='completed';
    const box=node('article',undefined,'agenda-row'+(done?' agenda-done':''));box.dataset.planId=p.id;
    const content=node('div',undefined,'agenda-row-content');box.append(content);
    const type=mode==='check'?'待办':p.target.kind==='article'?'阅读':mode==='content'?'课程':'计时行动';
    content.append(node('p',type+' · '+p.start_date+(mode==='time'?' '+p.at:'')+' · '+(done?'已完成':p.blocked?'上级已暂停':p.status==='paused'?'已暂停':running?'正在进行':'待执行'),'action-kicker'),node('h3',p.title));
    if(mode!=='check')content.append(node('p',(mode==='content'?'预计 ':'目标 ')+p.target_minutes+' 分钟'+(mode==='content'?' · 在原内容中确认读完／学完':''),'desc'));
    const actions=node('div',undefined,'action-buttons');box.append(actions);
    const future=p.start_date>ActionPlans.day(p.timezone);
    if(mode==='check'){
      const label=node('label',done?'已完成':'完成待办','agenda-check'),check=node('input');check.type='checkbox';check.checked=done;check.disabled=future||p.status==='paused'||p.blocked;label.prepend(check);actions.append(label);
      check.onchange=async()=>{check.disabled=true;try{await ActionPlans.change(p,done?'reopen':'complete');}catch(e){check.checked=done;check.disabled=false;toast(e.message);}};
    }else if(done){button(actions,type==='阅读'?'再次阅读':'查看内容',()=>ActionPlans.openTarget(p.target));}
    else if(p.status==='active'&&!p.blocked){
      if(running)button(actions,'继续'+(type==='阅读'?'阅读':'执行'),()=>ActionPlans.openTarget(p.target),true);
      else if(!future)button(actions,type==='阅读'?'开始阅读':mode==='content'?'开始学习':'开始行动',()=>ActionPlans.start(p,'standard'),true);
      else button(actions,'查看内容',()=>ActionPlans.openTarget(p.target));
      if(mode==='content'&&!future)button(actions,'核对完成',()=>ActionPlans.reconcile(p));
    }
    if(!done&&p.status!=='archived'){
      button(actions,'改期',()=>reschedule(p));button(actions,'取消安排',()=>cancel(p));
      if(p.status==='paused')button(actions,'恢复安排',()=>ActionPlans.change(p,'resume'));
    }
    parent.append(box);
  }
  function forDate(parent,date){
    if(!parent)return;parent.replaceChildren();
    const plans=data().plans.filter(p=>p.period==='day'&&p.start_date===date&&p.status!=='archived');
    plans.sort((a,b)=>(a.status==='completed')-(b.status==='completed')||(a.id===data().execution?.plan_id?-1:b.id===data().execution?.plan_id?1:0)||a.at.localeCompare(b.at));
    if(!plans.length)parent.append(node('p','这个日期还没有内容或行动安排，可从学习加入，或在下方添加待办。','action-empty'));
    for(const p of plans)row(parent,p);
  }
  function render(){
    const dateInput=document.getElementById('personalDate'),current=day();
    if(lastDay&&current!==lastDay&&dateInput?.value===lastDay){dateInput.value=current;lastDay=current;window.renderPersonal?.();return;}
    lastDay=current;
    const selected=document.getElementById('personalDate')?.value||day();
    forDate(document.getElementById('agendaList'),selected);
    forDate(document.getElementById('agendaTomorrowList'),shift(selected,1));
    const pending=document.getElementById('agendaPending');if(pending){pending.replaceChildren();const count=data().plans.filter(p=>p.period==='day'&&p.status==='active'&&p.start_date<ActionPlans.day(p.timezone)).length;
      if(count)button(pending,count+' 项过去的安排待调整',()=>{scope='earlier';page=1;goTab('action-schedule');});}
    window.updateDaySummary?.();refreshControls();window.renderOptionalLearning?.();
    if(document.getElementById('view-action-schedule')?.style.display!=='none')renderSchedule();
    renderGrowth();
  }
  function renderSchedule(){
    const root=document.getElementById('view-action-schedule');if(!root)return;root.replaceChildren(node('h2','日程安排'),node('p','安排今天和未来，过去未完成的事项可改期或取消。','desc'));

    // Show pending adjustment count at the top
    const pendingCount=data().plans.filter(p=>p.period==='day'&&p.status==='active'&&p.start_date<ActionPlans.day(p.timezone)).length;
    if(pendingCount>0&&scope!=='earlier'){
      const pendingBox=node('div',undefined,'action-pending');
      pendingBox.append(node('p',`有 ${pendingCount} 项过去的安排待调整`,'action-kicker'));
      button(pendingBox,'查看待调整',()=>{scope='earlier';page=1;renderSchedule();},true);
      root.append(pendingBox);
    }

    const tabs=node('div',undefined,'action-buttons');root.append(tabs);
    for(const [key,text] of [['today','今日'],['tomorrow','明日'],['future','未来'],['earlier','待调整'],['all','全部日程']]){const b=button(tabs,text,()=>{scope=key;page=1;renderSchedule();},scope===key);b.setAttribute('aria-pressed',String(scope===key));}
    button(tabs,'新建日行动',()=>ActionPlans.newDay());button(tabs,'刷新',()=>ActionPlans.refresh());
    const inScope=(date,done)=>scope==='all'||scope==='today'&&date===day()||scope==='tomorrow'&&date===shift(day(),1)||scope==='future'&&date>shift(day(),1)||scope==='earlier'&&date<day()&&!done;
    const list=data().plans.filter(p=>p.period==='day'&&p.status!=='archived'&&inScope(p.start_date,p.status==='completed'));
    const legacy=(window.legacyAgendaTasks?.()||[]).filter(item=>inScope(item.date,item.done));
    const combined=[...list.map(plan=>({date:plan.start_date,plan})),...legacy.map(task=>({date:task.date,task}))].sort((a,b)=>a.date.localeCompare(b.date));
    if(!combined.length)root.append(node('p','这个范围里还没有安排。','action-empty'));
    for(const item of combined.slice((page-1)*20,page*20)){
      if(item.plan){row(root,item.plan);continue;}
      const task=item.task,box=node('article',undefined,'agenda-row'),text=node('div');
      text.append(node('p','待办 · '+task.date+' · '+(task.done?'已完成':'待执行'),'action-kicker'),node('h3',task.title));box.append(text);
      const actions=node('div',undefined,'action-buttons'),check=node('input'),label=node('label',task.done?'已完成':'完成待办','agenda-check');check.type='checkbox';check.checked=task.done;check.disabled=task.date>day();check.onchange=()=>window.toggleTodo(task.index);label.prepend(check);actions.append(label);button(actions,'改期／编辑',()=>window.editTodo(task.index));box.append(actions);root.append(box);
    }
    const pages=node('div',undefined,'action-buttons');root.append(pages);
    const previous=button(pages,'上一页',()=>{page--;renderSchedule();});previous.disabled=page===1;
    pages.append(node('span',`共 ${combined.length} 项 · 第 ${page} 页`));const next=button(pages,'下一页',()=>{page++;renderSchedule();});next.disabled=page*20>=combined.length;
  }
  function renderGrowth(){
    const root=document.getElementById('actionGrowth');if(!root)return;
    // Only leaf-day facts are summed; parent aggregates would count them twice.
    const days=data().plans.filter(p=>p.period==='day'),done=days.filter(p=>p.status==='completed');
    const minutes=days.reduce((sum,p)=>sum+(p.progress?.minutes||0),0);
    root.replaceChildren(node('h2','行动积累'),node('p',`已完成 ${done.length} 项安排 · 其中内容学习 ${done.filter(p=>p.completion_mode==='content').length} 项 · 本人确认投入 ${minutes} 分钟`),node('p','安排完成数与文章／课程完成数分别统计。未确认的计时不计入投入。','desc'));
    button(root,'查看执行记录',()=>goTab('action-records'));
  }
  window.DailyAgenda={mount,render,row,reschedule,cancel,refreshControls,renderGrowth,shift,same,
    isScheduled:target=>matching(target).some(p=>!!p.start_date),
    enter:async()=>{try{await ActionPlans.refresh();renderSchedule();}catch(e){const root=document.getElementById('view-action-schedule');root.replaceChildren(node('p',e.message));button(root,'重试',()=>DailyAgenda.enter());}}};

  // Listen for plan changes to refresh agenda
  window.EventBus?.on('plans:changed',()=>{
    if(document.getElementById('view-personal')?.style.display!=='none'){
      render();
    }
  });

  window.EventBus?.on('plans:loaded',()=>{
    if(document.getElementById('view-personal')?.style.display!=='none'){
      render();
    }
  });
})();
