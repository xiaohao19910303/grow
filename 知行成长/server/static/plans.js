/* Plan UI uses DOM text nodes; model output is never interpreted as executable HTML. */
(() => {
  'use strict';
  const root = document.getElementById('view-plans');
  let navigation = 0;
  const node = (tag, text, cls) => { const n=document.createElement(tag); if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n; };
  const uuid = () => crypto.randomUUID();
  const canonical = x => JSON.stringify(x, (_, value) => value && !Array.isArray(value) && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(k=>[k,value[k]])) : value);
  async function api(path, data) {
    const r=await fetch('/api/plans'+path,{method:data===undefined?'GET':'POST',cache:'no-store',headers:{'Content-Type':'application/json','X-Copilot-Request':'1'},body:data===undefined?undefined:JSON.stringify({data})});
    const d=await r.json();if(!r.ok)throw new Error(typeof d.message==='string'?d.message:'请求未完成，请检查输入或重新读取。');return d;
  }
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
    ++navigation;root.oninput=null;root.replaceChildren();root.append(node('h2',title));const status=node('p','','desc');status.setAttribute('role','status');root.append(status);
    return status;
  }
  function markdown(parent,text){const p=node('div',undefined,'cp-reader');parent.append(p);window.renderLearningMarkdown(p,text);return p;}
  function briefFields(parent,b={}) {
    const box=node('div',undefined,'plan-grid');parent.append(box);
    const fields={title:field(box,'学习方向',b.title),goal:field(box,'希望学会什么',b.goal),level:field(box,'当前基础',b.level||'零基础'),weeks:field(box,'周期（周）',b.weeks||8,'number'),sessions:field(box,'每周学习次数',b.sessions||5,'number'),minutes:field(box,'每次分钟数',b.minutes||20,'number')};
    return ()=>Object.fromEntries(Object.entries(fields).map(([k,e])=>[k,['weeks','sessions','minutes'].includes(k)?Number(e.value):e.value]));
  }
  function refresh(){window.loadDailyLearning?.();}
  window.loadPlans=async()=>{
    const status=shell('学习计划');const turn=navigation;
    button(root,'创建学习计划',()=>create(),true);
    button(root,'检查未完成保存',async()=>{await api('/recover',{});toast('检查完成');await window.loadPlans();});
    button(root,'完整学习备份',async()=>{
      if(!confirm('请先停止自动任务和外部编辑写入。已停止并准备备份全部学习模块与平台数据库？'))return;
      const d=await api('/backup',{writers_stopped:true});status.textContent='备份已保存：'+d.path;
    });
    try{
      const data=await api('');if(turn!==navigation)return;
      status.textContent=data.generation_unavailable||('AI 模型：'+data.model+'；点击生成才会调用，可能产生费用。');
      const budget=node('details');budget.append(node('summary','每周总时间预算'));root.append(budget);
      budget.append(node('p',`已登记投入 ${data.budget.known_minutes} 分钟/周${data.budget.legacy_unknown?'；旧模块投入尚未登记':''}。新增计划默认不启用定时任务。`));
      const limit=field(budget,'总预算（分钟/周，留空为未知）',data.budget.weekly,'number');
      const legacy=field(budget,'旧模块合计投入（分钟/周，留空为未知）',data.budget.legacy_weekly,'number');
      button(budget,'保存预算',async()=>{await api('/budget',{weekly:limit.value===''?null:Number(limit.value),legacy_weekly:legacy.value===''?null:Number(legacy.value)});await window.loadPlans();});
      for(const p of data.plans){const card=node('section',undefined,'section');card.append(node('h3',p.name));card.append(node('p',`${p.id} · 规划v${p.version} · ${p.status==='active'?'学习中':'已暂停'} · ${p.lessons.length}课已保存`));button(card,'查看计划',()=>detail(p.id));root.append(card);}
      if(!data.plans.length)root.append(node('p','尚无新计划，可先手动填写，也可以让AI起草。'));
      const old=node('details');old.append(node('summary','原有学习模块（原目录保留）'));root.append(old);
      for(const p of data.legacy)button(old,p.name,()=>goTab(p.id==='renzhi'?'copilot':'library'));
      if(data.drafts.length){const drafts=node('details');drafts.append(node('summary','已保存草稿'));root.append(drafts);for(const d of [...data.drafts].reverse())button(drafts,`${d.created_at} · ${d.kind==='plan'?'规划':'课程'} · ${d.state}`,async()=>{const value=await api('/drafts/'+d.id);if(value.kind==='plan')await editPlan(value);else courseEditor(value);});}
      if(data.attempts.length){const attempts=node('details');attempts.append(node('summary','最近生成记录'));root.append(attempts);for(const a of [...data.attempts].reverse())button(attempts,`${a.created_at} · ${a.kind==='plan'?'规划':'课程'} · ${a.state}`,()=>watch(a.id));}
    }catch(e){status.textContent=e.message;}
  };
  function create(existing=null){
    shell(existing?'调整后续规划':'创建学习计划');button(root,'返回计划列表',window.loadPlans);
    const getBrief=briefFields(root,existing?.current.brief);
    root.append(node('p','发送内容：以上学习条件。修订时还包含原规划和你在下面明确选择的反馈；不会读取其他个人笔记。','desc'));
    const selected=[];
    for(const f of existing?.feedback||[]){const label=node('label',undefined,'plan-field');const check=node('input');check.type='checkbox';label.append(check,document.createTextNode(`第${f.lesson_no}课：${f.comment||f.state}`));root.append(label);selected.push([check,f.lesson_no]);}
    const args=()=>({brief:getBrief(),plan_id:existing?.plan.id||null,base_version:existing?.plan.version||0,feedback_lessons:selected.filter(([c])=>c.checked).map(([,n])=>n)});
    button(root,'让AI生成规划草稿',async()=>{const a=await api('/generate',{...args(),kind:'plan',key:uuid()});await watch(a.id);},true);
    button(root,'手动编写规划',()=>{
      const b=getBrief();const count=b.weeks*b.sessions;
      if(!Number.isInteger(count)||count<1||count>364)throw new Error('请先填写有效的周期与次数。');
      const doc=existing?.current.document||{prerequisites:'',stages:[{title:'',goal:''}],lessons:Array.from({length:count},(_,i)=>({number:i+1,topic:'',goal:'',exercise:'',assessment:'',stage:1,kind:i===count-1?'review':'lesson',minutes:b.minutes,requires:[]}))};
      editPlan({...args(),document:doc,external_hash:existing?.external.changed?existing.external.hash:null},existing);
    });
  }
  async function editPlan(d,existing=null){
    if(d.plan_id&&!existing)existing=await api('/'+d.plan_id);
    shell(d.plan_id?'预览与修订规划':'编辑规划草稿');button(root,'返回计划列表',window.loadPlans);
    const getBrief=briefFields(root,d.brief);const prereq=field(root,'先修说明',d.document.prerequisites,'textarea');
    if(existing){const old=node('details');old.append(node('summary','原规划与外部修改（核对差异）'));root.append(old);markdown(old,existing.external.content);if(existing.external.changed)old.append(node('p','检测到外部修改。手动核对并采用后会留存该版本原文，不能跳过核对。'));}
    const stages=node('div');root.append(stages);stages.append(node('h3','阶段目标'));const stageEditors=[];
    function addStage(s={title:'',goal:''}){const row=node('div',undefined,'section');stageEditors.push({title:field(row,'阶段名称',s.title),goal:field(row,'阶段目标',s.goal,'textarea')});stages.append(row);}
    d.document.stages.forEach(addStage);button(stages,'添加阶段',()=>addStage());
    const lessons=node('div');root.append(lessons);lessons.append(node('h3','逐课安排'));const editors=[];
    function addLesson(l){const box=node('details');box.append(node('summary',`第${editors.length+1}课 · ${l.topic||'待填写'}`));lessons.append(box);
      const e={};for(const [k,label] of [['topic','主题'],['goal','学习目标'],['exercise','练习'],['assessment','自查标准']])e[k]=field(box,label,l[k]||'',k==='topic'?'text':'textarea');
      e.stage=field(box,'所属阶段序号',l.stage||1,'number');e.minutes=field(box,'分钟数',l.minutes||d.brief.minutes,'number');e.requires=field(box,'先修课号（逗号分隔，可留空）',(l.requires||[]).join(','));
      const label=node('label','课型：');const select=node('select');for(const [v,t] of [['lesson','新知识'],['review','复盘']]){const o=node('option',t);o.value=v;select.append(o);}select.value=l.kind||'lesson';label.append(select);box.append(label);e.kind=select;editors.push(e);
      if(existing?.lessons.some(x=>x.lesson_no===editors.length)){box.append(node('p','已发布课次，安排冻结。'));box.querySelectorAll('input,textarea,select').forEach(x=>x.disabled=true);}
    }
    d.document.lessons.forEach(addLesson);button(lessons,'增加一课',()=>addLesson({}));button(lessons,'移除最后一课',()=>{if(editors.length<=(existing?.lessons.length||0))throw new Error('不能删除已发布课次。');editors.pop();lessons.querySelector('details:last-of-type')?.remove();});
    const acknowledge=node('label');const check=node('input');check.type='checkbox';acknowledge.append(check,document.createTextNode(existing?.external.changed?'已核对外部修改和所有规划差异':'已核对阶段目标、课次数量和时间安排'));root.append(acknowledge);
    const getDoc=()=>({prerequisites:prereq.value,stages:stageEditors.map(e=>({title:e.title.value,goal:e.goal.value})),lessons:editors.map((e,i)=>({number:i+1,...Object.fromEntries(['topic','goal','exercise','assessment','kind'].map(k=>[k,e[k].value])),stage:Number(e.stage.value),minutes:Number(e.minutes.value),requires:e.requires.value.trim()?e.requires.value.split(/[,，]/).map(Number):[]}))});
    button(root,'保存草稿并预览',async()=>{const doc=getDoc();const saved=await api('/drafts',{brief:getBrief(),document:doc,plan_id:d.plan_id||null,base_version:d.base_version||0,external_hash:existing?.external.changed?existing.external.hash:null});
      d=saved;toast('草稿已保存');preview.replaceChildren();const b=getBrief();preview.append(node('p',`${b.weeks}周 × 每周${b.sessions}次，每次${b.minutes}分钟；共${doc.lessons.length}课。`));for(const s of doc.stages)preview.append(node('p',s.title+'：'+s.goal));
      if(existing){const original=existing.current.document.lessons;const changes=doc.lessons.filter((x,i)=>canonical(x)!==canonical(original[i]));preview.append(node('p','与原规划不同的课次：'+(changes.map(x=>x.number).join('、')||'无')));}
      button(preview,'确认采用这份已保存草稿',async()=>{if(!check.checked)throw new Error('请先核对规划并勾选确认。');
        let result;try{result=await api('/drafts/'+saved.id+'/adopt',{key:saved.id+':adopt',accept_over:false});}catch(e){if(!e.message.includes('预算')||!confirm(e.message+' 仍然采用并接受超额？'))throw e;result=await api('/drafts/'+saved.id+'/adopt',{key:saved.id+':over',accept_over:true});}
        refresh();await detail(result.plan_id);
      },true);
    },true);
    const preview=node('section',undefined,'section');root.append(preview);root.oninput=(event)=>{if(event.target!==check)preview.replaceChildren(node('p','规划已修改，请重新保存草稿并预览。'));};
  }
  async function detail(pid){
    const status=shell('计划详情');const turn=navigation;const data=await api('/'+pid);if(turn!==navigation)return;
    root.querySelector('h2').textContent=data.plan.name;status.textContent=pid+' · 当前版本 v'+data.plan.version;
    button(root,'返回列表',window.loadPlans);button(root,'调整后续规划',()=>create(data));
    button(root,'修改显示名称',async()=>{const name=prompt('新的显示名称',data.plan.name);if(name){await api('/'+pid+'/metadata',{name,key:uuid()});await detail(pid);refresh();}});
    button(root,data.plan.status==='active'?'暂停计划':'恢复计划',async()=>{await api('/'+pid+'/metadata',{status:data.plan.status==='active'?'paused':'active',key:uuid()});await detail(pid);});
    const plan=node('details');plan.append(node('summary','查看当前规划'));root.append(plan);markdown(plan,data.external.content);
    if(data.external.changed)root.append(node('p','本地规划文件已修改。请在“调整后续规划 → 手动编写规划”核对并导入。'));
    const versions=node('details');versions.append(node('summary','规划历史版本'));root.append(versions);for(const v of data.versions)versions.append(node('p',`v${v.version} · ${v.created_at} · ${v.brief.title} · ${v.document.lessons.length}课`));
    const next=data.lessons.length+1;root.append(node('h3',`下一课：第${next}课`));
    button(root,'准备本课资料',()=>sourceEditor(pid),true);
    button(root,'生成下一课草稿',async()=>{const a=await api('/generate',{kind:'course',plan_id:pid,key:uuid()});await watch(a.id);},true);
    for(const l of data.lessons){const row=node('div',undefined,'todo-row');row.append(node('span',`第${l.lesson_no}课 ${l.topic} · ${l.learning_label}`));button(row,'阅读',()=>window.openPlanCourse(pid,l.lesson_no));root.append(row);}
  }
  async function sourceEditor(pid){
    const data=await api('/'+pid+'/sources');shell(`第${data.lesson_no}课：准备参考资料`);button(root,'返回计划',()=>detail(pid));
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
  async function watch(id){
    const status=shell('生成记录');const turn=navigation;button(root,'返回计划列表',window.loadPlans);button(root,'取消生成',async()=>{await api('/attempts/'+id+'/cancel',{});});
    const content=node('div',undefined,'cp-reader');root.append(content);
    async function poll(){try{const a=await api('/attempts/'+id);if(turn!==navigation)return;status.textContent=`${a.state} · ${a.model} · 费用：${a.cost==null?'未知':a.cost.toFixed(4)+'元'}${a.error?' · '+a.error:''}`;
      if(a.kind==='plan'){try{const doc=JSON.parse(a.raw);content.replaceChildren();const summary=node('div');summary.append(node('p',`${doc.lessons.length}课 · ${doc.stages.length}阶段`));content.append(summary);for(const s of doc.stages){const sec=node('section');sec.append(node('h3',s.title||'未命名阶段'));sec.append(node('p',s.goal||''));content.append(sec);}const lessons=node('details');lessons.append(node('summary',`逐课安排 (${doc.lessons.length}课)`));content.append(lessons);doc.lessons.forEach((l,i)=>{const row=node('div');row.style.cssText='padding:8px;border-bottom:1px solid var(--border)';row.append(node('strong',`第${l.number}课：${l.topic||'待填写'}`));row.append(node('p',l.goal||''));lessons.append(row);});}catch(_){content.replaceChildren(node('pre',a.raw));}}else{content.replaceChildren();markdown(content,a.raw||'');}
      if(['queued','generating'].includes(a.state)){setTimeout(poll,1500);return;}
      if(a.draft_id)button(root,'打开草稿',async()=>{const d=await api('/drafts/'+a.draft_id);if(d.kind==='plan')await editPlan(d);else courseEditor(d);},true);
      else if(a.kind==='plan'&&a.raw){button(root,'手动修正规划',()=>{let doc;try{doc=JSON.parse(a.raw);}catch(_){throw new Error('输出不是完整规划，请返回创建页手动填写或显式重新生成。');}return editPlan({...a.context,document:doc});});}
    }catch(e){if(turn===navigation)status.textContent=e.message;}}
    await poll();
  }
  function courseEditor(d){
    shell('课程草稿');button(root,'返回计划',()=>detail(d.context.plan_id));
    const content=field(root,'课程正文',d.content,'textarea');content.rows=18;const sources=field(root,'参考资料摘要',d.sources,'textarea');sources.rows=10;
    const preview=node('section');root.append(preview);
    button(root,'保存修改并预览',async()=>{d=await api('/drafts/'+d.id+'/edit-course',{content:content.value,sources:sources.value});if(d.state!=='ready')throw new Error('正文、引用或章节校验未通过，请检查课号、日期、分隔与必填章节。');preview.replaceChildren();markdown(preview,d.content);markdown(preview,d.sources);button(preview,'确认保存正式课程',async()=>{const result=await api('/drafts/'+d.id+'/publish',{key:d.id+':publish'});toast('已保存：'+result.path);refresh();await detail(result.plan_id);},true);},true);
  }
  window.openPlanCourse=async(pid,n)=>{
    rememberLearningOrigin();goTab('reader',{reading:true});const reader=document.getElementById('dailyReader');reader.hidden=false;reader.replaceChildren(node('p','正在读取…'));
    try{const d=await api('/'+pid+'/lessons/'+n);reader.replaceChildren();button(reader,'返回学习列表',returnFromLesson);markdown(reader,d.content);const source=node('details');source.append(node('summary','参考资料与边界'));reader.append(source);markdown(source,d.sources);
      const comment=field(reader,'本课反馈（可选，填写后保存；不会自动发送给AI）','','textarea');
      button(reader,'本人确认学完',async()=>{await api('/'+pid+'/lessons/'+n+'/feedback',{key:uuid(),state:'completed',comment:comment.value});d.lesson.learning_state='completed';toast('已记录本人反馈');refresh();},true);
      button(reader,'保存反馈，暂不标记完成',async()=>{await api('/'+pid+'/lessons/'+n+'/feedback',{key:uuid(),state:d.lesson.learning_state,comment:comment.value});toast('反馈已保存');});
    }catch(e){reader.replaceChildren(node('p',e.message));button(reader,'返回学习列表',returnFromLesson);}
  };
})();
