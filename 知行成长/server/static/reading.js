/* Article discovery: safe DOM rendering and explicit model use. */
(() => {
  'use strict';
  const root=document.getElementById('view-reading');let revision=0,dirty=null;const watching=new Map();
  const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  const state={queued:'等待开始',running:'进行中',ready:'已完成',failed:'未完成',cancelled:'已取消'};
  const category={recent:'近期精选',classic:'经典重读',mixed:'近期＋经典'};
  async function api(path='',data){const r=await fetch('/api/reading'+path,{method:data===undefined?'GET':'POST',cache:'no-store',headers:{'Content-Type':'application/json','X-Copilot-Request':'1'},body:data===undefined?undefined:JSON.stringify({data})});const j=await r.json();if(!r.ok)throw new Error(j.message||'读取失败，请稍后重试。');return j;}
  function button(parent,label,action,primary=false){const b=node('button',label,'btn'+(primary?' primary':''));b.type='button';b.onclick=async()=>{b.disabled=true;try{await action();}catch(e){toast(e.message);root.querySelector('[role=status]').textContent=e.message;}finally{b.disabled=false;}};parent.append(b);return b;}
  function field(parent,label,value='',type='text'){const wrap=node('label',label,'plan-field');const input=node(type==='textarea'?'textarea':'input');if(type!=='textarea')input.type=type;input.value=value;wrap.append(input);parent.append(wrap);return input;}
  function select(parent,label,values,value){const wrap=node('label',label,'plan-field'),input=node('select');for(const [v,t] of values){const o=node('option',t);o.value=v;input.append(o);}input.value=value;wrap.append(input);parent.append(wrap);return input;}
  function leave(){if(dirty?.()&&!confirm('笔记有未保存的修改。确定放弃并离开？'))return false;dirty=null;++revision;return true;}
  window.beforeReadingLeave=name=>{if(!leave())return false;if(name!=='reading'&&location.hash.startsWith('#reading/'))history.replaceState(null,'',location.pathname+location.search);return true;};
  window.addEventListener('beforeunload',e=>{if(dirty?.()){e.preventDefault();e.returnValue='';}});
  function shell(title,kind,id){if(!leave())throw new Error('已保留未保存的笔记。');history.replaceState(null,'',kind?'#reading/'+kind+'/'+id:location.pathname+location.search);root.replaceChildren(node('h2',title));const status=node('p','','desc');status.setAttribute('role','status');root.append(status);return status;}
  function markdown(parent,text){const box=node('div',undefined,'cp-reader');window.renderLearningMarkdown(box,text);parent.append(box);}
  function original(parent,a){const link=node('a','阅读原文 ↗','btn');link.href=a.url;link.target='_blank';link.rel='noopener noreferrer';parent.append(link);}
  function card(a,parent){const box=node('article',undefined,'reading-card');box.append(node('span',`${category[a.category]} · ${a.language==='zh'?'中文':'英文'} · 热度未核实`,'reading-tag'),node('h3',a.zh_title||a.title));if(a.zh_title)box.append(node('p',a.title,'desc'));box.append(node('p',`${a.source} · ${a.author} · ${a.published_at||'日期未知'}`,'desc'),node('p',a.summary||'来源未提供摘要，建议阅读原文。'),node('p',a.reason||'已保存到个人阅读资料'),node('p',a.access,'desc'));parent.append(box);return box;}
  window.loadReading=async()=>{
    const status=shell('今日阅读');const turn=revision;button(root,'帮我找文章',()=>collectForm(),true);button(root,'阅读偏好与来源',()=>settings());
    const data=await api();if(turn!==revision)return;const p=data.preferences;
    status.textContent=`${p.enabled?'每天':'已暂停每日搜集'} 北京时间 ${String(p.hour).padStart(2,'0')}:${String(p.minute).padStart(2,'0')} · ${p.count}篇 · ${category[p.mode]}。本地服务需保持运行；每日搜集不调用付费模型。`;
    const today=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
    const daily=data.jobs.find(j=>j.daily&&j.date===today);const banner=node('section',undefined,'reading-banner');root.append(banner);banner.append(node('h3','今日精选'));
    if(daily){banner.append(node('p',state[daily.state]+(daily.error?' · '+daily.error:'')));button(banner,'查看今日结果',()=>watch(daily.id));}
    else{banner.append(node('p','今天尚无定时搜集结果，也可以现在手动搜集。'));button(banner,'按我的偏好搜集',()=>start(p),true);}
    const active=data.jobs.filter(j=>['queued','running'].includes(j.state));for(const j of active)button(root,'查看进行中的'+(j.kind==='guide'?'导读':'搜集'),()=>watch(j.id));
    const filters=node('div',undefined,'reading-actions');root.append(filters);const list=node('section');root.append(list);
    function show(filter){list.replaceChildren();const articles=data.articles.filter(a=>filter==='all'||(filter==='bookmark'&&a.bookmarked)||(filter==='later'&&a.read_later)||(filter==='read'&&a.read));if(!articles.length)list.append(node('p','这里还没有文章。先搜集少量内容，选感兴趣的保存。','desc'));for(const a of articles){const box=card(a,list);box.append(node('p',a.read?'本人确认读完':'尚未确认读完','desc'));button(box,'阅读导读与笔记',()=>read(a.id),true);original(box,a);}}
    for(const [key,label] of [['all','全部资料'],['bookmark','我的收藏'],['later','稍后阅读'],['read','本人读完']])button(filters,label,()=>show(key));show('all');
    const history=node('details');history.append(node('summary','最近搜集与导读记录'));root.append(history);for(const j of data.jobs)button(history,`${j.created_at} · ${j.kind==='guide'?'中文导读':'文章搜集'} · ${state[j.state]}`,()=>watch(j.id));
  };
  function preferenceFields(parent,p,includeSchedule){
    const box=node('div',undefined,'plan-grid');parent.append(box);const count=field(box,'推荐数量（1—8篇）',p.count,'number');count.min=1;count.max=8;
    const mode=select(box,'文章类型',[['mixed','近期＋经典'],['recent','近期精选（30天内）'],['classic','经典重读']],p.mode);
    const topics=[],languages=[];const topicBox=node('fieldset');topicBox.append(node('legend','感兴趣的主题'));parent.append(topicBox);
    for(const value of ['认知','经济学','社会学','心理','成长']){const el=field(topicBox,value,'','checkbox');el.checked=p.topics.includes(value);topics.push([value,el]);}
    const languageBox=node('fieldset');languageBox.append(node('legend','文章语言'));parent.append(languageBox);for(const [value,label] of [['zh','中文'],['en','英文（可生成中文导读）']]){const el=field(languageBox,label,'','checkbox');el.checked=p.languages.includes(value);languages.push([value,el]);}
    let enabled,hour,minute;if(includeSchedule){enabled=field(parent,'启用每日搜集','','checkbox');enabled.checked=p.enabled;const time=node('div',undefined,'plan-grid');parent.append(time);hour=field(time,'北京时间：小时',p.hour,'number');minute=field(time,'分钟',p.minute,'number');}
    return ()=>({...p,count:Number(count.value),mode:mode.value,topics:topics.filter(([,x])=>x.checked).map(([v])=>v),languages:languages.filter(([,x])=>x.checked).map(([v])=>v),...(includeSchedule?{enabled:enabled.checked,hour:Number(hour.value),minute:Number(minute.value)}:{})});
  }
  async function settings(){const status=shell('阅读偏好与来源');const turn=revision;button(root,'返回今日阅读',window.loadReading);const data=await api();if(turn!==revision)return;const get=preferenceFields(root,data.preferences,true);
    root.append(node('p','服务停止期间不会搜集。重启后仅补当日；来源失败或数量不足会明确记录。已保存文章不会重复推荐。','desc'));
    button(root,'保存偏好',async()=>{await api('/preferences',get());toast('阅读偏好已保存');await window.loadReading();},true);

    // 自定义来源管理
    root.append(node('h3','内容来源管理'));
    root.append(node('p','系统会从以下来源搜集文章。你可以添加自定义来源（RSS/Atom订阅），也可以使用推荐的默认来源。','desc'));

    // 默认来源
    root.append(node('h4','默认推荐来源'));
    const defaultBox=node('div',undefined,'sources-list');root.append(defaultBox);
    for(const s of data.default_sources){
      const row=node('div',undefined,'source-row');
      row.append(node('strong',s.name),' · ',s.language==='zh'?'中文':'英文',' · ',s.topics.join('、'));
      const link=node('a','查看');link.href=s.url;link.target='_blank';link.rel='noopener noreferrer';
      row.append(' ',link);
      defaultBox.append(row);
    }

    // 自定义来源
    root.append(node('h4','自定义来源'));
    const customBox=node('div',undefined,'sources-list');root.append(customBox);
    function renderCustomSources(){
      customBox.replaceChildren();
      if(!data.custom_sources||!data.custom_sources.length){
        customBox.append(node('p','还没有自定义来源。点击下方"添加来源"按钮添加你喜欢的RSS/Atom订阅。','desc'));
        return;
      }
      for(const s of data.custom_sources){
        const row=node('div',undefined,'source-row');
        row.append(node('strong',s.name),' · ',s.language==='zh'?'中文':'英文',' · ',s.topics.join('、'));
        const link=node('a','查看');link.href=s.url;link.target='_blank';link.rel='noopener noreferrer';
        const del=node('button','删除','btn');del.type='button';
        del.onclick=async()=>{
          if(!confirm(`确定删除来源"${s.name}"？`))return;
          await api('/sources/'+s.id,undefined);
          toast('来源已删除');
          data.custom_sources=data.custom_sources.filter(x=>x.id!==s.id);
          renderCustomSources();
        };
        row.append(' ',link,' ',del);
        customBox.append(row);
      }
    }
    renderCustomSources();

    // 添加新来源表单
    const addBox=node('details');root.append(addBox);
    addBox.append(node('summary','添加自定义来源'));
    const form=node('div',undefined,'plan-grid');addBox.append(form);
    addBox.append(node('p','添加你常用的RSS或Atom订阅源。请确保链接是有效的订阅地址（通常以.xml或.rss结尾，或包含/feed/）。','desc'));
    const name=field(form,'来源名称','','text');name.placeholder='例如：我的博客';
    const url=field(form,'订阅地址','','text');url.placeholder='https://example.com/feed';
    const lang=select(form,'语言',[['zh','中文'],['en','英文']],'zh');
    const topicBox=node('fieldset');topicBox.append(node('legend','主题（可多选）'));addBox.append(topicBox);
    const topicChecks=[];
    for(const t of data.topics){
      const el=field(topicBox,t,'','checkbox');
      topicChecks.push([t,el]);
    }
    button(addBox,'添加来源',async()=>{
      const topics=topicChecks.filter(([,x])=>x.checked).map(([v])=>v);
      if(!topics.length){toast('请至少选择一个主题');return;}
      const source=await api('/sources',{name:name.value,url:url.value,language:lang.value,topics});
      toast('来源已添加');
      data.custom_sources.push(source);
      renderCustomSources();
      name.value='';url.value='';
    },true);

    status.textContent='AI导读模型：'+data.model+'；只有明确点击生成导读才调用，可能产生费用。';
  }
  async function collectForm(){shell('帮我找文章');const turn=revision;button(root,'返回今日阅读',window.loadReading);const data=await api();if(turn!==revision)return;
    const query=field(root,'主题或关键词（可留空，例如：心理、社会、decision）');root.append(node('p','在已配置来源的标题与摘要中筛选，中文主题会扩展为英文关键词。复杂问题建议提取核心关键词。','desc'));const get=preferenceFields(root,data.preferences,false);
    button(root,'开始搜集并预览',()=>start({...get(),query:query.value}),true);
  }
  async function start(p){const turn=revision;const j=await api('/collect',{key:crypto.randomUUID(),preferences:p});if(turn===revision&&root.style.display!=='none')await watch(j.id);else toast('文章搜集已开始，可从今日阅读查看。');}
  async function watch(id){const status=shell('搜集与导读结果','job',id);const turn=revision;watching.set(id,turn);button(root,'返回今日阅读',window.loadReading);const cancel=button(root,'取消任务',()=>api('/jobs/'+id+'/cancel',{}));const content=node('section');root.append(content);let delay=1500;
    async function poll(){try{const j=await api('/jobs/'+id);if(watching.get(id)!==turn)return;const current=turn===revision&&root.style.display!=='none';const active=['queued','running'].includes(j.state);
      if(current){status.textContent=(j.phase||state[j.state])+(j.error?' · '+j.error:'');cancel.hidden=!active;content.replaceChildren();
        if(active){content.append(node('p',j.kind==='collect'?'正在核对来源与日期，结果会去重后显示。':'正在生成中文导读，原资料和个人笔记不会被替换。'));if(j.raw)content.append(node('pre',j.raw,'reading-stream'));}
        for(const s of j.sources||[])content.append(node('p',`${s.name}：${s.error||'读取'+s.count+'条'}`,'desc'));for(const warning of j.warnings||[])content.append(node('p',warning,'reading-warning'));
        if(!active&&j.kind==='guide'&&j.state==='ready')button(content,'阅读中文导读',()=>read(j.article_id),true);
        if(!active&&j.kind==='collect'&&j.state==='ready'){
          const selected=[];for(const a of j.candidates){const box=card(a,content);original(box,a);if(!j.saved_ids){const el=field(box,'保存这篇文章','','checkbox');el.checked=true;selected.push([a.id,el]);}else button(box,'阅读本地资料',()=>read(a.id));}
          if(j.saved_ids)content.append(node('p','已保存至：'+j.path,'desc'));
          else button(content,'保存选中的文章与资料',async()=>{await api('/jobs/'+id+'/save',{ids:selected.filter(([,e])=>e.checked).map(([aid])=>aid)});await watch(id);},true);
        }
        if(!active&&j.state!=='ready'&&j.kind==='collect')button(content,'调整条件重新搜集',collectForm);
      }
      if(active){delay=1500;setTimeout(poll,current?1500:10000);}else if(!current)toast(j.state==='ready'?'今日阅读任务已完成，可返回查看。':'今日阅读任务未完成，请查看记录。');
    }catch(e){if(watching.get(id)!==turn)return;if(turn===revision)status.textContent='暂时无法读取，正在重新连接；不会重复搜集。';delay=Math.min(delay*2,15000);setTimeout(poll,delay);}}
    await poll();
  }
  async function read(id){const status=shell('文章阅读','article',id);const turn=revision;button(root,'返回今日阅读',window.loadReading);const d=await api('/articles/'+id);if(turn!==revision)return;const a=d.article;root.querySelector('h2').textContent=a.zh_title||a.title;status.textContent=`${a.source} · ${a.language==='zh'?'中文':'英文'} · ${a.access}`;

    // 操作按钮区
    const actions=node('div',undefined,'reading-actions');root.append(actions);

    // 收藏、稍后阅读、完成状态
    for(const [key,label] of [['bookmarked',a.bookmarked?'取消收藏':'收藏'],['read_later',a.read_later?'移出稍后阅读':'稍后阅读'],['read',a.read?'改为尚未读完':'本人确认读完']])button(actions,label,async()=>{await api('/articles/'+id+'/personal',{[key]:!a[key]});a[key]=!a[key];toast('阅读状态已保存，笔记输入保留。');const b=actions.querySelectorAll('button');const index=['bookmarked','read_later','read'].indexOf(key);b[index].textContent=key==='bookmarked'?(a[key]?'取消收藏':'收藏'):key==='read_later'?(a[key]?'移出稍后阅读':'稍后阅读'):(a[key]?'改为尚未读完':'本人确认读完');});

    // 本地文章内容展示
    const contentBox=node('section',undefined,'article-content-box');root.append(contentBox);

    if(d.full_text){
      // 显示完整文章
      contentBox.append(node('h3','完整文章'));
      const contentDiv=node('div',undefined,'article-full-content');
      markdown(contentDiv,d.full_text);
      contentBox.append(contentDiv);
    } else {
      // 没有完整文章，提供获取按钮
      contentBox.append(node('p','本文尚未保存完整内容。点击下方按钮获取并保存到本地。','desc'));
      button(contentBox,'获取并保存完整文章',async()=>{
        const j=await api('/articles/'+id+'/fetch_full',{key:crypto.randomUUID()});
        toast('正在获取文章...');
        await watch(j.id);
        // 重新加载文章
        const new_d=await api('/articles/'+id);
        if(new_d.full_text){
          contentBox.replaceChildren();
          contentBox.append(node('h3','完整文章'));
          const contentDiv=node('div',undefined,'article-full-content');
          markdown(contentDiv,new_d.full_text);
          contentBox.append(contentDiv);
        }
      },true);
    }

    // 摘要和总结
    const summaryBox=node('section',undefined,'article-summary-box');root.append(summaryBox);
    summaryBox.append(node('h3','内容总结'));
    if(d.summary){
      const summaryDiv=node('div',undefined,'article-summary');
      markdown(summaryDiv,d.summary);
      summaryBox.append(summaryDiv);
    } else {
      summaryBox.append(node('p','暂无总结。点击下方按钮生成中文总结。','desc'));
    }
    const summaryBtnBox=node('div',undefined,'summary-actions');summaryBox.append(summaryBtnBox);
    button(summaryBtnBox,'生成/更新中文总结',async()=>{
      const j=await api('/articles/'+id+'/summary',{key:crypto.randomUUID()});
      await watch(j.id);
      const new_d=await api('/articles/'+id);
      if(new_d.summary){
        summaryBox.querySelector('.article-summary')?.remove();
        const summaryDiv=node('div',undefined,'article-summary');
        markdown(summaryDiv,new_d.summary);
        summaryBox.insertBefore(summaryDiv,summaryBtnBox);
      }
    },true);

    // 英语学习（仅英文文章）
    if(a.language==='en'){
      const englishBox=node('section',undefined,'article-english-box');root.append(englishBox);
      englishBox.append(node('h3','英语学习'));
      if(d.english_learning){
        const englishDiv=node('div',undefined,'article-english');
        markdown(englishDiv,d.english_learning);
        englishBox.append(englishDiv);
      } else {
        englishBox.append(node('p','暂无英语学习材料。点击下方按钮生成单词解释、语法分析和翻译。','desc'));
      }
      const englishBtnBox=node('div',undefined,'english-actions');englishBox.append(englishBtnBox);
      button(englishBtnBox,'生成/更新英语学习材料',async()=>{
        const j=await api('/articles/'+id+'/english',{key:crypto.randomUUID()});
        await watch(j.id);
        const new_d=await api('/articles/'+id);
        if(new_d.english_learning){
          englishBox.querySelector('.article-english')?.remove();
          const englishDiv=node('div',undefined,'article-english');
          markdown(englishDiv,new_d.english_learning);
          englishBox.insertBefore(englishDiv,englishBtnBox);
        }
      },true);
    }

    // AI导读
    const guideBox=node('section',undefined,'article-guide-box');root.append(guideBox);
    guideBox.append(node('h3','AI导读与解读'));
    if(d.guide&&d.guide!=='导读文件缺失，请核对本地目录。'){
      const guideDiv=node('div',undefined,'article-guide');
      markdown(guideDiv,d.guide);
      guideBox.append(guideDiv);
    } else {
      guideBox.append(node('p','暂无AI导读。点击下方按钮生成AI导读，包含核心观点分析和我的理解。','desc'));
    }
    const guideBtnBox=node('div',undefined,'guide-actions');guideBox.append(guideBtnBox);
    guideBox.append(node('p','将发送本篇文章的标题、来源和内容给已配置模型。本次调用可能产生费用。','desc'));
    button(guideBtnBox,'生成/更新AI导读',async()=>{
      if(dirty?.())throw new Error('请先保存笔记，再生成导读。');
      const j=await api('/articles/'+id+'/guide',{key:crypto.randomUUID()});
      await watch(j.id);
      const new_d=await api('/articles/'+id);
      if(new_d.guide&&new_d.guide!=='导读文件缺失，请核对本地目录。'){
        guideBox.querySelector('.article-guide')?.remove();
        const guideDiv=node('div',undefined,'article-guide');
        markdown(guideDiv,new_d.guide);
        guideBox.insertBefore(guideDiv,guideBtnBox);
      }
    },true);

    // 个人笔记
    root.append(node('h3','我的思考与笔记'));
    const notes=field(root,'',d.note.text,'textarea');notes.rows=7;notes.placeholder='哪个观点改变了我的假设？哪些证据还不够？我的思考和疑问...';dirty=()=>notes.value!==d.note.text;
    button(root,'保存笔记',async()=>{const submitted=notes.value;const saved=await api('/articles/'+id+'/personal',{note:submitted,note_hash:d.note.hash});d.note.text=submitted;d.note.hash=saved.note_hash;toast('笔记已保存到本地');},true);

    root.append(node('p','本地资料：'+d.path,'desc'));
  }
  window.enterReading=()=>{const m=location.hash.match(/^#reading\/(job|article)\/([a-zA-Z0-9-]+)$/);return m?(m[1]==='job'?watch(m[2]):read(m[2])):window.loadReading();};
  window.addEventListener('load',()=>{if(location.hash.startsWith('#reading/'))goTab('reading');});
})();
