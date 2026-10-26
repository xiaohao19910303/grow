/* Course-first navigation. Reading and source completion retain their own contracts. */
(() => {
  'use strict';
  const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
  const labels={learning:'学习中',pending:'待学习',completed:'已学完',paused:'已暂停',archived:'已归档'};
  const library=document.getElementById('learningLibrary'), detail=document.getElementById('view-course');
  const activityPath='/api/study-materials/library/activity';
  let filter='learning', selected=null, activities=new Map(), activityError='', activityRequest=null;
  let failedOpen=null, activityRevision=0;
  const localUpdates=new Map();
  const snapshot=()=>window.DailyLearning?.snapshot() || {modules:[],errors:[],pending:[],loaded:false};
  const courses=()=>snapshot().modules.map(m=>CourseCatalog.describe(m,activities.get(CourseCatalog.key(m))));
  function button(parent,label,action,primary=false){
    const b=node('button',label,'btn'+(primary?' primary':''));b.type='button';
    b.onclick=async()=>{b.disabled=true;try{await action();}catch(error){toast(error.message);}finally{b.disabled=false;}};
    parent.append(b);return b;
  }
  async function request(body){
    const response=await fetch(activityPath,{method:body?'POST':'GET',cache:'no-store',
      headers:body?{'Content-Type':'application/json','X-Copilot-Request':'1'}:{},body:body?JSON.stringify(body):undefined});
    if(!response.ok)throw Error('学习位置暂未同步，可继续阅读并稍后重试。');
    return response.json();
  }
  function notice(){
    const box=document.getElementById('courseActivityNotice');if(!box)return;
    box.replaceChildren();box.hidden=!activityError;
    if(activityError){box.append(node('p',activityError));button(box,'重试学习位置同步',()=>failedOpen?recordOpened(failedOpen.course_key,failedOpen.lesson_no):loadActivity());}
  }
  function loadActivity(){
    if(activityRequest)return activityRequest;
    const revision=activityRevision;
    activityRequest=request().then(data=>{
      // A late initial read must not overwrite an open recorded in this tab.
      const loaded=new Map((data.items||[]).map(item=>[item.course_key,item]));
      for(const [key,updated] of localUpdates)if(updated>revision)loaded.set(key,activities.get(key));
      activities=loaded;
      if(!failedOpen)activityError='';
    }).catch(error=>{activityError=error.message;}).finally(()=>{activityRequest=null;notice();render();});
    return activityRequest;
  }
  async function recordOpened(courseKey,lessonNo){
    const body={course_key:courseKey,lesson_no:Number(lessonNo)};
    try{
      const saved=await request(body);activities.set(courseKey,saved);++activityRevision;
      localUpdates.set(courseKey,activityRevision);
      if(failedOpen?.course_key===courseKey)failedOpen=null;
      if(!failedOpen)activityError='';
    }catch(error){failedOpen=body;activityError=error.message;}
    notice();render();
  }
  function progress(parent,item){
    const wrap=node('div',undefined,'course-progress');
    const label=item.finite?`已学完 ${item.completed} / ${item.total} 课`:`已发布内容：已学完 ${item.completed} / ${item.total} 课`;
    wrap.append(node('span',label),node('span',item.total?`${item.percent}%`:'待准备课程'));
    const bar=node('progress');bar.max=Math.max(1,item.total);bar.value=item.completed;bar.setAttribute('aria-label',item.module.name+'学习进度');
    wrap.append(bar);parent.append(wrap);
  }
  function primary(parent,item){
    if(item.status==='completed')return button(parent,'查看与复习',()=>open(item.key),true);
    if(['paused','archived'].includes(item.status))return button(parent,'查看课程',()=>open(item.key));
    if(item.next)return button(parent,item.status==='pending'?'开始学习':'继续学习',()=>window.DailyLearning.read(item.module,item.next),true);
    return button(parent,item.caughtUp?'查看后续规划':'查看课程',()=>open(item.key),true);
  }
  function card(parent,item){
    const card=node('article',undefined,'course-card');card.dataset.courseKey=item.key;
    const head=node('div',undefined,'course-card-heading');head.append(node('h3',item.module.name));
    head.append(node('span',item.caughtUp&&!['paused','archived'].includes(item.status)?'已学至最新':labels[item.status],'course-badge'));card.append(head);
    if(item.goal)card.append(node('p',item.goal,'course-goal'));
    progress(card,item);
    card.append(node('p',item.status==='completed'?(item.completedAt?'完成于 '+item.completedAt.slice(0,10):'全部规划课次已确认学完'):
      `当前阶段：${item.stage} · 每次 ${item.module.duration}`,'desc'));
    if(item.last)card.append(node('p',`上次学到：第 ${item.last.lesson_no} 课 · ${item.last.topic}`,'course-resume'));
    else if(item.next)card.append(node('p',`下一课：第 ${item.next.lesson_no} 课 · ${item.next.topic}`,'course-resume'));
    else if(item.caughtUp)card.append(node('p',item.finite?'已学完已发布内容，后续课次待准备。':'当前内容已学完，可进入课程准备后续内容。','desc'));
    const actions=node('div',undefined,'course-actions');primary(actions,item);
    if(!['completed','paused','archived'].includes(item.status))button(actions,'课程详情',()=>open(item.key));
    card.append(actions);parent.append(card);
  }
  function sourceStatus(parent){
    const data=snapshot();
    for(const error of data.errors){const p=node('p',error,'course-source-error');p.setAttribute('role','status');parent.append(p);}
    if(data.pending.length){const p=node('p','正在读取'+data.pending.join('、')+'…','desc');p.setAttribute('role','status');parent.append(p);}
    if(data.errors.length)button(parent,'重试读取课程',()=>window.loadDailyLearning({force:true}));
  }
  function renderLibrary(){
    library.replaceChildren();sourceStatus(library);
    if(!snapshot().loaded){library.append(node('p','正在读取课程…','desc'));return;}
    const all=courses(), tabs=node('div',undefined,'course-filters');tabs.setAttribute('role','group');tabs.setAttribute('aria-label','课程状态');
    for(const state of ['learning','pending','completed']){
      const b=button(tabs,`${labels[state]} ${all.filter(c=>c.status===state).length}`,()=>{filter=state;renderLibrary();library.querySelector(`[data-filter="${state}"]`).focus();});
      b.dataset.filter=state;b.setAttribute('aria-pressed',String(filter===state));
    }
    library.append(tabs);
    const list=node('div',undefined,'course-cards');all.filter(c=>c.status===filter).forEach(item=>card(list,item));library.append(list);
    if(!list.childElementCount){const empty=node('div',undefined,'course-empty');empty.setAttribute('role','status');
      empty.append(node('p',snapshot().pending.length?'正在整理课程…':snapshot().errors.length?'部分课程暂未读取，请重试后查看。':`暂无${labels[filter]}课程`));
      if(filter==='learning'&&all.some(c=>c.status==='pending'))button(empty,'查看待学习课程',()=>{filter='pending';renderLibrary();library.querySelector('[data-filter="pending"]').focus();});
      library.append(empty);
    }
    const inactive=all.filter(c=>['paused','archived'].includes(c.status));
    if(inactive.length){const saved=node('details',undefined,'course-inactive');saved.append(node('summary',`暂停与归档（${inactive.length}）`));const list=node('div',undefined,'course-cards');inactive.forEach(item=>card(list,item));saved.append(list);library.append(saved);}
  }
  function disclosure(parent,label,id,opened=false){
    const box=node('details',undefined,'course-disclosure');box.dataset.section=id;box.open=opened;
    box.append(node('summary',label));parent.append(box);return box;
  }
  function tools(parent,item){
    const box=disclosure(parent,'课程工具与设置','tools');const actions=node('div',undefined,'course-actions');actions.setAttribute('role','group');actions.setAttribute('aria-label',item.module.name+'课程工具');box.append(actions);
    if(item.module.kind==='plan')button(actions,'调整规划与准备课程',()=>window.openLearningPlan(item.module.id));
    if(item.module.id==='renzhi'){
      button(actions,'认知课程管理',()=>goTab('copilot'));
      button(actions,'课程归档',()=>goTab('archive'));button(actions,'课程总结',()=>goTab('summary'));
    }
    button(actions,'草稿与课程设置',()=>goTab('plans'));
  }
  function renderDetail(){
    if(!detail || !selected)return;
    const expanded=new Map([...detail.querySelectorAll('details[data-section]')].map(el=>[el.dataset.section,el.open]));
    detail.replaceChildren();button(detail,'返回我的课程',()=>goTab('library'));
    const item=courses().find(c=>c.key===selected);
    if(!item){sourceStatus(detail);detail.append(node('h2',snapshot().pending.length||!snapshot().loaded?'正在读取课程…':'暂时找不到这门课程'));
      if(!snapshot().pending.length)button(detail,'重新读取课程',()=>window.loadDailyLearning({force:true}));return;}
    detail.append(node('p','我的课程 / '+item.module.name,'desc'));
    const heading=node('h2',item.module.name);heading.tabIndex=-1;detail.append(heading);
    if(item.goal)detail.append(node('p',item.goal,'course-detail-goal'));
    const overview=node('section',undefined,'course-overview');progress(overview,item);
    overview.append(node('p',`${['paused','archived'].includes(item.status)?labels[item.status]+' · ':''}当前阶段：${item.stage}${item.caughtUp?' · 已学至最新':''}`,'desc'));
    if(item.next)overview.append(node('p',`${item.last&&item.last===item.next?'继续上次课次':'接下来'}：第 ${item.next.lesson_no} 课 · ${item.next.topic}`));
    if(!['paused','archived','completed'].includes(item.status)){
      const actions=node('div',undefined,'course-actions');
      if(item.next)primary(actions,item);
      else actions.append(node('p',item.caughtUp?'已学完当前发布内容，可在下方选择下一步学习。':'尚无已发布课次，可在下方准备第一课。','desc'));
      overview.append(actions);
    }
    detail.append(overview);
    window.CourseContinuation?.mount(detail,item.key,{refresh:true});
    detail.append(node('h3','课程目录'));
    const curriculum=item.module.curriculum;
    const stages=item.finite?curriculum.stages:[{title:'已发布课次',goal:'课程持续更新；打开和暂存笔记不会自动算学完。'}];
    const current=item.finite?(curriculum.lessons.find(l=>l.number===(item.next?.lesson_no||item.upcoming?.number))?.stage||stages.length):1;
    stages.forEach((stage,index)=>{
      const planned=item.finite?curriculum.lessons.filter(l=>l.stage===index+1):item.lessons.map(l=>({number:l.lesson_no,topic:l.topic}));
      const done=planned.filter(p=>item.lessons.some(l=>l.lesson_no===p.number&&l.learning_state==='completed')).length;
      const box=disclosure(detail,`${item.finite?'阶段 '+(index+1)+' · ':''}${stage.title}（${done}/${planned.length}）`,'stage-'+index,index+1===current);
      if(stage.goal)box.append(node('p',stage.goal,'desc'));
      for(const plannedLesson of planned){
        const lesson=item.lessons.find(l=>l.lesson_no===plannedLesson.number);
        if(lesson)window.DailyLearning.lessonRow(box,item.module,lesson);
        else{const row=node('div',undefined,'course-unpublished');row.append(node('strong',`第 ${plannedLesson.number} 课 · ${plannedLesson.topic}`),node('span','待准备课程','desc'));box.append(row);}
      }
      if(!planned.length)box.append(node('p','尚无已发布课次。','desc'));
    });
    if(item.finite){const plan=disclosure(detail,'学习规划','plan');
      if(item.module.brief)plan.append(node('p',`当前基础：${item.module.brief.level||'未填写'} · `+(item.module.brief.pacing==='self_paced'?`自由节奏 · 共 ${item.module.brief.lesson_count} 课`:`${item.module.brief.weeks} 周 · 每周 ${item.module.brief.sessions} 次`),'desc'));
      if(curriculum.prerequisites)plan.append(node('p','先修说明：'+curriculum.prerequisites));
      button(plan,'查看或调整完整规划',()=>window.openLearningPlan(item.module.id));
    }
    tools(detail,item);sourceStatus(detail);
    for(const el of detail.querySelectorAll('details[data-section]'))if(expanded.has(el.dataset.section))el.open=expanded.get(el.dataset.section);
  }
  function render(){renderLibrary();if(selected&&detail.style.display!=='none')renderDetail();}
  function open(key,options={}){
    const previous=selected;selected=key;
    if(previous!==key)detail.replaceChildren();
    if(goTab('course',options)===false){selected=previous;return false;}
    if(!options.restore)detail.querySelector('h2')?.focus({preventScroll:true});return true;
  }
  window.CourseLibrary={render,renderDetail,open,recordOpened,loadActivity,currentKey:()=>selected};
  loadActivity();
})();
