/* Article discovery: safe DOM rendering and explicit model use. */
(() => {
  'use strict';
  const root=document.getElementById('view-reading');let revision=0,dirty=null;const watching=new Map();
  const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  const state={queued:'等待开始',running:'进行中',ready:'已完成',failed:'未完成',cancelled:'已取消'};
  const category={recent:'近期精选',classic:'经典重读',mixed:'近期＋经典'};
  async function api(path='',data){if(data!==undefined && /^\/articles\/[^/]+\/(guide|summary|english)$/.test(path))data={...data,ai_config:AIConfig.require()};const r=await fetch('/api/reading'+path,{method:data===undefined?'GET':'POST',cache:'no-store',headers:{'Content-Type':'application/json','X-Copilot-Request':'1'},body:data===undefined?undefined:JSON.stringify({data})});const j=await r.json();if(!r.ok)throw new Error(j.message||'读取失败，请稍后重试。');return j;}
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
    const status=shell('今日阅读');const turn=revision;button(root,'帮我找文章',()=>collectForm(),true);button(root,'添加文章',()=>importForm());button(root,'阅读偏好与来源',()=>settings());
    const data=await api();if(turn!==revision)return;const p=data.preferences;
    status.textContent=`${p.enabled?'每天':'已暂停每日搜集'} 北京时间 ${String(p.hour).padStart(2,'0')}:${String(p.minute).padStart(2,'0')} · ${p.count}篇 · ${category[p.mode]}。${data.storage_backend==='cloud'?'云端自动搜集，关闭浏览器后仍会运行':'本地服务需保持运行'}；每日搜集不调用付费模型。`;
    const today=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
    const daily=data.jobs.find(j=>j.daily&&j.date===today);const banner=node('section',undefined,'reading-banner');root.append(banner);banner.append(node('h3','今日精选'));
    if(daily){banner.append(node('p',state[daily.state]+(daily.error?' · '+daily.error:'')));button(banner,'查看今日结果',()=>watch(daily.id));}
    else{banner.append(node('p','今天尚无定时搜集结果，也可以现在手动搜集。'));button(banner,'按我的偏好搜集',()=>start(p),true);}
    const active=data.jobs.filter(j=>['queued','running'].includes(j.state));for(const j of active)button(root,'查看进行中的'+(j.kind==='guide'?'导读':'搜集'),()=>watch(j.id));
    // Search box
    const searchBar=node('div',undefined,'reading-actions');root.append(searchBar);
    const searchInput=node('input',undefined,'plan-field');searchInput.type='text';searchInput.placeholder='搜索标题、作者、来源…';searchInput.style.cssText='flex:1;max-width:340px;padding:6px 10px';
    searchBar.append(searchInput);
    let currentSearch='';let currentFilter='all';
    searchInput.oninput=async()=>{currentSearch=searchInput.value.trim();await refreshList();};
    const filters=node('div',undefined,'reading-actions');root.append(filters);const list=node('section');root.append(list);
    async function refreshList(){
      const params=new URLSearchParams();
      if(currentSearch)params.set('search',currentSearch);
      if(currentFilter==='archived')params.set('include_archived','true');
      const qs=params.toString();
      const freshData=qs?await api('?'+qs):data;
      list.replaceChildren();
      let articles=freshData.articles.filter(a=>currentFilter==='all'||currentFilter==='archived'||(currentFilter==='bookmark'&&a.bookmarked)||(currentFilter==='later'&&a.read_later)||(currentFilter==='read'&&a.read));
      if(currentFilter==='archived')articles=articles.filter(a=>a.archived);
      else if(currentFilter!=='archived')articles=articles.filter(a=>!a.archived);
      if(!articles.length)list.append(node('p','这里还没有文章。先搜集少量内容，或点击"添加文章"手动导入。','desc'));
      for(const a of articles){const box=card(a,list);box.append(node('p',a.read?'本人确认读完':'尚未确认读完','desc'));button(box,'阅读导读与笔记',()=>read(a.id),true);original(box,a);
        if(a.archived){button(box,'恢复',async()=>{await api('/articles/'+a.id+'/restore');toast('已恢复');await refreshList();});}
        else{button(box,'归档',async()=>{if(confirm('归档后列表默认隐藏，可在"已归档"中恢复。')){await api('/articles/'+a.id+'/archive');toast('已归档');await refreshList();}});}
      }
    }
    for(const [key,label] of [['all','全部资料'],['bookmark','我的收藏'],['later','稍后阅读'],['read','本人读完'],['archived','已归档']])button(filters,label,()=>{currentFilter=key;refreshList();});refreshList();
    const history=node('details');history.append(node('summary','最近搜集与导读记录'));root.append(history);for(const j of data.jobs)button(history,`${j.created_at} · ${j.kind==='guide'?'中文导读':'文章搜集'} · ${state[j.state]}`,()=>watch(j.id));
  };
  function preferenceFields(parent,p,includeSchedule,availableTopics){
    const box=node('div',undefined,'plan-grid');parent.append(box);const count=field(box,'推荐数量（1—8篇）',p.count,'number');count.min=1;count.max=8;
    const mode=select(box,'文章类型',[['mixed','近期＋经典'],['recent','近期精选（30天内）'],['classic','经典重读']],p.mode);
    const topics=[],languages=[];const topicBox=node('fieldset');topicBox.append(node('legend','感兴趣的主题'));parent.append(topicBox);
    for(const value of availableTopics){const el=field(topicBox,value,'','checkbox');el.checked=p.topics.includes(value);topics.push([value,el]);}
    const languageBox=node('fieldset');languageBox.append(node('legend','文章语言'));parent.append(languageBox);for(const [value,label] of [['zh','中文'],['en','英文（可生成中文导读）']]){const el=field(languageBox,label,'','checkbox');el.checked=p.languages.includes(value);languages.push([value,el]);}
    let enabled,hour,minute;if(includeSchedule){enabled=field(parent,'启用每日搜集','','checkbox');enabled.checked=p.enabled;const time=node('div',undefined,'plan-grid');parent.append(time);hour=field(time,'北京时间：小时',p.hour,'number');minute=field(time,'分钟',p.minute,'number');}
    return ()=>({...p,count:Number(count.value),mode:mode.value,topics:topics.filter(([,x])=>x.checked).map(([v])=>v),languages:languages.filter(([,x])=>x.checked).map(([v])=>v),...(includeSchedule?{enabled:enabled.checked,hour:Number(hour.value),minute:Number(minute.value)}:{})});
  }
  async function settings(){const status=shell('阅读偏好与来源');const turn=revision;button(root,'返回今日阅读',window.loadReading);const data=await api();if(turn!==revision)return;const get=preferenceFields(root,data.preferences,true,data.topics);
    root.append(node('p',(data.storage_backend==='cloud'?'云端每日自动搜集，电脑和浏览器无需保持开启。':'服务停止期间不会搜集。重启后仅补当日。')+'来源失败或数量不足会明确记录。已保存文章不会重复推荐。','desc'));
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

    status.textContent='AI导读模型：'+AIConfig.read().model_name+'；只有明确点击生成导读才调用，可能产生费用。';
  }
  async function collectForm(){shell('帮我找文章');const turn=revision;button(root,'返回今日阅读',window.loadReading);const data=await api();if(turn!==revision)return;
    const query=field(root,'主题或关键词（可留空，例如：科技、心理、社会、decision）');root.append(node('p','在已配置来源的标题与摘要中筛选，中文主题会扩展为英文关键词。复杂问题建议提取核心关键词。','desc'));const get=preferenceFields(root,data.preferences,false,data.topics);
    button(root,'开始搜集并预览',()=>start({...get(),query:query.value}),true);
  }
  async function importForm(){
    shell('添加文章');const turn=revision;button(root,'返回今日阅读',window.loadReading);
    root.append(node('p','通过 URL 抓取或手动粘贴正文导入文章。','desc'));
    const modeBox=node('div',undefined,'reading-actions');root.append(modeBox);
    let mode='url';
    const urlBtn=node('button','URL 导入','btn primary');urlBtn.type='button';
    const pasteBtn=node('button','粘贴正文','btn');pasteBtn.type='button';
    modeBox.append(urlBtn,pasteBtn);
    const formBox=node('section');root.append(formBox);
    function renderUrlForm(){
      mode='url';urlBtn.className='btn primary';pasteBtn.className='btn';
      formBox.replaceChildren();
      const url=field(formBox,'文章链接','','text');url.placeholder='https://example.com/article';url.style.cssText='width:100%;max-width:500px';
      const title=field(formBox,'标题（可选，自动提取）','','text');title.style.cssText='width:100%;max-width:500px';
      const author=field(formBox,'作者（可选）','','text');author.style.cssText='width:100%;max-width:300px';
      const lang=select(formBox,'语言',[['zh','中文'],['en','英文']],'zh');
      const tagsInput=field(formBox,'标签（逗号分隔，可选）','','text');tagsInput.placeholder='认知, 思维工具';tagsInput.style.cssText='width:100%;max-width:300px';
      const previewBox=node('div');formBox.append(previewBox);
      button(formBox,'抓取并预览',async()=>{
        const u=url.value.trim();if(!u){toast('请输入 URL');return;}
        previewBox.innerHTML='<p class="desc">正在抓取…</p>';
        try{
          const r=await api('/import-url',{url:u,title:title.value,author:author.value,language:lang.value,tags:tagsInput.value.split(',').map(s=>s.trim()).filter(Boolean)});
          if(r.status==='preview'){
            if(!r.content){previewBox.innerHTML='<p class="reading-warning">'+esc(r.warning||'抓取失败')+'</p>';return;}
            previewBox.replaceChildren();
            previewBox.append(node('h3','预览正文（前 2000 字）'));
            previewBox.append(node('pre',r.content,{style:'max-height:300px;overflow:auto;background:#f5f5f5;padding:12px;border-radius:6px;font-size:13px;white-space:pre-wrap'}));
            button(previewBox,'确认保存',async()=>{
              const r2=await api('/import-url',{url:u,title:title.value||'未命名文章',author:author.value,language:lang.value,tags:tagsInput.value.split(',').map(s=>s.trim()).filter(Boolean),confirm:true});
              if(r2.status==='saved'){toast('文章已保存');await window.loadReading();}
            },true);
          } else if(r.status==='saved'){toast('文章已保存');await window.loadReading();}
        }catch(e){previewBox.innerHTML='<p class="reading-warning">'+esc(e.message)+'</p>';}
      },true);
    }
    function renderPasteForm(){
      mode='paste';pasteBtn.className='btn primary';urlBtn.className='btn';
      formBox.replaceChildren();
      const title=field(formBox,'标题','','text');title.style.cssText='width:100%;max-width:500px';
      const author=field(formBox,'作者（可选）','','text');author.style.cssText='width:100%;max-width:300px';
      const url=field(formBox,'原文链接（可选）','','text');url.placeholder='https://...';url.style.cssText='width:100%;max-width:500px';
      const lang=select(formBox,'语言',[['zh','中文'],['en','英文']],'zh');
      const tagsInput=field(formBox,'标签（逗号分隔，可选）','','text');tagsInput.placeholder='认知, 思维工具';tagsInput.style.cssText='width:100%;max-width:300px';
      const contentArea=node('textarea',undefined,'plan-field');contentArea.placeholder='粘贴文章正文…';contentArea.style.cssText='width:100%;min-height:200px;font-family:inherit;font-size:14px;padding:8px';
      const contentLabel=node('label','正文');contentLabel.append(contentArea);formBox.append(contentLabel);
      button(formBox,'保存文章',async()=>{
        if(!title.value.trim()){toast('请填写标题');return;}
        if(!contentArea.value.trim()){toast('请填写正文');return;}
        try{
          const r=await api('/import-paste',{title:title.value,content:contentArea.value,author:author.value,url:url.value,language:lang.value,tags:tagsInput.value.split(',').map(s=>s.trim()).filter(Boolean)});
          if(r.status==='saved'){toast('文章已保存');await window.loadReading();}
        }catch(e){toast(e.message);}
      },true);
    }
    urlBtn.onclick=renderUrlForm;pasteBtn.onclick=renderPasteForm;
    renderUrlForm();
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
  async function read(id){const status=shell('文章阅读','article',id);const turn=revision;button(root,'返回今日阅读',window.loadReading);button(root,'我的生词本',()=>vocabPage(id));const d=await api('/articles/'+id);if(turn!==revision)return;const a=d.article;root.querySelector('h2').textContent=a.zh_title||a.title;status.textContent=`${a.source} · ${a.language==='zh'?'中文':'英文'} · ${a.access}`;

    // 操作按钮区
    const actions=node('div',undefined,'reading-actions');root.append(actions);

    // 收藏、稍后阅读、完成状态
    for(const [key,label] of [['bookmarked',a.bookmarked?'取消收藏':'收藏'],['read_later',a.read_later?'移出稍后阅读':'稍后阅读'],['read',a.read?'改为尚未读完':'本人确认读完']])button(actions,label,async()=>{await api('/articles/'+id+'/personal',{[key]:!a[key]});a[key]=!a[key];toast('阅读状态已保存，笔记输入保留。');const b=actions.querySelectorAll('button');const index=['bookmarked','read_later','read'].indexOf(key);b[index].textContent=key==='bookmarked'?(a[key]?'取消收藏':'收藏'):key==='read_later'?(a[key]?'移出稍后阅读':'稍后阅读'):(a[key]?'改为尚未读完':'本人确认读完');});

    // Five-view tabs
    const tabBox=node('div',undefined,'reading-tabs');root.append(tabBox);
    const views=['original','bilingual','summary','english','notes'];
    const viewLabels={original:'原文',bilingual:'双语',summary:'总结',english:'英语解析',notes:'我的笔记'};
    let currentView='original';
    const viewContents={};
    for(const v of views){const btn=node('button',viewLabels[v],'btn'+(v===currentView?' primary':''));btn.type='button';btn.onclick=()=>{currentView=v;for(const v2 of views){viewContents[v2].style.display=v2===v?'':'none';tabBox.querySelectorAll('button')[views.indexOf(v2)].className='btn'+(v2===v?' primary':'');}};tabBox.append(btn);}

    // Original view
    const originalView=node('section',undefined,'article-content-box');root.append(originalView);viewContents.original=originalView;
    if(d.full_text){
      originalView.append(node('h3','完整文章'));
      const contentDiv=node('div',undefined,'article-full-content');
      markdown(contentDiv,d.full_text);
      originalView.append(contentDiv);
      // Vocabulary selection
      setupVocabSelection(contentDiv,id,a);
    } else {
      originalView.append(node('p','本文尚未保存完整内容。点击下方按钮获取并保存。','desc'));
      button(originalView,'获取并保存完整文章',async()=>{
        const j=await api('/articles/'+id+'/fetch_full',{key:crypto.randomUUID()});
        toast('正在获取文章...');
        await watch(j.id);
        const new_d=await api('/articles/'+id);
        if(new_d.full_text){
          originalView.replaceChildren();
          originalView.append(node('h3','完整文章'));
          const contentDiv=node('div',undefined,'article-full-content');
          markdown(contentDiv,new_d.full_text);
          originalView.append(contentDiv);
          setupVocabSelection(contentDiv,id,a);
        }
      },true);
    }

    // Bilingual view
    const bilingualView=node('section',undefined,'article-content-box');root.append(bilingualView);viewContents.bilingual=bilingualView;
    bilingualView.style.display='none';
    bilingualView.append(node('h3','双语对照'));
    if(d.full_text){
      const drafts=d.article.translation_drafts||{};
      if(Object.keys(drafts).length){
        bilingualView.append(node('p','已有翻译草稿，可以逐段查看和采用。','desc'));
        const draftList=node('div',undefined,'translation-drafts');
        for(const [pid,draft] of Object.entries(drafts)){
          const row=node('div',undefined,'translation-row');
          row.append(node('p',`段落 ${pid}`,'desc'));
          row.append(node('p',draft.text));
          if(draft.adopted)row.append(node('span','✓ 已采用','reading-tag'));
          else button(row,'采用',async()=>{await api('/articles/'+id+'/translation/adopt',{paragraph_id:pid});toast('已采用');await read(id);});
          draftList.append(row);
        }
        bilingualView.append(draftList);
      } else {
        bilingualView.append(node('p','尚无翻译草稿。双语翻译功能正在开发中，可先阅读原文或生成总结。','desc'));
        // Show original text with paragraph numbers for reference
        const paraDiv=node('div',undefined,'article-full-content');
        const paragraphs=d.full_text.split('\n\n').filter(Boolean);
        for(let i=0;i<paragraphs.length;i++){
          const pBox=node('div',undefined,'bilingual-paragraph');
          pBox.append(node('span',`[${i+1}]`,'para-num'));
          const pContent=node('span');markdown(pContent,paragraphs[i]);
          pBox.append(pContent);
          paraDiv.append(pBox);
        }
        bilingualView.append(paraDiv);
      }
    } else {
      bilingualView.append(node('p','请先获取文章完整内容。','desc'));
    }

    // Summary view
    const summaryView=node('section',undefined,'article-summary-box');root.append(summaryView);viewContents.summary=summaryView;
    summaryView.style.display='none';
    summaryView.append(node('h3','内容总结'));
    // Draft status
    const summaryDraft=d.article.summary_draft;
    if(summaryDraft&&!summaryDraft.adopted){
      const draftBanner=node('div',undefined,'reading-warning');
      draftBanner.append(node('p',`有未采用的摘要草稿（版本 ${summaryDraft.version}）。`));
      button(draftBanner,'采用草稿',async()=>{await api('/articles/'+id+'/summary-draft/adopt');toast('已采用');await read(id);});
      summaryView.append(draftBanner);
    }
    if(d.summary){
      const summaryDiv=node('div',undefined,'article-summary');
      markdown(summaryDiv,d.summary);
      summaryView.append(summaryDiv);
    } else {
      summaryView.append(node('p','暂无总结。点击下方按钮生成中文总结。','desc'));
    }
    const summaryBtnBox=node('div',undefined,'summary-actions');summaryView.append(summaryBtnBox);
    button(summaryBtnBox,'生成/更新中文总结',async()=>{
      const j=await api('/articles/'+id+'/summary',{key:crypto.randomUUID()});
      await watch(j.id);
      const new_d=await api('/articles/'+id);
      if(new_d.summary){
        summaryView.querySelector('.article-summary')?.remove();
        const summaryDiv=node('div',undefined,'article-summary');
        markdown(summaryDiv,new_d.summary);
        summaryView.insertBefore(summaryDiv,summaryBtnBox);
      }
    },true);

    // English view
    const englishView=node('section',undefined,'article-english-box');root.append(englishView);viewContents.english=englishView;
    englishView.style.display='none';
    englishView.append(node('h3','英语学习'));
    const englishDraft=d.article.english_draft;
    if(englishDraft&&!englishDraft.adopted){
      const draftBanner=node('div',undefined,'reading-warning');
      draftBanner.append(node('p',`有未采用的英语学习草稿（版本 ${englishDraft.version}）。`));
      button(draftBanner,'采用草稿',async()=>{await api('/articles/'+id+'/english-draft/adopt');toast('已采用');await read(id);});
      englishView.append(draftBanner);
    }
    if(a.language==='en'){
      if(d.english_learning){
        const englishDiv=node('div',undefined,'article-english');
        markdown(englishDiv,d.english_learning);
        englishView.append(englishDiv);
      } else {
        englishView.append(node('p','暂无英语学习材料。点击下方按钮生成单词解释、语法分析和翻译。','desc'));
      }
      const englishBtnBox=node('div',undefined,'english-actions');englishView.append(englishBtnBox);
      button(englishBtnBox,'生成/更新英语学习材料',async()=>{
        const j=await api('/articles/'+id+'/english',{key:crypto.randomUUID()});
        await watch(j.id);
        const new_d=await api('/articles/'+id);
        if(new_d.english_learning){
          englishView.querySelector('.article-english')?.remove();
          const englishDiv=node('div',undefined,'article-english');
          markdown(englishDiv,new_d.english_learning);
          englishView.insertBefore(englishDiv,englishBtnBox);
        }
      },true);
    } else {
      englishView.append(node('p','本文非英文，英语学习材料不适用。','desc'));
    }

    // Notes view
    const notesView=node('section',undefined,'article-guide-box');root.append(notesView);viewContents.notes=notesView;
    notesView.style.display='none';
    // AI导读
    notesView.append(node('h3','AI导读与解读'));
    if(d.guide&&d.guide!=='导读文件缺失，请核对本地目录。'){
      const guideDiv=node('div',undefined,'article-guide');
      markdown(guideDiv,d.guide);
      notesView.append(guideDiv);
    } else {
      notesView.append(node('p','暂无AI导读。点击下方按钮生成AI导读，包含核心观点分析和我的理解。','desc'));
    }
    const guideBtnBox=node('div',undefined,'guide-actions');notesView.append(guideBtnBox);
    notesView.append(node('p','将发送本篇文章的标题、来源和内容给已配置模型。本次调用可能产生费用。','desc'));
    button(guideBtnBox,'生成/更新AI导读',async()=>{
      if(dirty?.())throw new Error('请先保存笔记，再生成导读。');
      const j=await api('/articles/'+id+'/guide',{key:crypto.randomUUID()});
      await watch(j.id);
      const new_d=await api('/articles/'+id);
      if(new_d.guide&&new_d.guide!=='导读文件缺失，请核对本地目录。'){
        notesView.querySelector('.article-guide')?.remove();
        const guideDiv=node('div',undefined,'article-guide');
        markdown(guideDiv,new_d.guide);
        notesView.insertBefore(guideDiv,guideBtnBox);
      }
    },true);

    // 个人笔记
    notesView.append(node('h3','我的思考与笔记'));
    const notes=field(notesView,'',d.note.text,'textarea');notes.rows=7;notes.placeholder='哪个观点改变了我的假设？哪些证据还不够？我的思考和疑问...';dirty=()=>notes.value!==d.note.text;
    button(notesView,'保存笔记',async()=>{const submitted=notes.value;const saved=await api('/articles/'+id+'/personal',{note:submitted,note_hash:d.note.hash});d.note.text=submitted;d.note.hash=saved.note_hash;toast('笔记已保存');},true);

    if(d.github_url){const link=node('a','在 GitHub 打开资料');link.href=d.github_url;link.target='_blank';link.rel='noopener noreferrer';root.append(link);}else root.append(node('p','资料位置：'+d.path,'desc'));
  }
  function setupVocabSelection(container,articleId,article){
    container.addEventListener('mouseup',async()=>{
      const sel=window.getSelection();
      const text=sel?.toString().trim();
      if(!text||text.length>50)return;
      // Show a floating "加入生词" button
      const existing=document.getElementById('vocab-add-float');
      if(existing)existing.remove();
      const rect=sel.getRangeAt(0).getBoundingClientRect();
      const btn=node('button','加入生词','btn primary');
      btn.id='vocab-add-float';
      btn.style.cssText=`position:fixed;left:${rect.right+8}px;top:${rect.top}px;z-index:1000;font-size:12px;padding:4px 8px`;
      btn.onclick=async()=>{
        try{
          const sent=sel.anchorNode?.parentElement?.closest('p')?.textContent?.slice(0,200)||text;
          await api('/vocabulary',{article_id:articleId,word:text,context_sentence:sent});
          toast(`已加入生词：${text.slice(0,20)}`);
          btn.remove();
        }catch(e){toast(e.message);}
      };
      document.body.append(btn);
      setTimeout(()=>{document.addEventListener('mousedown',function rm(e){if(e.target!==btn){btn.remove();document.removeEventListener('mousedown',rm);}},{once:true});},100);
    });
  }
  async function vocabPage(articleId){
    const status=shell('我的生词本');const turn=revision;
    button(root,'返回今日阅读',window.loadReading);
    const stats=await api('/vocabulary/stats'+(articleId?'?article_id='+articleId:''));
    const statsBox=node('div',undefined,'reading-banner');root.append(statsBox);
    statsBox.append(node('p',`总计 ${stats.total} 个 · 活跃 ${stats.active} · 待复习 ${stats.due} · 已暂停 ${stats.paused} · 已归档 ${stats.archived}`));
    const filterBox=node('div',undefined,'reading-actions');root.append(filterBox);
    let includeArchived=false,includePaused=true;
    const archBtn=node('button','显示已归档','btn');archBtn.type='button';
    archBtn.onclick=()=>{includeArchived=!includeArchived;archBtn.className='btn'+(includeArchived?' primary':'');refresh();};
    filterBox.append(archBtn);
    const list=node('section');root.append(list);
    async function refresh(){
      const params=new URLSearchParams();
      if(articleId)params.set('article_id',articleId);
      if(includeArchived)params.set('include_archived','true');
      if(!includePaused)params.set('include_paused','false');
      const items=await api('/vocabulary?'+params.toString());
      list.replaceChildren();
      if(!items.length){list.append(node('p','还没有生词。阅读时选中单词可快速加入。','desc'));return;}
      for(const v of items){
        const row=node('div',undefined,'vocab-row');
        row.append(node('strong',v.word));
        if(v.part_of_speech)row.append(node('span',` (${v.part_of_speech})`,'desc'));
        if(v.contextual_meaning)row.append(node('p',v.contextual_meaning));
        if(v.context_sentence)row.append(node('p',`原文：${v.context_sentence}`,'desc'));
        row.append(node('p',`步骤 ${v.step} · 下次复习 ${v.next_review}${v.paused?' · 已暂停':''}${v.archived?' · 已归档':''}`,'desc'));
        const actions=node('div',undefined,'reading-actions');
        if(v.paused)button(actions,'取消暂停',async()=>{await api('/vocabulary/'+v.id+'/pause',{paused:false});await refresh();});
        else button(actions,'暂停',async()=>{await api('/vocabulary/'+v.id+'/pause',{paused:true});await refresh();});
        if(v.archived)button(actions,'恢复',async()=>{await api('/vocabulary/'+v.id+'/archive',{archived:false});await refresh();});
        else button(actions,'归档',async()=>{await api('/vocabulary/'+v.id+'/archive',{archived:true});await refresh();});
        button(actions,'删除',async()=>{if(confirm('确定删除这个生词？所有复习记录也会删除。')){await api('/vocabulary/'+v.id,undefined);await refresh();}});
        row.append(actions);
        list.append(row);
      }
    }
    await refresh();
    // Due vocabulary section
    const due=await api('/vocabulary/due'+(articleId?'?article_id='+articleId:''));
    if(due.length){
      root.append(node('h3','待复习'));
      const dueList=node('section');root.append(dueList);
      for(const v of due){
        const row=node('div',undefined,'vocab-row');
        row.append(node('strong',v.word),node('p',`步骤 ${v.step} · 到期 ${v.next_review}`,'desc'));
        if(v.contextual_meaning)row.append(node('p',v.contextual_meaning));
        const reviewBox=node('div',undefined,'reading-actions');
        button(reviewBox,'忘了',async()=>{await api('/vocabulary/'+v.id+'/review',{feedback:'again'});toast('已重置');await refresh();await vocabPage(articleId);});
        button(reviewBox,'模糊',async()=>{await api('/vocabulary/'+v.id+'/review',{feedback:'hard'});toast('已记录');await refresh();await vocabPage(articleId);});
        button(reviewBox,'记得',async()=>{await api('/vocabulary/'+v.id+'/review',{feedback:'good'});toast('已记录');await refresh();await vocabPage(articleId);},true);
        row.append(reviewBox);
        dueList.append(row);
      }
    }
  }
  window.enterReading=()=>{const m=location.hash.match(/^#reading\/(job|article)\/([a-zA-Z0-9-]+)$/);return m?(m[1]==='job'?watch(m[2]):read(m[2])):window.loadReading();};
  window.addEventListener('load',()=>{if(location.hash.startsWith('#reading/'))goTab('reading');});
})();
