/* One read-only fact, shared across Today/Growth and the foreground reminder loop. */
(() => {
  'use strict';
  const cards=['coachFactToday','coachFactOverview'].map(id=>document.getElementById(id)).filter(Boolean);
  const destinations={record_decrease:'learning-history',course_gap:'learning-history',predictions:'predictions',streak:'learning-history',activity:'learning-history',empty:'library'};
  let accountId, data=null, error='', pending=null, queued=false, taskDue=false, attemptDay='', attempted=0, dismissed='';
  const active=()=>!!accountId&&window.Account?.user?.id===accountId;
  const day=()=>window.ActionPlans?.day('Asia/Shanghai')||new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai'}).format(new Date());
  const key=()=>`zhixing-coach-facts-v1:${accountId}`;
  function hiddenToday(){try{return (window.localStorage.getItem(key())||dismissed)===day();}catch{return dismissed===day();}}
  const node=(tag,text,cls)=>{const element=document.createElement(tag);if(text!==undefined)element.textContent=text;if(cls)element.className=cls;return element;};
  function button(parent,label,run){const element=node('button',label,'btn');element.type='button';element.onclick=run;parent.append(element);}
  function render(){
    if(!active()){for(const card of cards){card.hidden=true;card.replaceChildren();card.dataset.signature='';}return;}
    const current=data?.date===day()?data:null;
    for(const card of cards){
      card.hidden=taskDue||hiddenToday();
      const signature=JSON.stringify([current,error]);
      if(card.dataset.signature===signature)continue;
      card.dataset.signature=signature;card.replaceChildren(node('h2','教练今日提醒'));
      if(error){card.append(node('p','教练事实暂未读取，可稍后重试。','desc'));button(card,'重试',()=>refresh(true));continue;}
      if(!current){card.append(node('p','正在读取已保存的记录…','desc'));continue;}
      const fact=current.fact;
      card.append(node('p',fact.message),node('p',`依据：${fact.start} 至 ${fact.end}（北京时间） · ${fact.source}`,'desc'),node('p',fact.basis,'desc'));
      const actions=node('div',undefined,'action-buttons');card.append(actions);
      button(actions,fact.kind==='empty'?'选择学习内容':'查看记录',()=>window.goTab(destinations[fact.kind]));
      button(actions,'今天先不显示',dismiss);
    }
  }
  function dismiss(){
    if(!active())return;
    const current=cards.find(card=>card.contains?.(document.activeElement));
    dismissed=day();try{window.localStorage.setItem(key(),dismissed);}catch{/* Current-page dismissal still works. */}
    render();
    const next=current?.nextElementSibling;
    if(next){const target=next.querySelector('button,summary,a')||next;if(target===next)target.tabIndex=-1;target.focus();}
  }
  function validate(result){
    const fact=result?.fact;
    if(result?.date!==day()||result.timezone!=='Asia/Shanghai'||result.uses_model!==false||
       (result.account_id!=null&&result.account_id!==accountId)||!fact||!Object.hasOwn(destinations,fact.kind)||
       !['message','basis','source','start','end'].every(field=>typeof fact[field]==='string'))throw Error('Invalid fact response');
    return result;
  }
  async function refresh(force=false){
    await ready;
    if(!active()){render();return;}
    if(force)attemptDay='';
    if(document.hidden||taskDue||hiddenToday()){render();return;}
    if(pending){queued||=force;return pending;}
    if(!force&&attemptDay===day()&&Date.now()-attempted<300000){render();return;}
    attempted=Date.now();attemptDay=day();
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),10000);
    pending=(async()=>{
      try{
        const response=await window.fetch('/api/coach-facts',{cache:'no-store',signal:controller.signal});
        if(!response.ok)throw Error('Fact read failed');
        const next=await response.json();
        if(active()){data=validate(next);error='';}
      }catch{if(active()){data=null;error='unavailable';}}
      finally{clearTimeout(timeout);pending=null;render();}
      if(queued){queued=false;return refresh(true);}
    })();
    return pending;
  }
  async function tick(due){taskDue=!!due;render();if(!document.hidden&&!taskDue)return refresh();}
  const ready=(window.Account?.ready||Promise.reject(Error('Login required'))).then(user=>{accountId=user.id;});
  window.CoachFacts={refresh,tick,invalidate:()=>{attemptDay='';}};
  window.addEventListener('storage',event=>{if(active()&&event.key===key()){dismissed=event.newValue||'';render();}});
  ready.then(()=>refresh()).catch(()=>{for(const card of cards)card.hidden=true;});
})();
