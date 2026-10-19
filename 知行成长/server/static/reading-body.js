/* Read saved bodies and recover older articles without leaving the reader. */
(() => {
  'use strict';
  let fontSize=18;
  function mount(parent,article,data,{api,node,button,markdown,isCurrent,onSaved,onRendered,autoStart=true}){
    parent.classList.add('reading-body-panel');
    const toolbar=node('div',undefined,'reading-body-toolbar');parent.append(toolbar);
    toolbar.append(node('h3','文章正文'));
    const sizes=node('div',undefined,'reading-font-controls');sizes.setAttribute('role','group');sizes.setAttribute('aria-label','正文字号');toolbar.append(sizes);
    const smaller=node('button','A−','btn');smaller.type='button';smaller.onclick=()=>resize(-1);smaller.setAttribute('aria-label','缩小正文字号');sizes.append(smaller);
    const sizeLabel=node('span');sizeLabel.setAttribute('aria-live','polite');sizes.append(sizeLabel);
    const larger=node('button','A＋','btn');larger.type='button';larger.onclick=()=>resize(1);larger.setAttribute('aria-label','放大正文字号');sizes.append(larger);
    function resize(delta){fontSize=Math.max(16,Math.min(24,fontSize+delta));parent.style.setProperty('--reading-font-size',fontSize+'px');sizeLabel.textContent=fontSize+' px';smaller.disabled=fontSize===16;larger.disabled=fontSize===24;}
    resize(0);
    const status=node('p','','desc');status.setAttribute('role','status');status.setAttribute('aria-live','polite');parent.append(status);
    const body=node('div',undefined,'article-full-content');parent.append(body);
    const controls=node('div',undefined,'reading-actions');parent.append(controls);
    let running=false,key=null,job=data.content_job;
    const retry=button(controls,'重新加载正文',()=>load());
    function render(fresh){
      const text=fresh.full_text||fresh.article.full_content;
      const legacyPdf=fresh.content_needs_refresh&&/\.pdf(?:$|[?#])/i.test(fresh.article.url);
      body.replaceChildren();
      const imported=['paste','url'].includes(fresh.article.import_method);
      if(text&&(text.length>=100||imported)&&!legacyPdf){
        markdown(body,text);
        // Repair ornamental rules after rendering, preserving literal code.
        for(const list of body.querySelectorAll('ul'))if(list.children.length===1&&/^\s*(?:\*\s*){2,}$/.test(list.textContent))list.replaceWith(node('hr'));
        body.setAttribute('lang',fresh.article.language==='en'?'en':'zh-CN');onRendered(body);return true;
      }
      body.append(node('h4','来源摘要（不是正文）'),node('p',fresh.article.summary||'来源未提供摘要。'));
      return false;
    }
    const hasBody=render(data),needsBody=data.content_needs_refresh||!hasBody;
    status.textContent=hasBody?'已保存的正文，可直接在本站阅读。':'正文尚未保存。';
    retry.hidden=!needsBody;
    async function load(){
      if(running)return;running=true;retry.hidden=false;retry.disabled=true;parent.setAttribute('aria-busy','true');
      status.textContent=hasBody?'正在更新旧版正文，已保存的文字和笔记会保留…':'正在加载正文，完成后会自动保存在你的文章资料中…';
      try{
        if(!job||!['queued','running'].includes(job.state)){
          // Retain this key after an uncertain network result, so retry cannot
          // create a second request for the same attempt.
          if(!key)key='body-'+crypto.randomUUID();
          job=await api('/articles/'+article.id+'/fetch_full',{key});
        }
        while(['queued','running'].includes(job.state)){
          if(!isCurrent())return;
          await new Promise(resolve=>setTimeout(resolve,1500));
          job=await api('/jobs/'+job.id);
        }
        if(!isCurrent())return;
        if(job.state!=='ready'){
          key=null;
          throw new Error(job.error||'正文未能加载，可稍后在本站重试。');
        }
        const fresh=await api('/articles/'+article.id);if(!isCurrent())return;
        if(!render(fresh))throw new Error('正文还未保存成功，请重试。');
        onSaved(fresh);status.textContent='正文已保存，可直接在本站阅读。';retry.hidden=true;
      }catch(error){
        if(isCurrent())status.textContent=error.message+' 当前文章和未保存的笔记仍保留。';
      }finally{running=false;retry.disabled=false;parent.removeAttribute('aria-busy');}
    }
    let opened=false;
    function open(){if(opened||!needsBody)return;opened=true;
      if(job&&['failed','cancelled'].includes(job.state))status.textContent=(job.error||'上次加载未完成。')+' 可在本站重试；摘要不是正文。';
      else queueMicrotask(()=>{if(isCurrent())load();});
    }
    if(autoStart)open();
    return {open};
  }
  window.ReadingBody={mount};
})();
