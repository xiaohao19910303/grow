/* A separate, revocable reading scope. No automatic account or content adoption. */
(() => {
 const n=(tag,text)=>{const e=document.createElement(tag);if(text)e.textContent=text;return e;};
 async function api(path='',body){const r=await fetch('/api/mobile-learning'+path,{method:body?'POST':'GET',cache:'no-store',headers:body?{'Content-Type':'application/json','X-Copilot-Request':'1','X-Grow-Action-Schema':'2'}:{},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw Error(d.message||d.detail||'课程阅读连接暂未完成。');return d;}
 window.MobileLearning={mount:async parent=>{
  const box=n('section');parent.append(box);const status=n('p');box.append(n('h3','手机原生课程阅读'),status);
  try{const data=await api();if(!data.available){status.textContent='手机课程阅读连接暂未配置，网页学习可继续使用。';return;}status.textContent=data.enabled?'已允许同步英文阅读与正式计划的已发布正文/参考资料，手机可保存离线副本。':'课程正文需要单独允许；已有行动或记录连接不会自动授权。';
   if(data.enabled){const privateLabel=n('label'),privateCheck=n('input');privateCheck.type='checkbox';privateCheck.setAttribute('aria-label','确认私人学习范围');privateLabel.append(privateCheck,document.createTextNode(data.private_enabled?'确认撤回手机私人学习授权':'允许手机读取和保存本人私人笔记、练习答案、阅读位置，并按本人操作确认学完；不改变课程发布归属'));box.append(privateLabel);const privateButton=n('button',data.private_enabled?'撤回私人学习授权':'允许私人学习同步');privateButton.className='btn';privateButton.type='button';box.append(privateButton);privateButton.onclick=async()=>{if(!privateCheck.checked){status.textContent='请单独确认私人学习范围。';return;}privateButton.disabled=true;try{await api('/private-consent',{enabled:!data.private_enabled,consent:true});status.textContent='私人学习范围已保存，后台正在同步；手机收到来源回执后才显示已保存或已学完。';}catch(e){status.textContent=e.message;privateButton.disabled=false;}};}
   const label=n('label'),check=n('input');check.type='checkbox';check.setAttribute('aria-label','确认课程正文阅读范围');label.append(check,document.createTextNode(data.enabled?'确认撤回手机课程阅读授权':'允许同步已发布课程正文与参考资料；不含私人笔记、题下答案和生成草稿'));box.append(label);
   box.append(n('p','撤回后，在线手机会清理镜像；旧离线副本需在该手机清理。阅读位置只保存在设备，阅读不会标记学完。'));
   let code,proposal;if(!data.connected){const label=n('label','手机课程连接码');code=n('input');code.autocomplete='off';code.maxLength=80;code.setAttribute('aria-label','手机课程连接码');label.append(code);box.append(label);const verify=n('button','验证课程连接码');verify.type='button';verify.className='btn';box.append(verify);verify.onclick=async()=>{verify.disabled=true;try{proposal=await api('/preview',{code:code.value.trim()});status.textContent='目标客户端账户：'+proposal.target_user_id+'。请核对手机账户后确认课程阅读范围。';check.checked=false;}catch(e){status.textContent=e.message;}finally{verify.disabled=false;}};box.append(n('p','在手机“学习与接续”生成连接码。此连接只同步课程，不迁移行动或日常节奏。'));}
   const button=n('button',data.enabled?'撤回课程阅读':data.connected?'允许手机阅读课程':'连接并允许课程阅读');button.type='button';button.className='btn';button.disabled=!data.available;box.append(button);
   button.onclick=async()=>{if(!check.checked){status.textContent='请先确认课程阅读范围。';return;}button.disabled=true;try{if(data.connected)await api('/consent',{enabled:!data.enabled,consent:true});else {if(!proposal)throw Error('请先验证连接码并核对目标账户。');await api('/connect',{code:code.value.trim(),preview_id:proposal.preview_id,consent:true});}status.textContent='范围已保存，后台正在同步；请稍后在手机刷新。';}catch(e){status.textContent=e.message;button.disabled=false;}};
  }catch(e){status.textContent=e.message;}
 }};
 async function open(){const match=location.hash.match(/^#mobile\/learn\/(lesson-[a-z0-9-]{1,70})$/);if(!match)return;
  try{await window.Account?.ready;const target=await api('/source/'+match[1]);window.actionContentOrigin=null;if(target.kind==='plan')await window.openPlanCourse(target.plan_id,target.lesson_no);else{await window.loadDailyLearning();await window.openStudyCourse(target.module_id,target.filename);}}
  catch(e){if(typeof toast==='function')toast(e.message);else alert(e.message);}
 }
 window.addEventListener('load',open);window.addEventListener('hashchange',open);
})();
