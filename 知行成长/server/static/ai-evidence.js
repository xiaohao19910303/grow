/* 私人 AI 输入快照：只读展开，原记录跳转与快照正文分开展示。 */
(() => {
  'use strict';
  const node=(tag,text)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;return el;};
  const states={captured_input:'当时发送的输入',unchanged:'原记录未变化',changed:'原记录已变化',deleted:'原记录已删除',archived:'原记录已归档',unavailable:'原记录暂不可核验',unverifiable:'原记录版本不可核验'};
  function mount(parent,kind,id){
    if(!parent||!id)return;
    const details=node('details');details.className='ai-evidence';details.append(node('summary','分析依据'));parent.append(details);
    let loading=false,loaded=false;
    async function load(){
      if(loading||loaded||!details.open)return;
      loading=true;const owner=window.Account?.user?.id,body=node('div');details.append(body);body.textContent='正在读取本次发送范围…';
      try{
        const response=await fetch('/api/ai/evidence?'+new URLSearchParams({kind,resource_id:String(id)}),{cache:'no-store'});
        if(!response.ok)throw Error('分析依据暂时无法读取，请重试。');
        const data=await response.json();
        if(owner!==window.Account?.user?.id||!details.isConnected)return;
        body.replaceChildren();
        if(data.message)body.append(node('p',data.message));
        for(const snapshot of data.items||[]){
          body.append(node('p',`捕获于 ${snapshot.captured_at} · ${snapshot.timezone} · 模型 ${snapshot.model}`));
          if(snapshot.selection?.period)body.append(node('p','分析范围：'+snapshot.selection.period));
          for(const rule of snapshot.selection?.count_rules||[])body.append(node('p',rule));
          if(snapshot.selection?.scope)body.append(node('p',snapshot.selection.scope));
          if(snapshot.parent_id)body.append(node('p','本次调用关联已有输入或前一阶段，以下显示本次实际发送内容。'));
          for(const source of snapshot.sources){
            const line=node('p',source.label+' · '+(states[source.availability]||'来源状态未知')+' · '+source.scope+(source.truncated?'（已截取）':''));
            if(source.target){const open=node('button','打开当前原记录');open.type='button';open.className='btn';open.onclick=()=>window.RecordDiscovery?.open({target:source.target});line.append(open);}body.append(line);
          }
          const version=node('details');version.append(node('summary','输入版本'));version.append(node('p',`提示词 ${snapshot.prompt_version} · 输入哈希 ${snapshot.input_hash}`));body.append(version);
          const sent=node('details');sent.append(node('summary','查看本次发送内容'));const pre=node('pre');pre.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;max-height:24rem;overflow:auto';
          pre.textContent=snapshot.messages.filter(m=>m.role!=='system').map(m=>m.content).join('\n\n');sent.append(pre);body.append(sent);
        }
        loaded=true;
      }catch(error){body.textContent=error.message;const retry=node('button','重试读取依据');retry.type='button';retry.className='btn';retry.onclick=()=>{body.remove();load();};body.append(retry);}
      finally{loading=false;}
    }
    details.addEventListener('toggle',load);return details;
  }
  function task(parent,job){
    if((job.source||'reading')==='reading'&&!['guide','summary','english'].includes(job.kind))return;
    const kinds={'course-background':'course-background',copilot:'copilot',study:'study',plans:'plans',continuations:'continuations',reflection:'reflection','action-review':'action-review',reading:'reading',investments:'investments','behavior-report':'behavior-report'};
    const kind=kinds[job.source||'reading'];if(kind)mount(parent,kind,job.ref||job.id);
  }
  window.AIEvidence={mount,task};
})();
