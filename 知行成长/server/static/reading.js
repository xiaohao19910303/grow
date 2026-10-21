/* Article discovery: safe DOM rendering and explicit model use. */
(() => {
  'use strict';
  const root=document.getElementById('view-reading');let revision=0,dirty=null,starting=null,readingOrigin=null;const watching=new Map();
  let lastArticle=null;
  const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  const state={queued:'等待开始',running:'进行中',ready:'已完成',failed:'未完成',cancelled:'已取消'};
  const jobLabels={collect:'文章搜集',guide:'中文导读',fetch_full:'正文加载',summary:'文章总结',english:'英语解析'};
  const category={recent:'近期精选',classic:'经典重读',mixed:'近期＋经典'};
  const defaultTopics=['认知','科技','经济学','社会学','心理','成长'];
  const defaultPreferences={enabled:true,hour:10,minute:0,count:3,mode:'mixed',topics:defaultTopics,languages:['zh','en'],query:'',auto_guide:false};
  let preferenceCache=null;
  const libraryCache=new Map(),libraryRequests=new Map();let libraryEpoch=0;
  let libraryState={account:'',kind:'articles',search:'',filter:'all',page:1};
  function invalidateLibrary(){libraryEpoch++;libraryCache.clear();}
  const accountKey=()=>window.Account?.user?.id||'';
  async function api(path='',data){if(data&&(data.read===true||data.mark_read===true)){const origin=window.actionContentOrigin;data={...data,key:data.key||crypto.randomUUID(),...(origin?.target?.kind==='article'&&path.startsWith('/articles/'+origin.target.course+'/')?{origin_action_id:origin.actionId}:{})};}if(data!==undefined && /^\/articles\/[^/]+\/(guide|summary|english)$/.test(path))data={...data,ai_config:AIConfig.require()};const r=await fetch('/api/reading'+path,{method:data===undefined?'GET':'POST',cache:'no-store',headers:{'Content-Type':'application/json','X-Copilot-Request':'1'},body:data===undefined?undefined:JSON.stringify({data})});let j;try{j=await r.json();}catch(error){throw new Error('服务暂时不可用，请稍后重试。');}if(!r.ok)throw new Error(j.message||j.detail||'读取失败，请稍后重试。');if(data!==undefined){invalidateLibrary();if(data.read!==undefined||data.mark_read===true)await window.refreshLearningCompletion?.(j);}window.ReadingTasks?.track(j);return j;}
  function button(parent,label,action,primary=false){const b=node('button',label,'btn'+(primary?' primary':''));b.type='button';b.onclick=async()=>{const turn=revision;b.disabled=true;try{await action();}catch(e){toast(e.message);const status=root.querySelector('[role=status]');if(turn===revision&&status)status.textContent=e.message;}finally{b.disabled=false;}};parent.append(b);return b;}
  function field(parent,label,value='',type='text'){const wrap=node('label',label,'plan-field');const input=node(type==='textarea'?'textarea':'input');if(type!=='textarea')input.type=type;input.value=value;wrap.append(input);parent.append(wrap);return input;}
  function select(parent,label,values,value){const wrap=node('label',label,'plan-field'),input=node('select');for(const [v,t] of values){const o=node('option',t);o.value=v;input.append(o);}input.value=value;wrap.append(input);parent.append(wrap);return input;}
  function leave(){if(dirty?.()&&!confirm('笔记或阅读反馈有未保存的修改。确定放弃并离开？'))return false;window.ReadingPosition?.close();dirty=null;++revision;return true;}
  window.beforeReadingLeave=name=>{if(!leave())return false;if(name!=='reading'&&location.hash.startsWith('#reading/'))history.replaceState(null,'',location.pathname+location.search);return true;};
  window.addEventListener('beforeunload',e=>{if(dirty?.()){e.preventDefault();e.returnValue='';}});
  function shell(title,kind,id){if(!leave())throw new Error('已保留未保存的笔记和反馈。');history.replaceState(null,'',kind?'#reading/'+kind+'/'+id:location.pathname+location.search);root.replaceChildren(node('h2',title));const status=node('p','','desc');status.setAttribute('role','status');root.append(status);return status;}
  function markdown(parent,text){const box=node('div',undefined,'cp-reader');window.renderLearningMarkdown(box,text);parent.append(box);}
  function original(parent,a){if(!/^https?:\/\//i.test(a.url))return;const link=node('a','来源网页 ↗','reading-source-link');link.href=a.url;link.target='_blank';link.rel='noopener noreferrer';parent.append(link);}
  function card(a,parent){const box=node('article',undefined,'reading-card');box.append(node('span',`${category[a.category]||'已保存文章'} · ${a.language==='zh'?'中文':'英文'} · 热度未核实`,'reading-tag'),node('h3',a.zh_title||a.title||'未命名文章'));if(a.zh_title)box.append(node('p',a.title,'desc'));box.append(node('p',`${a.source||'未提供来源'} · ${a.author||'未提供作者'} · ${a.published_at||'日期未知'}`,'desc'),node('p',a.summary||'来源未提供摘要，可打开本站阅读查看正文。'),node('p',a.reason||'已保存到个人阅读资料'),node('p',a.access||'','desc'));parent.append(box);return box;}
  window.loadReading=async()=>{
    readingOrigin=null;lastArticle=null;const status=shell('阅读');
    status.textContent='从已保存的文章继续读，也可以主动搜集新文章。';
    const historyBox=node('section',undefined,'reading-banner');root.append(historyBox);
    historyBox.append(node('h3','历史文章'),node('p','之前保存的正文、笔记和阅读反馈都在这里。无需重新搜集。','desc'));
    button(historyBox,'查看历史文章',()=>loadHistory('articles'),true);
    button(historyBox,'历史搜集记录',()=>loadHistory('jobs'));
    const discover=node('section',undefined,'reading-banner');root.append(discover);
    discover.append(node('h3','发现新文章'),node('p','需要新内容时再开始搜集；搜集时间与来源可在偏好中调整。','desc'));
    button(discover,'帮我找文章',()=>collectForm(),true);button(discover,'添加文章',()=>importForm());button(discover,'阅读偏好与来源',()=>settings());
  };
  async function libraryData(params,force){
    const key=accountKey()+':'+params;
    if(force)invalidateLibrary();
    if(libraryCache.has(key))return libraryCache.get(key);
    const epoch=libraryEpoch,requestKey=epoch+':'+key;
    if(!libraryRequests.has(requestKey)){
      const pending=api('/library?'+params).then(data=>{
        if(epoch===libraryEpoch){libraryCache.set(key,data);if(libraryCache.size>20)libraryCache.delete(libraryCache.keys().next().value);}
        return data;
      }).finally(()=>libraryRequests.delete(requestKey));
      libraryRequests.set(requestKey,pending);
    }
    return libraryRequests.get(requestKey);
  }
  async function loadHistory(kind=libraryState.kind){
    if(libraryState.account!==accountKey())libraryState={account:accountKey(),kind,search:'',filter:'all',page:1};
    if(libraryState.kind!==kind)Object.assign(libraryState,{kind,search:'',filter:'all',page:1});
    const status=shell(kind==='jobs'?'历史搜集记录':'历史文章','history',kind);const turn=revision;
    status.setAttribute('aria-live','polite');
    button(root,'返回阅读',window.loadReading);button(root,kind==='jobs'?'历史文章':'历史搜集记录',()=>loadHistory(kind==='jobs'?'articles':'jobs'));
    button(root,'帮我找文章',collectForm);button(root,'刷新历史记录',()=>refresh(true));
    const help=node('p',kind==='jobs'?'可继续查看以前的搜集结果、保存文章或检查未完成任务。':'直接阅读已保存的文章；返回列表时会保留搜索、筛选和页码。','desc');root.append(help);
    const filters=node('div',undefined,'reading-actions');root.append(filters);
    let input,timer,request=0;
    if(kind==='articles'){
      input=field(root,'搜索历史文章',libraryState.search);input.maxLength=300;input.placeholder='标题、作者、标签、正文或我的收获';input.type='search';
      input.oninput=()=>{clearTimeout(timer);++request;libraryState.search=input.value.trim();libraryState.page=1;status.textContent='正在准备搜索历史文章…';timer=setTimeout(()=>refresh(),350);};
      input.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();clearTimeout(timer);refresh();}};
      for(const [key,label] of [['all','全部文章'],['bookmark','我的收藏'],['later','稍后阅读'],['read','本人读完'],['feedback','有反馈'],['archived','已归档']]){
        const b=button(filters,label,()=>{clearTimeout(timer);libraryState.filter=key;libraryState.page=1;return refresh();});b.dataset.filter=key;
      }
    }
    const list=node('section',undefined,'reading-history-list');root.append(list);
    const pages=node('div',undefined,'reading-actions');root.append(pages);
    async function refresh(force=false){
      if(turn!==revision)return;
      const serial=++request;const params=new URLSearchParams({kind,page:libraryState.page,page_size:20,filter:libraryState.filter,search:libraryState.search});
      status.textContent=kind==='jobs'?'正在读取历史搜集记录…':'正在读取历史文章…';status.classList.add('reading-loading');list.setAttribute('aria-busy','true');
      let slow=setTimeout(()=>{if(turn===revision&&serial===request)status.textContent='历史记录读取较慢，请稍候；不会重新搜集文章。';},8000);
      for(const b of filters.querySelectorAll('button')){const active=b.dataset.filter===libraryState.filter;b.classList.toggle('primary',active);b.setAttribute('aria-pressed',String(active));}
      try{
        const data=await libraryData(params,force);if(turn!==revision||serial!==request)return;
        if(data.page>1&&(data.page-1)*data.page_size>=data.total){libraryState.page=Math.max(1,Math.ceil(data.total/data.page_size));return refresh();}
        list.replaceChildren();pages.replaceChildren();
        status.textContent=`共 ${data.total} ${kind==='jobs'?'次记录':'篇文章'} · 第 ${data.page} 页`;
        if(kind==='jobs'){
          for(const j of data.jobs){const box=node('article',undefined,'reading-card');list.append(box);box.append(node('h3',jobLabels[j.kind]||'阅读任务'),node('p',`${j.created_at} · ${state[j.state]||j.state}`,'desc'));
            if(j.kind==='collect')box.append(node('p',`已找到 ${j.candidate_count} 篇${j.saved_ids?.length?' · 已保存 '+j.saved_ids.length+' 篇':''}`));
            if(j.error)box.append(node('p',j.error,'desc'));button(box,j.kind==='collect'&&j.state==='ready'&&!j.saved_ids?.length?'查看并保存':'查看结果',()=>watch(j.id),true);
          }
        }else for(const a of data.articles){const box=card(a,list);box.append(node('p',a.read?'本人确认读完':'尚未确认读完','desc'));button(box,'本站阅读',()=>read(a.id),true);button(box,ReadingGrowth.hasFeedback(a)?'查看反馈':'写阅读反馈',()=>read(a.id,'feedback'));
          const scheduleControls=node('div');box.append(scheduleControls);window.DailyAgenda?.mount(scheduleControls,{kind:'article',course:a.id},a.zh_title||a.title);
          button(box,a.archived?'恢复':'归档',async()=>{if(!a.archived&&!confirm('归档后可在“已归档”中恢复。'))return;await api('/articles/'+a.id+(a.archived?'/restore':'/archive'),{});await refresh();});
        }
        if(!data.total)list.append(node('p',libraryState.search?'没有匹配的历史文章，可更换关键词或筛选。':kind==='jobs'?'还没有搜集记录。':'这里还没有文章，可以切换筛选，或搜集、添加文章。','desc'));
        const previous=button(pages,'上一页',()=>{--libraryState.page;return refresh();});previous.disabled=data.page<=1;
        const next=button(pages,'下一页',()=>{++libraryState.page;return refresh();});next.disabled=data.page*data.page_size>=data.total;
      }catch(error){if(turn!==revision||serial!==request)return;status.textContent=error.message;pages.replaceChildren();button(pages,'重试读取历史',()=>refresh(true),true);}
      finally{clearTimeout(slow);if(turn===revision&&serial===request){status.classList.remove('reading-loading');list.removeAttribute('aria-busy');}}
    }
    await refresh();
  }
  window.loadReadingHistory=loadHistory;
  function preferenceFields(parent,p,includeSchedule,availableTopics){
    const box=node('div',undefined,'plan-grid');parent.append(box);const count=field(box,'推荐数量（1—8篇）',p.count,'number');count.min=1;count.max=8;
    const mode=select(box,'文章类型',[['mixed','近期＋经典'],['recent','近期精选（30天内）'],['classic','经典重读']],p.mode);
    const topics=[],languages=[];const topicBox=node('fieldset');topicBox.append(node('legend','感兴趣的主题'));parent.append(topicBox);
    for(const value of availableTopics){const el=field(topicBox,value,'','checkbox');el.checked=p.topics.includes(value);topics.push([value,el]);}
    const languageBox=node('fieldset');languageBox.append(node('legend','文章语言'));parent.append(languageBox);for(const [value,label] of [['zh','中文'],['en','英文（可生成中文导读）']]){const el=field(languageBox,label,'','checkbox');el.checked=p.languages.includes(value);languages.push([value,el]);}
    let autoGuide;if(includeSchedule){autoGuide=field(parent,'打开英文文章的「中文导读」时自动生成并保存（使用我的个人模型）','','checkbox');autoGuide.checked=!!p.auto_guide;}
    let enabled,hour,minute;if(includeSchedule){enabled=field(parent,'启用每日搜集','','checkbox');enabled.checked=p.enabled;const time=node('div',undefined,'plan-grid');parent.append(time);hour=field(time,'北京时间：小时',p.hour,'number');minute=field(time,'分钟',p.minute,'number');}
    return ()=>({...p,count:Number(count.value),mode:mode.value,topics:topics.filter(([,x])=>x.checked).map(([v])=>v),languages:languages.filter(([,x])=>x.checked).map(([v])=>v),...(includeSchedule?{enabled:enabled.checked,hour:Number(hour.value),minute:Number(minute.value),auto_guide:autoGuide.checked}:{})});
  }
  async function settings(){const status=shell('阅读偏好与来源');const turn=revision;button(root,'返回阅读',window.loadReading);const data=await api();if(turn!==revision)return;const get=preferenceFields(root,data.preferences,true,data.topics);
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
  function collectForm(preset){const status=shell('帮我找文章');const turn=revision;button(root,'返回阅读',window.loadReading);
    const cached=preferenceCache?.account===accountKey()?preferenceCache:null;
    const form=node('section');root.append(form);let edited=false;
    form.addEventListener('input',()=>{edited=true;});form.addEventListener('change',()=>{edited=true;});

    // 先渲染基础表单，使用默认值或缓存
    const initialData={...defaultPreferences,...(preset||cached?.preferences)};
    const query=field(form,'主题或关键词（可留空，例如：科技、心理、社会、decision）',initialData.query||'');
    form.append(node('p','在已配置来源的标题与摘要中筛选，中文主题会扩展为英文关键词。复杂问题建议提取核心关键词。','desc'));
    let getFn;
    const tempGet=preferenceFields(form,initialData,false,cached?.topics||defaultTopics);
    button(form,'开始查找',()=>start({...tempGet(),query:query.value}),true);

    if(preset||cached){status.textContent='调整条件后即可开始查找。';return;}

    // 异步加载偏好，更新表单
    status.textContent='正在读取你的偏好，条件已可调整…';status.classList.add('reading-loading');
    const account=accountKey();
    async function refresh(){try{const data=await api('/setup');if(turn!==revision||account!==accountKey())return;
      preferenceCache={account,preferences:data.preferences,topics:data.topics};
      if(!edited){
        // 更新表单值而不重建
        query.value=data.preferences.query||'';
      }
      status.textContent=edited?'已保留你正在调整的条件。':'已载入你的阅读偏好。';
    }catch(error){if(turn!==revision)return;status.textContent='偏好暂未载入，可继续使用当前条件查找。';
    }finally{if(turn===revision)status.classList.remove('reading-loading');}}
    void refresh();
  }
  async function importForm(){
    shell('添加文章');const turn=revision;button(root,'返回阅读',window.loadReading);
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
  function startupView(request){
    const status=shell('正在启动查找');request.turn=revision;
    status.textContent='正在创建查找任务…';status.classList.add('reading-loading');status.setAttribute('aria-live','polite');
    button(root,'返回阅读',window.loadReading);
    const box=node('section',undefined,'reading-startup');root.append(box);
    box.append(node('p',`${request.preferences.query?'关键词：'+request.preferences.query+' · ':''}${category[request.preferences.mode]} · ${request.preferences.languages.map(value=>value==='en'?'英文':'中文').join('、')} · 最多 ${request.preferences.count} 篇`,'desc'));
    const steps=node('ol',undefined,'reading-startup-steps');
    for(const [i,label] of ['提交任务','读取来源','筛选与预览'].entries()){const step=node('li',label);if(i===0)step.setAttribute('aria-current','step');steps.append(step);}box.append(steps);
    box.append(node('p','正在提交你的查找条件，确认后会自动显示来源读取进展。','desc'),node('p','可以返回阅读，启动请求会继续处理。','desc'));
    return status;
  }
  function start(p,key){
    if(starting){startupView(starting);return starting.promise;}
    if(!Number.isInteger(p.count)||p.count<1||p.count>8)throw new Error('请选择 1—8 篇文章。');
    if(!p.topics.length||!p.languages.length)throw new Error('请至少选择一个主题和一种文章语言。');
    const request={key:key||crypto.randomUUID(),preferences:{...p,topics:[...p.topics],languages:[...p.languages]}};
    startupView(request);starting=request;
    request.promise=(async()=>{
      try{
        const job=await api('/collect',{key:request.key,preferences:request.preferences});
        if(request.turn===revision&&root.style.display!=='none')await watch(job.id,job);
        else toast('文章查找已开始，可从阅读查看。');
      }catch(error){
        if(request.turn!==revision||root.style.display==='none'){toast('查找启动暂未确认，请返回阅读查看。');return;}
        root.querySelector('h2').textContent='启动查找遇到问题';
        const status=root.querySelector('[role=status]');status.classList.remove('reading-loading');
        status.textContent=error instanceof TypeError?'连接暂时中断，请检查网络后重试。':error.message;
        root.querySelector('.reading-startup').replaceChildren(node('p','查找条件已保留。重试会使用同一请求编号，避免重复创建任务。','desc'));
        button(root,'重试启动',()=>start(request.preferences,request.key),true);
        button(root,'调整条件',()=>collectForm(request.preferences));
      }finally{if(starting===request)starting=null;}
    })();
    return request.promise;
  }
  async function watch(id,initialJob){const status=shell('搜集与导读结果','job',id);status.textContent='正在读取已保存的搜集结果…';status.classList.add('reading-loading');const turn=revision;watching.set(id,turn);button(root,'返回阅读',window.loadReading);const cancel=button(root,'取消任务',async()=>{await api('/jobs/'+id+'/cancel',{});await poll();});cancel.hidden=true;const content=node('section');root.append(content);let delay=1500;
    async function poll(initial){try{const j=initial||await api('/jobs/'+id);if(watching.get(id)!==turn)return;const current=turn===revision&&root.style.display!=='none';const active=['queued','running'].includes(j.state);
      window.ReadingTasks?.track(j);
      if(current){if(j.kind==='collect')root.querySelector('h2').textContent=active?'正在查找文章':j.state==='ready'?'查找完成':j.state==='cancelled'?'查找已取消':'查找未完成';status.classList.toggle('reading-loading',active);status.textContent=(active?(j.phase||state[j.state]):state[j.state])+(j.error?' · '+j.error:'');cancel.hidden=!active;content.replaceChildren();
        if(active){content.append(node('p',j.kind==='collect'?'正在核对来源与日期，结果会去重后显示。':'正在生成中文导读，原资料和个人笔记不会被替换。'));if(j.raw)content.append(node('pre',j.raw,'reading-stream'));}
        for(const s of j.sources||[])content.append(node('p',`${s.name}：${s.error||'读取'+s.count+'条'}`,'desc'));for(const warning of j.warnings||[])content.append(node('p',warning,'reading-warning'));
        if(!active&&['guide','summary','english'].includes(j.kind)&&j.state==='ready')button(content,'查看'+jobLabels[j.kind],()=>read(j.article_id,j.kind),true);
        if(!active&&j.kind==='fetch_full'&&j.state==='ready')button(content,'阅读文章正文',()=>read(j.article_id),true);
        if(!active&&j.kind==='collect'&&j.state==='ready'){
          if(j.readable_only)content.append(node('p',`这 ${j.candidates.length} 篇文章均已取得可读正文。保存时会把正文一起保存，之后可直接在本站阅读。`,'desc'));
          const savedIds=new Set(j.saved_ids||[]),saved=savedIds.size>0;
          const selected=[];for(const a of j.candidates){const box=card(a,content);if(!saved){const preview=node('details');preview.append(node('summary','本站预览正文'));if(a.full_content?.length>=100&&(!/\.pdf(?:$|[?#])/i.test(a.url)||a.content_version===2))markdown(preview,a.full_content);else preview.append(node('p','本次未取得正文。保存后可在本站尝试重新加载；当前仅有来源摘要。','desc'));box.append(preview);const el=field(box,'保存这篇文章','','checkbox');el.checked=true;selected.push([a.id,el]);}else if(savedIds.has(a.id))button(box,'本站阅读',()=>read(a.id),true);else box.append(node('p','本次未选中保存。','desc'));}
          if(saved)content.append(node('p',`已保存 ${savedIds.size} 篇，可从历史文章继续阅读。`,'desc'));
          else button(content,'保存选中的文章与资料',async()=>{status.textContent='正在保存文章与正文…';status.classList.add('reading-loading');
            try{const saved=await api('/jobs/'+id+'/save',{ids:selected.filter(([,e])=>e.checked).map(([aid])=>aid)});if(turn===revision)await watch(id,saved);else toast('文章已保存，可从阅读打开。');}
            finally{if(turn===revision)status.classList.remove('reading-loading');}
          },true);
        }
        if(!active&&j.state!=='ready'&&j.kind==='collect')button(content,'调整条件重新搜集',collectForm);
      }
      if(active){delay=1500;setTimeout(poll,current?1500:10000);}else if(!current)toast(j.state==='ready'?'阅读任务已完成，可返回查看。':'阅读任务未完成，请查看记录。');
    }catch(e){if(watching.get(id)!==turn)return;if(turn===revision)status.textContent='暂时无法读取，正在重新连接；不会重复搜集。';delay=Math.min(delay*2,15000);setTimeout(poll,delay);}}
    await poll(initialJob);
  }
  async function read(id,requestedView){const status=shell('文章阅读','article',id);lastArticle={id,view:requestedView||'original'};const turn=revision;if(readingOrigin){const origin=readingOrigin;button(root,origin.tab==='personal'?'返回今日':'返回日程',()=>{if(goTab(origin.tab)===false)return;requestAnimationFrame(()=>{window.scrollTo({top:origin.scroll,behavior:'instant'});if(origin.focus?.isConnected)origin.focus.focus();});});}button(root,'返回历史文章',()=>loadHistory('articles'));button(root,'我的生词本',()=>vocabPage(id));
    // 显示明显的加载状态
    status.textContent='正在加载文章与正文…';status.classList.add('reading-loading');
    const loadingBox=node('div',undefined,'reading-loading-overlay');
    loadingBox.innerHTML='<div class="reading-loading-spinner"></div><p class="reading-loading-text">正在加载文章，请稍候…</p>';
    root.append(loadingBox);
    let d;
    try{d=await api('/articles/'+id);}catch(error){if(turn!==revision)return;loadingBox.remove();status.classList.remove('reading-loading');status.textContent=error.message;button(root,'重试加载文章',()=>read(id,requestedView),true);return;}
    if(turn!==revision)return;loadingBox.remove();status.classList.remove('reading-loading');const a=d.article;root.querySelector('h2').textContent=a.zh_title||a.title;status.textContent=`${a.source} · ${a.language==='zh'?'中文':'英文'} · ${a.access}`;

    window.ReadingTasks?.nameArticle(id,a.zh_title||a.title);
    // 操作按钮区
    const actions=node('div',undefined,'reading-actions');root.append(actions);

    // 收藏、稍后阅读、完成状态
    for(const [key,label] of [['bookmarked',a.bookmarked?'取消收藏':'收藏'],['read_later',a.read_later?'移出稍后阅读':'稍后阅读'],['read',a.read?'改为尚未读完':'本人确认读完']])button(actions,label,async()=>{await api('/articles/'+id+'/personal',{[key]:!a[key]});a[key]=!a[key];toast('阅读状态已保存，笔记输入保留。');const b=actions.querySelectorAll('button');const index=['bookmarked','read_later','read'].indexOf(key);b[index].textContent=key==='bookmarked'?(a[key]?'取消收藏':'收藏'):key==='read_later'?(a[key]?'移出稍后阅读':'稍后阅读'):(a[key]?'改为尚未读完':'本人确认读完');});

    root.append(node('p','可直接阅读；安排到今日用于列入日程和追踪完成，不是开始阅读的前提。','desc'));
    const scheduleControls=node('div');root.append(scheduleControls);window.DailyAgenda?.mount(scheduleControls,{kind:'article',course:id},a.zh_title||a.title);

    // Reading views
    const tabBox=node('div',undefined,'reading-tabs');root.append(tabBox);
    if(a.read||window.actionContentOrigin?.target?.course===id)button(actions,'确认本次读完',async()=>{await api('/articles/'+id+'/personal',{read:true});a.read=true;toast('本次读完确认已保存。');});
    const views=['original','guide','bilingual','summary','english','notes','feedback'];
    const viewLabels={guide:'中文导读',original:'文章正文',bilingual:'双语',summary:'总结',english:'英语解析',notes:'我的笔记',feedback:'阅读反馈'};
    let currentView=requestedView||'original';
    const viewContents={};let bodyReader;
    for(const v of views){const btn=node('button',viewLabels[v],'btn'+(v===currentView?' primary':''));btn.type='button';btn.onclick=()=>{currentView=v;lastArticle={id,view:v};if(v==='guide')ensureGuide();if(v==='original')bodyReader?.open();for(const v2 of views){viewContents[v2].style.display=v2===v?'':'none';tabBox.querySelectorAll('button')[views.indexOf(v2)].className='btn'+(v2===v?' primary':'');}};tabBox.append(btn);}

    const isCurrent=()=>turn===revision&&root.style.display!=='none';
    const guideView=node('section',undefined,'article-guide-box');root.append(guideView);viewContents.guide=guideView;
    let guideMounted=false;function ensureGuide(){if(guideMounted)return;guideMounted=true;ReadingGrowth.guide(guideView,a,d,{api,node,button,markdown,isCurrent,onSaved:saved=>{Object.assign(a,saved);root.querySelector('h2').textContent=a.zh_title||a.title;}});}
    if(currentView==='guide')ensureGuide();

    // Original view
    const originalView=node('section',undefined,'article-content-box');root.append(originalView);viewContents.original=originalView;
    let refreshBilingual=()=>{};
    bodyReader=ReadingBody.mount(originalView,a,d,{autoStart:currentView==='original',api,node,button,markdown,isCurrent,onSaved:fresh=>{d.full_text=fresh.full_text;d.content_needs_refresh=fresh.content_needs_refresh;a.full_content=fresh.article.full_content;a.content_version=fresh.article.content_version;a.hashes={...a.hashes,...fresh.article.hashes};refreshBilingual();},onRendered:body=>{setupVocabSelection(body,id,a);window.ReadingPosition?.mount(body,id,()=>isCurrent()&&currentView==='original');}});

    // Bilingual view
    const bilingualView=node('section',undefined,'article-content-box');root.append(bilingualView);viewContents.bilingual=bilingualView;
    bilingualView.style.display='none';
    bilingualView.append(node('h3','双语对照'));
    refreshBilingual=()=>{bilingualView.replaceChildren(node('h3','双语对照'));
    if(d.full_text&&!(d.content_needs_refresh&&/\.pdf(?:$|[?#])/i.test(a.url))){
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
    };refreshBilingual();

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
    function generationControl(parent,label,kind,field,section,selector){
      const progress=node('p','','desc');progress.setAttribute('role','status');parent.append(progress);
      const generate=button(parent,label,()=>run(),true);
      async function run(existing){
        if(dirty?.()&&!existing)throw new Error('请先保存笔记和反馈，再生成。');
        generate.disabled=true;progress.textContent='正在生成，可切换页面；进度和结果保留在右下角生成任务中。';
        try{
          let job=existing||await (window.ReadingTasks?window.ReadingTasks.start(id,kind,{key:crypto.randomUUID()},a.zh_title||a.title):api('/articles/'+id+'/'+kind,{key:crypto.randomUUID()}));
          if(window.ReadingTasks)await window.ReadingTasks.wait(job,j=>{if(isCurrent())progress.textContent=(j.phase||'正在生成…')+' 可切换页面，任务会继续。';});
          else{while(['queued','running'].includes(job.state)){await new Promise(resolve=>setTimeout(resolve,1500));job=await api('/jobs/'+job.id);}if(job.state!=='ready')throw new Error(job.error||'生成未完成');}
          if(!isCurrent())return;
          const fresh=await api('/articles/'+id);if(!isCurrent())return;
          section.querySelector(selector)?.remove();const result=node('div',undefined,selector.slice(1));markdown(result,fresh[field]||'生成结果已保存，可重新打开查看。');section.insertBefore(result,parent);
          progress.textContent='已生成并保存，可随时返回查看。';
        }catch(error){if(isCurrent())progress.textContent=error.message;}
        finally{generate.disabled=false;}
      }
      const existing=window.ReadingTasks?.find(id,kind);if(existing)run(existing);
    }
    generationControl(summaryBtnBox,'生成/更新中文总结','summary','summary',summaryView,'.article-summary');

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
      generationControl(englishBtnBox,'生成/更新英语学习材料','english','english_learning',englishView,'.article-english');
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
    generationControl(guideBtnBox,'生成/更新AI导读','guide','guide',notesView,'.article-guide');

    // 个人笔记
    notesView.append(node('h3','我的思考与笔记'));
    const notes=field(notesView,'',d.note.text,'textarea');notes.rows=7;notes.placeholder='哪个观点改变了我的假设？哪些证据还不够？我的思考和疑问...';dirty=()=>notes.value!==d.note.text;
    button(notesView,'保存笔记',async()=>{const submitted=notes.value;const saved=await api('/articles/'+id+'/personal',{note:submitted,note_hash:d.note.hash});d.note.text=submitted;d.note.hash=saved.note_hash;toast('笔记已保存');},true);

    const feedbackView=node('section',undefined,'article-guide-box');root.append(feedbackView);viewContents.feedback=feedbackView;
    const feedbackDirty=ReadingGrowth.feedback(feedbackView,a,{api,node,button,field,isCurrent,onSaved:saved=>{Object.assign(a,{feedback:saved.feedback,read:saved.read});actions.querySelectorAll('button')[2].textContent=a.read?'改为尚未读完':'本人确认读完';}});
    dirty=()=>notes.value!==d.note.text||feedbackDirty();
    for(const view of views)viewContents[view].style.display=view===currentView?'':'none';

    const provenance=node('details');provenance.append(node('summary','文章来源与存储位置'));original(provenance,a);root.append(provenance);
    if(d.github_url){const link=node('a','在 GitHub 打开资料');link.href=d.github_url;link.target='_blank';link.rel='noopener noreferrer';provenance.append(link);}else provenance.append(node('p','资料位置：'+d.path,'desc'));
  }
  function setupVocabSelection(container,articleId,article){
    if(container.dataset.vocabSelection)return;container.dataset.vocabSelection='1';
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
    button(root,'返回阅读',window.loadReading);
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
  window.openActionArticle=(id,origin)=>{readingOrigin=origin||null;return read(id);};
  window.enterReading=()=>{
    const m=location.hash.match(/^#reading\/(job|article)\/([a-zA-Z0-9-]+)$/);
    if(m){
      // 如果有特定的 job 或 article hash，显示对应内容
      return m[1]==='job'?watch(m[2]):read(m[2]);
    }
    const saved=location.hash.match(/^#reading\/history\/(articles|jobs)$/);
    if(saved)return loadHistory(saved[1]);
    if(lastArticle)return read(lastArticle.id,lastArticle.view);
    return window.loadReading();
  };
  window.ReadingTasks?.initialize({api,open:async job=>{
    if(goTab('reading')===false)return false;
    if(job.state==='ready'&&job.article_id)return read(job.article_id,['guide','summary','english'].includes(job.kind)?job.kind:'original');
    return watch(job.id,job);
  }});
  window.addEventListener('load',()=>{if(location.hash.startsWith('#reading/'))goTab('reading');});
})();
