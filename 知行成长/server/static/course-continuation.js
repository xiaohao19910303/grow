/* Private advice and editable continuation; only explicit actions call the model. */
(() => {
  'use strict';
  const states=new Map(),jobs=new Map();
  const n=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;};
  async function api(path='',body){
    const r=await fetch('/api/course-continuations'+path,{method:body?'POST':'GET',cache:'no-store',headers:body?{'Content-Type':'application/json','X-Copilot-Request':'1'}:{},body:body?JSON.stringify(body):undefined});
    const d=await r.json();if(!r.ok){const error=Error(d.message||d.detail||'接续请求暂未完成，请重试。');error.code=d.error||d.code;throw error;}return d;
  }
  function button(parent,text,action,primary=false){const b=n('button',text,'btn'+(primary?' primary':''));b.type='button';
    b.onclick=async()=>{b.disabled=true;try{await action();}catch(e){const status=parent.closest('.course-continuation')?.querySelector('[role="status"]');if(status){status.textContent=e.message;const s=[...states.values()].find(s=>s.node===status.closest('.course-continuation'));if(e.code==='conflict'&&s)offerRecheck(s);}else toast(e.message);}finally{b.disabled=false;}};parent.append(b);return b;}
  function field(parent,label,value='',type='text'){
    const wrap=n('label',label,'plan-field'),el=n(type==='textarea'?'textarea':'input');if(type!=='textarea')el.type=type;el.value=value??'';wrap.append(el);parent.append(wrap);return el;
  }
  function task(job){return window.GenerationTasks?.external('continuations',job,{kind:'course-advice',label:'学习接续建议',title:job.title,ref:job.id,course_key:job.course_key});}
  function track(job){jobs.set(job.id,job);if(window.GenerationTasks)window.GenerationTasks.track(task(job));}
  async function load(s){
    const version=s.viewVersion||0;
    const c=await api('?course_key='+encodeURIComponent(s.key));
    // A delayed refresh must not replace a direction the user has just opened or edited.
    if((s.viewVersion||0)!==version)return;
    s.context=c;
    if(s.session&&s.session.snapshot!==c.snapshot){s.session=null;s.id=null;s.planKey=null;s.adviceKey=null;s.nextKey=null;s.refs.clear();}
    if(!s.session)s.session=c.session?.snapshot===c.snapshot?c.session:null;
    if(!s.dirty&&s.session?.form)s.form=s.session.form;
    return c;
  }
  function mount(parent,key,options={}){
    let s=states.get(key);
    if(!s){s={key,node:n('section',undefined,'course-continuation section'),form:null,session:null,dirty:false,refs:new Set()};states.set(key,s);}
    parent.append(s.node);
    if(!s.loaded||options.refresh){const version=s.viewVersion||0;s.loaded=true;if(!s.context)s.node.replaceChildren(n('h3','下一步学什么'),n('p','正在核对课程进度…','desc'));load(s).then(()=>{if((s.viewVersion||0)===version)draw(s);}).catch(e=>{if((s.viewVersion||0)!==version)return;s.node.replaceChildren(n('h3','下一步学什么'),n('p',e.message,'desc'));button(s.node,'重试读取学习接续',()=>{s.loaded=false;mount(parent,key);});});}
    return s.node;
  }
  async function save(s){
    clearTimeout(s.timer);
    if(s.saving){await s.saving;if(!s.dirty)return s.session;}
    const form=s.inputs?readForm(s):s.form;
    const sent=JSON.stringify(form),id=s.session?.id||s.id||(s.id=crypto.randomUUID());
    s.saving=api('',{id,course_key:s.key,snapshot:s.context.snapshot,revision:s.session?.revision||0,form}).then(r=>{
      s.session=r;s.form=r.form;s.dirty=s.inputs?JSON.stringify(readForm(s))!==sent:false;
      if(s.status)s.status.textContent='填写内容已暂存；只有点击生成才会调用 AI。';return r;
    }).catch(e=>{s.dirty=true;if(s.status)s.status.textContent=e.message;if(e.code==='conflict')offerRecheck(s);throw e;}).finally(()=>{s.saving=null;});
    return s.saving;
  }
  function offerRecheck(s){
    if(s.node.querySelector('.continuation-recheck'))return;
    const box=n('div',undefined,'continuation-recheck');s.node.append(box);
    button(box,'重新核对课程与填写',async()=>{
      const local=s.inputs?readForm(s):s.form;s.session=null;await load(s);const remote=s.session?.form;
      s.form=local||remote;s.dirty=false;draw(s);form(s);s.dirty=JSON.stringify(local)!==JSON.stringify(remote);
      if(remote){const compare=n('details');compare.append(n('summary','云端当前填写（供核对）'),n('pre',JSON.stringify(remote,null,2)));s.body.append(compare);
        button(compare,'采用云端填写',()=>{s.form=remote;s.dirty=false;form(s);});}
      s.status.textContent='课程与云端版本已重新读取；当前输入保留。核对后可暂存或采用云端填写。';
    });
  }
  function privateChoices(s,parent){
    const box=n('details');box.append(n('summary','本次参考的私人记录（可选）'));parent.append(box);
    box.append(n('p','默认仅参考课程内容。选中记录只用于本次私人建议，不自动进入正式规划或正文。','desc'));
    for(const item of s.context.private_choices||[]){const label=n('label',undefined,'continuation-check'),input=n('input');input.type='checkbox';input.checked=s.refs.has(item.ref);
      input.onchange=()=>{s.adviceKey=null;input.checked?s.refs.add(item.ref):s.refs.delete(item.ref);};label.append(input,document.createTextNode(item.label));box.append(label);}
    if(!s.context.private_choices?.length)box.append(n('p','暂无可选私人记录。','desc'));
  }
  function draw(s){
    if(s.dirty&&s.inputs)return;
    s.node.replaceChildren(n('h3','下一步学什么'));s.inputs=null;
    s.status=n('p','','desc');s.status.setAttribute('role','status');s.node.append(s.status);
    const c=s.context;
    if(c.session&&c.session.snapshot!==c.snapshot&&!s.session){s.node.append(n('p','来源课程已有更新。旧接续记录仍保留，请核对当前课程后重新填写。','desc'));}
    if(c.related?.length){const related=n('div',undefined,'course-actions');s.node.append(related);for(const r of c.related)button(related,'关联课程：'+r.name,()=>window.CourseLibrary.open(r.course_key));}
    if(c.status!=='active'){s.status.textContent='课程已暂停或归档；恢复后可继续生成。';return;}
    const actions=n('div',undefined,'course-actions');s.node.append(actions);
    if(c.next_lesson)button(actions,'继续下一课',async()=>{await window.loadDailyLearning();const m=window.DailyLearning.snapshot().modules.find(m=>CourseCatalog.key(m)===s.key);if(m)await window.DailyLearning.read(m,m.lessons.find(l=>l.lesson_no===c.next_lesson.lesson_no));},true);
    else button(actions,c.total&&!c.can_extend?'按原规划生成下一课':'直接生成下一课',()=>direct(s),true);
    button(actions,'给我学习建议',()=>newDirection(s,false));button(actions,'自己填写方向',()=>newDirection(s,true));
    if(s.session?.new_plan_id){
      s.status.textContent='下一阶段规划已保存；可以准备第一课或打开新课程。';
      button(actions,'打开下一阶段课程',async()=>{await window.loadDailyLearning({force:true});window.CourseLibrary.open('plan:'+s.session.new_plan_id);});
      if(!c.child_published)button(actions,'生成第一课',()=>first(s.node,s.session.id));return;
    }
    const body=n('div',undefined,'continuation-body');s.body=body;s.node.append(body);
    privateChoices(s,body);
    if(s.session?.plan_attempt_id){button(body,'查看已生成的规划',()=>window.watchLearningPlanAttempt(s.session.plan_attempt_id));}
    if(s.session?.advice_job_id){if(!s.form)watchAdvice(s,s.session.advice_job_id);else button(body,'查看上次学习建议',()=>watchAdvice(s,s.session.advice_job_id));}
    if(s.form)form(s);
  }
  async function newDirection(s,manual){
    if(s.session?.new_plan_id){s.session=null;s.id=crypto.randomUUID();s.form=null;s.inputs=null;s.dirty=false;s.refs.clear();s.planKey=null;s.adviceKey=null;await save(s);draw(s);}
    return manual?form(s):suggest(s);
  }
  async function direct(s){
    s.viewVersion=(s.viewVersion||0)+1;
    if(s.key.startsWith('plan:')){
      s.nextKey ||= crypto.randomUUID();
      try{const job=await api('/next',{course_key:s.key,key:s.nextKey,ai_config:AIConfig.require()});s.nextKey=null;await window.watchLearningPlanAttempt(job.id);}
      catch(e){if(e.code==='sources')sourceForm(s.node,entries=>directWithSources(s,entries));throw e;}
      return;
    }
    if(s.key==='renzhi'){
      const panel=n('div');s.node.append(panel);s.status.textContent='正在核对认知课程下一课的主题与资料…';
      const response=await fetch('/api/copilot/today-task',{cache:'no-store'}),data=await response.json();
      if(!response.ok)throw Error(data.message||'课程暂不可用。');
      const blockers=data.blockers||[];
      if(blockers.length){s.status.textContent=blockers.map(b=>b.message).join('；');const draft=blockers.find(b=>b.draft_id);if(draft)button(panel,'预览已有草稿',()=>window.openGeneratedCopilotDraft(draft.draft_id));button(panel,'核对主题与参考资料',()=>goTab('copilot'));return;}
      if(goTab('copilot')!==false)await window.generateNextCognitiveLesson(data.next_generation_lesson);
      return;
    }
    const module=window.DailyLearning.snapshot().modules.find(m=>m.id===s.key);
    if(!module)throw Error('请刷新课程后重试。');
    let panel=s.node.querySelector('.continuation-direct');if(!panel){panel=n('div',undefined,'continuation-direct');s.node.append(panel);window.renderStudyGeneration(panel,module);}
    // The same click is explicit authorization to submit this one course generation.
    const generate=[...panel.querySelectorAll('button')].find(b=>['生成下一课','重新生成下一课'].includes(b.textContent));if(generate)generate.click();
  }
  async function directWithSources(s,entries){const job=await api('/next',{course_key:s.key,key:s.nextKey||(s.nextKey=crypto.randomUUID()),entries,ai_config:AIConfig.require()});await window.watchLearningPlanAttempt(job.id);}
  async function suggest(s){
    if(s.inputs)await save(s);else if(!s.session)await save(s);
    s.adviceKey ||= crypto.randomUUID();s.status.textContent='正在提交学习建议…';
    const job=await api('/'+s.session.id+'/suggest',{key:s.adviceKey,selected_refs:[...s.refs],ai_config:AIConfig.require()});
    s.session.advice_job_id=job.id;track(job);watchAdvice(s,job.id);
  }
  async function watchAdvice(s,id){
    clearTimeout(s.poll);
    try{
      const job=await api('/jobs/'+encodeURIComponent(id));track(job);
      if(['queued','generating'].includes(job.state)){s.status.textContent='学习建议生成中，可离开页面，稍后回来查看。';s.poll=setTimeout(()=>watchAdvice(s,id),1800);return;}
      if(job.state==='ready'){s.viewedAdvice=job;showAdvice(s,job.options);}
      else{s.status.textContent=job.error||'建议生成未完成。';s.adviceKey=null;button(s.body,'重试生成学习建议',()=>suggest(s));}
    }catch(e){s.status.textContent=e.message+' 正在重连。';s.poll=setTimeout(()=>watchAdvice(s,id),5000);}
  }
  function showAdvice(s,options){
    if(s.inputs&&s.dirty){s.status.textContent='学习建议已生成，当前填写仍保留。';button(s.body,'查看学习建议',async()=>{await save(s);showAdvice(s,options);});return;}
    if(!s.body||!s.body.isConnected){s.body=n('div',undefined,'continuation-body');s.node.append(s.body);}
    const stale=s.viewedAdvice?.snapshot&&s.viewedAdvice.snapshot!==s.context.snapshot;
    s.body.replaceChildren(n('p','以下为私人学习建议；采用前可以修改目标和课数。','desc'));s.inputs=null;
    for(const option of options){const box=n('article',undefined,'continuation-option');box.append(n('h4',option.title),n('p',option.goal),n('p',option.reason,'desc'),n('p','建议 '+option.lesson_count+' 课 · 自由节奏','desc'));
      if(!stale)button(box,'选择并调整',()=>{if(s.viewedAdvice&&s.session?.id!==s.viewedAdvice.continuation_id){s.session=null;s.id=crypto.randomUUID();s.planKey=null;}s.form={...s.form,direction:option.title,goal:option.goal,learning_mode:option.mode,lesson_count:option.lesson_count};form(s);s.dirty=true;save(s).catch(()=>{});},true);s.body.append(box);}
    button(s.body,'我自己填写',()=>newDirection(s,true));s.status.textContent=stale?'这份建议的来源课程已变化，仅供回看；请基于当前课程重新生成。':'已生成巩固、应用、进阶三个方向。';
  }
  function readForm(s){return Object.fromEntries(Object.entries(s.inputs).map(([k,e])=>[k,['lesson_count','minutes'].includes(k)?Number(e.value):e.value]));}
  function form(s){
    s.viewVersion=(s.viewVersion||0)+1;
    s.body.replaceChildren();const values={direction:'',goal:'',scenario:'',difficulty:'',feeling:'',learning_mode:'apply',lesson_count:4,minutes:s.context.brief.minutes||15,...s.form};
    const fields=n('div',undefined,'plan-grid');s.body.append(fields);s.inputs={};
    for(const [key,label] of [['direction','接下来希望学什么？'],['goal','希望达到的目标（可选）'],['scenario','应用场景（可选）'],['difficulty','目前的困惑（可选）'],['feeling','学习感受（可选）']])s.inputs[key]=field(fields,label,values[key],key==='direction'?'text':'textarea');
    const modeLabel=n('label','学习方式','plan-field'),mode=n('select');for(const [v,t] of [['consolidate','巩固练习'],['apply','实际应用'],['advance','继续进阶']]){const o=n('option',t);o.value=v;mode.append(o);}mode.value=values.learning_mode;modeLabel.append(mode);fields.append(modeLabel);s.inputs.learning_mode=mode;
    s.inputs.lesson_count=field(fields,'总课数（2–12课）',values.lesson_count,'number');s.inputs.lesson_count.min=2;s.inputs.lesson_count.max=12;
    s.inputs.minutes=field(fields,'每课分钟数',values.minutes,'number');s.inputs.minutes.min=5;s.inputs.minutes.max=120;
    s.body.append(n('p','自由节奏，不自动安排学习日期。填写内容会作为规划生成条件；私人笔记只用于已勾选的建议请求。','desc'));
    fields.oninput=fields.onchange=()=>{s.viewVersion=(s.viewVersion||0)+1;s.dirty=true;s.planKey=null;s.adviceKey=null;clearTimeout(s.timer);s.timer=setTimeout(()=>save(s).catch(()=>{}),800);};
    const actions=n('div',undefined,'course-actions');s.body.append(actions);
    button(actions,'暂存填写',()=>save(s));button(actions,'生成建议规划',async()=>{
      if(!readForm(s).direction.trim())throw Error('请先填写接下来希望学什么。');
      await save(s);s.planKey ||= crypto.randomUUID();
      const job=await api('/'+s.session.id+'/plan',{key:s.planKey,ai_config:AIConfig.require()});
      s.planKey=null;
      if(job.adopted){await window.loadDailyLearning({force:true});window.CourseLibrary.open('plan:'+job.plan_id);return;}
      await window.watchLearningPlanAttempt(job.id);
    },true);
    button(actions,'返回学习建议',()=>{s.dirty=false;draw(s);});
    s.inputs.direction.focus({preventScroll:true});
  }
  function sourceForm(parent,retry){
    if(parent.querySelector('.continuation-sources'))return;
    const box=n('div',undefined,'continuation-sources');parent.append(box);box.append(n('h4','补充参考资料'),n('p','规划和已填写内容仍保留。可填写书名、资料链接或粘贴教学内容。','desc'));
    const title=field(box,'资料名称','补充学习资料'),content=field(box,'参考资料内容','','textarea');
    button(box,'补充资料并重试',()=>{if(!content.value.trim())throw Error('请填写参考资料内容。');return retry([{title:title.value,content:content.value}]);},true);
  }
  async function first(parent,id,entries){
    let status=parent.querySelector('.continuation-adoption-status');if(!status){status=n('p','','continuation-adoption-status');status.setAttribute('role','status');parent.append(status);}
    status.textContent='规划已保存，正在准备第一课草稿…';
    const s=[...states.values()].find(s=>s.session?.id===id),key=s?.firstKey||(s?s.firstKey=crypto.randomUUID():parent.dataset.firstKey||(parent.dataset.firstKey=crypto.randomUUID()));
    try{const job=await api('/'+id+'/first-lesson',{key,entries,ai_config:AIConfig.require()});
      if(s)s.firstKey=null;else delete parent.dataset.firstKey;
      if(job.published){await window.loadDailyLearning({force:true});window.CourseLibrary.open('plan:'+job.plan_id);return;}
      await window.watchLearningPlanAttempt(job.id);
    }catch(e){status.textContent='规划已保存，第一课尚未生成：'+e.message;
      if(e.code==='sources')sourceForm(parent,items=>first(parent,id,items));
      else button(parent,'重试生成第一课',()=>{if(s)s.firstKey=crypto.randomUUID();else parent.dataset.firstKey=crypto.randomUUID();return first(parent,id);});
    }
  }
  function planActions(parent,d,check){
    parent.append(n('p','这份规划和后续课程将保存到内容仓库，请核对目标和目录。原始私人笔记不会随规划发布。','desc'));
    button(parent,'调整规划',()=>window.editLearningPlanDraft(d.id));
    const adopt=async(start)=>{
      if(!check.checked)throw Error('请先阅读规划并勾选确认。');
      const result=await api('/'+d.continuation_id+'/adopt',{draft_id:d.id,expected_hash:d.content_hash});
      const s=[...states.values()].find(s=>s.session?.id===d.continuation_id);if(s)s.session={...s.session,new_plan_id:result.plan_id};
      await window.loadDailyLearning({force:true});
      if(start)await first(parent,d.continuation_id);else window.CourseLibrary.open('plan:'+result.plan_id);
    };
    button(parent,'仅保存规划',()=>adopt(false));button(parent,'采用规划并生成第一课',()=>adopt(true),true);
  }
  window.addEventListener('beforeunload',event=>{if([...states.values()].some(s=>s.dirty)){event.preventDefault();event.returnValue='';}});
  window.GenerationTasks?.register('continuations',{read:async job=>task(await api('/jobs/'+job.ref)),cancel:async job=>task(await api('/jobs/'+job.ref+'/cancel',{})),
    recover:async()=>{const d=await api('/jobs');return d.items.map(task);},open:async job=>{await window.loadDailyLearning();const key=job.course_key||jobs.get(job.ref)?.course_key;window.CourseLibrary.open(key);const s=states.get(key);if(s){await load(s);draw(s);await watchAdvice(s,job.ref);}}});
  window.CourseContinuation={mount,planActions,retryPlan:id=>api('/'+id+'/plan',{key:crypto.randomUUID(),ai_config:AIConfig.require()})};
})();
