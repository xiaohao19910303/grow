/* Account-local action recovery. This is a draft copy, not a site backup. */
(() => {
  'use strict';
  const node=(tag,text)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;return el;};
  function download(client){
    const blob=new Blob([JSON.stringify(client.exportRecovery(),null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=node('a');
    a.href=url;a.download='grow-action-drafts-'+new Date().toISOString().slice(0,10)+'.json';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  window.ActionRecovery={attach(client,parent){
    const panel=node('section');panel.className='action-recovery action-recovery-warning';const text=node('p');text.setAttribute('role','status');panel.append(text);
    const save=node('button','下载行动草稿副本');save.type='button';save.className='btn';save.onclick=()=>download(client);panel.append(save);parent.append(panel);
    function render(){const status=client.storageStatus();panel.hidden=status.durable;text.textContent=status.reason==='quota'?'浏览器空间不足，当前输入可能只保留在本页；刷新或关闭前请下载副本。':'浏览器无法保存，当前输入可能只保留在本页；刷新或关闭前请下载副本。';}
    render();const unsubscribe=client.subscribe(render);parent.closest('dialog')?.addEventListener('close',unsubscribe,{once:true});return unsubscribe;
  },mount(client){
    document.getElementById('actionRecovery')?.remove();
    const panel=node('aside');panel.id='actionRecovery';panel.className='action-recovery';panel.setAttribute('aria-label','行动草稿保存与恢复');
    const warning=node('p');warning.setAttribute('role','status');warning.setAttribute('aria-live','polite');panel.append(warning);
    const details=node('details'),summary=node('summary','行动草稿副本与恢复');details.append(summary);panel.append(details);
    details.append(node('p','副本只包含当前账号的行动编辑草稿与待确认请求，保留原提交编号；不含全站数据、设备标识、AI 配置、复盘输入和模板表单。副本含个人填写，请妥善保管。'));
    const actions=node('div');actions.className='action-buttons';details.append(actions);
    const feedback=node('p');feedback.setAttribute('role','status');details.append(feedback);
    function button(label,run){const b=node('button',label);b.type='button';b.className='btn';b.onclick=async()=>{b.disabled=true;try{await run();}catch(error){feedback.textContent=error.message;}finally{b.disabled=false;}};actions.append(b);return b;}
    button('下载行动草稿副本',()=>{
      download(client);
      feedback.textContent='已生成当前账号的行动草稿副本。若浏览器仍无法保存，请在刷新后导入此文件；待确认请求会沿用原编号。';
    });
    const file=node('input');file.type='file';file.accept='.json,application/json';file.hidden=true;file.setAttribute('aria-label','选择行动草稿副本');details.append(file);
    button('导入行动草稿副本',()=>{file.value='';file.click();});
    file.onchange=async()=>{try{
      const selected=file.files[0];if(!selected)return;if(selected.size>1048576)throw Error('行动草稿副本不能超过 1 MiB。');
      let bundle;try{bundle=JSON.parse(await selected.text());}catch{throw Error('行动草稿副本不是有效的 JSON 文件。');}
      const result=client.importRecovery(bundle);feedback.textContent=`已恢复行动草稿和待确认请求（${result.imported} 项）。请关闭当前编辑窗口，再从原入口打开并核对；导入不会提交到服务端。`;
      window.dispatchEvent(new CustomEvent('action-recovery:imported'));
    }catch(error){feedback.textContent=error.message;}};
    const retry=button('重新尝试浏览器保存',()=>{const status=client.retryStorage();feedback.textContent=status.durable?'当前页草稿已保存到浏览器。':'浏览器仍无法保存，请下载行动草稿副本后再离开。';});
    function render(){const status=client.storageStatus();panel.classList.toggle('action-recovery-warning',!status.durable);warning.hidden=status.durable;retry.hidden=status.durable;
      warning.textContent=status.reason==='quota'?'浏览器空间不足：行动草稿或待确认请求可能只保留在当前页面，刷新前请下载副本。':'浏览器存储不可用：行动草稿或待确认请求可能只保留在当前页面，刷新前请下载副本。';
    }
    const unsubscribe=client.subscribe(render);render();document.querySelector('.topbar').after(panel);
    const beforeLeave=event=>{if(client.storageStatus().unsaved){event.preventDefault();event.returnValue='';}};
    window.addEventListener('beforeunload',beforeLeave);
    return ()=>{unsubscribe();window.removeEventListener('beforeunload',beforeLeave);panel.remove();};
  }};
})();
