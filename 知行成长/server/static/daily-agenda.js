/* One date arrangement references one existing article/course/action. */
(() => {
  'use strict';
  const mounts=new Set();
  let scope='today',page=1,lastDay=null;
  const batchSelected=new Set();let batchFailures=[];
  const node=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;};
  const day=()=>window.ActionPlans?.day()||ActionPlanClient.day(new Date());
  function shift(date,amount){const value=new Date(date+'T12:00:00Z');value.setUTCDate(value.getUTCDate()+amount);return value.toISOString().slice(0,10);}
  function same(a,b){return !!a&&!!b&&a.kind===b.kind&&(a.course||'')===(b.course||'')&&(a.plan_id||'')===(b.plan_id||'')&&(a.lesson_no||1)===(b.lesson_no||1);}
  function button(parent,text,run,primary=false){const b=node('button',text,'btn'+(primary?' primary':''));b.type='button';b.onclick=async()=>{b.disabled=true;try{await run();}catch(error){toast(error.message);}finally{b.disabled=false;}};parent.append(b);return b;}
  const data=()=>window.ActionPlans?.snapshot()||{plans:[],execution:null};
  // 课程安排包含内容确认和计时两种方式；英文等课程的计时回退也必须参与日期去重。
  function matching(target){return data().plans.filter(p=>p.period==='day'&&(p.completion_mode==='content'||p.completion_mode==='time'&&['plan','renzhi','yingyu','biaoda'].includes(target.kind))&&p.status!=='archived'&&same(p.target,target));}
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
    await ActionPlans.refresh();
    const current=matching(target),existing=current.find(p=>p.start_date===date);
    if(existing){toast(existing.status==='completed'?'该日期的安排已完成。':'该日期已有安排，可改期或取消。');refreshControls();return;}
    // 复用规划已关联的未定日期行动，保留关联关系，不为同一课另建一条。
    const undated=target.kind==='article'?[]:current.filter(p=>!p.start_date&&['active','paused'].includes(p.status));
    if(undated.length===1){await ActionPlans.change(undated[0],'reschedule',{date});toast('已安排 '+date+'，原行动和记录保留。');refreshControls();return;}
    if(!data().capabilities?.content_receipts?.includes(target.kind))return ActionPlans.newDay({date,target,seedValues:{title,completion_mode:'time',target,target_minutes:minutes||20}});
    const result=await ActionPlans.schedule({target,title:title.slice(0,160),date,target_minutes:minutes||20});
    toast(result.existing?(result.plan.status==='completed'?'该日期的安排已完成。':'该日期已有安排，可改期或取消。'):'已安排 '+date+'，可在今日的日期视图或明日预览查看。');
    refreshControls();
  }
  function drawControls(entry){
    const {parent,target,title,minutes}=entry;parent.replaceChildren();parent.className='agenda-content-controls';
    if(entry.compact){drawCourseControls(entry);return;}
    const controls=node('div',undefined,'action-buttons');parent.append(controls);
    const current=matching(target).sort((a,b)=>(a.start_date||'').localeCompare(b.start_date||''));
    const today=current.find(p=>p.start_date===day()),tomorrow=current.find(p=>p.start_date===shift(day(),1));
    if(today)controls.append(node('span','已在今日安排','desc'));
    else button(controls,'安排到今日',()=>arrange(target,title,day(),minutes));
    if(tomorrow)controls.append(node('span','已在明日安排','desc'));
    else button(controls,'安排到明日',()=>arrange(target,title,shift(day(),1),minutes));
    button(controls,'选择日期',()=>dateDialog('安排学习日期',shift(day(),1),date=>arrange(target,title,date,minutes)));
    for(const p of current.filter(p=>p.status!=='completed').slice(0,4)){
      const row=node('div',undefined,'agenda-scheduled');row.append(node('span','已安排 '+(p.start_date||'未定日期')+(p.status==='paused'?' · 已暂停':''),'desc'));
      button(row,'改期',()=>reschedule(p));button(row,'取消安排',()=>cancel(p));parent.append(row);
    }
  }
  function scheduleLabel(p){
    const date=p.start_date,current=day();
    const when=!date?'未安排日期':date<current&&p.status!=='completed'?'过去安排待处理 · '+date:date===current?'已安排今日 · '+date:date===shift(current,1)?'已安排明日 · '+date:'已安排 '+date;
    return when+(p.status==='completed'?' · 安排已完成':p.blocked?' · 上级已暂停':p.status==='paused'?' · 已暂停':'')+(p.completion_mode==='time'?' · 计时安排':'');
  }
  async function moveCourse(p,date){
    await ActionPlans.refresh();
    if(matching(p.target).some(item=>item.start_date===date)){
      toast('该日期已有这门课程的安排，请在日程中查看。');refreshControls();return;
    }
    await ActionPlans.change(p,'reschedule',{date});
  }
  // 待继续课程可直接学习；仅展示安排状态与次要入口，其他日期的安排不再隐藏课程。
  function drawCourseControls(entry){
    const {parent,target,title,minutes}=entry,current=matching(target).sort((a,b)=>(a.start_date||'').localeCompare(b.start_date||''));
    const today=current.find(p=>p.start_date===day()),pending=current.filter(p=>p.status!=='completed');
    const visible=pending.length?pending:current.slice(-1);
    const status=node('p',visible.length?visible.slice(0,2).map(scheduleLabel).join('；')+(visible.length>2?'；另有 '+(visible.length-2)+' 项安排':''):'尚未加入日程，可直接学习。','desc course-schedule-status');parent.append(status);
    const controls=node('div',undefined,'action-buttons');parent.append(controls);
    if(!today&&(!pending.length||pending.length===1&&!pending[0].start_date))button(controls,'加入今日安排',()=>arrange(target,title,day(),minutes));
    const more=node('details',undefined,'course-schedule-more');more.append(node('summary','更多安排','btn'));controls.append(more);
    const options=node('div',undefined,'action-buttons course-schedule-options');more.append(options);
    if(!pending.length){
      button(options,'安排到明日',()=>arrange(target,title,shift(day(),1),minutes));
      button(options,'选择日期',()=>dateDialog('安排学习日期',shift(day(),1),date=>arrange(target,title,date,minutes)));
    }
    for(const p of pending){
      const row=node('div',undefined,'agenda-scheduled');row.append(node('span',scheduleLabel(p),'desc'));
      if(data().execution?.plan_id===p.id)row.append(node('span','正在执行，请先保存本次投入再调整日期。','desc'));
      else {
        if(!today&&!p.blocked)button(row,!p.start_date?'安排到今日':p.start_date<day()?'移至今日':'改到今日',()=>moveCourse(p,day()));
        button(row,'改期',()=>dateDialog('改期 · '+p.title,p.start_date||day(),date=>moveCourse(p,date)));button(row,'取消安排',()=>cancel(p));
      }
      options.append(row);
    }
    if(Array.isArray(data().capabilities?.content_receipts)&&!data().capabilities.content_receipts.includes(target.kind))parent.append(node('p','此课程的日程按投入计时；学完仍需在课程中本人确认。','desc course-schedule-note'));
  }
  function mount(parent,target,title,minutes=20,options={}){const entry={parent,target,title,minutes,compact:!!options.compact};mounts.add(entry);drawControls(entry);}
  function refreshControls(){for(const entry of mounts){if(!entry.parent.isConnected)mounts.delete(entry);else drawControls(entry);}}
  function reschedule(p){dateDialog('修改日期 · '+p.title,p.start_date||day(),date=>ActionPlans.change(p,'reschedule',{date}));}
  async function cancel(p){await ActionPlans.change(p,'cancel');toast('已取消日期安排，原内容和笔记仍保留。');}
  // 今日安排／明日预览共用任务行：执行操作外露，日期与记录管理收进「更多」。
  function row(parent,p){
    const running=data().execution?.plan_id===p.id,mode=p.completion_mode||'time',done=p.status==='completed';
    const box=node('article',undefined,'agenda-row'+(done?' agenda-done':''));box.dataset.planId=p.id;
    const content=node('div',undefined,'agenda-row-content');box.append(content);
    const type=mode==='check'?'待办':p.target?.kind==='article'?'阅读':mode==='content'?'课程':'计时行动';
    content.append(node('p',type+' · '+(p.start_date||'未安排')+(p.at?' '+p.at:'')+' · '+(done?'已完成':p.blocked?'上级已暂停':p.status==='paused'?'已暂停':running?'正在进行':'待执行'),'action-kicker'),node('h3',p.title));
    if(mode!=='check')content.append(node('p',mode==='time'?`标准 ${p.target_minutes} 分钟 · 已确认累计 ${p.progress?.minutes||0} 分钟`:(p.estimated_minutes?`预计 ${p.estimated_minutes} 分钟 · `:'')+'在原内容中确认读完／学完','desc'));
    const actions=node('div',undefined,'action-buttons');box.append(actions);
    if(p.practice_source)button(actions,'实践来源与应用反馈',()=>window.LearningPractices.open(p.id));
    actions.className='action-buttons agenda-primary';
    const more=node('details',undefined,'agenda-more'),summary=node('summary','更多','btn');
    summary.setAttribute('aria-label','更多操作：'+p.title);more.append(summary);
    const secondary=node('div',undefined,'action-buttons agenda-secondary');more.append(secondary);
    const future=p.start_date>ActionPlans.day(p.timezone);
    if(!p.start_date&&p.status==='active'&&!p.blocked){
      button(actions,mode==='check'?'安排今日并完成':'安排今日并开始',async()=>{
        const saved=await ActionPlans.change(p,'reschedule',{date:ActionPlans.day(p.timezone)});
        try{if(mode==='check')await ActionPlans.change(saved.plan,'complete');else if(mode==='content')await ActionPlans.openTarget(saved.plan.target,saved.plan.id);else await ActionPlans.start(saved.plan,'standard');}
        catch(error){throw Error('已安排今日，但尚未开始或完成：'+error.message);}
      },true);
    }else if(mode==='check'){
      if(!future||done){
        const label=node('label',undefined,'agenda-check'),check=node('input');check.type='checkbox';check.checked=done;
        check.disabled=future||p.status==='paused'||p.blocked;
        check.setAttribute('aria-label',(done?'撤销完成：':'完成待办：')+p.title);label.append(check);box.prepend(label);box.classList.add('agenda-has-check');
        check.onchange=async()=>{
          const list=box.closest('#agendaList,#agendaTomorrowList,#view-action-schedule')||parent;
          check.disabled=true;
          try{
            await ActionPlans.change(p,done?'reopen':'complete');
            // 完成后条目可能移入折叠组，焦点应留在可见的列表控件上。
            const replacement=[...list.querySelectorAll('.agenda-row')].find(el=>el.dataset.planId===p.id);
            const target=replacement?.querySelector('input[type=checkbox]');
            const group=replacement?.closest('.agenda-completed');
            if(group&&!group.open)group.querySelector('summary')?.focus();
            else if(target?.getClientRects().length&&!target.disabled)target.focus();
            else list.querySelector('.agenda-completed>summary')?.focus();
          }catch(e){check.checked=done;check.disabled=future||p.status==='paused'||p.blocked;toast(e.message);}
        };
      }
    }else if(done){if(p.target)button(actions,type==='阅读'?'再次阅读':'查看内容',()=>ActionPlans.openTarget(p.target,p.id));}
    else if(p.status==='active'&&!p.blocked){
      if(running)button(actions,'继续'+(type==='阅读'?'阅读':'执行'),()=>ActionPlans.openTarget(p.target,p.id),true);
      else if(!future){
        if(mode==='content'){button(actions,type==='阅读'?'打开文章':'打开课程',()=>ActionPlans.openTarget(p.target,p.id),true);button(secondary,'计时记录投入',()=>ActionPlans.start(p,'standard'));}
        else {const reached=(p.progress?.minutes||0)>=p.target_minutes;
          if(reached)button(actions,'确认完成',()=>ActionPlans.change(p,'complete-time'),true);
          button(reached?secondary:actions,reached?'继续计时':'开始行动',()=>ActionPlans.start(p,'standard'),!reached);
          if(p.minimum_minutes&&p.minimum_minutes<p.target_minutes)button(secondary,'先做 '+p.minimum_minutes+' 分钟',()=>ActionPlans.start(p,'minimum'));}
      }
      else if(p.target)button(actions,'查看内容',()=>ActionPlans.openTarget(p.target,p.id));
      if(mode==='content'&&!future)button(secondary,'核对完成',()=>ActionPlans.reconcile(p));
    }
    if(!done&&p.status!=='archived'){
      if(!running){
        button(secondary,'编辑',()=>ActionPlans.editDay(p));
        button(secondary,'改期',()=>reschedule(p));
        button(secondary,'移至未安排',()=>ActionPlans.change(p,'reschedule',{date:null}));
        if(p.at){const calendar=node('a','添加到日历');calendar.href='/api/action-plans/'+encodeURIComponent(p.id)+'/calendar.ics';calendar.className='btn';secondary.append(calendar);}
        else button(secondary,'设置时间',()=>ActionPlans.editDay(p));
        button(secondary,'取消安排',async()=>{if(window.confirm('取消后将归档这条安排，原内容、笔记和执行记录仍保留。确定取消？'))await cancel(p);});
      }
      if(p.status==='paused')button(actions,'恢复安排',()=>ActionPlans.change(p,'resume'));
    }
    button(secondary,'复制为新行动',()=>ActionPlans.copyDay(p));
    button(secondary,'进度复盘',()=>ActionPlans.review(p));
    box.append(more);
    if(p.goal_id){const goal=data().plans.find(x=>x.id===p.goal_id);if(goal)content.append(node('p','所属目标：'+goal.title,'desc'));}
    if(p.deadline)content.append(node('p','截止 '+p.deadline+(p.deadline_passed?' · 已超期，请调整':''),'desc'));
    if(p.outside_period)content.append(node('p','安排超出上级预期周期，关联保留','desc'));

    parent.append(box);box.dataset.planId=p.id;
  }
  function forDate(parent,date){
    if(!parent)return;
    const completedOpen=parent.querySelector('.agenda-completed')?.open||false;
    parent.replaceChildren();
    const plans=data().plans.filter(p=>p.period==='day'&&p.start_date===date&&p.status!=='archived');
    plans.sort((a,b)=>(a.status==='completed')-(b.status==='completed')||(a.id===data().execution?.plan_id?-1:b.id===data().execution?.plan_id?1:0)||(a.at||'').localeCompare(b.at||''));
    if(!plans.length)parent.append(node('p','这个日期还没有安排。可以从阅读、课程加入，或直接添加待办。','action-empty'));
    for(const p of plans.filter(p=>p.status!=='completed'))row(parent,p);
    const completed=plans.filter(p=>p.status==='completed');
    if(completed.length){
      const group=node('details',undefined,'agenda-completed');group.open=completedOpen;
      group.append(node('summary','已完成 '+completed.length+' 项'));
      for(const p of completed)row(group,p);
      parent.append(group);
    }
  }
  function render(){
    const dateInput=document.getElementById('personalDate'),current=day();
    if(lastDay&&current!==lastDay&&dateInput?.value===lastDay){dateInput.value=current;lastDay=current;window.renderPersonal?.();return;}
    lastDay=current;
    const selected=document.getElementById('personalDate')?.value||day();
    forDate(document.getElementById('agendaList'),selected);
    forDate(document.getElementById('agendaTomorrowList'),shift(selected,1));
    const pending=document.getElementById('agendaPending');if(pending){pending.replaceChildren();const count=data().plans.filter(p=>p.period==='day'&&['active','paused'].includes(p.status)&&p.start_date&&p.start_date<ActionPlans.day(p.timezone)&&p.id!==data().execution?.plan_id).length;
      if(count)button(pending,count+' 项过去的安排待处理',()=>{scope='earlier';page=1;goTab('action-schedule');});}
    window.updateDaySummary?.();refreshControls();window.renderOptionalLearning?.();
    if(document.getElementById('view-action-schedule')?.style.display!=='none')renderSchedule();
    renderGrowth();
  }
  function renderSchedule(){
    const root=document.getElementById('view-action-schedule');if(!root)return;root.replaceChildren(node('h2','日程安排'),node('p','安排今天和未来，过去未完成的事项可改期或取消。','desc'));
    const tabs=node('div',undefined,'action-buttons');root.append(tabs);
    for(const [key,text] of [['today','今日'],['tomorrow','明日'],['future','未来'],['earlier','待调整'],['undated','未安排'],['all','全部日程']]){const b=button(tabs,text,()=>{scope=key;page=1;renderSchedule();},scope===key);b.setAttribute('aria-pressed',String(scope===key));}
    button(tabs,'新建行动',()=>ActionPlans.newDay());if(data().workspace_version===1)button(tabs,'规划本周',()=>window.GoalPlanning.week());button(tabs,'刷新',()=>ActionPlans.refresh());
    const list=data().plans.filter(p=>p.period==='day'&&p.status!=='archived'&&(scope==='all'||scope==='today'&&p.start_date===day()||scope==='tomorrow'&&p.start_date===shift(day(),1)||scope==='future'&&p.start_date>shift(day(),1)||scope==='undated'&&!p.start_date&&['active','paused'].includes(p.status)||scope==='earlier'&&p.start_date&&p.start_date<ActionPlans.day(p.timezone)&&['active','paused'].includes(p.status)&&p.id!==data().execution?.plan_id));
    const inScope=(date,done)=>scope==='all'||scope==='today'&&date===day()||scope==='tomorrow'&&date===shift(day(),1)||scope==='future'&&date>shift(day(),1)||scope==='earlier'&&date&&date<day()&&!done;
    const legacy=(window.legacyAgendaTasks?.()||[]).filter(task=>inScope(task.date,task.done));
    if(scope==='earlier'&&list.length){
      const batch=node('details');batch.append(node('summary','批量调整待安排事项'));root.append(batch);const selected=[];
      for(const p of list){const label=node('label',p.title,'agenda-check'),input=node('input');input.type='checkbox';input.checked=batchSelected.has(p.id);input.onchange=()=>input.checked?batchSelected.add(p.id):batchSelected.delete(p.id);label.prepend(input);batch.append(label);selected.push({p,input});}
      const date=node('input');date.type='date';date.setAttribute('aria-label','批量修改日期');date.value=day();batch.append(date);
      const report=node('p',batchFailures.join('；'));report.setAttribute('role','status');batch.append(report);
      async function apply(action){const chosen=selected.filter(x=>x.input.checked);if(!chosen.length)throw Error('请先选择要调整的行动。');if(action==='date'&&!date.value)throw Error('请选择日期。');let ok=0;const errors=[];for(const x of chosen){try{await ActionPlans.change(x.p,action==='archive'?'archive':'reschedule',action==='archive'?{}:{date:action==='date'?date.value:null});x.input.checked=false;x.input.disabled=true;batchSelected.delete(x.p.id);ok++;}catch(e){errors.push(x.p.title+'：'+e.message);}}batchFailures=errors;renderSchedule();toast(`已处理 ${ok} 项${errors.length?'；失败 '+errors.length+' 项：'+errors.join('；'):''}`);if(errors.length){const current=document.getElementById('view-action-schedule');const note=node('p',errors.join('；'),'action-error');note.setAttribute('role','alert');current.prepend(note);}}
      button(batch,'修改所选日期',()=>apply('date'));button(batch,'所选移到未安排',()=>apply('undated'));button(batch,'归档所选',()=>apply('archive'));
    }
    const combined=[...list.map(plan=>({date:plan.start_date,plan})),...legacy.map(task=>({date:task.date,task}))].sort((a,b)=>(a.date||'9999').localeCompare(b.date||'9999'));
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
    isScheduled:(target,date=day())=>matching(target).some(p=>p.start_date===date),
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
