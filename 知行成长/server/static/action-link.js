/* Pairing is explicit; connected plans have exactly one server writer. */
(() => {
 const root=document.getElementById('actionLinkSettings');let phase='local',refreshRevision=0;
 const n=(tag,text)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;return el;};
 async function api(path='',body){const r=await fetch('/api/action-link'+path,{method:body?'POST':'GET',cache:'no-store',headers:body?{'Content-Type':'application/json','X-Copilot-Request':'1'}:{},body:body?JSON.stringify(body):undefined});let data;try{data=await r.json();}catch{throw Error('联动连接未完成，请稍后重试。');}if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:data.message||'联动暂未完成。');return data;}
 function button(parent,text,action){const b=n('button',text);b.type='button';b.className='btn';b.onclick=async()=>{b.disabled=true;try{await action();}catch(e){message.textContent=e.message;}finally{b.disabled=false;}};parent.append(b);return b;}
 const message=n('p');message.setAttribute('role','status');
 async function refresh(){const turn=++refreshRevision;const data=await api();if(turn!==refreshRevision)return;phase=data.phase;root.replaceChildren(n('h2','LightTick 客户端联动'),message);message.textContent='';window.MobileLearning?.mount(root);
  if(phase==='active'){root.append(n('p','计划已由 LightTick 统一保存。网页与客户端共享计划、执行记录和复盘，刷新即可查看另一端的更新。'),n('p','已连接账号：'+data.target_user_id),n('p','原网页数据已保留只读备份；断网不会切回另一份可编辑计划。'));button(root,'刷新同步状态',async()=>{await refresh();await window.ActionPlans?.refresh();});return;}
  if(phase==='pending'){root.append(n('p','正在核对接管结果。原数据已保留备份并暂停本地写入，请重试完成联动。'));button(root,'重试接管',async()=>{message.textContent='正在核对接管回执…';await api('/retry',{});await refresh();await window.ActionPlans?.refresh();});return;}
  if(!data.configured){root.append(n('p','联动服务尚未配置，请联系管理员。网页计划仍可正常使用。'));return;}
  root.append(n('p','先在 LightTick 正式账号中打开“行动计划 → 连接网页”，生成连接码，再粘贴到这里。连接码五分钟有效；两边账号分别验证，不按用户名自动合并。'));
  const label=n('label','客户端连接码'),input=n('input');input.autocomplete='off';input.maxLength=36;input.setAttribute('aria-label','客户端连接码');label.append(input);root.append(label);
  const preview=n('div');root.append(preview);
  button(root,'预览联动范围',async()=>{message.textContent='正在验证账号与待接管数据…';const proposal=await api('/preview',{code:input.value.trim()});message.textContent='';preview.replaceChildren(n('p','目标 LightTick 账号：'+proposal.target_user_id),n('p',`将接管 ${proposal.counts.plans} 项计划、${proposal.counts.records} 次执行、${proposal.counts.reviews} 次手动复盘和 ${proposal.counts.reports} 份 AI 历史。课程、笔记与学习完成状态不在此范围内。`));
   if(proposal.snapshot_version===2)preview.append(n('p','同时允许手机查看正式学习计划的整体和阶段进度；课程正文、私人笔记仍由 Grow 保存。日常节奏尚不接管。'));
   const consentLabel=n('label','我确认两个账号都属于本人，同意将上述数据切换为 LightTick 统一保存'),consent=n('input');consent.type='checkbox';consent.setAttribute('aria-label','确认本人账号与接管范围');consentLabel.prepend(consent);preview.append(consentLabel);
   button(preview,'确认接管并联动',async()=>{if(!consent.checked){message.textContent='请先确认账号和接管范围。';return;}message.textContent='正在备份、接管并核对，期间请保留此页面…';await api('/confirm',{code:input.value.trim(),preview_id:proposal.preview_id,consent:true});input.value='';await refresh();await window.ActionPlans?.refresh();});
  });
 }
 window.ActionLink={show:()=>{if(goTab('settings')===false)return;refresh().catch(e=>{message.textContent=e.message;});root.scrollIntoView({block:'start'});},refresh};
 (window.Account?.ready||Promise.resolve()).then(()=>refresh()).catch(e=>{root.replaceChildren(n('h2','LightTick 客户端联动'),message);message.textContent=e.message;button(root,'重试读取联动状态',refresh);});
})();
