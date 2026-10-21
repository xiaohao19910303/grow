/* Account-scoped generation tasks, independent of the current page and producer. */
(() => {
  'use strict';
  const jobs=new Map(),pending=new Map(),timers=new Map(),listeners=new Map(),dismissed=new Set(),providers=new Map();
  const labels={collect:'文章搜集',guide:'中文导读',summary:'中文总结',english:'英语解析',fetch_full:'文章正文'};
  const states={queued:'等待开始',running:'生成中',ready:'已完成',failed:'生成失败',cancelled:'已取消',interrupted:'进度待核对'};
  const active=job=>['queued','running','generating'].includes(job.state);
  const success=job=>['ready','published','adopted'].includes(job.state);
  const label=job=>job.label||labels[job.kind]||'生成任务';
  let api,open,account='',box,list,toggle,notice,preparing;
  const node=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;};
  const key=()=> 'grow-reading-tasks:'+account;
  function save(){try{const retained=[...jobs.values()].filter(active).concat([...jobs.values()].filter(job=>!active(job)).slice(-30));localStorage.setItem(key(),JSON.stringify(retained.map(({id,kind,state,article_id,title,seen,source,ref,module,draft_id,lesson_no,label,result_id,entry_id,plan_id})=>({id,kind,state,article_id,title,seen,source,ref,module,draft_id,lesson_no,label,result_id,entry_id,plan_id}))));}catch{}}
  function action(parent,label,run){const b=node('button',label,'btn');b.type='button';b.onclick=()=>Promise.resolve(run()).catch(e=>{notice.textContent=e.message;});parent.append(b);return b;}
  function mount(){if(box)return;box=node('aside',undefined,'reading-task-center');box.id='readingTaskCenter';box.setAttribute('aria-label','生成任务中心');
    const details=node('details');toggle=node('summary','生成任务','btn reading-task-toggle');toggle.setAttribute('aria-controls','readingTaskList');details.append(toggle);box.append(details);
    notice=node('p','','reading-task-notice');notice.setAttribute('role','status');notice.setAttribute('aria-live','polite');details.append(notice);
    list=node('div',undefined,'reading-task-list');list.id='readingTaskList';details.append(list);const dock=document.getElementById?.('floatingPanels');if(dock)dock.prepend(box);else document.body.append(box);
  }
  function render(){mount();box.hidden=!jobs.size;const running=[...jobs.values()].filter(active).length,unread=[...jobs.values()].filter(j=>success(j)&&!j.seen).length;
    toggle.textContent=`生成任务${running?' · '+running+' 项进行中':unread?' · '+unread+' 项已完成':''}`;
    list.replaceChildren();
    for(const job of [...jobs.values()].reverse()){
      const row=node('section',undefined,'reading-task-item');row.append(node('strong',label(job)),node('p',job.title||(job.source?label(job):job.kind==='collect'?'搜集文章':'阅读文章'),'desc'),node('p',job.connectionError||(active(job)?job.phase:null)||states[job.state]||(success(job)?'已完成':job.state==='generating'?'生成中':job.state),'desc'));
      if(job.error)row.append(node('p',job.error,'reading-warning'));
      action(row,success(job)?'查看结果':'查看进度',async()=>{const provider=providers.get(job.source||'reading');if(!provider)throw new Error('任务入口正在恢复，请稍后再试。');if(await provider.open(job)!==false){job.seen=true;save();render();}});
      if(active(job)&&providers.get(job.source||'reading')?.cancel)action(row,'取消生成',async()=>track(await providers.get(job.source||'reading').cancel(job)));
      else if(!active(job))action(row,'移除记录',()=>{jobs.delete(job.id);dismissed.add(job.id);try{localStorage.setItem(key()+':dismissed',JSON.stringify([...dismissed].slice(-100)));}catch{}save();render();});
      list.append(row);
    }
  }
  function track(job,metadata={}){
    if(!job?.id||!job.kind||!job.state||!account)return job;
    const previous=jobs.get(job.id);if(previous&&!active(previous)&&active(job))return previous;
    const entry={...previous,...job,...metadata};jobs.set(job.id,entry);
    const completed=[...jobs.values()].filter(item=>!active(item));for(const old of completed.slice(0,-30))if(old.id!==entry.id)jobs.delete(old.id);
    if(previous&&active(previous)&&!active(entry)){
      entry.seen=false;notice.textContent=`${label(entry)}${success(entry)?'已完成，可查看结果。':entry.state==='cancelled'?'已取消。':'未完成，请查看原因。'}`;
      if(success(entry))window.toast?.(notice.textContent);
    }
    save();render();for(const callback of listeners.get(job.id)||[])callback(entry);
    if(active(entry)&&providers.get(entry.source||'reading')?.read&&!timers.has(job.id))timers.set(job.id,setTimeout(()=>{timers.delete(job.id);poll(job.id);},2000));
    if(!active(entry)&&timers.has(job.id)){clearTimeout(timers.get(job.id));timers.delete(job.id);}
    return entry;
  }
  async function poll(id){
    try{const job=jobs.get(id),provider=providers.get(job?.source||'reading');if(!provider?.read)return;track(await provider.read(job),{connectionError:''});}
    catch(error){const job=jobs.get(id);if(!job||!active(job))return;job.connectionError='连接暂时中断，正在重试；不会重新生成。';render();timers.set(id,setTimeout(()=>{timers.delete(id);poll(id);},8000));}
  }
  function find(article,kind){return [...jobs.values()].reverse().find(j=>j.article_id===article&&j.kind===kind&&active(j));}
  function nameArticle(article,title){let changed=false;for(const job of jobs.values())if(job.article_id===article&&job.title!==title){job.title=title;changed=true;}if(changed){save();render();}}
  async function start(article,kind,values={},title=''){
    const identity=article+':'+kind;
    if(pending.has(identity))return pending.get(identity);
    const existing=find(article,kind);if(existing)return existing;
    const request=api('/articles/'+article+'/'+kind,values).then(job=>track(job,{title,article_id:article}));pending.set(identity,request);
    try{return await request;}finally{pending.delete(identity);}
  }
  async function wait(job,onUpdate){
    track(job);if(!active(job)){if(job.state!=='ready')throw new Error(job.error||'生成未完成');return job;}
    return new Promise((resolve,reject)=>{
      const changed=current=>{onUpdate?.(current);if(active(current))return;listeners.get(job.id)?.delete(changed);current.state==='ready'?resolve(current):reject(new Error(current.error||'生成已取消或失败'));};
      if(!listeners.has(job.id))listeners.set(job.id,new Set());listeners.get(job.id).add(changed);onUpdate?.(job);
    });
  }
  function external(source,job,metadata={}){
    const {id,kind,state,status,phase,error,draft_id,lesson_no,raw,result_id}=job;
    return {id:source+':'+id,ref:id,source,kind:kind||source,state:state||status,phase,error,draft_id,lesson_no,raw,result_id,...metadata};
  }
  function forget(id){if(!jobs.delete(id))return;clearTimeout(timers.get(id));timers.delete(id);save();render();}
  async function prepare(){
    if(preparing)return preparing;
    preparing=(async()=>{
      await window.Account?.ready;account=window.Account?.user?.id||'';if(!account)return;
      mount();
      try{for(const id of JSON.parse(localStorage.getItem(key()+':dismissed')||'[]'))dismissed.add(id);}catch{}
      try{for(const job of JSON.parse(localStorage.getItem(key())||'[]'))track(job);}catch{}
      render();
    })();
    return preparing;
  }
  async function register(source,provider){
    providers.set(source,provider);await prepare();if(!account)return;
    for(const job of jobs.values())if((job.source||'reading')===source&&active(job))track(job);
    if(provider.recover)try{for(const job of await provider.recover())if(!dismissed.has(job.id))track(job);}catch{}
  }
  async function initialize(options){
    api=options.api;open=options.open;
    await register('reading',{read:job=>api('/jobs/'+job.id),open,cancel:job=>api('/jobs/'+job.id+'/cancel',{})});
    if(!account)return;
    try{const recent=await api('/library?kind=jobs&page_size=50');await Promise.all((recent.jobs||[]).filter((job,index)=>(active(job)||index<5)&&!jobs.has(job.id)&&!dismissed.has(job.id)).map(async job=>{try{track(await api('/jobs/'+job.id));}catch{}}));}catch{}
    render();
  }
  window.GenerationTasks=window.ReadingTasks={initialize,track,start,wait,find,nameArticle,register,external,forget};
})();
