/* Private resume location: restoring or scrolling never marks an article read. */
(() => {
  'use strict';
  let active=null;
  function mount(body,id,isCurrent){
    active?.close();let revision=0,last=-1,timer=null,ready=false,saving=false,queued=null,closed=false;
    const status=document.createElement('p');status.className='desc reading-position-status';status.setAttribute('role','status');body.before(status);
    const path='/api/reading/articles/'+encodeURIComponent(id)+'/position';
    async function request(data){const response=await fetch(path,{method:data?'POST':'GET',cache:'no-store',keepalive:!!data,headers:data?{'Content-Type':'application/json','X-Copilot-Request':'1'}:{},body:data?JSON.stringify({data}):undefined});const result=await response.json();if(!response.ok)throw Error(result.message||'阅读位置暂未保存，可稍后重试。');return result;}
    function ratio(){const top=body.getBoundingClientRect().top+window.scrollY;return Math.max(0,Math.min(1,(window.scrollY-top)/Math.max(1,body.scrollHeight-window.innerHeight)));}
    async function save(){
      clearTimeout(timer);if(!ready||(!closed&&!isCurrent()))return;
      const value=queued??ratio();queued=null;if(Math.abs(value-last)<.002)return;
      if(saving){queued=value;return;}saving=true;
      try{const saved=await request({ratio:value,revision});revision=saved.revision;last=value;if(!closed)status.textContent='阅读位置已保存';}
      catch(error){ready=false;if(!closed){status.textContent=error.message;const retry=document.createElement('button');retry.type='button';retry.className='btn';retry.textContent='重试保存位置';retry.onclick=async()=>{try{const latest=await request();revision=latest.revision;ready=true;await save();}catch(e){status.firstChild.textContent=e.message;}};status.append(retry);}}
      finally{saving=false;if(queued!==null&&!closed)save();}
    }
    function scroll(){if(ready&&isCurrent()){clearTimeout(timer);timer=setTimeout(save,700);}}
    const close=()=>{if(closed)return;queued=ready&&isCurrent()?ratio():queued;closed=true;clearTimeout(timer);if(queued!==null)save();window.removeEventListener('scroll',scroll);window.removeEventListener('pagehide',close);};
    active={close};window.addEventListener('scroll',scroll,{passive:true});window.addEventListener('pagehide',close);
    request().then(saved=>{if(closed||!isCurrent())return;revision=saved.revision;last=saved.ratio;ready=true;
      if(saved.ratio>0){const top=body.getBoundingClientRect().top+window.scrollY;window.scrollTo({top:top+saved.ratio*Math.max(1,body.scrollHeight-window.innerHeight),behavior:'instant'});status.textContent='已回到上次阅读位置';}
    }).catch(()=>{if(!closed)status.textContent='阅读位置暂未载入，原文仍可继续阅读。';});
    return {close};
  }
  window.ReadingPosition={mount,close:()=>{active?.close();active=null;}};
})();
