/* Goal ownership and calendar dates are two views of the same action identities. */
(() => {
  'use strict';
  let ctx, detail, selected, detailTab='overview', page=1;
  const expanded=new Map();let coursesOpen=false;
  const state={view:'goals',status:'active',query:'',cycle:'month',begin:'',end:''};
  const labels={goal:'目标',plan:'计划',action:'行动',year:'年度',month:'月计划',week:'周计划',custom:'阶段计划',day:'行动'};
  const statusLabels={active:'进行中',paused:'已暂停',completed:'已完成',archived:'已归档'};
  const node=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;};
  function button(parent,text,run,primary=false){const b=node('button',text,'btn'+(primary?' primary':''));b.type='button';b.onclick=async()=>{b.disabled=true;try{await run();}catch(e){toast(e.message);}finally{b.disabled=false;}};parent.append(b);return b;}
  function menu(parent,title='更多'){const d=node('details',undefined,'gw-menu');d.append(node('summary',title));const body=node('div',undefined,'gw-menu-body');d.append(body);parent.append(d);body.addEventListener('click',e=>{if(e.target.closest('button'))d.open=false;});return body;}
  function field(parent,text,type='text',value=''){return ctx.field(parent,text,type,value);}
  function select(parent,text,choices,value){const el=field(parent,text,'select');for(const [key,label] of choices)ctx.option(el,key,label);el.value=value;return el;}
  const plans=()=>ctx?.snapshot.plans||[];
  const byId=id=>plans().find(p=>p.id===id);
  function descendants(id){let ids=new Set([id]);for(;;){const next=new Set([...ids,...plans().filter(p=>ids.has(p.parent_id)).map(p=>p.id)]);if(next.size===ids.size)return plans().filter(p=>next.has(p.id)&&p.id!==id);ids=next;}}
  function ancestors(p){const chain=[],seen=new Set([p.id]);while(p.parent_id&&!seen.has(p.parent_id)){seen.add(p.parent_id);p=byId(p.parent_id);if(!p)break;chain.unshift(p);}return chain;}
  function periodText(p){return p.start_date?(p.period==='day'?p.start_date:p.start_date+' — '+p.end_date):'暂未安排周期';}
  function resultText(p){const r=p.result;if(!r||r.percent===null)return '待完善完成标准';return `${r.current} / ${r.target} ${r.unit||'项'} · ${r.percent}%`;}
  function resultView(parent,p){parent.append(node('p',resultText(p),'gw-result'));if(p.result?.percent!==null&&p.result?.percent!==undefined){const progress=node('progress');progress.max=100;progress.value=p.result.percent;progress.setAttribute('aria-label',p.title+'结果进度');parent.append(progress);}}
  function filtered(list){return list.filter(p=>(state.status==='all'||p.status===state.status)&&(!state.query||[p.title,p.expected_result,byId(p.goal_id)?.title,...(p.entity_type==='goal'?descendants(p.id).map(x=>x.title):[])].filter(Boolean).join(' ').toLocaleLowerCase().includes(state.query.toLocaleLowerCase())));}
  function summary(parent,p){
    const row=node('article',undefined,'gw-card');row.dataset.planId=p.id;parent.append(row);
    const info=node('div',undefined,'gw-card-info');row.append(info);
    info.append(node('p',`${labels[p.entity_type]} · ${statusLabels[p.status]} · ${periodText(p)}`,'action-kicker'));
    const title=button(info,p.title,()=>open(p.id));title.className='gw-title';
    if(p.entity_type==='goal'){
      resultView(info,p);
      const children=descendants(p.id),today=ctx.day();
      const stage=children.find(x=>x.entity_type==='plan'&&x.status==='active'&&x.start_date<=today&&x.end_date>=today);
      const next=children.filter(x=>x.entity_type==='action'&&x.status==='active'&&!x.blocked).sort((a,b)=>(a.start_date||'9999').localeCompare(b.start_date||'9999'))[0];
      info.append(node('p',stage?'当前阶段：'+stage.title:'当前阶段尚未安排','desc'));
      if(next)info.append(node('p','下一步：'+next.title,'desc'));
    }else{
      if(p.goal_id)info.append(node('p','所属目标：'+(byId(p.goal_id)?.title||''),'desc'));
      if(p.entity_type==='plan')info.append(node('p',`已完成 ${p.progress.completed} 项行动 · 投入 ${p.progress.minutes} 分钟`,'desc'));
    }
    if(p.outside_period)info.append(node('p','安排超出上级预期周期，关联保留','gw-notice'));
    if(p.deadline)info.append(node('p',`截止 ${p.deadline}${p.deadline_passed?' · 已超期，请调整':''}`,'gw-notice'));
    const actions=node('div',undefined,'gw-row-actions');row.append(actions);button(actions,'查看详情',()=>open(p.id));moreActions(actions,p);
  }
  function moreActions(parent,p){if(['completed','archived'].includes(p.status))return;const body=menu(parent);if(['active','paused'].includes(p.status))button(body,'编辑',()=>edit(p));
    if(p.status==='active'){button(body,'暂停',()=>statusChange(p,'pause'));if(p.entity_type!=='action')button(body,'确认完成',()=>statusChange(p,'complete'));}
    if(p.status==='paused')button(body,'恢复',()=>ctx.change(p,'resume'));
    if(p.status!=='archived')button(body,'归档',()=>statusChange(p,'archive'));
  }
  async function statusChange(p,action){if(p.entity_type!=='action'&&descendants(p.id).some(x=>x.status==='active')&&!confirm('该操作会影响下级行动的推进。确认继续？'))return;await ctx.change(p,action);}
  function create(kind,parent=null){if(kind==='action')return ActionPlans.newDay({parent,date:null,onSaved:p=>{if(p){open(p.id);highlight(p.id);}}});return window.GoalEditor.open(kind,null,parent);}
  function edit(p){if(p.entity_type==='action')return ActionPlans.editDay(p);return window.GoalEditor.open(p.entity_type,p);}
  function choose(parent=null){const d=ctx.dialog('新建');d.append(node('p',parent?'添加到「'+parent.title+'」，保存前可以修改所属。':'先记录方向、阶段安排，或下一件要做的事。','desc'));
    for(const [kind,title,description] of [['goal','目标','想达成什么结果，周期可以稍后确定'],['plan','计划','安排本月、本周或一个阶段的重点'],['action','行动','下一步做什么，可以暂不设日期']]){if(parent&&kind==='goal')continue;const b=button(d,title+' · '+description,()=>{d.close();create(kind,parent);});b.classList.add('gw-create-choice');}
    button(d,'取消',()=>d.close());
  }
  function render(context){ctx=context;const scroll=window.scrollY;const root=ctx.root;root.classList.add('goal-workspace');root.replaceChildren();
    const head=node('div',undefined,'gw-heading');root.append(head);const title=node('div');title.append(node('h2','目标与计划'),node('p','看清方向，安排下一步。也可以直接从一周或一件事开始。','desc'));head.append(title);
    const actions=node('div',undefined,'gw-row-actions');head.append(actions);button(actions,'＋新建',()=>choose(),true);
    const more=menu(actions,'工作区设置');button(more,'刷新',()=>ctx.refresh());button(more,'LightTick 联动',()=>window.ActionLink.show());button(more,'完成与进度说明',()=>window.showCompletionHelp?.());
    const toolbar=node('div',undefined,'gw-toolbar');root.append(toolbar);const views=node('div',undefined,'gw-segments');toolbar.append(views);
    for(const [value,text] of [['goals','按目标'],['cycles','按周期']]){const b=button(views,text,()=>{state.view=value;page=1;render(ctx);},state.view===value);b.setAttribute('aria-pressed',String(state.view===value));}
    const search=field(toolbar,'搜索目标、计划或行动','search',state.query);let timer;
    search.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>{const pos=search.selectionStart;state.query=search.value;page=1;render(ctx);const input=root.querySelector('input[type=search]');input.focus();input.setSelectionRange(pos,pos);},250);});
    const filters=node('details',undefined,'gw-filters');filters.append(node('summary','筛选'));toolbar.append(filters);
    const status=select(filters,'状态',[['active','进行中'],['paused','已暂停'],['completed','已完成'],['archived','已归档'],['all','全部']],state.status);status.onchange=()=>{state.status=status.value;page=1;render(ctx);};
    if(state.status!=='active'||state.query){const chips=node('div',undefined,'gw-chips');root.append(chips);chips.append(node('span',`筛选：${statusLabels[state.status]||'全部状态'}${state.query?' · '+state.query:''}`));button(chips,'清除筛选',()=>{state.status='active';state.query='';page=1;render(ctx);});}
    const content=node('div',undefined,'gw-content');root.append(content);
    if(state.view==='goals'){
      const goals=filtered(plans().filter(p=>p.entity_type==='goal'));
      if(!goals.length){content.append(node('h3','从一个想达成的结果开始'),node('p','可以创建目标，也可以先安排一个短期计划。','action-empty'));button(content,'创建目标',()=>create('goal'));}
      const list=node('div');content.append(list);for(const p of goals.slice((page-1)*12,page*12))summary(list,p);
      if(goals.length>12)paging(content,goals.length);
      const independent=filtered(plans().filter(p=>p.entity_type!=='goal'&&!p.goal_id&&(state.query||!p.parent_id)));
      const section=node('section',undefined,'gw-independent');section.append(node('h3','独立计划与行动'),node('p','不需要年目标，也能从本月、本周或下一步开始。','desc'));content.append(section);
      const shown=state.query?independent:independent.slice(0,12);for(const p of shown)summary(section,p);
      if(!shown.length)section.append(node('p','暂时没有独立计划或行动。','action-empty'));
      if(independent.length>shown.length)button(section,'查看全部独立项目',()=>{state.view='cycles';state.cycle='all';render(ctx);});
    }else{
      const ranges=node('div',undefined,'gw-cycle-controls');content.append(ranges);const cycle=select(ranges,'时间范围',[['month','本月'],['week','本周'],['custom','自定义'],['all','全部时间']],state.cycle);cycle.onchange=()=>{state.cycle=cycle.value;page=1;render(ctx);};
      const today=ctx.day();let [begin,end]=ctx.range(state.cycle==='week'?'week':'month',today);
      if(state.cycle==='custom'){const from=field(ranges,'开始日期','date',state.begin||today),to=field(ranges,'结束日期','date',state.end||today);button(ranges,'应用日期',()=>{if(!from.value||!to.value||to.value<from.value){toast('请选择有效日期范围。');return;}state.begin=from.value;state.end=to.value;page=1;render(ctx);});begin=state.begin||today;end=state.end||today;}
      const list=filtered(plans().filter(p=>p.entity_type!=='goal'&&(state.cycle==='all'||p.start_date&&p.start_date<=end&&p.end_date>=begin)));
      if(!list.length)content.append(node('p','这个范围没有安排，可调整日期或新建计划。','action-empty'));
      for(const p of list.slice((page-1)*15,page*15))summary(content,p);if(list.length>15)paging(content,list.length,15);
    }
    const courses=node('details',undefined,'gw-courses');courses.open=coursesOpen;courses.append(node('summary','关联课程'));root.append(courses);courses.addEventListener('toggle',()=>{coursesOpen=courses.open;if(courses.open&&!courses.dataset.loaded){courses.dataset.loaded='1';window.PlanActions?.mount(courses);}});
    if(detail?.open)renderDetail();window.scrollTo({top:scroll,behavior:'instant'});
  }
  function paging(parent,total,size=12){const bar=node('div',undefined,'action-buttons');parent.append(bar);button(bar,'上一页',()=>{page--;render(ctx);}).disabled=page===1;bar.append(node('span',`第 ${page} 页 · 共 ${total} 项`));button(bar,'下一页',()=>{page++;render(ctx);}).disabled=page*size>=total;}
  function highlight(id){const el=[...ctx.root.querySelectorAll('[data-plan-id]')].find(x=>x.dataset.planId===id);if(el){el.classList.add('gw-highlight');el.scrollIntoView({block:'center'});}}
  function open(id){if(!byId(id))return false;if(detail&&selected!==id)detail.scrollTop=0;selected=id;detailTab='overview';if(!detail?.isConnected){detail=node('dialog',undefined,'gw-detail');document.body.append(detail);const origin=document.activeElement;detail.addEventListener('close',()=>{detail.remove();detail=null;const row=[...ctx.root.querySelectorAll('[data-plan-id]')].find(x=>x.dataset.planId===selected);const focus=origin?.isConnected?origin:row?.querySelector('.gw-title')||ctx.root.querySelector('button');focus?.focus();});detail.showModal();}renderDetail();const heading=detail.querySelector('h2');heading.tabIndex=-1;heading.focus({preventScroll:true});return true;}
  function renderDetail(){const p=byId(selected);if(!p){detail.close();return;}const previousScroll=detail.scrollTop;detail.setAttribute('aria-label',p.title+'详情');detail.replaceChildren();
    const top=node('div',undefined,'gw-heading');detail.append(top);top.append(node('span',labels[p.entity_type]+' · '+statusLabels[p.status],'action-kicker'));button(top,'关闭详情',()=>detail.close());
    detail.append(node('h2',p.title));const chain=ancestors(p);if(chain.length){const nav=node('nav',undefined,'gw-breadcrumb');nav.setAttribute('aria-label','所属关系');detail.append(nav);for(const x of chain)button(nav,x.title,()=>open(x.id));}
    const tabs=node('div',undefined,'gw-segments');detail.append(tabs);for(const [key,text] of [['overview','概览'],['children','计划与行动'],['progress','进度与复盘']]){const b=button(tabs,text,()=>{detailTab=key;renderDetail();},detailTab===key);b.setAttribute('aria-pressed',String(detailTab===key));}
    const body=node('div',undefined,'gw-detail-body');detail.append(body);
    if(detailTab==='overview'){
      body.append(node('p',periodText(p),'desc'));if(p.expected_result)body.append(node('p','预期结果：'+p.expected_result));if(p.reason)body.append(node('p','为什么做：'+p.reason));
      if(p.entity_type==='goal')resultView(body,p);if(p.deadline)body.append(node('p','截止日期：'+p.deadline));if(p.outside_period)body.append(node('p','安排超出上级预期周期，关联仍保留。','gw-notice'));
      if(p.entity_type==='action')window.DailyAgenda.row(body,p);
      else{const children=descendants(p.id),today=ctx.day();const stages=children.filter(x=>x.entity_type==='plan'&&x.status==='active'&&x.start_date<=today&&x.end_date>=today);body.append(node('h3','当前阶段'));if(!stages.length)body.append(node('p','还没有当前阶段，可以先安排一个计划或行动。','desc'));for(const x of stages)summary(body,x);body.append(node('h3','下一步行动'));const next=children.filter(x=>x.entity_type==='action'&&x.status==='active').slice(0,3);for(const x of next)window.DailyAgenda.row(body,x);if(!next.length){body.append(node('p','先选一件能够开始的小事。','desc'));button(body,'安排第一步',()=>choose(p),true);}}
    }else if(detailTab==='children'){
      if(p.entity_type==='action')body.append(node('p','行动已是具体执行步骤。','desc'));
      else{button(body,'添加计划或行动',()=>choose(p),true);tree(body,p.id,new Set());}
    }else{
      if(p.entity_type==='goal'){resultView(body,p);button(body,'更新结果与完成标准',()=>window.GoalEditor.result(p),true);if(p.result?.ready)body.append(node('p','已达到当前标准，可在更多操作中本人确认完成。','gw-notice'));}
      body.append(node('p',`实际投入 ${p.progress.minutes} 分钟 · 有效完成 ${p.progress.completed} 项行动 · 起步 ${p.progress.minimum} 次`));
      button(body,'进度复盘与 AI 建议',()=>ActionPlans.review(p));
      for(const row of [...(p.result_history||[])].reverse())body.append(node('p',`${new Date(row.at).toLocaleString()} · 调整前：${row.metric?.mode||'未设置'}${row.note?' · '+row.note:''}`,'desc'));
    }
    const footer=node('div',undefined,'gw-detail-footer');detail.append(footer);if(['active','paused'].includes(p.status))button(footer,'编辑',()=>edit(p));
    if(p.entity_type!=='action'&&p.status==='active'){button(footer,'添加下一步',()=>choose(p),true);button(footer,'AI 辅助拆解',()=>window.GoalPlanning.ai(p));}
    moreActions(footer,p);footer.hidden=!footer.childElementCount;detail.scrollTop=previousScroll;
  }
  function tree(parent,id,seen){if(seen.has(id))return;seen.add(id);const children=plans().filter(p=>p.parent_id===id);if(!children.length){parent.append(node('p','还没有下级计划或行动。','desc'));return;}
    const today=ctx.day();for(const p of children){if(p.entity_type==='action'){window.DailyAgenda.row(parent,p);continue;}const group=node('details',undefined,'gw-tree');group.open=expanded.has(p.id)?expanded.get(p.id):p.status==='active'&&p.start_date<=today&&p.end_date>=today;group.addEventListener('toggle',()=>expanded.set(p.id,group.open));const title=node('summary',p.title+' · '+statusLabels[p.status]);group.append(title);parent.append(group);button(group,'查看计划',()=>open(p.id));tree(group,p.id,new Set(seen));}}
  window.GoalWorkspace={configure:context=>{ctx=context;},leave:()=>detail?.close(),render,open,create,edit,choose,context:()=>ctx,plans,byId,descendants,ancestors,node,button,menu,field,select,periodText,resultText,highlight};
})();
