/* Private feedback and a cached Chinese guide, using only this browser's model. */
(() => {
  'use strict';
  const values={insightful:'有启发',neutral:'一般',not_for_me:'不感兴趣'};
  const levels={easy:'轻松',right:'合适',hard:'吃力'};
  const hasFeedback=a=>{const f=a.feedback||{};return !!(f.value||f.difficulty||f.takeaway||f.question||f.action||f.tags?.length);};
  function feedbackLabel(a){const f=a.feedback||{};return [values[f.value],levels[f.difficulty],...(f.tags||[])].filter(Boolean).join(' · ');}

  function feedback(parent,a,{api,node,button,field,onSaved,isCurrent}){
    const initial=a.feedback||{};let version=initial.version||0,saving=false;
    parent.append(node('h3','阅读反馈'),node('p','记下真正有用的内容，方便以后检索、复习和应用。价值反馈会轻微影响后续选文，同时保留不同主题。','desc'));
    const row=node('div',undefined,'reading-feedback-grid');parent.append(row);
    function select(label,options,value){const wrap=node('label',label,'plan-field'),input=node('select');
      for(const [key,text] of [['','暂不评价'],...Object.entries(options)]){const option=node('option',text);option.value=key;input.append(option);}
      input.value=value||'';wrap.append(input);row.append(wrap);return input;}
    const value=select('这篇对我的价值',values,initial.value),difficulty=select('阅读难度',levels,initial.difficulty);
    const takeaway=field(parent,'一句话收获',initial.takeaway||'','textarea');takeaway.rows=3;takeaway.maxLength=4000;takeaway.placeholder='这篇改变了我的什么看法？用自己的话说清楚。';
    const extra=node('details');extra.append(node('summary','补充疑问、应用行动和标签'));parent.append(extra);
    const question=field(extra,'我仍有的疑问',initial.question||'','textarea');question.rows=2;question.maxLength=2000;
    const action=field(extra,'准备怎么用',initial.action||'','textarea');action.rows=2;action.maxLength=2000;action.placeholder='例如：下次开会先讲结论，再给两个证据。';
    const tags=field(extra,'回查标签（用逗号分隔）',(initial.tags||[]).join('，'));tags.placeholder='例如：决策、沟通、AI、社会观察';
    const get=()=>({value:value.value,difficulty:difficulty.value,takeaway:takeaway.value.trim(),question:question.value.trim(),action:action.value.trim(),tags:tags.value.split(/[,，]/).map(t=>t.trim()).filter(Boolean)});
    let baseline=JSON.stringify(get());const status=node('p','','desc');status.setAttribute('role','status');parent.append(status);
    const controls=node('div',undefined,'reading-actions');parent.append(controls);const buttons=[];
    async function save(markRead){if(saving)return;saving=true;buttons.forEach(b=>b.disabled=true);const submitted=get();status.textContent='正在保存反馈…';
      try{const saved=await api('/articles/'+a.id+'/feedback',{...submitted,version,mark_read:markRead});if(!isCurrent())return;
        version=saved.feedback.version;baseline=JSON.stringify(submitted);onSaved(saved);
        status.textContent=(markRead?'反馈已保存，已标记读完。':'反馈已保存。')+(JSON.stringify(get())!==baseline?'后续输入仍未保存。':'可用标签、收获或疑问搜索找回。');
      }catch(e){if(isCurrent())status.textContent=e.message+' 输入已保留。';throw e;}
      finally{saving=false;buttons.forEach(b=>b.disabled=false);}}
    buttons.push(button(controls,'保存反馈并标记读完',()=>save(true),true),button(controls,'仅保存反馈',()=>save(false)));
    return ()=>JSON.stringify(get())!==baseline;
  }

  function guide(parent,a,data,{api,node,button,markdown,isCurrent,onSaved}){
    parent.append(node('h3','中文导读与核心观点'));
    const status=node('p','','desc');status.setAttribute('role','status');parent.append(status);
    const body=node('div',undefined,'article-guide');parent.append(body);
    let ready=a.guide_version==='reading-v2',running=false,jobId=null;
    if(ready&&data.guide)markdown(body,data.guide);
    else{body.append(node('p','中文导读会帮你先抓住主旨、核心观点与证据边界，再结合原文提高阅读能力。'));
      if(data.guide){const old=node('details');old.append(node('summary','查看已有导读与来源摘要'));markdown(old,data.guide);body.append(old);}}
    const actions=node('div',undefined,'reading-actions');parent.append(actions);
    const generate=button(actions,ready?'更新中文导读':'生成中文导读',()=>start(false),true);
    const cancel=button(actions,'取消生成',async()=>{if(jobId)await api('/jobs/'+jobId+'/cancel',{});});cancel.hidden=true;
    parent.append(node('p','仅将本篇文章资料发送给你配置的模型，可能产生费用。生成结果保存后可直接复用；个人笔记和反馈不会发送。','desc'));
    async function start(automatic,existing){
      if(running)return;
      const missing=existing?null:AIConfig.status();if(missing){status.textContent=missing;return;}
      running=true;generate.disabled=true;cancel.hidden=false;status.textContent='正在生成中文导读与核心观点…';
      try{const sourceHash=a.hashes?.['认知阅读/文章资料/'+a.id+'/原文.md']?.slice(0,16)||'summary';
        const key=automatic?'auto-guide-v2-'+a.id+'-'+sourceHash:crypto.randomUUID();
        let job=existing||await (window.ReadingTasks?window.ReadingTasks.start(a.id,'guide',{key,guide_format:'reading-v2'},a.zh_title||a.title):api('/articles/'+a.id+'/guide',{key,guide_format:'reading-v2'}));jobId=job.id;
        if(window.ReadingTasks)job=await window.ReadingTasks.wait(job,j=>{if(isCurrent())status.textContent=(j.phase||'正在生成中文导读…')+' 可切换页面，右下角生成任务会保留进度。';});
        while(['queued','running'].includes(job.state)){
          if(!isCurrent())return;
          status.textContent=job.phase||'正在生成中文导读…';
          await new Promise(resolve=>setTimeout(resolve,1500));
          job=await api('/jobs/'+job.id);
        }
        if(!isCurrent())return;
        if(job.state!=='ready')throw new Error(job.error||'导读未生成完成，可手动重试。');
        const fresh=await api('/articles/'+a.id);if(!isCurrent())return;
        body.replaceChildren();markdown(body,fresh.guide);ready=true;onSaved(fresh.article);
        generate.textContent='更新中文导读';status.textContent='中文导读已保存，下次打开可直接阅读。';
      }catch(e){if(isCurrent())status.textContent=e.message+' 原有文章和输入仍保留，可点击按钮重试。';}
      finally{running=false;generate.disabled=false;cancel.hidden=true;}
    }
    const existing=window.ReadingTasks?.find(a.id,'guide');
    if(existing)start(false,existing);
    else if(a.language==='en'&&!ready&&data.reading_preferences?.auto_guide){
      if(AIConfig.status()){
        status.textContent='配置个人模型后，再次打开英文文章即可自动生成中文导读。';
        button(actions,'配置个人模型',()=>window.AISetup?window.AISetup.open():goTab('settings'));
      }else queueMicrotask(()=>{if(isCurrent())start(true);});
    }
  }
  window.ReadingGrowth={hasFeedback,feedbackLabel,feedback,guide};
})();
