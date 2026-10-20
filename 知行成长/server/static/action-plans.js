/* Year direction, week commitments and day actions, connected to the existing readers. */
(() => {
  'use strict';
  const home=document.getElementById('actionHome'),root=document.getElementById('view-action-plans'),bar=document.getElementById('actionExecution');
  const label={year:'年目标',month:'月计划',week:'周计划',day:'日行动'},statusLabel={active:'待推进',paused:'已暂停',completed:'已完成',archived:'已归档'};
  let initialized;
  let client,snapshot={plans:[],execution:null},offset=0,loading=null,loadTurn=0,lastSignature='',lastDays='',period='all',horizon='all',status='active',page=1,historyTurn=0,formDialog=null;
  const n=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;};
  const now=()=>new Date(Date.now()+offset),day=zone=>ActionPlanClient.day(now(),zone||'Asia/Shanghai');
  const visible=()=>root.style.display!=='none';
  function button(parent,text,action,primary=false){const b=n('button',text,'btn'+(primary?' primary':''));b.type='button';b.onclick=async()=>{b.disabled=true;try{await action();}catch(e){toast(e.message);}finally{b.disabled=false;}};parent.append(b);return b;}
  function field(parent,text,type='text',value=''){const wrap=n('label',text,'action-field');const input=n(type==='textarea'?'textarea':type==='select'?'select':'input');input.setAttribute('aria-label',text);if(!['textarea','select'].includes(type))input.type=type;if(type==='checkbox')input.checked=!!value;else input.value=value;wrap.append(input);parent.append(wrap);return input;}
  function option(select,value,text){const el=n('option',text);el.value=value;select.append(el);}
  const planById=id=>snapshot.plans.find(p=>p.id===id);
  function progress(p){return `${p.progress.completed} 次达标 · ${p.progress.minimum} 次起步 · 累计 ${p.progress.minutes} 分钟`;}
  async function load(force=false){
    if(!client)return;if(loading&&!force)return loading;
    const turn=++loadTurn;
    const task=client.read('').then(data=>{if(turn!==loadTurn)return snapshot;snapshot=data;offset=new Date(data.server_time)-Date.now();
      const signature=JSON.stringify([data.plans,data.execution]),days=[...new Set(['Asia/Shanghai',...data.plans.map(p=>p.timezone)])].map(zone=>day(zone)).join(',');
      if(signature!==lastSignature||days!==lastDays){lastSignature=signature;lastDays=days;renderHome();renderBar();if(visible())renderWorkspace();}remind().catch(()=>{});return data;});
    loading=task;try{return await task;}finally{if(loading===task)loading=null;}
  }
  async function change(p,action,values={}){
    const result=await client.write(action+':'+(values.execution_id||p.id),'/'+p.id+'/operations',{revision:p.revision,action,...values});
    const old=planById(p.id);snapshot.plans=snapshot.plans.map(item=>item.id===p.id?{...old,...result.plan}:item);
    if(result.execution&&(result.execution.outcome==='running'||result.execution.id===snapshot.execution?.id))snapshot.execution=result.execution.outcome==='running'?result.execution:null;
    renderHome();renderBar();if(visible())renderWorkspace();remind().catch(()=>{});
    try{await load(true);}catch{toast('操作已保存，列表暂未刷新，请稍后点击刷新计划。');}return result;
  }
  function openWorkspace(){if(goTab('action-plans')===false)return;}
  function dateTitle(p){return p.period==='day'?`${p.start_date} ${p.at} · ${p.target_minutes} 分钟 · ${p.timezone}`:`${p.start_date} 至 ${p.end_date} · 目标 ${p.target_count} 次达标`;}
  function item(parent,p,featured=false){
    const row=n('article',undefined,'action-row'+(featured?' action-featured':''));parent.append(row);
    row.append(n('p',label[p.period]+' · '+(p.horizon==='long'?'长期':'短期')+' · '+(p.blocked?'上级计划已暂停或结束':statusLabel[p.status]),'action-kicker'),n('h3',p.title),n('p',dateTitle(p),'desc'));
    if(p.reason)row.append(n('p','留给自己的理由：'+p.reason));if(p.if_then)row.append(n('p',p.if_then,'action-intention'));
    if(p.parent_id){const ancestor=planById(p.parent_id);row.append(n('p','关联'+(ancestor?label[ancestor.period]+'：'+ancestor.title:'上级计划'),'desc'));}
    row.append(n('p',progress(p),'action-progress'));
    const meter=n('progress');meter.max=p.target_count;meter.value=Math.min(p.target_count,p.progress.completed);meter.setAttribute('aria-label',p.title+'达标进度');row.append(meter,n('span',` ${p.progress.completed} / ${p.target_count} 次达标 · ${Math.min(100,Math.round(p.progress.completed/p.target_count*100))}%`,'desc'));
    const actions=n('div',undefined,'action-buttons');row.append(actions);
    if(p.period==='day'&&p.status==='active'&&!p.blocked){
      const future=p.start_date>day(p.timezone),running=snapshot.execution?.plan_id===p.id;
      if(running)button(actions,'继续学习',()=>openTarget(p.target),true);
      else if(!future){button(actions,'开始学习 · '+p.target_minutes+' 分钟',()=>start(p,'standard'),featured);button(actions,'先做 '+p.minimum_minutes+' 分钟',()=>start(p,'minimum'));}
      if(p.reminder){button(actions,'延后提醒 15 分钟',()=>change(p,'snooze'));}
      const calendar=n('a','添加到日历','btn');calendar.href='/api/action-plans/'+encodeURIComponent(p.id)+'/calendar.ics';actions.append(calendar);
    }
    if(!featured){
      button(actions,'进度复盘与 AI 建议',()=>window.ActionReviews.open({client,plan:p,dialog,edit:()=>editor(p.period,planById(p.id)||p)}));
      if(p.status!=='archived')button(actions,'编辑',()=>editor(p.period,p));
      if(p.status==='active')button(actions,'暂停',()=>change(p,'pause'));
      if(p.status==='paused')button(actions,'恢复',()=>change(p,'resume'));
      if(p.period!=='day'&&p.status==='active'){button(actions,'添加日行动',()=>editor('day',null,p));button(actions,'本人确认目标完成',async()=>{if(confirm('确认这个'+label[p.period]+'已经完成？已有执行记录会保留。'))await change(p,'complete');});}
      if(p.period==='year'&&p.status==='active')button(actions,'添加月计划',()=>editor('month',null,p));
      if(['year','month'].includes(p.period)&&p.status==='active')button(actions,'添加周计划',()=>editor('week',null,p));
      if(p.status!=='archived')button(actions,'归档',async()=>{if(confirm('归档后停止推进和提醒，历史执行记录会保留。'))await change(p,'archive');});
    }
  }
  function renderHome(){window.DailyAgenda?.render();}

  function renderWorkspace(){
    const reminderOpen=root.querySelector('.action-reminder-help')?.open;root.replaceChildren();const head=n('div',undefined,'section-heading');root.append(head);
    const title=n('div');title.append(n('h2','目标与计划'),n('p','年目标定方向，月周计划拆解，日行动从小处开始；随时查看进度并复盘。','desc'));head.append(title);
    const controls=n('div',undefined,'action-buttons');head.append(controls);for(const kind of ['year','month','week','day'])button(controls,'新建'+label[kind],()=>editor(kind),kind==='day');button(controls,'刷新计划',()=>load(true));button(controls,'LightTick 联动',()=>window.ActionLink.show());
    const tabs=n('div',undefined,'action-buttons');root.append(tabs);for(const [value,text] of [['all','全部'],['year','年目标'],['month','月计划'],['week','周计划'],['day','日行动']]){const b=button(tabs,text,()=>{period=value;page=1;renderWorkspace();},period===value);b.setAttribute('aria-pressed',String(period===value));}
    const horizonFilter=field(root,'规划视角','select');for(const [value,text] of [['all','全部长短期'],['long','长期规划'],['short','短期计划']])option(horizonFilter,value,text);horizonFilter.value=horizon;horizonFilter.onchange=()=>{horizon=horizonFilter.value;page=1;renderWorkspace();};
    const filter=field(root,'计划状态','select');for(const [value,text] of Object.entries(statusLabel))option(filter,value,text);option(filter,'all','全部状态');filter.value=status;filter.onchange=()=>{status=filter.value;page=1;renderWorkspace();};
    const plans=snapshot.plans.filter(p=>(period==='all'?p.period!=='day':p.period===period)&&(horizon==='all'||p.horizon===horizon)&&(status==='all'||p.status===status));
    const list=n('div');root.append(list);for(const p of plans.slice((page-1)*15,page*15))item(list,p);
    if(!plans.length)list.append(n('p','这个范围里还没有计划。可以先安排一次阅读，也可以从年目标开始。','action-empty'));
    const paging=n('div',undefined,'action-buttons');root.append(paging);const previous=button(paging,'上一页',()=>{page--;renderWorkspace();});previous.disabled=page===1;
    paging.append(n('span',`第 ${page} 页 · 共 ${plans.length} 项`));const next=button(paging,'下一页',()=>{page++;renderWorkspace();});next.disabled=page*15>=plans.length;
    const reminders=n('details',undefined,'action-reminder-help');reminders.open=!!reminderOpen;reminders.append(n('summary','提醒方式与 LightTick 联动'));root.append(reminders);
    reminders.append(n('p','到时提醒会在网页打开时显示。允许浏览器通知后可显示桌面通知，22:00–08:00 免打扰；网页关闭后请使用“添加到日历”，并在设备日历中确认导入和通知权限。'));
    reminders.append(n('p','日历提醒由设备独立管理；调整或归档网页计划后，请同步修改已导入的日历。LightTick 原生计划、系统提醒和离线执行的联动正在按统一账号与数据归属设计，当前版本未同步到 App。'));
    button(reminders,'允许网页打开时的浏览器提醒',enableNotifications);
    const records=n('section',undefined,'action-history');records.append(n('h3','执行记录'),n('p','起步、达标和中断分别保留；记录执行不会自动标记课程学完。','desc'));root.append(records);renderRecords(records,1);
  }
  async function renderRecords(container,recordPage){
    const turn=++historyTurn,rows=n('div');container.querySelector('.action-history-rows')?.remove();rows.className='action-history-rows';container.append(rows);rows.append(n('p','正在读取执行记录…'));
    try{const data=await client.read('/records?page='+recordPage);if(turn!==historyTurn||!rows.isConnected)return;rows.replaceChildren();
      for(const record of data.records){const row=n('article',undefined,'action-history-row');row.append(n('strong',record.title),n('p',`${record.business_date} · ${{running:'进行中',completed:record.completion_mode==='content'?'内容已完成':record.completion_mode==='check'?'待办已完成':'已达标',minimum:'已完成起步',partial:'已保存投入',interrupted:'中断已保存',reopened:'已撤销勾选'}[record.outcome]||record.outcome} · 实际 ${record.actual_minutes} 分钟`));if(record.note)row.append(n('p',record.note));rows.append(row);}
      if(!data.records.length)rows.append(n('p','开始一次行动后，执行记录会保存在这里。'));
      const controls=n('div',undefined,'action-buttons');rows.append(controls);const previous=button(controls,'更近的记录',()=>renderRecords(container,recordPage-1));previous.disabled=recordPage===1;
      controls.append(n('span',`共 ${data.total} 次执行 · 第 ${recordPage} 页`));const next=button(controls,'更早的记录',()=>renderRecords(container,recordPage+1));next.disabled=recordPage*30>=data.total;
    }catch(e){rows.replaceChildren(n('p',e.message));button(rows,'重新读取执行记录',()=>renderRecords(container,recordPage));}
  }
  function dialog(title){if(formDialog)formDialog.close();const d=n('dialog',undefined,'action-dialog');formDialog=d;d.append(n('h2',title));document.body.append(d);d.addEventListener('close',()=>{d.remove();if(formDialog===d)formDialog=null;});d.showModal();return d;}
  function range(kind,selected=day()){
    if(kind==='year')return [selected.slice(0,4)+'-01-01',selected.slice(0,4)+'-12-31'];
    if(kind==='month'){const dt=new Date(selected.slice(0,7)+'-01T12:00:00Z');dt.setUTCMonth(dt.getUTCMonth()+1);dt.setUTCDate(0);return [selected.slice(0,7)+'-01',dt.toISOString().slice(0,10)];}
    if(kind==='week'){const dt=new Date(selected+'T12:00:00Z'),shift=(dt.getUTCDay()+6)%7;dt.setUTCDate(dt.getUTCDate()-shift);const begin=dt.toISOString().slice(0,10);dt.setUTCDate(dt.getUTCDate()+6);return [begin,dt.toISOString().slice(0,10)];}
    return [selected,selected];
  }
  function editor(kind,existing=null,parent=null){
    const draftName='form.'+(existing?.id||'new'),draft=client.get(draftName),anchor=parent?[parent.start_date,day(parent.timezone),parent.end_date].sort()[1]:day(),[begin,end]=range(kind,anchor).map(value=>parent?[parent.start_date,value,parent.end_date].sort()[1]:value),defaultDate=parent?anchor:begin;
    const base=existing||{title:'',period:kind,horizon:kind==='year'?'long':'short',start_date:kind==='day'?defaultDate:begin,end_date:kind==='day'?defaultDate:end,parent_id:parent?.id||null,timezone:parent?.timezone||'Asia/Shanghai',target_minutes:20,minimum_minutes:5,target_count:kind==='day'?1:kind==='week'?5:kind==='month'?20:100,at:'21:00',reminder:true,reason:'',if_then:'',target:{kind:'library'}};
    const seed=draft?.period===kind?{...base,...draft}:base;
    const d=dialog((existing?'编辑':'新建')+label[kind]),form=n('form');d.append(form);const error=n('p','','action-error');error.setAttribute('role','alert');
    if(draft?.period===kind)d.append(n('p','已恢复上次未提交的填写。','desc'));
    const fields={},grid=n('div',undefined,'action-form-grid');form.append(grid);
    fields.title=field(grid,'计划名称','text',seed.title);fields.title.required=true;fields.title.maxLength=160;
    fields.horizon=field(grid,'长短期分类','select');option(fields.horizon,'short','短期计划');option(fields.horizon,'long','长期规划');fields.horizon.value=seed.horizon||(kind==='year'?'long':'short');
    fields.parent_id=field(grid,'关联上级计划（可选）','select');option(fields.parent_id,'','独立计划');
    for(const p of snapshot.plans.filter(p=>p.status==='active'&&({year:0,month:1,week:2,day:3}[p.period]<{year:0,month:1,week:2,day:3}[kind])))option(fields.parent_id,p.id,label[p.period]+' · '+(p.horizon==='long'?'长期':'短期')+' · '+p.title);
    fields.parent_id.value=seed.parent_id||'';
    fields.start_date=field(grid,kind==='day'?'行动日期':'开始日期','date',seed.start_date);fields.start_date.required=true;
    if(kind!=='day'){fields.end_date=field(grid,'结束日期','date',seed.end_date);fields.end_date.required=true;}
    fields.timezone=field(grid,'计划时区','text',seed.timezone);fields.timezone.required=true;
    fields.target_minutes=field(grid,'每次标准分钟','number',seed.target_minutes);fields.target_minutes.min=1;fields.target_minutes.max=1440;
    fields.minimum_minutes=field(grid,'起步分钟','number',seed.minimum_minutes);fields.minimum_minutes.min=1;fields.minimum_minutes.max=1440;
    if(kind!=='day'){fields.target_count=field(grid,'目标达标次数','number',seed.target_count);fields.target_count.min=1;fields.target_count.max=1000;}
    fields.at=field(grid,kind==='day'?'计划开始时间':'默认行动时间','time',seed.at);fields.at.required=true;
    if(kind==='day')fields.reminder=field(grid,'到时提醒（网页打开时）','checkbox',seed.reminder);
    fields.reason=field(form,'为什么想做（可选）','textarea',seed.reason);fields.reason.maxLength=1000;
    fields.if_then=field(form,'分心时的约定（可选）','textarea',seed.if_then);fields.if_then.placeholder='例如：想刷短视频时，先读 5 分钟再决定。';fields.if_then.maxLength=1000;
    const target=field(form,'一键开始后做什么','select');let targets=[{name:'进入我的课程选择内容',value:{kind:'library'}},{name:'读纸质书／其他行动，只记录执行',value:{kind:'book'}}];
    if(!['library','book'].includes(seed.target.kind))targets.push({name:'沿用已关联的学习内容',value:seed.target});
    targets.forEach((t,i)=>option(target,String(i),t.name));target.value=String(Math.max(0,targets.findIndex(t=>JSON.stringify(t.value)===JSON.stringify(seed.target))));
    const targetControls=n('div',undefined,'action-buttons');form.append(targetControls);button(targetControls,'选择已有课程或历史文章',async()=>{error.textContent='正在读取可关联内容…';
      const requests=await Promise.allSettled([fetch('/api/study-materials').then(r=>r.ok?r.json():Promise.reject(Error('英文与表达课程暂不可用'))),fetch('/api/copilot/today-task').then(r=>r.ok?r.json():Promise.reject(Error('认知课程暂不可用'))),fetch('/api/plans').then(r=>r.ok?r.json():Promise.reject(Error('学习计划暂不可用'))),fetch('/api/reading/library?page_size=50').then(r=>r.ok?r.json():Promise.reject(Error('历史文章暂不可用')))]);
      if(!d.isConnected)return;
      const add=(name,value)=>{if(!targets.some(t=>JSON.stringify(t.value)===JSON.stringify(value))){targets.push({name,value});option(target,String(targets.length-1),name);}};
      if(requests[0].status==='fulfilled')for(const m of requests[0].value.modules||[])for(const l of m.lessons)add(m.name+' · '+l.topic,{kind:m.id,course:l.filename});
      if(requests[1].status==='fulfilled')for(const l of requests[1].value.lessons||[])add('认知 · '+l.topic,{kind:'renzhi',lesson_no:l.lesson_no});
      if(requests[2].status==='fulfilled')for(const p of requests[2].value.plans||[])for(const l of p.lessons)add(p.name+' · '+l.topic,{kind:'plan',plan_id:p.id,lesson_no:l.lesson_no});
      if(requests[3].status==='fulfilled')for(const a of requests[3].value.articles||[])add('历史文章 · '+(a.zh_title||a.title),{kind:'article',course:a.id});
      error.textContent=requests.filter(r=>r.status==='rejected').map(r=>r.reason.message).join('；');target.focus();
    });
    const repeat=n('fieldset',undefined,'action-repeat');if(kind==='day'&&!existing){repeat.append(n('legend','重复安排（同一周，可选）'));form.append(repeat);}
    function repeatChoices(){if(!repeat.isConnected)return;repeat.querySelectorAll('label').forEach(el=>el.remove());const [monday]=range('week',fields.start_date.value||day());for(let i=0;i<7;i++){const dt=new Date(monday+'T12:00:00Z');dt.setUTCDate(dt.getUTCDate()+i);const value=dt.toISOString().slice(0,10);const input=field(repeat,['周一','周二','周三','周四','周五','周六','周日'][i]+' '+value,'checkbox',(seed.repeat_dates||[]).includes(value));input.dataset.date=value;}}
    repeatChoices();fields.start_date.addEventListener('change',repeatChoices);
    function payload(){const values={period:kind,target_count:1,reminder:false};if(seed.completion_mode&&seed.completion_mode!=='time')values.completion_mode=seed.completion_mode;for(const [name,input] of Object.entries(fields))values[name]=input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):input.value;values.parent_id||=null;values.end_date||=values.start_date;values.target=targets[Number(target.value)]?.value||seed.target;
      return values;}
    function saveDraft(){const values=payload();values.revision=existing?.revision||seed.revision;values.repeat_dates=[...repeat.querySelectorAll('input:checked')].map(input=>input.dataset.date);client.put(draftName,values);}
    form.addEventListener('input',saveDraft);form.addEventListener('change',saveDraft);form.append(error);
    const actions=n('div',undefined,'action-buttons');form.append(actions);const save=n('button',existing?'保存修改':'创建计划','btn primary');save.type='submit';actions.append(save);button(actions,'稍后继续',()=>{saveDraft();d.close();});
    if(existing||draft)button(actions,'放弃表单修改',async()=>{if(confirm('放弃当前表单的未提交修改？已保存的计划和执行记录会保留。')){client.remove(draftName);d.close();}});
    form.onsubmit=async event=>{event.preventDefault();save.disabled=true;error.textContent='正在保存计划…';saveDraft();try{const values=payload();
      if(existing)await change({...existing,revision:seed.revision||existing.revision},'edit',{fields:values});
      else{const dates=[...repeat.querySelectorAll('input:checked')].map(input=>input.dataset.date).sort();if(dates.length){values.start_date=dates[0];values.end_date=dates[0];}const saved=await client.write('create','',{...values,repeat_dates:dates});snapshot.plans.push(...saved.plans.map(p=>({...p,progress:{completed:0,minimum:0,minutes:0,interrupted:0},blocked:false})));}
      client.remove(draftName);d.close();renderHome();if(visible())renderWorkspace();toast(existing?'计划已更新':'计划已保存，可以开始行动了。');try{await load(true);}catch{toast('计划已保存，列表暂未刷新，可以稍后再刷新。');}
    }catch(e){error.textContent=e.message;}finally{save.disabled=false;}};
    fields.title.focus();
  }
  async function openTarget(target){
    if(target.kind==='book'){toast('已开始行动，可以在底部保存实际投入。');return;}
    if(target.kind==='library'){goTab('library');return;}
    if(target.kind==='renzhi'){rememberLearningOrigin();await window.openCopilotLesson(target.lesson_no);return;}
    if(target.kind==='plan'){await window.openPlanCourse(target.plan_id,target.lesson_no);return;}
    if(target.kind==='article'){const origin={tab:currentTab,scroll:window.scrollY,focus:document.activeElement};if(goTab('reading')===false)return;await window.openActionArticle(target.course,origin);return;}
    await window.loadDailyLearning();await window.openStudyCourse(target.kind,target.course);
  }
  async function start(p,variant){const result=await change(p,'start',{variant});try{await openTarget(result.plan.target);}catch(e){toast('执行已保留，学习内容暂未打开：'+e.message);}}
  function renderBar(){
    bar.replaceChildren();bar.hidden=!snapshot.execution;document.body.classList.toggle('action-running',!!snapshot.execution);if(!snapshot.execution)return;
    const execution=snapshot.execution,p=planById(execution.plan_id),text=n('div');text.append(n('strong','正在执行：'+execution.title),n('span',' 计时中 · 计划 '+execution.planned_minutes+' 分钟','action-clock'));bar.append(text);
    const actions=n('div',undefined,'action-buttons');bar.append(actions);button(actions,'继续执行',()=>openTarget(execution.target));button(actions,p?.completion_mode==='content'?'记录投入':'记录完成',()=>finish(p,execution,'completed'),true);button(actions,'中断并保留记录',()=>finish(p,execution,'interrupted'));
  }
  function finish(p,execution,outcome){const draftKey='finish.'+execution.id,draft=client.get(draftKey)||{};const d=dialog(outcome==='completed'?'确认本次执行':'保存中断记录'),form=n('form');d.append(form);form.append(n('p',execution.title),n('p',p.completion_mode==='content'?'计时只作参考，请确认实际投入。读完／学完请在原内容中确认，这里仅保存投入。':'计时只作参考，请确认实际投入。课程完成与学习笔记保持独立。','desc'));
    const minutes=field(form,'实际执行分钟','number',draft.minutes??Math.max(0,Math.floor((now()-new Date(execution.started_at))/60000)));minutes.min=outcome==='completed'?1:0;minutes.max=1440;minutes.required=true;
    const note=field(form,'收获或中断原因（可选）','textarea',draft.note||'');note.maxLength=2000;form.addEventListener('input',()=>client.put(draftKey,{minutes:minutes.value,note:note.value}));const error=n('p','','action-error');error.setAttribute('role','alert');form.append(error);
    const actions=n('div',undefined,'action-buttons');form.append(actions);const save=n('button',outcome==='completed'?'确认并记录':'保存中断','btn primary');save.type='submit';actions.append(save);button(actions,'继续执行',()=>d.close());
    form.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{const result=await change(p,'finish',{execution_id:execution.id,outcome,actual_minutes:Number(minutes.value),note:note.value});client.remove(draftKey);d.close();toast(result.execution.outcome==='completed'?'本次已达标，执行记录已保存。':'记录已保存，之后可以继续。');}catch(e){error.textContent=e.message;}finally{save.disabled=false;}};
  }
  async function enableNotifications(){
    if(!('Notification' in window)||!window.isSecureContext){toast('当前浏览器不支持通知，可使用站内提醒或添加到日历。');return;}
    const permission=await Notification.requestPermission();client.put('notifications',permission==='granted');toast(permission==='granted'?'已允许网页打开时的浏览器提醒。':'将继续使用站内提醒，也可以添加到日历。');
  }
  async function remind(){
    if(!client||document.hidden)return;const due=ActionPlanClient.pending(snapshot.plans,now(),snapshot.execution).filter(p=>p.reminder&&new Date(p.reminder_at)<=now()&&p.id!==snapshot.execution?.plan_id);
    const banner=document.getElementById('actionReminder'),identity=due.length?JSON.stringify([due[0].id,due[0].revision]):'';
    if(banner.dataset.reminder!==identity){banner.dataset.reminder=identity;banner.replaceChildren();banner.hidden=!due.length;
      if(due.length){const p=due[0];banner.append(n('strong','你留给自己的行动时间到了：'+p.title));button(banner,'现在开始',()=>start(p,'standard'),true);button(banner,'延后 15 分钟',()=>change(p,'snooze'));}}
    if(!client.get('notifications')||!('Notification' in window)||Notification.permission!=='granted')return;
    for(const p of due.slice(0,3)){const claim=await client.read('/'+p.id+'/reminder-claim',{device_id:client.device,reminder_at:p.reminder_at});if(claim.notify){try{const notice=new Notification('留一点时间给自己',{body:p.title+' · 先开始 '+p.minimum_minutes+' 分钟也可以',tag:p.id});notice.onclick=()=>{window.focus();openWorkspace();notice.close();};}catch{client.put('notifications',false);}}}
  }
  async function schedule(values){
    await initialized;const result=await client.write('schedule:'+JSON.stringify(values.target)+':'+values.date,'/schedules',values);
    await load(true);return result;
  }
  async function addTask(title,date){
    await initialized;const values={title,period:'day',start_date:date,end_date:date,completion_mode:'check',target:{kind:'book'}};
    await client.write('todo:'+date,'',values);await load(true);
  }
  async function records(){
    const target=document.getElementById('view-action-records');target.replaceChildren(n('h2','执行记录'),n('p','本人确认的完成、投入与中断记录；内容完成不推算时长。','desc'));
    try{await initialized;await renderRecords(target,1);}catch(e){target.append(n('p',e.message));button(target,'重试',records);}
  }
  window.ActionPlans={enter:async()=>{root.setAttribute('aria-busy','true');if(!root.childElementCount)root.append(n('h2','目标与计划'),n('p','正在读取计划与进度…'));try{await initialized;await load();renderWorkspace();}catch(e){root.replaceChildren(n('p',e.message));button(root,'重试读取计划',()=>window.ActionPlans.enter());}finally{root.removeAttribute('aria-busy');}},
    refresh:async()=>{await initialized;return load(true);},snapshot:()=>snapshot,day,newDay:async()=>{await initialized;editor('day');},
    schedule,addTask,change,start,openTarget,records,
    reconcile:async p=>{const result=await change(p,'reconcile');toast('已核对保存的内容完成记录。');return result;}};
  document.querySelector('.topbar').after(document.getElementById('actionReminder'));
  initialized=(window.Account?.ready||Promise.resolve({id:'local'})).then(user=>{client=ActionPlanClient.create({request:window.fetch.bind(window),storage:localStorage,account:user.id});
    load().then(remind).catch(e=>{const list=document.getElementById('agendaList');list.replaceChildren(n('p',e.message));button(list,'重新读取安排',()=>load(true));});
    setInterval(()=>{const el=bar.querySelector('.action-clock');if(el&&snapshot.execution){const seconds=Math.max(0,Math.floor((now()-new Date(snapshot.execution.started_at))/1000));el.textContent=` · 已开始 ${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')} · 请确认实际投入`; }},1000);
    setInterval(()=>{if(!document.hidden)load().then(remind).catch(()=>{});},30000);
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)load().then(remind).catch(()=>{});});
  });
})();
