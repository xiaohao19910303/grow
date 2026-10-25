/* Records have separate consent from action plans. Text is always rendered as text. */
(()=>{
 const root=document.getElementById('recordLinkSettings');if(!root)return;
 const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
 const message=el('p');message.setAttribute('role','status');
 async function api(path='',body){const r=await fetch('/api/record-link'+path,{method:body?'POST':'GET',cache:'no-store',headers:body?{'Content-Type':'application/json','X-Copilot-Request':'1'}:{},body:body?JSON.stringify(body):undefined});const data=await r.json();if(!r.ok)throw Error(data.message||data.detail||'记录联动尚未确认，请重试。');return data;}
 function button(parent,text,action){const b=el('button',text);b.type='button';b.className='btn';b.onclick=async()=>{b.disabled=true;try{await action();}catch(e){message.textContent=e.message;}finally{b.disabled=false;}};parent.append(b);}
 async function refresh(){const state=await api();root.replaceChildren(el('h2','Grow 记录客户端联动'),message);message.textContent='';
  if(['active','readonly'].includes(state.phase)){if(state.phase==='readonly')root.append(el('p','当前处于只读恢复状态，请先导出最新数据并联系支持；旧数据继续冻结。'));root.append(el('p','记录已由 LightTick 统一保存，网页和客户端共享原文、版本与归档状态。'),el('p','目标账户：'+state.target_user_id),el('p','旧记录与 AI 历史已保留；断网时当前输入保留。'));button(root,'导出全部记录和历史',async()=>{const value=await api('/export'),url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'})),a=el('a');a.href=url;a.download='grow-records-export.json';a.click();URL.revokeObjectURL(url);});return;}
  if(['preparing','frozen'].includes(state.phase)){root.append(el('p','记录交接正在核对，旧数据已暂停写入并完整保留。可重试，不会重复导入。'));const code=el('input');code.placeholder='原目标账户的新连接码（仅旧码过期时填写）';code.setAttribute('aria-label','恢复用连接码');root.append(code);button(root,'重试并核对回执',async()=>{await api('/retry',code.value.trim()?{code:code.value.trim()}:{});await refresh();});button(root,'取消尚未激活的交接',async()=>{await api('/cancel',{});await refresh();});return;}
  if(!state.configured){root.append(el('p','记录联动服务尚未配置，网页记录仍可正常使用。'));return;}
  root.append(el('p','在 LightTick 的“记录 → 连接 Grow 网页”生成五分钟连接码，粘贴到这里。核对后才会转入。行动计划需要单独连接。'));
  const label=el('label','记录连接码'),code=el('input');code.maxLength=36;code.autocomplete='off';code.setAttribute('aria-label','记录连接码');label.append(code);root.append(label);const box=el('div');root.append(box);
  button(root,'预览记录与目标账户',async()=>{const value=await api('/preview',{code:code.value.trim()});box.replaceChildren(el('p','目标账户：'+value.target_user_id),el('p',`转入 ${value.counts.records} 条记录、${value.counts.versions} 个已存版本。旧版未留存的历史版本有 ${value.counts.history_gaps} 个，会如实标明。AI 历史保留只读；旧版缺失的整理依据不作推断，原始历史随导出保留。`));const consent=el('input');consent.type='checkbox';const check=el('label','我确认两个账户属于本人，同意把上述记录交由 LightTick 统一保存');check.prepend(consent);box.append(check);button(box,'确认转入并连接',async()=>{if(!consent.checked)throw Error('请先确认账户和转入范围。');await api('/confirm',{code:code.value.trim(),preview_id:value.preview_id,consent:true});code.value='';await refresh();});});
 }
 (window.Account?.ready||Promise.resolve()).then(refresh).catch(e=>{root.replaceChildren(el('h2','Grow 记录客户端联动'),message);message.textContent=e.message;button(root,'重试读取记录联动',refresh);});
})();
