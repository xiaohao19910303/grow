/* Plan UI uses DOM text nodes; model output is never interpreted as executable HTML. */
(() => {
  'use strict';
  const root = document.getElementById('view-plans');
  let navigation = 0;
  const node = (tag, text, cls) => { const n=document.createElement(tag); if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n; };
  const uuid = () => crypto.randomUUID();
  const canonical = x => JSON.stringify(x, (_, value) => value && !Array.isArray(value) && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(k=>[k,value[k]])) : value);
  async function api(path, data) {
    if(data!==undefined && (path==='/generate'||/^\/drafts\/[^/]+\/refine$/.test(path))) data={...data,ai_config:AIConfig.require()};
    const r=await fetch('/api/plans'+path,{method:data===undefined?'GET':'POST',cache:'no-store',headers:{'Content-Type':'application/json','X-Copilot-Request':'1','X-Grow-Action-Schema':'2'},body:data===undefined?undefined:JSON.stringify({data})});
    let d;try{d=await r.json();}catch{throw new Error(r.ok?'返回的数据暂时无法读取，请重试。':`服务暂时无法完成请求（${r.status}），请稍后重试。`);}
    if(!r.ok)throw new Error(typeof d.message==='string'?d.message:typeof d.detail==='string'?d.detail:'请求未完成，请检查输入或重新读取。');
    if(data!==undefined && /\/lessons\/\d+\/feedback$/.test(path))await window.refreshLearningCompletion?.(d);
    if(d.id&&d.state&&['plan','course'].includes(d.kind)&&(path==='/generate'||path.startsWith('/attempts/')||/^\/drafts\/[^/]+\/refine$/.test(path)))trackGeneration(d);
    if(/^\/drafts\/[^/]+$/.test(path)&&d.id)window.GenerationTasks?.forget('plans:'+d.id);
    if(data!==undefined)window.PlanActions?.refresh();
    return d;
  }
  function planTask(a){const context=a.context;return window.GenerationTasks?.external('plans',a,{label:a.kind==='plan'?'学习计划生成':'计划课程生成',...(context?.brief?.title?{title:context.brief.title+(context.lesson?' · 第 '+context.lesson.number+' 课':' · 规划草稿')}:{})});}
  function trackGeneration(a){if(window.GenerationTasks)window.GenerationTasks.track(planTask(a));}
  function button(parent,label,action,primary=false) {
    const b=node('button',label,'btn'+(primary?' primary':''));b.type='button';
    b.onclick=async()=>{b.disabled=true;try{await action();}catch(e){toast(e.message);const status=root.querySelector('[role="status"]');if(status)status.textContent=e.message;}finally{b.disabled=false;}};
    parent.append(b);return b;
  }
  function field(parent,label,value='',type='text') {
    const wrap=node('label',label,'plan-field');const input=node(type==='textarea'?'textarea':'input');
    if(type!=='textarea')input.type=type;input.value=value??'';wrap.append(input);parent.append(wrap);return input;
  }
  function shell(title) {
    if(!leave())throw new Error('已保留未保存的输入。');
    ++navigation;page=null;route(null);root.oninput=null;root.onchange=null;root.replaceChildren();root.append(node('h2',title));const status=node('p','','desc');status.setAttribute('role','status');root.append(status);
    return status;
  }
  function markdown(parent,text){const p=node('div',undefined,'cp-reader');parent.append(p);window.renderLearningMarkdown(p,text);return p;}
  function githubLink(parent,label,url){
    if(!url)return;let parsed;try{parsed=new URL(url);}catch(_){return;}
    if(parsed.protocol!=='https:'||parsed.hostname!=='github.com')return;
    const a=node('a',label,'btn');a.href=parsed.href;a.target='_blank';a.rel='noopener noreferrer';parent.append(a);
  }
  function briefFields(parent,b={}) {
    const box=node('div',undefined,'plan-grid');parent.append(box);
    const fields={title:field(box,'学习方向',b.title),goal:field(box,'希望学会什么',b.goal),level:field(box,'当前基础',b.level||'零基础'),weeks:field(box,'周期（周）',b.weeks||8,'number'),sessions:field(box,'每周学习次数',b.sessions||5,'number'),minutes:field(box,'每次分钟数',b.minutes||20,'number')};
    return ()=>Object.fromEntries(Object.entries(fields).map(([k,e])=>[k,['weeks','sessions','minutes'].includes(k)?Number(e.value):e.value]));
  }
  async function generateAndWatch(body){const turn=navigation;const a=await api('/generate',body);if(turn===navigation&&root.style.display!=='none')await watch(a.id);else observe(a.id);}
  function refresh(){window.loadDailyLearning?.({force:true});}
  window.loadPlans=async()=>{
    const status=shell('课程规划');const turn=navigation;
    root.append(node('p','规划学什么、课程结构和下一课；具体哪天、几点学习，可在课程中安排到行动日程。','desc'));
    button(root,'创建课程规划',()=>create(),true);
    button(root,'检查未完成保存',async()=>{await api('/recover',{});toast('检查完成');await window.loadPlans();});
    const backupButton=button(root,'完整学习备份',async()=>{
      if(!confirm('请先停止自动任务和外部编辑写入。已停止并准备备份全部学习模块与平台数据库？'))return;
      const d=await api('/backup',{writers_stopped:true});status.textContent='备份已保存：'+d.path;
    });
    try{
      const data=await api('');if(turn!==navigation)return;
      if(data.storage==='github'){
        backupButton.hidden=true;
        root.append(node('p','正式课程保存在 GitHub；学习反馈保存在云端数据库。','desc'));
      }
      if(data.pending_publications?.length)root.append(node('p',`有 ${data.pending_publications.length} 项保存尚未完成。请点击“检查未完成保存”重试；草稿仍然保留。`,'desc'));
      status.textContent=data.generation_unavailable||AIConfig.status()||('AI 模型：'+AIConfig.read().model_name+'；点击生成才会调用，可能产生费用。');
      if(AIConfig.status())window.AISetup?.entry(root);
      button(root,'完成与进度说明',()=>window.showCompletionHelp?.());
      const budget=node('details');budget.append(node('summary','每周总时间预算'));root.append(budget);
      budget.append(node('p',`已登记投入 ${data.budget.known_minutes} 分钟/周${data.budget.legacy_unknown?'；旧模块投入尚未登记':''}。新增计划默认不启用定时任务。`));
      const limit=field(budget,'总预算（分钟/周，留空为未知）',data.budget.weekly,'number');
      const legacy=field(budget,'旧模块合计投入（分钟/周，留空为未知）',data.budget.legacy_weekly,'number');
      button(budget,'保存预算',async()=>{await api('/budget',{weekly:limit.value===''?null:Number(limit.value),legacy_weekly:legacy.value===''?null:Number(legacy.value)});await window.loadPlans();});
      for(const p of data.plans){const card=node('section',undefined,'section');card.append(node('h3',p.name));card.append(node('p',`${p.id} · 规划v${p.version} · ${p.status==='active'?'学习中':'已暂停'} · ${p.lessons.length}课已保存`));button(card,'查看计划',()=>detail(p.id));root.append(card);}
      if(!data.plans.length)root.append(node('p','尚无新计划，可先手动填写，也可以让AI起草。'));
      const old=node('details');old.append(node('summary','原有学习模块（原目录保留）'));root.append(old);
      for(const p of data.legacy)button(old,p.name,()=>goTab(p.id==='renzhi'?'copilot':'library'));
      if(data.drafts.length){const drafts=node('details');drafts.append(node('summary','已保存草稿'));root.append(drafts);for(const d of [...data.drafts].reverse())button(drafts,`${d.created_at} · ${d.kind==='plan'?'规划':'课程'} · ${stateLabel[d.state]||'已保存'}`,async()=>{const value=await api('/drafts/'+d.id);await previewDraft(value.id);});}
      for(const a of data.attempts)if(['queued','generating'].includes(a.state))observe(a.id);
      if(data.attempts.length){const attempts=node('details');attempts.append(node('summary','最近生成记录'));root.append(attempts);for(const a of [...data.attempts].reverse())button(attempts,`${a.created_at} · ${a.kind==='plan'?'规划':'课程'} · ${stateLabel[a.state]||a.state}`,()=>watch(a.id));}
    }catch(e){status.textContent=e.message;}
  };
  function create(existing=null){
    shell(existing?'调整后续规划':'创建课程规划');button(root,'返回计划列表',window.loadPlans);
    const getBrief=briefFields(root,existing?.current.brief);
    root.append(node('p','发送内容：以上学习条件。修订时还包含原规划和你在下面明确选择的反馈；不会读取其他个人笔记。','desc'));
    const selected=[];
    for(const f of existing?.feedback||[]){const label=node('label',undefined,'plan-field');const check=node('input');check.type='checkbox';label.append(check,document.createTextNode(`第${f.lesson_no}课：${f.comment||f.state}`));root.append(label);selected.push([check,f.lesson_no]);}
    const args=()=>({brief:getBrief(),plan_id:existing?.plan.id||null,base_version:existing?.plan.version||0,feedback_lessons:selected.filter(([c])=>c.checked).map(([,n])=>n)});
    button(root,'让AI生成规划草稿',async()=>{await generateAndWatch({...args(),kind:'plan',key:uuid()});},true);
    button(root,'手动编写规划',()=>{
      const b=getBrief();const count=b.weeks*b.sessions;
      if(!Number.isInteger(count)||count<1||count>364)throw new Error('请先填写有效的周期与次数。');
      const doc=existing?.current.document||{prerequisites:'',stages:[{title:'',goal:''}],lessons:Array.from({length:count},(_,i)=>({number:i+1,topic:'',goal:'',exercise:'',assessment:'',stage:1,kind:i===count-1?'review':'lesson',minutes:b.minutes,requires:[]}))};
      editPlan({...args(),document:doc,external_hash:existing?.external.changed?existing.external.hash:null},existing);
    });
  }
  async function editPlan(d,existing=null){
    shell('编辑学习规划');page={kind:'edit',id:d.id};const turn=navigation;
    if(d.plan_id&&!existing){existing=await api('/'+d.plan_id);if(turn!==navigation)return;}
    const frozen=new Set(existing?.lessons.map(x=>x.lesson_no)||d.frozen_lessons||[]);
    button(root,d.id?'放弃修改并返回预览':'返回创建',()=>d.id?previewDraft(d.id):create(existing));
    const getBrief=briefFields(root,d.brief);const prereq=field(root,'先修说明',d.document.prerequisites,'textarea');
    if(existing?.external.changed){const external=node('details');external.append(node('summary','规划文件存在外部修改，请核对'));markdown(external,existing.external.content);root.append(external);}
    const stageBox=node('section');root.append(stageBox);stageBox.append(node('h3','阶段目标'));const stages=[];
    const lessonBox=node('section');root.append(lessonBox);lessonBox.append(node('h3','逐课安排'));const editors=[];
    const mapping=node('p','','desc');root.append(mapping);
    function addStage(value={title:'',goal:''}){
      const row=node('div',undefined,'section');const e={row,title:field(row,'阶段名称',value.title),goal:field(row,'阶段目标',value.goal,'textarea')};stages.push(e);stageBox.append(row);
      button(row,'删除此阶段',()=>{const i=stages.indexOf(e)+1;if(editors.some(x=>Number(x.stage.value)===i))throw new Error('请先把该阶段课次移到其他阶段，再删除。');if(editors.some((x,n)=>frozen.has(n+1)&&Number(x.stage.value)>i))throw new Error('删除会改变已发布课次的阶段序号，不能删除。');stages.splice(i-1,1);row.remove();for(const l of editors)if(Number(l.stage.value)>i)l.stage.value=Number(l.stage.value)-1;mapping.textContent='阶段已重新编号，受影响课次的所属阶段同步更新。';});
    }
    d.document.stages.forEach(addStage);button(stageBox,'添加阶段',()=>addStage());
    function updateNumbers(){editors.forEach((e,i)=>{e.summary.textContent=`第${i+1}课 · ${e.topic.value||'待填写'}${frozen.has(i+1)?'（已发布）':''}`;lessonBox.append(e.box);});}
    function readRequires(e){return e.requires.value.trim()?e.requires.value.split(/[,，]/).map(Number):[];}
    function move(e,delta){const old=[...editors],from=old.indexOf(e),to=from+delta;
      if(to<0||to>=old.length||frozen.has(from+1)||frozen.has(to+1))throw new Error('只能移动未发布课次。');
      const reordered=[...old];reordered.splice(from,1);reordered.splice(to,0,e);const map=new Map(old.map((x,i)=>[i+1,reordered.indexOf(x)+1]));
      const mapped=reordered.map(x=>readRequires(x).map(n=>map.get(n)));
      if(mapped.some((arr,i)=>arr.some(n=>!n||n>=i+1)))throw new Error('移动后先修课会位于本课之后，请先调整先修关系。');
      if(reordered.some((x,i)=>frozen.has(i+1)&&canonical(mapped[i])!==canonical(readRequires(x))))throw new Error('不能改变已发布课次的先修关系。');
      editors.splice(0,editors.length,...reordered);editors.forEach((x,i)=>x.requires.value=mapped[i].join(','));updateNumbers();mapping.textContent='本次课号映射：'+[...map].filter(([a,b])=>a!==b).map(([a,b])=>`原第${a}课 → 第${b}课`).join('；')+'。先修课号已同步更新。';
    }
    function addLesson(l={}){
      const box=node('details');const summary=node('summary');box.append(summary);const e={box,summary};
      for(const [k,label] of [['topic','主题'],['goal','学习目标'],['exercise','练习'],['assessment','自查标准']])e[k]=field(box,label,l[k]||'',k==='topic'?'text':'textarea');
      e.stage=field(box,'所属阶段序号',l.stage||1,'number');e.minutes=field(box,'分钟数',l.minutes||d.brief.minutes,'number');e.requires=field(box,'先修课号（逗号分隔，可留空）',(l.requires||[]).join(','));
      const label=node('label','课型');e.kind=node('select');for(const [v,t] of [['lesson','新知识'],['review','复盘']]){const o=node('option',t);o.value=v;e.kind.append(o);}e.kind.value=l.kind||'lesson';label.append(e.kind);box.append(label);editors.push(e);
      button(box,'上移一课',()=>move(e,-1));button(box,'下移一课',()=>move(e,1));
      if(frozen.has(editors.length)){box.querySelectorAll('input,textarea,select,button').forEach(x=>x.disabled=true);}
      updateNumbers();
    }
    d.document.lessons.forEach(addLesson);
    const controls=node('div');root.append(controls);button(controls,'增加一课',()=>addLesson());button(controls,'移除最后一课',()=>{if(!editors.length||frozen.has(editors.length))throw new Error('不能删除已发布课次。');editors.pop().box.remove();});
    const getDoc=()=>({prerequisites:prereq.value,stages:stages.map(e=>({title:e.title.value,goal:e.goal.value})),lessons:editors.map((e,i)=>({number:i+1,...Object.fromEntries(['topic','goal','exercise','assessment','kind'].map(k=>[k,e[k].value])),stage:Number(e.stage.value),minutes:Number(e.minutes.value),requires:readRequires(e)}))});
    const initial=canonical({brief:getBrief(),document:getDoc()});dirtyCheck=()=>canonical({brief:getBrief(),document:getDoc()})!==initial;
    const ack=existing?.external.changed?field(root,'已核对规划文件的外部修改，允许导入并保留原文','','checkbox'):null;
    button(root,'保存草稿并预览',async()=>{const turn=navigation;if(ack&&!ack.checked)throw new Error('请先核对规划文件的外部修改。');const saved=await api('/drafts',{brief:getBrief(),document:getDoc(),plan_id:d.plan_id||null,base_version:d.base_version||0,external_hash:ack?existing.external.hash:null,...(d.id?{parent_draft_id:d.id,parent_hash:d.content_hash}:{})});if(turn===navigation){dirtyCheck=null;await previewDraft(saved.id);}else toast('草稿已保存，可从计划列表查看。');},true);
  }
  async function detail(pid){
    const status=shell('计划详情');status.textContent='正在读取课程规划…';const turn=navigation;const data=await api('/'+pid);if(turn!==navigation)return;
    root.querySelector('h2').textContent=data.plan.name;status.textContent=pid+' · 当前版本 v'+data.plan.version;
    window.PlanActions?.mount(root,pid);
    button(root,'返回列表',window.loadPlans);button(root,'调整后续规划',()=>create(data));
    button(root,'修改显示名称',async()=>{const name=prompt('新的显示名称',data.plan.name);if(name){await api('/'+pid+'/metadata',{name,key:uuid()});await detail(pid);refresh();}});

    // 状态管理按钮组
    const statusActions=node('div',undefined,'plan-status-actions');
    root.append(statusActions);

    const currentStatus=data.plan.status||'active';
    if(currentStatus==='active'){
      button(statusActions,'暂停计划',async()=>{
        if(!confirm('确定要暂停此课程规划？'))return;
        await api('/'+pid+'/metadata',{status:'paused',key:uuid()});
        toast('计划已暂停');
        await detail(pid);
      },false,'pause');
      button(statusActions,'归档计划',async()=>{
        if(!confirm('确定要归档此课程规划？归档后将不再显示在活跃列表中。'))return;
        await api('/'+pid+'/metadata',{status:'archived',key:uuid()});
        toast('计划已归档');
        await detail(pid);
      },false,'archive');
    }else if(currentStatus==='paused'){
      button(statusActions,'恢复计划',async()=>{
        await api('/'+pid+'/metadata',{status:'active',key:uuid()});
        toast('计划已恢复');
        await detail(pid);
      },true,'resume');
      button(statusActions,'归档计划',async()=>{
        if(!confirm('确定要归档此课程规划？'))return;
        await api('/'+pid+'/metadata',{status:'archived',key:uuid()});
        toast('计划已归档');
        await detail(pid);
      },false,'archive');
    }else if(currentStatus==='archived'){
      button(statusActions,'恢复计划',async()=>{
        await api('/'+pid+'/metadata',{status:'active',key:uuid()});
        toast('计划已恢复');
        await detail(pid);
      },true,'resume');
    }

    // 加载状态历史
    loadStatusHistory(pid);

    const plan=node('details');plan.append(node('summary','查看当前规划'));root.append(plan);markdown(plan,data.external.content);
    githubLink(plan,'在 GitHub 打开规划',data.github_url);
    if(data.external.changed)root.append(node('p','规划文件已被外部修改。请在”调整后续规划 → 手动编写规划”核对并导入。'));
    const versions=node('details');versions.append(node('summary','规划历史版本'));root.append(versions);for(const v of data.versions)versions.append(node('p',`v${v.version} · ${v.created_at} · ${v.brief.title} · ${v.document.lessons.length}课`));
    const next=data.lessons.length+1;root.append(node('h3',`下一课：第${next}课`));
    button(root,'准备本课资料',()=>sourceEditor(pid),true);
    button(root,'生成下一课草稿',async()=>{await generateAndWatch({kind:'course',plan_id:pid,key:uuid()});},true);
    for(const l of data.lessons){const row=node('div',undefined,'todo-row');row.append(node('span',`第${l.lesson_no}课 ${l.topic} · ${l.learning_label}`));button(row,'阅读',()=>window.openPlanCourse(pid,l.lesson_no));root.append(row);}
  }

  // 加载并展示状态历史
  async function loadStatusHistory(planId){
    try{
      const response=await fetch(`/api/plans/${planId}/status-history`);
      if(!response.ok)throw new Error('加载状态历史失败');
      const data=await response.json();
      renderStatusHistory(data.history||[]);
    }catch(error){
      console.error('Status history error:',error);
    }
  }

  function renderStatusHistory(history){
    if(!history||history.length===0)return;
    const historyBox=node('div',undefined,'plan-status-history');
    historyBox.append(node('h4','状态变更历史'));
    const timeline=node('div',undefined,'plan-status-timeline');
    historyBox.append(timeline);

    const statusLabels={active:'学习中',paused:'已暂停',archived:'已归档'};

    history.forEach(event=>{
      const eventEl=node('div',undefined,'plan-status-event');
      const dateStr=event.changed_at?event.changed_at.replace('T',' ').substring(0,16):'';
      eventEl.append(node('div',dateStr,'plan-status-event-date'));
      const fromLabel=statusLabels[event.from_status]||event.from_status||'初始';
      const toLabel=statusLabels[event.to_status]||event.to_status;
      eventEl.append(node('div',`${fromLabel} → ${toLabel}`,'plan-status-event-label'));
      if(event.reason){
        eventEl.append(node('div',event.reason,'plan-status-event-note'));
      }
      timeline.append(eventEl);
    });

    root.append(historyBox);
  }
  async function sourceEditor(pid){
    const status=shell('准备参考资料');const turn=navigation;button(root,'返回计划',()=>detail(pid));const loading=window.LoadingState?.start(root,'正在读取参考资料…','正在读取已保存的备课材料。');
    let data;try{data=await api('/'+pid+'/sources');}finally{loading?.finish();}if(turn!==navigation)return;root.querySelector('h2').textContent=`第${data.lesson_no}课：准备参考资料`;
    const help=node('details');help.open=true;help.append(node('summary','什么是备课资料？（点击展开说明）'));
    help.append(node('p','备课资料是 AI 生成课程时的参考材料。你可以指定一本书、给一个网页链接、或直接粘贴相关内容。','desc'));
    help.append(node('p','如果不想手动准备，可以直接返回点击"生成下一课草稿"，AI 会使用默认资料。','desc'));
    root.append(help);
    const items=node('div');root.append(items);const editors=[];
    function add(value={}){const box=node('section',undefined,'section');items.append(box);box.append(node('h4','资料条目'));
      const title=field(box,'标题（书名/文章名/主题）',value.title||'');
      const content=field(box,'内容（链接、书名、或粘贴相关资料）',value.content||'','textarea');
      content.rows=6;editors.push({title,content});button(box,'移除',()=>{editors.splice(editors.indexOf(editors[editors.length-1]),1);box.remove();});}
    (data.entries.length?data.entries:[{}]).forEach(add);button(root,'增加资料',()=>add());
    button(root,'保存',async()=>{await api('/'+pid+'/sources',{entries:editors.map(e=>({title:e.title.value,content:e.content.value}))});await detail(pid);},true);
  }
  const observers=new Map();
  let page=null, dirtyCheck=null;
  const stateLabel={queued:'已提交',generating:'正在生成',waiting:'正在等待 AI 返回内容',receiving:'正在生成内容',validating:'正在检查完整性',ready:'生成完成',failed:'生成未完成',cancelled:'已取消'};
  const fieldLabels={topic:'主题',goal:'学习目标',exercise:'练习',assessment:'自查',minutes:'分钟数',stage:'所属阶段',kind:'课型',requires:'先修课号',brief:'学习条件',document:'规划',lessons:'课次',stages:'阶段',prerequisites:'先修说明',title:'名称',level:'基础',weeks:'周数',sessions:'每周次数',plan_id:'计划',base_version:'基线版本',overrides:'外部修改'};
  const labelPath=path=>path.replace('规划/document/','规划/').split('/').map(x=>fieldLabels[x]||x).join(' / ');
  function hasDirty(){return !!dirtyCheck?.();}
  function leave(){
    if(hasDirty()&&!confirm('还有未保存的修改。离开会丢弃这些输入，确定离开？'))return false;
    dirtyCheck=null;for(const o of observers.values()){o.auto=false;o.left=true;};return true;
  }
  window.beforePlansLeave=name=>{if(!leave())return false;++navigation;page=null;if(name!=='plans'&&location.hash.startsWith('#plans/'))route(null);return true;};
  window.addEventListener('beforeunload',e=>{if(hasDirty()){e.preventDefault();e.returnValue='';}});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)for(const o of observers.values()){o.auto=false;o.left=true;};});
  const route=(kind,id)=>history.replaceState(null,'',kind?'#plans/'+kind+'/'+encodeURIComponent(id):location.pathname+location.search);
  window.enterPlans=()=>{
    const m=location.hash.match(/^#plans\/(attempt|draft)\/([\w-]+)$/);
    return m?(m[1]==='attempt'?watch(m[2]):previewDraft(m[2])):window.loadPlans();
  };
  window.addEventListener('hashchange',()=>{if(location.hash.startsWith('#plans/'))goTab('plans');});
  function foreground(id){return page?.kind==='attempt'&&page.id===id&&root.style.display!=='none'&&!document.hidden;}
  function notifyResult(a){
    if(window.GenerationTasks){trackGeneration(a);return;}
    const box=node('aside',undefined,'plan-notice');box.setAttribute('role','status');
    box.append(node('span',a.state==='ready'?'你的学习草稿已生成，可以查看预览。':(a.error||stateLabel[a.state])));
    button(box,a.draft_id?'查看草稿':'查看生成记录',async()=>{if(!leave())return;route(a.draft_id?'draft':'attempt',a.draft_id||a.id);goTab('plans');box.remove();});
    button(box,'关闭',()=>box.remove());document.body.append(box);
  }
  function observe(id,view=null,auto=false){
    let o=observers.get(id);
    if(o){o.view=view;o.auto=auto&&!o.left; if(o.last&&view)view(o.last);return o;}
    o={id,view,auto,revision:-1,delay:1500,last:null};observers.set(id,o);
    async function poll(){
      try{
        const a=await api('/attempts/'+id+'/progress?after_revision='+o.revision);
        o.delay=1500;o.revision=a.revision;
        o.last={...a,preview:a.preview||o.last?.preview};
        if(foreground(id))o.view?.(o.last);
        if(['queued','generating'].includes(a.state)){o.timer=setTimeout(poll,foreground(id)?o.delay:10000);return;}
        if(o.auto&&foreground(id)&&a.state==='ready'&&a.draft_id&&!hasDirty()){
          o.auto=false;await previewDraft(a.draft_id);
        }else if(!foreground(id)){notifyResult(a);}
      }catch(e){
        o.delay=Math.min(o.delay*2,15000);
        if(foreground(id))root.querySelector('[role="status"]').textContent='暂时无法读取进度，正在重新连接；不会重复生成。';
        o.timer=setTimeout(poll,o.delay);
      }
    }
    poll();return o;
  }
  async function watch(id){
    const status=shell('正在准备你的学习内容');route('attempt',id);page={kind:'attempt',id};
    button(root,'返回计划列表',window.loadPlans);
    const cancel=button(root,'取消生成',async()=>{
      try{
        await api('/attempts/'+id+'/cancel',{});
        toast('已取消生成');
        status.textContent='已取消生成';
        cancel.disabled=true;
        cancel.textContent='已取消';
        cancel.hidden=false;
        setTimeout(()=>window.loadPlans(),1500);
      }catch(e){
        toast('取消失败：'+e.message);
      }
    });
    const clock=node('p','','desc');root.append(clock);
    const note=node('p','内容会逐步显示。完整生成并通过检查后才能正式保存。','desc');root.append(note);
    const content=node('div',undefined,'plan-stream');content.setAttribute('aria-label','生成中的内容');root.append(content);
    const follow=button(root,'回到最新内容',()=>{following=true;content.scrollTop=content.scrollHeight;follow.hidden=true;});follow.hidden=true;
    let following=true,rendered='',opened=false;
    content.addEventListener('scroll',()=>{following=content.scrollHeight-content.scrollTop-content.clientHeight<48;follow.hidden=following;});
    const actions=node('div');root.append(actions);
    const details=node('details');details.append(node('summary','生成详情'));root.append(details);const info=node('p');details.append(info);
    button(details,'查看原始输出（排查用）',async()=>{const a=await api('/attempts/'+id);let pre=details.querySelector('pre');if(!pre){pre=node('pre');details.append(pre);}pre.textContent=a.raw||'尚未收到内容。';});
    const render=a=>{
      status.textContent=stateLabel[a.phase]||stateLabel[a.state]||'正在处理';
      const active=['queued','generating'].includes(a.state);cancel.hidden=!active;
      clock.textContent=`已用时 ${Math.floor(a.elapsed_seconds/60)}分${a.elapsed_seconds%60}秒${active&&a.idle_seconds>=20?' · 暂无新内容，AI 可能仍在准备；可以继续等待或取消。':''}`;
      info.textContent=`模型：${a.model} · 费用：${a.cost==null?'未提供用量或单价，无法计算':a.cost.toFixed(4)+'元'} · ${a.error||'输出完成后会进行结构检查'}`;
      const p=a.preview||{};let entries=[];
      if(p.type==='plan')entries=[...(p.stages||[]).map((x,i)=>({key:'s'+i,title:`阶段 ${i+1} · ${x.title}`,text:x.goal})),...(p.lessons||[]).map(x=>({key:'l'+x.number,title:`第${x.number}课 · ${x.topic}`,text:`${x.goal}\n练习：${x.exercise}\n自查：${x.assessment}\n${x.minutes}分钟`}))];
      else if(p.type==='course')entries=[{key:'body',title:'课程正文（生成中）',text:p.content},{key:'sources',title:'参考资料（生成中）',text:p.sources}].filter(x=>x.text);
      else if(p.type==='changes')entries=(p.items||[]).map((x,i)=>({key:'c'+i,title:x.number?'第'+x.number+'课调整':'章节调整',text:x.text||Object.entries(x.changes||{}).map(([k,v])=>(fieldLabels[k]||k)+'：'+(Array.isArray(v)?v.join('、'):v)).join('\n')}));
      if(canonical(entries)!==rendered){rendered=canonical(entries);const scroll=content.scrollTop;
        const wanted=new Set(entries.map(e=>e.key));for(const el of [...content.children])if(!wanted.has(el.dataset.key))el.remove();
        for(const e of entries){let el=[...content.children].find(x=>x.dataset.key===e.key);if(!el){el=node('section',undefined,'plan-stream-item');el.dataset.key=e.key;el.append(node('h3'),node('div',undefined,'plan-pending-text'));content.append(el);}el.children[0].textContent=e.title;el.children[1].textContent=e.text;}
        if(following)content.scrollTop=content.scrollHeight;else content.scrollTop=scroll;
      }
      note.textContent=active?(entries.length?'正在逐步补全。下面是预览片段，尚未正式保存。':'已经提交给 AI，首段内容到达后会在这里显示。'):(a.error||'已完成，可以阅读和调整草稿。');
      if(!active&&!opened){opened=true;
        if(a.draft_id)button(actions,a.state==='ready'?'查看生成预览':'检查并修正草稿',()=>previewDraft(a.draft_id),true);
        if(a.state==='failed'&&a.kind==='plan'&&!a.draft_id)button(actions,'检查完整输出并手动修正',async()=>{const failed=await api('/attempts/'+id);if(!failed.complete||failed.operation==='refine')throw new Error('输出未完整结束或是局部调整，请保留原稿并重新调整。');let doc;try{doc=JSON.parse(failed.raw);}catch(_){throw new Error('输出不是完整JSON，请返回创建页手动填写。');}if(!Array.isArray(doc.stages)||!Array.isArray(doc.lessons)||doc.stages.some(x=>!x||typeof x!=='object')||doc.lessons.some(x=>!x||typeof x!=='object'))throw new Error('结构无法安全编辑，请返回创建页手动填写。');await editPlan({...failed.context,document:doc});});
        if(a.state!=='ready')button(actions,'重新生成一份',async()=>{const old=await api('/attempts/'+id);const ctx=old.context;let fresh;
          if(old.operation==='refine')fresh=await api('/drafts/'+ctx.parent.id+'/refine',{key:uuid(),parent_hash:ctx.parent_hash,instruction:ctx.instruction,scope:ctx.scope,...(old.kind==='plan'&&ctx.scope.mode==='all'?{brief:ctx.brief}:{})});
          else fresh=await api('/generate',{key:uuid(),kind:old.kind,...(old.kind==='plan'?ctx:{plan_id:ctx.plan_id})});
          await watch(fresh.id);
        });
      }
    };
    const o=observe(id,render,true);if(o.last&&!['queued','generating'].includes(o.last.state)){o.auto=false;render(o.last);}
  }
  async function previewDraft(id){
    const status=shell('生成预览');route('draft',id);page={kind:'draft',id};const turn=navigation;
    const d=await api('/drafts/'+id);if(turn!==navigation)return;
    status.textContent=(d.kind==='plan'?'学习规划':'课程')+' · '+(d.state==='published'?'已正式保存':d.state==='ready'?'草稿，尚未正式保存':'结构检查未通过，请直接编辑修正')+' · '+d.created_at;
    root.querySelector('h2').textContent=d.kind==='plan'?d.brief.title:'课程阅读预览';
    const actions=node('div',undefined,'plan-actions');root.append(actions);button(actions,'返回计划列表',window.loadPlans);
    const editable=!d.family_published&&d.state!=='published';
    if(editable){
      button(actions,'编辑草稿',()=>d.kind==='plan'?editPlan(d):courseEditor(d),true);
      if(d.state==='ready')button(actions,'告诉 AI 如何调整',()=>refineEditor(d));
    }
    if(d.kind==='plan'){
      root.append(node('p',`${d.brief.weeks}周 · 每周${d.brief.sessions}次 · 每次${d.brief.minutes}分钟 · 共${d.document.lessons.length}课`,'plan-summary'));
      if(d.budget)root.append(node('p',`每周已知总投入（含本规划）：${d.budget.known_minutes}分钟；预算：${d.budget.weekly??'未设置'}${d.budget.over?'；超出'+d.budget.over+'分钟':''}${d.budget.legacy_unknown?'；旧模块投入尚未登记':''}`,'desc'));
      root.append(node('p','学习目标：'+d.brief.goal),node('p','当前基础：'+d.brief.level),node('h3','先修说明'),node('p',d.document.prerequisites));
      d.document.stages.forEach((s,i)=>{const box=node('section',undefined,'plan-stage');box.append(node('h3',`阶段${i+1} · ${s.title}`),node('p',s.goal));root.append(box);});
      root.append(node('h3','逐课安排'));
      for(const l of d.document.lessons){const box=node('details');box.append(node('summary',`第${l.number}课 · ${l.topic} · ${l.minutes}分钟${d.frozen_lessons.includes(l.number)?' · 已发布，不能调整':''}`));box.append(node('p','目标：'+l.goal),node('p','练习：'+l.exercise),node('p','自查：'+l.assessment),node('p',`阶段${l.stage} · ${l.kind==='review'?'复盘':'新知识'} · 先修：${l.requires.join('、')||'无'}`));root.append(box);}
    }else{markdown(root,d.content);const notes=node('details');notes.open=true;notes.append(node('summary','参考资料与适用边界'));root.append(notes);notes.append(node('p','以下内容是 AI 整理的资料摘要。提供链接不等于已核实网页全文，请核对出处。','desc'));markdown(notes,d.sources);}
    if(d.parent_draft_id){
      const comparison=node('section',undefined,'section plan-comparison');comparison.append(node('h3','与上一版的实际变化'));root.append(comparison);
      if(!d.diff.length)comparison.append(node('p','内容没有变化。'));
      for(const change of d.diff){const box=node('details');box.append(node('summary',labelPath(change.path)));const pair=node('div',undefined,'plan-grid');for(const [label,value] of [['原版',change.before],['新版',change.after]]){const column=node('div');column.append(node('strong',label),node('pre',typeof value==='string'?value:JSON.stringify(value,null,2)));pair.append(column);}box.append(pair);comparison.append(box);}
      button(comparison,'返回原版',()=>previewDraft(d.parent_draft_id));comparison.append(node('p','当前选择的是这份新稿；查看和切换版本不会正式保存。','desc'));
    }
    const history=node('details');history.append(node('summary','本组草稿历史（可从旧版继续调整）'));root.append(history);const list=node('div');history.append(list);
    async function historyPage(offset){const h=await api('/drafts/'+id+'/history?offset='+offset);for(const x of h.items){const row=node('div',undefined,'plan-history');row.append(node('span',`${x.created_at} · ${{manual:'手动编辑',refine:'AI 调整',original:'原始草稿',redate:'确认新日期'}[x.operation]||'初稿'}${x.id===id?' · 当前查看':''}${x.parent_draft_id?' · 分支 '+x.parent_draft_id.slice(0,8):''}`));button(row,'查看此版',()=>previewDraft(x.id));if(x.instruction)row.append(node('p',x.instruction));list.append(row);}if(h.next_offset!==null){const more=button(list,'加载更多版本',async()=>{more.remove();await historyPage(h.next_offset);});}}
    await historyPage(0);if(turn!==navigation)return;
    if(d.family_published){root.append(node('p','本组已有正式保存的版本。可以查看历史内容；后续调整请从计划详情中的正式版本开始。'));return;}
    if(d.state!=='ready')return;
    const confirmBox=node('section',undefined,'section plan-confirm');root.append(confirmBox);
    if(d.kind==='course'&&d.context.date!==new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())){
      confirmBox.append(node('p','这份课程的日期已过期。确认后会保留原版，创建今天日期的新草稿。'));
      button(confirmBox,'确认改为今天日期并预览',async()=>{const child=await api('/drafts/'+id+'/redate',{parent_hash:d.content_hash,confirm_date:true});await previewDraft(child.id);},true);return;
    }
    const check=field(confirmBox,'已阅读这份草稿，确认将其正式保存','','checkbox');
    const linkActions=d.kind==='plan'?field(confirmBox,'同时关联到行动（不指定学习日期）','','checkbox'):null;if(linkActions)linkActions.checked=true;
    button(confirmBox,d.kind==='plan'?'采用这份规划':'保存正式课程',async()=>{
      const turn=navigation;if(!check.checked)throw new Error('请先阅读草稿并勾选确认。');let result;
      if(d.kind==='plan'){
        try{result=await api('/drafts/'+id+'/adopt',{key:id+':adopt',expected_hash:d.content_hash,accept_over:false,link_actions:!!linkActions?.checked});}
        catch(e){if(!e.message.includes('预算')||!confirm(e.message+' 仍然采用并接受超额？'))throw e;result=await api('/drafts/'+id+'/adopt',{key:id+':over',expected_hash:d.content_hash,accept_over:true,link_actions:!!linkActions?.checked});}
      }else result=await api('/drafts/'+id+'/publish',{key:id+':publish',expected_hash:d.content_hash});
      toast(result.learning_action_sync_error||(result.storage==='github'?'已提交 GitHub，可立即阅读；学习状态仍待本人记录。':'已正式保存；学习状态仍待本人记录。'));
      refresh();
      if(turn===navigation){
        await detail(result.plan_id);
        if(result.learning_action_sync_error&&turn+1===navigation){
          const warning=node('p',result.learning_action_sync_error);warning.setAttribute('role','status');root.prepend(warning);
        }
      }
    },true);
  }
  function refineEditor(d){
    shell('告诉 AI 如何调整');page={kind:'refine',id:d.id};root.append(node('p',`基线：${d.created_at} · 草稿 ${d.id.slice(0,8)}`,'desc'));
    root.append(node('p','以当前查看的草稿为基线。会发送这份草稿、明确选择的范围和你的意见；其他个人笔记不会自动发送。','desc'));
    button(root,'返回预览',()=>previewDraft(d.id));
    const instruction=field(root,'调整意见','','textarea');instruction.rows=4;
    for(const idea of ['更适合零基础，先用生活例子讲清概念','降低单次练习难度，保留学习目标','增加一个完整示范和明确自查标准'])button(root,idea,()=>{instruction.value=idea;ack.checked=false;update();});
    const select=node('select');const wrap=node('label','调整范围');wrap.className='plan-field';wrap.append(select);root.append(wrap);
    for(const [v,t] of [['selected',d.kind==='plan'?'只调整所选课次和字段':'只调整所选章节'],['all',d.kind==='plan'?'整份规划（已发布课次保留）':'整课正文与资料']]){const o=node('option',t);o.value=v;select.append(o);}
    const scopeBox=node('section');root.append(scopeBox);const choices=[],fields=[];
    if(d.kind==='plan'){
      scopeBox.append(node('h3','选择课次'));for(const l of d.document.lessons){const box=field(scopeBox,`第${l.number}课 · ${l.topic}${d.frozen_lessons.includes(l.number)?'（已发布）':''}`,'','checkbox');box.disabled=d.frozen_lessons.includes(l.number);choices.push([l.number,box]);}
      scopeBox.append(node('h3','允许修改的字段'));for(const k of ['topic','goal','exercise','assessment','minutes','stage','kind','requires'])fields.push([k,field(scopeBox,fieldLabels[k],'','checkbox')]);
    }else{
      for(const s of [...d.sections,{id:'sources',title:'参考资料摘要'}])choices.push([s.id,field(scopeBox,s.title,'','checkbox')]);
      if(!d.sections.length){select.value='all';select.options[0].disabled=true;root.append(node('p','章节边界无法明确定位，仅支持整课调整。'));}
    }
    const conditions=node('details');conditions.append(node('summary','整份调整时，显式修改学习条件（可选）'));root.append(conditions);
    const getBrief=d.kind==='plan'?briefFields(conditions,d.brief):null;
    const summary=node('p','','plan-summary');root.append(summary);const ack=field(root,'已核对下方发送概要，同意发送并生成新草稿','','checkbox');
    function selected(){return choices.filter(([,x])=>x.checked).map(([k])=>k);}
    function scope(){return select.value==='all'?{mode:'all'}:d.kind==='plan'?{mode:'selected',lessons:selected(),fields:fields.filter(([,x])=>x.checked).map(([k])=>k)}:{mode:'selected',sections:selected()};}
    function update(){scopeBox.hidden=select.value==='all';conditions.hidden=d.kind!=='plan'||select.value!=='all';summary.textContent=`发送：当前${d.kind==='plan'?'规划及学习条件':'课程正文、资料及本课备课内容'} + 调整意见。修改范围：${select.value==='all'?'全部未冻结内容':selected().length+'个课次/章节'+(d.kind==='plan'?'，字段：'+fields.filter(([,x])=>x.checked).map(([k])=>fieldLabels[k]).join('、'):'' )}。生成后先预览，不会自动正式保存。`;}
    root.oninput=e=>{if(e.target!==ack)ack.checked=false;update();};root.onchange=update;update();
    const initial=canonical({instruction:'',scope:scope(),brief:getBrief?.()});dirtyCheck=()=>canonical({instruction:instruction.value,scope:scope(),brief:getBrief?.()})!==initial;
    button(root,'按以上范围生成新稿',async()=>{
      if(!ack.checked)throw new Error('请核对发送范围并勾选确认。');const request={key:uuid(),parent_hash:d.content_hash,instruction:instruction.value,scope:scope()};if(getBrief&&select.value==='all')request.brief=getBrief();
      const turn=navigation;const a=await api('/drafts/'+d.id+'/refine',request);if(turn===navigation&&root.style.display!=='none'){dirtyCheck=null;await watch(a.id);}else observe(a.id);
    },true);
  }
  function courseEditor(d){
    shell('编辑课程草稿');page={kind:'edit',id:d.id};button(root,'放弃修改并返回预览',()=>previewDraft(d.id));
    root.append(node('p','保存后建立新版本，原稿保留。课号、日期和练习与参考分析之间的分隔线需保持正确。','desc'));
    const content=field(root,'课程正文',d.content,'textarea');content.rows=18;const sources=field(root,'参考资料摘要',d.sources,'textarea');sources.rows=10;
    dirtyCheck=()=>content.value!==d.content||sources.value!==d.sources;
    button(root,'保存修改并预览',async()=>{const turn=navigation;const saved=await api('/drafts/'+d.id+'/edit-course',{content:content.value,sources:sources.value,parent_hash:d.content_hash});if(turn===navigation){dirtyCheck=null;await previewDraft(saved.id);}else toast('草稿已保存，可从计划列表查看。');},true);
  }
  window.GenerationTasks?.register('plans',{
    read:async job=>planTask(await api('/attempts/'+job.ref+'/progress')),
    cancel:async job=>planTask(await api('/attempts/'+job.ref+'/cancel',{})),
    open:async job=>{if(goTab('plans')===false)return false;return job.draft_id?previewDraft(job.draft_id):watch(job.ref);}
  });
  window.addEventListener('load',async()=>{if(location.hash.startsWith('#plans/'))goTab('plans');else try{const data=await api('');for(const a of data.attempts){trackGeneration(a);if(['queued','generating'].includes(a.state))observe(a.id);}}catch(_){/* The plans page offers a manual retry. */}});
  window.openPlanCourse=async(pid,n)=>{
    rememberLearningOrigin();if(goTab('reader',{reading:true})===false)return;const turn=window.studyReaderRequest;const reader=document.getElementById('dailyReader');reader.hidden=false;reader.replaceChildren();const loading=window.LoadingState?.start(reader,'正在读取课程规划课程…','正在读取课程正文与个人反馈。');
    try{const [d,detail]=await Promise.all([api('/'+pid+'/lessons/'+n),api('/'+pid)]);const version=await window.StudyNotes.contentVersion(d.content);if(turn!==window.studyReaderRequest)return;reader.replaceChildren();button(reader,(window.lessonReturnLabel?.() || '返回我的课程'),returnFromLesson);githubLink(reader,'在 GitHub 打开课程',d.github_url);const content=markdown(reader,d.content);const source=node('details');source.append(node('summary','参考资料与边界'));reader.append(source);githubLink(source,'在 GitHub 打开参考资料',d.sources_github_url);markdown(source,d.sources);
      const feedback=detail.feedback.find(item=>item.lesson_no===n);
      const notes=window.StudyNotes.mount({parent:reader,content,kind:'plan',course:pid+'/'+n,version,seedNotes:feedback?.comment||''});
      const status=node('p',d.lesson.learning_state==='completed'?'本课已完成；修改笔记不会改变完成状态。':'本课尚未完成；笔记与答案可先暂存。','desc');notes.form.insertBefore(status,notes.status);
      button(notes.actions,'本人确认学完',async()=>{await notes.flush();await api('/'+pid+'/lessons/'+n+'/feedback',{key:uuid(),state:'completed',comment:feedback?.comment||'',...(window.actionContentOrigin?.target?.kind==='plan'&&window.actionContentOrigin.target.plan_id===pid&&window.actionContentOrigin.target.lesson_no===n?{origin_action_id:window.actionContentOrigin.actionId}:{})});d.lesson.learning_state='completed';status.textContent='本课已完成，笔记与练习答案已独立暂存。';refresh();},true);
    }catch(e){if(turn!==window.studyReaderRequest)return;reader.replaceChildren(node('p',e.message));button(reader,(window.lessonReturnLabel?.() || '返回我的课程'),returnFromLesson);button(reader,'重试读取课程',()=>window.openPlanCourse(pid,n));}finally{loading?.finish();}
  };
  window.openLearningPlan=async pid=>{if(goTab('plans')===false)return false;await detail(pid);return true;};
})();
